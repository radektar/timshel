"""Verdict pass — the verification stage of the magic-insights prototype.

Synthesis PROPOSES connections from note summaries; this pass VERIFIES each one
against the fuller text of the notes it links, and drops the ones that do not
survive: fabricated/mismatched evidence quotes, rationales that do not follow
from these specific notes (the horoscope guard, re-applied with more context),
contradictions whose dates do not actually order a stance change.

Cost is bounded by design: the verifier sees only the FINAL connections plus
the fuller text of the union of their linked notes (``VERDICT_MAX_NOTE_CHARS``
each) — typically 3-6 notes, not the 25-note synthesis prompt.

Mirrors :class:`src.connections.recall.synthesis.RecallSynthesizer` exactly —
same lazy Anthropic client, circuit-breaker contract, forced tool-use — and is
independently swappable via ``resolve_model("verdict")`` (the cascade
experiment runs synthesis on one model and verdict on another).

FAIL OPEN everywhere: a recoverable API error returns ``None`` and the caller
keeps every connection. The verdict pass must never lose a digest to a hiccup.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, ValidationError

from src.config import config
from src.connections.candidate_assembly import (
    NoteRef,
    _body_after_frontmatter,
    _excerpt,
)
from src.connections.synthesis import Connection
from src.llm.model_router import resolve_model
from src.logger import logger
from src.summarizer import APIBillingError, _is_permanent_api_error

Anthropic: Any = None

_TOOL_NAME = "emit_verdicts"

_LANG_NAMES = {"pl": "Polish", "en": "English"}


# --------------------------------------------------------------------------- #
# Schema
# --------------------------------------------------------------------------- #
class Verdict(BaseModel):
    """Judgment on one proposed connection (by its 1-based index)."""

    index: int = Field(..., description="1-based index of the connection under review.")
    verdict: bool = Field(..., description="True = keep, false = drop.")
    reason: str = Field("", description="One grounded sentence for the judgment.")
    severity: Literal["fatal", "weak", "ok"] = Field(
        "ok",
        description="fatal = fabricated/ungrounded evidence; weak = real but thin; "
        "ok = solid.",
    )


class VerdictList(BaseModel):
    verdicts: List[Verdict] = Field(default_factory=list)


def _parse_payload(payload: object) -> Optional[VerdictList]:
    """Lenient parse — drop malformed verdict items, never the whole list."""
    if not isinstance(payload, dict):
        return None
    try:
        return VerdictList.model_validate(payload)
    except ValidationError:
        good: List[Verdict] = []
        for raw in payload.get("verdicts", []) or []:
            try:
                good.append(Verdict.model_validate(raw))
            except ValidationError:
                continue
        return VerdictList(verdicts=good)


# --------------------------------------------------------------------------- #
# Prompts
# --------------------------------------------------------------------------- #
_SYSTEM_PROMPT = (
    "You VERIFY proposed connections between a person's own notes. Another pass "
    "proposed them from short summaries; you now see the FULLER text of the "
    "linked notes and judge each connection strictly against it.\n\n"
    "For each numbered connection return one verdict:\n"
    "- Check EVERY evidence quote: it must genuinely appear in the fuller text "
    "of its note (allow small transcription noise, but never a paraphrase "
    "presented as a quote, never an invented date). Fabricated evidence -> "
    "verdict false, severity 'fatal'.\n"
    "- Re-apply the horoscope guard with this fuller context: if the rationale "
    "would be roughly true of a random handful of this person's notes, or does "
    "not follow from THESE specific notes, drop it ('fatal' if ungrounded, "
    "'weak' if merely generic).\n"
    "- For contradiction-over-time: the dates must genuinely order a stance "
    "change on the SAME question. Different topics or no real reversal -> drop.\n"
    "- A connection that is real but thin may be kept with severity 'weak' — "
    "judge honestly; do not drop merely for being modest.\n"
    "- When in doubt about fabrication, drop. When in doubt about value, keep.\n"
    "Return one verdict per connection, in order, ONLY through the "
    f"{_TOOL_NAME} tool."
)


def _fuller_text(note: NoteRef, max_chars: int) -> str:
    """Re-read the note and return summary + TRANSCRIPT (bounded head/tail).

    Verification only means something against the ground truth, i.e. the actual
    recording. ``_summary_or_excerpt`` (what synthesis uses) strips the
    transcript whenever a summary block exists, so verifying against it would
    check a quote against the very summary it may have been extracted from —
    circular. We take the whole body after the frontmatter (summary AND
    transcript) and bound it head/tail. Falls back to the summary only when the
    file can't be re-read.
    """
    try:
        full = note.md_path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.debug(
            "verdict: cannot re-read %s (%s); using summary", note.md_path, exc
        )
        return note.summary_md
    return _excerpt(_body_after_frontmatter(full).strip(), max_chars)


def _build_user_prompt(
    connections: List[Connection],
    notes_by_basename: Dict[str, NoteRef],
    language: Optional[str],
) -> str:
    lang_name = _LANG_NAMES.get(language or "", "the language of the notes")
    lines: List[str] = [
        f"Write every 'reason' in {lang_name}.",
        "",
        "PROPOSED CONNECTIONS:",
    ]
    linked: Dict[str, NoteRef] = {}
    for i, conn in enumerate(connections, 1):
        lines.append(
            f"\n{i}. [{conn.type}] notes: " + ", ".join(f"[[{b}]]" for b in conn.notes)
        )
        lines.append(f"   rationale: {conn.rationale}")
        for ev in conn.evidence:
            lines.append(f"   evidence [[{ev.note}]] {ev.date}: „{ev.quote}”")
        for b in conn.notes:
            note = notes_by_basename.get(b)
            if note is not None:
                linked[b] = note

    max_chars = getattr(config, "VERDICT_MAX_NOTE_CHARS", 4000)
    lines.append("\nNOTES (fuller text):")
    for basename, note in linked.items():
        lines.append(f"\n[[{basename}]] | {note.date}")
        lines.append(_fuller_text(note, max_chars).strip())
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Verifier
# --------------------------------------------------------------------------- #
class ConnectionVerifier:
    """Runs one verification pass over proposed connections."""

    def __init__(self, api_key: str, model: str) -> None:
        global Anthropic
        try:
            from anthropic import Anthropic as AnthropicClient
        except ImportError as exc:  # pragma: no cover
            raise ImportError(
                "anthropic package not installed. Install via `pip install anthropic`."
            ) from exc
        if Anthropic is None:
            Anthropic = AnthropicClient
        self.client = Anthropic(api_key=api_key)
        self.model = model
        self.last_usage: Any = None

    def verify(
        self,
        connections: List[Connection],
        notes_by_basename: Dict[str, NoteRef],
        language: Optional[str] = None,
    ) -> Optional[VerdictList]:
        """Return verdicts, or ``None`` on a recoverable error (caller fails OPEN).

        Raises:
            APIBillingError: on a permanent API error (same contract as synthesis).
        """
        if not connections:
            return VerdictList()

        tool = {
            "name": _TOOL_NAME,
            "description": "Return one verdict per proposed connection, in order.",
            "input_schema": VerdictList.model_json_schema(),
        }
        user_prompt = _build_user_prompt(connections, notes_by_basename, language)

        try:
            logger.debug("verdict: calling Claude (model=%s)", self.model)
            message = self.client.messages.create(
                model=self.model,
                max_tokens=config.SYNTHESIS_MAX_TOKENS,
                timeout=config.SYNTHESIS_TIMEOUT,
                system=_SYSTEM_PROMPT,
                tools=[tool],
                tool_choice={"type": "tool", "name": _TOOL_NAME},
                messages=[{"role": "user", "content": user_prompt}],
            )
        except Exception as exc:  # noqa: BLE001
            reason = _is_permanent_api_error(exc)
            if reason:
                logger.critical(
                    "❌ Claude API permanent error (verdict, reason=%s): %s",
                    reason,
                    exc,
                )
                raise APIBillingError(str(exc)) from exc
            logger.error("verdict API error: %s", exc, exc_info=True)
            return None

        self.last_usage = getattr(message, "usage", None)
        if getattr(message, "stop_reason", None) == "max_tokens":
            logger.warning(
                "verdict: response truncated at max_tokens (%s) — failing open",
                config.SYNTHESIS_MAX_TOKENS,
            )
            return None
        for block in message.content:
            if (
                getattr(block, "type", None) == "tool_use"
                and getattr(block, "name", None) == _TOOL_NAME
            ):
                return _parse_payload(block.input)
        logger.warning("verdict: model returned no tool_use block — failing open")
        return None


def apply_verdicts(
    connections: List[Connection], verdicts: Optional[VerdictList]
) -> List[Connection]:
    """Filter connections by verdicts — FAIL OPEN on anything unclear.

    ``None`` (recoverable error) keeps everything. A connection with no verdict
    keeps. An index outside 1..len is ignored. Only an explicit
    ``verdict: false`` drops.
    """
    if verdicts is None:
        return list(connections)
    drop: set = set()
    for v in verdicts.verdicts:
        if 1 <= v.index <= len(connections) and not v.verdict:
            drop.add(v.index - 1)
            logger.info(
                "verdict: dropping connection %d (%s): %s",
                v.index,
                v.severity,
                v.reason,
            )
    return [c for i, c in enumerate(connections) if i not in drop]


def get_verifier() -> Optional[ConnectionVerifier]:
    """Factory mirroring ``get_synthesizer`` — gated purely by config."""
    if not getattr(config, "VERDICT_ENABLED", False):
        logger.debug("verdict pass disabled in config")
        return None
    if config.LLM_PROVIDER != "claude" or not config.LLM_API_KEY:
        logger.warning("verdict pass needs a Claude API key — skipping")
        return None
    try:
        return ConnectionVerifier(
            api_key=config.LLM_API_KEY, model=resolve_model("verdict")
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to init ConnectionVerifier: %s", exc)
        return None
