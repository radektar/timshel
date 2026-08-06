"""LLM-based tag generator implementations."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any, Iterable, List, Optional

from src.config import config
from src.llm.client import build_anthropic_client
from src.llm.model_router import resolve_model
from src.logger import logger
from src.summarizer import APIBillingError, _is_permanent_api_error, detect_language
from src.tag_index import TagIndex


class BaseTagger(ABC):
    """Abstract interface for transcript taggers."""

    @abstractmethod
    def generate_tags(
        self,
        transcript: str,
        summary_markdown: str,
        existing_tags: Iterable[str],
        known_entities: str = "",
    ) -> List[str]:
        """Generate tags for given transcript and summary.

        Args:
            transcript: full transcription text (snippets are taken from it).
            summary_markdown: the generated, already-canonicalised summary.
            existing_tags: tags already present in the vault, most-used first
                (see :meth:`src.tag_index.TagIndex.existing_tags_ranked`).
            known_entities: canonical glossary lines offered as tag candidates
                (see :meth:`src.vocabulary.VocabularyIndex.canonical_terms_block`);
                "" disables the block.
        """
        raise NotImplementedError


class ClaudeTagger(BaseTagger):
    """Anthropic Claude based tagger implementation."""

    def __init__(self, api_key: str, model: str) -> None:
        """Initialize Claude client."""
        self.client = build_anthropic_client(api_key)
        self.model = model
        # Token usage of the LAST call, for the per-note cost ledger.
        self.last_usage: Any = None

    def generate_tags(
        self,
        transcript: str,
        summary_markdown: str,
        existing_tags: Iterable[str],
        known_entities: str = "",
    ) -> List[str]:
        """Generate tags using Claude API."""
        # Cleared up front: see ClaudeSummarizer.generate — a call that never
        # reaches the API must not leave the previous note's usage behind.
        self.last_usage = None
        if not config.ENABLE_LLM_TAGGING:
            logger.debug("LLM tagging disabled; skipping tag generation.")
            return []

        summary_snippet = self._truncate(
            summary_markdown, config.MAX_TAGGER_SUMMARY_CHARS
        )
        transcript_snippet = self._build_transcript_snippet(
            transcript,
            config.MAX_TAGGER_TRANSCRIPT_CHARS,
        )
        prepared_existing = self._prepare_existing_tags(existing_tags)
        prompt = self._build_prompt(
            summary_snippet,
            transcript_snippet,
            prepared_existing,
            known_entities,
        )

        try:
            logger.debug(
                "Calling Claude API for tag generation (model: %s)", self.model
            )
            # Low temperature: tag choice is near-mechanical (name what is
            # there, reuse an existing tag when it fits). Reasoning models
            # (any Opus) reject `temperature` — omit it there, as in the
            # summarizer.
            extra = {}
            if not self.model.startswith("claude-opus-"):
                extra["temperature"] = 0.2
            message = self.client.messages.create(
                model=self.model,
                # 256: multi-word entity tags plus JSON overhead clipped at 128
                # once the prompt started asking for proper names. Billed on
                # actual output, so the headroom is free.
                max_tokens=256,
                # 30s: the prompt now carries the glossary; a timeout means the
                # note silently ships with no tags at all.
                timeout=30.0,
                messages=[
                    {
                        "role": "user",
                        "content": prompt,
                    }
                ],
                **extra,
            )
            self.last_usage = getattr(message, "usage", None)
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
        known_entities: str = "",
    ) -> str:
        """Construct concise prompt for Claude.

        Tags are not decoration: they are one of only three signals the digest
        gets per note (tags, the Stanowiska section, the summary text), and
        connection scoring only counts a tag that recurs across notes. So the
        prompt optimises for two things — naming the concrete entities the
        recording is about, and reusing an existing tag whenever it honestly
        fits.
        """
        existing_line = ", ".join(existing_tags)
        max_tags = config.MAX_TAGS_PER_NOTE

        # Name the tag language explicitly (same reasoning as the summarizer's
        # language directive): the instruction block is Polish, so a model left
        # to infer would tag an English recording in Polish.
        lang = detect_language(f"{summary_snippet}\n{transcript_snippet}")
        tag_language = "angielski" if lang == "en" else "polski"

        entities_block = ""
        if known_entities:
            entities_block = (
                "ZNANE ENCJE — nazwy potwierdzone w tym vaultcie, kandydaci na "
                "tagi. Użyj TYLKO tych, o których to nagranie faktycznie mówi; "
                "nie taguj z listy na siłę:\n"
                f"{known_entities}\n\n"
            )

        return (
            "Na podstawie podsumowania (markdown) oraz fragmentów transkrypcji "
            f"wygeneruj od 1 do {max_tags} tagów nazywających, o CZYM naprawdę "
            "jest to nagranie.\n\n"
            "ZASADA NADRZĘDNA — konkret bije ogólnik. Priorytet:\n"
            "1. nazwy własne faktycznie omawiane w nagraniu (osoby, organizacje, "
            "projekty, produkty, miejsca) — nazwy wielowyrazowe są dozwolone "
            "i pożądane, np. 'Tech to the Rescue';\n"
            "2. konkretne tematy tego nagrania;\n"
            "3. najwyżej JEDEN szeroki tag dziedzinowy.\n\n"
            "CZEGO NIE ROBIĆ:\n"
            "- żadnych rzeczowników odczasownikowych opisujących czynność w "
            "ogóle: 'planowanie strategii rozwoju', 'mapowanie procesu', "
            "'konfiguracja narzędzia', 'omówienie tematu'. Taki tag pasuje do "
            "każdego nagrania, więc nie łączy niczego z niczym. Wyjątek: proces, "
            "który sam jest nazwanym, powracającym tematem;\n"
            "- nie taguj rzeczy, których w nagraniu nie ma.\n\n"
            "PONOWNE UŻYCIE: tag jest użyteczny tylko wtedy, gdy POWTARZA się "
            "między notatkami. Jeśli któryś z istniejących tagów uczciwie opisuje "
            "to nagranie, użyj go DOKŁADNIE w tej formie (nawet jeśli jest w innym "
            "języku niż nagranie). Nowy tag twórz dla konkretnej encji lub tematu, "
            "który prawdopodobnie wróci w kolejnych nagraniach.\n\n"
            "FORMA:\n"
            f"- język {tag_language};\n"
            "- mianownik, małe litery (nazwy własne też);\n"
            "- krótko: pojedyncze słowo albo nazwa własna;\n"
            "- bez znaków specjalnych (#, przecinki itp.).\n\n"
            f"{entities_block}"
            "ISTNIEJĄCE TAGI (najczęstsze w vaultcie):\n"
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
        return ClaudeTagger(api_key=config.LLM_API_KEY, model=resolve_model("tags"))
    except ImportError:
        logger.error(
            "anthropic package not installed. Install via `pip install anthropic`."
        )
        return None
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to initialize ClaudeTagger: %s", exc)
        return None
