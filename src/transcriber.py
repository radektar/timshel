"""Transcription engine for Timshel."""

import fcntl
import json
import os
import platform
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, NamedTuple, Optional, Tuple

from src.app_status import AppStatus
from src.config import config as default_config
from src.config.config import Config
from src.config.settings import UserSettings
from src.fingerprint import compute_fingerprint
from src.hostinfo import get_hostname
from src.logger import logger
from src.markdown_frontmatter import read_frontmatter
from src.markdown_generator import MarkdownGenerator
from src.stance_guard import guard_stance_subjects
from src.state_manager import get_last_sync_time, save_sync_time
from src.summarizer import (
    APIBillingError,
    BaseSummarizer,
    _is_permanent_api_error,
    get_summarizer,
    is_fallback_summary,
    transcript_coverage,
)
from src.tag_index import GENERATED_TAG, TagIndex
from src.tagger import BaseTagger, get_tagger
from src.vault_index import IndexEntry, VaultIndex
from src.vocabulary import VocabularyIndex, find_alias_misses
from src.volume_utils import find_matching_volumes

# whisper-cli with -pp prints "whisper_print_progress_callback: progress =  NN%".
_PROGRESS_RE = re.compile(r"progress\s*=\s*(\d+)\s*%")


class WhisperRun(subprocess.CompletedProcess):
    """A finished whisper-cli run, plus why it finished.

    ``stalled`` is True only when *we* killed the process for going silent —
    something no exit code can express, and something the caller must handle
    differently from a failure whisper reported itself (see
    ``_STALL_SILENCE_SECONDS``). ``stalled_after`` carries how long that silence
    actually was, so the error the user reads is the measured number and not
    whichever threshold the code happens to quote. Callers that only know about
    :class:`subprocess.CompletedProcess` keep working unchanged.
    """

    def __init__(
        self, *args, stalled: bool = False, stalled_after: float = 0.0, **kwargs
    ):
        super().__init__(*args, **kwargs)
        self.stalled = stalled
        self.stalled_after = stalled_after


class NoteMeter(NamedTuple):
    """What a note's paid calls are attributed to in the cost ledger.

    ``note`` is the fingerprint, not the filename: it joins the summary, alias
    retry and tag rows of one note without writing its title into the ledger.
    """

    note: str
    source_type: str
    duration_seconds: Optional[int]
    # Retranscribes reuse the fingerprint, so without this a v2 note's spend is
    # indistinguishable from v1's in any per-note cost analysis.
    version: int = 1


def send_notification(title: str, message: str, subtitle: str = "") -> None:
    """Send macOS notification using osascript.

    Args:
        title: Notification title
        message: Notification message body
        subtitle: Optional subtitle
    """
    try:
        # Escape quotes in strings
        title = title.replace('"', '\\"')
        message = message.replace('"', '\\"')
        subtitle = subtitle.replace('"', '\\"')

        if subtitle:
            script = f'display notification "{message}" with title "{title}" subtitle "{subtitle}"'
        else:
            script = f'display notification "{message}" with title "{title}"'

        subprocess.run(
            ["osascript", "-e", script], capture_output=True, timeout=5.0, check=False
        )
    except Exception as e:
        logger.debug(f"Failed to send notification: {e}")


class RetranscribeLockBusyError(RuntimeError):
    """Wskazuje że ``force_retranscribe`` nie mógł acquire lock-a.

    Inny proces (typowo automatic ``process_recorder``) trzyma lock —
    UI łapie ten exception i pokazuje alert "Auto transkrypcja w toku".
    """


class ProcessLock:
    """Advisory cross-process lock guarding the recorder workflow.

    Backed by ``fcntl.flock`` instead of a hand-rolled PID file. The kernel
    drops the lock automatically when the owning process exits — crash, hard
    kill, or clean shutdown alike — so a stuck lock can never outlive its
    owner. The previous PID-file scheme could deadlock for the whole
    ``TRANSCRIPTION_TIMEOUT`` window: in a single-process app the recorded PID
    is always our own (so it always looked "alive"), and a kill between
    ``open`` and ``write`` left an empty file that was never recognised as
    stale. The lock file is never unlinked while in use — with ``flock`` the
    lock lives in the kernel, and deleting the file would let a second opener
    race onto a fresh inode.
    """

    def __init__(self, lock_path: Path):
        """Configure lock helper.

        Args:
            lock_path: Full path to lock file.
        """
        self.lock_path = lock_path
        self._fd: Optional[int] = None

    def acquire(self) -> bool:
        """Try to grab the lock without blocking.

        Returns:
            True if the lock was acquired, False if another live process
            currently holds it.
        """
        try:
            self.lock_path.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(str(self.lock_path), os.O_CREAT | os.O_RDWR)
        except OSError as error:
            logger.error("Could not open process lock at %s: %s", self.lock_path, error)
            return False

        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            # Held by another live process. The kernel releases the flock
            # automatically if that process dies, so there is nothing to
            # clean up and no stale file can ever wedge us.
            os.close(fd)
            return False

        # Record the holder for diagnostics (logs, manual inspection) only —
        # the lock state lives in the kernel, never in this file's contents.
        try:
            os.ftruncate(fd, 0)
            os.write(fd, f"{os.getpid()}\n{time.time():.0f}".encode("utf-8"))
        except OSError as error:
            logger.debug("Could not write process lock diagnostics: %s", error)

        self._fd = fd
        return True

    def release(self) -> None:
        """Release the lock if held (no-op otherwise)."""
        if self._fd is None:
            return
        try:
            fcntl.flock(self._fd, fcntl.LOCK_UN)
        except OSError as error:
            logger.warning("Error releasing process lock %s: %s", self.lock_path, error)
        finally:
            try:
                os.close(self._fd)
            except OSError:
                pass
            self._fd = None


class Transcriber:
    """Main transcription engine.

    Handles finding the recorder, scanning for new audio files,
    managing transcription state, and invoking Whisper CLI.

    Attributes:
        transcription_in_progress: Track files currently being transcribed
        whisper_available: Flag indicating if Whisper CLI is available
        recorder_monitoring: Flag if recorder is currently connected
        recorder_was_notified: Flag to track if connection notification was sent
        state_updater: Optional callback to update application state
        config: Configuration instance (injected dependency)
    """

    def __init__(self, config: Optional[Config] = None):
        """Initialize the transcriber.

        Args:
            config: Configuration instance. If None, uses global default config.
                    This allows for dependency injection in tests.
        """
        # Use injected config or fall back to global default
        self.config = config if config is not None else default_config

        self.transcription_in_progress: Dict[str, bool] = {}
        self.whisper_available = self._check_whisper()
        self.recorder_monitoring = False
        self.recorder_was_notified = False
        # Serializes the automatic recorder workflow against a user-triggered
        # re-transcription *within this process* (the periodic checker and the
        # menu action run on separate threads). Cross-process exclusion — and
        # crash-safe auto-release — is handled by ProcessLock (fcntl.flock).
        self._workflow_lock = threading.Lock()
        # Live whisper-cli subprocess, tracked so stop() can kill its process
        # group on app quit — otherwise an orphaned whisper (cores-2 threads)
        # keeps burning CPU with its timeout enforcement dead.
        self._active_whisper_proc: Optional[subprocess.Popen] = None
        self._active_proc_lock = threading.Lock()
        self.state_updater: Optional[
            Callable[
                [
                    AppStatus,
                    Optional[str],
                    Optional[str],
                    Optional[str],
                    Optional[int],
                ],
                None,
            ]
        ] = None

        # Initialize summarizer and markdown generator
        self.summarizer: Optional[BaseSummarizer] = get_summarizer()
        self.markdown_generator = MarkdownGenerator()
        self.tag_index = TagIndex()
        # Personal glossary — rebuilt per recording (see workflow) so every
        # new note's wikilinks widen the vocabulary for the *next* one.
        self.vocabulary = VocabularyIndex()
        self.tagger: Optional[BaseTagger] = get_tagger()
        self._ai_disabled_reason: Optional[str] = None
        self.ai_billing_callback: Optional[Callable[[Exception], None]] = None
        self._session_failed_fingerprints: set = set()
        self._postprocess_attempts: Dict[str, int] = {}
        # Recordings already lost to a stall once. A stall is treated as
        # transient (a busy CPU, a disk waking up, a backup running) and gets a
        # second chance on the next cycle — but only one, or a genuinely wedged
        # machine would retry the same recording forever.
        self._stalled_once: set = set()
        self._gpu_disabled_in_session: bool = False
        self._load_persisted_gpu_disabled()
        self._last_run_was_transient_failure: bool = False
        self.vault_index = VaultIndex(self.config.TRANSCRIBE_DIR)
        self.vault_index.load()
        self._run_index_migration_if_needed()

        # Ensure output directory exists
        self.config.ensure_directories()

    def set_state_updater(
        self,
        updater: Callable[
            [AppStatus, Optional[str], Optional[str], Optional[str], Optional[int]],
            None,
        ],
    ) -> None:
        """Set callback function for state updates.

        Args:
            updater: Function that takes (status, current_file, error_message)
        """
        self.state_updater = updater

    def set_ai_billing_callback(self, callback: Callable[[Exception], None]) -> None:
        """Register a callback invoked once when the AI circuit breaker trips."""
        self.ai_billing_callback = callback

    def _disable_ai(self, reason: str, exc: Exception) -> None:
        """Trip the AI circuit breaker for the rest of the session."""
        if self._ai_disabled_reason is not None:
            return
        self._ai_disabled_reason = reason
        logger.critical("🛑 AI disabled for this session (%s): %s", reason, exc)
        if self.ai_billing_callback is not None:
            try:
                self.ai_billing_callback(exc)
            except Exception as cb_exc:  # noqa: BLE001
                logger.error("AI billing callback failed: %s", cb_exc)

    def reload_ai_config(self) -> None:
        """Re-read AI config live after a settings change (e.g. a fixed API key).

        The summarizer/tagger each hold an Anthropic client built with the key
        that was current at daemon start, and the circuit breaker latches for
        the session — so a key fixed in Settings would otherwise only take
        effect on the next app launch (the cause of summaries/tags staying dead
        after a 401). Call this *after* the global config has been rebuilt
        (:func:`src.config.config.reload_config`) so the new key/model is picked
        up immediately and any prior auth/billing/model trip is cleared.
        """
        self._ai_disabled_reason = None
        self.summarizer = get_summarizer()
        self.tagger = get_tagger()
        logger.info(
            "🔄 AI config reloaded (summaries=%s, tags=%s)",
            self.summarizer is not None,
            self.tagger is not None,
        )

    def reload_paths(self) -> None:
        """Re-point the vault index at the current output folder.

        ``vault_index`` is bound to ``TRANSCRIBE_DIR`` at construction. When the
        user changes the output folder in Settings, note *writes* follow the new
        folder live (via the config proxy), but dedup/lookup would keep reading
        the OLD folder's index — new notes wouldn't be deduped and the digest
        would read the wrong vault. Rebuild the index on the new path so write
        and index never diverge. Call *after* ``reload_config()``.
        """
        new_dir = self.config.TRANSCRIBE_DIR
        if str(getattr(self.vault_index, "vault_dir", "")) == str(new_dir):
            return
        self.vault_index = VaultIndex(new_dir)
        self.vault_index.load()
        logger.info("🔄 Vault index re-pointed at %s", new_dir)

    def _run_index_migration_if_needed(self) -> None:
        """Run one-time migration of legacy markdown metadata to index."""
        try:
            settings = UserSettings.load()
            if settings.index_migrated and not self._vault_needs_reindex():
                return
            self._update_state(AppStatus.MIGRATING)
            script_path = (
                Path(__file__).resolve().parent.parent
                / "scripts"
                / "migrate_to_v2_index.py"
            )
            subprocess.run(
                [sys.executable, str(script_path)],
                timeout=120.0,
                check=False,
                capture_output=True,
                text=True,
            )
            self.vault_index.load()
            self._update_state(AppStatus.IDLE)
        except Exception as error:  # noqa: BLE001
            logger.warning("Index migration failed (continuing): %s", error)

    def _vault_needs_reindex(self) -> bool:
        """Detect stale state where index is empty but markdown notes exist."""
        if self.vault_index.entry_count() > 0:
            return False
        if not self.config.TRANSCRIBE_DIR.exists():
            return False
        return any(self.config.TRANSCRIBE_DIR.glob("*.md"))

    def _update_state(
        self,
        status: AppStatus,
        current_file: Optional[str] = None,
        error_message: Optional[str] = None,
        recorder_name: Optional[str] = None,
        pending_count: Optional[int] = None,
    ) -> None:
        """Update application state via callback if available.

        Args:
            status: New status
            current_file: Current file being processed
            error_message: Error message if status is ERROR
        """
        if self.state_updater:
            try:
                self.state_updater(
                    status,
                    current_file,
                    error_message,
                    recorder_name,
                    pending_count,
                )
            except Exception as e:
                logger.debug(f"Error updating state: {e}")

    def _check_whisper(self) -> bool:
        """Check if whisper.cpp binary and ffmpeg are available.

        Returns:
            True if both whisper.cpp and ffmpeg are available, False otherwise
        """
        # Check for whisper.cpp binary
        if not self.config.WHISPER_CPP_PATH.exists():
            logger.warning(
                f"⚠️  whisper.cpp not found at: {self.config.WHISPER_CPP_PATH}\n"
                "Aplikacja spróbuje pobrać zależności automatycznie przy "
                "pierwszym uruchomieniu."
            )
            # Nie zwracamy False - pozwalamy aplikacji sprawdzić czy może pobrać
            # (UI powinno pokazać ekran pobierania)

        # Check for ffmpeg
        ffmpeg_path = self.config.FFMPEG_PATH
        if not ffmpeg_path or not ffmpeg_path.exists():
            # Fallback do systemowego ffmpeg
            system_ffmpeg = shutil.which("ffmpeg")
            if system_ffmpeg:
                ffmpeg_path = Path(system_ffmpeg)
            else:
                logger.warning(
                    "⚠️  ffmpeg not found. Aplikacja spróbuje pobrać automatycznie."
                )
                # Nie zwracamy False - pozwalamy aplikacji sprawdzić czy może pobrać

        if (
            self.config.WHISPER_CPP_PATH.exists()
            and ffmpeg_path
            and ffmpeg_path.exists()
        ):
            logger.info(f"✓ Found whisper.cpp at: {self.config.WHISPER_CPP_PATH}")
            logger.info(f"✓ Found ffmpeg at: {ffmpeg_path}")

            # Check for Core ML encoder (required by whisper-cli built with WHISPER_COREML=ON)
            coreml_model = (
                self.config.WHISPER_CPP_MODELS_DIR
                / f"ggml-{self.config.WHISPER_MODEL}-encoder.mlmodelc"
            )
            if coreml_model.exists():
                logger.info("✓ Core ML encoder found - GPU acceleration enabled")
            else:
                logger.warning(
                    "⚠️  Core ML encoder brakuje — whisper-cli może crashować. "
                    "Startuje pobieranie w tle..."
                )
                import threading

                from src.setup.downloader import DependencyDownloader

                def _bg_download_encoder() -> None:
                    try:
                        DependencyDownloader().download_model_encoder(
                            self.config.WHISPER_MODEL
                        )
                        logger.info(
                            "✓ Core ML encoder pobrany — transkrypcja będzie działać "
                            "od następnego cyklu skanowania"
                        )
                    except Exception as exc:
                        logger.error("Błąd pobierania Core ML encodera: %s", exc)

                threading.Thread(
                    target=_bg_download_encoder,
                    daemon=True,
                    name="CoreMLEncoderDownload",
                ).start()

            return True

        # Zależności brakują - zwróć False (UI powinno pokazać ekran pobierania)
        return False

    def find_recorder(self) -> Optional[Path]:
        """Search for a connected recorder volume.

        Delegates to :func:`find_recorders` for discovery and returns the
        first match. Kept for backward compatibility with callers and tests
        that expect a single ``Optional[Path]``.

        Returns:
            Path to the first matching recorder volume or None if none found.
        """
        recorders = self.find_recorders()
        if recorders:
            return recorders[0]
        return None

    def find_recorders(self) -> List[Path]:
        """Return every mounted volume that qualifies as a recorder.

        Honours ``UserSettings.watch_mode`` so this stays consistent with
        ``FileMonitor``:

        * ``auto`` - any non-system volume containing audio files.
        * ``specific`` - only volumes named in ``watched_volumes``.
        * ``manual`` - never auto-detect.

        For backward compatibility, if ``config.RECORDER_NAMES`` has been
        set to a non-empty list (e.g. via explicit injection in tests), the
        result is filtered to that whitelist.

        Returns:
            Sorted list of matching volume paths (possibly empty).
        """
        settings = UserSettings.load()
        matching = find_matching_volumes(settings)

        whitelist = getattr(self.config, "RECORDER_NAMES", None) or []
        if whitelist and settings.watch_mode != "auto":
            # Only enforce the legacy whitelist outside of auto mode; in auto
            # mode the user explicitly asked for any volume with audio files.
            matching = [v for v in matching if v.name in whitelist]

        if matching:
            for recorder in matching:
                logger.info(f"✓ Recorder found: {recorder}")
        else:
            logger.debug("No recorder found in /Volumes")
        return matching

    def get_last_sync_time(self) -> datetime:
        """Get timestamp of last synchronization.

        Returns:
            Datetime of last sync, or 7 days ago if no state file exists
        """
        return get_last_sync_time()

    def save_sync_time(self) -> None:
        """Save current time as last sync timestamp."""
        save_sync_time()

    def find_audio_files(self, recorder_path: Path, since: datetime) -> List[Path]:
        """Find new audio files modified after given datetime.

        Args:
            recorder_path: Root path of the recorder volume
            since: Only return files modified after this datetime

        Returns:
            List of audio file paths, sorted by modification time
        """
        from src.config.defaults import defaults

        new_files = []
        max_depth = defaults.MAX_SCAN_DEPTH

        try:
            # Recursively find all files
            for item in recorder_path.rglob("*"):
                # Skip directories and non-audio files
                if not item.is_file():
                    continue

                # Check depth limit (count directories, not file name)
                # max_depth=3 means up to 3 directory levels deep
                try:
                    relative = item.relative_to(recorder_path)
                    # Count directory depth: parts - 1 (exclude filename)
                    dir_depth = len(relative.parts) - 1
                    if dir_depth > max_depth:
                        logger.debug(
                            f"Skipping file beyond max_depth ({max_depth}): {item.relative_to(recorder_path)} (depth: {dir_depth})"
                        )
                        continue
                except ValueError:
                    # If relative_to fails, skip this item
                    continue

                # Skip macOS metadata files
                if item.name.startswith("._") or item.name == ".DS_Store":
                    logger.debug(f"Skipping macOS metadata file: {item.name}")
                    continue

                if item.suffix.lower() not in self.config.AUDIO_EXTENSIONS:
                    continue

                # Check modification time
                try:
                    mtime = datetime.fromtimestamp(item.stat().st_mtime)
                    if mtime > since:
                        new_files.append(item)
                        logger.debug(
                            f"Found new file: {item.name} (mtime: {mtime}, depth: {dir_depth})"
                        )
                except OSError as e:
                    logger.warning(f"Could not access file {item}: {e}")
                    continue

        except OSError as e:
            logger.error(
                f"OSError scanning recorder (may have unmounted): {e}", exc_info=True
            )
            return []
        except PermissionError as e:
            logger.error(f"PermissionError scanning recorder: {e}", exc_info=True)
            return []
        except Exception as e:
            logger.error(f"Error scanning for audio files: {e}", exc_info=True)
            return []

        logger.debug(f"Scan complete: found {len(new_files)} new audio file(s)")

        # Sort by modification time (oldest first)
        new_files.sort(key=lambda x: x.stat().st_mtime)

        return new_files

    def _iter_audio_files(self, recorder_path: Path) -> Iterator[Path]:
        """Yield audio files from recorder up to configured max depth.

        Per-item OSErrors (e.g. fskit returning EINVAL/ENXIO during FAT32
        warm-up on macOS Tahoe) are logged and skipped — one flaky file
        must not abort the whole scan.
        """
        from src.config.defaults import defaults

        max_depth = defaults.MAX_SCAN_DEPTH
        try:
            iterator = recorder_path.rglob("*")
        except OSError as error:
            logger.error("Cannot start scan of %s: %s", recorder_path, error)
            return
        while True:
            try:
                item = next(iterator)
            except StopIteration:
                return
            except OSError as error:
                logger.warning(
                    "Skipping unreadable entry during scan of %s: %s",
                    recorder_path,
                    error,
                )
                continue
            try:
                if not item.is_file():
                    continue
                if item.name.startswith("._") or item.name == ".DS_Store":
                    continue
                if item.suffix.lower() not in self.config.AUDIO_EXTENSIONS:
                    continue
                relative = item.relative_to(recorder_path)
                dir_depth = len(relative.parts) - 1
                if dir_depth > max_depth:
                    continue
            except OSError as error:
                logger.warning("Skipping unreadable file %s: %s", item, error)
                continue
            except ValueError:
                continue
            yield item

    def find_pending_audio_files(self, recorder_path: Path) -> List[Tuple[Path, str]]:
        """Return recorder audio files (with fingerprint) missing from vault index."""
        pending_files: List[Tuple[Path, str]] = []
        try:
            for audio_file in self._iter_audio_files(recorder_path):
                try:
                    size = audio_file.stat().st_size
                except OSError as error:
                    logger.warning("Cannot stat %s: %s", audio_file, error)
                    continue
                if (
                    self.vault_index.lookup_by_filename_size(audio_file.name, size)
                    is not None
                ):
                    logger.debug("✓ Skip (filename+size match): %s", audio_file.name)
                    continue
                try:
                    fingerprint = compute_fingerprint(audio_file)
                except OSError as error:
                    logger.warning("Cannot fingerprint %s: %s", audio_file, error)
                    continue
                if fingerprint in self._session_failed_fingerprints:
                    logger.debug("Skipping previously failed file: %s", audio_file.name)
                    continue
                if self.vault_index.lookup(fingerprint) is None:
                    pending_files.append((audio_file, fingerprint))
        except OSError as error:
            # Volume-level error (e.g. recorder unmounted mid-scan). Keep
            # what was collected so far — a partial result is far better
            # than losing N successfully-scanned files because file N+1
            # tripped fskit. Next periodic check will pick up the rest.
            logger.warning(
                "Partial scan on %s after I/O error (%d files kept): %s",
                recorder_path,
                len(pending_files),
                error,
            )
        return pending_files

    # A .partial older than this is debris from a killed copy, not a copy in
    # flight: staging a recording takes seconds, not hours.
    _PARTIAL_SWEEP_SECONDS = 6 * 3600

    def prune_staging_dir(self) -> int:
        """Drop staged copies that are old AND already have a note.

        The staging dir is a feature (retranscription, recovery without the
        recorder), so this is retention, not cleanup: a copy is only removed
        once its note is verifiably ON DISK, and only after it has SAT HERE
        for the retention window. Anything else is left alone — the staged
        copy may be the only surviving original.

        Returns the number of files removed.
        """
        staging_dir = self.config.LOCAL_RECORDINGS_DIR
        if not staging_dir or not staging_dir.exists():
            return 0

        keep_days = getattr(self.config, "STAGING_RETENTION_DAYS", 30)
        if keep_days <= 0:
            return 0
        cutoff = time.time() - keep_days * 86400

        removed = 0
        freed = 0
        for path in staging_dir.iterdir():
            try:
                if not path.is_file():
                    continue
                stat = path.stat()

                # An interrupted staging copy (SIGKILL, power loss) leaves a
                # .partial behind; nothing else would ever collect it.
                if path.suffix == ".partial":
                    if stat.st_mtime < time.time() - self._PARTIAL_SWEEP_SECONDS:
                        size = stat.st_size
                        path.unlink()
                        removed += 1
                        freed += size
                    continue

                if path.suffix.lower() not in self.config.AUDIO_EXTENSIONS:
                    continue

                # st_ctime, NOT st_mtime: copy2 preserves the RECORDING's
                # timestamp, so a January recording imported in May would be
                # "older than 30 days" the instant it was staged — deleted in
                # the same batch that created it. ctime is bumped by the copy
                # and the rename, so it measures time spent in staging.
                if stat.st_ctime > cutoff:
                    continue

                # Match on filename+size, not a recomputed fingerprint: a
                # Voice Memo is indexed with its filename-derived recording
                # time (its mtime lies), so re-hashing here would produce a
                # different fingerprint, find nothing, and keep every imported
                # memo forever. This lookup also skips a 1 MB read per file.
                entry = self.vault_index.lookup_by_filename_size(
                    path.name, stat.st_size
                )
                if entry is None or not self._entry_note_on_disk(entry):
                    continue  # no note on disk — this copy may be the original
                size = stat.st_size
                path.unlink()
            except OSError as error:
                logger.debug("Staging retention: skipping %s: %s", path.name, error)
                continue
            removed += 1
            freed += size

        if removed:
            logger.info(
                "Staging retention: removed %d file(s) past the %d-day window, "
                "freed %.1f MB",
                removed,
                keep_days,
                freed / (1024 * 1024),
            )
        return removed

    def _entry_note_on_disk(self, entry) -> bool:
        """True when an index entry's note actually exists in the vault.

        The index alone is not proof: an entry can outlive its note (the user
        deletes it in Obsidian, or the orphan safety valve deliberately keeps
        entries it refuses to clean). Trusting it would let retention delete
        the only remaining copy of a recording whose note is already gone.
        """
        if entry is None:
            return False
        candidates = [entry.markdown_path] + [
            v.get("markdown_path", "") for v in (entry.versions or [])
        ]
        transcribe_dir = self.config.TRANSCRIBE_DIR
        for rel in candidates:
            if rel and (transcribe_dir / rel).exists():
                return True
        return False

    def _stage_audio_file(self, audio_file: Path) -> Optional[Path]:
        """Copy audio file from recorder to local staging directory.

        Creates a local copy of the recorder file in the staging directory.
        This allows transcription to proceed even if the recorder unmounts
        during processing. The staged file preserves the original filename
        and modification time.

        Args:
            audio_file: Path to audio file on recorder (e.g., /Volumes/LS-P1/...)

        Returns:
            Path to staged file in LOCAL_RECORDINGS_DIR, or None if staging failed
        """
        try:
            # Ensure staging directory exists
            self.config.LOCAL_RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)

            # Destination path (same filename as original)
            staged_path = self.config.LOCAL_RECORDINGS_DIR / audio_file.name

            # Check if file already exists and matches (size and mtime)
            if staged_path.exists():
                try:
                    source_stat = audio_file.stat()
                    staged_stat = staged_path.stat()

                    # If size and mtime match, reuse existing copy
                    if (
                        source_stat.st_size == staged_stat.st_size
                        and abs(source_stat.st_mtime - staged_stat.st_mtime) < 1.0
                    ):
                        logger.debug(
                            f"✓ Reusing existing staged copy: {audio_file.name}"
                        )
                        return staged_path
                except OSError:
                    # If we can't stat the source, try to copy anyway
                    # (might be a race condition with unmounting)
                    pass

            logger.debug(f"📋 Staging file: {audio_file.name}")
            self._copy_atomically(audio_file, staged_path)
            logger.debug(f"✓ Staged: {audio_file.name} -> {staged_path}")

            return staged_path

        except FileNotFoundError as e:
            logger.warning(
                f"⚠️  Could not stage {audio_file.name}: "
                f"recorder may have unmounted ({e})"
            )
            return None
        except OSError as e:
            logger.warning(f"⚠️  Could not stage {audio_file.name}: {e}")
            return None
        except Exception as e:
            logger.error(
                f"✗ Unexpected error staging {audio_file.name}: {e}", exc_info=True
            )
            return None

    def _run_whisper_transcription(
        self,
        audio_file: Path,
        use_gpu: bool = True,
        source_audio: Optional[Path] = None,
    ) -> WhisperRun:
        """Run whisper.cpp transcription.

        Args:
            audio_file: Original recording; its stem names the output TXT.
            use_gpu: Whether to allow the Metal backend (off for the fallback).
                Note this does *not* turn Core ML off — the encoder always runs
                through Core ML in this build; only the decoder moves to CPU.
            source_audio: Actual audio fed to whisper-cli. Defaults to
                ``audio_file``; callers pass a converted 16 kHz WAV here so
                whisper always receives a format it can decode (see
                ``_convert_to_wav``).

        Returns:
            CompletedProcess from subprocess.run
        """
        if use_gpu and self._gpu_disabled_in_session:
            use_gpu = False

        whisper_input = source_audio if source_audio is not None else audio_file

        # Build whisper.cpp command
        model_path = (
            self.config.WHISPER_CPP_MODELS_DIR / f"ggml-{self.config.WHISPER_MODEL}.bin"
        )
        output_base = self.config.TRANSCRIBE_DIR / audio_file.stem

        threads = self._whisper_thread_count()
        whisper_cmd = [
            str(self.config.WHISPER_CPP_PATH),
            "-m",
            str(model_path),
            "-f",
            str(whisper_input),
            "-otxt",
            "-of",
            str(output_base),
            "-t",
            str(threads),
            "-pp",  # stream progress to stderr so a long run never looks hung
        ]

        # Add language if specified
        if self.config.WHISPER_LANGUAGE:
            whisper_cmd.extend(["-l", self.config.WHISPER_LANGUAGE])

        # Personal glossary as initial prompt: biases decoding toward the
        # user's confirmed spellings, so "Tech to the Rescue" doesn't come
        # out as "TekTutoreski". Refreshed here (cheap: one vault scan) so
        # notes written since daemon start already feed this recording.
        glossary = ""
        try:
            self.vocabulary.build(force_refresh=True)
            glossary = self.vocabulary.whisper_prompt()
        except Exception as exc:  # noqa: BLE001 — glossary must never block
            logger.warning("Vocabulary glossary unavailable: %s", exc)
        if glossary:
            whisper_cmd.extend(["--prompt", glossary])
            logger.debug("Whisper glossary (%d chars): %s", len(glossary), glossary)

        # Turn the GPU off for the fallback attempt. This has to be the CLI
        # flag: WHISPER_COREML / GGML_METAL_DISABLE are build-time switches in
        # whisper.cpp, so setting them in the environment did nothing at all —
        # the "CPU retry" used to run with `use gpu = 1`, identical to the
        # attempt it was supposed to be rescuing.
        if not use_gpu:
            whisper_cmd.append("-ng")
            logger.debug("Metal backend disabled for this attempt (-ng)")

        logger.debug(
            f"Running whisper.cpp: model={self.config.WHISPER_MODEL}, "
            f"language={self.config.WHISPER_LANGUAGE}, "
            f"gpu={'enabled' if use_gpu else 'disabled'}, "
            f"threads={threads}, "
            f"timeout={self.config.TRANSCRIPTION_TIMEOUT}s"
        )

        return self._run_whisper_streaming(
            whisper_cmd,
            env=None,
            use_gpu=use_gpu,
            audio_file=audio_file,
            audio_duration=self._audio_duration_seconds(whisper_input),
        )

    @staticmethod
    def _whisper_thread_count() -> int:
        """Thread count for whisper-cli, leaving headroom for the UI.

        whisper-cli otherwise pins the CPU and the low-priority menu-bar process
        gets starved enough that macOS flags it 'Not Responding'. Reserving two
        cores keeps the app interactive during a long transcription.
        """
        cores = os.cpu_count() or 4
        return max(1, cores - 2)

    # How long whisper may produce nothing at all before we call it wedged.
    #
    # A GPU that fails loudly is handled by _METAL_FAIL_MARKERS; this covers the
    # one that just stops. Silence is a weaker signal than an error message, so
    # the threshold sits far above any legitimate quiet period.
    #
    # Segments are the *fast* heartbeat (one per ~30 s window of audio, 0.7–5 s
    # apart on an M2 Pro with medium + Core ML) but not a guaranteed one:
    # whisper emits none for a window it classifies as no-speech, so a quiet
    # stretch of the recording is silent on stdout. The guaranteed heartbeat is
    # `progress = NN%`, printed every 5% of the *file position* whatever the
    # audio contains — which fixes the floor: one step is at most 5% of the
    # run's compute, so a run that would legitimately finish inside
    # TRANSCRIPTION_TIMEOUT (3600 s) cannot be silent for longer than one step
    # (180 s). The floor carries half a step of margin on top, because a run
    # pacing to only just fit the budget produces exactly that gap and the
    # comparison is `>=` — landing on the boundary would kill a healthy run.
    _STALL_SILENCE_SECONDS = 270

    # …but that argument only holds when one progress step is a small slice of
    # the run. whisper decodes in ~30 s windows and reports progress per window,
    # so on a *short* recording a single window is a large share of the file and
    # its compute is a large share of a legitimate run: an old dual-core on
    # `medium` with the GPU off can need minutes for one window of a 4-minute
    # memo and still finish far inside the hour. The window scales for that
    # from two numbers known before whisper starts — the audio duration and the
    # time budget. The slowest machine still worth waiting for is the one that
    # spends the whole TRANSCRIPTION_TIMEOUT on this recording; its time for
    # one decode window is TIMEOUT * (window / duration), and that is the
    # longest silence a run that can still succeed will ever produce. Anything
    # quieter is wedged — or too slow to finish inside the budget, which ends
    # the same way. Static by design: an earlier adaptive version measured the
    # machine's pace from the output stream and produced eight review findings
    # (fd ordering, segment bursts, a compile banked as pace, ...) — including
    # one where the learned value switched the detector off entirely.
    _WHISPER_DECODE_WINDOW_SECONDS = 30.0

    # Before the first decoded window, silence is normal: whisper loads the
    # model and says nothing until the first segment comes out.
    _STALL_GRACE_SECONDS = 900

    # The one phase that can be silent far longer: the first Core ML run for a
    # model on a device compiles the encoder (whisper warns "first run on a
    # device may take a while"), and on `large` that compile can outlast the
    # grace window on older hardware. whisper announces the phase, so it is
    # detected rather than guessed at — and only *this* window is generous. The
    # run as a whole is still bounded by TRANSCRIPTION_TIMEOUT.
    _STALL_COMPILE_SECONDS = 1800
    _COREML_COMPILE_START = "loading Core ML model"
    _COREML_COMPILE_END = "Core ML model loaded"

    def _stall_limit(
        self,
        decoding_started: bool,
        *,
        coreml_compiling: bool = False,
        audio_duration: float = 0.0,
    ) -> float:
        """How long this phase of the run may stay silent.

        Args:
            decoding_started: True once whisper has emitted a segment or a
                progress line — i.e. it is past model load and Core ML compile,
                so the generous grace window no longer applies.
            coreml_compiling: True between whisper announcing the Core ML load
                and confirming it — a first-run encoder compile lives here.
            audio_duration: Length of the recording in seconds (0 = unknown,
                which keeps the floor). See _WHISPER_DECODE_WINDOW_SECONDS for
                why the window widens for short recordings.
        """
        if decoding_started:
            # Whatever the flags say, output means the compile is behind us.
            limit = float(self._STALL_SILENCE_SECONDS)
            if audio_duration > 0:
                budget = max(self.config.TRANSCRIPTION_TIMEOUT, 0)
                windows = audio_duration / self._WHISPER_DECODE_WINDOW_SECONDS
                # Capped at the startup grace: a clip of a few windows would
                # otherwise be handed most of the hour budget — for a 30 s memo
                # the whole of it — which is the "you lose an hour" this feature
                # removes. Tolerating more silence while decoding than while
                # starting up would be backwards in any case.
                limit = min(
                    max(limit, budget / windows), float(self._STALL_GRACE_SECONDS)
                )
            return limit
        if coreml_compiling:
            return self._STALL_COMPILE_SECONDS
        return self._STALL_GRACE_SECONDS

    def _is_stalled(
        self,
        *,
        silent_for: float,
        decoding_started: bool,
        coreml_compiling: bool = False,
        audio_duration: float = 0.0,
    ) -> bool:
        """Whether a live whisper has been quiet long enough to count as wedged.

        Args:
            silent_for: Seconds since the last byte on *either* pipe.
            decoding_started: See :meth:`_stall_limit`.
            coreml_compiling: See :meth:`_stall_limit`.
            audio_duration: See :meth:`_stall_limit`.
        """
        return silent_for >= self._stall_limit(
            decoding_started,
            coreml_compiling=coreml_compiling,
            audio_duration=audio_duration,
        )

    @staticmethod
    def _audio_duration_seconds(audio_path: Optional[Path]) -> float:
        """Duration of a WAV in seconds, 0.0 when unknown.

        Only the converted 16 kHz mono WAV ever lands here (whisper always
        receives one, see _convert_to_wav), so the wave module suffices; any
        failure just means the stall window stays at its floor.
        """
        if audio_path is None:
            return 0.0
        import wave

        try:
            with wave.open(str(audio_path), "rb") as handle:
                rate = handle.getframerate()
                if rate <= 0:
                    return 0.0
                return handle.getnframes() / rate
        except (OSError, wave.Error, EOFError):
            return 0.0

    def _run_whisper_streaming(
        self,
        cmd: List[str],
        *,
        env: Optional[dict],
        use_gpu: bool,
        audio_file: Path,
        audio_duration: float = 0.0,
    ) -> WhisperRun:
        """Run whisper-cli with live stderr streaming.

        Replaces a blocking ``subprocess.run(capture_output=True)`` to fix three
        bugs at once:
          1. **Early Metal abort.** whisper.cpp prints the Metal error
             at backend init; the old post-hoc stderr check only saw it after the
             whole run finished, wasting ~10 min before the CPU fallback. We now
             detect the marker live and kill the process within seconds.
          2. **Progress heartbeat.** With ``-pp`` whisper emits ``progress = NN%``
             to stderr; we log it so a long run is visibly alive.
          3. **Stall detection.** A GPU that wedges says nothing at all, so
             neither of the above sees it and the recording used to die on
             TRANSCRIPTION_TIMEOUT an hour later. Silence on *both* pipes is
             the signal (see ``_is_stalled``).

        Both pipes are read: stderr for markers and progress, stdout purely as a
        sign of life — whisper prints each decoded segment there, far more often
        than it prints progress, and the content is redundant (the TXT comes
        from ``-otxt``) so it is read and dropped. Reading both is also what
        keeps the old pipe-buffer deadlock away now that stdout is no longer
        DEVNULL. Returns a :class:`WhisperRun` (stdout always ``""``) so the
        caller is unchanged, and raises :class:`subprocess.TimeoutExpired` on
        the deadline to preserve the old contract.

        encoding/errors are critical under py2app (ASCII locale) — whisper prints
        UTF-8 paths / Polish chars to stderr.

        All reads happen on the RAW non-blocking fd (``os.read``), never on the
        buffered ``proc.stderr`` wrapper: a buffered ``readline()`` blocks
        forever on a partial line without a newline (a stalled whisper mid-write
        used to wedge this thread — and with it ``_workflow_lock`` + the process
        flock — past the deadline). With ``os.read`` a partial line just sits in
        our own buffer and the deadline check always fires.
        """
        import codecs
        import select

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,  # read purely as a sign of life, then dropped
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            start_new_session=True,  # own process group → stop() can killpg
        )
        with self._active_proc_lock:
            self._active_whisper_proc = proc

        stderr_chunks: List[str] = []
        deadline = time.time() + max(self.config.TRANSCRIPTION_TIMEOUT, 0.0)
        last_logged_pct = -1
        last_heartbeat = time.time()
        started = time.time()
        # Liveness is tracked separately from the heartbeat above: that one only
        # moves when a heartbeat is actually *logged* (throttled to every 10
        # points / 20 s), so reusing it would let the logging policy decide when
        # a healthy run counts as hung.
        last_activity = started
        decoding_started = False
        coreml_compiling = False
        metal_failed = False
        stalled = False
        stalled_after = 0.0

        assert proc.stderr is not None  # stderr=PIPE above guarantees it
        assert proc.stdout is not None  # stdout=PIPE above guarantees it
        stderr_fd = proc.stderr.fileno()
        stdout_fd = proc.stdout.fileno()
        os.set_blocking(stderr_fd, False)
        os.set_blocking(stdout_fd, False)
        open_fds = {stderr_fd, stdout_fd}
        decoder = codecs.getincrementaldecoder("utf-8")("replace")
        pending = ""  # text accumulated until a newline arrives

        def handle_line(line: str) -> bool:
            """Marker + progress logic for one stderr line. True = stop."""
            nonlocal metal_failed, last_logged_pct, last_heartbeat
            nonlocal coreml_compiling
            # The Core ML encoder compile is the one silence that can outlast
            # the grace window (first run of a model on a device). whisper
            # brackets it, so the phase is known instead of guessed.
            if self._COREML_COMPILE_END in line or self._coreml_load_failed(line):
                # The failure line ("failed to load Core ML model") also ends
                # the phase: it neither matches the success marker nor repeats
                # the start one, so without this the flag latches and the whole
                # run gets the 30-minute compile window — on a build that
                # continues past the failure, the wedged machine this feature
                # exists for would take 30 minutes to detect instead of 3.
                coreml_compiling = False
            elif self._COREML_COMPILE_START in line:
                coreml_compiling = True
            if use_gpu and any(m in line for m in self._METAL_FAIL_MARKERS):
                metal_failed = True
                logger.warning(
                    "⚡ Metal error detected after %.0fs — "
                    "aborting GPU attempt, will retry with GPU off",
                    time.time() - started,
                )
                proc.kill()
                return True
            match = _PROGRESS_RE.search(line)
            if match:
                pct = int(match.group(1))
                now = time.time()
                start_decoding()
                if pct >= last_logged_pct + 10 or now - last_heartbeat >= 20:
                    logger.info(
                        "⏳ Transkrypcja %d%% — %s",
                        pct,
                        audio_file.name,
                    )
                    last_logged_pct = pct
                    last_heartbeat = now
            return False

        def mark_activity() -> None:
            """Whisper said something: reset the stall clock.

            Deliberately just a clock. An earlier version also *learned* the
            machine's pace from these reads; that adaptive layer produced eight
            review findings (fd ordering, segment bursts, a Core ML compile
            banked as pace...) and was replaced by the static duration-based
            limit — see _WHISPER_DECODE_WINDOW_SECONDS.
            """
            nonlocal last_activity
            last_activity = time.time()

        def start_decoding() -> None:
            """First sign the decode loop is running, from either pipe."""
            nonlocal decoding_started
            decoding_started = True

        def read_chunk() -> Optional[str]:
            """One non-blocking stderr read. Text (possibly ''), or None on EOF."""
            try:
                chunk = os.read(stderr_fd, 65536)
            except BlockingIOError:
                return ""
            except OSError:  # pragma: no cover - defensive (closed fd)
                return None
            if not chunk:
                return None
            mark_activity()
            return decoder.decode(chunk)

        def drain_stdout() -> Optional[int]:
            """One non-blocking stdout read, discarded. Bytes read, None on EOF.

            whisper writes the transcript itself (``-otxt``); what we want here
            is only the *timing* of each decoded segment, so nothing is kept and
            a long recording costs no memory.
            """
            try:
                chunk = os.read(stdout_fd, 65536)
            except BlockingIOError:
                return 0
            except OSError:  # pragma: no cover - defensive (closed fd)
                return None
            if not chunk:
                return None
            mark_activity()
            start_decoding()  # a segment on stdout = the decode loop runs
            return len(chunk)

        def process_remaining() -> None:
            """Flush the decoder and run marker/progress logic on every
            not-yet-processed line, including a final newline-less one (a Metal
            error can be the last thing whisper prints before stalling)."""
            nonlocal pending
            tail = decoder.decode(b"", final=True)
            if tail:
                stderr_chunks.append(tail)
                pending += tail
            for line in pending.split("\n"):
                if line and handle_line(line):
                    break
            pending = ""

        try:
            stop = False
            while not stop:
                # Check exit before blocking on select so a finished (or fast)
                # run drains cleanly without needing a selectable fd.
                if proc.poll() is not None:
                    while True:
                        text = read_chunk()
                        if not text:
                            break
                        stderr_chunks.append(text)
                        pending += text
                    while drain_stdout():
                        pass
                    process_remaining()
                    break

                remaining = deadline - time.time()
                if remaining <= 0:
                    proc.kill()
                    raise subprocess.TimeoutExpired(
                        cmd, self.config.TRANSCRIPTION_TIMEOUT
                    )

                silent_for = time.time() - last_activity
                if self._is_stalled(
                    silent_for=silent_for,
                    decoding_started=decoding_started,
                    coreml_compiling=coreml_compiling,
                    audio_duration=audio_duration,
                ):
                    # Last look before killing it: bytes written between the
                    # empty select() and this check are still in the pipes, and
                    # if they carry the "transcript written" marker the run
                    # actually finished — discarding them would cost a whole
                    # re-transcription and delete a complete TXT.
                    while True:
                        text = read_chunk()
                        if not text:
                            break
                        stderr_chunks.append(text)
                        pending += text
                    while drain_stdout():
                        pass
                    stalled = True
                    stalled_after = silent_for
                    # Whisper may have written a marker without a trailing
                    # newline and *then* wedged; without this its stderr would
                    # reach the caller as a plain stall and a genuine Metal
                    # failure would never be recorded.
                    process_remaining()
                    if not metal_failed:
                        logger.warning(
                            "⚠️  whisper produced nothing for %.0fs (%s, %.0fs "
                            "into the run) — killing it as stalled",
                            silent_for,
                            (
                                "compiling the Core ML encoder"
                                if coreml_compiling
                                else "decoding" if decoding_started else "starting up"
                            ),
                            time.time() - started,
                        )
                    proc.kill()
                    break

                # Never sleep past the moment the run would count as stalled:
                # the check only runs between selects, so a longer sleep would
                # let the poll interval, not the threshold, decide when a wedged
                # GPU is noticed.
                until_stall = (
                    self._stall_limit(
                        decoding_started,
                        coreml_compiling=coreml_compiling,
                        audio_duration=audio_duration,
                    )
                    - silent_for
                )
                wait = max(min(1.0, remaining, until_stall), 0.01)
                ready, _, _ = select.select(list(open_fds), [], [], wait)
                if not ready:
                    continue

                for fd in ready:
                    if fd == stdout_fd:
                        if drain_stdout() is None:
                            open_fds.discard(stdout_fd)
                        continue

                    text = read_chunk()
                    if text is None:
                        # EOF: the write end closed — flush any final partial
                        # line. stderr closing ends the run; whatever stdout
                        # still holds is output we deliberately discard.
                        process_remaining()
                        stop = True
                        break
                    if not text:
                        continue

                    stderr_chunks.append(text)
                    pending += text
                    while "\n" in pending:
                        line, pending = pending.split("\n", 1)
                        if handle_line(line):
                            stop = True
                            break
                    if stop:
                        break
        finally:
            for pipe in (proc.stderr, proc.stdout):
                try:
                    if pipe is not None:
                        pipe.close()
                except Exception:  # pragma: no cover - defensive
                    pass
            if proc.poll() is None:
                try:
                    proc.wait(timeout=5)
                except Exception:  # pragma: no cover - defensive
                    proc.kill()
                    proc.wait()
            else:
                proc.wait()
            with self._active_proc_lock:
                self._active_whisper_proc = None

        returncode = proc.returncode if proc.returncode is not None else -1
        if (metal_failed or stalled) and returncode == 0:
            # Ensure the caller treats a run we aborted ourselves as a failure
            # so the CPU fallback fires.
            returncode = -1
        return WhisperRun(
            args=cmd,
            returncode=returncode,
            stdout="",
            stderr="".join(stderr_chunks),
            stalled=stalled,
            stalled_after=stalled_after,
        )

    def stop(self) -> None:
        """Kill an in-flight whisper-cli on shutdown (SIGTERM → SIGKILL).

        Without this, quitting mid-transcription orphans whisper-cli: its
        timeout enforcement lives in this process's deadline loop, the kernel
        releases the flock on exit, and a relaunched app can start a second
        whisper on the same file alongside the orphan. Targets the process
        GROUP (Popen uses start_new_session=True). Safe to call anytime.
        """
        with self._active_proc_lock:
            proc = self._active_whisper_proc
        if proc is None or proc.poll() is not None:
            return
        pid = getattr(proc, "pid", None)  # test fakes may lack a pid
        if pid is None:
            return
        try:
            pgid = os.getpgid(pid)
            logger.info("⏹  Stopping in-flight whisper (pgid=%s)...", pgid)
            os.killpg(pgid, signal.SIGTERM)
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                os.killpg(pgid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError) as error:
            logger.debug("stop(): could not kill whisper process: %s", error)

    # Bumped whenever the detector's semantics change: an old verdict was
    # recorded by a different (here: broken) definition of "Metal failed", so
    # it must not survive the upgrade — every machine re-probes the GPU once.
    _GPU_VERDICT_VERSION = 2

    def _gpu_flag_path(self) -> Path:
        """Sidecar file recording that Metal failed on this machine.

        Filename kept from when the verdict was (mis)labelled "coreml" so no
        migration is needed — the version in the signature invalidates it.
        """
        return self.config.STATE_FILE.parent / "coreml_status.json"

    def _gpu_signature(self) -> str:
        """Identity for the persisted verdict: re-probe when anything that could
        change the answer changes — whisper binary, model, macOS, detector."""
        try:
            size = self.config.WHISPER_CPP_PATH.stat().st_size
        except OSError:
            size = 0
        macos = platform.mac_ver()[0]
        return (
            f"v{self._GPU_VERDICT_VERSION}:{size}:{self.config.WHISPER_MODEL}:{macos}"
        )

    # A Metal failure only becomes a standing verdict once it has happened on
    # this many separate boots. One `failed to allocate Metal buffer` under
    # momentary VRAM pressure (Blender, a browser) is an accident, not a broken
    # machine — and the verdict is expensive: it silently keeps the decoder on
    # the CPU for good, with no UI signal and no reset button.
    _GPU_VERDICT_MIN_FAILURES = 2

    # …or once they are this far apart in time. Boot alone is too lazy a unit:
    # macOS boxes run for weeks (a reboot is not a thing users do to fix this),
    # and a GPU that dies *mid-run* costs a doubled wall clock on the first
    # recording after every app start until the verdict finally sticks.
    _GPU_FAILURE_COOLDOWN_SECONDS = 12 * 3600

    # Absolute path: launchd hands the daemon a minimal PATH, and a silent
    # slide into the day-based fallback would quietly change what the tally
    # counts.
    _SYSCTL_PATH = "/usr/sbin/sysctl"

    def _boot_id(self) -> str:
        """Identity of the current boot — the unit the failure tally counts in.

        Counting *processes* would not do: the daemon and the menu bar app run
        side by side (see ProcessLock) with a Transcriber each, so one hour of
        VRAM pressure would tick the tally twice within a minute and condemn a
        healthy GPU — exactly the false positive the threshold exists to stop.
        Falls back to the calendar day if sysctl is unavailable.
        """
        try:
            probe = subprocess.run(
                [self._SYSCTL_PATH, "-n", "kern.boottime"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=5,
            )
            match = re.search(r"sec\s*=\s*(\d+)", probe.stdout or "")
            if match:
                return f"boot:{match.group(1)}"
            logger.debug("Unexpected kern.boottime output: %r", probe.stdout)
        except (OSError, subprocess.SubprocessError) as exc:
            logger.debug("Could not read kern.boottime: %s", exc)
        return f"day:{datetime.now().date().isoformat()}"

    def _read_gpu_verdict(self) -> dict:
        """Persisted verdict for the current signature, or an empty dict."""
        try:
            data = json.loads(self._gpu_flag_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            # ValueError covers both JSONDecodeError and the UnicodeDecodeError
            # a corrupted sidecar raises — callers run inside the transcription
            # path, where a bad status file must never sink the recording.
            return {}
        if not isinstance(data, dict) or data.get("signature") != self._gpu_signature():
            return {}
        return data

    def _load_persisted_gpu_disabled(self) -> None:
        """Honour a *confirmed* Metal failure so we don't waste a full GPU
        attempt rediscovering it on every launch."""
        data = self._read_gpu_verdict()
        failures = data.get("failures", 0)
        if data.get("disabled") and failures >= self._GPU_VERDICT_MIN_FAILURES:
            self._gpu_disabled_in_session = True
            logger.info(
                "GPU (Metal) disabled (persisted: %d independent Metal failures "
                "on this machine for the current whisper/model/macOS)",
                failures,
            )

    def _persist_gpu_disabled(self) -> None:
        """Count this Metal failure; a second, independent one makes it stick.

        "Independent" = another boot, or far enough apart in time. The daemon
        and the menu bar app hitting the same VRAM squeeze minutes apart is one
        event, not two; the same machine failing again tomorrow is two.
        """
        data = self._read_gpu_verdict()
        boot_id = self._boot_id()
        now = time.time()
        failures = data.get("failures", 0)
        age = now - data.get("at", 0)
        counted = (
            data.get("boot_id") != boot_id or age >= self._GPU_FAILURE_COOLDOWN_SECONDS
        )
        if counted:
            failures += 1
        try:
            self._gpu_flag_path().parent.mkdir(parents=True, exist_ok=True)
            self._gpu_flag_path().write_text(
                json.dumps(
                    {
                        "disabled": True,
                        "signature": self._gpu_signature(),
                        "failures": failures,
                        "boot_id": boot_id,
                        # Stamped only when the failure was counted: a rolling
                        # stamp would restart the window on every failure, so a
                        # machine failing more often than the cooldown could
                        # never reach the threshold — the exact cost the
                        # cooldown exists to stop.
                        "at": now if counted else data.get("at", now),
                    }
                ),
                encoding="utf-8",
            )
        except OSError as exc:  # pragma: no cover - defensive
            logger.debug("Could not persist GPU status: %s", exc)
            return
        if failures < self._GPU_VERDICT_MIN_FAILURES:
            logger.info(
                "Metal failure recorded (%d/%d) — the GPU is still tried on the "
                "next launch; only a second, independent failure makes it stick",
                failures,
                self._GPU_VERDICT_MIN_FAILURES,
            )

    def _clear_gpu_verdict(self) -> None:
        """A GPU run that finished retires the tally recorded so far.

        Without this, two unrelated hiccups years apart would add up to a
        permanent verdict on hardware that works. Note this only reaches a
        tally *below* the threshold: once the verdict stands, the GPU is never
        attempted again, so it can no longer prove itself — those installs
        re-probe when whisper, the model or macOS changes (see
        ``_gpu_signature``), or when the sidecar is deleted by hand.
        """
        if not self._read_gpu_verdict():
            return
        try:
            self._gpu_flag_path().unlink()
            logger.info("GPU ran cleanly — cleared the recorded Metal failure(s)")
        except OSError as exc:  # pragma: no cover - defensive
            logger.debug("Could not clear GPU status: %s", exc)

    def _convert_to_wav(self, audio_file: Path) -> Optional[Path]:
        """Transcode *audio_file* to a 16 kHz mono PCM WAV for whisper-cli.

        whisper-cli only reliably decodes 16 kHz WAV; its bundled decoder
        rejects common recorder formats (m4a/aac from iPhone Voice Memos, wma),
        which previously failed silently with "failed to read audio data as
        wav". Normalising every input through ffmpeg first makes all formats in
        ``AUDIO_EXTENSIONS`` work uniformly and also fixes non-16 kHz / stereo
        sources.

        Returns the path to a temporary WAV (the caller must delete it), or
        ``None`` when conversion fails (corrupted/unreadable input) — which the
        caller treats as a permanent transcription failure.
        """
        ffmpeg_path = self.config.FFMPEG_PATH
        if not ffmpeg_path or not Path(ffmpeg_path).exists():
            system_ffmpeg = shutil.which("ffmpeg")
            if not system_ffmpeg:
                logger.error("ffmpeg not available — cannot convert audio to WAV")
                return None
            ffmpeg_path = Path(system_ffmpeg)

        # Hidden sibling in the output dir; cleaned up by the caller.
        wav_path = self.config.TRANSCRIBE_DIR / f".{audio_file.stem}.whisper16k.wav"
        cmd = [
            str(ffmpeg_path),
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(audio_file),
            "-ar",
            "16000",
            "-ac",
            "1",
            "-c:a",
            "pcm_s16le",
            str(wav_path),
        ]
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                timeout=self.config.TRANSCRIPTION_TIMEOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except subprocess.TimeoutExpired:
            logger.error("ffmpeg conversion timed out for %s", audio_file.name)
            wav_path.unlink(missing_ok=True)
            return None
        if result.returncode != 0 or not wav_path.exists():
            logger.error(
                "ffmpeg conversion failed for %s (rc=%s): %s",
                audio_file.name,
                result.returncode,
                (result.stderr or "").strip()[:300],
            )
            wav_path.unlink(missing_ok=True)
            return None
        return wav_path

    # Markers in whisper.cpp stderr that mean the *Metal* backend is unusable,
    # so a `-ng` (GPU off) retry is worth the wall clock. Error lines ONLY:
    # the bare words "ggml_metal" / "Core ML" / "tensor API disabled" show up
    # in every healthy run ("whisper_init_state: Core ML model loaded"), and
    # matching those made every GPU attempt look like a failure — Core ML was
    # never actually exercised, and the verdict got persisted as fact.
    _METAL_FAIL_MARKERS = (
        # init-time
        "ggml_metal_init: error",
        "ggml_metal_init: failed",
        "ggml_metal_device_init: error",
        "ggml_metal_device_init: failed",
        "ggml_metal_library_init: error",
        "ggml_metal_library_init: failed",
        "failed to allocate Metal",
        "whisper_backend_init_gpu: failed",
        "MTLLibraryErrorDomain",
        # run-time: the GPU can also die *after* a clean init — command buffers
        # fail mid-graph (ggml-metal-context.m) and pipelines compile lazily
        # (ggml-metal-device.m). Without these a GPU that dies two hours into a
        # recording is a hard error instead of a `-ng` retry. Only covers a GPU
        # that *says* it failed: one that simply wedges still ends the recording
        # on TRANSCRIPTION_TIMEOUT, with no fallback attempt.
        "ggml_metal_synchronize: error",
        "failed with status",
        "failed to compile pipeline",
    )

    # A Core ML encoder that won't load is NOT recoverable by retrying: this
    # whisper-cli is built without WHISPER_COREML_ALLOW_FALLBACK, so it aborts
    # (rc=3) before decoding a single frame — with or without `-ng`, since -ng
    # only turns off Metal and the encoder still goes through Core ML. Retrying
    # just burns another full run; surface an actionable error instead.
    _COREML_LOAD_FAIL_MARKERS = ("failed to load Core ML model",)

    # Proof that whisper finished writing the transcript. File existence is not
    # that proof: `fout = std::ofstream{fname_out}` creates and truncates the
    # TXT *before* whisper prints "saving output to", and the content follows.
    # A wedge during that write (a stalled iCloud writeback on the synced output
    # dir is exactly the kind of stall this feature exists for) leaves an empty
    # or truncated file behind. whisper prints its timings only after the
    # ofstream has gone out of scope — i.e. after the file was flushed and
    # closed — so this marker, and only this marker, means "the text is on disk".
    _TRANSCRIPT_WRITTEN_MARKER = "whisper_print_timings"

    def _coreml_load_failed(self, stderr: Optional[str]) -> bool:
        """True when whisper aborted because the Core ML encoder wouldn't load."""
        if not stderr:
            return False
        return any(marker in stderr for marker in self._COREML_LOAD_FAIL_MARKERS)

    def _should_retry_without_gpu(
        self,
        stderr: Optional[str],
        *,
        gpu_attempted: bool,
        returncode: int,
    ) -> bool:
        """Determine if the whisper run should be retried with the GPU off.

        Args:
            stderr: stderr output from the whisper.cpp invocation.
            gpu_attempted: True only if that run actually allowed Metal.
            returncode: whisper's exit status; a clean run is never retried,
                whatever its stderr happens to mention.

        Returns:
            True when Metal genuinely failed and a `-ng` retry is warranted.
        """
        if not gpu_attempted or not stderr or returncode == 0:
            return False

        return any(marker in stderr for marker in self._METAL_FAIL_MARKERS)

    def _summary_coverage(
        self, transcript_text: str, summarized_by_llm: bool
    ) -> Optional[float]:
        """Fraction of the recording the summary describes, or None when full.

        Measured on a real 3h11m meeting: the summarizer read the last 5.5% of
        it and produced a summary that named none of the material the meeting
        was actually about. The cap is now high enough that this is rare, but
        "rare" is not "never" — so a partial summary says so in the note
        instead of passing for a complete one.

        None (no frontmatter key) means there is no window to warn about: the
        whole transcript was read, or no LLM summary exists at all (empty
        recording, AI disabled, fallback summary) — a fallback note describes
        nothing, so a coverage number would be a lie of a different kind.

        A summarizer that cannot state its cap also yields None. This flag is a
        cosmetic honesty marker; it must never be the reason a transcription
        fails to be written.
        """
        if not summarized_by_llm or not self.summarizer:
            return None
        cap = getattr(self.summarizer, "transcript_cap", None)
        if not isinstance(cap, int) or cap <= 0:
            return None
        coverage = transcript_coverage(transcript_text, cap)
        if coverage >= 1.0:
            return None
        return round(coverage, 3)

    def _record_llm_usage(self, call: str, client: object, meter: "NoteMeter") -> None:
        """Log one paid call to the per-note cost ledger. Best-effort.

        Reads ``last_usage`` off the summarizer/tagger right after its call —
        the alias retry runs on the same summarizer instance and overwrites it,
        which is why every call site records before the next one starts.
        """
        usage = getattr(client, "last_usage", None)
        if usage is None:
            # No API call happened (empty input, or an error swallowed into a
            # fallback summary). Billing this note would charge it the previous
            # note's tokens — the client instance is long-lived.
            return
        try:
            from src.connections.insight_metrics import record_note_llm_call

            record_note_llm_call(
                call=call,
                note=meter.note,
                model=str(getattr(client, "model", "")),
                usage=usage,
                source_type=meter.source_type,
                duration_seconds=meter.duration_seconds,
                version=meter.version,
            )
        except Exception as exc:  # noqa: BLE001 - instrument, never a blocker
            logger.debug("note-llm metering skipped: %s", exc)

    def _count_ai_hours(self, duration_seconds: Optional[int]) -> None:
        """Add this note's audio to the monthly AI budget; notify once at 80%.

        Only recordings that actually got an AI summary count — local
        transcription is free and unlimited, and the weekly digest is a flat
        cost outside this budget.
        """
        try:
            from src import usage_ledger

            usage = usage_ledger.add_ai_seconds(duration_seconds)
            budget = int(getattr(self.config, "AI_HOURS_BUDGET", 0) or 0)
            if budget <= 0 or usage.notified_80:
                return
            if usage.budget_fraction(budget) < 0.8:
                return
            send_notification(
                "Timshel",
                f"AI use this month: {usage_ledger.format_hours(usage.ai_seconds)}"
                f" of {budget}h.",
                "Transcription stays unlimited.",
            )
            usage_ledger.mark_notified_80()
        except Exception as exc:  # noqa: BLE001 - budget display, never a blocker
            logger.debug("AI-hours accounting skipped: %s", exc)

    def _canonicalize_aliases(
        self,
        summary: dict,
        transcript_text: str,
        known_terms: str,
        *,
        meter: Optional["NoteMeter"] = None,
    ) -> dict:
        """Judge the summary for un-canonicalised aliases; ONE corrective retry.

        The model owns canonicalisation (a code substitution would stop the
        vocabulary learning new variants — see ``VocabularyIndex.find_alias_hits``).
        This detects confirmed aliases the model left outside the Quotes section
        and, if any, re-prompts it ONCE naming the specific misses. The retry is
        accepted only when it is non-empty and not itself a fallback. A miss that
        survives the retry is logged as a model-quality signal, never patched.
        The extra Haiku call happens only on a miss, so a clean summary is free.
        """
        if not summary:
            return summary
        misses = find_alias_misses(summary.get("summary", ""), self.vocabulary)
        if not misses:
            return summary

        correction = "\n".join(f"- '{a}' → '{c}'" for a, c in misses)
        try:
            retry = self.summarizer.generate(
                transcript_text,
                known_terms_block=known_terms,
                correction=correction,
            )
            if meter is not None:
                # Its own row, not folded into the summary: this retry fires on
                # roughly 40% of meetings and doubles that note's summary spend.
                self._record_llm_usage("alias_retry", self.summarizer, meter)
        except APIBillingError as exc:
            # Keep the first (good) summary; disable AI for subsequent notes.
            self._disable_ai(_is_permanent_api_error(exc) or "billing", exc)
            logger.warning(
                "alias-judge retry hit billing error — keeping first summary"
            )
            return summary

        retry_summary = retry.get("summary", "") if retry else ""
        if retry_summary and not is_fallback_summary(retry_summary):
            summary = retry
            misses = find_alias_misses(retry_summary, self.vocabulary)

        if misses:
            survivors = ", ".join(sorted({a for a, _ in misses}))
            logger.warning("alias-miss survived retry: %s", survivors)
        return summary

    @staticmethod
    def _extract_fallback_title(transcript: str, max_chars: int = 60) -> str:
        """Wyciągnij sensowny tytuł fallback z pierwszych słów transkryptu.

        Używane gdy AI summarizer nie jest dostępny (brak klucza, brak
        kredytów, błąd sieci). Lepsze niż "260430 0173" dla człowieka.

        Args:
            transcript: Treść transkryptu (po-whisperowa).
            max_chars: Maksymalna długość zwracanego tytułu.

        Returns:
            Pierwsze zdanie skrócone do ``max_chars``, lub pusty string
            gdy transkrypt jest pusty / sam ``(Brak rozpoznawalnej mowy)``.
        """
        text = (transcript or "").strip()
        if not text or text.startswith("(Brak"):
            return ""
        # Pierwsze zdanie (rozdzielone . ! ? lub nową linią).
        first = re.split(r"[.!?\n]", text, maxsplit=1)[0].strip()
        if not first:
            return ""
        if len(first) <= max_chars:
            return first
        truncated = first[:max_chars].rsplit(" ", 1)[0]
        if not truncated:
            truncated = first[:max_chars]
        return truncated.rstrip() + "…"

    @staticmethod
    def _wait_for_output_file(
        path: Path,
        timeout: float = 120.0,
        interval: float = 0.5,
    ) -> bool:
        """Czekaj aż plik będzie widoczny w filesystem i ma rozmiar > 0.

        whisper-cli zapisuje TXT do TRANSCRIBE_DIR — gdy ten katalog leży
        w iCloud Drive (np. ~/Library/Mobile Documents/iCloud~md~obsidian/...),
        File Provider chwilowo zwraca False z ``Path.exists()`` mimo że
        plik fizycznie istnieje. Empirycznie obserwowane lag-i Apple
        File Provider sięgają ~90 s przy świeżej synchronizacji, więc
        polling do 120 s pokrywa wszystkie obserwowane przypadki.

        Sprawdzamy też że plik ma >0 bajtów — żeby nie wracać True dla
        placeholder który CloudKit utworzył przed dosynchronizowaniem
        właściwej zawartości.

        Lokalne katalogi: pierwsza iteracja zwraca natychmiast (no-op).
        """
        deadline = time.time() + max(timeout, 0.0)
        while time.time() < deadline:
            try:
                if path.exists() and path.stat().st_size > 0:
                    return True
            except OSError:
                pass
            time.sleep(max(interval, 0.05))
        try:
            return path.exists() and path.stat().st_size > 0
        except OSError:
            return False

    def _stall_key(self, audio_file: Path, fingerprint: Optional[str] = None) -> str:
        """Identity of a recording for the one-retry-after-a-stall rule.

        The caller's fingerprint whenever there is one: computing our own would
        omit ``recording_datetime``, and for a tagless .m4a that falls back to
        mtime — which iCloud rewrites on re-sync. The key would then differ on
        every cycle, the second stall would never be recognised as a repeat, and
        the recording would run whisper twice per cycle forever: exactly the
        loop this counter exists to stop.

        Content, not filename: recorders reuse names (`DS300001.WAV` on every
        card), so a stem would let one recording spend the second chance that
        belongs to another. Falls back to the path when the file cannot be
        fingerprinted — a weaker key must never be worse than raising here.
        """
        if fingerprint:
            return fingerprint
        try:
            return compute_fingerprint(audio_file)
        except Exception as exc:  # noqa: BLE001 - identity is best-effort
            logger.debug("Could not fingerprint %s for stall key: %s", audio_file, exc)
            return str(audio_file.resolve())

    def _record_stall_strike(
        self, audio_file: Path, fingerprint: Optional[str] = None
    ) -> None:
        """Give a stalled recording one more cycle — but only one.

        The same reasoning that keeps the GPU verdict unwritten applies to the
        recording: if a backup or a sleeping disk wedged this run, the note is
        fine and deserves the next cycle. The second stall on the same recording
        makes it permanent, so a truly wedged machine does not retry forever.

        Keyed by content, not by name (see :meth:`_stall_key`).
        """
        stall_key = self._stall_key(audio_file, fingerprint)
        if stall_key in self._stalled_once:
            logger.warning(
                "  Stalled twice — %s will not be retried this session",
                audio_file.name,
            )
            return
        self._stalled_once.add(stall_key)
        self._last_run_was_transient_failure = True

    def _retire_stall(
        self, audio_file: Path, fingerprint: Optional[str] = None
    ) -> None:
        """A run that finished retires the earlier stall.

        The next stall is a first stall again, not a second one inherited from a
        problem the machine has evidently recovered from. Guarded so the normal
        path — nothing ever stalled — never pays for computing a key.
        """
        if self._stalled_once:
            self._stalled_once.discard(self._stall_key(audio_file, fingerprint))

    def _run_macwhisper(
        self, audio_file: Path, fingerprint: Optional[str] = None
    ) -> Optional[Path]:
        """Run whisper.cpp transcription and return path to TXT file.

        Args:
            audio_file: Path to the audio file to transcribe
            fingerprint: The recording's canonical identity, when the caller
                already has it. Used to key the one-retry-after-a-stall rule
                (see :meth:`_stall_key`).

        Returns:
            Path to created TXT file, or None if transcription failed.
            When returning None, ``self._last_run_was_transient_failure``
            is set: True for transient cases (whisper rc=0 but output
            file never appeared — usually iCloud sync lag), False for
            permanent failures (rc≠0, timeout, exception). Callers use
            this to decide whether to retry on the next cycle.
        """
        self._last_run_was_transient_failure = False
        if not self.whisper_available:
            logger.error("whisper.cpp not available, cannot transcribe")
            return None

        # Generate expected output file path
        output_file = self.config.TRANSCRIBE_DIR / f"{audio_file.stem}.txt"
        file_id = audio_file.stem

        # Check if already in progress
        if file_id in self.transcription_in_progress:
            logger.info(f"⏳ Already transcribing: {audio_file.name}")
            return None

        # Check if already transcribed (check for both TXT and MD)
        if output_file.exists():
            logger.info(f"✓ Already transcribed: {audio_file.name}")
            return output_file

        # Check if markdown version exists
        md_pattern = f"{audio_file.stem}*.md"
        existing_md = list(self.config.TRANSCRIBE_DIR.glob(md_pattern))
        if existing_md:
            logger.info(f"✓ Already transcribed (markdown exists): {audio_file.name}")
            return None

        logger.info(f"🎙️  Starting transcription: {audio_file.name}")
        self.transcription_in_progress[file_id] = True
        self._update_state(AppStatus.TRANSCRIBING, audio_file.name)

        wav_for_whisper: Optional[Path] = None
        # A stalled run can leave a truncated TXT behind (whisper creates the
        # file before writing it). Tracked across the whole call, not at the
        # exit that noticed the stall: the Core ML diagnosis and the timeout
        # both return earlier, and a fragment left on disk is adopted by the
        # crash-recovery path on the next cycle and filed as the finished note,
        # with whisper never re-running. Bound before the try so `finally` can
        # read it however we leave.
        stalled_unconfirmed = False
        try:
            # Ensure output directory exists
            self.config.TRANSCRIBE_DIR.mkdir(parents=True, exist_ok=True)

            # Normalise to 16 kHz mono WAV first. whisper-cli cannot decode
            # m4a/aac/wma directly; converting up front makes every supported
            # format work and fixes non-16 kHz / stereo inputs.
            wav_for_whisper = self._convert_to_wav(audio_file)
            if wav_for_whisper is None:
                error_msg = "Konwersja audio nieudana (uszkodzony/nieobsługiwany plik)"
                logger.error(
                    "✗ Could not convert %s to WAV — skipping", audio_file.name
                )
                self._update_state(AppStatus.ERROR, audio_file.name, error_msg)
                return None

            # Try with the GPU first (unless a prior/persisted Metal failure
            # already took it off the table for this session). Track what we
            # actually attempted: passing a hardcoded True to the retry check
            # made a GPU-less run look like a failed GPU run, so every single
            # transcription ran twice, start to finish.
            def note_run(res: subprocess.CompletedProcess) -> None:
                nonlocal stalled_unconfirmed
                wrote = self._TRANSCRIPT_WRITTEN_MARKER in (res.stderr or "")
                if getattr(res, "stalled", False) and not wrote:
                    stalled_unconfirmed = True
                elif wrote or res.returncode == 0:
                    # A later complete run overwrites whatever the stalled one
                    # left: the file on disk is a transcript again.
                    stalled_unconfirmed = False

            gpu_attempted = not self._gpu_disabled_in_session
            if gpu_attempted:
                logger.info("🔄 Attempting transcription with GPU acceleration")
            else:
                logger.info("🔄 Starting transcription (GPU disabled on this machine)")
            result = self._run_whisper_transcription(
                audio_file, use_gpu=gpu_attempted, source_audio=wav_for_whisper
            )
            note_run(result)

            logger.debug(
                f"Transcription attempt completed - "
                f"returncode: {result.returncode}, "
                f"stderr length: {len(result.stderr) if result.stderr else 0}"
            )

            def stalled_after_finishing() -> bool:
                """A stall that came *after* the transcript was safely written.

                Then the work is done and the wedge was in the teardown (a Metal
                driver that never returns): re-running would redo a whole
                transcription and lose the finished one if the retry stalled too.

                Requires whisper's own proof of a completed write
                (``_TRANSCRIPT_WRITTEN_MARKER``), not just a file on disk — see
                that constant for why existence means nothing here.
                """
                if not getattr(result, "stalled", False):
                    return False
                # Deliberately not "and output_file.exists()": whisper sometimes
                # writes under a different basename, which the verification
                # below already recovers. The marker says the stream was
                # flushed and closed; finding the file is that block's job.
                return self._TRANSCRIPT_WRITTEN_MARKER in (result.stderr or "")

            # If Metal failed, retry with the GPU off. Checked *before* the
            # stall branch: a GPU that reports an error and then wedges is a
            # reported failure first — reading it as a plain stall would skip
            # the verdict and leave every future recording to rediscover it.
            #
            # …unless the transcript is already written. Our own kill supplies
            # rc=-9, and a GPU dying in teardown prints the same runtime markers
            # (dead command buffer, pipeline), so this branch would otherwise
            # re-transcribe over the finished file — and record a permanent
            # verdict the stall path deliberately declines to record.
            if not stalled_after_finishing() and self._should_retry_without_gpu(
                result.stderr,
                gpu_attempted=gpu_attempted,
                returncode=result.returncode,
            ):
                logger.warning(
                    f"⚠️  Metal failed, falling back to CPU for {audio_file.name}"
                )
                if result.stderr:
                    logger.debug(f"  Error details: {result.stderr[:500]}")

                if not self._gpu_disabled_in_session:
                    self._gpu_disabled_in_session = True
                    self._persist_gpu_disabled()
                    logger.info(
                        "GPU disabled for this session and future launches "
                        "(Metal failed on this machine)"
                    )

                logger.info("🔄 Retrying transcription with GPU off")
                result = self._run_whisper_transcription(
                    audio_file, use_gpu=False, source_audio=wav_for_whisper
                )
                note_run(result)
                logger.debug(f"CPU retry completed - returncode: {result.returncode}")

            # A run we killed for going silent gets exactly one retry with the
            # GPU off — and, unlike a reported Metal failure, leaves no verdict
            # behind. A stall can come from outside Metal (a loaded CPU, a disk
            # going to sleep, iCloud), so condemning the GPU on this evidence
            # would be a guess; the `-ng` run is the experiment that tells us,
            # and it costs one recording, not every future one.
            elif (
                getattr(result, "stalled", False)
                and gpu_attempted
                and not stalled_after_finishing()
            ):
                logger.warning(
                    "⚠️  GPU attempt stalled for %s — retrying once with GPU off "
                    "(no permanent verdict recorded)",
                    audio_file.name,
                )
                result = self._run_whisper_transcription(
                    audio_file, use_gpu=False, source_audio=wav_for_whisper
                )
                note_run(result)
                logger.debug(f"Stall fallback completed - rc: {result.returncode}")

            elif gpu_attempted and result.returncode == 0:
                # Working GPU — retire any earlier one-off failure on record.
                self._clear_gpu_verdict()

            # A Core ML encoder that won't load is terminal for this build — no
            # retry can rescue it, so say what actually needs fixing. Checked on
            # the *final* result: an early-aborted GPU attempt is killed before
            # whisper even reaches the Core ML load, so the diagnosis can only
            # show up on the fallback run.
            if self._coreml_load_failed(result.stderr):
                error_msg = (
                    "Core ML encoder nie ładuje się — uruchom ponownie instalację "
                    "zależności (brakujący lub uszkodzony ggml-"
                    f"{self.config.WHISPER_MODEL}-encoder.mlmodelc)"
                )
                logger.error("✗ Core ML encoder failed to load: %s", audio_file.name)
                if result.stderr:
                    logger.error("  Error: %s", result.stderr[:500])
                self._update_state(AppStatus.ERROR, audio_file.name, error_msg)
                return None

            # Still silent after the fallback (or with the GPU already off):
            # nothing left to try, and a generic "kod: -9" would send the user
            # looking for a broken file instead of a wedged machine.
            if getattr(result, "stalled", False) and not stalled_after_finishing():
                # The measured silence, not a quoted threshold: a run killed
                # during startup was quiet for far longer than the decode
                # window, and saying "3 min" there is simply untrue.
                minutes = max(1, round(getattr(result, "stalled_after", 0) / 60))
                error_msg = (
                    f"Transkrypcja utknęła (brak postępu przez {minutes} min)"
                    if not gpu_attempted
                    else f"Transkrypcja utknęła (brak postępu przez {minutes} min) "
                    "także z wyłączonym GPU — sprawdź model i zależności"
                )
                logger.error(
                    "✗ Transcription stalled after %.0fs: %s (GPU %s)",
                    getattr(result, "stalled_after", 0),
                    audio_file.name,
                    "was already off" if not gpu_attempted else "off on the retry too",
                )
                self._record_stall_strike(audio_file, fingerprint)
                self._update_state(AppStatus.ERROR, audio_file.name, error_msg)
                return None

            if stalled_after_finishing():
                logger.warning(
                    "⚠️  whisper wedged after writing the transcript for %s — "
                    "keeping the finished TXT instead of transcribing again",
                    audio_file.name,
                )

            # Check for errors
            elif result.returncode != 0:
                error_msg = f"Transkrypcja nieudana (kod: {result.returncode})"
                if result.stderr:
                    error_msg = result.stderr[:200]
                logger.error(f"✗ Transcription failed: {audio_file.name}")
                logger.error(f"  Return code: {result.returncode}")
                if result.stderr:
                    logger.error(f"  Error: {result.stderr[:500]}")
                self._update_state(AppStatus.ERROR, audio_file.name, error_msg)
                return None

            logger.info(
                "✓ whisper.cpp process completed (rc=0): %s",
                audio_file.name,
            )

            # Verify output file was created. iCloud-synced TRANSCRIBE_DIR
            # może opóźnić widoczność świeżo zapisanego pliku przez File
            # Provider — retry pollem przez kilka sekund pokrywa ten lag.
            logger.info(f"Checking for output file: {output_file}")
            if output_file.exists() or self._wait_for_output_file(output_file):
                logger.info(f"✓ Transcription TXT verified: {output_file.name}")
                self._retire_stall(audio_file, fingerprint)
                return output_file
            else:
                logger.warning(
                    f"⚠️  Expected output file not found: {output_file}, "
                    f"searching for alternative files..."
                )
                # List what files were actually created
                output_dir = self.config.TRANSCRIBE_DIR
                created_files = list(output_dir.glob(f"{audio_file.stem}*"))
                logger.debug(
                    f"Found {len(created_files)} file(s) matching pattern "
                    f"'{audio_file.stem}*' in {output_dir}"
                )
                if created_files:
                    logger.warning(
                        f"⚠️  Expected output file not found, but found: "
                        f"{[f.name for f in created_files]}"
                    )
                    # Try to find .txt file with different name
                    txt_files = [f for f in created_files if f.suffix == ".txt"]
                    if txt_files:
                        logger.debug(f"✓ Using found file: {txt_files[0]}")
                        self._retire_stall(audio_file, fingerprint)
                        return txt_files[0]

                logger.error(
                    f"✗ Transcription completed but output file not found: "
                    f"{output_file}"
                )
                logger.error(f"  Searched directory: {output_dir}")
                logger.error(f"  Files found matching pattern: {len(created_files)}")
                try:
                    recent_cutoff = time.time() - 60.0
                    recent = []
                    for entry in output_dir.iterdir():
                        try:
                            if entry.stat().st_mtime >= recent_cutoff:
                                recent.append(entry.name)
                        except OSError:
                            continue
                    if recent:
                        logger.error(
                            "  Files in output_dir modified in last 60 s "
                            "(possible different basename): %s",
                            recent,
                        )
                except OSError as scan_err:
                    logger.error(
                        "  Could not list output_dir for diagnostics: %s",
                        scan_err,
                    )
                if result.stderr:
                    logger.error(f"  stderr: {result.stderr}")
                if result.stdout:
                    logger.info(f"  stdout: {result.stdout}")
                self._last_run_was_transient_failure = True
                return None

        except subprocess.TimeoutExpired:
            # A timeout on the attempt that *followed* a stall is still the
            # stall's story: the deadline is per attempt, so a wedge late in a
            # long recording hands the `-ng` re-run a full fresh hour it can
            # plausibly exceed on CPU. Reporting a bare timeout here would drop
            # both the diagnosis and the second chance the stall rule promises.
            if stalled_unconfirmed:
                error_msg = (
                    "Transkrypcja utknęła, a ponowna próba nie zdążyła "
                    f"w limicie ({self.config.TRANSCRIPTION_TIMEOUT}s)"
                )
                logger.error(
                    "✗ Stalled, then the retry hit the timeout (%ss): %s",
                    self.config.TRANSCRIPTION_TIMEOUT,
                    audio_file.name,
                )
                self._record_stall_strike(audio_file, fingerprint)
            else:
                error_msg = f"Timeout ({self.config.TRANSCRIPTION_TIMEOUT}s)"
                logger.error(
                    f"✗ Transcription timeout ({self.config.TRANSCRIPTION_TIMEOUT}s): "
                    f"{audio_file.name}"
                )
            self._update_state(AppStatus.ERROR, audio_file.name, error_msg)
            return None

        except Exception as e:
            error_msg = str(e)[:200]
            logger.error(f"✗ Error transcribing {audio_file.name}: {e}", exc_info=True)
            self._update_state(AppStatus.ERROR, audio_file.name, error_msg)
            return None

        finally:
            # Whatever exit we took, never leave a half-written transcript on
            # disk: the adoption path would treat it as the finished note.
            if stalled_unconfirmed and output_file.exists():
                logger.warning(
                    "  Removing unconfirmed transcript left by a stalled run: %s",
                    output_file.name,
                )
                output_file.unlink(missing_ok=True)
            # Drop the temporary converted WAV (best-effort).
            if wav_for_whisper is not None:
                wav_for_whisper.unlink(missing_ok=True)
            # Remove from in-progress tracking
            self.transcription_in_progress.pop(file_id, None)
            # Reset state if no more files in progress
            if not self.transcription_in_progress:
                self._update_state(AppStatus.IDLE)

    def _postprocess_transcript(
        self,
        audio_file: Path,
        transcript_path: Path,
        fingerprint: str,
        version: int = 1,
        previous_version: Optional[str] = None,
        output_filename: Optional[str] = None,
        recorded_at: Optional[datetime] = None,
        provenance: Optional[Dict[str, str]] = None,
    ) -> Optional[Path]:
        """Post-process transcript: generate summary and create markdown.

        Args:
            audio_file: Original audio file path
            transcript_path: Path to temporary TXT transcript file
            recorded_at: True recording time, when the caller knows it better
                than the file does (Voice Memos: parsed from the filename,
                because iCloud sync rewrites mtime).
            provenance: Extra frontmatter identifying the source
                (``source_type``/``origin``); merged over the audio defaults.

        Returns:
            True if post-processing succeeded, False otherwise
        """
        try:
            # Read transcript
            logger.debug(f"Reading transcript from: {transcript_path}")
            with open(transcript_path, "r", encoding="utf-8") as f:
                transcript_text = f.read()

            metadata = self.markdown_generator.extract_audio_metadata(audio_file)
            if recorded_at is not None:
                metadata["recording_datetime"] = recorded_at

            extra_frontmatter = {
                "source_volume": audio_file.parent.name,
                "model": self.config.WHISPER_MODEL,
                "language": self.config.WHISPER_LANGUAGE,
            }
            extra_frontmatter.update(provenance or {})

            md_path = self._finalize_note(
                transcript_text,
                metadata,
                fingerprint,
                version=version,
                previous_version=previous_version,
                output_filename=output_filename,
                fallback_title=audio_file.stem.replace("_", " ").title(),
                extra_frontmatter=extra_frontmatter,
            )
            if md_path is None:
                return None

            # Delete temporary TXT file if configured
            if self.config.DELETE_TEMP_TXT:
                try:
                    transcript_path.unlink()
                    logger.debug(
                        f"✓ Deleted temporary TXT file: {transcript_path.name}"
                    )
                except OSError as e:
                    logger.warning(f"Could not delete temporary TXT file: {e}")
                self._cleanup_transcript_sidecar(transcript_path)

            return md_path

        except Exception as e:
            logger.error(
                f"Post-processing failed for {audio_file.name}: {e}", exc_info=True
            )
            return None

    def _finalize_note(
        self,
        transcript_text: str,
        metadata: Dict[str, Any],
        fingerprint: str,
        *,
        version: int = 1,
        previous_version: Optional[str] = None,
        output_filename: Optional[str] = None,
        fallback_title: str = "Nagranie",
        extra_frontmatter: Optional[Dict[str, str]] = None,
    ) -> Optional[Path]:
        """Summarize → tag → render one note. The single 'text → note' tail,
        shared by audio post-processing and text import (``src.ingest``).

        ``metadata`` is the dict :meth:`MarkdownGenerator.extract_audio_metadata`
        returns (``source_file``, ``recording_datetime``, ``duration_*``); the
        import path synthesizes it without audio. ``extra_frontmatter`` carries
        source-specific keys (audio: source_volume/model/language; import:
        source_type/origin) merged over the common fingerprint/version block.
        """
        # Empty transcript is legal (silence, music) — write a placeholder note
        # so the file is indexed and doesn't loop in the retry queue.
        empty_transcript = not transcript_text.strip()
        if empty_transcript:
            logger.info("Pusty transkrypt — generuję markdown-placeholder")
            transcript_text = "(Brak rozpoznawalnej mowy w nagraniu)"

        duration_seconds = metadata.get("duration_seconds")
        meter = NoteMeter(
            note=fingerprint,
            source_type=(extra_frontmatter or {}).get("source_type") or "recorder",
            version=int(version),
            duration_seconds=(
                int(duration_seconds)
                if isinstance(duration_seconds, (int, float))
                and not isinstance(duration_seconds, bool)
                else None
            ),
        )

        summary = None
        summarized_by_llm = False
        if empty_transcript:
            summary = {
                "title": fallback_title,
                "summary": "(Brak rozpoznawalnej mowy w nagraniu)",
            }
        elif self.summarizer and self._ai_disabled_reason is None:
            try:
                logger.info("📝 Generating summary...")
                known_terms = self.vocabulary.known_terms_block()
                summary = self.summarizer.generate(
                    transcript_text,
                    known_terms_block=known_terms,
                )
                summarized_by_llm = True
                self._record_llm_usage("summary", self.summarizer, meter)
                summary = self._canonicalize_aliases(
                    summary, transcript_text, known_terms, meter=meter
                )
                # Aliases first (that step may rewrite the whole summary),
                # then the deterministic stance-subject guard on the final text.
                summary["summary"] = guard_stance_subjects(
                    summary.get("summary", ""), self.vocabulary
                )
                logger.info(f"✓ Summary generated: {summary.get('title', 'N/A')}")
            except APIBillingError as exc:
                self._disable_ai(_is_permanent_api_error(exc) or "billing", exc)
                summary = None
            except Exception as e:
                logger.error(f"Summary generation failed: {e}", exc_info=True)
                logger.warning("Continuing without summary")
                summary = None

        if not summary:
            logger.debug("Using fallback summary")
            title = self._extract_fallback_title(transcript_text) or fallback_title
            summary = {
                "title": title,
                "summary": """## Podsumowanie

Brak podsumowania AI. Możliwe przyczyny:
- klucz Claude API (ANTHROPIC_API_KEY) nie jest skonfigurowany
- konto Anthropic nie ma kredytów (https://console.anthropic.com/settings/billing)
- przejściowy błąd sieci

## Lista działań (To-do)

- Przejrzeć transkrypcję ręcznie
- Wyciągnąć kluczowe wnioski ze spotkania""",
            }

        tags = [GENERATED_TAG]
        if empty_transcript:
            tags.append("transcript-empty")
        if (
            not empty_transcript
            and self.config.ENABLE_LLM_TAGGING
            and self.tagger
            and self._ai_disabled_reason is None
        ):
            try:
                existing_tags = self.tag_index.existing_tags_ranked()
                generated_tags = self.tagger.generate_tags(
                    transcript=transcript_text,
                    summary_markdown=summary.get("summary", ""),
                    existing_tags=existing_tags,
                    known_entities=self.vocabulary.canonical_terms_block(),
                )
                self._record_llm_usage("tags", self.tagger, meter)
                for tag in generated_tags:
                    if tag not in tags:
                        tags.append(tag)
            except APIBillingError as exc:
                self._disable_ai(_is_permanent_api_error(exc) or "billing", exc)
            except Exception as error:  # noqa: BLE001
                logger.error("Tag generation failed: %s", error, exc_info=True)

        frontmatter = {
            "fingerprint": fingerprint,
            "version": version,
            "transcribed_on": get_hostname(),
            "previous_version": previous_version or "",
        }
        # Honesty about scope: only written when the summarizer read a window
        # rather than the whole recording, so the 99% of notes that fit stay
        # clean and the rare over-long one cannot pass as a full summary.
        coverage = self._summary_coverage(transcript_text, summarized_by_llm)
        if coverage is not None:
            frontmatter["summary_coverage"] = coverage
        frontmatter.update(extra_frontmatter or {})

        logger.info("📄 Creating markdown document...")
        md_path = self.markdown_generator.create_markdown_document(
            transcript=transcript_text,
            summary=summary,
            metadata=metadata,
            output_dir=self.config.TRANSCRIBE_DIR,
            tags=tags,
            extra_frontmatter=frontmatter,
            output_filename=output_filename,
        )
        logger.info(f"✓ Markdown document created: {md_path.name}")
        # Budget accounting LAST, and only for a note that really got an AI
        # summary. Rendering can fail (vault unmounted, disk full) and the
        # periodic scan then retries the whole tail every 30s — counting before
        # the note exists would burn a 30h budget in minutes on one recording.
        # Cost rows stay where they are: that spend was real either way.
        # A retranscribe (version 2+) charges the recording's hours again.
        # Deliberate: the second summary is a second real API call. The rows
        # carry ``version`` so a cost analysis can separate the two.
        if summarized_by_llm and not is_fallback_summary(summary.get("summary", "")):
            self._count_ai_hours(meter.duration_seconds)
        return md_path

    def _find_existing_markdown_for_audio(self, audio_file: Path) -> Optional[Path]:
        """Find existing markdown note for given audio file.

        Looks for markdown files in the transcription directory whose YAML
        frontmatter contains a ``source: <audio_file.name>`` line. This allows
        us to reliably detect previously processed recordings even if markdown
        filenames change when the summary title changes.

        Args:
            audio_file: Audio file whose markdown note we want to find.

        Returns:
            Path to existing markdown file if found, otherwise None.
        """
        try:
            if not self.config.TRANSCRIBE_DIR.exists():
                return None

            for md_path in self.config.TRANSCRIBE_DIR.glob("*.md"):
                try:
                    frontmatter = read_frontmatter(md_path)
                    if frontmatter.get("source", "").strip() == audio_file.name:
                        return md_path
                except OSError as read_error:
                    logger.warning(
                        "Could not read markdown file %s: %s",
                        md_path,
                        read_error,
                    )
                    continue
        except Exception as error:
            logger.error(
                "Error searching for existing markdown for %s: %s",
                audio_file.name,
                error,
            )

        return None

    # Below this many index entries, an empty vault is just a small vault the
    # user emptied — cleaning up is correct and lets those recordings be
    # transcribed again. Above it, an empty vault means something is wrong
    # with the READ, not with the user's intent.
    _ORPHAN_CLEANUP_MIN = 5

    def _vault_transcript_files(self, transcribe_dir: Path) -> List[Path]:
        """Every transcript note in the vault, including sub-folders.

        A flat ``glob("*.md")`` was the bug: filing notes into folders is
        ordinary Obsidian housekeeping, and to a flat scan those notes simply
        vanish — reconciliation then declared their index entries orphaned and
        the whole archive got re-transcribed, at cost, on the next scan. The
        rest of the app already walks the vault recursively (menu_app's recent
        list, obsidian_link); reconciliation was the outlier.

        Skips what the app itself writes (digests, recall answers, the sidecar
        dir) so generated files never masquerade as transcripts.
        """
        from src.connections.recall.answer_writer import RECALL_DIR_NAME

        excluded_dirs = {
            self.config.DIGEST_DIR_NAME,
            self.config.SIDECAR_DIR_NAME,
            RECALL_DIR_NAME,
            ".malinche",  # pre-rename sidecar, may survive a migration
            # Obsidian's own dirs. .trash matters for correctness, not just
            # noise: "Move to Obsidian trash" is the default delete, and a
            # note found there would keep its index entry alive — silently
            # breaking delete-then-replug as a way to redo a bad transcript.
            ".trash",
            ".obsidian",
        }
        files: List[Path] = []
        for path in transcribe_dir.rglob("*.md"):
            try:
                parts = path.relative_to(transcribe_dir).parts
            except ValueError:  # pragma: no cover - defensive
                continue
            if any(part in excluded_dirs for part in parts[:-1]):
                continue
            files.append(path)
        return files

    def reconcile_existing_markdowns(self) -> Dict[str, int]:
        """Synchronizuj vault_index z plikami w TRANSCRIBE_DIR.

        Cztery scenariusze:
        * MD na dysku, brak fingerprintu w vault_index → dodaj wpis.
        * MD na dysku, MD-towarzyszący ``<source.stem>.txt`` → usuń .txt
          (DELETE_TEMP_TXT default True; cleanup zaległych).
        * Wpis w vault_index, ale jego ``markdown_path`` nie istnieje na
          dysku (orphan po manualnym/force_retranscribe usunięciu MD) →
          usuń wpis, żeby przy kolejnym scan plik audio mógł być
          przetranskrybowany ponownie.
        * .txt na dysku bez sąsiadującego MD → potraktuj jako "TXT bez
          markdown" i wypchnij plik MP3 na listę pending; postprocess
          wygeneruje brakujący markdown w `transcribe_file` ścieżką
          "TXT-already-exists" (bez ponownego whispera).

        Idempotentne: kolejne wywołanie nie robi nic gdy stan jest spójny.

        Returns:
            Dict z licznikami:
            ``{"indexed": N, "orphan_cleaned": K, "txt_cleaned": M, "txt_recovered": R}``.
        """
        result = {
            "indexed": 0,
            "orphan_cleaned": 0,
            "txt_cleaned": 0,
            "txt_recovered": 0,
        }
        transcribe_dir = self.config.TRANSCRIBE_DIR
        result["orphan_skipped"] = 0

        if not transcribe_dir.exists():
            return result

        try:
            md_files = self._vault_transcript_files(transcribe_dir)
        except OSError as error:
            logger.debug("Reconciliation: could not list %s: %s", transcribe_dir, error)
            return result

        # ---- Etap A: MD na dysku — buduj mapy fingerprint → md_path i source → ----
        # Czytamy frontmatter każdego MD raz; zbieramy fingerprinty żeby
        # zarówno (a) uzupełnić vault_index oraz (b) wykryć orphan wpisy.
        md_fingerprints: set[str] = set()
        md_sources: set[str] = set()
        for md_path in md_files:
            try:
                fm = read_frontmatter(md_path)
            except Exception as error:  # noqa: BLE001
                logger.debug("Reconciliation: skipping %s: %s", md_path.name, error)
                continue

            fingerprint = fm.get("fingerprint", "").strip()
            source = fm.get("source", "").strip()
            if not fingerprint or not source:
                continue
            md_fingerprints.add(fingerprint)
            md_sources.add(source)

            if not self.vault_index.lookup(fingerprint):
                try:
                    version = int(fm.get("version", "1") or "1")
                except ValueError:
                    version = 1
                # Path RELATIVE to the vault, not the bare name: consumers
                # resolve it as TRANSCRIBE_DIR / markdown_path, so a note the
                # user filed into a sub-folder would otherwise be recorded as
                # a path that does not exist.
                try:
                    md_rel = md_path.relative_to(transcribe_dir).as_posix()
                except ValueError:  # pragma: no cover - defensive
                    md_rel = md_path.name
                self.vault_index.add(
                    fingerprint,
                    IndexEntry(
                        fingerprint=fingerprint,
                        source_filename=source,
                        source_volume=fm.get("source_volume", ""),
                        markdown_path=md_rel,
                        versions=[
                            {
                                "version": version,
                                "transcribed_at": fm.get("recording_date", ""),
                                "hostname": fm.get("transcribed_on", ""),
                                "model": fm.get("model", ""),
                                "language": fm.get("language", ""),
                                "markdown_path": md_rel,
                            }
                        ],
                    ),
                )
                result["indexed"] += 1

            # Cleanup osieroconego TXT towarzyszącego MD.
            try:
                source_stem = Path(source).stem
            except (TypeError, ValueError):
                continue
            if not source_stem:
                continue
            txt_path = transcribe_dir / f"{source_stem}.txt"
            if txt_path.exists():
                try:
                    txt_path.unlink()
                    self._cleanup_transcript_sidecar(txt_path)
                    result["txt_cleaned"] += 1
                    logger.debug("Reconciliation: removed leftover %s", txt_path.name)
                except OSError as error:
                    logger.debug(
                        "Reconciliation: could not remove %s: %s",
                        txt_path.name,
                        error,
                    )

        # ---- Etap B: orphan vault_index entries — TYLKO gdy żaden MD na dysku
        # nie zawiera tego fingerprintu w frontmatterze. Stary check po nazwie
        # pliku (markdown_path) niesłusznie kasował poprawne wpisy gdzie nazwa
        # MD na dysku zmieniła się (np. po zmianie tytułu po retranscribe). ----
        try:
            entries_snapshot = dict(self.vault_index._data.get("entries", {}))
        except Exception:  # noqa: BLE001
            entries_snapshot = {}
        orphans = [fp for fp in entries_snapshot if fp not in md_fingerprints]
        # Safety valve. Every entry dropped here sends its recording back
        # through transcription (and a paid summary) on the next scan, so a
        # scan that suddenly declares most of the vault orphaned is far more
        # likely to be a bad read — an unmounted iCloud vault, a permission
        # blip, a folder the user just moved — than a real mass deletion.
        # Refuse it and keep the index; the next run reconciles for real.
        # Distinguish the two cases by asking directly, not by remembering.
        # "The vault is unreadable" and "the user deleted their notes" differ
        # in one observable: a deletion leaves the OTHER notes in place, an
        # unreadable vault shows nothing at all. So refuse only when the scan
        # found no notes whatsoever while the index still holds entries —
        # a state no ordinary deletion produces. (An earlier version tried to
        # confirm across two runs; reconciliation only runs once per process,
        # so the confirming run never came and the entries were immortal.)
        if not md_files and len(entries_snapshot) >= self._ORPHAN_CLEANUP_MIN:
            result["orphan_skipped"] = len(orphans)
            logger.warning(
                "Reconciliation: the vault at %s holds no notes at all while the "
                "index has %s entries — refusing to clean up. The vault is most "
                "likely unmounted or still syncing; nothing will be re-transcribed "
                "on a false alarm.",
                transcribe_dir,
                len(entries_snapshot),
            )
            orphans = []

        for fp in orphans:
            # Brak MD z matching fingerprint: faktyczny orphan.
            try:
                if self.vault_index.remove(fp):
                    result["orphan_cleaned"] += 1
                    logger.debug(
                        "Reconciliation: removed orphan vault_index entry for %s (no MD has this fingerprint)",
                        fp[:24],
                    )
            except Exception as error:  # noqa: BLE001
                logger.debug(
                    "Reconciliation: could not remove orphan %s: %s", fp, error
                )

        # ---- Etap C: TXT bez MD na dysku — kandydat do recovery postprocess ----
        # Aplikacja sama wykryje to przy kolejnym `process_recorder` (TXT-exists
        # path w transcribe_file), ale liczymy tutaj dla loga.
        try:
            txt_files = list(transcribe_dir.glob("*.txt"))
        except OSError:
            txt_files = []
        for txt_path in txt_files:
            stem = txt_path.stem
            # Czy istnieje MD wskazujący na ten audio? Heurystyka: source field
            # ma rozszerzenie, więc szukamy `stem.MP3`, `stem.WAV`, itd.
            possible_sources = {
                f"{stem}.{ext}" for ext in ("MP3", "WAV", "M4A", "mp3", "wav", "m4a")
            }
            if md_sources & possible_sources:
                continue  # MD już istnieje, .txt zostanie sprzątnięty w etapie A
            result["txt_recovered"] += 1

        if any(result.values()):
            logger.info(
                "Reconciliation: indexed=%d, orphan_cleaned=%d, orphan_skipped=%d, "
                "txt_cleaned=%d, txt_recovered=%d",
                result["indexed"],
                result["orphan_cleaned"],
                result["orphan_skipped"],
                result["txt_cleaned"],
                result["txt_recovered"],
            )
        else:
            logger.debug("Reconciliation: nothing to do (vault_index in sync)")
        return result

    def _cache_fingerprint_for_existing_markdown(
        self, audio_file: Path, markdown_path: Path, fingerprint: str
    ) -> None:
        """Store canonical sha256 index entry after legacy source-name fallback."""
        if self.vault_index.lookup(fingerprint):
            return

        fm = read_frontmatter(markdown_path)
        try:
            version = int(fm.get("version", "1") or "1")
        except ValueError:
            version = 1

        try:
            audio_size = audio_file.stat().st_size
        except OSError:
            audio_size = 0
        self.vault_index.add(
            fingerprint,
            IndexEntry(
                fingerprint=fingerprint,
                source_filename=audio_file.name,
                source_volume=fm.get("source_volume", audio_file.parent.name),
                markdown_path=markdown_path.name,
                source_size=audio_size,
                versions=[
                    {
                        "version": version,
                        "transcribed_at": fm.get("recording_date", ""),
                        "hostname": fm.get("transcribed_on", ""),
                        "model": fm.get("model", ""),
                        "language": fm.get("language", ""),
                        "markdown_path": markdown_path.name,
                    }
                ],
            ),
        )

    def _remove_existing_transcription(self, audio_file: Path) -> Dict[str, List[str]]:
        """Remove existing transcription files for given audio.

        Finds and removes markdown files with matching source field,
        and removes TXT transcript file if it exists.

        Args:
            audio_file: Path to audio file (staged copy)

        Returns:
            Dict with 'removed_md' and 'removed_txt' lists containing
            names of removed files
        """
        removed = {"removed_md": [], "removed_txt": []}

        # Find and remove markdown files with matching source
        existing_md = self._find_existing_markdown_for_audio(audio_file)
        if existing_md:
            try:
                existing_md.unlink()
                removed["removed_md"].append(existing_md.name)
                logger.info(f"🗑️  Removed existing markdown: {existing_md.name}")
            except OSError as e:
                logger.warning(f"Could not remove {existing_md}: {e}")

        # Find and remove TXT file
        txt_path = self.config.TRANSCRIBE_DIR / f"{audio_file.stem}.txt"
        if txt_path.exists():
            try:
                txt_path.unlink()
                removed["removed_txt"].append(txt_path.name)
                logger.info(f"🗑️  Removed existing TXT: {txt_path.name}")
            except OSError as e:
                logger.warning(f"Could not remove {txt_path}: {e}")
        self._cleanup_transcript_sidecar(txt_path)

        return removed

    def force_retranscribe(self, audio_file: Path) -> bool:
        """Force re-transcription of a previously processed file.

        Removes existing transcription files (MD/TXT) and runs
        transcription again. Uses ProcessLock to prevent conflicts
        with automatic processing.

        Args:
            audio_file: Path to audio file (should be in staging directory)

        Returns:
            True if re-transcription succeeded, False otherwise
        """
        if not audio_file.exists():
            logger.error(f"Audio file not found: {audio_file}")
            return False

        logger.info(f"🔄 Force re-transcription requested: {audio_file.name}")

        # In-process guard first: an automatic process_recorder pass on the
        # periodic-checker thread is the usual contender for this lock.
        if not self._workflow_lock.acquire(blocking=False):
            logger.warning(
                "Cannot acquire workflow lock - another transcription in progress"
            )
            raise RetranscribeLockBusyError(
                "Auto transkrypcja w toku — spróbuj ponownie za chwilę."
            )

        # Cross-process guard (advisory flock, auto-released if the holder dies).
        lock = ProcessLock(self.config.PROCESS_LOCK_FILE)
        if not lock.acquire():
            logger.warning(
                "Cannot acquire process lock - another process is transcribing"
            )
            self._workflow_lock.release()
            raise RetranscribeLockBusyError(
                "Auto transkrypcja w toku — spróbuj ponownie za chwilę."
            )

        try:
            # Remove existing transcription files
            removed = self._remove_existing_transcription(audio_file)
            logger.info(
                f"Removed {len(removed['removed_md'])} MD, "
                f"{len(removed['removed_txt'])} TXT files"
            )

            # Również wyczyść vault_index — bez tego transcribe_file widzi
            # stary fingerprint i może przyjąć go za "Already transcribed"
            # (ścieżka FREE) albo wersjonować nową transkrypcję jako v2 mimo że
            # user explicite poprosił o nadpisanie.
            try:
                fingerprint = compute_fingerprint(audio_file)
                if self.vault_index.lookup(fingerprint):
                    self.vault_index.remove(fingerprint)
                    logger.info(
                        "Removed vault_index entry for fingerprint %s",
                        fingerprint,
                    )
                # Plus session blacklist — fingerprint mógł tam wpaść z
                # poprzedniej nieudanej próby; bez czyszczenia kolejny scan
                # by go pominął.
                self._session_failed_fingerprints.discard(fingerprint)
                # …i licznik zastojów: bez tego pierwszy zastój ręcznie
                # wznowionej transkrypcji liczy się jako drugi i nagranie
                # od razu wraca na blacklistę, choć user właśnie poprosił
                # o kolejną szansę.
                # Ten sam fingerprint co dwie linijki wyżej — liczenie
                # własnego dawałoby inny klucz (i drugi odczyt 1 MB).
                self._stalled_once.discard(self._stall_key(audio_file, fingerprint))
                # …i licznik nieudanych postprocessów: user właśnie naprawił
                # przyczynę (np. wrócił vault) i prosi o ponowną próbę, więc
                # nagranie ma dostać pełną pulę prób, nie zostatnią.
                self._postprocess_attempts.pop(fingerprint, None)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Could not clean vault_index entry before retranscribe: %s",
                    exc,
                )

            self._update_state(AppStatus.TRANSCRIBING, audio_file.name)

            success = self.transcribe_file(audio_file)

            if success:
                logger.info(f"✅ Re-transcription complete: {audio_file.name}")
            else:
                logger.error(f"❌ Re-transcription failed: {audio_file.name}")

            return success

        finally:
            lock.release()
            self._workflow_lock.release()
            # Reset state if no more files in progress
            if not self.transcription_in_progress:
                self._update_state(AppStatus.IDLE)

    # ------------------------------------------------------------------ #
    # TXT ownership sidecar
    #
    # A leftover ``{stem}.txt`` (crash between whisper and postprocess, or
    # DELETE_TEMP_TXT=False) used to be adopted as the CURRENT audio's
    # transcript purely by stem — recorders reset numbering, so REC001.MP3
    # from another card could permanently receive someone else's transcript.
    # The sidecar records which fingerprint a TXT belongs to; adoption is
    # allowed only on a match. A vault-index check cannot replace this: the
    # index entry is written only AFTER postprocess, i.e. it does not exist
    # yet in exactly the crash-recovery window adoption must serve.
    # ------------------------------------------------------------------ #
    @staticmethod
    def _transcript_sidecar_path(transcript_path: Path) -> Path:
        """Hidden ownership sidecar next to the TXT: ``.{stem}.txt.owner``."""
        return transcript_path.parent / f".{transcript_path.name}.owner"

    def _write_transcript_owner(
        self, transcript_path: Path, audio_file: Path, fingerprint: str
    ) -> None:
        """Best-effort: record which recording the upcoming TXT belongs to."""
        try:
            payload = {
                "fingerprint": fingerprint,
                "source": audio_file.name,
                "started_at": datetime.now().isoformat(timespec="seconds"),
            }
            self._transcript_sidecar_path(transcript_path).write_text(
                json.dumps(payload), encoding="utf-8"
            )
        except OSError as error:
            logger.debug("Could not write transcript sidecar: %s", error)

    def _owns_transcript(self, transcript_path: Path, fingerprint: str) -> bool:
        """True iff the sidecar exists and names this audio's fingerprint."""
        sidecar = self._transcript_sidecar_path(transcript_path)
        try:
            data = json.loads(sidecar.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, ValueError):
            return False
        return bool(fingerprint) and data.get("fingerprint") == fingerprint

    def _cleanup_transcript_sidecar(self, transcript_path: Path) -> None:
        """Remove the sidecar once its TXT is consumed or removed."""
        try:
            self._transcript_sidecar_path(transcript_path).unlink(missing_ok=True)
        except OSError:  # pragma: no cover - defensive
            pass

    def _quarantine_stale_transcript(self, transcript_path: Path) -> Optional[Path]:
        """Rename an unowned leftover TXT aside — never delete user data.

        Returns the new path, or ``None`` if the rename failed (in which case
        the caller proceeds and whisper simply overwrites the file).
        """
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        candidate = transcript_path.with_name(
            f"{transcript_path.stem}.stale-{stamp}.txt"
        )
        counter = 2
        while candidate.exists():
            candidate = transcript_path.with_name(
                f"{transcript_path.stem}.stale-{stamp}-{counter}.txt"
            )
            counter += 1
        try:
            transcript_path.rename(candidate)
        except OSError as error:
            logger.warning(
                "Could not move stale TXT %s aside: %s", transcript_path.name, error
            )
            return None
        self._cleanup_transcript_sidecar(transcript_path)
        return candidate

    def transcribe_file(
        self,
        audio_file: Path,
        *,
        recorded_at: Optional[datetime] = None,
        provenance: Optional[Dict[str, str]] = None,
    ) -> bool:
        """Transcribe a single audio file using whisper.cpp.

        Automatically retries with the GPU off if Metal fails.
        Post-processes transcript to create markdown document with summary.

        Args:
            audio_file: Path to the audio file to transcribe
            recorded_at: True recording time when the caller knows it better
                than the file (Voice Memos: from the filename). Also stabilises
                the fingerprint, which otherwise falls back to mtime.
            provenance: Extra frontmatter identifying the source.

        Returns:
            True if transcription succeeded, False otherwise
        """
        # If markdown already exists for this audio (based on `source` field),
        # treat it as successfully transcribed and skip any further work.
        fingerprint = compute_fingerprint(audio_file, recording_datetime=recorded_at)
        existing_entry = self.vault_index.lookup(fingerprint)
        # Tier gating removed: versioning (v2/v3) is available to everyone.
        can_version = True
        if existing_entry and not can_version:
            logger.info(
                "✓ Already transcribed (fingerprint exists): %s", audio_file.name
            )
            return True

        # If TXT transcript already exists AND belongs to this recording
        # (ownership sidecar), skip whisper and only post-process once to
        # create markdown — the crash-recovery path. An unowned TXT (legacy
        # leftover, or a different recording sharing the stem) is moved aside
        # and the audio transcribed fresh: wrong-transcript adoption is worse
        # than one redundant whisper run.
        transcript_path = self.config.TRANSCRIBE_DIR / f"{audio_file.stem}.txt"
        adopt_existing_txt = transcript_path.exists()
        if adopt_existing_txt and not self._owns_transcript(
            transcript_path, fingerprint
        ):
            adopt_existing_txt = False
            quarantined = self._quarantine_stale_transcript(transcript_path)
            if quarantined is None:
                # Can't move it aside and must not adopt it: skip this run
                # (retried next cycle) rather than risk attaching someone
                # else's transcript via the whisper-side early return.
                logger.error(
                    "✗ Stale TXT %s could not be moved aside — skipping %s "
                    "this cycle",
                    transcript_path.name,
                    audio_file.name,
                )
                self._last_run_was_transient_failure = True
                return False
            logger.warning(
                "⚠️  Leftover TXT %s did not belong to %s — moved aside as "
                "%s; transcribing fresh",
                transcript_path.name,
                audio_file.name,
                quarantined.name,
            )
        if adopt_existing_txt:
            logger.info(
                "✓ Transcription TXT already exists, "
                "creating markdown if needed: %s",
                audio_file.name,
            )
            md_path = self._postprocess_transcript(
                audio_file,
                transcript_path,
                fingerprint=fingerprint,
                version=1,
                recorded_at=recorded_at,
                provenance=provenance,
            )
            success = md_path is not None
            if success:
                logger.info("✓ Complete: %s", audio_file.name)
                self._index_completed_transcription(
                    audio_file=audio_file,
                    fingerprint=fingerprint,
                    md_path=md_path,
                    existing_entry=existing_entry,
                    version=1,
                )
            else:
                self._note_postprocess_failure(audio_file, fingerprint)
            return success

        # Run whisper transcription. The sidecar written first claims the
        # upcoming TXT for this fingerprint, so a crash between whisper and
        # postprocess stays recoverable (adoption above) without stem-only
        # guessing.
        self._write_transcript_owner(transcript_path, audio_file, fingerprint)
        transcript_path = self._run_macwhisper(audio_file, fingerprint=fingerprint)

        if transcript_path is None:
            if self._last_run_was_transient_failure:
                logger.info(
                    "Transient failure for %s — will retry on next cycle "
                    "(fingerprint: %s)",
                    audio_file.name,
                    fingerprint,
                )
            else:
                self._session_failed_fingerprints.add(fingerprint)
                logger.warning(
                    "Marked %s as failed for this session (fingerprint: %s)",
                    audio_file.name,
                    fingerprint,
                )
            return False

        # Post-process: generate summary and create markdown
        version = 1
        previous_version = None
        output_filename = None
        if existing_entry and can_version:
            version = len(existing_entry.versions) + 1
            previous_version = existing_entry.markdown_path
            output_filename = f"{audio_file.stem}.v{version}.md"
        md_path = self._postprocess_transcript(
            audio_file,
            transcript_path,
            fingerprint=fingerprint,
            version=version,
            previous_version=previous_version,
            output_filename=output_filename,
            recorded_at=recorded_at,
            provenance=provenance,
        )
        success = md_path is not None

        if success:
            logger.info(f"✓ Complete: {audio_file.name}")
        else:
            self._note_postprocess_failure(audio_file, fingerprint)

        if success and md_path is not None:
            self._index_completed_transcription(
                audio_file=audio_file,
                fingerprint=fingerprint,
                md_path=md_path,
                existing_entry=existing_entry,
                version=version,
            )

            self._post_note_hooks(md_path)

        return success

    # Post-processing buys a summary, and the periodic scan comes round every
    # 30 s: an unattended failure loop is real money, invisibly spent (the
    # AI-hours counter only ticks on success). But blacklisting on the first
    # failure trades that for a worse outcome — a two-minute iCloud outage
    # would cost the recording its note for the rest of a daemon session that
    # can run for weeks. A few spaced attempts cover the transient case and
    # still cap the spend.
    _POSTPROCESS_MAX_ATTEMPTS = 3

    def _note_postprocess_failure(self, audio_file: Path, fingerprint: str) -> None:
        """Count a failed post-process; give up only after several attempts."""
        attempts = self._postprocess_attempts.get(fingerprint, 0) + 1
        self._postprocess_attempts[fingerprint] = attempts
        if attempts >= self._POSTPROCESS_MAX_ATTEMPTS:
            self._session_failed_fingerprints.add(fingerprint)
            logger.warning(
                "⚠️  Post-processing failed %d times for %s — not retrying this "
                "session (fingerprint: %s). Use 'Retranscribe file…' once the "
                "cause is fixed.",
                attempts,
                audio_file.name,
                fingerprint,
            )
        else:
            logger.warning(
                "⚠️  Post-processing failed for %s (attempt %d of %d) — will retry",
                audio_file.name,
                attempts,
                self._POSTPROCESS_MAX_ATTEMPTS,
            )

    def _post_note_hooks(self, md_path: Path) -> None:
        """Fire the two opportunistic post-note hooks: bump the digest new-note
        counter and refresh the recall index. Both are best-effort and must
        NEVER disturb the caller. Shared by audio transcription and text import.
        """
        try:
            from src.connections import enqueue_connection_analysis

            enqueue_connection_analysis(self, md_path=md_path)
        except Exception as exc:  # noqa: BLE001
            logger.debug("connection enqueue skipped: %s", exc)

        try:
            from src.config.config import get_config

            if getattr(get_config(), "ENABLE_RECALL_INDEX", False):
                from src.connections.recall.seam import index_transcript_safe

                index_transcript_safe(md_path)
        except Exception as exc:  # noqa: BLE001
            logger.debug("recall index skipped: %s", exc)

    def stage_audio_file(self, source: Path) -> Path:
        """Copy a manually chosen audio file into the local staging area.

        Fallback path for when automatic recorder/SD detection misses a file:
        the user points Timshel at an audio file anywhere on disk. The
        original is never touched — a copy is placed in
        ``LOCAL_RECORDINGS_DIR`` (collision-safe) and returned for transcription.

        Args:
            source: Path to an audio file outside the watched volumes.

        Returns:
            Path to the staged copy inside ``LOCAL_RECORDINGS_DIR``.

        Raises:
            FileNotFoundError: if *source* does not exist or is not a file.
            ValueError: if *source* has an unsupported audio extension.
        """
        source = Path(source)
        if not source.is_file():
            raise FileNotFoundError(f"Not a file: {source}")
        if source.suffix.lower() not in self.config.AUDIO_EXTENSIONS:
            raise ValueError(
                f"Unsupported audio format {source.suffix!r}; expected one of "
                f"{sorted(self.config.AUDIO_EXTENSIONS)}"
            )

        staging_dir = self.config.LOCAL_RECORDINGS_DIR
        staging_dir.mkdir(parents=True, exist_ok=True)

        destination = self._unique_staging_path(staging_dir, source.name)
        self._copy_atomically(source, destination)
        logger.info("📥 Imported %s → %s", source.name, destination)
        return destination

    @staticmethod
    def _copy_atomically(source: Path, destination: Path) -> None:
        """Copy via a temp name and rename only once the copy is whole.

        Landing directly on the final name means an interrupted copy (device
        unplugged, app quit, an iCloud-evicted source going away mid-read)
        leaves a truncated file that looks ready — it gets transcribed and
        filed as a complete note, and the full recording later comes back as
        a duplicate.
        """
        tmp_path = destination.with_name(destination.name + ".partial")
        try:
            shutil.copy2(source, tmp_path)
            source_size = source.stat().st_size
            staged_size = tmp_path.stat().st_size
            if staged_size != source_size:
                raise OSError(
                    f"short copy: {staged_size} of {source_size} bytes "
                    f"(source went away mid-copy?)"
                )
            tmp_path.replace(destination)
        except BaseException:
            tmp_path.unlink(missing_ok=True)
            raise

    @staticmethod
    def _unique_staging_path(staging_dir: Path, filename: str) -> Path:
        """Return a non-colliding path in *staging_dir* for *filename*.

        If ``recording.mp3`` already exists, returns ``recording (1).mp3``,
        then ``recording (2).mp3``, etc., so a re-import never overwrites an
        earlier copy that may still be pending.
        """
        candidate = staging_dir / filename
        if not candidate.exists():
            return candidate
        stem = candidate.stem
        suffix = candidate.suffix
        index = 1
        while True:
            candidate = staging_dir / f"{stem} ({index}){suffix}"
            if not candidate.exists():
                return candidate
            index += 1

    def import_audio_file(
        self,
        source: Path,
        *,
        recorded_at: Optional[datetime] = None,
        provenance: Optional[Dict[str, str]] = None,
    ) -> bool:
        """Stage *source* and run the full single-file pipeline on the copy.

        Convenience wrapper around :meth:`stage_audio_file` +
        :meth:`transcribe_file` for the menu-bar "Import audio…" action and the
        Voice Memos connector (which passes ``recorded_at``/``provenance``).

        Takes the same locks as :meth:`force_retranscribe` — without them a
        manual import (menu background thread) could run a second whisper-cli
        concurrently with the automatic recorder workflow: 2×(cores-2)
        threads pegging every core and unsynchronized vault_index writes.
        Locks are acquired BEFORE staging so a busy rejection has zero side
        effects (no orphaned staged copy).

        Returns:
            True if transcription succeeded, False otherwise.

        Raises:
            RetranscribeLockBusyError: another transcription is in progress.
            FileNotFoundError / ValueError: propagated from
            :meth:`stage_audio_file` for invalid input.
        """
        if not self._workflow_lock.acquire(blocking=False):
            logger.warning(
                "Cannot acquire workflow lock - another transcription in progress"
            )
            raise RetranscribeLockBusyError(
                "Auto transkrypcja w toku — spróbuj ponownie za chwilę."
            )

        lock = ProcessLock(self.config.PROCESS_LOCK_FILE)
        if not lock.acquire():
            logger.warning(
                "Cannot acquire process lock - another process is transcribing"
            )
            self._workflow_lock.release()
            raise RetranscribeLockBusyError(
                "Auto transkrypcja w toku — spróbuj ponownie za chwilę."
            )

        try:
            staged = self.stage_audio_file(source)
            return self.transcribe_file(
                staged, recorded_at=recorded_at, provenance=provenance
            )
        finally:
            # Retention runs at the very end of a workflow, never during: the
            # staged copy is the only original while a recording is still
            # being processed. It lives in `finally` so it also runs on the
            # paths that never see a recorder — a user importing audio or
            # syncing Voice Memos accumulates staged files just the same, and
            # every early return above would otherwise skip the sweep.
            try:
                self.prune_staging_dir()
            except Exception as exc:  # noqa: BLE001 - must never block a batch
                logger.debug("Staging retention skipped: %s", exc)
            lock.release()
            self._workflow_lock.release()
            if not self.transcription_in_progress:
                self._update_state(AppStatus.IDLE)

    def import_text_file(self, source: Path, status: Optional[dict] = None) -> bool:
        """Import an already-transcribed text file (txt/md/vtt) as a note.

        Skips whisper entirely: parses the source via :mod:`src.ingest`, then
        runs the SAME summarize→render→index tail as audio (``_finalize_note``),
        so imported notes get v2 summaries (canonicalisation + Stanowiska), land
        in the vault index and recall, and feed the next digest. Imported notes
        carry ``source_type: import`` in frontmatter for provenance.

        Takes the same workflow + process locks as audio import so it can't run
        concurrently with a transcription (CPU/vault-index safety).

        Args:
            status: optional dict filled with ``{"duplicate": bool}`` so a caller
                can tell a freshly-written note from an already-indexed one. A
                re-import of the same text is a no-op (fingerprint dedup); without
                this signal the UI reports "Imported N" for pure duplicates and
                the user hunts for notes that were never re-written.

        Returns:
            True on success (or a duplicate already imported), False on failure.

        Raises:
            RetranscribeLockBusyError: another transcription is in progress.
            FileNotFoundError / ValueError: unsupported or empty source.
        """
        from src.ingest import parse, text_fingerprint

        if not self._workflow_lock.acquire(blocking=False):
            logger.warning(
                "Cannot acquire workflow lock - another transcription in progress"
            )
            raise RetranscribeLockBusyError(
                "Auto transkrypcja w toku — spróbuj ponownie za chwilę."
            )

        lock = ProcessLock(self.config.PROCESS_LOCK_FILE)
        if not lock.acquire():
            logger.warning(
                "Cannot acquire process lock - another process is transcribing"
            )
            self._workflow_lock.release()
            raise RetranscribeLockBusyError(
                "Auto transkrypcja w toku — spróbuj ponownie za chwilę."
            )

        try:
            doc = parse(Path(source))  # raises ValueError on unsupported/empty
            fingerprint = text_fingerprint(doc.text, doc.source_name)

            if self.vault_index.lookup(fingerprint):
                logger.info(
                    "✓ Already imported (fingerprint exists): %s", doc.source_name
                )
                if status is not None:
                    status["duplicate"] = True
                return True
            if status is not None:
                status["duplicate"] = False

            metadata = {
                "source_file": doc.source_name,
                "recording_datetime": doc.recorded_at,
                "duration_seconds": None,
                "duration_formatted": "00:00:00",
                "extension": Path(source).suffix.lower(),
            }
            self._update_state(AppStatus.TRANSCRIBING, doc.source_name)
            md_path = self._finalize_note(
                doc.text,
                metadata,
                fingerprint,
                fallback_title=doc.title,
                extra_frontmatter={"source_type": "import", "origin": doc.origin},
            )
            if md_path is None:
                logger.warning("Import post-processing failed: %s", doc.source_name)
                return False

            self._index_completed_transcription(
                Path(source), fingerprint, md_path, existing_entry=None
            )
            logger.info("✓ Imported: %s → %s", doc.source_name, md_path.name)
            self._post_note_hooks(md_path)
            return True
        finally:
            lock.release()
            self._workflow_lock.release()
            if not self.transcription_in_progress:
                self._update_state(AppStatus.IDLE)

    def _index_completed_transcription(
        self,
        audio_file: Path,
        fingerprint: str,
        md_path: Path,
        existing_entry: Optional[IndexEntry],
        version: int = 1,
    ) -> None:
        """Zarejestruj sukces transkrypcji w vault_index.

        Wcześniej tylko ścieżka po nowym whisper-runie indexowała wpis;
        ścieżka "TXT already exists → postprocess only" pomijała indexowanie,
        co powodowało pętlę pending dla tych samych plików (find_pending nie
        widział fingerprintu, więc whisper był uruchamiany ponownie).
        """
        version_info = {
            "version": version,
            "transcribed_at": self.vault_index.current_iso_timestamp(),
            "hostname": get_hostname(),
            "model": self.config.WHISPER_MODEL,
            "language": self.config.WHISPER_LANGUAGE,
            "markdown_path": md_path.name,
        }
        if existing_entry:
            self.vault_index.add_version(fingerprint, version_info)
        else:
            try:
                audio_size = audio_file.stat().st_size
            except OSError:
                audio_size = 0
            self.vault_index.add(
                fingerprint,
                IndexEntry(
                    fingerprint=fingerprint,
                    source_filename=audio_file.name,
                    source_volume=audio_file.parent.name,
                    markdown_path=md_path.name,
                    source_size=audio_size,
                    versions=[version_info],
                ),
            )

    def process_recorder(self) -> None:
        """Main workflow: detect recorder, find new files, transcribe.

        This is the main entry point called when recorder activity is detected.
        It orchestrates the entire transcription workflow.
        """
        # In-process guard first: the periodic checker and a user-triggered
        # force_retranscribe run on different threads of this same process.
        if not self._workflow_lock.acquire(blocking=False):
            logger.debug(
                "⛔️ Skipping process_recorder — another workflow is already "
                "running in this process"
            )
            # Keep current state to avoid UI flicker while another run is active.
            return

        # Cross-process guard (e.g. a separate `make run` daemon): advisory
        # flock the kernel releases automatically if the holder dies.
        lock = ProcessLock(self.config.PROCESS_LOCK_FILE)
        if not lock.acquire():
            logger.debug(
                "⛔️ Skipping process_recorder because another process holds lock %s",
                self.config.PROCESS_LOCK_FILE,
            )
            self._workflow_lock.release()
            # Keep current state to avoid UI flicker while another run is active.
            return

        try:
            logger.info("=" * 60)
            logger.info("🔍 Checking for recorder...")
            self._update_state(AppStatus.SCANNING)

            # Find all matching recorders (auto/specific/manual aware)
            recorders = self.find_recorders()
            if not recorders:
                # No physical recorder — still check local staging dir for
                # previously staged files that were never successfully transcribed.
                staged_pending = self.find_pending_audio_files(
                    self.config.LOCAL_RECORDINGS_DIR
                )
                if staged_pending:
                    logger.warning(
                        "📂 LOCAL_RECORDINGS_DIR scan: %d file(s) pending. "
                        "Note: this is a manual drop area, not a live recorder source. "
                        "Files left here from earlier sessions (or moved manually) "
                        "will be transcribed.",
                        len(staged_pending),
                    )
                    processed_s = 0
                    processed_f = 0
                    for staged_file, _fingerprint in staged_pending:
                        logger.info(f"Processing: {staged_file.name}")
                        if self.transcribe_file(staged_file):
                            processed_s += 1
                        else:
                            processed_f += 1
                        time.sleep(1)
                    logger.info(
                        "✓ Staged batch: %d/%d succeeded",
                        processed_s,
                        processed_s + processed_f,
                    )
                else:
                    logger.info("❌ Recorder not found")
                self.recorder_monitoring = False
                self.recorder_was_notified = False
                self._update_state(
                    AppStatus.IDLE,
                    recorder_name=None,
                    pending_count=None,
                )
                return

            logger.info(f"✓ Recorder(s) detected: {[r.name for r in recorders]}")

            # Recorder volume may have unmounted between find_recorders() and now
            # (LS-P1 auto-sleep, USB drop, etc). Drop any that disappeared.
            live_recorders = [r for r in recorders if r.exists()]
            if not live_recorders:
                logger.warning(
                    "⚠️  Recorder(s) disappeared before scan could start "
                    "(volume unmounted?): %s",
                    [r.name for r in recorders],
                )
                self.recorder_monitoring = False
                self.recorder_was_notified = False
                self._update_state(
                    AppStatus.IDLE,
                    recorder_name=None,
                    pending_count=None,
                )
                return
            recorders = live_recorders

            self.recorder_monitoring = True
            recorder_names = ", ".join(r.name for r in recorders)

            pending_files: List[Tuple[Path, str]] = []
            for recorder in recorders:
                pending_files.extend(self.find_pending_audio_files(recorder))
            pending_count = len(pending_files)

            if pending_count > 0:
                self._update_state(
                    AppStatus.RECORDER_PENDING,
                    recorder_name=recorder_names,
                    pending_count=pending_count,
                )
            else:
                self._update_state(
                    AppStatus.RECORDER_IDLE,
                    recorder_name=recorder_names,
                    pending_count=0,
                )

            # Keep last_sync diagnostics, but process queue is based on fingerprint
            # pending list so older unindexed recordings are never missed.
            last_sync = self.get_last_sync_time()
            logger.info("📅 Last sync timestamp: %s", last_sync)
            logger.info(
                "📁 Pending files by fingerprint: %s on %s",
                pending_count,
                recorder_names,
            )

            # Recorder-detected notification removed: the menu-bar status item
            # already shows connection/pending state (no redundant system push).

            processed_success = 0
            processed_failed = 0

            # Process each pending file (source of truth: missing fingerprint).
            if pending_files:
                for recorder_file, fingerprint in pending_files:
                    if not recorder_file.exists():
                        logger.warning(
                            "🪪 Source file disappeared "
                            "(volume unmounted?), skipping: %s",
                            recorder_file.name,
                        )
                        processed_failed += 1
                        continue
                    logger.info(f"Processing: {recorder_file.name}")

                    existing_markdown = self._find_existing_markdown_for_audio(
                        recorder_file
                    )
                    if self.vault_index.lookup(fingerprint):
                        logger.info(
                            "↪️ Skipping already transcribed file (fingerprint): %s",
                            recorder_file.name,
                        )
                        processed_success += 1
                        continue
                    if existing_markdown:
                        logger.info(
                            "↪️ Skipping already transcribed file: %s -> %s",
                            recorder_file.name,
                            existing_markdown.name,
                        )
                        self._cache_fingerprint_for_existing_markdown(
                            recorder_file,
                            existing_markdown,
                            fingerprint,
                        )
                        processed_success += 1
                        continue

                    # Stage file to local directory
                    staged_file = self._stage_audio_file(recorder_file)
                    if staged_file is None:
                        logger.warning(
                            f"⚠️  Failed to stage {recorder_file.name}, "
                            "skipping transcription"
                        )
                        processed_failed += 1
                        continue

                    # Transcribe using staged file
                    if self.transcribe_file(staged_file):
                        processed_success += 1
                    else:
                        processed_failed += 1

                    # Small delay between files
                    time.sleep(1)

                total_processed = processed_success + processed_failed
                logger.info(
                    f"✓ Transcription batch complete: "
                    f"{processed_success}/{total_processed} succeeded, "
                    f"{processed_failed}/{total_processed} failed"
                )

                # Completion notification removed: menu-bar status reflects this.
            else:
                logger.info("ℹ️  No pending files to transcribe")

            # Only advance sync time if ALL files were successfully processed
            # This prevents losing files that failed due to unmounting or other errors
            if processed_failed == 0 and processed_success > 0:
                self.save_sync_time()
                logger.info("✓ Sync complete (state updated)")
            elif processed_failed > 0:
                logger.warning(
                    f"⚠️  Batch had {processed_failed} failure(s). "
                    "Not updating last_sync to avoid losing unprocessed files. "
                    "Failed files will be retried on next sync."
                )
            else:
                logger.info(
                    "ℹ️  Skipping sync update (no files processed). "
                    "State remains at previous value."
                )
            logger.info("=" * 60)

            # Keep recorder_monitoring True if any recorder still connected
            # This prevents notification spam on periodic checks
            if not self.find_recorders():
                self.recorder_monitoring = False
                self.recorder_was_notified = False

            if self.recorder_monitoring:
                if pending_count > 0:
                    self._update_state(
                        AppStatus.RECORDER_PENDING,
                        recorder_name=recorder_names,
                        pending_count=pending_count,
                    )
                else:
                    self._update_state(
                        AppStatus.RECORDER_IDLE,
                        recorder_name=recorder_names,
                        pending_count=0,
                    )
            else:
                self._update_state(
                    AppStatus.IDLE, recorder_name=None, pending_count=None
                )
        finally:
            # Retention runs at the very end of a workflow, never during: the
            # staged copy is the only original while a recording is still
            # being processed. It lives in `finally` so it also runs on the
            # paths that never see a recorder — a user importing audio or
            # syncing Voice Memos accumulates staged files just the same, and
            # every early return above would otherwise skip the sweep.
            try:
                self.prune_staging_dir()
            except Exception as exc:  # noqa: BLE001 - must never block a batch
                logger.debug("Staging retention skipped: %s", exc)
            lock.release()
            self._workflow_lock.release()
