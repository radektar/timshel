"""Results-synthesis — the ONE LLM door in the recall (pull) path.

Search itself is 100% local and LLM-free. This module is the *explicit* escalation:
the user asks "synthesize these results", and only then do the matched excerpts (and
nothing else) go to the LLM, which returns a grounded answer card in the same
thesis → cited-evidence → directions grammar as the push digest.

Mirrors :class:`src.connections.synthesis.ConnectionSynthesizer` exactly — the same
lazy Anthropic client, circuit breaker, and forced tool-use for schema-validated
output — but over a query + retrieved passages instead of a candidate note set. The
model is independently swappable via ``resolve_model("results_synthesis")``.
"""

from __future__ import annotations

from typing import Any, List, Optional

from pydantic import BaseModel, Field, ValidationError, field_validator

from src.config import config
from src.llm.model_router import resolve_model
from src.logger import logger
from src.summarizer import APIBillingError, _is_permanent_api_error
from src.ui.recall_presenter import split_stem

Anthropic: Any = None

_TOOL_NAME = "emit_answer"


# --------------------------------------------------------------------------- #
# Schema (validated by Pydantic, surfaced to Claude as the tool input schema)
# --------------------------------------------------------------------------- #
class AnswerEvidence(BaseModel):
    """One cited passage the answer rests on — the 'ground' layer of the card."""

    note: str = Field(..., description="Exact [[note id]] of the source passage.")
    date: str = Field("", description="The note's date as supplied.")
    quote: str = Field(..., description="A short verbatim fragment from that passage.")

    @field_validator("note")
    @classmethod
    def _strip_note_wikilink(cls, value: str) -> str:
        return value.strip().strip("[]").strip()


class RecallAnswer(BaseModel):
    """A grounded answer to the user's question, synthesized ONLY from the passages."""

    answered: bool = Field(
        ...,
        description="True only if the passages genuinely answer the question. If they "
        "do not, set false and say so in 'thesis' — never invent an answer.",
    )
    thesis: str = Field(
        ...,
        description="The grounded answer in 1-3 sentences (the SPARK). If unanswerable, "
        "a short honest note that the notes don't cover it.",
    )
    evidence: List[AnswerEvidence] = Field(
        default_factory=list,
        description="The passages the answer rests on — date + exact [[note]] + verbatim quote.",
    )
    directions: List[str] = Field(
        default_factory=list,
        description="0-4 non-prescriptive follow-up questions (~1-2 sentences), phrased "
        "as invitations.",
    )


def _parse_payload(payload: object) -> Optional[RecallAnswer]:
    if not isinstance(payload, dict):
        return None
    try:
        return RecallAnswer.model_validate(payload)
    except ValidationError:
        logger.warning("results-synthesis: tool payload failed validation")
        return None


_SYSTEM_PROMPT = (
    "You answer a person's question using ONLY the retrieved passages from their own "
    "notes provided below. You are a thinking partner grounded strictly in their words.\n\n"
    "Hard rules:\n"
    "- Answer ONLY from the supplied passages. NEVER add outside knowledge or invent "
    "facts. If the passages do not actually answer the question, set 'answered' false "
    "and say so plainly in 'thesis' — that is the correct answer, not a failure.\n"
    "- 'thesis' is 1-3 grounded sentences: the direct answer (the SPARK). Do not pack "
    "the dated quotes into it — those belong in 'evidence'.\n"
    "- 'evidence': for each passage you actually used, one item with its exact [[note]] "
    "id, its 'date' as given, and a SHORT VERBATIM fragment as 'quote'. Quote only — "
    "never paraphrase into a quote, never invent a date. Cite only passages provided.\n"
    "- 'directions': 0-4 non-prescriptive follow-up questions the person could pursue, "
    "each a self-contained invitation of ~1-2 sentences. Phrase as questions, never "
    "instruct. Clean language only — no foreign words dropped in.\n"
    "- Write 'thesis' and 'directions' in the language of the notes (Polish unless the "
    "passages are clearly in another language).\n"
    "Return your answer ONLY through the emit_answer tool."
)


def _build_user_prompt(query: str, results: List[Any]) -> str:
    lines: List[str] = [f"QUESTION: {query}", "", "RETRIEVED PASSAGES:"]
    for r in results:
        date, title = split_stem(r.note_id)
        head = f"[[{r.note_id}]]"
        if date:
            head += f" | {date}"
        lines.append(f"\n{head}")
        lines.append((r.quote or "").strip())
    return "\n".join(lines)


class RecallSynthesizer:
    """Runs one grounded answer-synthesis pass over a query + retrieved passages."""

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

    def synthesize(self, query: str, results: List[Any]) -> Optional[RecallAnswer]:
        """Return a grounded answer, or ``None`` on a recoverable error.

        Raises:
            APIBillingError: on a permanent API error, so the caller can trip the
                shared session circuit breaker (same contract as ConnectionSynthesizer).
        """
        query = (query or "").strip()
        if not query or not results:
            return None

        tool = {
            "name": _TOOL_NAME,
            "description": "Return the grounded answer built only from the passages.",
            "input_schema": RecallAnswer.model_json_schema(),
        }
        user_prompt = _build_user_prompt(query, results)

        try:
            logger.debug("results-synthesis: calling Claude (model=%s)", self.model)
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
                logger.critical("❌ Claude API permanent error (results-synthesis): %s", exc)
                raise APIBillingError(str(exc)) from exc
            logger.error("results-synthesis API error: %s", exc, exc_info=True)
            return None

        self.last_usage = getattr(message, "usage", None)
        if getattr(message, "stop_reason", None) == "max_tokens":
            logger.warning("results-synthesis: response truncated at max_tokens — skipping")
            return None
        for block in message.content:
            if (
                getattr(block, "type", None) == "tool_use"
                and getattr(block, "name", None) == _TOOL_NAME
            ):
                return _parse_payload(block.input)
        logger.warning("results-synthesis: model returned no tool_use block")
        return None


def get_recall_synthesizer() -> Optional[RecallSynthesizer]:
    """Factory mirroring ``get_synthesizer`` — gated purely by config, not license."""
    if not config.ENABLE_CONNECTION_SYNTHESIS:
        logger.debug("results-synthesis disabled in config")
        return None
    if config.LLM_PROVIDER != "claude" or not config.LLM_API_KEY:
        logger.warning("results-synthesis needs a Claude API key — skipping")
        return None
    try:
        return RecallSynthesizer(
            api_key=config.LLM_API_KEY, model=resolve_model("results_synthesis")
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to init RecallSynthesizer: %s", exc)
        return None


def synthesize_answer_safe(query: str, results: List[Any]) -> Optional[RecallAnswer]:
    """Best-effort escalation for the UI: ``None`` on any failure (no synthesizer,
    permanent API error, empty inputs) so the window degrades gracefully."""
    synth = get_recall_synthesizer()
    if synth is None:
        return None
    try:
        return synth.synthesize(query, results)
    except APIBillingError as exc:  # permanent → swallow here; UI shows a soft failure
        logger.warning("results-synthesis billing error: %s", exc)
        return None
    except Exception as exc:  # noqa: BLE001
        logger.debug("results-synthesis failed: %s", exc)
        return None
