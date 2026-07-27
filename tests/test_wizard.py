"""Unit tests for SetupWizard."""

from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from src.config import UserSettings
from src.setup.wizard import SetupWizard, WizardStep
from src.ui.constants import APP_VERSION


class TestSetupWizard:
    """Testy dla klasy SetupWizard."""

    def test_needs_setup_first_run(self, tmp_path, monkeypatch):
        """Zwraca True gdy setup_completed=False."""
        config_file = tmp_path / "config.json"
        monkeypatch.setattr(
            UserSettings, "config_path", staticmethod(lambda: config_file)
        )

        assert SetupWizard.needs_setup() is True

    def test_needs_setup_after_completion(self, tmp_path, monkeypatch):
        """Zwraca False gdy setup_completed=True i wersja setupu jest aktualna."""
        config_file = tmp_path / "config.json"
        monkeypatch.setattr(
            UserSettings, "config_path", staticmethod(lambda: config_file)
        )

        settings = UserSettings(setup_completed=True, setup_version=APP_VERSION)
        settings.save()

        assert SetupWizard.needs_setup() is False

    def test_needs_setup_when_setup_version_missing(self, tmp_path, monkeypatch):
        """Zwraca True dla starego configu bez setup_version po update aplikacji."""
        config_file = tmp_path / "config.json"
        monkeypatch.setattr(
            UserSettings, "config_path", staticmethod(lambda: config_file)
        )

        settings = UserSettings(setup_completed=True, setup_version="")
        settings.save()

        assert SetupWizard.needs_setup() is True

    def test_needs_setup_false_for_alpha_patch_bump(self, tmp_path, monkeypatch):
        """Zmiana alpha/patch w tej samej linii major.minor nie wymusza wizarda."""
        config_file = tmp_path / "config.json"
        monkeypatch.setattr(
            UserSettings, "config_path", staticmethod(lambda: config_file)
        )
        monkeypatch.setattr("src.setup.wizard.APP_VERSION", "2.0.0-alpha.5")

        settings = UserSettings(setup_completed=True, setup_version="2.0.0-alpha.4")
        settings.save()

        assert SetupWizard.needs_setup() is False

    def test_wizard_step_order(self):
        """Kroki są w poprawnej kolejności."""
        assert SetupWizard.STEPS_ORDER[0] == WizardStep.WELCOME
        assert SetupWizard.STEPS_ORDER[1] == WizardStep.SOURCE_CONFIG
        assert SetupWizard.STEPS_ORDER[2] == WizardStep.BASIC_CONFIG
        assert SetupWizard.STEPS_ORDER[3] == WizardStep.DOWNLOAD
        # Import step sits AFTER the key screen (the hook) and before FINISH.
        assert SetupWizard.STEPS_ORDER[-3] == WizardStep.AI_CONFIG
        assert SetupWizard.STEPS_ORDER[-2] == WizardStep.IMPORT_NOTES
        assert SetupWizard.STEPS_ORDER[-1] == WizardStep.FINISH
        assert len(SetupWizard.STEPS_ORDER) == 8

    def test_welcome_step_ok(self, monkeypatch):
        """Kliknięcie OK przechodzi dalej."""
        monkeypatch.setattr("rumps.alert", lambda **kwargs: 1)

        wizard = SetupWizard()
        result = wizard._show_welcome()

        assert result == "next"

    def test_welcome_step_cancel(self, monkeypatch):
        """Kliknięcie Cancel kończy wizard."""
        monkeypatch.setattr("rumps.alert", lambda **kwargs: 0)

        wizard = SetupWizard()
        result = wizard._show_welcome()

        assert result == "cancel"

    def test_download_skip_if_installed(self, monkeypatch):
        """Pomija krok gdy zależności zainstalowane."""
        wizard = SetupWizard()
        monkeypatch.setattr(
            wizard.dependency_manager,
            "status",
            lambda: Mock(ready=True, total_missing_size=0),
        )

        result = wizard._show_download()

        assert result == "next"

    def test_download_can_return_back_to_model_choice(self, monkeypatch):
        """Użytkownik może wrócić do kroku wyboru modelu."""
        wizard = SetupWizard()
        monkeypatch.setattr(
            wizard.dependency_manager,
            "status",
            lambda: Mock(ready=False, total_missing_size=500_000_000),
        )
        monkeypatch.setattr("rumps.alert", lambda **kwargs: 0)

        assert wizard._show_download() == "back"

    def test_download_does_not_show_status_modal_after_start(self, monkeypatch):
        """Po starcie pobierania wizard nie pokazuje statycznego modala statusu.

        Regresja dla UX bugu: modal 'Pobieranie trwa w tle' nie reagował na
        zakończenie pobierania i blokował wizard.
        """
        wizard = SetupWizard()
        monkeypatch.setattr(
            wizard.dependency_manager,
            "status",
            lambda: Mock(ready=False, total_missing_size=500_000_000),
        )
        monkeypatch.setattr(
            wizard.dependency_manager,
            "download_async",
            lambda **kwargs: True,
        )

        alert_calls = []

        def _fake_alert(**kwargs):
            alert_calls.append(kwargs)
            return 1  # "Pobierz teraz"

        monkeypatch.setattr("rumps.alert", _fake_alert)

        fake_window = Mock()
        monkeypatch.setattr(
            "src.setup.wizard.DownloadWindow", lambda **kwargs: fake_window
        )

        result = wizard._show_download()

        assert result == "next"
        for call in alert_calls:
            title = call.get("title", "")
            assert (
                "Download running in background" not in title
            ), f"Unexpected status modal after download start: {title}"
            assert (
                "Downloaded" not in title
            ), f"Unexpected success modal after download start: {title}"
        fake_window.show.assert_called_once()

    def test_download_done_closes_window_automatically(self, monkeypatch):
        """Callback _done woła close_after na DownloadWindow."""
        wizard = SetupWizard()
        monkeypatch.setattr(
            wizard.dependency_manager,
            "status",
            lambda: Mock(ready=False, total_missing_size=500_000_000),
        )

        captured = {}

        def _fake_download_async(on_progress, on_done, on_error):
            captured["on_done"] = on_done
            captured["on_error"] = on_error
            return True

        monkeypatch.setattr(
            wizard.dependency_manager, "download_async", _fake_download_async
        )
        monkeypatch.setattr("rumps.alert", lambda **kwargs: 1)

        fake_window = Mock()
        monkeypatch.setattr(
            "src.setup.wizard.DownloadWindow", lambda **kwargs: fake_window
        )

        wizard._show_download()
        captured["on_done"]()

        fake_window.close_after.assert_called_once()
        fake_window.update.assert_any_call(detail="✓ Download complete", progress=1.0)

    def test_download_error_keeps_window_open_and_notifies(self, monkeypatch):
        """Callback _error pokazuje błąd w oknie i nie wywołuje close_after."""
        wizard = SetupWizard()
        monkeypatch.setattr(
            wizard.dependency_manager,
            "status",
            lambda: Mock(ready=False, total_missing_size=500_000_000),
        )

        captured = {}

        def _fake_download_async(on_progress, on_done, on_error):
            captured["on_error"] = on_error
            return True

        monkeypatch.setattr(
            wizard.dependency_manager, "download_async", _fake_download_async
        )
        monkeypatch.setattr("rumps.alert", lambda **kwargs: 1)

        notifications = []
        monkeypatch.setattr(
            "rumps.notification",
            lambda **kwargs: notifications.append(kwargs),
        )

        fake_window = Mock()
        monkeypatch.setattr(
            "src.setup.wizard.DownloadWindow", lambda **kwargs: fake_window
        )

        wizard._show_download()
        captured["on_error"](RuntimeError("boom"))

        fake_window.close_after.assert_not_called()
        fake_window.update.assert_any_call(detail="❌ Error: boom")
        assert any(
            "Download failed" in (n.get("subtitle") or "") for n in notifications
        ), "Error notification should be sent"

    def test_stage_is_persisted_on_step(self, tmp_path, monkeypatch):
        """Wizard zapisuje setup_stage, aby umożliwić wznowienie."""
        config_file = tmp_path / "config.json"
        monkeypatch.setattr(
            UserSettings, "config_path", staticmethod(lambda: config_file)
        )
        monkeypatch.setattr("rumps.alert", lambda **kwargs: 1)

        wizard = SetupWizard()
        wizard.current_step_index = 2  # BASIC_CONFIG
        wizard._persist_stage()

        loaded = UserSettings.load()
        assert loaded.setup_stage == "basic_config"

    def test_permissions_skip_if_granted(self, monkeypatch):
        """Pomija krok gdy FDA nadane."""
        monkeypatch.setattr("src.setup.wizard.check_full_disk_access", lambda: True)

        wizard = SetupWizard()
        result = wizard._show_permissions()

        assert result == "next"

    def test_settings_saved_after_finish(self, tmp_path, monkeypatch):
        """Po zakończeniu setup_completed=True."""
        config_file = tmp_path / "config.json"
        monkeypatch.setattr(
            UserSettings, "config_path", staticmethod(lambda: config_file)
        )

        # Mock wszystkie dialogi żeby zwracały "next"
        monkeypatch.setattr("rumps.alert", lambda **kwargs: 1)
        monkeypatch.setattr(
            "rumps.Window",
            lambda **kwargs: Mock(run=lambda: Mock(clicked=1, text="test")),
        )

        wizard = SetupWizard()
        # Symuluj że wszystkie kroki przeszły
        wizard.settings.setup_completed = True
        wizard.settings.save()

        loaded = UserSettings.load()
        assert loaded.setup_completed is True


class TestImportNotesStep:
    """Krok IMPORT_NOTES — zbiera folder, persystuje natychmiast."""

    def _wizard(self, tmp_path, monkeypatch):
        config_file = tmp_path / "config.json"
        monkeypatch.setattr(
            UserSettings, "config_path", staticmethod(lambda: config_file)
        )
        monkeypatch.setattr(
            "src.setup.onboarding_window._APPKIT_AVAILABLE", True, raising=False
        )
        return SetupWizard()

    def test_skip_persists_nothing(self, tmp_path, monkeypatch):
        wizard = self._wizard(tmp_path, monkeypatch)
        monkeypatch.setattr(
            "src.setup.onboarding_window.show_onboarding_screen",
            lambda **kw: 0,  # Skip
        )
        assert wizard._show_import_notes() == "next"
        assert UserSettings.load().pending_import_dir is None

    def test_cancel_cancels(self, tmp_path, monkeypatch):
        wizard = self._wizard(tmp_path, monkeypatch)
        monkeypatch.setattr(
            "src.setup.onboarding_window.show_onboarding_screen",
            lambda **kw: -1,  # Cancel
        )
        assert wizard._show_import_notes() == "cancel"

    def test_pick_persists_immediately(self, tmp_path, monkeypatch):
        wizard = self._wizard(tmp_path, monkeypatch)
        notes = tmp_path / "notes"
        (notes / "sub").mkdir(parents=True)
        (notes / "a.md").write_text("body", encoding="utf-8")
        (notes / "sub" / "b.txt").write_text("body", encoding="utf-8")
        (notes / "skip.pdf").write_text("x", encoding="utf-8")
        monkeypatch.setattr(
            "src.setup.onboarding_window.show_onboarding_screen",
            lambda **kw: 1,  # Choose folder…
        )
        monkeypatch.setattr(
            "src.ui.dialogs.choose_folder_dialog", lambda **kw: str(notes)
        )
        monkeypatch.setattr("rumps.alert", lambda *a, **kw: 1)  # confirm count

        assert wizard._show_import_notes() == "next"
        assert UserSettings.load().pending_import_dir == str(notes)
        assert wizard._count_importable(notes) == 2  # pdf filtered out

    def test_empty_folder_not_persisted(self, tmp_path, monkeypatch):
        wizard = self._wizard(tmp_path, monkeypatch)
        empty = tmp_path / "empty"
        empty.mkdir()
        # Screen: first call -> pick, second call (after the empty-folder
        # alert loops back) -> Skip.
        calls = iter([1, 0])
        monkeypatch.setattr(
            "src.setup.onboarding_window.show_onboarding_screen",
            lambda **kw: next(calls),
        )
        monkeypatch.setattr(
            "src.ui.dialogs.choose_folder_dialog", lambda **kw: str(empty)
        )
        monkeypatch.setattr("rumps.alert", lambda *a, **kw: 1)

        assert wizard._show_import_notes() == "next"
        assert UserSettings.load().pending_import_dir is None

    def test_resume_stage_maps_import_notes(self, tmp_path, monkeypatch):
        config_file = tmp_path / "config.json"
        monkeypatch.setattr(
            UserSettings, "config_path", staticmethod(lambda: config_file)
        )
        settings = UserSettings(setup_stage="import_notes")
        settings.save()
        wizard = SetupWizard()
        assert wizard.current_step == WizardStep.IMPORT_NOTES

    def test_skip_clears_crash_resume_pick(self, tmp_path, monkeypatch):
        # Crash-resume: a folder persisted before the crash must NOT survive
        # an explicit Skip on the resumed step.
        config_file = tmp_path / "config.json"
        monkeypatch.setattr(
            UserSettings, "config_path", staticmethod(lambda: config_file)
        )
        UserSettings(
            setup_stage="import_notes", pending_import_dir=str(tmp_path)
        ).save()
        monkeypatch.setattr(
            "src.setup.onboarding_window._APPKIT_AVAILABLE", True, raising=False
        )
        monkeypatch.setattr(
            "src.setup.onboarding_window.show_onboarding_screen",
            lambda **kw: 0,  # Skip
        )
        wizard = SetupWizard()
        assert wizard._show_import_notes() == "next"
        assert UserSettings.load().pending_import_dir is None
