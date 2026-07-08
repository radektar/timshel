"""macOS menu bar application for Malinche."""

import sys
import threading
from pathlib import Path
from datetime import datetime
from typing import Optional, List

from src.bootstrap import ensure_ready

# Bootstrap must run before any config-dependent imports.
ensure_ready()

try:
    import rumps
    RUMPS_AVAILABLE = True
except ImportError:
    RUMPS_AVAILABLE = False

try:
    from PyObjCTools import AppHelper
    _APPHELPER_AVAILABLE = True
except ImportError:
    _APPHELPER_AVAILABLE = False

try:
    from AppKit import NSThread
    _NSTHREAD_AVAILABLE = True
except ImportError:
    _NSTHREAD_AVAILABLE = False


def _is_main_thread() -> bool:
    """True gdy obecny wątek to Cocoa main thread."""
    if _NSTHREAD_AVAILABLE:
        try:
            return bool(NSThread.isMainThread())
        except Exception:
            return False
    return False


def _run_on_main_thread(func):
    """Schedule *func* on the main thread; fall back to direct call in tests.

    Gdy już jesteśmy na main thread, wywołujemy synchronicznie — schedule
    przez ``AppHelper.callAfter`` w połączeniu z blokującym ``Event.wait``
    powodował deadlock (callback czekał na runloop, który stał na wait).
    """
    if _is_main_thread():
        func()
        return
    if _APPHELPER_AVAILABLE:
        AppHelper.callAfter(func)
    else:
        func()


# Device-independent NSEvent modifier bits (avoid importing AppKit for a pure check).
_MOD_SHIFT, _MOD_CONTROL, _MOD_OPTION, _MOD_COMMAND = 1 << 17, 1 << 18, 1 << 19, 1 << 20
_RECALL_KEYCODE_SPACE = 49


def _is_recall_chord(keycode, flags) -> bool:
    """True iff the event is exactly ⌃⌥Space (Control+Option+Space).

    Exclusive of Command/Shift so it never fires on supersets, and deliberately NOT
    plain ⌥Space — that is the macOS non-breaking-space key, so binding it would
    hijack a normal keystroke system-wide. Pure function → unit-testable.
    """
    if int(keycode) != _RECALL_KEYCODE_SPACE:
        return False
    active = int(flags) & (_MOD_SHIFT | _MOD_CONTROL | _MOD_OPTION | _MOD_COMMAND)
    return active == (_MOD_CONTROL | _MOD_OPTION)


from src.config import config
from src.config.settings import UserSettings
from src.file_monitor import (
    DECISION_BLOCKED,
    DECISION_NONE,
    DECISION_ONCE,
    DECISION_TRUSTED,
)
from src import volume_session
from src.logger import logger
from src.app_core import MalincheTranscriber
from src.app_status import AppStatus
from src.state_manager import reset_state
from src.transcriber import RetranscribeLockBusyError, send_notification
from src.setup.dependency_manager import DependencyManager
from src.setup.errors import NetworkError, DiskSpaceError, DownloadError
from src.setup import SetupWizard
from src.ui.dialogs import choose_date_dialog, show_about_dialog
from src.ui.constants import TEXTS
from src.ui.settings_window import show_settings_window
from src.ui.pro_activation import show_pro_status
from src.ui.download_window import DownloadWindow


class MalincheMenuApp(rumps.App):
    """macOS menu bar application wrapper for Malinche."""

    def __init__(self):
        """Initialize menu bar application."""
        if not RUMPS_AVAILABLE:
            raise ImportError(
                "rumps not available. Install with: pip install rumps"
            )

        super(MalincheMenuApp, self).__init__(
            "Malinche",
            title=None,
            icon=None,
            template=True,
            quit_button=None,
        )
        self._icon_paths = self._resolve_icon_paths()
        self._update_icon(AppStatus.IDLE)

        self.transcriber: Optional[MalincheTranscriber] = None
        self.daemon_thread: Optional[threading.Thread] = None
        self._running = False
        self._retranscription_in_progress = False
        self._retranscription_file: Optional[str] = None
        self._download_active = False
        self._download_manager = DependencyManager()
        self._download_window: Optional[DownloadWindow] = None

        # Status (header) + primary actions
        self.status_item = rumps.MenuItem("Status: Initializing…")
        self.menu.add(self.status_item)
        self.menu.add(rumps.separator)

        # Insights — open the "Konstelacja" window (the designed home where the
        # connections Malinche found are read). Entered from here, not by
        # hijacking the menu-bar click (that opens this native menu, Docker-style).
        # Trailing "…" per macOS HIG = the command needs more input in a
        # dialog/picker before it completes. So only "Import audio…" (file
        # picker) and "Settings…" (config window) keep it; everything else acts
        # immediately or opens a submenu and stays ellipsis-free.
        self.insights_item = rumps.MenuItem(
            "Insights",
            callback=self._open_insights,
        )
        self.menu.add(self.insights_item)
        self.menu.add(rumps.separator)

        self.open_logs_item = rumps.MenuItem(
            "Open logs",
            callback=self._open_logs,
        )
        self.menu.add(self.open_logs_item)

        # Manual import — fallback when auto-detection misses a disk/file.
        self.import_item = rumps.MenuItem(
            "Import audio…",
            callback=self._import_audio_clicked,
        )
        self.menu.add(self.import_item)

        # Synthesis — open the latest connection digest note in the vault.
        self.digest_item = rumps.MenuItem(
            "Open latest digest",
            callback=self._open_latest_digest,
        )
        self.menu.add(self.digest_item)
        self.gen_digest_item = rumps.MenuItem(
            "Generate digest now",
            callback=self._generate_digest_now,
        )
        self.menu.add(self.gen_digest_item)

        # Retranscribe submenu (lazy populated by refresh timer)
        self.retranscribe_menu = rumps.MenuItem("Retranscribe file")
        self.menu.add(self.retranscribe_menu)

        self.menu.add(rumps.separator)

        self.settings_item = rumps.MenuItem(
            "Settings…",
            callback=self._show_settings,
        )
        self.menu.add(self.settings_item)

        self.menu.add(rumps.separator)

        self.quit_item = rumps.MenuItem(
            "Quit Malinche",
            callback=self._quit_app,
        )
        self.menu.add(self.quit_item)

        # Docker-style: SF Symbol icons on each action (template images that
        # adapt to light/dark + selection). Best-effort — skipped on any OS
        # where system symbols aren't available.
        self._apply_menu_icons()

        # Menu-bar click opens the native NSMenu (system surface, like Docker /
        # Cursor). The designed "home" is the Insights window (dashboard_window),
        # reached from the "Insights…" item above — we no longer hijack the click
        # with an NSPopover. The old status-panel popover is retired entirely.
        from src.ui.dashboard_window import build_dashboard_window

        self._dashboard = build_dashboard_window(callbacks=self._dashboard_callbacks())
        self._refresh_insights_badge()

        # Global hotkey (⌃⌥Space) → recall ask-bar. Best-effort; never blocks launch.
        try:
            self._register_recall_hotkey()
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("recall hotkey unavailable: %s", exc)

        # Recall "just works": catch the index up to the vault in the background so a
        # fresh install is searchable without a manual backfill. Non-blocking, gated.
        try:
            if config.ENABLE_RECALL_INDEX:
                from src.connections.recall import seam

                seam.start_background_index()
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("recall background index unavailable: %s", exc)

        # Start status update timer
        rumps.Timer(self._update_status, 2).start()  # Update every 2 seconds
        
        # Start retranscribe menu refresh timer
        rumps.Timer(self._refresh_retranscribe_menu, 10).start()  # Update every 10 seconds
        
        # Check if wizard is needed (first run)
        self._dependencies_checked = False
        if SetupWizard.needs_setup():
            # Wizard will handle dependencies
            self._dependencies_checked = True
            rumps.Timer(self._run_wizard_if_needed, 0.5).start()
        else:
            # Normal start - check dependencies
            rumps.Timer(self._delayed_check_dependencies, 1).start()

    def _resolve_icon_paths(self) -> dict[AppStatus, Optional[str]]:
        """Build menu bar status icons by rendering SF Symbols to template PNGs.

        Replaces the old shipped-PNG set (which had missing assets and fell back
        to emoji). SF Symbols are guaranteed on macOS 12+, so every state now has
        a real, consistent glyph; the emoji fallback in ``_update_icon`` only
        triggers if symbol rendering is unavailable. See ``src/ui/style.py`` and
        ``Docs/UI-REDESIGN-L4-PLAN.md`` (phase 2).
        """
        import tempfile

        from src.ui import style

        resolved: dict[AppStatus, Optional[str]] = {
            status: None for status in AppStatus
        }
        if not getattr(style, "_APPKIT_AVAILABLE", False):
            return resolved

        # Parallel set of badged (gold-dot) icons for the "unseen insight" signal.
        dot_resolved: dict[AppStatus, Optional[str]] = {
            status: None for status in AppStatus
        }

        icon_dir = Path(tempfile.mkdtemp(prefix="malinche-menubar-icons-"))
        for status in AppStatus:
            try:
                name = style.symbol_name_for_status(status)
                png = style.render_symbol_png(
                    name, point=15.0, weight="regular", pixel_size=36
                )
                if png:
                    out = icon_dir / f"{status.value}.png"
                    out.write_bytes(png)
                    resolved[status] = str(out)
                dot_png = style.render_symbol_png(
                    name, point=15.0, weight="regular", pixel_size=36, dot=True
                )
                if dot_png:
                    dot_out = icon_dir / f"{status.value}-dot.png"
                    dot_out.write_bytes(dot_png)
                    dot_resolved[status] = str(dot_out)
            except Exception as exc:  # pragma: no cover - defensive
                logger.debug("Could not render menu-bar icon for %s: %s", status, exc)
        self._icon_paths_dot = dot_resolved
        return resolved

    def _update_icon(self, status: AppStatus) -> None:
        """Update menu bar icon based on app status.

        When a template image is available we always clear the title so macOS
        does not render both the icon and a stray emoji/name fallback next to
        each other in the status bar.
        """
        # Docker-style status dot on the header item, keyed by state.
        self._apply_status_icon(status)

        # Let an open Insights window show its loading state while we work.
        dash = getattr(self, "_dashboard", None)
        if dash is not None:
            try:
                dash.setTranscribing_(
                    status in (AppStatus.TRANSCRIBING, AppStatus.SCANNING)
                )
            except Exception:  # pragma: no cover - cosmetic, never fatal
                pass

        # When an unseen insight is waiting, show the badged (gold-dot) icon —
        # a non-template image, so the gold survives macOS's menu-bar tinting.
        if getattr(self, "_unseen_insights", 0) > 0:
            dot_path = getattr(self, "_icon_paths_dot", {}).get(status)
            if dot_path:
                self.title = None
                self.template = False
                self.icon = dot_path
                return

        icon_path = self._icon_paths.get(status)
        if icon_path:
            self.title = None
            self.template = True
            self.icon = icon_path
            return

        fallback_titles = {
            AppStatus.IDLE: "🎙️",
            AppStatus.SCANNING: "🔎",
            AppStatus.TRANSCRIBING: "⏳",
            AppStatus.DOWNLOADING: "⬇️",
            AppStatus.MIGRATING: "🔄",
            AppStatus.RECORDER_IDLE: "🟢",
            AppStatus.RECORDER_PENDING: "🟡",
            AppStatus.ERROR: "⚠️",
        }
        self.icon = None
        self.title = fallback_titles.get(status, "🎙️")

    def _run_wizard_if_needed(self, timer):
        """Uruchom wizard jeśli to pierwsze uruchomienie."""
        timer.stop()
        logger.info("Uruchamianie Setup Wizard...")
        wizard = SetupWizard()
        if wizard.run():
            # Wizard zakończony pomyślnie - start transcribera
            logger.info("Wizard finished — starting transcriber")
            self._start_daemon()
        else:
            # User cancelled wizard
            self.status_item.title = "Status: Configuration required"
            rumps.alert(
                title="Configuration incomplete",
                message=(
                    "Malinche requires configuration to operate.\n\n"
                    "Restart the app to finish configuring it."
                ),
                ok="OK",
            )

    def _delayed_check_dependencies(self, timer):
        """Sprawdź zależności po uruchomieniu aplikacji (z opóźnieniem)."""
        # Stop timer after first call
        timer.stop()

        if self._dependencies_checked:
            return

        self._dependencies_checked = True
        self._check_dependencies()
        # Onboarding banner po starcie (nieblokujący, jednorazowy per uruchomienie).
        self._maybe_run_volume_onboarding()

    def _maybe_run_volume_onboarding(self) -> None:
        """Pokaż banner migracji + (opcjonalnie) review podłączonych dysków.

        Wykonuje się gdy ``UserSettings.needs_volume_onboarding`` to True
        (typowo: świeża migracja z trybu ``auto`` → ``manual`` w v2.0.0-beta.2).
        """
        try:
            settings = UserSettings.load()
        except Exception as exc:  # noqa: BLE001
            logger.error(f"Could not load settings for onboarding: {exc}")
            return
        if not settings.needs_volume_onboarding:
            return

        choice = rumps.alert(
            title="🛡 Security mode updated",
            message=(
                "Every new disk connected to the computer must now be approved "
                "before Malinche transcribes from it. This prevents accidental "
                "scanning of disks like external music drives.\n\n"
                "Would you like to review the disks currently mounted and "
                "decide which ones are recorders?"
            ),
            ok="Review now",
            cancel="Later",
        )

        if choice != 1:
            # Odłożone — flaga zostaje, banner pokaże się przy następnym starcie.
            logger.info("Volume onboarding postponed by user")
            return

        # Reuse manualnej ścieżki — ta sama logika.
        self._review_mounted_volumes(settings)

    def _import_audio_clicked(self, _) -> None:
        """Menu: manually pick an audio file and run the full pipeline on it.

        Fallback for when automatic recorder/SD detection misses a file. The
        file picker runs on the main thread; the actual stage+transcribe runs
        in a background thread so the menu stays responsive.
        """
        if self.transcriber is None:
            rumps.alert(
                title="Not ready",
                message="Malinche is still starting up. Try again in a moment.",
                ok="OK",
            )
            return

        path = self._choose_audio_file()
        if not path:
            return

        threading.Thread(
            target=self._run_import,
            args=(Path(path),),
            daemon=True,
            name="ManualImport",
        ).start()

    def _choose_audio_file(self) -> Optional[str]:
        """Show an NSOpenPanel filtered to supported audio types.

        Returns the selected path, or None if cancelled / unavailable.
        """
        try:
            from AppKit import NSOpenPanel
        except ImportError:
            rumps.alert(
                title="Unavailable",
                message="The file picker is not available in this environment.",
                ok="OK",
            )
            return None

        result = {"path": None}

        def _panel() -> None:
            panel = NSOpenPanel.openPanel()
            panel.setCanChooseFiles_(True)
            panel.setCanChooseDirectories_(False)
            panel.setAllowsMultipleSelection_(False)
            panel.setMessage_("Choose an audio file to transcribe")
            allowed = [ext.lstrip(".") for ext in sorted(config.AUDIO_EXTENSIONS)]
            panel.setAllowedFileTypes_(allowed)
            # NSModalResponseOK == 1
            if panel.runModal() == 1:
                urls = panel.URLs()
                if urls and len(urls) > 0:
                    result["path"] = str(urls[0].path())

        _run_on_main_thread(_panel)
        return result["path"]

    def _run_import(self, audio_path: Path) -> None:
        """Stage + transcribe a manually imported file (background thread)."""
        name = audio_path.name
        try:
            send_notification("Malinche", "Importing", f"Transcribing {name}…")
        except Exception:  # noqa: BLE001
            pass

        try:
            ok = self.transcriber.import_audio_file(audio_path)
        except (FileNotFoundError, ValueError) as exc:
            logger.warning("Manual import rejected %s: %s", audio_path, exc)
            # Bind the message now: the ``exc`` name is cleared when the except
            # block exits, but ``_on_main`` may run later on the main thread.
            reason = str(exc)

            def _on_main() -> None:
                rumps.alert(title="Cannot import file", message=reason, ok="OK")

            _run_on_main_thread(_on_main)
            return
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "Manual import failed for %s: %s", audio_path, exc, exc_info=True
            )
            reason = str(exc)

            def _on_main() -> None:
                rumps.alert(title="Import failed", message=reason, ok="OK")

            _run_on_main_thread(_on_main)
            return

        if ok:
            logger.info("✓ Manual import complete: %s", name)
            try:
                send_notification("Malinche", "Done", f"Transcribed {name}")
            except Exception:  # noqa: BLE001
                pass
        else:
            def _on_main() -> None:
                rumps.alert(
                    title="Transcription failed",
                    message=f"Could not transcribe {name}. Check the logs.",
                    ok="OK",
                )

            _run_on_main_thread(_on_main)

    def _manage_volumes_clicked(self, _) -> None:
        """Menu item: manage trusted/blocked disk list."""
        try:
            settings = UserSettings.load()
        except Exception as exc:  # noqa: BLE001
            logger.error(f"Could not load settings: {exc}")
            rumps.alert(title="Error", message=str(exc), ok="OK")
            return

        trusted = [tv for tv in settings.trusted_volumes if tv.decision == "trusted"]
        blocked = [tv for tv in settings.trusted_volumes if tv.decision == "blocked"]

        lines = []
        if trusted:
            lines.append("✅ Trusted (transcribed):")
            for tv in trusted:
                lines.append(f"   • {tv.name}")
        if blocked:
            if lines:
                lines.append("")
            lines.append("🚫 Blocked (skipped):")
            for tv in blocked:
                lines.append(f"   • {tv.name}")
        if not lines:
            lines.append("No remembered disks.")
            lines.append("Connect a recorder or use 'Review /Volumes' below.")

        message = "\n".join(lines) + "\n\nWhat would you like to do?"

        choice = rumps.alert(
            title="🛡 Manage disks",
            message=message,
            ok="Review /Volumes",
            cancel="Close",
            other="Clear decisions",
        )

        if choice == 1:  # Review /Volumes
            self._review_mounted_volumes(settings)
        elif choice == -1:  # Clear decisions (other button)
            confirm = rumps.alert(
                title="Clear decisions?",
                message=(
                    "All trusted and blocked disks will be removed from the list. "
                    "The next time a disk is connected, you'll be asked again."
                ),
                ok="Clear",
                cancel="Cancel",
            )
            if confirm == 1:
                settings.trusted_volumes = []
                settings.save()
                rumps.alert(title="Cleared", message="The decision list is empty.", ok="OK")

    def _review_mounted_volumes(self, settings: UserSettings) -> None:
        """Iteruj po podłączonych /Volumes i pytaj o nieznane dyski.

        Współdzielona ścieżka między onboardingiem a manualnym przeglądem.
        """
        from pathlib import Path
        from src.config.defaults import defaults as _defaults
        from src.volume_identity import get_volume_uuid

        volumes_root = Path("/Volumes")
        if not volumes_root.exists():
            rumps.alert(title="No /Volumes", message="The /Volumes directory does not exist.", ok="OK")
            return

        try:
            candidates = sorted(volumes_root.iterdir(), key=lambda p: p.name)
        except OSError as error:
            logger.error(f"Manage volumes: could not list /Volumes: {error}")
            rumps.alert(title="Error", message=str(error), ok="OK")
            return

        skipped_existing = 0
        skipped_system = 0
        reviewed = 0
        for candidate in candidates:
            if not candidate.is_dir():
                continue
            if candidate.name in _defaults.SYSTEM_VOLUMES:
                skipped_system += 1
                continue
            uuid = get_volume_uuid(candidate)
            if settings.find_trusted_volume(uuid) is not None:
                skipped_existing += 1
                continue
            decision = self._prompt_unknown_volume(candidate, uuid)
            if decision == DECISION_TRUSTED:
                settings.add_trusted_volume(uuid, candidate.name, "trusted")
                reviewed += 1
            elif decision == DECISION_BLOCKED:
                settings.add_trusted_volume(uuid, candidate.name, "blocked")
                reviewed += 1

        settings.needs_volume_onboarding = False
        settings.save()

        summary_lines = ["Reviewed disks in /Volumes:"]
        summary_lines.append(f"• New decisions recorded: {reviewed}")
        if skipped_existing:
            summary_lines.append(f"• Already known (skipped): {skipped_existing}")
        if skipped_system:
            summary_lines.append(f"• System volumes (skipped): {skipped_system}")
        rumps.alert(title="Done", message="\n".join(summary_lines), ok="OK")

    def _check_dependencies(self):
        """Sprawdź czy wszystkie zależności są zainstalowane."""
        try:
            status = self._download_manager.status()
            if status.ready:
                # Płytkie sprawdzenie OK — teraz głęboka weryfikacja (checksum + runtime).
                health = self._download_manager.health_check()
                if health.ok:
                    logger.info("✓ All dependencies installed and verified")
                    return True

                logger.warning(
                    "Health check NIEUDANY: %s (repair=%s)",
                    health.reason,
                    health.needs_whisper_repair,
                )
                if health.needs_whisper_repair:
                    self._prompt_whisper_repair(health.reason or "")
                else:
                    self.status_item.title = "Status: Dependency repair required"
                return False

            # Dependencies missing — prompt user
            logger.warning("Dependencies missing — download required")
            model = config.WHISPER_MODEL
            size_mb = status.total_missing_size / 1_000_000
            response = rumps.alert(
                title="📥 Download dependencies",
                message=(
                    f"Selected model: {model}\n"
                    f"Missing data: ~{size_mb:.0f} MB.\n\n"
                    "Download now?\n\n"
                    "Downloads run in the background — the app stays responsive."
                ),
                ok="Download now",
                cancel="Skip",
            )

            if response == 1:  # OK clicked
                self._download_dependencies()
            else:
                logger.info("User skipped dependency download")
                self.status_item.title = "Status: Dependencies need to be downloaded"

            return False

        except (NetworkError, DiskSpaceError, DownloadError) as e:
            logger.error(f"Error while checking dependencies: {e}")
            rumps.alert(
                title="⚠️ Error",
                message=f"Could not download dependencies:\n\n{str(e)}",
                ok="OK",
            )
            self.status_item.title = "Status: Download error"
            return False
        except Exception as e:
            logger.error(f"Unexpected error: {e}", exc_info=True)
            return False
    
    def _download_dependencies(self):
        """Download all missing dependencies asynchronously."""
        if self._download_active:
            return
        self._download_active = True
        self._update_icon(AppStatus.DOWNLOADING)
        self.status_item.title = "Status: Downloading dependencies…"
        self._download_window = DownloadWindow(
            title="Downloading dependencies",
            detail="Starting download…",
        )
        self._download_window.show()

        def progress_callback(name: str, progress: float):
            percent = int(progress * 100)

            def _on_main() -> None:
                self.status_item.title = f"Status: Downloading {name}… {percent}%"
                if self._download_window is not None:
                    self._download_window.update(
                        detail=f"Downloading: {name}",
                        progress=progress,
                    )

            # Fired from the DependencyDownload worker thread — AppKit mutation
            # (menu title + window) must hop to the main thread, like done/error.
            _run_on_main_thread(_on_main)
            logger.debug(f"Downloading {name}: {percent}%")

        def done_callback():
            def _on_main() -> None:
                self._download_active = False
                if self._download_window is not None:
                    self._download_window.update(detail="Download complete", progress=1.0)
                    self._download_window.close()
                logger.info("✓ All dependencies downloaded")
                rumps.alert(
                    title="✅ Ready",
                    message="All dependencies were downloaded.\n\nMalinche is ready to use.",
                    ok="OK",
                )
                self.status_item.title = "Status: Ready"
                self._update_icon(AppStatus.IDLE)
            _run_on_main_thread(_on_main)

        def error_callback(exc: Exception):
            def _on_main() -> None:
                self._download_active = False
                if self._download_window is not None:
                    self._download_window.update(detail=f"Error: {exc}")
                if isinstance(exc, NetworkError):
                    logger.error(f"No internet: {exc}")
                    rumps.alert(
                        title="⚠️ No internet connection",
                        message=(
                            "No internet connection.\n\n"
                            "Malinche needs a one-time download of the transcription engine (~500 MB).\n"
                            "Connect to the internet and try again."
                        ),
                        ok="OK",
                    )
                    self.status_item.title = "Status: No internet"
                elif isinstance(exc, DiskSpaceError):
                    logger.error(f"Disk space error: {exc}")
                    rumps.alert(title="⚠️ Not enough disk space", message=str(exc), ok="OK")
                    self.status_item.title = "Status: Not enough disk space"
                elif isinstance(exc, DownloadError):
                    logger.error(f"Download error: {exc}")
                    rumps.alert(
                        title="⚠️ Download error",
                        message=f"Could not download dependencies:\n\n{str(exc)}\n\nPlease try again later.",
                        ok="OK",
                    )
                    self.status_item.title = "Status: Download error"
                else:
                    logger.error(f"Unexpected error: {exc}", exc_info=True)
                    rumps.alert(
                        title="⚠️ Error",
                        message=f"Unexpected error:\n\n{str(exc)}",
                        ok="OK",
                    )
                    self.status_item.title = "Status: Error"
                self._update_icon(AppStatus.ERROR)
            _run_on_main_thread(_on_main)

        started = self._download_manager.download_async(
            on_progress=progress_callback,
            on_done=done_callback,
            on_error=error_callback,
        )
        if not started:
            self._download_active = True

    def _prompt_whisper_repair(self, reason: str) -> None:
        """Show whisper-cli repair dialog and optionally start the repair."""
        self.status_item.title = "Status: whisper-cli repair required"
        self._update_icon(AppStatus.ERROR)
        response = rumps.alert(
            title="⚠️ whisper-cli needs repair",
            message=(
                f"{reason}\n\n"
                "Re-downloading ~3 MB of the correct binary usually fixes "
                "transcription.\n"
                "The download runs in the background — the app stays responsive."
            ),
            ok="Repair now",
            cancel="Skip",
        )
        if response == 1:
            self._run_repair_whisper()

    def _repair_whisper_clicked(self, _) -> None:
        """Trigger whisper-cli repair from menu."""
        if self._download_active:
            rumps.alert(
                title="Download in progress",
                message="Wait until the current download finishes, then try again.",
                ok="OK",
            )
            return
        confirm = rumps.alert(
            title="Repair whisper-cli",
            message=(
                "The current whisper-cli binary will be removed and re-downloaded "
                "from the release.\n"
                "The download runs in the background (~3 MB)."
            ),
            ok="Repair",
            cancel="Cancel",
        )
        if confirm == 1:
            self._run_repair_whisper()

    def _run_repair_whisper(self) -> None:
        """Uruchomienie naprawy whisper-cli w tle (wspólna ścieżka)."""
        if self._download_active:
            return
        self._download_active = True
        self._update_icon(AppStatus.DOWNLOADING)
        self.status_item.title = "Status: Repairing whisper-cli…"
        self._download_window = DownloadWindow(
            title="Repairing whisper-cli",
            detail="Removing and re-downloading whisper-cli…",
        )
        self._download_window.show()

        def progress_callback(name: str, progress: float) -> None:
            percent = int(progress * 100)

            def _on_main() -> None:
                self.status_item.title = f"Status: Repairing {name}… {percent}%"
                if self._download_window is not None:
                    self._download_window.update(
                        detail=f"Downloading: {name}",
                        progress=progress,
                    )

            # Worker-thread callback — AppKit mutation hops to the main thread.
            _run_on_main_thread(_on_main)

        def done_callback() -> None:
            def _on_main() -> None:
                self._download_active = False
                if self._download_window is not None:
                    self._download_window.update(detail="Repair complete", progress=1.0)
                    self._download_window.close()
                logger.info("✓ whisper-cli repaired")
                rumps.alert(
                    title="✅ Repaired",
                    message="whisper-cli was re-downloaded. Transcription should work now.",
                    ok="OK",
                )
                self.status_item.title = "Status: Ready"
                self._update_icon(AppStatus.IDLE)
            _run_on_main_thread(_on_main)

        def error_callback(exc: Exception) -> None:
            def _on_main() -> None:
                self._download_active = False
                if self._download_window is not None:
                    self._download_window.update(detail=f"Error: {exc}")
                logger.error("whisper-cli repair failed: %s", exc, exc_info=True)
                rumps.alert(
                    title="⚠️ Repair failed",
                    message=f"Could not download whisper-cli:\n\n{exc}",
                    ok="OK",
                )
                self.status_item.title = "Status: Repair failed"
                self._update_icon(AppStatus.ERROR)
            _run_on_main_thread(_on_main)

        started = self._download_manager.repair_whisper_async(
            on_progress=progress_callback,
            on_done=done_callback,
            on_error=error_callback,
        )
        if not started:
            self._download_active = False
            logger.warning("whisper-cli repair did not start (download already in progress)")

    def _prompt_unknown_volume(
        self, volume_path, uuid: str, timeout: float = 600
    ) -> str:
        """Synchronicznie zapytaj usera o nieznany dysk: Tak/Nie/Raz.

        Wywoływane z wątku FileMonitora. Dialog rumps musi działać na main
        thread, więc używamy AppHelper + threading.Event do synchronizacji.

        Timeout NIE oznacza "No": zwracamy ``DECISION_NONE`` (nic nie jest
        persystowane; periodic scan zapyta ponownie), a późniejsza odpowiedź
        w wiszącym wciąż dialogu zostaje zapisana przez
        ``_record_late_decision`` — modalu rumps nie da się programowo
        zamknąć, więc rejestrujemy spóźniony klik zamiast go gubić.

        Returns:
            DECISION_TRUSTED / DECISION_BLOCKED / DECISION_ONCE / DECISION_NONE.
        """
        state = {"decision": DECISION_NONE, "timed_out": False}
        state_lock = threading.Lock()
        done = threading.Event()
        volume_name = volume_path.name if hasattr(volume_path, "name") else str(volume_path)

        def _ask_on_main() -> None:
            decision = DECISION_NONE
            try:
                response = rumps.alert(
                    title="🛡 New disk detected",
                    message=(
                        f"Is '{volume_name}' a recorder you want to transcribe?\n\n"
                        "• Yes — remember as a recorder and transcribe\n"
                        "• No — remember as untrusted and ignore\n"
                        "• Once — transcribe this time only, don't remember"
                    ),
                    ok="Yes",
                    cancel="No",
                    other="Once",
                )
                if response == 1:
                    decision = DECISION_TRUSTED
                elif response == -1:
                    decision = DECISION_ONCE
                else:
                    decision = DECISION_BLOCKED
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    f"Dialog _prompt_unknown_volume failed: {exc}",
                    exc_info=True,
                )
                decision = DECISION_NONE  # błąd UI nie może trwale blokować
            finally:
                with state_lock:
                    if state["timed_out"]:
                        # Wątek monitora dawno wrócił z DECISION_NONE — zapisz
                        # spóźnioną odpowiedź zamiast mutować martwy słownik.
                        self._record_late_decision(uuid, volume_name, decision)
                    else:
                        state["decision"] = decision
                done.set()

        _run_on_main_thread(_ask_on_main)
        # Czekaj na decyzję; UI się nie zawiesi (rumps.alert na main jest modalny).
        if not done.wait(timeout=timeout):
            with state_lock:
                state["timed_out"] = True
            logger.info(
                f"Volume '{volume_name}' (uuid={uuid}) prompt timed out — "
                "no decision persisted, will re-ask"
            )
            return DECISION_NONE
        decision = state["decision"]
        logger.info(
            f"Volume '{volume_name}' (uuid={uuid}) decision={decision}"
        )
        return decision

    @staticmethod
    def _record_late_decision(uuid: str, volume_name: str, decision: str) -> None:
        """Persist an answer given AFTER the prompt timed out.

        The monitor thread already returned DECISION_NONE, so this is the only
        place the user's actual click can still be honored.
        """
        if decision == DECISION_TRUSTED or decision == DECISION_BLOCKED:
            try:
                UserSettings.mutate(
                    lambda s: s.add_trusted_volume(
                        uuid=uuid, name=volume_name, decision=decision
                    )
                )
                logger.info(
                    "Late volume decision recorded: name=%r decision=%s uuid=%s",
                    volume_name,
                    decision,
                    uuid,
                )
            except Exception as error:  # noqa: BLE001
                logger.error(
                    "Failed to record late volume decision for %s: %s",
                    volume_name,
                    error,
                    exc_info=True,
                )
        elif decision == DECISION_ONCE:
            volume_session.approve_once(uuid)
            logger.info(
                "Late 'Once' approval recorded for %s (uuid=%s)",
                volume_name,
                uuid,
            )

    def _update_status(self, _):
        """Update status menu item based on current state."""
        if not self.transcriber:
            self.status_item.title = "Status: Not running"
            self._update_icon(AppStatus.IDLE)
            return

        # Check retranscription first (takes priority)
        if self._retranscription_in_progress:
            filename = self._retranscription_file or "…"
            self.status_item.title = f"Status: Re-transcribing {filename}"
            self._update_icon(AppStatus.TRANSCRIBING)
            return

        if self._download_active:
            self._update_icon(AppStatus.DOWNLOADING)
            return

        state = self.transcriber.state
        status_str = state.get_status_string()
        self.status_item.title = f"Status: {status_str}"

        self._update_icon(state.status)

        # Surface a freshly written synthesis digest once (calm, never pesters).
        digest = state.digest_ready
        if digest:
            state.digest_ready = None
            self._notify_digest_ready(digest)
            self._refresh_insights_badge()

    def _open_logs(self, _):
        """Open the in-app log viewer (newest entries first, with live tail)."""
        log_file = config.LOG_FILE
        if not log_file.exists():
            rumps.alert("Error", f"Log file does not exist: {log_file}", "OK")
            return

        from src.ui.log_viewer import show_log_viewer

        try:
            self._log_viewer = show_log_viewer(log_file)
        except Exception as exc:
            logger.error("Failed to open log viewer: %s", exc)
            rumps.alert("Error", f"Could not open log viewer: {exc}", "OK")

    def _ensure_dashboard(self):
        """Build the Insights window if needed and refresh it to the latest persisted
        digest. The window is built once eagerly at launch (with a placeholder deck),
        so without this refresh it would render the placeholder for the whole session
        even after a real digest lands. Returns the controller (or None without AppKit).
        """
        if getattr(self, "_dashboard", None) is None:
            from src.ui.dashboard_window import build_dashboard_window

            self._dashboard = build_dashboard_window(
                callbacks=self._dashboard_callbacks()
            )
        if self._dashboard is not None:
            try:
                from src.ui.insight_pipeline import latest_deck

                fresh = latest_deck()
                if fresh is not None:
                    self._dashboard.updateDeck_(fresh)
            except Exception as exc:  # pragma: no cover - defensive
                logger.debug("could not refresh insights deck on open: %s", exc)
        return self._dashboard

    def _open_insights(self, _):
        """Open the Insights 'Konstelacja' window — the designed home surface."""
        try:
            if self._ensure_dashboard() is not None:
                self._dashboard.showWindow()
                self._refresh_insights_badge()
            else:
                logger.warning("Insights window unavailable (AppKit missing)")
                rumps.alert("Malinche", "Insights view needs macOS AppKit.", ok="OK")
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("Could not open Insights window: %s", exc)

    def _open_recall(self, _=None):
        """Bring the Insights window forward with the ask-bar focused — recall entry.

        Refreshes to the latest digest first (via _ensure_dashboard), so entering by
        hotkey doesn't operate on the stale launch-time placeholder deck.
        """
        try:
            dash = self._ensure_dashboard()
            if dash is not None:
                dash.focusRecall()
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("Could not open recall ask-bar: %s", exc)

    def _register_recall_hotkey(self):
        """Best-effort global hotkey (⌃⌥Space) → focus the recall ask-bar.

        A global NSEvent monitor needs Accessibility permission (silent no-op without
        it); a local monitor covers the app-active case (a global monitor never fires
        for the app's own events, so there is no double-trigger). Both return the event
        so the chord is never swallowed. All failures are swallowed — the ask-bar stays
        reachable from the Insights window regardless.
        """
        try:
            from AppKit import NSEvent
        except Exception:  # pragma: no cover - non-mac
            return
        mask = 1 << 10  # NSEventMaskKeyDown

        def _handler(event):
            try:
                if _is_recall_chord(event.keyCode(), event.modifierFlags()):
                    _run_on_main_thread(self._open_recall)
            except Exception:  # pragma: no cover - defensive
                pass
            return event

        try:
            # Retain the monitor tokens so they can be removed and never double-register.
            self._recall_hotkey_monitors = [
                NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(mask, _handler),
                NSEvent.addLocalMonitorForEventsMatchingMask_handler_(mask, _handler),
            ]
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("recall hotkey registration failed: %s", exc)

    def _dashboard_callbacks(self):
        """Wiring the Insights window needs from the app (vault + Obsidian).

        The window stays a pure renderer; only ``menu_app`` owns the transcriber
        and the vault, so the deep-link + recent-transcript logic lives here and
        is injected as callbacks.
        """
        return {
            "recent_transcripts": self._recent_transcripts_for_insights,
            "open_note": self._open_note_in_obsidian,
            "open_transcript": self._open_transcript_in_obsidian,
            "recall_search": self._recall_search,
            "recall_synthesize": self._recall_synthesize,
            "recall_save_answer": self._recall_save_answer,
            "recall_index_status": self._recall_index_status,
        }

    def _recall_index_status(self):
        """Snapshot of the background index (Standby/Indexing/Ready/Error + progress)
        for the window's honest partial banner. ``None`` if recall isn't wired."""
        try:
            from src.connections.recall import seam

            return seam.index_state().snapshot()
        except Exception:  # pragma: no cover - defensive
            return None

    def _recall_search(self, query):
        """Query the local recall index for the window's pull surface (no LLM).

        Best-effort and fully local: returns ``(results, confidence, status)`` where
        status distinguishes a genuine no-match ("ok") from an unindexed vault
        ("empty") or a not-ready engine ("unavailable"), so the window can be honest
        instead of claiming "nothing in your notes" when it never actually searched.
        """
        from src.connections.recall import seam

        return seam.search_detailed(query)

    def _recall_synthesize(self, query, results):
        """The one LLM in the pull path: synthesize a grounded answer from the
        retrieved passages on the user's explicit escalation. Best-effort → None
        (window shows a soft failure). Only these matched excerpts leave the Mac.

        A permanent billing/credit error trips the shared AI circuit breaker (same as
        the push digest path) so we don't re-issue a doomed request on every click.
        """
        from src.connections.recall.synthesis import synthesize_answer_safe
        from src.summarizer import APIBillingError

        try:
            return synthesize_answer_safe(query, results)
        except APIBillingError as exc:
            disable = getattr(self.transcriber, "_disable_ai", None)
            if disable is not None:
                disable("billing", exc)
            return None

    def _recall_save_answer(self, query, answer):
        """Save a synthesized answer to the vault as a linkable markdown note.

        Returns ``None`` (→ a soft "couldn't save" toast) rather than raising if the
        vault dir isn't configured yet.
        """
        from datetime import datetime

        from src.connections.recall.answer_writer import save_answer

        if not config.TRANSCRIBE_DIR:
            return None
        date_str = datetime.now().strftime("%Y-%m-%d")  # match digest_writer's 4-digit year
        return save_answer(query, answer, config.TRANSCRIBE_DIR, date_str=date_str)

    def _recent_transcripts_for_insights(self):
        """Real recent transcripts for the Insights rail (replaces atrapy).

        Returns a list of ``{"label": str, "path": Path}`` the dashboard renders
        as clickable rows; each opens its transcript in Obsidian.
        """
        from pathlib import Path

        out = []
        if self.transcriber is None:
            return out
        try:
            entries = self.transcriber.vault_index.recent_entries(5)
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("recent_entries for insights failed: %s", exc)
            entries = []  # fall through to the on-disk scan below
        for entry in entries:
            raw = entry.markdown_path or entry.source_filename or ""
            if not raw:
                continue
            name = raw.rsplit("/", 1)[-1]
            if name.endswith(".md"):
                name = name[:-3]
            path = Path(raw)
            if not path.is_absolute():
                path = Path(config.TRANSCRIBE_DIR) / raw
            out.append({"label": name, "path": path})
        if out:
            return out
        # The index can be empty (fresh install, or transcripts written by an
        # older build that didn't maintain it) while transcripts sit on disk.
        # Fall back to the filesystem so the rail reflects what's actually
        # there rather than showing "—".
        return self._recent_transcripts_from_disk()

    def _recent_transcripts_from_disk(self, limit: int = 5):
        """Most-recent ``*.md`` transcripts straight from the vault on disk.

        Excludes the digest sub-folder and the ``.malinche`` sidecar dir so the
        rail only lists actual transcripts, newest first by mtime.
        """
        from pathlib import Path

        try:
            root = Path(config.TRANSCRIBE_DIR)
            digest_dir = (root / config.DIGEST_DIR_NAME).resolve()
            hits = []
            for p in root.rglob("*.md"):
                rp = p.resolve()
                if ".malinche" in rp.parts:
                    continue
                if rp == digest_dir or digest_dir in rp.parents:
                    continue
                hits.append((p.stat().st_mtime, p))
            hits.sort(key=lambda it: it[0], reverse=True)
        except OSError as exc:  # pragma: no cover - defensive
            logger.debug("disk scan for recent transcripts failed: %s", exc)
            return []
        return [{"label": p.stem, "path": p} for _, p in hits[:limit]]

    def _open_note_in_obsidian(self, basename):
        """Resolve a source-note basename in the vault and open it in the
        user's configured markdown app (Obsidian by default)."""
        from src.ui import obsidian_link

        obsidian_link.open_note(
            basename, config.TRANSCRIBE_DIR, opener=config.NOTE_OPENER
        )

    def _open_transcript_in_obsidian(self, path):
        """Open a recent transcript (absolute path) in the user's configured
        markdown app (Obsidian by default)."""
        from src.ui import obsidian_link

        obsidian_link.open_path(path, opener=config.NOTE_OPENER)

    def _notify_digest_ready(self, digest_name: str) -> None:
        """Notify carrying the *thesis* of the top connection, not "digest ready".

        Per the tone-of-voice + Insights design, the signal should land the
        observation itself. Falls back to the plain note if no structured
        connection is available.
        """
        top = None
        try:
            from src.ui.insight_pipeline import latest_deck

            deck = latest_deck()
            if deck is not None and not deck.is_empty:
                top = deck.active()
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("could not load insights for notification: %s", exc)
        if top is not None:
            send_notification("Malinche", top.resolved_label(), top.rationale)
        else:
            send_notification("Malinche", "New synthesis digest ready", digest_name)

    def _refresh_insights_badge(self) -> None:
        """Show the count of connections in the latest digest on the menu item."""
        n = 0
        try:
            from src.ui.insight_pipeline import latest_deck

            deck = latest_deck()
            n = deck.unseen_count if deck is not None else 0
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("could not refresh insights badge: %s", exc)
        # Drives both the menu label and the gold-dot menu-bar icon (picked up by
        # the next status tick in _update_icon).
        self._unseen_insights = n
        try:
            # Count lives in the title; the ✦ is now the SF Symbol icon.
            self.insights_item.title = f"Insights ({n})" if n else "Insights"
        except Exception:  # pragma: no cover - cosmetic
            pass

    @staticmethod
    def _sf_image(symbol: str, point_size: float = 14.0):
        """A template NSImage for an SF Symbol, or ``None`` if unavailable.

        Template images render monochrome and adapt to light/dark and menu
        selection automatically — the right primitive for menu-item icons.
        """
        try:
            from AppKit import NSImage, NSImageSymbolConfiguration

            img = NSImage.imageWithSystemSymbolName_accessibilityDescription_(
                symbol, None
            )
            if img is None:
                return None
            try:
                cfg = NSImageSymbolConfiguration.configurationWithPointSize_weight_(
                    point_size, 0
                )
                img = img.imageWithSymbolConfiguration_(cfg)
            except Exception:  # pragma: no cover - cosmetic
                pass
            img.setTemplate_(True)
            return img
        except Exception:  # pragma: no cover - non-mac / old OS
            return None

    _STATUS_SYMBOLS = {
        AppStatus.IDLE: "circle",
        AppStatus.SCANNING: "magnifyingglass",
        AppStatus.TRANSCRIBING: "waveform",
        AppStatus.DOWNLOADING: "arrow.down.circle",
        AppStatus.MIGRATING: "arrow.triangle.2.circlepath",
        AppStatus.RECORDER_IDLE: "circle.fill",
        AppStatus.RECORDER_PENDING: "circle.dashed",
        AppStatus.ERROR: "exclamationmark.triangle.fill",
    }

    def _apply_status_icon(self, status) -> None:
        """Set an SF Symbol status dot on the header item, keyed by state.

        Called on every status tick (~2s), so it short-circuits when the state
        hasn't changed and caches the rendered NSImage per state — no fresh
        image allocation when nothing moved.
        """
        item = getattr(self, "status_item", None)
        if item is None:
            return
        if getattr(self, "_status_icon_applied", None) == status:
            return
        cache = getattr(self, "_status_icon_cache", None)
        if cache is None:
            cache = self._status_icon_cache = {}
        img = cache.get(status)
        if img is None:
            img = self._sf_image(self._STATUS_SYMBOLS.get(status, "circle"))
            if img is None:
                return
            cache[status] = img
        try:
            item._menuitem.setImage_(img)
            self._status_icon_applied = status
        except Exception:  # pragma: no cover - cosmetic
            pass

    def _apply_menu_icons(self) -> None:
        """Attach SF Symbol icons to the action items (best-effort)."""
        icons = {
            "insights_item": "sparkles",
            "open_logs_item": "doc.plaintext",
            "import_item": "square.and.arrow.down",
            "digest_item": "doc.richtext",
            "gen_digest_item": "wand.and.stars",
            "retranscribe_menu": "arrow.triangle.2.circlepath",
            "settings_item": "gearshape",
        }
        for attr, symbol in icons.items():
            item = getattr(self, attr, None)
            if item is None:
                continue
            img = self._sf_image(symbol)
            if img is None:
                continue
            try:
                item._menuitem.setImage_(img)
            except Exception:  # pragma: no cover - cosmetic
                pass

    def _open_latest_digest(self, _):
        """Open the most recent synthesis digest note in the default app."""
        import subprocess
        from pathlib import Path

        from src.connections.scheduler import get_scheduler

        path_str = get_scheduler().last_digest_path
        path = Path(path_str) if path_str else None
        if path is None or not path.exists():
            folder = Path(config.TRANSCRIBE_DIR) / config.DIGEST_DIR_NAME
            digests = sorted(folder.glob("*.md")) if folder.exists() else []
            path = digests[-1] if digests else None
        if path is None or not path.exists():
            rumps.alert("Malinche", "No synthesis digest yet.", ok="OK")
            return
        try:
            subprocess.Popen(["open", str(path)])
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to open digest: %s", exc)
            rumps.alert("Error", f"Could not open digest: {exc}", ok="OK")

    def _generate_digest_now(self, _):
        """Force a synthesis digest now (runs in the background, BYOK/PRO)."""
        import threading

        if not self.transcriber:
            return

        def _run():
            try:
                from src.connections import run_digest_if_due

                path = run_digest_if_due(self.transcriber, force=True)
                if path is None:
                    send_notification(
                        "Malinche",
                        "No new connections",
                        "Nothing connected this time (or AI key not set).",
                    )
            except Exception as exc:  # noqa: BLE001
                logger.error("Manual digest failed: %s", exc)
                send_notification("Malinche", "Digest failed", str(exc))

        threading.Thread(target=_run, name="ManualDigest", daemon=True).start()
        send_notification(
            "Malinche", "Generating synthesis digest…", "Reading your notes…"
        )

    def _reset_memory(self, _):
        """Reset transcription memory to a specific date."""
        target_date = choose_date_dialog(default_days=7)
        
        if target_date is None:
            logger.info("User cancelled reset memory dialog")
            return  # User cancelled
        
        logger.info(f"Resetting memory to date: {target_date.strftime('%Y-%m-%d')}")
        success = reset_state(target_date)

        if success:
            logger.info(f"Memory reset successful, sending notification for date: {target_date.strftime('%Y-%m-%d')}")
            send_notification(
                title="Malinche",
                message=f"From: {target_date.strftime('%Y-%m-%d')}",
                subtitle=TEXTS["reset_memory_success"],
            )
        else:
            logger.error("Failed to reset memory state")
            rumps.alert("Error", TEXTS["reset_memory_error"], ok="OK")

    def _show_settings(self, _):
        """Show settings window with maintenance/disks tabs wired to MenuApp callbacks."""
        callbacks = {
            "reset_memory":   self._reset_memory,
            "repair_whisper": self._repair_whisper_clicked,
            "open_logs":      self._open_logs,
            "show_about":     self._show_about,
            "review_volumes": self._manage_volumes_clicked,
            "forget_all_volumes": self._forget_all_volumes,
        }
        saved = show_settings_window(callbacks)
        if saved and getattr(self, "transcriber", None) is not None:
            # show_settings_window() already rebuilt the global config; refresh
            # the live daemon's summarizer/tagger and clear any AI circuit-breaker
            # trip so a fixed API key takes effect immediately — no restart.
            self.transcriber.reload_ai_config()

    def _forget_all_volumes(self, _):
        """Clear the trusted volume whitelist; user will be re-prompted on next mount."""
        settings = UserSettings.load()
        if not settings.trusted_volumes:
            rumps.alert("Disk list", "No remembered disks to forget.", "OK")
            return
        response = rumps.alert(
            title="Forget all disks?",
            message=(
                "All previously trusted/blocked decisions will be cleared. "
                "Each disk will be re-asked the next time it's connected."
            ),
            ok="Forget",
            cancel="Cancel",
        )
        if response != 1:
            return
        settings.trusted_volumes = []
        settings.save()
        logger.info("All trusted volume decisions forgotten")
        rumps.alert("Done", "Disk decisions have been cleared.", "OK")

    def _show_pro(self, _):
        """Show PRO activation or status dialog."""
        show_pro_status()

    def _show_about(self, _):
        """Show About dialog with app information."""
        show_about_dialog()

    def _get_staged_files(self) -> List[Path]:
        """Get list of audio files in staging directory.
        
        Returns:
            List of audio file paths, sorted by modification time
            (newest first), limited to 10 files
        """
        if not config.LOCAL_RECORDINGS_DIR.exists():
            return []
        
        files = []
        for ext in config.AUDIO_EXTENSIONS:
            # Search both lowercase and uppercase extensions
            files.extend(config.LOCAL_RECORDINGS_DIR.glob(f"*{ext}"))
            files.extend(config.LOCAL_RECORDINGS_DIR.glob(f"*{ext.upper()}"))
        
        # Sort by modification time (newest first) and limit to 10
        sorted_files = sorted(
            files,
            key=lambda p: p.stat().st_mtime,
            reverse=True
        )[:10]
        
        return sorted_files

    def _refresh_retranscribe_menu(self, _):
        """Refresh the retranscribe submenu with current staged files."""
        self.retranscribe_menu.title = "Retranscribe file…"
        # Clear existing submenu items (handle case when _menu is not yet initialized)
        try:
            if self.retranscribe_menu._menu is not None:
                self.retranscribe_menu.clear()
        except (AttributeError, TypeError):
            pass
        
        # Show busy state during retranscription
        if self._retranscription_in_progress:
            busy_item = rumps.MenuItem(
                f"⏳ Retranskrybowanie: {self._retranscription_file or '...'}"
            )
            busy_item.set_callback(None)
            self.retranscribe_menu.add(busy_item)
            return
        
        staged_files = self._get_staged_files()
        
        if not staged_files:
            empty_item = rumps.MenuItem("(no staged files)")
            empty_item.set_callback(None)
            self.retranscribe_menu.add(empty_item)
            return
        
        for audio_file in staged_files:
            try:
                mtime = datetime.fromtimestamp(audio_file.stat().st_mtime)
                date_str = mtime.strftime("%d.%m.%Y %H:%M")
                label = f"📁 {audio_file.name} ({date_str})"
            except OSError:
                label = f"📁 {audio_file.name}"
            
            item = rumps.MenuItem(label)
            # Store file path for callback
            item._audio_path = audio_file
            item.set_callback(self._retranscribe_file_callback)
            self.retranscribe_menu.add(item)

    def _retranscribe_file_callback(self, sender):
        """Handle retranscribe native-menu item click."""
        self._retranscribe_path(getattr(sender, '_audio_path', None))

    def _retranscribe_panel_file(self, filename):
        """Handle a re-transcribe row click from the status panel.

        The panel passes a bare file name; resolve it back to the staged audio
        path before running the shared re-transcription flow.
        """
        if not filename:
            return
        self._retranscribe_path(config.LOCAL_RECORDINGS_DIR / filename)

    def _retranscribe_path(self, audio_path):
        """Confirm and re-transcribe *audio_path* (shared by menu and panel)."""
        if not audio_path:
            return

        # Check if retranscription already in progress
        if self._retranscription_in_progress:
            rumps.alert(
                "Retranscription in progress",
                f"Wait for the current retranscription to finish:\n{self._retranscription_file}",
                ok="OK",
            )
            return

        # Check if automatic transcription is in progress
        if self.transcriber and self.transcriber.state.status == AppStatus.TRANSCRIBING:
            rumps.alert(
                "Transcription in progress",
                "Wait for the current transcription to finish.",
                ok="OK",
            )
            return

        # Confirm with user
        response = rumps.alert(
            "Retranscribe",
            f"Are you sure you want to re-transcribe:\n\n"
            f"{audio_path.name}\n\n"
            f"The existing transcription will be removed.",
            ok="Yes, retranscribe",
            cancel="Cancel",
        )
        
        if response != 1:  # Cancel
            return
        
        # Set flag BEFORE starting thread
        self._retranscription_in_progress = True
        self._retranscription_file = audio_path.name
        
        # Send start notification
        send_notification(
            title="Malinche",
            subtitle="Retranscription started",
            message=f"File: {audio_path.name}",
        )

        # Run retranscription in background thread
        def do_retranscribe():
            try:
                if self.transcriber and self.transcriber.transcriber:
                    success = self.transcriber.transcriber.force_retranscribe(audio_path)

                    if success:
                        send_notification(
                            title="Malinche",
                            subtitle="Retranscription complete",
                            message=f"File: {audio_path.name}",
                        )
                    else:
                        send_notification(
                            title="Malinche",
                            subtitle="Retranscription failed",
                            message=f"Check logs: {audio_path.name}",
                        )
            except RetranscribeLockBusyError:
                logger.info(
                    "Retranscribe lock-busy for %s — informing user",
                    audio_path.name,
                )
                def _on_main_lock_busy() -> None:
                    rumps.alert(
                        title="⏳ Automatic transcription in progress",
                        message=(
                            "Malinche is currently processing another file from the recorder.\n\n"
                            "Try again in a few minutes, after the automatic "
                            "transcription has finished."
                        ),
                        ok="OK",
                    )
                _run_on_main_thread(_on_main_lock_busy)
            except Exception as e:
                logger.error(f"Retranscribe error: {e}", exc_info=True)
                send_notification(
                    title="Malinche",
                    subtitle="Error",
                    message=str(e)[:50],
                )
            finally:
                # Always clear flag when done
                self._retranscription_in_progress = False
                self._retranscription_file = None
        
        thread = threading.Thread(target=do_retranscribe, daemon=True)
        thread.start()

    def _quit_app(self, _):
        """Quit application gracefully."""
        response = rumps.alert(
            "Quit Malinche",
            "Are you sure you want to quit?",
            ok="Quit",
            cancel="Cancel",
        )

        if response == 1:  # "OK" button (1 = OK, 0 = Cancel)
            self._shutdown()
            rumps.quit_application()

    def _shutdown(self):
        """Shutdown transcriber daemon."""
        if self.transcriber:
            logger.info("Shutting down transcriber from menu app...")
            self.transcriber.stop()
            self._running = False

            # Wait for daemon thread to finish
            if self.daemon_thread and self.daemon_thread.is_alive():
                self.daemon_thread.join(timeout=5.0)

    def _notify_billing_error(self, exc: Exception) -> None:
        """Show a one-time alert when Claude API hits a permanent error."""
        exc_str = str(exc).lower()
        if "invalid x-api-key" in exc_str or "authentication" in exc_str:
            title = "⚠️ Claude API: key rejected"
            message = (
                "Your Claude API key was rejected (invalid, missing or "
                "revoked).\n\n"
                "Open Settings and paste a valid key from\n"
                "https://console.anthropic.com/settings/keys\n\n"
                "Summaries and tags resume as soon as you save — no restart "
                "needed. Whisper transcription keeps working regardless."
            )
        elif "credit balance" in exc_str:
            title = "⚠️ Claude API: insufficient credits"
            message = (
                "Your Anthropic (BYOK) account has run out of credits.\n\n"
                "Top up at: https://console.anthropic.com/account/billing\n\n"
                "For the rest of this session, Malinche will transcribe "
                "without AI summaries or tags (Whisper still works normally)."
            )
        elif "not_found" in exc_str or "model" in exc_str:
            title = "⚠️ Claude API: unknown model"
            message = (
                "The Claude model configured in settings does not exist "
                "or has been retired.\n\n"
                "Change the model under Settings → Transcription.\n\n"
                "For the rest of this session, Malinche will transcribe "
                "without AI summaries or tags (Whisper still works normally)."
            )
        else:
            title = "⚠️ Claude API: permanent error"
            message = (
                f"Claude API returned a permanent error:\n{exc}\n\n"
                "For the rest of this session, Malinche will transcribe "
                "without AI summaries or tags (Whisper still works normally)."
            )

        def _on_main() -> None:
            try:
                rumps.alert(title=title, message=message, ok="Got it")
            except Exception as alert_exc:  # noqa: BLE001
                logger.error("AI error alert failed to display: %s", alert_exc)

        _run_on_main_thread(_on_main)

    def _run_daemon(self):
        """Run transcriber daemon in background thread."""
        try:
            logger.info("Starting transcriber daemon from menu app...")
            # Don't setup signal handlers in background thread
            self.transcriber = MalincheTranscriber(setup_signals=False)
            self.transcriber.set_ai_billing_callback(self._notify_billing_error)
            self.transcriber.set_unknown_volume_callback(self._prompt_unknown_volume)
            self.transcriber.start()
        except Exception as e:
            logger.error(f"Error in daemon thread: {e}", exc_info=True)
            rumps.notification(
                title="Malinche",
                subtitle="Error",
                message=f"Startup error: {e}",
            )

    def _start_daemon(self):
        """Uruchom daemon transcribera w tle."""
        if self._running:
            return  # Already running
        
        logger.info("Uruchamianie daemona transcribera...")
        self._running = True
        self.daemon_thread = threading.Thread(
            target=self._run_daemon,
            daemon=True,
            name="TranscriberDaemon"
        )
        self.daemon_thread.start()

    def run(self):
        """Start the menu bar application."""
        logger.info("=" * 60)
        logger.info("🚀 Malinche Menu App starting...")
        logger.info("=" * 60)

        # If wizard is not needed, start daemon immediately
        if not SetupWizard.needs_setup():
            self._start_daemon()

        # Run menu app (blocks until quit)
        super(MalincheMenuApp, self).run()


def main():
    """Main entry point for menu app."""
    if not RUMPS_AVAILABLE:
        print("ERROR: rumps not available. Install with: pip install rumps")
        sys.exit(1)

    try:
        from src import startup_manager

        try:
            startup_manager.sync_with_settings(UserSettings.load())
        except Exception as sync_err:  # noqa: BLE001
            logger.warning("Launch-at-login sync failed: %s", sync_err)

        # Menu-bar-only: no Dock icon. The built .app gets this from
        # LSUIElement in Info.plist, but that does not apply when running the
        # script directly (dev shows a "Python" Dock icon). Setting the
        # activation policy at runtime makes dev match production and is a
        # belt-and-suspenders for the bundle. Accessory (not Prohibited) so the
        # Settings / log windows can still be shown and focused.
        try:
            from AppKit import (
                NSApplication,
                NSApplicationActivationPolicyAccessory,
            )

            NSApplication.sharedApplication().setActivationPolicy_(
                NSApplicationActivationPolicyAccessory
            )
        except Exception as policy_err:  # noqa: BLE001
            logger.debug("Could not set accessory activation policy: %s", policy_err)

        app = MalincheMenuApp()
        app.run()
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()

