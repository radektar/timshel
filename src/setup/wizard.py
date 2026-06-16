"""First-run setup wizard."""

import rumps
from enum import Enum, auto
from pathlib import Path
from typing import Optional

from src.config import UserSettings, SUPPORTED_LANGUAGES, SUPPORTED_MODELS
from src.setup.downloader import DependencyDownloader
from src.setup.dependency_manager import DependencyManager
from src.setup.permissions import check_full_disk_access, open_fda_preferences
from src.logger import logger
from src.ui.dialogs import choose_folder_dialog
from src.ui.constants import TEXTS
from src.ui.constants import APP_VERSION
from src.ui.download_window import DownloadWindow
from src.vault_index import is_icloud_synced


class WizardStep(Enum):
    """Wizard steps for first-run configuration."""

    WELCOME = auto()
    DOWNLOAD = auto()
    PERMISSIONS = auto()
    SOURCE_CONFIG = auto()
    BASIC_CONFIG = auto()
    AI_CONFIG = auto()
    FINISH = auto()


class SetupWizard:
    """First-run setup wizard."""

    STEPS_ORDER = [
        WizardStep.WELCOME,
        WizardStep.SOURCE_CONFIG,
        WizardStep.BASIC_CONFIG,
        WizardStep.DOWNLOAD,
        WizardStep.PERMISSIONS,
        WizardStep.AI_CONFIG,
        WizardStep.FINISH,
    ]

    def __init__(self):
        """Initialize the wizard."""
        self.current_step_index = 0
        self.settings = UserSettings.load()
        self.downloader = DependencyDownloader(
            progress_callback=self._on_progress
        )
        self.dependency_manager = DependencyManager(self.downloader)
        self._download_status = ""
        self._download_in_progress = False
        self._download_error: Optional[Exception] = None
        self._download_complete = False
        self._wizard_completed = False
        self._download_window: Optional[DownloadWindow] = None
        self._restore_step_from_settings()

    def _restore_step_from_settings(self) -> None:
        """Restore wizard position from persisted setup_stage when available."""
        stage_name = (self.settings.setup_stage or "").lower()
        stage_map = {
            "welcome": WizardStep.WELCOME,
            "source_config": WizardStep.SOURCE_CONFIG,
            "basic_config": WizardStep.BASIC_CONFIG,
            "download": WizardStep.DOWNLOAD,
            "permissions": WizardStep.PERMISSIONS,
            "ai_config": WizardStep.AI_CONFIG,
            "finish": WizardStep.FINISH,
        }
        step = stage_map.get(stage_name)
        if step in self.STEPS_ORDER:
            self.current_step_index = self.STEPS_ORDER.index(step)

    def _persist_stage(self) -> None:
        """Persist current stage to support wizard resume after interruption."""
        self.settings.setup_stage = self.current_step.name.lower()
        self.settings.save()

    @staticmethod
    def _version_line(version: str) -> str:
        """Return major.minor part used for setup compatibility checks."""
        parts = (version or "").split(".")
        if len(parts) < 2:
            return version or ""
        return ".".join(parts[:2])

    @staticmethod
    def needs_setup() -> bool:
        """Check whether the wizard should run."""
        settings = UserSettings.load()
        if not settings.setup_completed:
            return True

        # Re-run wizard only when compatibility line changes (major.minor),
        # not for alpha/patch bumps inside the same release line.
        return SetupWizard._version_line(settings.setup_version) != SetupWizard._version_line(
            APP_VERSION
        )

    @property
    def current_step(self) -> WizardStep:
        """Current wizard step."""
        return self.STEPS_ORDER[self.current_step_index]

    def run(self) -> bool:
        """Run the wizard. Returns True if completed successfully."""
        logger.info("Starting Setup Wizard")

        self._wizard_completed = False
        self._process_wizard_step()

        return self._wizard_completed

    def _process_wizard_step(self):
        """Process the current wizard step."""
        self._persist_stage()
        if self.current_step == WizardStep.FINISH:
            self._show_finish()
            self.settings.setup_completed = True
            self.settings.setup_version = APP_VERSION
            self.settings.setup_stage = WizardStep.FINISH.name.lower()
            self.settings.save()
            logger.info("Setup Wizard finished successfully")
            self._wizard_completed = True
            return

        result = self._run_current_step()

        if result == "cancel":
            logger.info("Wizard cancelled by user")
            self._wizard_completed = False
            return
        elif result == "back" and self.current_step_index > 0:
            self.current_step_index -= 1
            self._process_wizard_step()
        elif result == "next":
            self.current_step_index += 1
            self._process_wizard_step()

    def _run_current_step(self) -> str:
        """Dispatch the current step to its handler."""
        step_handlers = {
            WizardStep.WELCOME: self._show_welcome,
            WizardStep.DOWNLOAD: self._show_download,
            WizardStep.PERMISSIONS: self._show_permissions,
            WizardStep.SOURCE_CONFIG: self._show_source_config,
            WizardStep.BASIC_CONFIG: self._show_basic_config,
            WizardStep.AI_CONFIG: self._show_ai_config,
        }
        handler = step_handlers.get(self.current_step)
        if handler:
            return handler()
        return "next"

    def _on_progress(self, name: str, progress: float):
        """Download progress callback (runs on the download worker thread)."""
        self._download_status = f"{name}: {int(progress * 100)}%"
        logger.debug(f"Downloading: {self._download_status}")

        if self._download_window is not None:
            self._download_window.update(
                detail=f"Downloading: {name}",
                progress=progress,
            )

        # Quarter-progress notifications
        percent = int(progress * 100)
        if percent in {25, 50, 75, 100}:
            rumps.notification(
                title="Malinche — Downloading",
                subtitle=f"{name}",
                message=f"Progress: {percent}%",
            )

    def _show_welcome(self) -> str:
        """Welcome screen (styled onboarding window, alert fallback)."""
        from src.setup.onboarding_window import show_onboarding_screen

        result = show_onboarding_screen(
            title="Welcome to Malinche",
            body=(
                "Malinche automatically transcribes recordings from your voice "
                "recorder or SD card.\n\nWe'll walk you through a quick setup — "
                "about 3–5 minutes."
            ),
            primary="Get started",
            secondary="Cancel",
            step_index=0,
            step_count=len(self.STEPS_ORDER),
        )
        if result is None:
            result = rumps.alert(
                title="🎙️ Welcome to Malinche!",
                message=(
                    "Malinche automatically transcribes recordings from your "
                    "voice recorder or SD card.\n\n"
                    "We'll walk you through a quick setup.\n\n"
                    "It takes about 3-5 minutes."
                ),
                ok="Get started →",
                cancel="Cancel",
            )
        return "next" if result == 1 else "cancel"

    def _show_download(self) -> str:
        """Download dependencies for the selected model."""
        status = self.dependency_manager.status()
        if status.ready:
            logger.info("Dependencies already installed — skipping step")
            return "next"

        model = self.settings.whisper_model
        total_mb = status.total_missing_size / 1_000_000
        response = rumps.alert(
            title="📥 Download transcription engine",
            message=(
                f"Selected model: {model}\n"
                f"Missing data to download: ~{total_mb:.0f} MB\n\n"
                "Download now? You can go back and pick a different model."
            ),
            ok="Download now",
            cancel="Change model",
            other="Cancel",
        )

        if response == 0:
            return "back"
        if response != 1:
            return "cancel"

        self._download_in_progress = True
        self._download_complete = False
        self._download_error = None
        self._download_status = "Starting…"

        self._download_window = DownloadWindow(
            title="Downloading dependencies",
            detail=f"Model: {model}",
        )
        self._download_window.show()
        self._download_in_background()

        # Download continues in the background. Wizard advances right away;
        # the user sees progress in the DownloadWindow, which closes itself
        # on success (or stays open with an error message).
        return "next"

    def _download_in_background(self):
        """Start asynchronous download and update wizard flags from callbacks."""
        logger.info("Background dependency download started")

        def _done() -> None:
            self._download_complete = True
            self._download_in_progress = False
            if self._download_window is not None:
                self._download_window.update(
                    detail="✓ Download complete", progress=1.0
                )
                self._download_window.close_after(1.2)
            try:
                rumps.notification(
                    title="Malinche",
                    subtitle="Download complete",
                    message="The transcription engine is ready.",
                )
            except Exception:
                pass
            logger.info("✓ Download finished successfully")

        def _error(exc: Exception) -> None:
            self._download_error = exc
            self._download_in_progress = False
            if self._download_window is not None:
                self._download_window.update(detail=f"❌ Error: {exc}")
            try:
                rumps.notification(
                    title="Malinche",
                    subtitle="Download failed",
                    message=str(exc),
                )
            except Exception:
                pass
            logger.error(f"Download error: {exc}", exc_info=True)

        started = self.dependency_manager.download_async(
            on_progress=self._on_progress,
            on_done=_done,
            on_error=_error,
        )
        if not started:
            self._download_in_progress = True

    def _show_permissions(self) -> str:
        """Full Disk Access instructions — skipped if already granted."""
        if check_full_disk_access():
            logger.info("FDA already granted — skipping step")
            return "next"

        response = rumps.alert(
            title="🔐 Disk access permissions",
            message=(
                "To detect a recorder automatically, Malinche needs "
                "'Full Disk Access' permission.\n\n"
                "Steps:\n"
                "1. Click 'Open Settings'\n"
                "2. Unlock the lock 🔒 (admin password)\n"
                "3. Find 'Malinche' and check ☑\n"
                "4. Return to this app\n\n"
                "You can also skip this step and pick files manually."
            ),
            ok="Open Settings",
            cancel="Skip",
            other="Cancel",
        )

        if response == -1:  # Cancel (other button)
            return "cancel"
        elif response == 1:  # Open Settings
            open_fda_preferences()
            rumps.alert(
                title="Done?",
                message="Click OK once you've granted the permission in System Settings.",
                ok="OK",
            )

        return "next"

    def _show_source_config(self) -> str:
        """Recording source configuration.

        v2.0.0-beta.2: 'auto' mode was removed. Every disk must be
        explicitly approved (via the Yes/No/Once dialog when connected,
        or legacy 'specific' with a list of disk names).
        """
        response = rumps.alert(
            title="📁 Recording sources",
            message=(
                "Where should Malinche pull recordings from?\n\n"
                "• Ask for every new disk (recommended) — Malinche asks "
                "the first time a new disk is connected whether it's a "
                "recorder. The decision is remembered.\n\n"
                "• Specific disk names (advanced) — only volumes with the "
                "names you provide (e.g. LS-P1, ZOOM-H6)."
            ),
            ok="Ask on new disk",
            cancel="Specific disk names",
            other="Cancel",
        )

        if response == -1:  # Cancel (other button)
            return "cancel"
        elif response == 1:  # Ask — manual + UUID whitelist
            self.settings.watch_mode = "manual"
            self.settings.watched_volumes = []
            self.settings.needs_volume_onboarding = False
        else:  # Specific disks (legacy specific)
            window = rumps.Window(
                title="Disk names",
                message="Enter disk names separated by commas\n(e.g. LS-P1, ZOOM-H6):",
                default_text="LS-P1",
                ok="OK",
                cancel="Back",
                dimensions=(300, 24),
            )
            result = window.run()

            if result.clicked == 0:  # Cancel/Back
                return "back"

            volumes = [v.strip() for v in result.text.split(",") if v.strip()]
            self.settings.watch_mode = "specific"
            self.settings.watched_volumes = volumes
            self.settings.needs_volume_onboarding = False

        return "next"

    def _show_basic_config(self) -> str:
        """Unified step for output folder, language and model."""
        try:
            from AppKit import NSAlert, NSView, NSRect, NSTextField, NSPopUpButton

            from src.ui.folder_picker import (
                FolderPickerTarget,
                PICK_FOLDER_RESPONSE,
                apply_basic_settings,
                make_folder_picker_button,
                select_folder_with_warning,
            )

            language_codes = list(SUPPORTED_LANGUAGES.keys())
            model_codes = list(SUPPORTED_MODELS.keys())
            selected_folder = str(self.settings.output_dir)
            selected_language = (
                self.settings.language
                if self.settings.language in language_codes
                else language_codes[0]
            )
            selected_model = (
                self.settings.whisper_model
                if self.settings.whisper_model in model_codes
                else model_codes[0]
            )

            picker_target = FolderPickerTarget.alloc().init()

            while True:
                alert = NSAlert.alloc().init()
                alert.setMessageText_(TEXTS["wizard_basic_title"])
                alert.setInformativeText_(TEXTS["wizard_basic_message"])
                alert.addButtonWithTitle_("Next")
                alert.addButtonWithTitle_("Back")
                alert.addButtonWithTitle_("Cancel")

                accessory = NSView.alloc().initWithFrame_(NSRect((0, 0), (460, 170)))

                folder_label = NSTextField.alloc().initWithFrame_(NSRect((0, 140), (130, 20)))
                folder_label.setStringValue_("Output folder:")
                folder_label.setBezeled_(False)
                folder_label.setDrawsBackground_(False)
                folder_label.setEditable_(False)
                folder_label.setSelectable_(False)
                accessory.addSubview_(folder_label)

                folder_value = NSTextField.alloc().initWithFrame_(NSRect((130, 140), (330, 20)))
                display_folder = (
                    selected_folder
                    if len(selected_folder) <= 60
                    else "..." + selected_folder[-57:]
                )
                folder_value.setStringValue_(display_folder)
                folder_value.setBezeled_(False)
                folder_value.setDrawsBackground_(False)
                folder_value.setEditable_(False)
                folder_value.setSelectable_(True)
                accessory.addSubview_(folder_value)

                pick_button = make_folder_picker_button(
                    NSRect((130, 108), (200, 28)),
                    target=picker_target,
                    title="Choose folder…",
                )
                if pick_button is not None:
                    accessory.addSubview_(pick_button)

                language_label = NSTextField.alloc().initWithFrame_(NSRect((0, 68), (130, 20)))
                language_label.setStringValue_("Language:")
                language_label.setBezeled_(False)
                language_label.setDrawsBackground_(False)
                language_label.setEditable_(False)
                language_label.setSelectable_(False)
                accessory.addSubview_(language_label)

                language_popup = NSPopUpButton.alloc().initWithFrame_(NSRect((130, 64), (330, 26)))
                for code, name in SUPPORTED_LANGUAGES.items():
                    language_popup.addItemWithTitle_(f"{name} ({code})")
                language_popup.selectItemAtIndex_(language_codes.index(selected_language))
                accessory.addSubview_(language_popup)

                model_label = NSTextField.alloc().initWithFrame_(NSRect((0, 28), (130, 20)))
                model_label.setStringValue_("Model:")
                model_label.setBezeled_(False)
                model_label.setDrawsBackground_(False)
                model_label.setEditable_(False)
                model_label.setSelectable_(False)
                accessory.addSubview_(model_label)

                model_popup = NSPopUpButton.alloc().initWithFrame_(NSRect((130, 24), (330, 26)))
                for code, name in SUPPORTED_MODELS.items():
                    model_popup.addItemWithTitle_(f"{code.upper()}: {name}")
                model_popup.selectItemAtIndex_(model_codes.index(selected_model))
                accessory.addSubview_(model_popup)

                alert.setAccessoryView_(accessory)
                response = alert.runModal()

                selected_language = language_codes[language_popup.indexOfSelectedItem()]
                selected_model = model_codes[model_popup.indexOfSelectedItem()]

                if response == PICK_FOLDER_RESPONSE:
                    picked = select_folder_with_warning(
                        choose_folder_dialog,
                        warn_non_icloud=lambda _p: rumps.alert(
                            title="Folder outside iCloud",
                            message=(
                                "The selected folder is not inside iCloud. "
                                "Multi-device dedup will be local to this Mac."
                            ),
                            ok="OK",
                        ),
                        is_icloud_check=lambda p: is_icloud_synced(Path(p)),
                        title=TEXTS["folder_picker_title"],
                        message=TEXTS["folder_picker_message"],
                    )
                    if picked:
                        selected_folder = picked
                    continue

                if response == 1001:
                    return "back"
                if response == 1002:
                    return "cancel"

                apply_basic_settings(
                    self.settings,
                    selected_folder=selected_folder,
                    selected_language=selected_language,
                    selected_model=selected_model,
                    supported_languages=SUPPORTED_LANGUAGES,
                    supported_models=SUPPORTED_MODELS,
                )
                return "next"

        except ImportError:
            logger.warning("AppKit not available, fallback to legacy config steps")
            output_result = self._show_output_config()
            if output_result != "next":
                return output_result
            return self._show_language()

    def _show_output_config(self) -> str:
        """Output folder configuration (legacy fallback)."""
        # Three-button rumps.alert: ok = pick folder, cancel = use default,
        # other = back. We add a Cancel option in the secondary dialog if the
        # user opens the picker but cancels it.
        response = rumps.alert(
            title=TEXTS["folder_picker_title"],
            message=(
                f"{TEXTS['folder_picker_message']}\n\n"
                f"Current: {self.settings.output_dir}"
            ),
            ok=TEXTS["folder_picker_select"],
            cancel=TEXTS["folder_picker_default"],
            other=TEXTS["folder_picker_back"],
        )

        if response == -1:  # other = Back (rumps -1 is "other")
            return "back"
        elif response == 0:  # Use default
            return "next"
        # else response == 1: Choose folder

        folder_path = choose_folder_dialog()
        if folder_path:
            self.settings.output_dir = folder_path
            return "next"
        else:
            response2 = rumps.alert(
                title=TEXTS["folder_picker_title"],
                message="Folder selection cancelled. What would you like to do?",
                ok="Use default",
                cancel="Cancel setup",
                other="Back",
            )

            if response2 == -1:
                return "back"
            elif response2 == 0:
                return "cancel"
            else:
                return "next"

    def _show_language(self) -> str:
        """Audio-language configuration (legacy fallback)."""
        try:
            from AppKit import NSAlert, NSPopUpButton, NSRect

            alert = NSAlert.alloc().init()
            alert.setMessageText_("🗣️ Transcription language")
            alert.setInformativeText_(
                "Choose the default language for all recordings.\n\n"
                "You can change this later in Settings."
            )

            popup = NSPopUpButton.alloc().initWithFrame_(NSRect((0, 0), (250, 24)))
            for code, name in SUPPORTED_LANGUAGES.items():
                popup.addItemWithTitle_(f"{name} ({code})")

            lang_codes = list(SUPPORTED_LANGUAGES.keys())
            if self.settings.language in lang_codes:
                current_idx = lang_codes.index(self.settings.language)
                popup.selectItemAtIndex_(current_idx)

            alert.setAccessoryView_(popup)
            alert.addButtonWithTitle_("OK")
            alert.addButtonWithTitle_("Back")
            alert.addButtonWithTitle_("Cancel")

            response = alert.runModal()
            # NSAlert button responses: 1000=OK, 1001=Back, 1002=Cancel
            if response == 1000:
                selected_idx = popup.indexOfSelectedItem()
                selected_code = lang_codes[selected_idx]
                self.settings.language = selected_code
                return "next"
            elif response == 1001:
                return "back"
            else:
                return "cancel"
        except ImportError:
            logger.warning("AppKit not available, using text input fallback")
            lang_options = "\n".join(
                [f"• {code}: {name}" for code, name in SUPPORTED_LANGUAGES.items()]
            )

            window = rumps.Window(
                title="🗣️ Transcription language",
                message=(
                    f"What language are your recordings in?\n\n"
                    f"Available options:\n{lang_options}\n\n"
                    f"Type the language code:"
                ),
                default_text=self.settings.language,
                ok="OK",
                cancel="Back",
                dimensions=(200, 24),
            )
            result = window.run()

            if result.clicked == 0:
                return "back"

            lang = result.text.strip().lower()
            if lang in SUPPORTED_LANGUAGES:
                self.settings.language = lang

            return "next"

    def _show_ai_config(self) -> str:
        """AI summary configuration (optional)."""
        response = rumps.alert(
            title="🤖 AI summaries (optional)",
            message=(
                "Malinche can generate intelligent summaries and titles "
                "using Claude AI.\n\n"
                "This requires an API key from anthropic.com\n"
                "(cost ~$0.01-0.05 per transcription)\n\n"
                "You can configure this later in Settings."
            ),
            ok="Skip",
            cancel="Configure API",
            other="Cancel",
        )

        if response == -1:  # Cancel (other button)
            return "cancel"
        elif response == 1:  # Skip
            self.settings.enable_ai_summaries = False
            return "next"

        # Configure API key
        window = rumps.Window(
            title="Claude API key",
            message="Paste the API key from anthropic.com:",
            default_text="",
            ok="Save",
            cancel="Skip",
            dimensions=(350, 24),
        )
        result = window.run()

        if result.clicked == 1 and result.text.strip():
            self.settings.enable_ai_summaries = True
            self.settings.ai_api_key = result.text.strip()
        else:
            self.settings.enable_ai_summaries = False

        return "next"

    def _show_finish(self) -> str:
        """Finish screen (styled onboarding window, alert fallback)."""
        from src.setup.onboarding_window import show_onboarding_screen

        result = show_onboarding_screen(
            title="Malinche is ready",
            body=(
                "Setup complete. Connect your voice recorder or SD card and "
                "Malinche transcribes automatically.\n\nThe icon lives in the "
                "menu bar at the top of the screen. Happy transcribing!"
            ),
            primary="Get started",
            step_index=len(self.STEPS_ORDER) - 1,
            step_count=len(self.STEPS_ORDER),
        )
        if result is None:
            rumps.alert(
                title="✅ Malinche is ready!",
                message=(
                    "Setup complete.\n\n"
                    "Connect your voice recorder or SD card and Malinche "
                    "will process your recordings automatically.\n\n"
                    "The 🎙️ icon appears in the menu bar (top of the screen).\n\n"
                    "Happy transcribing!"
                ),
                ok="🎉 Get started!",
            )
        return "next"
