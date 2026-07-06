"""AI-powered summarization for transcripts."""

import re
import time
from abc import ABC, abstractmethod
from typing import Dict, Optional, Tuple

from src.config import config
from src.logger import logger

Anthropic = None  # type: ignore[assignment]


def _fingerprint_key(key: Optional[str]) -> str:
    """Redacted, log-safe view of an API key.

    Shows just enough to catch a truncated, whitespace-padded, placeholder-
    contaminated, or simply *wrong* key — without ever writing the secret to a
    log. Answers "which key is actually being sent?" when Claude returns 401 on
    a key the user is sure is correct: compare ``head``/``tail`` against the key
    in the Anthropic console, and watch for the ``⚠`` flags.
    """
    if not key:
        return "<none>"
    stripped = key.strip()
    flags = []
    if key != stripped:
        flags.append("SURROUNDING_WHITESPACE")
    if any(c in key for c in ("\n", "\r", "\t")):
        flags.append("INNER_WHITESPACE")
    if "—" in key or "•" in key:
        flags.append("PLACEHOLDER_CHAR")
    if not stripped.startswith("sk-ant-"):
        flags.append("UNEXPECTED_PREFIX")
    tail = key[-4:] if len(key) > 8 else ""
    note = (" ⚠ " + ",".join(flags)) if flags else ""
    return f"len={len(key)} head={key[:14]!r} tail={tail!r}{note}"


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
    "się",
    "że",
    "jest",
    "oraz",
    "jako",
    "dla",
    "nie",
    "tak",
    "czy",
    "już",
    "albo",
    "ale",
    "być",
    "ma",
    "to",
    "na",
    "do",
    "po",
    "od",
    "przy",
    "który",
}
_EN_STOPWORDS = {
    "the",
    "and",
    "to",
    "of",
    "is",
    "for",
    "we",
    "in",
    "on",
    "that",
    "this",
    "with",
    "will",
    "by",
    "an",
    "it",
    "at",
    "as",
    "be",
    "are",
    "our",
    "have",
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
    """Return a reason string when *exc* is a permanent Anthropic API error, else None.

    "Permanent" = retrying with the same config cannot succeed this session, so
    the caller trips the AI circuit breaker and surfaces a clear message instead
    of failing silently. Recognises both the raw Anthropic SDK exception (which
    carries ``status_code``) and our own wrapped :class:`APIBillingError`
    (string only) — so re-classifying an already-wrapped error still yields the
    right reason.
    """
    status = getattr(exc, "status_code", None)
    blob = (str(getattr(exc, "message", "")) + " " + str(exc)).lower()
    # Auth: missing / invalid / revoked API key (HTTP 401). The single most
    # common silent failure — without this it returns None and the summary is
    # quietly dropped, leaving the user with no summaries/tags and no idea why.
    if status == 401 or "invalid x-api-key" in blob or "authentication_error" in blob:
        return "auth"
    # Billing: Anthropic credit balance exhausted (HTTP 400 invalid_request_error).
    if "credit balance" in blob:
        return "billing"
    # Model: unknown / retired model id (HTTP 404).
    if (status == 404 or "not_found" in blob) and "model" in blob:
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
    def generate(self, transcript: str, known_terms_block: str = "") -> Dict[str, str]:
        """Generate summary and title from transcript.

        Args:
            transcript: Full transcription text
            known_terms_block: Optional personal-glossary lines (see
                :class:`src.vocabulary.VocabularyIndex.known_terms_block`);
                empty string disables the KNOWN TERMS prompt block.

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

    def __init__(self, api_key: str, model: str = "claude-haiku-4-5-20251001"):
        """Initialize Claude summarizer.

        Args:
            api_key: Anthropic API key
            model: Claude model name. Defaults to the current config default;
                the retired ``claude-3-haiku-20240307`` (now HTTP 404) was a
                latent trap if any caller relied on the default.
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
        # Visibility for "valid key but 401": log the redacted fingerprint of the
        # key actually handed to the Anthropic client. Built at startup and on
        # every settings hot-reload, so the log viewer shows exactly which key is
        # in use — confirm it matches the one pasted in Settings.
        logger.info(
            "🔑 Claude client built — key %s, model=%s",
            _fingerprint_key(api_key),
            model,
        )
        self.max_words = config.SUMMARY_MAX_WORDS
        self.title_max_length = config.TITLE_MAX_LENGTH

    def generate(self, transcript: str, known_terms_block: str = "") -> Dict[str, str]:
        """Generate summary and title from transcript using Claude API.

        Args:
            transcript: Full transcription text
            known_terms_block: Personal-glossary lines for the KNOWN TERMS
                prompt block ("" = no block).

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

        prompt = self._build_prompt(transcript, known_terms_block)

        try:
            logger.debug(f"Calling Claude API (model: {self.model})")
            start_time = time.time()

            message = self.client.messages.create(
                model=self.model,
                max_tokens=1024,
                timeout=30.0,  # 30 second timeout
                messages=[{"role": "user", "content": prompt}],
            )

            elapsed = time.time() - start_time
            logger.debug(f"Claude API call completed in {elapsed:.2f}s")

            # Extract response
            response_text = message.content[0].text if message.content else ""

            # Parse response (expects format: TITLE: ...\n\nSUMMARY: ...)
            title, summary = self._parse_response(response_text)

            # Ensure title is within limits
            if len(title) > self.title_max_length:
                title = title[: self.title_max_length - 3] + "..."

            return {"title": title.strip(), "summary": summary.strip()}

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

    def _build_prompt(self, transcript: str, known_terms_block: str = "") -> str:
        """Build prompt for Claude API.

        Args:
            transcript: Transcription text
            known_terms_block: Personal-glossary lines ("" = no block)

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

        # The user's confirmed vocabulary: canonicalise clear variants, under
        # strict no-invention rules. Injected only when the glossary is
        # non-empty, so a fresh vault gets the baseline prompt unchanged.
        if known_terms_block:
            known_terms_directive = f"""
KNOWN TERMS — the user's confirmed vocabulary. This is the ONE exception to
the VERBATIM rule above: speech-to-text mangles proper names phonetically,
and the canonical spelling IS the term as actually spoken. When the
transcript CLEARLY refers to one of the terms below — phonetically close, a
listed alias, or unambiguous from context — write it in its canonical form
everywhere in the notes (title, summary, key points, stances). Strict rules:
- Canonicalise ONLY on a clear match. When unsure, keep exactly what was
  transcribed — a wrong "correction" is worse than a mangled name.
- NEVER mention a known term the recording does not refer to. This list says
  what the user's world contains, not what this recording is about.
- NEVER expand an abbreviation unless the expansion is given in this list or
  spoken in the recording.
- The "Quotes" section stays verbatim as transcribed, even when mangled —
  quotes are evidence.

{known_terms_block}
"""
        else:
            known_terms_directive = ""

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

VOCABULARY — preserve distinctive terms VERBATIM: proper names, product names,
place names and domain-specific terms must appear exactly as spoken ("Digitakt"
stays "Digitakt", never "music hardware"). These exact words are how notes are
found and cross-linked later — a genericising paraphrase breaks that.
{known_terms_directive}
Produce:

1. A SHORT TITLE (max {self.title_max_length} characters) — concise and descriptive, in the transcript's language.

2. A SUMMARY in markdown with these sections. Translate the headings, but in
   Polish use EXACTLY these forms (they are matched by software):
   "## Podsumowanie", "## Kluczowe punkty", "## Stanowiska",
   "## Wątki otwarte", "## Cytaty", "## Lista działań (To-do)".
   Never leave a heading in English inside a Polish note, and never invent
   alternative headings ("Streszczenie", "Elementy do wykonania").

   ## Summary
   - This heading is REQUIRED — never start the body as bare text without it
   - As many sentences as the content truly supports (a short recording → a short summary; do not stretch it)
   - **Bold** the key concepts, decisions and commitments; *italics* for context that is actually present

   ## Key points
   - Bullets grouped by priority, only those genuinely present in the recording:
     - ⚠️ **Critical:** decisions, commitments, deadlines stated directly
     - ⚡ **Important:** significant topics needing follow-up
     - 📝 **Info:** context, background
   - Skip a tier entirely if nothing fits it. Do not manufacture points.

   ## Stances
   (in Polish use exactly the heading "## Stanowiska")
   - ONLY when the speaker PERSONALLY evaluates something — a clear judgement,
     preference or decision voiced in the recording ("X to dobry kierunek",
     "rezygnuję z Y", "nie warto").
   - One line per stance, MAXIMUM 5:
     - [[Subject]] ✅ short reason, close to the speaker's own words
     - [[Subject]] ❌ short reason, close to the speaker's own words
     - [[Subject]] 🔄 changed mind — ONLY when the speaker explicitly says
       THEIR OWN previous opinion changed ("zmieniłem zdanie", "już nie
       uważam"); note old → new if stated. Never for tensions between other
       people's preferences and possibilities.
   - [[Subject]] is the person, project, company, product or place the stance
     is about, in [[double brackets]], in its BASE dictionary form (Polish:
     mianownik — write [[Fundacja Ziemi]] even if the recording says
     "Fundacji Ziemi"). Never bracket generic nouns ("pomysł", "spotkanie"),
     processes ("proces doboru mentorów") or abstract concepts.
   - These are NOT stances — never list them: neutral facts or reports
     ("spotkałem się z X"), plans without judgement, someone else's opinion
     or preference the speaker merely relays ("Syri chce ręcznie dobierać
     mentorów" = Syri's preference, NOT the speaker's stance), hedged musings
     ("może", "jeszcze nie wiem"), open dilemmas the speaker has not resolved
     (those belong in Open threads).
   - When in doubt, leave it out. Most recordings contain ZERO stances — then
     OMIT this whole section, heading included. An invented stance is far
     worse than a missing one.

   ## Open threads
   (in Polish use exactly the heading "## Wątki otwarte")
   - 0–4 questions or hypotheses the speaker EXPLICITLY voices and leaves
     unresolved ("czy dałoby się…?", "chcę sprawdzić, czy…").
   - One bullet each, staying close to the speaker's wording. Do NOT derive
     or invent questions the speaker did not ask. No open threads → omit the
     section entirely, heading included.

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
- Keep the stance markers (✅ ❌ 🔄) and the [[double-bracket]] links EXACTLY as
  specified — they are read by software, not only by people

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
                if (
                    stripped_line or summary_lines
                ):  # Include empty lines for markdown spacing
                    summary_lines.append(line)

        summary = "\n".join(summary_lines).strip()

        # Fallback if parsing failed
        if not title or not summary:
            # Try to extract first line as title, rest as summary
            parts = response_text.split("\n\n", 1)
            if len(parts) >= 2:
                title = parts[0].strip()[: self.title_max_length]
                summary = parts[1].strip()
                # Ensure summary has markdown structure if missing
                if not summary.startswith("##"):
                    summary = f"## Podsumowanie\n\n{summary[:self.max_words * 6]}"
            elif parts:
                title = parts[0].strip()[: self.title_max_length]
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
            title = first_line[: self.title_max_length] if first_line else "Nagranie"
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

        return {"title": title, "summary": summary}


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
            return ClaudeSummarizer(api_key=config.LLM_API_KEY, model=config.LLM_MODEL)
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
