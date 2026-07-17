"""Core application orchestrator for Timshel."""

import time
import signal
import threading
from typing import Callable, Optional

from src.config import config
from src.logger import logger
from src.transcriber import Transcriber
from src.file_monitor import FileMonitor
from src.app_status import AppStatus, AppState


class TimshelTranscriber:
    """Main application orchestrator.

    Manages the lifecycle of the transcriber daemon, coordinating
    FSEvents monitoring, periodic checking, and graceful shutdown.

    Attributes:
        transcriber: Transcription engine instance
        monitor: File system monitor instance
        periodic_thread: Background thread for periodic checks
        running: Flag indicating if application is running
        state: Thread-safe application state
    """

    def __init__(self, setup_signals: bool = True):
        """Initialize the application.
        
        Args:
            setup_signals: Whether to setup signal handlers (only works in main thread)
        """
        self.transcriber: Optional[Transcriber] = None
        self.monitor: Optional[FileMonitor] = None
        self.periodic_thread: Optional[threading.Thread] = None
        self.running = False
        self.state = AppState()
        self._ai_billing_callback: Optional[Callable[[Exception], None]] = None
        self._on_unknown_volume: Optional[Callable] = None

        # Setup signal handlers for graceful shutdown (only in main thread)
        if setup_signals:
            signal.signal(signal.SIGINT, self._signal_handler)
            signal.signal(signal.SIGTERM, self._signal_handler)

    def set_ai_billing_callback(
        self, callback: Callable[[Exception], None]
    ) -> None:
        """Register a callback forwarded to the underlying Transcriber."""
        self._ai_billing_callback = callback
        if self.transcriber is not None:
            self.transcriber.set_ai_billing_callback(callback)

    def set_unknown_volume_callback(self, callback: Callable) -> None:
        """Register dialog handler for unknown volumes (Tak/Nie/Raz).

        Forwarded to ``FileMonitor`` przy następnym ``start()``.
        Można podać przed lub po ``start()`` — w drugim wypadku monitor
        sięgnie po nowy callback przy kolejnym evencie.
        """
        self._on_unknown_volume = callback
        if self.monitor is not None:
            self.monitor.on_unknown_volume = callback

    def import_audio_file(self, source) -> bool:
        """Manually import an audio file into the pipeline (menu fallback).

        Forwards to the underlying :class:`Transcriber`. Raises if the daemon
        has not finished starting (no transcriber yet).
        """
        if self.transcriber is None:
            raise RuntimeError("Transcriber not started yet")
        return self.transcriber.import_audio_file(source)

    def import_text_file(self, source, status=None) -> bool:
        """Import an already-transcribed text file (txt/md/vtt) as a note.

        Forwards to the underlying :class:`Transcriber` (including the optional
        ``status`` dict that reports duplicate vs freshly-written). Raises if the
        daemon has not finished starting (no transcriber yet).
        """
        if self.transcriber is None:
            raise RuntimeError("Transcriber not started yet")
        return self.transcriber.import_text_file(source, status=status)

    def reload_ai_config(self) -> None:
        """Re-read AI config live after a settings change.

        Forwards to the underlying :class:`Transcriber` so a fixed API key /
        model takes effect immediately (no restart). The menu app calls this
        after Settings is saved. A no-op until the daemon has built its
        transcriber — a key saved that early is picked up by the start-time
        client build anyway, so this must not raise into the settings handler.
        """
        if self.transcriber is not None:
            self.transcriber.reload_ai_config()

    def reload_paths(self) -> None:
        """Re-point the vault index after an output-folder change.

        Forwards to the underlying :class:`Transcriber`. No-op until the daemon
        has built its transcriber — so it must never raise into the Settings
        handler.
        """
        if self.transcriber is not None:
            self.transcriber.reload_paths()

    @property
    def vault_index(self):
        """The inner transcriber's vault index (recent transcripts, lookups).

        Forwarded so callers (the menu app's Insights rail) don't reach through
        ``.transcriber.transcriber``. Raises ``AttributeError`` before the
        daemon has built its transcriber, which callers already guard.
        """
        if self.transcriber is None:
            raise AttributeError("vault_index unavailable before transcriber init")
        return self.transcriber.vault_index

    def _signal_handler(self, signum, frame):
        """Handle shutdown signals.

        Args:
            signum: Signal number
            frame: Current stack frame
        """
        signal_name = signal.Signals(signum).name
        logger.info(f"Received {signal_name}, shutting down...")
        self.stop()

    def _periodic_check(self):
        """Periodic check for recorder (fallback if FSEvents misses event).

        Runs in a background thread, checking every PERIODIC_CHECK_INTERVAL
        seconds for a connected recorder.
        """
        logger.info(
            f"✓ Periodic checker started "
            f"(interval: {config.PERIODIC_CHECK_INTERVAL}s)"
        )

        while self.running:
            try:
                time.sleep(config.PERIODIC_CHECK_INTERVAL)

                if not self.running:
                    break

                if self.transcriber:
                    logger.debug("Periodic check triggered processing")
                    # Fallback for unknown disks the FSEvents stream missed:
                    # prompt for any new volume, then process (newly trusted
                    # disks become visible to process_recorder right away).
                    if self.monitor is not None:
                        try:
                            self.monitor.scan_unknown_volumes()
                        except Exception as scan_error:  # noqa: BLE001
                            logger.error(
                                f"Error scanning unknown volumes: {scan_error}",
                                exc_info=True,
                            )
                    self.transcriber.process_recorder()

                    # Opportunistic connection-synthesis digest. Returns in
                    # microseconds unless a digest is actually due; transcription
                    # always runs first so it keeps priority on the tick.
                    try:
                        from src.connections import run_digest_if_due

                        run_digest_if_due(self.transcriber)
                    except Exception as digest_error:  # noqa: BLE001
                        logger.error(
                            "Error in digest run: %s", digest_error, exc_info=True
                        )

            except Exception as e:
                logger.error(f"Error in periodic check: {e}", exc_info=True)
                self.state.status = AppStatus.ERROR
                self.state.error_message = str(e)

        logger.info("✓ Periodic checker stopped")

    def start(self):
        """Start the transcriber daemon."""
        logger.info("=" * 60)
        logger.info("🚀 Timshel starting...")
        logger.info("=" * 60)

        # Log configuration
        logger.info(f"📂 Transcription directory: {config.TRANSCRIBE_DIR}")
        logger.info(f"📄 State file: {config.STATE_FILE}")
        logger.info(f"📋 Log file: {config.LOG_FILE}")

        # Log TRANSCRIBE_DIR source (from config, which was migrated from ENV if needed)
        logger.info(
            f"ℹ️  TRANSCRIBE_DIR: {config.TRANSCRIBE_DIR} "
            f"(set TIMSHEL_TRANSCRIBE_DIR env var and restart to change)"
        )
        
        # Ensure transcription directory exists
        try:
            config.ensure_directories()
            if config.TRANSCRIBE_DIR.exists():
                logger.info(f"✓ Transcription directory exists: {config.TRANSCRIBE_DIR}")
            else:
                logger.warning(
                    f"⚠️  Transcription directory does not exist and could not be created: "
                    f"{config.TRANSCRIBE_DIR}"
                )
        except Exception as e:
            logger.error(
                f"✗ Failed to create transcription directory: {e}",
                exc_info=True
            )
            logger.error(
                "Please ensure TIMSHEL_TRANSCRIBE_DIR points to a valid, "
                "accessible directory (same vault path on all computers to avoid duplicates)"
            )
            raise
        
        # Diagnostic check: warn if directory doesn't look like a synced vault
        transcribe_path_str = str(config.TRANSCRIBE_DIR)
        if "iCloud" not in transcribe_path_str and "Obsidian" not in transcribe_path_str:
            logger.warning(
                "⚠️  TRANSCRIBE_DIR does not appear to be in a synced location "
                "(iCloud/Obsidian). For multi-computer setups, ensure all instances "
                "point to the same synchronized vault directory to prevent duplicate transcriptions."
            )

        # Initialize transcriber
        try:
            # Create transcriber with injected config for better testability
            self.transcriber = Transcriber(config=config)
            # Inject state updater callback into transcriber
            self.transcriber.set_state_updater(self._update_state)
            if self._ai_billing_callback is not None:
                self.transcriber.set_ai_billing_callback(self._ai_billing_callback)
        except Exception as e:
            logger.error(f"Failed to initialize transcriber: {e}", exc_info=True)
            self.state.status = AppStatus.ERROR
            self.state.error_message = f"Błąd inicjalizacji: {e}"
            raise

        # Reconcile vault_index z markdownami na dysku — naprawia stan po
        # wcześniejszych runach, w których ścieżka "TXT-already-exists"
        # tworzyła markdown bez wpisu w vault_index (powodując pętlę pending).
        try:
            self.transcriber.reconcile_existing_markdowns()
        except Exception as error:  # noqa: BLE001
            logger.warning("Reconciliation failed at startup: %s", error)

        # Initialize file monitor
        self.monitor = FileMonitor(
            callback=self.transcriber.process_recorder,
            on_unknown_volume=self._on_unknown_volume,
        )

        # Start FSEvents monitor
        try:
            self.monitor.start()
        except Exception as e:
            logger.error(f"Failed to start file monitor: {e}")
            logger.warning("Continuing with periodic check only")
            self.state.status = AppStatus.ERROR
            self.state.error_message = f"Błąd monitora plików: {e}"

        # Start periodic checker thread
        self.running = True
        self.state.status = AppStatus.IDLE
        self.periodic_thread = threading.Thread(
            target=self._periodic_check,
            daemon=True,
            name="PeriodicChecker"
        )
        self.periodic_thread.start()

        logger.info("=" * 60)
        logger.info("✓ All monitors running")
        logger.info("⏳ Waiting for recorder connection...")
        logger.info("   (Press Ctrl+C to stop)")
        logger.info("=" * 60)

        # Keep main thread alive
        try:
            while self.running:
                time.sleep(1)
        except KeyboardInterrupt:
            # Already handled by signal handler, but catch here too
            pass

    def stop(self):
        """Stop the transcriber daemon."""
        if not self.running:
            return

        logger.info("⏹  Shutting down...")

        # Stop running flag
        self.running = False
        self.state.status = AppStatus.IDLE

        # Kill an in-flight whisper before anything else: its process group
        # would otherwise outlive us (timeout enforcement dies with this
        # process, flock is kernel-released on exit → orphan + double run).
        if self.transcriber:
            try:
                self.transcriber.stop()
            except Exception as e:  # noqa: BLE001 — shutdown must proceed
                logger.error(f"Error stopping transcriber: {e}")

        # Stop file monitor
        if self.monitor:
            try:
                self.monitor.stop()
            except Exception as e:
                logger.error(f"Error stopping monitor: {e}")

        # Wait for periodic thread to finish
        if self.periodic_thread and self.periodic_thread.is_alive():
            logger.debug("Waiting for periodic checker to stop...")
            self.periodic_thread.join(timeout=5.0)

        logger.info("✓ Shutdown complete")
        logger.info("=" * 60)

    def _update_state(
        self,
        status: AppStatus,
        current_file: Optional[str] = None,
        error_message: Optional[str] = None,
        recorder_name: Optional[str] = None,
        pending_count: Optional[int] = None,
    ) -> None:
        """Update application state (called by Transcriber).

        Args:
            status: New status
            current_file: Current file being processed (if any)
            error_message: Error message (if status is ERROR)
        """
        self.state.status = status
        self.state.current_file = current_file
        self.state.recorder_name = recorder_name
        self.state.pending_count = pending_count
        if error_message:
            self.state.error_message = error_message

