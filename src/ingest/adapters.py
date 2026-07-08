"""Source adapters: normalize a text file into an :class:`ImportedDoc`.

Dispatch is by suffix. Each adapter returns text + a title + a recorded-at
timestamp; the caller synthesizes the metadata dict the markdown generator
expects. Unsupported suffixes raise ``ValueError`` (mirrors how audio staging
rejects non-audio), so the caller can surface a clean "unsupported file" error.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict

# v1 scope. PDF / platform JSON are deferred (Docs/future/ingest-plan.md).
PLAIN_SUFFIXES = {".txt", ".md"}
VTT_SUFFIXES = {".vtt"}
SUPPORTED_SUFFIXES = PLAIN_SUFFIXES | VTT_SUFFIXES

# A WebVTT cue-timing line, e.g. "00:00:01.000 --> 00:00:04.000 align:start".
_VTT_TIMING = re.compile(r"-->")
# Inline voice/markup tags: <v Speaker>, </v>, <00:00:01.000>, <c.colorE5E5E5>.
_VTT_TAG = re.compile(r"<[^>]+>")


@dataclass
class ImportedDoc:
    """Normalized result of parsing one importable file."""

    text: str
    title: str
    recorded_at: datetime
    origin: str  # "txt" | "md" | "vtt"
    source_name: str
    extra_frontmatter: Dict[str, str] = field(default_factory=dict)


def _mtime(path: Path) -> datetime:
    """File modification time as a naive local datetime (fallback for date)."""
    return datetime.fromtimestamp(path.stat().st_mtime)


def _parse_plain(path: Path) -> ImportedDoc:
    text = path.read_text(encoding="utf-8", errors="replace").strip()
    return ImportedDoc(
        text=text,
        title=path.stem.replace("_", " ").strip() or "Import",
        recorded_at=_mtime(path),
        origin=path.suffix.lower().lstrip("."),
        source_name=path.name,
    )


def _parse_vtt(path: Path) -> ImportedDoc:
    """Strip WebVTT scaffolding down to the spoken text.

    Drops the WEBVTT header, NOTE blocks, numeric cue indices, timing lines and
    inline tags; keeps cue text. Speaker labels stay inline as written (no
    diarization in v1 — see plan). Consecutive duplicate lines are collapsed
    (some exporters repeat a line across overlapping cues).
    """
    raw = path.read_text(encoding="utf-8", errors="replace")
    lines: list[str] = []
    skip_note = False
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped:
            skip_note = False
            continue
        if stripped.upper().startswith("WEBVTT"):
            continue
        if stripped.startswith("NOTE"):
            skip_note = True
            continue
        if skip_note:
            continue
        if _VTT_TIMING.search(stripped):
            continue
        if stripped.isdigit():  # cue index
            continue
        cleaned = _VTT_TAG.sub("", stripped).strip()
        if cleaned and (not lines or lines[-1] != cleaned):
            lines.append(cleaned)
    text = "\n".join(lines).strip()
    return ImportedDoc(
        text=text,
        title=path.stem.replace("_", " ").strip() or "Import",
        recorded_at=_mtime(path),
        origin="vtt",
        source_name=path.name,
    )


def parse(path: Path) -> ImportedDoc:
    """Parse *path* into an :class:`ImportedDoc`. Raises on unsupported types."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"Not a file: {path}")
    suffix = path.suffix.lower()
    if suffix in PLAIN_SUFFIXES:
        doc = _parse_plain(path)
    elif suffix in VTT_SUFFIXES:
        doc = _parse_vtt(path)
    else:
        raise ValueError(
            f"Unsupported import type '{suffix}'. "
            f"Supported: {', '.join(sorted(SUPPORTED_SUFFIXES))}."
        )
    if not doc.text.strip():
        raise ValueError(f"No text content found in {path.name}")
    return doc
