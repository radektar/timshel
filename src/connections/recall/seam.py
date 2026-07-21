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
# Bumped by reset_engine: a construction that started before the bump is
# discarded instead of published, so a reset never has to WAIT on a slow
# in-flight engine build (model load/download) to invalidate it.
_ENGINE_GEN = 0
# Single-flight backfill: one worker at a time, later requests coalesce into
# one more pass — N rapid settings saves must not stack N threads racing on
# the shared IndexingState.
_BACKFILL_LOCK = threading.Lock()
_BACKFILL_ACTIVE = False
_BACKFILL_PENDING = False


def _engine():
    global _ENGINE
    if _ENGINE is not None:  # unlocked fast path — plain reference read
        return _ENGINE
    while True:
        with _ENGINE_LOCK:
            if _ENGINE is not None:
                return _ENGINE
            gen = _ENGINE_GEN
            from src.config.config import get_config
            from src.connections.recall.engine import RecallEngine

            eng = RecallEngine(get_config().TRANSCRIBE_DIR)
            if gen == _ENGINE_GEN:
                _ENGINE = eng
                return eng
        # A reset landed mid-construction: this engine was built from the OLD
        # config — publishing it would resurrect the old vault. Discard and
        # rebuild fresh.
        try:
            eng.close()
        except Exception:  # noqa: BLE001
            pass


def index_state() -> IndexingState:
    """The shared recall index status (Standby/Indexing/Ready/Error + progress)."""
    return _STATE


def start_background_index() -> None:
    """Catch the recall index up to the vault on a daemon thread — non-blocking.

    First launch embeds the whole vault (incremental on later runs), so recall "just
    works" without a manual backfill. Constructing the engine may download the model,
    which is exactly why this runs off the main thread. Best-effort; never raises.

    Single-flight: while a pass is running, further calls just request ONE more
    pass with the then-current engine (a reset mid-run would otherwise stack
    threads all writing the shared IndexingState). ``_STATE.begin()`` fires at
    request time, not after the engine builds — a vault switch must not keep
    showing the OLD vault's READY while the new engine constructs.
    """
    global _INDEX_STARTED, _BACKFILL_ACTIVE, _BACKFILL_PENDING
    _INDEX_STARTED = True
    with _BACKFILL_LOCK:
        if _BACKFILL_ACTIVE:
            _BACKFILL_PENDING = True
            _STATE.begin()
            return
        _BACKFILL_ACTIVE = True
    _STATE.begin()

    def _run():
        global _BACKFILL_ACTIVE, _BACKFILL_PENDING
        while True:
            try:
                run_backfill(_engine(), _STATE, incremental=True)
            except Exception as exc:  # noqa: BLE001 - pragma: no cover
                logger.debug("recall background index failed to start: %s", exc)
                _STATE.failed(exc)
            with _BACKFILL_LOCK:
                if _BACKFILL_PENDING:
                    _BACKFILL_PENDING = False
                    # Narrow the READY flicker: pass N's ready() already fired
                    # inside run_backfill — flip back to INDEXING before the
                    # coalesced pass starts.
                    _STATE.begin()
                    continue  # one more pass with the current engine
                _BACKFILL_ACTIVE = False
                return

    try:
        threading.Thread(target=_run, name="RecallBackfill", daemon=True).start()
    except Exception as exc:  # noqa: BLE001 - thread/fd exhaustion
        # Roll the flag back or every future request would coalesce into a
        # worker that does not exist — backfill dead until relaunch.
        with _BACKFILL_LOCK:
            _BACKFILL_ACTIVE = False
            _BACKFILL_PENDING = False
        _STATE.failed(exc)
        logger.warning("recall: could not start backfill thread: %s", exc)


# Heal throttling: one destructive rebuild per window. A persistently
# corrupting disk (or any misclassification) must not loop wipe → full
# re-embed at CPU-melting cost while the user retries ⌘K.
# Sentinel is -COOLDOWN, not 0.0: time.monotonic() is time since BOOT, and a
# 0.0 sentinel would throttle the very first heal during the first two
# minutes of uptime — exactly the post-reboot window where an iCloud-synced
# store is most likely to surface corruption.
_HEAL_COOLDOWN_S = 120.0
_LAST_HEAL_MONO = -_HEAL_COOLDOWN_S


def _heal_if_corrupt(exc, eng) -> bool:
    """Rebuild the store when the FILE itself is bad at query time.

    An iCloud-synced vault can rewrite pages under us: the store then opens
    cleanly but every operation raises 'database disk image is malformed' —
    permanently, across relaunches, with no CLI escape hatch in the bundle.

    NEVER heals on: OperationalError (locked/busy — transient),
    ProgrammingError ('Cannot operate on a closed database' — that's a reset
    closing the store under an in-flight op, and this PR's backfill treats it
    as exactly that), an engine that is no longer the published one (the
    failure belongs to a closed predecessor — wiping the fresh engine's
    healthy store would be the bug), or within the cooldown window.
    Returns True when a rebuild was triggered (backfill restarted).
    """
    import sqlite3
    import time

    global _LAST_HEAL_MONO

    if (
        not isinstance(exc, sqlite3.DatabaseError)
        or isinstance(exc, sqlite3.OperationalError)
        or isinstance(exc, sqlite3.ProgrammingError)
    ):
        return False
    if eng is None:
        return False
    rebuild = getattr(eng, "rebuild_store", None)
    if rebuild is None:
        return False
    # Identity check AND rebuild under _ENGINE_LOCK: an unlocked check-then-act
    # let a concurrent reset publish a fresh engine between the check and the
    # rebuild — the stale heal then unlinked the store the fresh engine had
    # open (its whole backfill written into an orphaned inode). Bounded wait:
    # if the lock is busy the engine world is changing anyway — skip.
    if not _ENGINE_LOCK.acquire(timeout=2.0):
        return False
    failed = False
    try:
        if eng is not _ENGINE:
            return False
        now = time.monotonic()
        if now - _LAST_HEAL_MONO < _HEAL_COOLDOWN_S:
            logger.warning(
                "recall: store corrupt again within cooldown (%s) — not rebuilding",
                exc,
            )
            return False
        _LAST_HEAL_MONO = now
        logger.warning("recall: store corrupt at query time (%s); rebuilding", exc)
        try:
            rebuild()
        except Exception as exc2:  # noqa: BLE001
            logger.warning("recall: store rebuild failed: %s", exc2)
            failed = True
    finally:
        _ENGINE_LOCK.release()
    if failed:
        # A failed rebuild leaves the engine holding a CLOSED store — every
        # further op raises ProgrammingError, which heal rightly ignores, so
        # nothing would EVER retry. Drop the wedged engine; the next search
        # (or the restarted backfill) lazily builds a fresh one.
        reset_engine()
        return False
    # The digest lane's cached engine still holds a handle on the deleted
    # corrupt inode — same hazard reset_engine guards against.
    try:
        from src.connections.candidate_assembly import reset_recall_engines

        reset_recall_engines()
    except Exception as exc2:  # noqa: BLE001 - pragma: no cover
        logger.debug("recall: digest engine cache reset failed: %s", exc2)
    start_background_index()
    return True


def index_transcript_safe(path) -> None:
    """Index one freshly-written transcript. Best-effort; logs and swallows failures."""
    eng = None
    try:
        eng = _engine()
        eng.index_path(Path(path))
    except Exception as exc:  # noqa: BLE001
        logger.debug("recall index_transcript failed: %s", exc)
        _heal_if_corrupt(exc, eng)


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
        _heal_if_corrupt(exc, eng)
        return [], 0.0, "unavailable"
    try:
        results, confidence = eng.search_scored(query, k=k)
        return results, confidence, "ok"
    except Exception as exc:  # noqa: BLE001
        logger.debug("recall search failed: %s", exc)
        _heal_if_corrupt(exc, eng)
        return [], 0.0, "unavailable"


def search_safe(query: str, k: int = 8):
    """Back-compat 2-tuple ``(results, confidence)`` wrapper over :func:`search_detailed`."""
    results, confidence, _status = search_detailed(query, k=k)
    return results, confidence


def _deferred_reset() -> None:
    """Finish a reset whose 1s lock acquire timed out: retire whatever engine
    is published once the slow holder (builder or heal) releases the lock,
    then re-request a backfill pass so the index converges on the new config."""
    global _ENGINE
    with _ENGINE_LOCK:
        old = _ENGINE
        _ENGINE = None
    if old is not None:
        try:
            old.close()
        except Exception:  # noqa: BLE001
            pass
    try:
        from src.connections.candidate_assembly import reset_recall_engines

        reset_recall_engines()
    except Exception as exc:  # noqa: BLE001 - pragma: no cover
        logger.debug("recall: digest engine cache reset failed: %s", exc)
    if _INDEX_STARTED:
        start_background_index()


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
    global _ENGINE, _ENGINE_GEN
    _ENGINE_GEN += 1  # invalidate any in-flight construction (old config)
    # Bounded wait: if a slow lock-holder is in the way (model download in a
    # builder, or a heal mid-rebuild), do NOT beachball the caller (settings
    # save runs on the main thread).
    acquired = _ENGINE_LOCK.acquire(timeout=1.0)
    old = None
    if acquired:
        try:
            old = _ENGINE
            _ENGINE = None
        finally:
            _ENGINE_LOCK.release()
    else:
        # NOT acquired. Touching _ENGINE unlocked could steal-and-close a
        # freshly-published valid engine — and skipping the swap outright is
        # wrong too: the holder may be a HEAL rebuilding the still-published
        # OLD-config engine, which would then survive this reset and keep
        # serving (and re-indexing) the old vault forever. Defer the swap to
        # a small daemon thread that waits out the holder and retires
        # whatever is published then.
        threading.Thread(
            target=_deferred_reset, name="RecallDeferredReset", daemon=True
        ).start()
    if old is not None:
        try:
            old.close()
        except Exception:  # noqa: BLE001
            pass
    # The digest lane keeps its own engine cache — reset it too, or it keeps
    # an open handle on a store file a fresh engine may have replaced.
    try:
        from src.connections.candidate_assembly import reset_recall_engines

        reset_recall_engines()
    except Exception as exc:  # noqa: BLE001 - pragma: no cover
        logger.debug("recall: digest engine cache reset failed: %s", exc)
    # Gate on _INDEX_STARTED alone: gating on had_engine too would leave
    # recall permanently unindexed when the INITIAL build failed (transient
    # lock at launch), the user fixed settings, and reset found no engine.
    if _INDEX_STARTED:
        start_background_index()
