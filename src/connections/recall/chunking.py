"""Chunk a note's markdown body into overlapping passages with provenance.

Recall embeds *small* chunks but returns the surrounding *parent* block
(small-to-big retrieval), so matching is precise while the answer/citation keeps
enough context. Pure and dependency-free — unit-testable without a model.

Boundaries snap to paragraph/sentence breaks so a citable quote is never cut
mid-word; consecutive chunks overlap so a point split across a boundary is still
retrievable.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import List, Optional


@dataclass(frozen=True)
class Chunk:
    """One embeddable passage plus everything needed to cite and expand it."""

    note_id: str
    seq: int
    text: str  # raw passage — the citable quote; the header is added only for embedding
    parent_text: str  # surrounding block returned to the reader / answerer
    char_start: int  # offset into the body handed to the chunker
    char_end: int
    version_hash: str = ""
    ts_start: Optional[float] = None
    ts_end: Optional[float] = None


def content_hash(text: str) -> str:
    """Short stable hash of a note body — keys re-embedding on edit/re-transcription."""
    return hashlib.sha1((text or "").encode("utf-8")).hexdigest()[:16]


def _snap_start(body: str, pos: int) -> int:
    """Advance ``pos`` to the start of the next whole word so a chunk never *begins*
    mid-word (the overlap step lands inside a token). No-op at a real boundary (start
    of body, or preceded by whitespace). Bounded so it can't skip more than a token."""
    n = len(body)
    if pos <= 0 or pos >= n or body[pos - 1].isspace():
        return pos
    limit = min(n, pos + 60)
    i = pos
    while i < limit and not body[i].isspace():
        i += 1
    while i < limit and body[i].isspace():
        i += 1
    return i if i < n else pos


def _snap_end(body: str, start: int, hard_end: int) -> int:
    """End a chunk at a paragraph, then sentence, break within the window.

    Only snap in the *back half* of the window — snapping too near ``start`` would
    emit degenerate one-token chunks and stall forward progress.
    """
    if hard_end >= len(body):
        return len(body)
    floor = start + max(1, (hard_end - start) // 2)
    para = body.rfind("\n", floor, hard_end)
    if para > floor:
        return para
    sent = max(body.rfind(". ", floor, hard_end), body.rfind("? ", floor, hard_end))
    if sent > floor:
        return sent + 1
    return hard_end


def chunk_body(
    note_id: str,
    body: str,
    *,
    target_chars: int = 1200,
    overlap_chars: int = 200,
    parent_margin: int = 700,
    version_hash: Optional[str] = None,
) -> List[Chunk]:
    """Split ``body`` into overlapping, boundary-snapped chunks with char offsets.

    ``target_chars`` ~ e5's 512-token window for Polish (~2 chars/token leaves
    headroom). ``parent_margin`` extends each side for the small-to-big parent.
    """
    body = body or ""
    if version_hash is None:
        version_hash = content_hash(body)
    if not body.strip():
        return []

    chunks: List[Chunk] = []
    pos = 0
    seq = 0
    n = len(body)
    while pos < n:
        # skip leading whitespace so char_start lands on real content
        while pos < n and body[pos].isspace():
            pos += 1
        if pos >= n:
            break
        end = _snap_end(body, pos, min(n, pos + target_chars))
        raw = body[pos:end]
        text = raw.strip()
        if text:
            p_start = max(0, pos - parent_margin)
            p_end = min(n, end + parent_margin)
            chunks.append(
                Chunk(
                    note_id=note_id,
                    seq=seq,
                    text=text,
                    parent_text=body[p_start:p_end].strip(),
                    char_start=pos,
                    char_end=end,
                    version_hash=version_hash,
                )
            )
            seq += 1
        if end >= n:
            break
        pos = _snap_start(body, max(end - overlap_chars, pos + 1))
    return chunks
