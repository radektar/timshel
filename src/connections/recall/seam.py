"""Transcription-time seam for the recall index — lazy, gated, best-effort.

The daemon calls :func:`index_transcript_safe` after writing a transcript, but only
when ``Config.ENABLE_RECALL_INDEX`` is on. A lazy singleton engine avoids reloading
the embedding model per note. Indexing must NEVER disturb transcription, so every
path here swallows its own errors.
"""

from __future__ import annotations

import threading
from pathlib import Path

from src.connections.recall.indexing import IndexingState, run_backfill
from src.logger import logger

_ENGINE = None
# Guards lazy init/reset: three threads reach _engine() (RecallBackfill,
# the transcription thread via index_transcript_safe, UI search). Engine
# construction is SLOW (may download the model), so an unlocked check-then-set
# raced into two engines: two embedding models resident and two writers on the
# same on-disk index.
_ENGINE_LOCK = threading.Lock()
# Shared, process-wide index status: the background backfill writes it, the menu chip
# and the window's partial banner read it (via index_state()).
_STATE = IndexingState()
# True once the app launched the background index — reset_engine only restarts
# it then, so bare resets (tests, CLI) never spawn a surprise indexing thread.
_INDEX_STARTED = False


def _engine():
    global _ENGINE
    if _ENGINE is not None:  # unlocked fast path — plain reference read
        return _ENGINE
    with _ENGINE_LOCK:
        if _ENGINE is None:
            from src.config.config import get_config
            from src.connections.recall.engine import RecallEngine

            _ENGINE = RecallEngine(get_config().TRANSCRIBE_DIR)
        return _ENGINE


def index_state() -> IndexingState:
    """The shared recall index status (Standby/Indexing/Ready/Error + progress)."""
    return _STATE


def start_background_index() -> None:
    """Catch the recall index up to the vault on a daemon thread — non-blocking.

    First launch embeds the whole vault (incremental on later runs), so recall "just
    works" without a manual backfill. Constructing the engine may download the model,
    which is exactly why this runs off the main thread. Best-effort; never raises.
    """
    import threading

    global _INDEX_STARTED
    _INDEX_STARTED = True

    def _run():
        try:
            run_backfill(_engine(), _STATE, incremental=True)
        except Exception as exc:  # noqa: BLE001 - pragma: no cover
            logger.debug("recall background index failed to start: %s", exc)
            _STATE.failed(exc)

    threading.Thread(target=_run, name="RecallBackfill", daemon=True).start()


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


def lexical_only():
    """The ACTIVE engine's mode: True (lexical-only), False (dense), or
    ``None`` when no engine is cached — 'unknown' must stay distinguishable,
    because a False here forecloses the presenter's channel-based inference
    and would apply the dense abstain floor to lexical evidence.
    """
    eng = _ENGINE
    if eng is None:
        return None
    return bool(getattr(eng, "lexical_only", False))


def reset_engine() -> None:
    """Drop the cached engine (e.g. after a settings change).

    Restarts the background index when an engine was active: the reset may
    have closed a store mid-backfill (leaving READY over a partial index),
    and a vault-folder change needs the NEW vault indexed — relaunch was
    otherwise the only path that ever re-triggered the backfill.
    """
    global _ENGINE
    with _ENGINE_LOCK:
        had_engine = _ENGINE is not None
        if _ENGINE is not None:
            try:
                _ENGINE.close()
            except Exception:  # noqa: BLE001
                pass
        _ENGINE = None
    # The digest lane keeps its own engine cache — reset it too, or it keeps
    # an open handle on a store file a fresh engine may have replaced.
    try:
        from src.connections.candidate_assembly import reset_recall_engines

        reset_recall_engines()
    except Exception as exc:  # noqa: BLE001 - pragma: no cover
        logger.debug("recall: digest engine cache reset failed: %s", exc)
    if had_engine and _INDEX_STARTED:
        start_background_index()
