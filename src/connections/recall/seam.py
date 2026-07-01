"""Transcription-time seam for the recall index — lazy, gated, best-effort.

The daemon calls :func:`index_transcript_safe` after writing a transcript, but only
when ``Config.ENABLE_RECALL_INDEX`` is on. A lazy singleton engine avoids reloading
the embedding model per note. Indexing must NEVER disturb transcription, so every
path here swallows its own errors.
"""

from __future__ import annotations

from pathlib import Path

from src.logger import logger

_ENGINE = None


def _engine():
    global _ENGINE
    if _ENGINE is None:
        from src.config.config import get_config
        from src.connections.recall.engine import RecallEngine

        _ENGINE = RecallEngine(get_config().TRANSCRIBE_DIR)
    return _ENGINE


def index_transcript_safe(path) -> None:
    """Index one freshly-written transcript. Best-effort; logs and swallows failures."""
    try:
        _engine().index_path(Path(path))
    except Exception as exc:  # noqa: BLE001
        logger.debug("recall index_transcript failed: %s", exc)


def search_detailed(query: str, k: int = 8):
    """Query the recall index and report a coarse status so the UI can be honest.

    Returns ``(results, confidence, status)`` where ``status`` is:
      - ``"ok"``          — the index was searched (results may still be empty = a
                            genuine no-match → the UI's honest abstinence copy);
      - ``"empty"``       — nothing indexed yet (needs a backfill) — NOT a no-match;
      - ``"unavailable"`` — engine/model/deps not ready, or search raised.

    The distinction matters: a hard failure must never be dressed up as "nothing in
    your notes about X". Best-effort throughout — never raises into the caller.
    """
    try:
        eng = _engine()
    except Exception as exc:  # noqa: BLE001
        logger.debug("recall engine unavailable: %s", exc)
        return [], 0.0, "unavailable"
    try:
        if eng.count() == 0:
            return [], 0.0, "empty"
    except Exception as exc:  # noqa: BLE001
        logger.debug("recall count failed: %s", exc)
        return [], 0.0, "unavailable"
    try:
        results, confidence = eng.search_scored(query, k=k)
        return results, confidence, "ok"
    except Exception as exc:  # noqa: BLE001
        logger.debug("recall search failed: %s", exc)
        return [], 0.0, "unavailable"


def search_safe(query: str, k: int = 8):
    """Back-compat 2-tuple ``(results, confidence)`` wrapper over :func:`search_detailed`."""
    results, confidence, _status = search_detailed(query, k=k)
    return results, confidence


def reset_engine() -> None:
    """Drop the cached engine (e.g. after a settings change)."""
    global _ENGINE
    if _ENGINE is not None:
        try:
            _ENGINE.close()
        except Exception:  # noqa: BLE001
            pass
    _ENGINE = None
