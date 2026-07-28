"""Scheduling + orchestration for the connection-synthesis digest.

The digest is a *calm weekly container* that can be pulled forward when enough
new material arrives (pattern-triggered), never more often than a floor gap.
The heavy run hangs off the existing 30s periodic daemon tick: when not due,
:func:`run_digest_if_due` returns in microseconds.

State (one JSON file, shared by the resident app and the CLI dogfood scripts):
  * ``last_digest_at`` / ``last_digest_path`` — persisted.
  * ``new_notes`` — persisted trigger counter: live bumps from
    :func:`enqueue_connection_analysis` at the post-transcript seam plus the
    clamped backfill leftover written by :meth:`DigestScheduler.mark_ran`
    (so a restart cannot strand the backlog).
  * ``seen_note_keys`` / ``seen_epoch`` — the notes digests have consumed.
    Writers merge with the file (union within an epoch); ``reset_seen`` bumps
    the epoch so a deliberate forget propagates instead of being resurrected
    by another process's union.
"""

from __future__ import annotations

import fcntl
import json
import os
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Set

from src.config import config
from src.logger import logger

# Onboarding first-digest model — chosen by the 2026-07-24 blind eval on the
# real corpus: never returned an empty digest (Opus did, on the newest
# window), ~2x faster, ~half the cost. Injected per-run; the weekly default
# (tester_mode -> Opus) is untouched.
ONBOARDING_DIGEST_MODEL = "claude-sonnet-5"
# Owner's cost ceiling: at most this many PAID windows in one first session.
ONBOARDING_MAX_WINDOWS = 2
# How long a first-session hold on the automatic digest stays valid. Long
# enough for an import + a dialog the user may leave open; short enough that
# a crash mid-flow cannot freeze weekly digests (the hold self-expires).
AUTO_DIGEST_HOLD_MINUTES = 60


class DigestScheduler:
    """Decides when a digest is due and records when one ran."""

    def __init__(self, state_file: Path):
        self.state_file = Path(state_file)
        self.last_digest_at: Optional[str] = None
        self.last_digest_path: Optional[str] = None
        self.new_notes: int = 0
        # note_key() of every note a digest has already consumed. None means
        # "not migrated yet" — the run path seeds it from the vault (everything
        # dated before last_digest_at) exactly once.
        self.seen_note_keys: Optional[Set[str]] = None
        # Bumped by reset_seen: lets other processes tell "the set shrank on
        # purpose, adopt it" from "my union is newer, keep merging".
        self.seen_epoch: int = 0
        # Keys explicitly un-seen (retranscribed notes). Within one epoch the
        # seen-set is add-only, so a plain discard would be undone by any
        # stale holder's union — a tombstone survives the union and is lifted
        # only when a digest actually consumes the key again.
        self.unseen_tombstones: Set[str] = set()
        # In-memory only: when the local gate skipped a low-potential run, so
        # the 30s tick doesn't re-assemble the corpus until the cooldown ends
        # (or new material arrives). The signature dedups the telemetry rows:
        # one gate-skip record per distinct skipped window, not one per hour.
        self._gate_skip_at: Optional[datetime] = None
        self._gate_skip_sig: Optional[frozenset] = None
        # First-session hold on the automatic weekly path (see
        # suspend_auto_digest): in-memory flag for this process plus a
        # PERSISTED deadline so other processes (daemon, relaunched app)
        # honour it and a crash cannot freeze the cadence forever.
        self.auto_digest_suspended: bool = False
        self.auto_digest_hold_until: Optional[str] = None
        # True only for the process that set or cleared the hold. Every other
        # writer adopts the disk value before saving, so an unrelated write
        # (a CLI's unsee after a transcription) can neither wipe a live hold
        # nor resurrect one the owner has released.
        self._hold_owned: bool = False
        self._load()

    def suspend_auto_digest(self, now: Optional[datetime] = None) -> None:
        """Hold the automatic path — PERSISTED, so every process honours it.

        The hold protects the user's consent: while the first-session flow
        runs (import → offer dialog → paid run), no tick may fire a weekly
        digest over the freshly imported notes. An in-memory flag only
        reached this process; a LaunchAgent daemon (same app_core tick) or
        this app relaunched after a crash would happily pay. The stored
        deadline also self-expires, so a crash mid-dialog cannot freeze
        weekly digests forever.
        """
        stamp = (now or datetime.now()) + timedelta(minutes=AUTO_DIGEST_HOLD_MINUTES)
        self._merge_disk_seen()
        self.auto_digest_suspended = True
        self.auto_digest_hold_until = stamp.isoformat(timespec="seconds")
        self._hold_owned = True  # our value wins this write
        self._save()

    def resume_auto_digest(self) -> None:
        self._merge_disk_seen()
        self.auto_digest_suspended = False
        self.auto_digest_hold_until = None
        self._hold_owned = True  # releasing is authoritative too
        self._save()

    def auto_digest_on_hold(self, now: datetime) -> bool:
        """True while a first-session hold is active (this process or another).

        Reads the persisted deadline so a separate daemon process sees the
        hold too; an expired deadline is ignored (and lazily cleared).
        """
        if self.auto_digest_suspended:
            return True
        data = self._read_disk_state() or {}
        until = data.get("auto_digest_hold_until")
        if not isinstance(until, str) or not until:
            return False
        try:
            deadline = datetime.fromisoformat(until)
        except ValueError:
            return False
        return now < deadline

    def settle_after_import(self, now: datetime) -> None:
        """Make the post-import state CHEAP and consistent, immediately.

        Called the moment the first-session import finishes — before the
        offer dialog, before anything can fail. The import bumps the
        new-notes counter per file and a fresh install has no clock, so
        every later exit path (transient API error, crash, "Later", no key,
        low potential) would otherwise leave ``is_due()`` true and the next
        tick would pay for a digest the user never approved.

        Starts the weekly clock (only if never started) and clamps the
        counter below the pattern trigger — the same rule
        :meth:`mark_ran` applies to a backfill backlog, so a bulk import
        cannot escalate to the every-2-days cadence either.
        """
        # refresh_from_disk (not a hand-rolled read): it adopts a NEWER clock
        # as well as the seen-set, so this save cannot roll the cadence back
        # to a stale in-memory timestamp.
        self.refresh_from_disk()
        if self.last_digest_at is None:
            self.last_digest_at = now.isoformat(timespec="seconds")
        self.new_notes = min(self.new_notes, config.CONNECTIONS_PATTERN_TRIGGER_MIN - 1)
        self._save()

    def _read_disk_state(self) -> Optional[dict]:
        """Parse the state file, or None. The ONE place the schema is read."""
        try:
            if not self.state_file.exists():
                return None
            data = json.loads(self.state_file.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else None
        except (json.JSONDecodeError, OSError) as exc:
            logger.debug("digest state unreadable (%s)", exc)
            return None

    def _load(self) -> None:
        data = self._read_disk_state()
        if data is None:
            return
        try:
            self.last_digest_at = data.get("last_digest_at")
            self.last_digest_path = data.get("last_digest_path")
            raw_seen = data.get("seen_note_keys")
            self.seen_note_keys = set(raw_seen) if raw_seen is not None else None
            self.seen_epoch = int(data.get("seen_epoch", 0) or 0)
            self.unseen_tombstones = set(data.get("unseen_tombstones", []) or [])
            hold = data.get("auto_digest_hold_until")
            self.auto_digest_hold_until = hold if isinstance(hold, str) else None
            # Persisted pending (backfill leftover): without it, a restart
            # would strand the backlog — is_due() needs a non-zero counter.
            self.new_notes = int(data.get("new_notes", 0) or 0)
        except (TypeError, ValueError) as exc:
            logger.warning("DigestScheduler state load failed (%s)", exc)

    def _merge_disk_seen(self) -> None:
        """Reconcile the in-memory seen-set with the on-disk one.

        Another process (the resident app vs the ``magic_digest`` CLI) may
        have consumed a window since our load; a blind write would un-see it
        and re-digest those notes. Within one epoch keys are add-only, so
        union is the safe merge. A HIGHER epoch on disk means another process
        deliberately reset the set — adopt it wholesale instead of unioning
        our stale keys back (the resurrection bug); a LOWER one means we are
        the resetter and must not re-import what we just forgot.
        """
        try:
            data = self._read_disk_state()
            if data is None:
                return
            raw = data.get("seen_note_keys")
            disk_epoch = int(data.get("seen_epoch", 0) or 0)
            disk_tombstones = set(data.get("unseen_tombstones", []) or [])
            if disk_epoch > self.seen_epoch:
                if raw is not None:
                    self.seen_note_keys = set(raw)
                self.seen_epoch = disk_epoch
                self.unseen_tombstones = disk_tombstones
            elif disk_epoch == self.seen_epoch:
                if raw:
                    if self.seen_note_keys is None:
                        self.seen_note_keys = set()
                    self.seen_note_keys |= set(raw)
                # Tombstones are ADOPTED from disk, not unioned: a lift (the
                # key was genuinely re-consumed by a digest, possibly in a CLI
                # process) must propagate to stale holders, or their memory
                # copy would resurrect the tombstone on every write and force
                # endless re-digests of that note. Adoption is safe because
                # every tombstone writer (unsee) saves synchronously right
                # after its own merge, and only the transcribing daemon ever
                # un-sees — there is a single tombstone producer.
                self.unseen_tombstones = disk_tombstones
            # The first-session hold belongs to whoever set it: a writer that
            # doesn't own it adopts the disk value, so an unrelated save (a
            # CLI's unsee) can neither clear a live hold — letting that
            # process pay for a weekly digest mid-onboarding — nor write a
            # released one back and freeze the cadence for the whole TTL.
            if not self._hold_owned:
                hold = data.get("auto_digest_hold_until")
                self.auto_digest_hold_until = hold if isinstance(hold, str) else None
            # A tombstoned key stays un-seen no matter which side's union
            # re-added it — until mark_ran lifts the tombstone on consumption.
            # Runs even with no seen-set on disk (pre-migration): the
            # tombstones must still be adopted so a later migration seeding
            # the key as seen-by-date cannot clobber a pre-migration unsee.
            if self.seen_note_keys:
                self.seen_note_keys -= self.unseen_tombstones
        except (TypeError, ValueError) as exc:
            # Same tolerance as _load: a hand-mangled value must degrade to
            # "merge skipped", never blow up mark_ran after a PAID run.
            logger.debug("seen-set disk merge skipped (%s)", exc)

    def refresh_from_disk(self) -> None:
        """Pull other processes' progress before READING the seen-set.

        The write path always merges, but a resident app that only ever reads
        its stale in-memory set would re-pay for windows a CLI run already
        consumed. Called at the top of every assembly (run + preview): adopts
        the disk seen-set (epoch-aware) and a newer ``last_digest_at``.
        """
        self._merge_disk_seen()
        data = self._read_disk_state()
        if data is None:
            return
        disk_at = data.get("last_digest_at")
        if isinstance(disk_at, str) and disk_at > (self.last_digest_at or ""):
            self.last_digest_at = disk_at
            self.last_digest_path = data.get("last_digest_path")

    def _save(self) -> None:
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            payload: dict = {
                "last_digest_at": self.last_digest_at,
                "last_digest_path": self.last_digest_path,
                "new_notes": int(self.new_notes),
                "seen_epoch": int(self.seen_epoch),
                "unseen_tombstones": sorted(self.unseen_tombstones),
                "auto_digest_hold_until": self.auto_digest_hold_until,
            }
            if self.seen_note_keys is not None:
                payload["seen_note_keys"] = sorted(self.seen_note_keys)
            tmp = self.state_file.with_suffix(".json.tmp")
            tmp.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            os.replace(tmp, self.state_file)
        except OSError as exc:
            logger.error("DigestScheduler state save failed: %s", exc)

    def register_new_notes(self, count: int = 1) -> None:
        self.new_notes += count
        # Fresh material re-opens the gate immediately — the cooldown only
        # guards against re-scoring the same unchanged corpus every tick.
        self._gate_skip_at = None

    def init_seen(self, keys: Set[str]) -> None:
        """One-time seed of the seen-set (date-based state migration)."""
        self.seen_note_keys = set(keys)
        self._merge_disk_seen()
        self._save()

    def clear_pending(self) -> None:
        """Zero a stale trigger counter (registered material that no longer
        exists unseen — muted, deleted, or deduped notes)."""
        self._merge_disk_seen()  # never clobber another process's keys
        self.new_notes = 0
        self._save()

    def unsee(self, key: str) -> None:
        """Un-see one key: a freshly (re)written transcript is new material by
        definition, even when its fingerprint was consumed before (user
        deleted the note and re-transcribed the same recording).

        Full sync-protocol participant: syncs from disk first (a stale or
        pre-migration in-memory set must neither miss the key nor clobber
        other processes' progress on save), and records a TOMBSTONE rather
        than a bare discard — within an epoch the seen-set is add-only, so a
        discard alone would be silently undone by any stale holder's union.
        The tombstone also outlives a later migration seeding the key as
        seen-by-date. ``mark_ran`` lifts it when a digest truly re-consumes
        the note.
        """
        self._merge_disk_seen()
        self.unseen_tombstones.add(key)
        if self.seen_note_keys:
            self.seen_note_keys.discard(key)
        self._save()

    def reset_seen(self, keys: Optional[Set[str]] = None) -> None:
        """Explicitly REPLACE the seen-set — the archive re-digest seam.

        Unlike :meth:`init_seen`/:meth:`mark_ran` this does NOT union the
        on-disk state: the whole point is to forget. Bumping the epoch makes
        the forget PROPAGATE — any process still holding the old set adopts
        the reset at its next disk sync instead of resurrecting it.
        """
        data = self._read_disk_state() or {}
        try:
            disk_epoch = int(data.get("seen_epoch", 0) or 0)
        except (TypeError, ValueError):
            disk_epoch = 0
        self.seen_epoch = max(self.seen_epoch, disk_epoch) + 1
        self.seen_note_keys = set(keys or set())
        self.unseen_tombstones = set()  # everything is unseen now anyway
        self._save()

    def note_gate_skip(self, now: datetime) -> None:
        self._gate_skip_at = now

    def gate_cooldown_active(self, now: datetime) -> bool:
        if self._gate_skip_at is None:
            return False
        elapsed = (now - self._gate_skip_at).total_seconds()
        return bool(elapsed < config.DIGEST_GATE_COOLDOWN_MINUTES * 60)

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

    def mark_ran(
        self,
        now: datetime,
        path: Optional[Path] = None,
        seen_keys: Optional[Set[str]] = None,
        pending: int = 0,
    ) -> None:
        """Record a completed (paid) run.

        ``seen_keys`` — the consumed window's note keys, added to the seen-set.
        ``pending`` — unseen notes left over by the window cap (a backfill
        catching up): kept as the new-notes counter so the weekly cadence keeps
        firing until the backlog drains, even with no new recordings. Clamped
        BELOW the pattern-trigger threshold: a backlog alone must never
        escalate to the every-2-days cadence (that would multiply cost after a
        bulk import) — only genuinely new recordings, which bump the counter on
        top via :meth:`register_new_notes`, can.
        """
        self.last_digest_at = now.isoformat(timespec="seconds")
        if path is not None:
            self.last_digest_path = str(path)
        # Sync from disk FIRST, union our consumed window AFTER: if another
        # process bumped the epoch (reset) mid-run, adoption replaces the set —
        # our window must be re-added on top, not lost in the swap. Consuming
        # a key also lifts its un-see tombstone: the note really is seen again.
        self._merge_disk_seen()
        if seen_keys:
            if self.seen_note_keys is None:
                self.seen_note_keys = set()
            self.unseen_tombstones -= set(seen_keys)
            self.seen_note_keys |= set(seen_keys)
        self.new_notes = max(
            0, min(int(pending), config.CONNECTIONS_PATTERN_TRIGGER_MIN - 1)
        )
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
def enqueue_connection_analysis(
    transcriber: object = None, md_path: Optional[Path] = None
) -> None:
    """Called right after a transcript is finalized (no API, tiny IO).

    Bumps the trigger counter; when the note path is given, also un-sees its
    fingerprint — a freshly written transcript is new digest material even if
    the same recording was digested before (delete-and-retranscribe), which
    the grow-only seen-set would otherwise hide forever.
    """
    scheduler = get_scheduler()
    scheduler.register_new_notes(1)
    if md_path is None:
        return
    try:
        from src.markdown_frontmatter import parse_frontmatter

        md_path = Path(md_path)
        fp = parse_frontmatter(md_path.read_text(encoding="utf-8")).get("fingerprint")
        scheduler.unsee(fp or f"name:{md_path.stem}")
    except Exception as exc:  # noqa: BLE001 - best-effort, never disturb the seam
        logger.debug("could not unsee fresh note %s: %s", md_path, exc)


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
    synthesizer,
    candidates,
    connections,
    path,
    verifier=None,
    verdict_dropped=0,
    onboarding=False,
    window_fallback=False,
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
        onboarding=onboarding,
        window_fallback=window_fallback,
    )


_migration_lock = threading.Lock()


def _ensure_seen_migrated(scheduler: DigestScheduler, vault: Path) -> Set[str]:
    """Seed the seen-set once, mirroring the legacy window's reach.

    Digest ran before: everything dated before the last digest — plus undated
    notes, which the date window could never select — is marked seen.
    Never ran (fresh install on a populated vault): everything EXCEPT the
    newest ``FIRST_RUN_WINDOW`` notes is marked seen, exactly the reach of the
    legacy first run. Without this, a fresh install would auto-drain the whole
    archive through paid weekly runs nobody asked for.

    Either way, behaviour is unchanged at the moment of upgrade, while notes
    that appear in the vault LATER (a backfill of old recordings) count as new
    material regardless of their recording date. Locked: the menu preview
    thread and the daemon tick share the singleton, and a double migration
    would double-scan the vault and race the state write.
    """
    if scheduler.seen_note_keys is not None:
        return scheduler.seen_note_keys
    with _migration_lock:
        if scheduler.seen_note_keys is not None:
            return scheduler.seen_note_keys
        from src.connections.candidate_assembly import (
            FIRST_RUN_WINDOW,
            load_corpus,
            note_key,
        )

        corpus = load_corpus(vault)
        if scheduler.last_digest_at:
            cutoff = scheduler.last_digest_at[:10]
            seen = {note_key(n) for n in corpus if not n.date or n.date < cutoff}
        else:
            newest = sorted(corpus, key=lambda n: n.date, reverse=True)[
                :FIRST_RUN_WINDOW
            ]
            seen = {note_key(n) for n in corpus} - {note_key(n) for n in newest}
        scheduler.init_seen(seen)
        logger.info(
            "digest seen-set migrated: %d notes marked as already seen", len(seen)
        )
        return scheduler.seen_note_keys  # type: ignore[return-value]


@dataclass
class DigestPotential:
    """Local, $0 estimate of whether a synthesis run can find anything."""

    window: int  # new (unseen) notes in the window
    neighbors: int  # STRONG-channel archive neighbours (bm25-only excluded)
    ok: bool


def digest_potential(candidates) -> DigestPotential:
    """Score an assembled candidate set. Pure — no I/O, no API.

    Passes when the window can connect among itself (>=2 new notes) or a
    single new note pulled enough STRONG channel neighbours from the archive
    (shared tag, rare-token bridge, entity, dense, graph, stance). Notes that
    only bm25 surfaced don't count — every transcript shares the section-header
    tokens, so a positive bm25 score is not evidence of a connection. A lone
    note nothing strong connects to fails — that run would burn an Opus call
    on nothing.
    """
    window = len(candidates.window_basenames)
    neighbors = sum(
        1
        for name, channels in candidates.channel_map.items()
        if name not in candidates.window_basenames and (channels - {"bm25"})
    )
    ok = window >= 2 or (window >= 1 and neighbors >= config.DIGEST_GATE_MIN_NEIGHBORS)
    return DigestPotential(window=window, neighbors=neighbors, ok=ok)


def _assemble_for_digest(
    scheduler: DigestScheduler,
    vault: Path,
    dismissals,
    legacy_window: bool = False,
    onboarding: bool = False,
    onboarding_exclude: Optional[Set[str]] = None,
):
    """THE digest candidate assembly — the run and the $0 preview both call
    this, so their windows and channel configuration can never diverge.

    ``legacy_window=True`` ignores the seen-set and takes the newest
    first-run window instead (the forced-regenerate fallback).
    ``onboarding=True`` treats the WHOLE corpus as first-session material
    (deliberately skipping ``_ensure_seen_migrated`` — migration would
    degenerate the connectable window to newest-15) and selects the most
    connectable window; ``onboarding_exclude`` removes an already-consumed
    first window so the retry picks the next one. Refreshes the scheduler
    from disk first so a resident process never assembles against a window
    another process already consumed and paid for.
    """
    from src.connections import candidate_assembly
    from src.connections.candidate_assembly import assemble_candidates

    scheduler.refresh_from_disk()
    if onboarding:
        seen: Optional[Set[str]] = set(onboarding_exclude or ())
        window_mode = "connectable"
    else:
        seen = None if legacy_window else _ensure_seen_migrated(scheduler, vault)
        window_mode = "newest"
    return assemble_candidates(
        vault,
        None if (legacy_window or onboarding) else scheduler.last_digest_at,
        dismissals,
        first_run_window=candidate_assembly.FIRST_RUN_WINDOW,
        inject_bridges=config.SYNTHESIS_BRIDGE_COUNT,
        inject_entities=config.SYNTHESIS_ENTITY_COUNT,
        inject_dense=config.SYNTHESIS_DENSE_COUNT,
        inject_graph=config.SYNTHESIS_GRAPH_COUNT,
        inject_stance=config.SYNTHESIS_STANCE_COUNT,
        seen_keys=seen,
        window_mode=window_mode,
    )


def estimate_digest_potential(onboarding: bool = False) -> DigestPotential:
    """Assemble candidates locally and score them — the manual-trigger preview.

    Shares :func:`_assemble_for_digest` with the paid run, so the preview can
    never warn about a run the scheduler itself would have paid for (the dense
    channel fails soft without its index; its engine is cached per process, so
    only the very first tester-mode call pays the model load). With
    ``onboarding=True`` it previews the same connectable window
    :func:`run_onboarding_digest` would consume — preview/run parity holds in
    both modes. The tokenize LRU is cleared on exit for the same reason the
    digest run clears it: don't pin note texts in the resident app. Callers
    must NOT invoke this on the UI main thread — it reads the whole corpus.
    """
    from src.connections.candidate_assembly import clear_tokenize_cache
    from src.connections.dismissals import DismissalStore

    vault = Path(config.TRANSCRIBE_DIR)
    scheduler = get_scheduler()
    dismissals = DismissalStore(vault).load()
    try:
        return digest_potential(
            _assemble_for_digest(scheduler, vault, dismissals, onboarding=onboarding)
        )
    finally:
        clear_tokenize_cache()


def _synthesize_and_write(
    transcriber,
    candidates,
    dismissals,
    synthesizer,
    verifier_override,
    language,
    *,
    onboarding: bool = False,
    window_fallback: bool = False,
    mark=None,
    set_ready: bool = True,
) -> tuple[Optional[Path], str]:
    """THE one paid synthesis→verdict→write tail, shared by every digest run.

    Duplicating this tail in scripts is what caused pipeline drift before —
    keep it single. Returns ``(path, status)`` with status one of:
    ``"written"`` (digest on disk, sidecar + metrics + digest_ready fired),
    ``"empty"`` (PAID run, nothing survived — metrics recorded, no digest),
    ``"error"`` (recoverable or billing failure — nothing consumed, caller
    must NOT mark the window seen).

    ``mark`` — optional callback invoked with the digest path (or None) the
    moment the window counts as CONSUMED, BEFORE the metrics append and the
    ready flag: a crash mid-tail must not leave a paid window unmarked (it
    would be re-paid next tick). The weekly path passes its ``_mark``;
    onboarding marks once itself after its retry loop.
    ``set_ready=False`` skips the digest_ready flag — the onboarding flow
    opens the Insights window itself and must not double-notify via the
    status tick.
    ``verifier_override`` — an explicitly injected verifier runs REGARDLESS
    of ``VERDICT_ENABLED`` (deliberate: the onboarding success metric is
    "verdict-surviving connections", also for non-tester users); ``None``
    keeps the config-gated factory behaviour.
    """
    from src.connections.digest_writer import write_digest_note
    from src.summarizer import APIBillingError

    def _disable(exc) -> None:
        disable_ai = getattr(transcriber, "_disable_ai", None)
        if callable(disable_ai):
            disable_ai("billing", exc)

    try:
        result = synthesizer.synthesize(
            candidates, dismissals.dismissed_descriptions(), language
        )
    except APIBillingError as exc:
        _disable(exc)
        return None, "error"
    if result is None:
        return None, "error"

    known = {n.basename for n in candidates.notes}
    connections = [
        c
        for c in result.connections
        if len(c.notes) >= 2 and all(b in known for b in c.notes)
    ]
    if not connections:
        # Synthesis ran and was PAID for but produced nothing — a real
        # H1/H4 data point (a paid run that yielded zero connections).
        logger.info("synthesis: no genuine connections this run")
        if mark is not None:
            mark(None)
        _record_digest_metrics(
            synthesizer,
            candidates,
            [],
            None,
            onboarding=onboarding,
            window_fallback=window_fallback,
        )
        return None, "empty"

    # Verdict pass: verify the proposed connections against fuller note text
    # BEFORE anything is written, so the digest, the sidecar and the action
    # instrument only ever see survivors. Fail OPEN on any recoverable
    # problem — verification must never lose a digest to an API hiccup.
    verdict_verifier = None  # set only when a verdict actually completed
    verdict_dropped = 0
    if verifier_override is not None:
        verifier = verifier_override
    elif getattr(config, "VERDICT_ENABLED", False):
        from src.connections.verdict import get_verifier

        verifier = get_verifier()
    else:
        verifier = None
    if verifier is not None:
        from src.connections.verdict import apply_verdicts

        try:
            verdicts = verifier.verify(
                connections,
                {n.basename: n for n in candidates.notes},
                language,
            )
        except APIBillingError as exc:
            _disable(exc)
            return None, "error"
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
        # Every proposal died in verification — a legitimate, PAID outcome.
        logger.info("verdict: no connections survived verification")
        if mark is not None:
            mark(None)
        _record_digest_metrics(
            synthesizer,
            candidates,
            [],
            None,
            verifier=verdict_verifier,
            verdict_dropped=verdict_dropped,
            onboarding=onboarding,
            window_fallback=window_fallback,
        )
        return None, "empty"

    path, conn_meta = write_digest_note(connections, len(candidates.notes))
    dismissals.record_digest(path, conn_meta)
    if mark is not None:
        mark(path)
    _record_digest_metrics(
        synthesizer,
        candidates,
        connections,
        path,
        verifier=verdict_verifier,
        verdict_dropped=verdict_dropped,
        onboarding=onboarding,
        window_fallback=window_fallback,
    )
    if set_ready:
        _set_digest_ready(transcriber, path)
    return path, "written"


def run_onboarding_digest(transcriber: object = None) -> tuple:
    """The first-session digest: the activation moment, policy separate from
    the weekly path.

    Whole corpus = first-session material (no seen-set migration), the most
    CONNECTABLE window, synthesis + verdict on ``ONBOARDING_DIGEST_MODEL``
    (injected per-run — the weekly default is untouched), and at most
    ``ONBOARDING_MAX_WINDOWS`` paid attempts: an empty first window retries
    once on the next connectable window. Afterwards the WHOLE corpus is
    marked seen with ``pending=0`` — byte-identical semantics to a fresh
    install (no paid auto-drain of the archive) and the weekly clock starts
    now.

    Returns ``(path, outcome)`` — the caller MUST distinguish these, because
    telling a user "your notes have no strong connections" when nothing was
    analyzed is a false verdict at the one moment that decides activation:
      * ``"written"`` — digest on disk (``path`` set),
      * ``"empty"`` — ran and paid, nothing survived verification,
      * ``"error"`` — synthesis/verification failed (nothing consumed),
      * ``"billing"`` — no credits / AI disabled (nothing attempted),
      * ``"busy"`` — another digest run holds the lock (nothing attempted),
      * ``"unavailable"`` — no API key / non-Claude provider.
    Never raises.
    """
    from src.connections.dismissals import DismissalStore
    from src.connections.synthesis import ConnectionSynthesizer
    from src.connections.verdict import ConnectionVerifier
    from src.summarizer import detect_language

    if not config.LLM_API_KEY or config.LLM_PROVIDER != "claude":
        return None, "unavailable"
    if getattr(transcriber, "_ai_disabled_reason", None):
        # Billing already tripped (e.g. during the import's summaries) —
        # don't burn another paid call that will fail the same way.
        return None, "billing"
    scheduler = get_scheduler()
    now = datetime.now()
    lock_fd = _acquire_digest_lock()
    if lock_fd is None:
        logger.info("onboarding digest: another digest run holds the lock")
        return None, "busy"
    try:
        vault = Path(config.TRANSCRIBE_DIR)
        dismissals = DismissalStore(vault).load()
        dismissals.sync_frontmatter_dismissals()
        synthesizer = ConnectionSynthesizer(
            api_key=config.LLM_API_KEY, model=ONBOARDING_DIGEST_MODEL
        )
        verifier = ConnectionVerifier(
            api_key=config.LLM_API_KEY, model=ONBOARDING_DIGEST_MODEL
        )

        consumed: Set[str] = set()
        corpus_keys: Set[str] = set()
        final_path: Optional[Path] = None
        pre_run_notes = scheduler.new_notes
        outcome = "empty"  # no material at all reads as "nothing to connect"
        for attempt in range(1, ONBOARDING_MAX_WINDOWS + 1):
            candidates = _assemble_for_digest(
                scheduler,
                vault,
                dismissals,
                onboarding=True,
                onboarding_exclude=consumed,
            )
            corpus_keys |= candidates.corpus_keys
            if len(candidates.notes) < 2 or not candidates.window_basenames:
                logger.info("onboarding digest: window %d has no material", attempt)
                break
            language = detect_language(
                " ".join(n.summary_md for n in candidates.notes)[:5000]
            )
            logger.info(
                "onboarding digest: attempt %d/%d — %d candidates "
                "(%d in window, fallback=%s)",
                attempt,
                ONBOARDING_MAX_WINDOWS,
                len(candidates.notes),
                len(candidates.window_basenames),
                candidates.window_fallback,
            )
            path, status = _synthesize_and_write(
                transcriber,
                candidates,
                dismissals,
                synthesizer,
                verifier,
                language,
                onboarding=True,
                window_fallback=candidates.window_fallback,
                # The first-session flow opens the Insights window itself —
                # the status tick must not also fire the digest_ready
                # notification for the same digest.
                set_ready=False,
            )
            if status == "error":
                # Nothing consumed. Distinguish a billing stop (the user must
                # top up) from a transient failure (retry makes sense).
                outcome = (
                    "billing"
                    if getattr(transcriber, "_ai_disabled_reason", None)
                    else "error"
                )
                break
            consumed |= candidates.window_keys
            outcome = status  # "written" | "empty"
            if status == "written":
                final_path = path
                break
            # "empty": paid attempt, retry with the next connectable window.

        if consumed:
            # At least one PAID window ran: the whole corpus becomes
            # pre-existing material (fresh-install semantics) and the weekly
            # clock starts now. pending=0 — the import bumped the trigger
            # counter; without the reset the tick would immediately re-digest.
            # Notes transcribed DURING the run (recorder plugged in mid-
            # session) bumped the counter after the snapshot — re-register
            # them so mark_ran's overwrite doesn't strand their trigger.
            late = max(0, scheduler.new_notes - pre_run_notes)
            scheduler.mark_ran(
                now, final_path, seen_keys=corpus_keys or consumed, pending=0
            )
            if late:
                scheduler.register_new_notes(late)
        return final_path, outcome
    finally:
        try:
            from src.connections.candidate_assembly import clear_tokenize_cache

            clear_tokenize_cache()
        except Exception:  # noqa: BLE001 - best effort
            pass
        _release_digest_lock(lock_fd)


def run_digest_if_due(
    transcriber: object = None, force: bool = False
) -> Optional[Path]:
    """Generate a digest when due. Safe to call every periodic tick.

    Returns the digest path when one was written, else ``None``. Never raises
    into the daemon loop — synthesis must never disturb transcription.
    """
    # Lazy imports keep `import src.connections` light (no anthropic/pydantic
    # unless a digest actually runs) and avoid import cycles with transcriber.
    from src.connections.dismissals import DismissalStore
    from src.connections.synthesis import get_synthesizer
    from src.summarizer import detect_language

    scheduler = get_scheduler()
    now = datetime.now()
    if not force and scheduler.auto_digest_on_hold(now):
        # First-session flow in progress (this process or another): the offer
        # dialog owns the next run. Logged so a stuck hold is diagnosable.
        logger.debug("digest: automatic path on first-session hold")
        return None
    if not force and not scheduler.is_due(now):
        return None
    if not force and scheduler.gate_cooldown_active(now):
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
        pre_run_notes = scheduler.new_notes
        candidates = _assemble_for_digest(scheduler, vault, dismissals)
        if candidates.corpus_size > 0 and candidates.unseen_total == 0:
            if not force:
                # Stale trigger counter: material was registered but nothing
                # is actually unseen (note muted/deleted after transcription,
                # or a re-transcribed known file). Clear it, or the tick
                # re-scans the corpus forever. Guarded on corpus_size so an
                # unreadable/empty vault never zeroes a real pending backlog.
                if scheduler.new_notes:
                    logger.info(
                        "digest: no unseen notes — clearing stale trigger counter"
                    )
                    scheduler.clear_pending()
                return None
            # Forced regenerate with nothing unseen: fall back to the newest
            # first-run window — the pre-seen-set behaviour of a manual run
            # (e.g. the user deleted a bad digest and wants it redone).
            logger.info(
                "digest (forced): nothing unseen — regenerating over the "
                "recent window"
            )
            candidates = _assemble_for_digest(
                scheduler, vault, dismissals, legacy_window=True
            )

        # Local pre-API gate: don't pay for a run assembly says can't connect.
        # Skip WITHOUT mark_ran — the material stays pending and is re-scored
        # after the cooldown or as soon as another note arrives. Forced runs
        # bypass the gate (the menu already asked the user).
        potential = digest_potential(candidates)
        if not force and not potential.ok:
            logger.info(
                "digest gate: low connection potential "
                "(window=%d, neighbors=%d) — skipping, $0 spent",
                potential.window,
                potential.neighbors,
            )
            scheduler.note_gate_skip(now)
            # One telemetry row per distinct skipped window — a pending window
            # re-skipped every cooldown must not spam the ledger hourly. The
            # signature is stamped only AFTER a successful append: a failed or
            # disabled write must stay retryable, not silence the window for
            # the process lifetime.
            sig = frozenset(candidates.window_keys)
            if sig != scheduler._gate_skip_sig:
                from src.connections.insight_metrics import record_gate_skip

                if record_gate_skip(
                    window=potential.window,
                    neighbors=potential.neighbors,
                    candidates=len(candidates.notes),
                ):
                    scheduler._gate_skip_sig = sig
            return None

        if len(candidates.notes) < 2:
            logger.info("synthesis: fewer than 2 candidate notes, skipping")
            return None

        pending = max(0, candidates.unseen_total - len(candidates.window_basenames))

        def _mark(digest_path: Optional[Path] = None) -> None:
            # Notes transcribed DURING the paid run bumped the counter after
            # the snapshot; re-register them on top of the clamped pending so
            # mark_ran's overwrite doesn't silently drop them.
            late = max(0, scheduler.new_notes - pre_run_notes)
            scheduler.mark_ran(
                now,
                digest_path,
                seen_keys=candidates.window_keys,
                pending=pending,
            )
            if late:
                scheduler.register_new_notes(late)

        language = detect_language(
            " ".join(n.summary_md for n in candidates.notes)[:5000]
        )
        # _mark passed as the tail's mark callback: it fires the moment the
        # window counts as consumed ("empty" and "written" both paid), in the
        # exact pre-refactor order (before metrics/ready). "error" never marks.
        path, _status = _synthesize_and_write(
            transcriber,
            candidates,
            dismissals,
            synthesizer,
            None,
            language,
            mark=_mark,
        )
        return path
    finally:
        # Bound the _tokenize LRU's lifetime to one digest pass — otherwise it
        # pins up to 8192 note texts in the resident daemon until it cycles.
        try:
            from src.connections.candidate_assembly import clear_tokenize_cache

            clear_tokenize_cache()
        except Exception:  # noqa: BLE001 - best effort, never disturb the tick
            pass
        _release_digest_lock(lock_fd)
