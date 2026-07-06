"""Scheduling + orchestration for the connection-synthesis digest.

The digest is a *calm weekly container* that can be pulled forward when enough
new material arrives (pattern-triggered), never more often than a floor gap.
The heavy run hangs off the existing 30s periodic daemon tick: when not due,
:func:`run_digest_if_due` returns in microseconds.

State split:
  * ``last_digest_at`` / ``last_digest_path`` — persisted (survives restarts).
  * ``new_notes`` — an in-memory counter bumped by :func:`enqueue_connection_analysis`
    at the post-transcript seam (no IO, no API there). Resetting to 0 on restart
    only loses mid-week *escalation*; the weekly cadence still fires from the
    persisted timestamp.
"""

from __future__ import annotations

import fcntl
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from src.config import config
from src.logger import logger


class DigestScheduler:
    """Decides when a digest is due and records when one ran."""

    def __init__(self, state_file: Path):
        self.state_file = Path(state_file)
        self.last_digest_at: Optional[str] = None
        self.last_digest_path: Optional[str] = None
        self.new_notes: int = 0
        self._load()

    def _load(self) -> None:
        try:
            if self.state_file.exists():
                data = json.loads(self.state_file.read_text(encoding="utf-8"))
                self.last_digest_at = data.get("last_digest_at")
                self.last_digest_path = data.get("last_digest_path")
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("DigestScheduler state load failed (%s)", exc)

    def _save(self) -> None:
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.state_file.with_suffix(".json.tmp")
            tmp.write_text(
                json.dumps(
                    {
                        "last_digest_at": self.last_digest_at,
                        "last_digest_path": self.last_digest_path,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            os.replace(tmp, self.state_file)
        except OSError as exc:
            logger.error("DigestScheduler state save failed: %s", exc)

    def register_new_notes(self, count: int = 1) -> None:
        self.new_notes += count

    def _elapsed_days(self, now: datetime) -> Optional[float]:
        if not self.last_digest_at:
            return None
        try:
            prev = datetime.fromisoformat(self.last_digest_at)
        except ValueError:
            return None
        return (now - prev).total_seconds() / 86400.0

    def is_due(self, now: datetime) -> bool:
        if self.new_notes <= 0:
            return False
        elapsed = self._elapsed_days(now)
        if elapsed is None:  # never run -> due once there is new material
            return True
        if elapsed >= config.CONNECTIONS_DIGEST_INTERVAL_DAYS:
            return True
        if (
            self.new_notes >= config.CONNECTIONS_PATTERN_TRIGGER_MIN
            and elapsed >= config.CONNECTIONS_MIN_GAP_DAYS
        ):
            return True
        return False

    def mark_ran(self, now: datetime, path: Optional[Path] = None) -> None:
        self.last_digest_at = now.isoformat(timespec="seconds")
        if path is not None:
            self.last_digest_path = str(path)
        self.new_notes = 0
        self._save()


# --------------------------------------------------------------------------- #
# Process-singleton accessor
# --------------------------------------------------------------------------- #
_scheduler: Optional[DigestScheduler] = None


def get_scheduler() -> DigestScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = DigestScheduler(config.CONNECTIONS_STATE_FILE)
    return _scheduler


def reset_scheduler_for_tests() -> None:
    """Drop the cached singleton (tests configure a fresh state file)."""
    global _scheduler
    _scheduler = None


# --------------------------------------------------------------------------- #
# Seam hook (cheap, no API) + the heavy daemon-driven run
# --------------------------------------------------------------------------- #
def enqueue_connection_analysis(transcriber: object = None) -> None:
    """Called right after a transcript is finalized. Bumps a counter only."""
    get_scheduler().register_new_notes(1)


def _acquire_digest_lock() -> Optional[int]:
    """Non-blocking exclusive lock; returns fd, or None if a run is in flight."""
    lock_path = Path(config.DIGEST_LOCK_FILE)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        return None
    return fd


def _release_digest_lock(fd: int) -> None:
    try:
        fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def _set_digest_ready(transcriber: object, path: Path) -> None:
    state = getattr(transcriber, "state", None)
    if state is not None and hasattr(state, "digest_ready"):
        try:
            state.digest_ready = path.name
        except Exception as exc:  # noqa: BLE001
            logger.debug("could not set digest_ready: %s", exc)


def _record_digest_metrics(
    synthesizer, candidates, connections, path, verifier=None, verdict_dropped=0
) -> None:
    """Append the per-digest cost + coverage record. Best-effort, never raises.

    ``path`` may be ``None`` (paid run that wrote no digest — synthesis found
    nothing, or verdict dropped everything). ``verifier`` is passed only when a
    verdict actually completed; ``verdict_dropped`` is the real number removed
    by :func:`~src.connections.verdict.apply_verdicts` (threaded in, not
    re-derived, so the ledger can never disagree with the digest).
    """
    from src.connections.insight_metrics import record_digest_metrics

    record_digest_metrics(
        model=getattr(synthesizer, "model", ""),
        usage=getattr(synthesizer, "last_usage", None),
        candidates=len(candidates.notes),
        connections=len(connections),
        connection_types=[c.type for c in connections],
        digest=path.name if path is not None else "",
        tester_mode=bool(getattr(config, "PROTOTYPE_TESTER_MODE", False)),
        verdict_model=getattr(verifier, "model", "") if verifier is not None else "",
        verdict_usage=(
            getattr(verifier, "last_usage", None) if verifier is not None else None
        ),
        verdict_dropped=verdict_dropped,
    )


def run_digest_if_due(
    transcriber: object = None, force: bool = False
) -> Optional[Path]:
    """Generate a digest when due. Safe to call every periodic tick.

    Returns the digest path when one was written, else ``None``. Never raises
    into the daemon loop — synthesis must never disturb transcription.
    """
    # Lazy imports keep `import src.connections` light (no anthropic/pydantic
    # unless a digest actually runs) and avoid import cycles with transcriber.
    from src.connections.candidate_assembly import assemble_candidates
    from src.connections.digest_writer import write_digest_note
    from src.connections.dismissals import DismissalStore
    from src.connections.synthesis import get_synthesizer
    from src.summarizer import APIBillingError, detect_language

    scheduler = get_scheduler()
    now = datetime.now()
    if not force and not scheduler.is_due(now):
        return None
    if getattr(transcriber, "_ai_disabled_reason", None):
        return None

    synthesizer = get_synthesizer()
    if synthesizer is None:
        return None

    lock_fd = _acquire_digest_lock()
    if lock_fd is None:
        logger.debug("digest already running; skipping this tick")
        return None
    try:
        vault = Path(config.TRANSCRIBE_DIR)
        dismissals = DismissalStore(vault).load()
        dismissals.sync_frontmatter_dismissals()
        candidates = assemble_candidates(
            vault,
            scheduler.last_digest_at,
            dismissals,
            inject_bridges=config.SYNTHESIS_BRIDGE_COUNT,
            inject_entities=config.SYNTHESIS_ENTITY_COUNT,
            inject_dense=config.SYNTHESIS_DENSE_COUNT,
            inject_graph=config.SYNTHESIS_GRAPH_COUNT,
            inject_stance=config.SYNTHESIS_STANCE_COUNT,
        )
        if len(candidates.notes) < 2:
            logger.info("synthesis: fewer than 2 candidate notes, skipping")
            return None

        language = detect_language(
            " ".join(n.summary_md for n in candidates.notes)[:5000]
        )
        try:
            result = synthesizer.synthesize(
                candidates, dismissals.dismissed_descriptions(), language
            )
        except APIBillingError as exc:
            disable_ai = getattr(transcriber, "_disable_ai", None)
            if callable(disable_ai):
                disable_ai("billing", exc)
            return None
        if result is None:
            return None  # recoverable error -> retry next tick, don't reset

        known = {n.basename for n in candidates.notes}
        connections = [
            c
            for c in result.connections
            if len(c.notes) >= 2 and all(b in known for b in c.notes)
        ]
        if not connections:
            # Synthesis ran and was PAID for but produced nothing — a real
            # H1/H4 data point (a paid run that yielded zero connections), so
            # record it, exactly like the verdict-all-dropped branch below.
            logger.info("synthesis: no genuine connections this run")
            scheduler.mark_ran(now)  # reset weekly clock; write no digest
            _record_digest_metrics(synthesizer, candidates, [], None)
            return None

        # Verdict pass (prototype): verify the proposed connections against
        # fuller note text BEFORE anything is written, so the digest, the
        # sidecar and the action instrument only ever see survivors. Fail
        # OPEN on any recoverable problem — verification must never lose a
        # digest to an API hiccup.
        verdict_verifier = None  # set only when a verdict actually completed
        verdict_dropped = 0
        if getattr(config, "VERDICT_ENABLED", False):
            from src.connections.verdict import apply_verdicts, get_verifier

            verifier = get_verifier()
            if verifier is not None:
                try:
                    verdicts = verifier.verify(
                        connections,
                        {n.basename: n for n in candidates.notes},
                        language,
                    )
                except APIBillingError as exc:
                    disable_ai = getattr(transcriber, "_disable_ai", None)
                    if callable(disable_ai):
                        disable_ai("billing", exc)
                    return None
                # verify() returns None on a recoverable error (fail open): keep
                # all, and do NOT stamp a verdict model/cost onto the ledger — a
                # verdict that never completed must not read as one that ran clean.
                if verdicts is not None:
                    kept = apply_verdicts(connections, verdicts)
                    verdict_dropped = len(connections) - len(kept)
                    if verdict_dropped:
                        logger.info(
                            "verdict: dropped %d/%d connections",
                            verdict_dropped,
                            len(connections),
                        )
                    connections = kept
                    verdict_verifier = verifier

        if not connections:
            # Every proposal died in verification — a legitimate, PAID outcome:
            # record the metrics (H1/H4 data point), reset the clock, write nothing.
            logger.info("verdict: no connections survived verification")
            scheduler.mark_ran(now)
            _record_digest_metrics(
                synthesizer,
                candidates,
                [],
                None,
                verifier=verdict_verifier,
                verdict_dropped=verdict_dropped,
            )
            return None

        path, conn_meta = write_digest_note(connections, len(candidates.notes))
        dismissals.record_digest(path, conn_meta)
        scheduler.mark_ran(now, path)
        _record_digest_metrics(
            synthesizer,
            candidates,
            connections,
            path,
            verifier=verdict_verifier,
            verdict_dropped=verdict_dropped,
        )
        _set_digest_ready(transcriber, path)
        return path
    finally:
        _release_digest_lock(lock_fd)
