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


def reset_engine() -> None:
    """Drop the cached engine (e.g. after a settings change)."""
    global _ENGINE
    if _ENGINE is not None:
        try:
            _ENGINE.close()
        except Exception:  # noqa: BLE001
            pass
    _ENGINE = None
