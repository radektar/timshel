"""LLM-based tag generator implementations."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Iterable, List, Optional

from src.config import config
from src.llm.client import build_anthropic_client
from src.logger import logger
from src.summarizer import APIBillingError, _is_permanent_api_error
from src.tag_index import TagIndex


class BaseTagger(ABC):
    """Abstract interface for transcript taggers."""

    @abstractmethod
    def generate_tags(
        self,
        transcript: str,
        summary_markdown: str,
        existing_tags: Iterable[str],
    ) -> List[str]:
        """Generate tags for given transcript and summary."""
        raise NotImplementedError


class ClaudeTagger(BaseTagger):
    """Anthropic Claude based tagger implementation."""

    def __init__(self, api_key: str, model: str) -> None:
        """Initialize Claude client."""
        self.client = build_anthropic_client(api_key)
        self.model = model

    def generate_tags(
        self,
        transcript: str,
        summary_markdown: str,
        existing_tags: Iterable[str],
    ) -> List[str]:
        """Generate tags using Claude API."""
        if not config.ENABLE_LLM_TAGGING:
            logger.debug("LLM tagging disabled; skipping tag generation.")
            return []

        summary_snippet = self._truncate(summary_markdown, config.MAX_TAGGER_SUMMARY_CHARS)
        transcript_snippet = self._build_transcript_snippet(
            transcript,
            config.MAX_TAGGER_TRANSCRIPT_CHARS,
        )
        prepared_existing = self._prepare_existing_tags(existing_tags)
        prompt = self._build_prompt(
            summary_snippet,
            transcript_snippet,
            prepared_existing,
        )

        try:
            logger.debug("Calling Claude API for tag generation (model: %s)", self.model)
            message = self.client.messages.create(
                model=self.model,
                max_tokens=128,
                timeout=10.0,
                messages=[
                    {
                        "role": "user",
                        "content": prompt,
                    }
                ],
            )
            response_text = message.content[0].text if message.content else ""
            return self._parse_tags_response(response_text)
        except Exception as exc:  # noqa: BLE001
            reason = _is_permanent_api_error(exc)
            if reason:
                logger.critical(
                    "❌ Claude API permanent error (tagger, reason=%s): %s",
                    reason,
                    exc,
                )
                raise APIBillingError(str(exc)) from exc
            logger.error("ClaudeTagger API error: %s", exc, exc_info=True)
            return []

    @staticmethod
    def _truncate(text: str, max_chars: int) -> str:
        """Truncate text to fit within max_chars."""
        if len(text) <= max_chars:
            return text
        return text[: max_chars - 3] + "..."

    def _build_transcript_snippet(self, transcript: str, max_chars: int) -> str:
        """Take start and end fragments to keep context small."""
        if not transcript:
            return ""
        if len(transcript) <= max_chars * 2:
            return transcript
        head = transcript[:max_chars]
        tail = transcript[-max_chars:]
        return f"{head}\n...\n{tail}"

    def _prepare_existing_tags(self, existing_tags: Iterable[str]) -> List[str]:
        """Normalize and limit existing tags before sending to model."""
        unique_map: dict[str, str] = {}
        for tag in existing_tags:
            stripped = tag.strip()
            if not stripped:
                continue
            sanitized = TagIndex.sanitize_tag_value(stripped)
            if not sanitized:
                continue
            normalized = sanitized
            if normalized not in unique_map:
                unique_map[normalized] = sanitized

        limited = list(unique_map.values())[: config.MAX_EXISTING_TAGS_IN_PROMPT]
        return limited

    def _build_prompt(
        self,
        summary_snippet: str,
        transcript_snippet: str,
        existing_tags: List[str],
    ) -> str:
        """Construct concise prompt for Claude."""
        existing_line = ", ".join(existing_tags)
        max_tags = config.MAX_TAGS_PER_NOTE

        return (
            "Na podstawie podsumowania (markdown) oraz krótkich fragmentów "
            "transkrypcji wygeneruj od 1 do "
            f"{max_tags} tagów opisujących główne tematy nagrania.\n\n"
            "ZASADY:\n"
            "- język polski;\n"
            "- forma: rzeczowniki w mianowniku, maks. 2 słowa, małe litery;\n"
            "- bez znaków specjalnych (#, przecinki itp.);\n"
            "- jeżeli nowy tag jest bliskoznaczny istniejącego, użyj dokładnie "
            "istniejącego tagu (np. jeśli jest 'sauna', nie twórz 'saunowanie').\n\n"
            "ISTNIEJĄCE_TAGI:\n"
            f"{existing_line}\n\n"
            "PODSUMOWANIE (MARKDOWN):\n"
            f"{summary_snippet}\n\n"
            "FRAGMENTY TRANSKRYPCJI:\n"
            f"{transcript_snippet}\n\n"
            "Odpowiedz WYŁĄCZNIE w formacie JSON (lista stringów):\n"
            '["tag1", "tag2"]\n'
        )

    def _parse_tags_response(self, response_text: str) -> List[str]:
        """Parse JSON array from Claude response."""
        text = response_text.strip()
        if not text:
            return []

        start = text.find("[")
        end = text.rfind("]")
        if start == -1 or end == -1 or end <= start:
            logger.warning("ClaudeTagger response missing JSON array.")
            return []

        fragment = text[start : end + 1]
        try:
            data = json.loads(fragment)
        except json.JSONDecodeError:
            logger.warning("Failed to parse JSON with tags.")
            return []

        if not isinstance(data, list):
            return []

        unique: List[str] = []
        seen = set()
        for item in data:
            if not isinstance(item, str):
                continue
            candidate = item.strip()
            if not candidate:
                continue
            sanitized = TagIndex.sanitize_tag_value(candidate)
            if not sanitized:
                continue
            normalized = sanitized
            if normalized in seen:
                continue
            seen.add(normalized)
            unique.append(sanitized)
            if len(unique) >= config.MAX_TAGS_PER_NOTE:
                break

        return unique


def get_tagger() -> Optional[BaseTagger]:
    """Factory returning tagger instance based on configuration."""
    # Tier gating removed: smart tags are available to everyone. Availability is
    # decided purely by config (an API key / enabled provider), not by license.
    if not config.ENABLE_LLM_TAGGING:
        logger.debug("LLM tagging disabled in config.")
        return None

    if config.LLM_PROVIDER != "claude":
        logger.warning(
            "Tagger currently available only for provider 'claude', got %s",
            config.LLM_PROVIDER,
        )
        return None

    if not config.LLM_API_KEY:
        logger.warning("Claude API key missing; disabling tagger.")
        return None

    try:
        return ClaudeTagger(api_key=config.LLM_API_KEY, model=config.LLM_MODEL)
    except ImportError:
        logger.error(
            "anthropic package not installed. Install via `pip install anthropic`."
        )
        return None
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to initialize ClaudeTagger: %s", exc)
        return None

