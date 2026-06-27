"""Bridge the connection digest to the Insights window.

The synthesis layer (``src.connections.synthesis.Connection``) produces the
structured connections; ``digest_writer`` persists them to
``{vault}/.malinche/insights-latest.json``. This module loads that sidecar and
builds the pure :class:`~src.ui.insight_model.InsightDeck` the window renders —
so the dashboard shows the *real* digest, not the placeholder.

Kept free of AppKit and of a module-level ``config`` import (the path is
resolved lazily) so the mapping is unit-testable on its own.
"""

from __future__ import annotations

import json
from typing import Dict, List, Optional

from src.logger import logger
from src.ui import insight_model as im

#: synthesis type string → insight_model type constant.
_TYPE_MAP: Dict[str, str] = {
    "contradiction-over-time": im.CONTRADICTION,
    "shared-thread": im.SHARED,
    "emergent-idea": im.EMERGENT,
}


def map_type(synthesis_type: str) -> str:
    """Map a synthesis ``type`` to an :mod:`insight_model` constant.

    Unknown / missing types fall back to the shared-thread look rather than
    raising, so a schema drift never empties the window.
    """
    return _TYPE_MAP.get((synthesis_type or "").strip(), im.SHARED)


def connection_dict_to_insight(d: dict) -> im.InsightConnection:
    """Build an :class:`InsightConnection` from one sidecar/synthesis dict.

    Carries the ground layer (``evidence``) and the identity fields
    (``synthesis_type`` + precomputed ``sig``) so the window can render the
    evidence and log a canonical ``action_taken`` signature (ADR-004).
    """
    syn_type = d.get("type", "")
    evidence = [
        im.EvidenceItem(
            note=str(e.get("note", "")),
            date=str(e.get("date", "")),
            quote=str(e.get("quote", "")),
        )
        for e in (d.get("evidence") or [])
        if isinstance(e, dict)
    ]
    return im.make_connection(
        map_type(syn_type),
        d.get("rationale", ""),
        list(d.get("notes", []) or []),
        list(d.get("directions", []) or []),
        evidence=evidence,
        synthesis_type=syn_type,
        sig=str(d.get("sig", "")),
    )


def deck_from_dicts(dicts: List[dict]) -> im.InsightDeck:
    """Build an :class:`InsightDeck` from a list of connection dicts.

    Dicts missing the minimum (a type/rationale and 2+ notes) are skipped so a
    partially-malformed sidecar still yields a usable deck.
    """
    conns: List[im.InsightConnection] = []
    for d in dicts or []:
        if not isinstance(d, dict):
            continue
        notes = d.get("notes") or []
        if len(notes) < 2:
            continue
        conns.append(connection_dict_to_insight(d))
    return im.InsightDeck(conns)


def latest_insights_file():
    """Path to the sidecar, or ``None`` if config is unavailable."""
    try:
        from src.config import config

        from pathlib import Path

        return Path(config.TRANSCRIBE_DIR) / ".malinche" / "insights-latest.json"
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("could not resolve insights sidecar path: %s", exc)
        return None


def latest_deck() -> Optional[im.InsightDeck]:
    """Load the latest persisted connections as a deck, or ``None``.

    Returns ``None`` when there is no sidecar yet (no digest has run) or it can't
    be read — the caller then falls back to placeholder data.
    """
    path = latest_insights_file()
    if path is None or not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("could not read insights sidecar: %s", exc)
        return None
    conns = data.get("connections", []) if isinstance(data, dict) else []
    deck = deck_from_dicts(conns)
    return deck if not deck.is_empty else None
