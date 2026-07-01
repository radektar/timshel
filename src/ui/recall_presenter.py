"""Headless presenter for the recall results surface (Faza 3 — pull, no LLM).

Turns :class:`~src.connections.recall.retriever.Result` objects into a render-ready
view-model the native Konstelacja window draws verbatim: ranked citation rows
(rank · date · title · verbatim quote · open-target) and an honest *abstinence*
state when nothing in the corpus is semantically close enough.

No AppKit here — pure data, fully unit-tested. The window is a thin renderer over
this model, mirroring the existing ``insight_model`` ↔ ``dashboard_window`` split.
Search reaches no LLM and nothing leaves the Mac; this layer only shapes results.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional, Sequence

# Confidence floor below which we abstain rather than dress up weak neighbours as
# answers. Confidence is max(top dense cosine, top lexical overlap) — see
# HybridRetriever.search_scored. Tuned against the real 170-note vault: relevant
# paraphrase/named-entity queries land ≥0.70, genuinely-absent topics ≤0.55. Biased
# toward the low end of that gap — a false abstention (hiding a real hit) is worse UX
# than showing one marginal row. Module constant so it can be retuned per model.
DEFAULT_ABSTAIN_FLOOR = 0.60

_DATE_PREFIX = re.compile(r"^(\d{2}-\d{2}-\d{2})\s*[-–]\s*(.*)$")


@dataclass(frozen=True)
class RecallRow:
    """One ranked citation — the render payload for a single result line."""

    rank: int          # 1-based display rank ("01".."0N" in the UI)
    date: str          # "26-06-17" parsed from the note, or "" if none
    title: str         # note title (filename minus the date prefix)
    quote: str         # verbatim passage, whitespace-normalized and length-capped
    note_id: str       # identifier the opener resolves to a file on disk
    score: float       # fused RRF score (opaque; ordering only)
    channels: str      # which channels found it: "dense" / "lexical" / "dense+lexical"
    dimmed: bool = False  # the near-miss shown under an abstinence state


@dataclass(frozen=True)
class RecallResults:
    """View-model for the results surface. ``rows`` is empty in abstinence."""

    query: str
    rows: List[RecallRow]
    is_empty: bool                 # True → render the abstinence state
    nearest: Optional[RecallRow]   # closest weak match to show dimmed when empty
    confidence: float              # top dense cosine similarity (0..1)

    @property
    def count(self) -> int:
        return len(self.rows)


def split_stem(note_id: str) -> tuple:
    """(date, title) from a ``YY-MM-DD - Title`` filename stem. Date "" if absent."""
    m = _DATE_PREFIX.match((note_id or "").strip())
    if m:
        return m.group(1), m.group(2).strip()
    return "", (note_id or "").strip()


def trim_quote(text: str, limit: int = 240) -> str:
    """Collapse whitespace and cap length on a word boundary with an ellipsis."""
    q = " ".join((text or "").split())
    if len(q) <= limit:
        return q
    return q[:limit].rsplit(" ", 1)[0].rstrip() + "…"


_MD_MARKERS = re.compile(r"[*_`#>]+")
# Leading run of non-letter noise (markdown bullets, emoji, stray punctuation).
_LEAD_NOISE = re.compile(r"^[^0-9A-Za-zÀ-ÿ„”\"']+", re.UNICODE)


def clean_quote(text: str, limit: int = 240) -> str:
    """Turn a raw chunk into a readable citation for display.

    Chunks are cut over markdown summaries, so a raw quote carries structural noise
    (``**bold**``, ``## heading``, ``>`` blockquotes, list bullets, emoji). This strips
    that noise and length-caps — safely, without dropping real words. Mid-word chunk
    *starts* are fixed at the source (the chunker snaps to a word boundary), so this
    layer only cleans markup. Display-only; the stored chunk stays raw for anchoring.
    """
    q = _MD_MARKERS.sub("", " ".join((text or "").split()))
    q = _LEAD_NOISE.sub("", q).strip()
    return trim_quote(q, limit)


def _row(result, rank: int, *, quote_limit: int, dimmed: bool = False) -> RecallRow:
    date, title = split_stem(result.note_id)
    return RecallRow(
        rank=rank,
        date=date,
        title=title,
        quote=clean_quote(result.quote, quote_limit),
        note_id=result.note_id,
        score=result.score,
        channels=result.channels,
        dimmed=dimmed,
    )


def present(
    query: str,
    results: Sequence,
    confidence: float,
    *,
    floor: float = DEFAULT_ABSTAIN_FLOOR,
    max_rows: int = 8,
    per_note_cap: int = 2,
    quote_limit: int = 240,
) -> RecallResults:
    """Shape raw hits into the results view-model.

    Abstains (``is_empty=True``) when there are no hits or the best semantic match
    is below ``floor`` — surfacing the closest weak hit as a dimmed near-miss so the
    UI can say "nothing about X — closest match:" honestly instead of inventing one.
    Otherwise returns up to ``max_rows`` ranked rows, capping any single note to
    ``per_note_cap`` fragments so one chatty note can't crowd out the rest.
    """
    query = (query or "").strip()
    hits = list(results or [])

    if not hits or confidence < floor:
        nearest = _row(hits[0], 1, quote_limit=quote_limit, dimmed=True) if hits else None
        return RecallResults(query=query, rows=[], is_empty=True, nearest=nearest, confidence=confidence)

    rows: List[RecallRow] = []
    per_note: dict = {}
    for result in hits:
        if per_note.get(result.note_id, 0) >= per_note_cap:
            continue
        per_note[result.note_id] = per_note.get(result.note_id, 0) + 1
        rows.append(_row(result, len(rows) + 1, quote_limit=quote_limit))
        if len(rows) >= max_rows:
            break

    return RecallResults(query=query, rows=rows, is_empty=False, nearest=None, confidence=confidence)
