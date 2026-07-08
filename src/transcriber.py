"""Transcription engine for Malinche."""

import fcntl
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, Iterator, List, Optional, Tuple

from src.config import config as default_config
from src.config.config import Config
from src.logger import logger
from src.summarizer import (
    APIBillingError,
    BaseSummarizer,
    _is_permanent_api_error,
    get_summarizer,
)
from src.markdown_generator import MarkdownGenerator
from src.app_status import AppStatus
from src.state_manager import get_last_sync_time, save_sync_time
from src.tag_index import TagIndex
from src.tagger import BaseTagger, get_tagger
from src.vocabulary import VocabularyIndex
from src.fingerprint import compute_fingerprint
from src.hostinfo import get_hostname
from src.vault_index import IndexEntry, VaultIndex
from src.config.settings import UserSettings
from src.markdown_frontmatter import read_frontmatter
from src.volume_utils import find_matching_volumes

# whisper-cli with -pp prints "whisper_print_progress_callback: progress =  NN%".
_PROGRESS_RE = re.compile(r"progress\s*=\s*(\d+)\s*%")


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
        self._coreml_disabled_in_session: bool = False
        self._load_persisted_coreml_disabled()
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

            # Copy file with metadata preservation
            logger.debug(f"📋 Staging file: {audio_file.name}")
            shutil.copy2(audio_file, staged_path)
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
        use_coreml: bool = True,
        source_audio: Optional[Path] = None,
    ) -> subprocess.CompletedProcess:
        """Run whisper.cpp transcription.

        Args:
            audio_file: Original recording; its stem names the output TXT.
            use_coreml: Whether to allow Core ML acceleration (disable for fallback)
            source_audio: Actual audio fed to whisper-cli. Defaults to
                ``audio_file``; callers pass a converted 16 kHz WAV here so
                whisper always receives a format it can decode (see
                ``_convert_to_wav``).

        Returns:
            CompletedProcess from subprocess.run
        """
        if use_coreml and self._coreml_disabled_in_session:
            use_coreml = False

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

        # Set environment for Core ML / Metal control
        env = None
        if not use_coreml:
            # Explicitly disable Core ML / Metal backends to force pure CPU mode.
            # Using both WHISPER_COREML and GGML_METAL_DISABLE increases
            # compatibility across whisper.cpp / ggml versions.
            base_env = dict(os.environ)
            base_env["WHISPER_COREML"] = "0"
            base_env["GGML_METAL_DISABLE"] = "1"
            env = base_env
            logger.debug(
                "Core ML / Metal disabled for this attempt "
                "(WHISPER_COREML=0, GGML_METAL_DISABLE=1)"
            )

        logger.debug(
            f"Running whisper.cpp: model={self.config.WHISPER_MODEL}, "
            f"language={self.config.WHISPER_LANGUAGE}, "
            f"coreml={'enabled' if use_coreml else 'disabled'}, "
            f"threads={threads}, "
            f"timeout={self.config.TRANSCRIPTION_TIMEOUT}s"
        )

        return self._run_whisper_streaming(
            whisper_cmd, env=env, use_coreml=use_coreml, audio_file=audio_file
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

    def _run_whisper_streaming(
        self,
        cmd: List[str],
        *,
        env: Optional[dict],
        use_coreml: bool,
        audio_file: Path,
    ) -> subprocess.CompletedProcess:
        """Run whisper-cli with live stderr streaming.

        Replaces a blocking ``subprocess.run(capture_output=True)`` to fix two
        bugs at once:
          1. **Early Core ML/Metal abort.** whisper.cpp prints the Metal error
             at backend init; the old post-hoc stderr check only saw it after the
             whole run finished, wasting ~10 min before the CPU fallback. We now
             detect the marker live and kill the process within seconds.
          2. **Progress heartbeat.** With ``-pp`` whisper emits ``progress = NN%``
             to stderr; we log it so a long run is visibly alive.

        stdout → DEVNULL (whisper writes the TXT via ``-otxt``); this also avoids
        a pipe-buffer deadlock while we block on stderr. Returns a
        :class:`subprocess.CompletedProcess` (stdout always ``""``) so the caller
        is unchanged, and raises :class:`subprocess.TimeoutExpired` on the
        deadline to preserve the old contract.

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
            stdout=subprocess.DEVNULL,
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
        coreml_failed = False

        stderr_fd = proc.stderr.fileno()
        os.set_blocking(stderr_fd, False)
        decoder = codecs.getincrementaldecoder("utf-8")("replace")
        pending = ""  # text accumulated until a newline arrives

        def handle_line(line: str) -> bool:
            """Marker + progress logic for one stderr line. True = stop."""
            nonlocal coreml_failed, last_logged_pct, last_heartbeat
            if use_coreml and any(m in line for m in self._COREML_FAIL_MARKERS):
                coreml_failed = True
                logger.warning(
                    "⚡ Core ML/Metal error detected after %.0fs — "
                    "aborting GPU attempt, will retry on CPU",
                    time.time() - started,
                )
                proc.kill()
                return True
            match = _PROGRESS_RE.search(line)
            if match:
                pct = int(match.group(1))
                now = time.time()
                if pct >= last_logged_pct + 10 or now - last_heartbeat >= 20:
                    logger.info(
                        "⏳ Transkrypcja %d%% — %s",
                        pct,
                        audio_file.name,
                    )
                    last_logged_pct = pct
                    last_heartbeat = now
            return False

        def read_chunk() -> Optional[str]:
            """One non-blocking read. Text (possibly ''), or None on EOF."""
            try:
                chunk = os.read(stderr_fd, 65536)
            except BlockingIOError:
                return ""
            except OSError:  # pragma: no cover - defensive (closed fd)
                return None
            if not chunk:
                return None
            return decoder.decode(chunk)

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
                    process_remaining()
                    break

                remaining = deadline - time.time()
                if remaining <= 0:
                    proc.kill()
                    raise subprocess.TimeoutExpired(
                        cmd, self.config.TRANSCRIPTION_TIMEOUT
                    )

                ready, _, _ = select.select([stderr_fd], [], [], min(1.0, remaining))
                if not ready:
                    continue

                text = read_chunk()
                if text is None:
                    # EOF: the write end closed — flush any final partial line.
                    process_remaining()
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
        finally:
            try:
                if proc.stderr is not None:
                    proc.stderr.close()
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
        if coreml_failed and returncode == 0:
            # Ensure the caller treats an early-aborted GPU run as a failure
            # so the CPU fallback fires.
            returncode = -1
        return subprocess.CompletedProcess(
            args=cmd, returncode=returncode, stdout="", stderr="".join(stderr_chunks)
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

    def _coreml_flag_path(self) -> Path:
        """Sidecar file recording that Core ML/Metal failed on this machine."""
        return self.config.STATE_FILE.parent / "coreml_status.json"

    def _coreml_signature(self) -> str:
        """Identity for the persisted verdict: re-probe if whisper or model changes."""
        try:
            size = self.config.WHISPER_CPP_PATH.stat().st_size
        except OSError:
            size = 0
        return f"{size}:{self.config.WHISPER_MODEL}"

    def _load_persisted_coreml_disabled(self) -> None:
        """Honour a previously recorded Metal failure so we don't waste a full
        GPU attempt rediscovering it on every launch."""
        try:
            data = json.loads(self._coreml_flag_path().read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if data.get("disabled") and data.get("signature") == self._coreml_signature():
            self._coreml_disabled_in_session = True
            logger.info(
                "Core ML disabled (persisted: Metal failed previously on this "
                "machine for the current whisper/model)"
            )

    def _persist_coreml_disabled(self) -> None:
        """Record the Metal failure so future launches skip the GPU attempt."""
        try:
            self._coreml_flag_path().parent.mkdir(parents=True, exist_ok=True)
            self._coreml_flag_path().write_text(
                json.dumps({"disabled": True, "signature": self._coreml_signature()}),
                encoding="utf-8",
            )
        except OSError as exc:  # pragma: no cover - defensive
            logger.debug("Could not persist Core ML status: %s", exc)

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

    # Markers in whisper.cpp stderr that mean the Core ML / Metal backend
    # failed and we should fall back to pure CPU. Shared by the live stream
    # detector (early abort) and the post-hoc check.
    _COREML_FAIL_MARKERS = (
        "Core ML",
        "ggml_metal",
        "MTLLibrar",
        "tensor API disabled",
    )

    def _should_retry_without_coreml(
        self, stderr: Optional[str], use_coreml_attempted: bool
    ) -> bool:
        """Determine if whisper run should be retried without Core ML acceleration.

        Args:
            stderr: stderr output from whisper.cpp invocation.
            use_coreml_attempted: True if the failed run tried Core ML.

        Returns:
            True when stderr indicates Metal/Core ML failures and CPU retry is warranted.
        """
        if not use_coreml_attempted or not stderr:
            return False

        return any(marker in stderr for marker in self._COREML_FAIL_MARKERS)

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

    def _run_macwhisper(self, audio_file: Path) -> Optional[Path]:
        """Run whisper.cpp transcription and return path to TXT file.

        Args:
            audio_file: Path to the audio file to transcribe

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

            # Try with Core ML acceleration first (unless a prior/persisted
            # Metal failure already took it off the table for this session).
            if self._coreml_disabled_in_session:
                logger.info("🔄 Starting transcription (CPU — Core ML disabled)")
            else:
                logger.info("🔄 Attempting transcription with Core ML acceleration")
            result = self._run_whisper_transcription(
                audio_file, use_coreml=True, source_audio=wav_for_whisper
            )

            logger.debug(
                f"Transcription attempt completed - "
                f"returncode: {result.returncode}, "
                f"stderr length: {len(result.stderr) if result.stderr else 0}"
            )

            # If Core ML failed, retry without it
            if self._should_retry_without_coreml(
                result.stderr, use_coreml_attempted=True
            ):
                logger.warning(
                    f"⚠️  Core ML/Metal failed, falling back to CPU for {audio_file.name}"
                )
                if result.stderr:
                    logger.debug(f"  Error details: {result.stderr[:500]}")

                if not self._coreml_disabled_in_session:
                    self._coreml_disabled_in_session = True
                    self._persist_coreml_disabled()
                    logger.info(
                        "Core ML disabled for this session and future launches "
                        "(Metal failed on this machine)"
                    )

                logger.info("🔄 Retrying transcription with CPU only")
                result = self._run_whisper_transcription(
                    audio_file, use_coreml=False, source_audio=wav_for_whisper
                )
                logger.debug(f"CPU retry completed - returncode: {result.returncode}")

            # Check for errors
            if result.returncode != 0:
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
    ) -> Optional[Path]:
        """Post-process transcript: generate summary and create markdown.

        Args:
            audio_file: Original audio file path
            transcript_path: Path to temporary TXT transcript file

        Returns:
            True if post-processing succeeded, False otherwise
        """
        try:
            # Read transcript
            logger.debug(f"Reading transcript from: {transcript_path}")
            with open(transcript_path, "r", encoding="utf-8") as f:
                transcript_text = f.read()

            # Pusty transcript = legalny scenariusz (cisza, muzyka bez wokalu).
            # Generujemy markdown-placeholder z notatką, żeby plik został
            # zaindeksowany i nie wracał w pętlę retry.
            empty_transcript = not transcript_text.strip()
            if empty_transcript:
                logger.info(
                    "Pusty transkrypt dla %s — generuję markdown-placeholder",
                    audio_file.name,
                )
                transcript_text = "(Brak rozpoznawalnej mowy w nagraniu)"

            # Generate summary (if summarizer available and AI not disabled).
            # Pomijamy AI dla pustego transcriptu (nic do podsumowania, oszczędza koszty).
            summary = None
            if empty_transcript:
                summary = {
                    "title": audio_file.stem.replace("_", " ").title(),
                    "summary": "(Brak rozpoznawalnej mowy w nagraniu)",
                }
            elif self.summarizer and self._ai_disabled_reason is None:
                try:
                    logger.info("📝 Generating summary...")
                    summary = self.summarizer.generate(
                        transcript_text,
                        known_terms_block=self.vocabulary.known_terms_block(),
                    )
                    logger.info(f"✓ Summary generated: {summary.get('title', 'N/A')}")
                except APIBillingError as exc:
                    self._disable_ai(_is_permanent_api_error(exc) or "billing", exc)
                    summary = None
                except Exception as e:
                    logger.error(f"Summary generation failed: {e}", exc_info=True)
                    logger.warning("Continuing without summary")
                    summary = None

            # Fallback summary if summarizer unavailable
            if not summary:
                logger.debug("Using fallback summary")
                fallback_title = self._extract_fallback_title(transcript_text)
                if not fallback_title:
                    fallback_title = audio_file.stem.replace("_", " ").title()
                summary = {
                    "title": fallback_title,
                    "summary": """## Podsumowanie

Brak podsumowania AI. Możliwe przyczyny:
- klucz Claude API (ANTHROPIC_API_KEY) nie jest skonfigurowany
- konto Anthropic nie ma kredytów (https://console.anthropic.com/settings/billing)
- przejściowy błąd sieci

## Lista działań (To-do)

- Przejrzeć transkrypcję ręcznie
- Wyciągnąć kluczowe wnioski ze spotkania""",
                }

            # Extract audio metadata
            logger.debug("Extracting audio metadata...")
            metadata = self.markdown_generator.extract_audio_metadata(audio_file)

            # Generate tags
            tags = ["transcription"]
            if empty_transcript:
                tags.append("transcript-empty")
            if (
                not empty_transcript
                and self.config.ENABLE_LLM_TAGGING
                and self.tagger
                and self._ai_disabled_reason is None
            ):
                try:
                    existing_tags = self.tag_index.existing_tags()
                    generated_tags = self.tagger.generate_tags(
                        transcript=transcript_text,
                        summary_markdown=summary.get("summary", ""),
                        existing_tags=existing_tags,
                    )
                    for tag in generated_tags:
                        if tag not in tags:
                            tags.append(tag)
                except APIBillingError as exc:
                    self._disable_ai(_is_permanent_api_error(exc) or "billing", exc)
                except Exception as error:  # noqa: BLE001
                    logger.error(
                        "Tag generation failed for %s: %s",
                        audio_file.name,
                        error,
                        exc_info=True,
                    )

            # Create markdown document
            logger.info("📄 Creating markdown document...")
            md_path = self.markdown_generator.create_markdown_document(
                transcript=transcript_text,
                summary=summary,
                metadata=metadata,
                output_dir=self.config.TRANSCRIBE_DIR,
                tags=tags,
                extra_frontmatter={
                    "fingerprint": fingerprint,
                    "source_volume": audio_file.parent.name,
                    "version": version,
                    "transcribed_on": get_hostname(),
                    "model": self.config.WHISPER_MODEL,
                    "language": self.config.WHISPER_LANGUAGE,
                    "previous_version": previous_version or "",
                },
                output_filename=output_filename,
            )

            logger.info(f"✓ Markdown document created: {md_path.name}")

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

        if not transcribe_dir.exists():
            return result

        try:
            md_files = list(transcribe_dir.glob("*.md"))
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
                self.vault_index.add(
                    fingerprint,
                    IndexEntry(
                        fingerprint=fingerprint,
                        source_filename=source,
                        source_volume=fm.get("source_volume", ""),
                        markdown_path=md_path.name,
                        versions=[
                            {
                                "version": version,
                                "transcribed_at": fm.get("recording_date", ""),
                                "hostname": fm.get("transcribed_on", ""),
                                "model": fm.get("model", ""),
                                "language": fm.get("language", ""),
                                "markdown_path": md_path.name,
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
        for fp in entries_snapshot.keys():
            if fp in md_fingerprints:
                continue  # mamy MD z tym fingerprintem — wpis jest legalny
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
                "Reconciliation: indexed=%d, orphan_cleaned=%d, txt_cleaned=%d, txt_recovered=%d",
                result["indexed"],
                result["orphan_cleaned"],
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

    def transcribe_file(self, audio_file: Path) -> bool:
        """Transcribe a single audio file using whisper.cpp.

        Automatically falls back to CPU-only if Core ML fails.
        Post-processes transcript to create markdown document with summary.

        Args:
            audio_file: Path to the audio file to transcribe

        Returns:
            True if transcription succeeded, False otherwise
        """
        # If markdown already exists for this audio (based on `source` field),
        # treat it as successfully transcribed and skip any further work.
        fingerprint = compute_fingerprint(audio_file)
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
                logger.warning(
                    "⚠️  TXT exists but post-processing failed: %s",
                    audio_file.name,
                )
            return success

        # Run whisper transcription. The sidecar written first claims the
        # upcoming TXT for this fingerprint, so a crash between whisper and
        # postprocess stays recoverable (adoption above) without stem-only
        # guessing.
        self._write_transcript_owner(transcript_path, audio_file, fingerprint)
        transcript_path = self._run_macwhisper(audio_file)

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
        )
        success = md_path is not None

        if success:
            logger.info(f"✓ Complete: {audio_file.name}")
        else:
            logger.warning(
                f"⚠️  Transcription complete but post-processing failed: {audio_file.name}"
            )

        if success and md_path is not None:
            self._index_completed_transcription(
                audio_file=audio_file,
                fingerprint=fingerprint,
                md_path=md_path,
                existing_entry=existing_entry,
                version=version,
            )

            # Connection synthesis is opportunistic and must NEVER disturb
            # transcription — enqueue (a cheap in-memory counter bump, no API,
            # no IO) and swallow anything that goes wrong.
            try:
                from src.connections import enqueue_connection_analysis

                enqueue_connection_analysis(self)
            except Exception as exc:  # noqa: BLE001
                logger.debug("connection enqueue skipped: %s", exc)

            # Keep the local recall index fresh at transcription time. Opt-in
            # (ENABLE_RECALL_INDEX) and fully guarded — must never disturb
            # transcription.
            try:
                from src.config.config import get_config

                if getattr(get_config(), "ENABLE_RECALL_INDEX", False):
                    from src.connections.recall.seam import index_transcript_safe

                    index_transcript_safe(md_path)
            except Exception as exc:  # noqa: BLE001
                logger.debug("recall index skipped: %s", exc)

        return success

    def stage_audio_file(self, source: Path) -> Path:
        """Copy a manually chosen audio file into the local staging area.

        Fallback path for when automatic recorder/SD detection misses a file:
        the user points Malinche at an audio file anywhere on disk. The
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
        shutil.copy2(source, destination)
        logger.info("📥 Imported %s → %s", source.name, destination)
        return destination

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

    def import_audio_file(self, source: Path) -> bool:
        """Stage *source* and run the full single-file pipeline on the copy.

        Convenience wrapper around :meth:`stage_audio_file` +
        :meth:`transcribe_file` for the menu-bar "Import audio…" action.

        Returns:
            True if transcription succeeded, False otherwise.

        Raises:
            FileNotFoundError / ValueError: propagated from
            :meth:`stage_audio_file` for invalid input.
        """
        staged = self.stage_audio_file(source)
        return self.transcribe_file(staged)

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
            lock.release()
            self._workflow_lock.release()
