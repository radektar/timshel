"""The synthesis pass: ask the user's own Claude to find connections.

This is the differentiating step. It reuses the existing lazy Anthropic client
pattern (summarizer/tagger) and the same circuit breaker, but produces a strict,
schema-validated result via **forced tool use** (``tool_choice``) rather than a
beta structured-output endpoint — tool use is GA on every Claude model, which
matters because the synthesis model is user-selectable (Opus / Sonnet / Haiku).

Design rules are locked in Docs/POSITIONING.md: non-prescriptive directions,
grounded-only claims, temporal contradiction detection, and "empty is fine"
(no genuine pattern → no digest).
"""

from __future__ import annotations

from typing import Any, List, Literal, Optional

from pydantic import BaseModel, Field, ValidationError, field_validator

from src.config import config
from src.connections.candidate_assembly import CandidateSet
from src.llm.client import build_anthropic_client
from src.llm.model_router import resolve_model
from src.logger import logger
from src.summarizer import APIBillingError, _is_permanent_api_error

_TOOL_NAME = "emit_connections"


# --------------------------------------------------------------------------- #
# Schema (validated by Pydantic, surfaced to Claude as the tool input schema)
# --------------------------------------------------------------------------- #
class Evidence(BaseModel):
    """The grounding fragment for one linked note — the 'ground' layer.

    One per note in the connection. ``quote`` is a SHORT verbatim fragment from
    that note's supplied summary; ``date`` is the note's date as given. This is
    what the Insights window reveals under the high-level rationale so the user
    can reconstruct *why* the notes connect without relying on fresh memory.
    """

    note: str = Field(..., description="Exact [[basename]] id — one of the connection's notes.")
    date: str = Field("", description="The note's date as supplied.")
    quote: str = Field(..., description="A short verbatim fragment from that note's summary.")

    @field_validator("note")
    @classmethod
    def _strip_note_wikilink(cls, value: str) -> str:
        return value.strip().strip("[]").strip()


class Connection(BaseModel):
    """One proposed connection across 2+ notes."""

    type: Literal["shared-thread", "contradiction-over-time", "emergent-idea"]
    notes: List[str] = Field(
        ..., min_length=2, description="Exact [[basename]] ids of the linked notes."
    )
    rationale: str = Field(
        ...,
        description="The spark: a high-level grounded claim. NOT the dated quotes "
        "(those go in 'evidence').",
    )
    evidence: List[Evidence] = Field(
        default_factory=list,
        description="One grounding fragment per linked note (date + verbatim quote).",
    )
    directions: List[str] = Field(
        ...,
        min_length=2,
        max_length=4,
        description="2-4 non-prescriptive invitations (~1-2 sentences), phrased as questions.",
    )

    @field_validator("evidence")
    @classmethod
    def _evidence_for_known_notes(cls, value: List["Evidence"], info: Any) -> List["Evidence"]:
        """Drop evidence whose note isn't in the connection (lenient, not fatal)."""
        notes = info.data.get("notes") or []
        known = {n.strip().strip("[]").strip() for n in notes}
        return [e for e in value if not known or e.note in known]

    @field_validator("notes")
    @classmethod
    def _strip_wikilinks(cls, value: List[str]) -> List[str]:
        """Normalize note ids to bare basenames.

        Models echo the ids inconsistently — some return ``"[[Cooling v1]]"``
        (following the prompt literally), others ``"Cooling v1"``. Stripping the
        brackets here means the known-basename filter, dismiss signatures and the
        digest's ``[[wikilinks]]`` all behave the same regardless of the model
        (otherwise a model that wraps ids would have every connection dropped and
        produce double-bracketed links).
        """
        return [n.strip().strip("[]").strip() for n in value]


class ConnectionList(BaseModel):
    connections: List[Connection] = Field(default_factory=list)


def _parse_payload(payload: object) -> ConnectionList:
    """Validate Claude's tool input, leniently dropping malformed connections."""
    if not isinstance(payload, dict):
        return ConnectionList()
    try:
        return ConnectionList.model_validate(payload)
    except ValidationError:
        good: List[Connection] = []
        for raw in payload.get("connections", []) or []:
            try:
                good.append(Connection.model_validate(raw))
            except ValidationError:
                continue
        return ConnectionList(connections=good)


# --------------------------------------------------------------------------- #
# Prompts
# --------------------------------------------------------------------------- #
_LANG_NAMES = {"pl": "Polish", "en": "English"}

# Legacy prompt — superseded in production by the sharpened _SYSTEM_PROMPT below.
# Kept only so scripts/compare_distance_experiment.py can still reproduce the
# pre-promotion baseline (condition A). Do not use in the pipeline.
_SYSTEM_PROMPT_LEGACY = (
    "You read a person's own voice notes (transcribed) and find GENUINE "
    "connections across them. You are a thinking partner, not an assistant that "
    "gives orders.\n\n"
    "Connection types:\n"
    "- shared-thread: the same idea/theme recurs across notes.\n"
    "- contradiction-over-time: the person's stance CHANGED between an earlier "
    "and a later note (use the dates to detect this).\n"
    "- emergent-idea: several scattered notes combine into a new idea the person "
    "has not stated outright.\n\n"
    "Hard rules:\n"
    "- Ground every connection in the supplied summaries. NEVER invent a link. "
    "If nothing genuinely connects, return an empty list — that is the correct, "
    "expected answer, not a failure.\n"
    "- Reference 2+ notes by their exact [[basename]] id (as given).\n"
    "- 'directions' must be 2-4 NON-PRESCRIPTIVE options the person could "
    'pursue, phrased as invitations or questions ("A: Could you…?"). Never '
    'instruct ("do X"). They are prompts for thought.\n'
    "- 'rationale' is exactly one grounded sentence.\n"
    "- Do NOT re-propose anything under ALREADY-DISMISSED.\n"
    "- Prefer a few strong connections over many weak ones.\n"
    "Return your answer ONLY through the emit_connections tool."
)

# Production prompt. A surprise target: a horoscope guard (reject connections
# that would be true of any random notes), a real separation of shared-thread vs
# emergent-idea, and a deeper 2-3 sentence rationale that names the specific
# tension/transfer, not the topic. Promoted from the distance experiment, where
# it eliminated generic shared-thread noise and deepened every rationale; it is
# also terse enough to fit SYNTHESIS_MAX_TOKENS (the legacy prompt truncated).
_SYSTEM_PROMPT = (
    "You read a person's own voice notes (transcribed) and surface the few "
    "GENUINELY surprising connections across them. A connection is worth showing "
    "only if it is both PLAUSIBLE (it really holds, grounded in the notes) and "
    "UNEXPECTED (the person would not have put these notes together themselves). "
    "You are a thinking partner, not an assistant that gives orders.\n\n"
    "Connection types:\n"
    "- contradiction-over-time: the person's stance CHANGED between an earlier "
    "and a later note (use the dates). Highest value — look for it first.\n"
    "- emergent-idea: two or more notes that do NOT obviously belong together "
    "combine into a claim the person never stated. The further apart their topics, "
    "the better. A new idea, not a restated theme.\n"
    "- shared-thread: the same theme simply recurs. LOWEST value — use sparingly, "
    "and never label a mere recurring theme as emergent-idea.\n\n"
    "Hard rules:\n"
    "- HOROSCOPE GUARD: reject any connection whose rationale would be roughly "
    "true of a random handful of this person's notes. It must depend on the "
    "SPECIFIC content of the notes it links. If in doubt, drop it.\n"
    "- Ground every connection in the supplied summaries. NEVER invent a link. "
    "If nothing genuinely connects, return an empty list — that is the correct, "
    "expected answer, not a failure.\n"
    "- Reference 2+ notes by their exact [[basename]] id (as given).\n"
    "- 'rationale' is 1-2 grounded sentences naming the SPECIFIC tension or "
    "transfer (what new thing follows from putting these notes together), never "
    "just the shared topic. It is the high-level SPARK — do NOT pack the dated "
    "quotes into it; those belong in 'evidence'. Address the PERSON as the "
    "subject ('w marcu zakładałeś X, teraz przesuwasz to za Y'); dates are "
    "timestamps, never narrators ('March proposes...' is wrong).\n"
    "- 'evidence': for EACH linked note, one item with its exact [[basename]] "
    "as 'note', its 'date' as given, and a SHORT VERBATIM fragment of that "
    "note's summary as 'quote' (the line that grounds the connection). Quote "
    "only — never paraphrase into a quote, never invent a date.\n"
    "- 'directions' must be 2-4 NON-PRESCRIPTIVE options the person could "
    "pursue, each a self-contained invitation or question of ~1-2 sentences "
    '(enough to stand alone without the fresh context). Phrase as questions '
    '("Could you…?"), never instruct ("do X"). Clean language only — no English '
    "words dropped into another language.\n"
    "- Do NOT re-propose anything under ALREADY-DISMISSED.\n"
    "- Prefer two surprising connections over six obvious ones.\n"
    "Return your answer ONLY through the emit_connections tool."
)


def _build_user_prompt(
    candidates: CandidateSet, dismissed: List[str], language: Optional[str]
) -> str:
    lang_name = _LANG_NAMES.get(language or "", "the language of the notes")
    lines: List[str] = [
        f"Write 'rationale' and 'directions' in {lang_name}.",
        "",
        "NOTES (newest marked NEW):",
    ]
    for note in candidates.notes:
        new = " | NEW" if note.basename in candidates.window_basenames else ""
        tags = ", ".join(note.tags) if note.tags else "—"
        lines.append(f"\n[[{note.basename}]] | {note.date} | tags: {tags}{new}")
        lines.append(note.summary_md.strip())
    if dismissed:
        lines.append("\nALREADY-DISMISSED (do not re-propose):")
        for desc in dismissed:
            lines.append(f"- {desc}")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Synthesizer
# --------------------------------------------------------------------------- #
class ConnectionSynthesizer:
    """Runs one Claude synthesis pass over an assembled candidate set."""

    def __init__(self, api_key: str, model: str) -> None:
        self.client = build_anthropic_client(api_key)
        self.model = model
        self.last_usage: Any = None  # usage of the most recent call (for the eval)

    def synthesize(
        self,
        candidates: CandidateSet,
        dismissed: Optional[List[str]] = None,
        language: Optional[str] = None,
        system_prompt: Optional[str] = None,
    ) -> Optional[ConnectionList]:
        """Return validated connections, or ``None`` on a recoverable error.

        Raises:
            APIBillingError: on a permanent API error (credits/model), so the
                caller can trip the shared session circuit breaker.
        """
        if len(candidates.notes) < 2:
            return ConnectionList()

        tool = {
            "name": _TOOL_NAME,
            "description": "Return the genuine connections you found across the notes.",
            "input_schema": ConnectionList.model_json_schema(),
        }
        user_prompt = _build_user_prompt(candidates, dismissed or [], language)

        try:
            logger.debug("synthesis: calling Claude (model=%s)", self.model)
            message = self.client.messages.create(
                model=self.model,
                max_tokens=config.SYNTHESIS_MAX_TOKENS,
                timeout=config.SYNTHESIS_TIMEOUT,
                system=system_prompt or _SYSTEM_PROMPT,
                tools=[tool],
                tool_choice={"type": "tool", "name": _TOOL_NAME},
                messages=[{"role": "user", "content": user_prompt}],
            )
        except Exception as exc:  # noqa: BLE001
            reason = _is_permanent_api_error(exc)
            if reason:
                logger.critical(
                    "❌ Claude API permanent error (synthesis, reason=%s): %s",
                    reason,
                    exc,
                )
                raise APIBillingError(str(exc)) from exc
            logger.error("synthesis API error: %s", exc, exc_info=True)
            return None

        self.last_usage = getattr(message, "usage", None)
        # A forced tool call truncated at the token ceiling still returns a
        # tool_use block with partial/invalid JSON; parsing it leniently would
        # yield "0 connections", indistinguishable from a genuinely empty run —
        # and the caller would then mark_ran(), resetting the weekly clock and
        # discarding the accumulated trigger. Treat truncation as recoverable.
        if getattr(message, "stop_reason", None) == "max_tokens":
            logger.warning(
                "synthesis: response truncated at max_tokens (%s) — skipping run, "
                "will retry next tick",
                config.SYNTHESIS_MAX_TOKENS,
            )
            return None
        for block in message.content:
            if (
                getattr(block, "type", None) == "tool_use"
                and getattr(block, "name", None) == _TOOL_NAME
            ):
                return _parse_payload(block.input)
        logger.warning("synthesis: model returned no tool_use block")
        return ConnectionList()


def get_synthesizer() -> Optional[ConnectionSynthesizer]:
    """Factory mirroring ``get_summarizer`` — available to everyone.

    Tier gating removed: availability is decided purely by config (a Claude API
    key / enabled provider), not by license.
    """
    if not config.ENABLE_CONNECTION_SYNTHESIS:
        logger.debug("Connection synthesis disabled in config")
        return None
    if config.LLM_PROVIDER != "claude" or not config.LLM_API_KEY:
        logger.warning("Connection synthesis needs a Claude API key — skipping")
        return None
    try:
        return ConnectionSynthesizer(
            api_key=config.LLM_API_KEY, model=resolve_model("synthesis")
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to init ConnectionSynthesizer: %s", exc)
        return None
