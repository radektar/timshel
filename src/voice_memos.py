"""Apple Voice Memos connector — iPhone recordings, transcribed automatically.

iCloud drops memos recorded on the iPhone into a local folder on the Mac:
``~/Library/Group Containers/group.com.apple.VoiceMemos.shared/Recordings``.
Once the user has enabled iCloud for Voice Memos and opened the app on the Mac
once, the system daemon (``voicememod``) keeps syncing in the background — a new
memo lands on disk about a minute after it is recorded, with the app closed.

Two facts from the sync layer shape this module:

1. **The filename carries the truth.** ``YYYYMMDD HHMMSS-XXXXXXXX.m4a`` is the
   local recording time plus a stable per-memo id. We read both from the name
   and never touch ``CloudRecordings.db`` beside it — no dependency on Apple's
   private schema.
2. **mtime lies.** It is the sync time, not the recording time: a whole archive
   arrives with today's mtime, and an evicted-then-redownloaded file gets a
   fresh one. So mtime can drive neither the "from now on" watermark nor
   deduplication — the memo id does, and ``recorded_at`` is passed down the
   pipeline explicitly.

The core (:class:`VoiceMemosConnector`) is pollable and free of FSEvents, so it
is tested synchronously; :class:`VoiceMemosWatcher` is a thin live-event shell
over the same code.
"""

import json
import os
import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from src.logger import logger
from src.transcriber import RetranscribeLockBusyError

try:
    from fsevents import Observer, Stream

    FSEVENTS_AVAILABLE = True
except ImportError:  # pragma: no cover - fsevents missing in some environments
    FSEVENTS_AVAILABLE = False

# "20260730 095901-4E1A2B3C" — date, time, stable per-memo id.
MEMO_FILENAME_RE = re.compile(r"^(\d{8}) (\d{6})-([0-9A-Fa-f]+)$")

MEMO_SUFFIX = ".m4a"
STATE_SCHEMA = 1
# A memo that fails this many times is parked: without a cap a permanently
# broken file would be retried on every tick, forever.
MAX_ATTEMPTS = 3
# A file must hold the same size across two observations this far apart before
# we touch it — iCloud writes it in place while downloading.
MIN_STABLE_SECONDS = 5.0

PROVENANCE = {
    "source_type": "voice-memo",
    "origin": "apple-voice-memos",
    "source_volume": "Voice Memos",
}


class ConnectorStatus(Enum):
    """What the user should be told about the connector right now."""

    DISABLED = "disabled"
    NOT_CONFIGURED = "not_configured"  # no folder / no memos: iCloud not set up
    NO_ACCESS = "no_access"  # the folder exists but macOS denies reading it
    ACTIVE = "active"


@dataclass(frozen=True)
class MemoCandidate:
    """One recording on disk, ready to be judged."""

    path: Path
    memo_id: str
    recorded_at: datetime
    size: int
    name_parsed: bool


@dataclass(frozen=True)
class ImportStats:
    """Outcome of one batch.

    ``lock_aborted`` covers both ways a batch can end early without finishing:
    the transcriber was busy mid-batch, and another import pass already held
    this module's lock so we never started. Callers that retry must not read
    "nothing happened" as "nothing left to do".
    """

    imported: int = 0
    skipped: int = 0
    failed: int = 0
    lock_aborted: bool = False


def parse_memo_filename(path: Path) -> Optional[MemoCandidate]:
    """Build a candidate from *path*, or ``None`` if it is not a memo file.

    An unexpected filename is not fatal: the name is still stable across
    re-syncs, so it works as an id, and mtime stands in for the recording time.
    Losing a recording would be worse than dating one badly.
    """
    if path.suffix.lower() != MEMO_SUFFIX:
        return None

    try:
        size = path.stat().st_size
    except OSError as error:  # noqa: BLE001 - file vanished mid-scan
        logger.debug("Voice Memos: cannot stat %s: %s", path.name, error)
        return None

    match = MEMO_FILENAME_RE.match(path.stem)
    if match is not None:
        day, clock, memo_id = match.groups()
        try:
            recorded_at = datetime.strptime(f"{day} {clock}", "%Y%m%d %H%M%S")
        except ValueError:
            recorded_at = None  # e.g. "20261345" — fall through to the fallback
        if recorded_at is not None:
            return MemoCandidate(
                path=path,
                memo_id=memo_id.upper(),
                recorded_at=recorded_at,
                size=size,
                name_parsed=True,
            )

    logger.warning(
        "Voice Memos: unexpected filename %s — using the name as id and mtime "
        "as the recording time",
        path.name,
    )
    return MemoCandidate(
        path=path,
        memo_id=path.stem,
        recorded_at=datetime.fromtimestamp(path.stat().st_mtime),
        size=size,
        name_parsed=False,
    )


class VoiceMemosConnector:
    """Decides which memos are new, and remembers what was already imported.

    State lives in its own JSON file (App Support), written atomically. Only the
    menu app writes it, so there is no cross-process merge — unlike the digest
    scheduler, which the CLI also touches.
    """

    def __init__(self, recordings_dir: Path, state_file: Path) -> None:
        self.recordings_dir = recordings_dir
        self.state_file = state_file
        self._lock = threading.Lock()
        # path -> (size, monotonic timestamp of that observation)
        self._last_seen: Dict[str, Tuple[int, float]] = {}
        self._state = self._load()

    # ------------------------------------------------------------------ state

    def _load(self) -> dict:
        """Read state from disk, tolerating anything but a working file."""
        empty: dict = {"schema": STATE_SCHEMA, "imported": {}, "failed": {}}
        try:
            raw = self.state_file.read_text(encoding="utf-8")
        except FileNotFoundError:
            return empty
        except OSError as error:  # noqa: BLE001
            logger.warning("Voice Memos: cannot read state: %s", error)
            return empty

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as error:
            logger.warning(
                "Voice Memos: state file is corrupt (%s) — starting fresh. "
                "Already-imported memos are still caught by the vault index.",
                error,
            )
            return empty

        if not isinstance(data, dict):
            return empty

        return {
            "schema": data.get("schema", STATE_SCHEMA),
            "enabled_at": data.get("enabled_at"),
            "imported": data.get("imported") or {},
            "failed": data.get("failed") or {},
        }

    def _save(self) -> None:
        """Atomic write: temp file + rename, so a crash never truncates state."""
        tmp = self.state_file.with_suffix(".json.tmp")
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(
                json.dumps(self._state, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            os.replace(tmp, self.state_file)
        except OSError as error:  # noqa: BLE001
            logger.error("Voice Memos: cannot save state: %s", error)

    @property
    def enabled_at(self) -> Optional[datetime]:
        raw = self._state.get("enabled_at")
        if not raw:
            return None
        try:
            return datetime.fromisoformat(raw)
        except (TypeError, ValueError):
            return None

    def enable(self, now: Optional[datetime] = None) -> None:
        """Set the "from here on" watermark — once.

        Re-enabling after a pause must not rewind it, or the whole archive would
        turn into new material and quietly bill hours of whisper.
        """
        with self._lock:
            if self._state.get("enabled_at"):
                return
            self._state["enabled_at"] = (now or datetime.now()).isoformat()
            self._save()

    def mark_imported(
        self,
        memo: MemoCandidate,
        note_path: Optional[Path] = None,
        fingerprint: Optional[str] = None,
    ) -> None:
        with self._lock:
            self._state["imported"][memo.memo_id] = {
                "file": memo.path.name,
                "recorded_at": memo.recorded_at.isoformat(),
                "imported_at": datetime.now().isoformat(),
                "fingerprint": fingerprint,
                "note": str(note_path) if note_path else None,
            }
            self._state["failed"].pop(memo.memo_id, None)
            self._save()

    def mark_failed(self, memo: MemoCandidate, error: str) -> bool:
        """Record a failed attempt. Returns True when the memo is given up on."""
        with self._lock:
            entry = self._state["failed"].get(memo.memo_id) or {"attempts": 0}
            entry["attempts"] = int(entry.get("attempts", 0)) + 1
            entry["last_error"] = error
            entry["file"] = memo.path.name
            entry["gave_up"] = entry["attempts"] >= MAX_ATTEMPTS
            self._state["failed"][memo.memo_id] = entry
            self._save()
            return bool(entry["gave_up"])

    def _is_settled(self, memo_id: str) -> bool:
        """True when this memo needs no further work (done, or given up on)."""
        if memo_id in self._state["imported"]:
            return True
        failed = self._state["failed"].get(memo_id)
        return bool(failed and failed.get("gave_up"))

    # ----------------------------------------------------------------- lookup

    def _list_memos(self) -> Optional[List[Path]]:
        """All .m4a files, or ``None`` when the folder cannot be read."""
        try:
            return [
                entry
                for entry in self.recordings_dir.iterdir()
                if entry.is_file() and entry.suffix.lower() == MEMO_SUFFIX
            ]
        except FileNotFoundError:
            return []
        except (PermissionError, OSError) as error:  # noqa: BLE001
            logger.warning(
                "Voice Memos: cannot read %s: %s", self.recordings_dir, error
            )
            return None

    def has_any_recordings(self) -> bool:
        memos = self._list_memos()
        return bool(memos)

    def status(self, enabled: bool) -> ConnectorStatus:
        if not enabled:
            return ConnectorStatus.DISABLED
        memos = self._list_memos()
        if memos is None:
            return ConnectorStatus.NO_ACCESS
        if not memos:
            return ConnectorStatus.NOT_CONFIGURED
        return ConnectorStatus.ACTIVE

    def _is_stable(self, candidate: MemoCandidate) -> bool:
        """True once the file has held its size across two observations.

        iCloud grows the file in place while downloading; importing mid-write
        would transcribe half a memo and then dedup would call it done.
        """
        key = str(candidate.path)
        now = time.monotonic()
        previous = self._last_seen.get(key)
        self._last_seen[key] = (candidate.size, previous[1] if previous else now)

        if previous is None:
            return False
        seen_size, first_seen = previous
        if seen_size != candidate.size:
            # Still growing — restart the clock at this size.
            self._last_seen[key] = (candidate.size, now)
            return False
        return (now - first_seen) >= MIN_STABLE_SECONDS

    def scan(self) -> List[MemoCandidate]:
        """New memos recorded since the connector was switched on."""
        memos = self._list_memos()
        if not memos:
            self._last_seen.clear()
            return []

        # Forget files that are gone (deleted in the Voice Memos app), so the
        # stability map cannot grow for the lifetime of the menu-bar process.
        present = {str(path) for path in memos}
        self._last_seen = {
            key: value for key, value in self._last_seen.items() if key in present
        }

        watermark = self.enabled_at
        if watermark is None:
            # Fail closed. No watermark means we never recorded the moment of
            # consent — either the settings toggle was saved before the
            # connector existed, or the state file was lost. Treating that as
            # "no filter" would sweep in the entire archive (a decade of memos,
            # hours of whisper) that the user never agreed to import.
            logger.warning(
                "Voice Memos: enabled with no start marker — importing nothing "
                "until it is set (re-toggle the connector in Settings)"
            )
            return []

        fresh: List[MemoCandidate] = []
        for path in memos:
            candidate = parse_memo_filename(path)
            if candidate is None or self._is_settled(candidate.memo_id):
                continue
            if candidate.recorded_at < watermark:
                continue  # archive: only imported on an explicit opt-in
            if not self._is_stable(candidate):
                continue
            fresh.append(candidate)

        return sorted(fresh, key=lambda memo: memo.recorded_at)

    def archive_candidates(self) -> List[MemoCandidate]:
        """Memos older than the watermark — the explicit backfill offer."""
        memos = self._list_memos()
        if not memos:
            return []

        watermark = self.enabled_at
        if watermark is None:
            return []

        older: List[MemoCandidate] = []
        for path in memos:
            candidate = parse_memo_filename(path)
            if candidate is None or self._is_settled(candidate.memo_id):
                continue
            if candidate.recorded_at < watermark:
                older.append(candidate)

        return sorted(older, key=lambda memo: memo.recorded_at)


# Serialises the FSEvents shell against the periodic tick: both call into the
# same import loop, and a second concurrent pass would fight for the workflow
# lock and double-count attempts.
_IMPORT_LOCK = threading.Lock()


def process_voice_memos(
    transcriber,
    connector: VoiceMemosConnector,
    *,
    candidates: Optional[List[MemoCandidate]] = None,
    notify: Optional[Callable[[str, str], None]] = None,
    progress: Optional[Callable[[int, int, MemoCandidate], None]] = None,
) -> ImportStats:
    """Import pending memos through the normal audio pipeline.

    ``candidates`` overrides the scan — the backfill passes the archive list.
    Returns counts; a busy transcription lock aborts the batch without touching
    state, because the next tick will simply try again.
    """
    if not _IMPORT_LOCK.acquire(blocking=False):
        logger.debug("Voice Memos: an import pass is already running — skipping")
        # Not "done": the backfill loop must retry rather than report a batch
        # of zero as a finished job.
        return ImportStats(lock_aborted=True)

    try:
        pending = connector.scan() if candidates is None else candidates
        if not pending:
            return ImportStats()

        imported = skipped = failed = 0
        lock_aborted = False

        for index, memo in enumerate(pending):
            if progress is not None:
                progress(index, len(pending), memo)

            # The vault index is the second line of defence: if the connector
            # state is lost (fresh install on a second Mac sharing one vault),
            # this still stops a re-import — and a re-import would not even be
            # a visible duplicate, it would silently become note ".v2".
            try:
                existing = transcriber.vault_index.lookup_by_filename_size(
                    memo.path.name, memo.size
                )
            except Exception as error:  # noqa: BLE001 - index must never block
                logger.debug("Voice Memos: index lookup failed: %s", error)
                existing = None

            if existing is not None:
                logger.info("Voice Memos: already in the vault: %s", memo.path.name)
                connector.mark_imported(memo)
                skipped += 1
                continue

            try:
                ok = transcriber.import_audio_file(
                    memo.path,
                    recorded_at=memo.recorded_at,
                    provenance=dict(PROVENANCE),
                )
            except RetranscribeLockBusyError:
                logger.info(
                    "Voice Memos: transcription busy — %d memo(s) wait for the "
                    "next pass",
                    len(pending) - index,
                )
                lock_aborted = True
                break
            except (FileNotFoundError, ValueError) as error:
                connector.mark_failed(memo, str(error))
                failed += 1
                continue
            except Exception as error:  # noqa: BLE001 - one bad memo, not a crash
                logger.error(
                    "Voice Memos: import of %s failed: %s",
                    memo.path.name,
                    error,
                    exc_info=True,
                )
                connector.mark_failed(memo, str(error))
                failed += 1
                continue

            if ok:
                connector.mark_imported(memo)
                imported += 1
            else:
                gave_up = connector.mark_failed(memo, "transcription failed")
                failed += 1
                if gave_up:
                    logger.warning(
                        "Voice Memos: giving up on %s after %d attempts",
                        memo.path.name,
                        MAX_ATTEMPTS,
                    )

        if imported and notify is not None:
            notify(
                "Timshel",
                f"Voice Memos: {imported} nagranie/nagrania przepisane.",
            )

        return ImportStats(
            imported=imported,
            skipped=skipped,
            failed=failed,
            lock_aborted=lock_aborted,
        )
    finally:
        _IMPORT_LOCK.release()


class VoiceMemosWatcher:
    """Live FSEvents shell over :meth:`VoiceMemosConnector.scan`.

    Purely an accelerator: everything it triggers also happens on the periodic
    tick, so a missing fsevents module or an unwatchable folder degrades to
    "picked up within 30 s" rather than failing.
    """

    def __init__(
        self,
        recordings_dir: Path,
        on_activity: Callable[[], None],
        debounce_seconds: float = 2.0,
    ) -> None:
        self.recordings_dir = recordings_dir
        self.on_activity = on_activity
        self.debounce_seconds = debounce_seconds
        self.observer = None
        self.is_watching = False
        self._last_trigger = 0.0

    def _handle_event(self, *_args) -> None:
        now = time.monotonic()
        if now - self._last_trigger < self.debounce_seconds:
            return
        self._last_trigger = now
        try:
            self.on_activity()
        except Exception as error:  # noqa: BLE001 - never kill the fsevents thread
            logger.error("Voice Memos: watcher callback failed: %s", error)

    def start(self) -> bool:
        if self.is_watching:
            return True
        if not FSEVENTS_AVAILABLE:
            logger.info(
                "Voice Memos: fsevents unavailable — falling back to the "
                "periodic scan"
            )
            return False
        if not self.recordings_dir.exists():
            logger.info(
                "Voice Memos: %s does not exist yet — the periodic scan will "
                "pick it up once iCloud creates it",
                self.recordings_dir,
            )
            return False

        try:
            observer = Observer()
            stream = Stream(
                self._handle_event, str(self.recordings_dir), file_events=True
            )
            observer.schedule(stream)
            observer.start()
            self.observer = observer
            self.is_watching = True
            logger.info("Voice Memos: watching %s", self.recordings_dir)
            return True
        except Exception as error:  # noqa: BLE001
            logger.error("Voice Memos: cannot start the watcher: %s", error)
            self.observer = None
            return False

    def stop(self) -> None:
        if self.observer is not None:
            try:
                self.observer.stop()
                self.observer.join(timeout=5.0)
            except Exception as error:  # noqa: BLE001
                logger.debug("Voice Memos: watcher stop failed: %s", error)
        self.observer = None
        self.is_watching = False
