"""AI-powered summarization for transcripts."""

import re
import time
from abc import ABC, abstractmethod
from typing import Dict, Optional, Tuple

from src.config import config
from src.logger import logger

Anthropic = None  # type: ignore[assignment]


# --------------------------------------------------------------------------- #
# Output-language detection.
#
# Claude (esp. Haiku) has a strong prior toward the language of its long
# instruction block, so "respond in the transcript's language" alone is flaky
# (~60% on English input). Detecting the language in code and naming it
# explicitly in the prompt ("Write the ENTIRE response in ENGLISH") makes the
# output language deterministic. The app's content languages are Polish and
# English (see ``SUPPORTED_LANGUAGES``); anything else falls back to the
# generic in-prompt rule.
# --------------------------------------------------------------------------- #

_PL_DIACRITICS = set("ąćęłńóśźżĄĆĘŁŃÓŚŹŻ")
_PL_STOPWORDS = {
    "się", "że", "jest", "oraz", "jako", "dla", "nie", "tak", "czy", "już",
    "albo", "ale", "być", "ma", "to", "na", "do", "po", "od", "przy", "który",
}
_EN_STOPWORDS = {
    "the", "and", "to", "of", "is", "for", "we", "in", "on", "that", "this",
    "with", "will", "by", "an", "it", "at", "as", "be", "are", "our", "have",
}


def detect_language(text: str) -> Optional[str]:
    """Best-effort ``"pl"``/``"en"`` detection for the summary's output language.

    Returns ``None`` when neither language is a clear winner, so the caller can
    fall back to the generic "respond in the transcript's language" instruction.
    """
    if not text or not text.strip():
        return None
    if any(ch in _PL_DIACRITICS for ch in text):
        return "pl"
    words = re.findall(r"[a-ząćęłńóśźż]+", text.lower())
    if not words:
        return None
    pl_hits = sum(w in _PL_STOPWORDS for w in words)
    en_hits = sum(w in _EN_STOPWORDS for w in words)
    if en_hits > pl_hits:
        return "en"
    if pl_hits > en_hits:
        return "pl"
    return None


class APIBillingError(Exception):
    """Claude API credit_balance exhausted (HTTP 400 invalid_request_error)."""


def _is_permanent_api_error(exc: BaseException) -> str | None:
    """Return error reason string when *exc* is a permanent Anthropic API error, else None."""
    status = getattr(exc, "status_code", None)
    message = str(getattr(exc, "message", exc)).lower()
    exc_str = str(exc).lower()
    if status == 400 and ("credit balance" in message or "credit balance is too low" in exc_str):
        return "billing"
    if status == 404 and ("model" in message or "not_found" in exc_str):
        return "model_not_found"
    return None


def _is_credit_balance_error(exc: BaseException) -> bool:
    """Return True when *exc* is an Anthropic 400 credit_balance error."""
    return _is_permanent_api_error(exc) == "billing"


class BaseSummarizer(ABC):
    """Base class for transcript summarizers.
    
    Provides interface for generating summaries and titles from transcripts.
    All summarizer implementations should inherit from this class.
    """
    
    @abstractmethod
    def generate(self, transcript: str) -> Dict[str, str]:
        """Generate summary and title from transcript.
        
        Args:
            transcript: Full transcription text
            
        Returns:
            Dict with 'title' and 'summary' keys
            
        Raises:
            Exception: If summarization fails
        """
        pass


class ClaudeSummarizer(BaseSummarizer):
    """Claude API-based summarizer.
    
    Uses Anthropic's Claude API to generate summaries and titles
    from transcriptions in Polish.
    """
    
    def __init__(self, api_key: str, model: str = "claude-3-haiku-20240307"):
        """Initialize Claude summarizer.
        
        Args:
            api_key: Anthropic API key
            model: Claude model name
        """
        global Anthropic
        try:
            from anthropic import Anthropic as AnthropicClient
        except ImportError:
            raise ImportError(
                "anthropic package not installed. "
                "Install with: pip install anthropic"
            )
        if Anthropic is None:
            Anthropic = AnthropicClient
        
        self.client = Anthropic(api_key=api_key)
        self.model = model
        self.max_words = config.SUMMARY_MAX_WORDS
        self.title_max_length = config.TITLE_MAX_LENGTH
    
    def generate(self, transcript: str) -> Dict[str, str]:
        """Generate summary and title from transcript using Claude API.
        
        Args:
            transcript: Full transcription text
            
        Returns:
            Dict with 'title' and 'summary' keys
            
        Raises:
            Exception: If API call fails
        """
        if not transcript or not transcript.strip():
            logger.warning("Empty transcript provided, using fallback")
            return self._fallback_summary()
        
        # Truncate transcript if too long (Claude has token limits)
        # Keep last 10000 characters to preserve context
        max_transcript_length = 10000
        if len(transcript) > max_transcript_length:
            logger.debug(
                f"Transcript too long ({len(transcript)} chars), "
                f"truncating to last {max_transcript_length} chars"
            )
            transcript = transcript[-max_transcript_length:]
        
        prompt = self._build_prompt(transcript)
        
        try:
            logger.debug(f"Calling Claude API (model: {self.model})")
            start_time = time.time()
            
            message = self.client.messages.create(
                model=self.model,
                max_tokens=1024,
                timeout=30.0,  # 30 second timeout
                messages=[
                    {
                        "role": "user",
                        "content": prompt
                    }
                ]
            )
            
            elapsed = time.time() - start_time
            logger.debug(f"Claude API call completed in {elapsed:.2f}s")
            
            # Extract response
            response_text = message.content[0].text if message.content else ""
            
            # Parse response (expects format: TITLE: ...\n\nSUMMARY: ...)
            title, summary = self._parse_response(response_text)
            
            # Ensure title is within limits
            if len(title) > self.title_max_length:
                title = title[:self.title_max_length - 3] + "..."
            
            return {
                "title": title.strip(),
                "summary": summary.strip()
            }
            
        except Exception as e:
            reason = _is_permanent_api_error(e)
            if reason:
                logger.critical(
                    "❌ Claude API permanent error (summarizer, reason=%s): %s",
                    reason,
                    e,
                )
                raise APIBillingError(str(e)) from e
            logger.error(f"Claude API error: {e}", exc_info=True)
            logger.warning("Falling back to simple title generation")
            return self._fallback_summary(transcript)
    
    def _build_prompt(self, transcript: str) -> str:
        """Build prompt for Claude API.
        
        Args:
            transcript: Transcription text
            
        Returns:
            Formatted prompt string
        """
        lang = detect_language(transcript)
        if lang == "en":
            lang_directive = (
                "WRITE THE ENTIRE RESPONSE IN ENGLISH — the title, every section "
                "heading, and all body text. Do not use any other language.\n\n"
            )
        elif lang == "pl":
            lang_directive = (
                "NAPISZ CAŁĄ ODPOWIEDŹ PO POLSKU — tytuł, wszystkie nagłówki sekcji "
                "i całą treść. Nie używaj żadnego innego języka.\n\n"
            )
        else:
            lang_directive = ""

        return f"""{lang_directive}Analyse the audio transcript below and produce concise, well-structured notes.

OUTPUT LANGUAGE — most important: Write the ENTIRE response — the title, EVERY
section heading, and ALL body text — in the SAME language as the transcript. If the
transcript is in English, respond fully in English; if in Polish, respond in Polish;
and so on. The example headings below are in English ONLY as a layout guide —
translate every heading into the transcript's own language. Never mix or switch
languages, and never default to a language other than the transcript's.

GROUNDING — equally important: Base everything ONLY on what is actually said in the
transcript. Do not invent tasks, deadlines, names, numbers, decisions or conclusions
that are not there. No editorialising such as "the project will succeed if…". If
there is little to report, write less or omit a section — fewer true points beat a
padded, invented template. Never add content just to fill the structure.

Produce:

1. A SHORT TITLE (max {self.title_max_length} characters) — concise and descriptive, in the transcript's language.

2. A SUMMARY in markdown with these sections (translate the headings):

   ## Summary
   - As many sentences as the content truly supports (a short recording → a short summary; do not stretch it)
   - **Bold** the key concepts, decisions and commitments; *italics* for context that is actually present

   ## Key points
   - Bullets grouped by priority, only those genuinely present in the recording:
     - ⚠️ **Critical:** decisions, commitments, deadlines stated directly
     - ⚡ **Important:** significant topics needing follow-up
     - 📝 **Info:** context, background
   - Skip a tier entirely if nothing fits it. Do not manufacture points.

   ## Quotes
   - 0–5 VERBATIM fragments from the transcript (not paraphrases), grouped by topic
   - Each topic under a level-3 heading (###); format:
     > "Exact quote from the transcript"
     > — *Context: [short note on the situation]*
   - A quote MUST appear literally in the transcript. If there are no clear quotes, give fewer or omit the section.

   ## Action items
   - Only tasks that genuinely follow from the transcript (there may be fewer than 3, or zero)
   - Each as `- [ ]`, starting with a verb. Do not invent tasks "for completeness".

MARKDOWN STYLE:
- Use **bold**, *italics*, `inline code`, blockquotes (`>`), lists and separators (`---`) where they aid readability
- Use the emoji (⚠️ ⚡ 📝) consistently for priorities in "Key points"

Reply ONLY in this format (keep the labels TITLE and SUMMARY in English — do not translate them):
TITLE: [title in the transcript's language]
SUMMARY: [markdown summary; section headings in the transcript's language]

REMINDER: respond ENTIRELY in the transcript's own language (title, headings, body).

Transcript:
{transcript}"""
    
    def _parse_response(self, response_text: str) -> Tuple[str, str]:
        """Parse Claude API response.
        
        Args:
            response_text: Raw response from API
            
        Returns:
            Tuple of (title, summary) where summary contains markdown formatting
        """
        title = ""
        summary_lines = []
        
        lines = response_text.split("\n")
        current_section = None
        
        for line in lines:
            stripped_line = line.strip()
            if stripped_line.startswith("TITLE:"):
                title = stripped_line.replace("TITLE:", "").strip()
                current_section = "title"
            elif stripped_line.startswith("SUMMARY:"):
                # Start collecting summary, preserve the line after SUMMARY:
                summary_content = stripped_line.replace("SUMMARY:", "").strip()
                if summary_content:
                    summary_lines.append(summary_content)
                current_section = "summary"
            elif current_section == "summary":
                # Preserve markdown formatting - keep empty lines and indentation
                if stripped_line or summary_lines:  # Include empty lines for markdown spacing
                    summary_lines.append(line)
        
        summary = "\n".join(summary_lines).strip()
        
        # Fallback if parsing failed
        if not title or not summary:
            # Try to extract first line as title, rest as summary
            parts = response_text.split("\n\n", 1)
            if len(parts) >= 2:
                title = parts[0].strip()[:self.title_max_length]
                summary = parts[1].strip()
                # Ensure summary has markdown structure if missing
                if not summary.startswith("##"):
                    summary = f"## Podsumowanie\n\n{summary[:self.max_words * 6]}"
            elif parts:
                title = parts[0].strip()[:self.title_max_length]
                summary = f"## Podsumowanie\n\n{parts[0].strip()[:self.max_words * 6]}"
        
        # Ensure summary has basic markdown structure if completely missing
        if not summary or summary == "Brak podsumowania":
            summary = """## Podsumowanie

Brak podsumowania.

## Kluczowe punkty

⚠️ **Krytyczne:**
- Przejrzeć transkrypcję ręcznie

⚡ **Ważne:**
- Wyciągnąć kluczowe wnioski ze spotkania

📝 **Informacyjne:**
- Sprawdzić pełną transkrypcję poniżej

## Cytaty

*Brak cytatów - wymagana ręczna analiza transkrypcji*

## Lista działań (To-do)

- Przejrzeć transkrypcję ręcznie"""
        
        return title or "Nagranie", summary
    
    def _fallback_summary(self, transcript: Optional[str] = None) -> Dict[str, str]:
        """Generate fallback summary when API fails.
        
        Args:
            transcript: Optional transcript text for basic extraction
            
        Returns:
            Dict with basic title and summary in markdown format
        """
        if transcript:
            # Extract first sentence or first 50 chars as title
            first_line = transcript.split("\n")[0].strip()
            title = first_line[:self.title_max_length] if first_line else "Nagranie"
            # Use first 200 chars as summary with markdown structure
            summary_text = transcript[:200].strip() + "..."
            summary = f"""## Podsumowanie

{summary_text}

## Kluczowe punkty

⚠️ **Krytyczne:**
- Przejrzeć transkrypcję i wyciągnąć kluczowe wnioski

⚡ **Ważne:**
- Zidentyfikować następne kroki do wykonania

📝 **Informacyjne:**
- Przeanalizować pełną transkrypcję poniżej

## Cytaty

*Brak cytatów - wymagana ręczna analiza transkrypcji*

## Lista działań (To-do)

- Przejrzeć transkrypcję i wyciągnąć kluczowe wnioski
- Zidentyfikować następne kroki do wykonania"""
        else:
            title = "Nagranie"
            summary = """## Podsumowanie

Nie udało się wygenerować podsumowania.

## Kluczowe punkty

⚠️ **Krytyczne:**
- Przejrzeć transkrypcję ręcznie

⚡ **Ważne:**
- Wyciągnąć kluczowe wnioski ze spotkania

📝 **Informacyjne:**
- Sprawdzić pełną transkrypcję poniżej

## Cytaty

*Brak cytatów - wymagana ręczna analiza transkrypcji*

## Lista działań (To-do)

- Przejrzeć transkrypcję ręcznie
- Wyciągnąć kluczowe wnioski ze spotkania"""
        
        return {
            "title": title,
            "summary": summary
        }


def get_summarizer() -> Optional[BaseSummarizer]:
    """Factory function to create appropriate summarizer instance.
    
    Returns:
        Summarizer instance or None if summarization is disabled/unavailable
    """
    # Tier gating removed: summaries are available to everyone. Availability is
    # decided purely by config (an API key / enabled provider), not by license.
    if not config.ENABLE_SUMMARIZATION:
        logger.debug("Summarization disabled in config")
        return None
    
    if config.LLM_PROVIDER == "claude":
        if not config.LLM_API_KEY:
            logger.warning("Claude API key not found, summarization disabled")
            return None
        
        try:
            return ClaudeSummarizer(
                api_key=config.LLM_API_KEY,
                model=config.LLM_MODEL
            )
        except ImportError:
            logger.error(
                "anthropic package not installed. "
                "Install with: pip install anthropic"
            )
            return None
        except Exception as e:
            logger.error(f"Failed to initialize Claude summarizer: {e}")
            return None
    
    elif config.LLM_PROVIDER == "ollama":
        # Placeholder for future Ollama implementation
        logger.warning("Ollama summarizer not yet implemented")
        return None
    
    else:
        logger.warning(f"Unknown LLM provider: {config.LLM_PROVIDER}")
        return None

