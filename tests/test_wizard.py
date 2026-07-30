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
        # Voice Memos needs Full Disk Access to see anything, so it follows the
        # permission step (asserted on its own in TestVoiceMemosStep).
        assert SetupWizard.STEPS_ORDER[4] == WizardStep.PERMISSIONS
        assert SetupWizard.STEPS_ORDER[5] == WizardStep.VOICE_MEMOS
        # Import step sits AFTER the key screen (the hook) and before FINISH.
        assert SetupWizard.STEPS_ORDER[-3] == WizardStep.AI_CONFIG
        assert SetupWizard.STEPS_ORDER[-2] == WizardStep.IMPORT_NOTES
        assert SetupWizard.STEPS_ORDER[-1] == WizardStep.FINISH
        assert len(SetupWizard.STEPS_ORDER) == 9

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
        # Derived, not hardcoded: this asserts persistence, so inserting a step
        # should not break it.
        wizard.current_step_index = SetupWizard.STEPS_ORDER.index(
            WizardStep.BASIC_CONFIG
        )
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


class TestVoiceMemosStep:
    """Krok VOICE_MEMOS — offer the iPhone source, once, without nagging later."""

    def _wizard(self, tmp_path, monkeypatch, **settings_fields):
        config_file = tmp_path / "config.json"
        monkeypatch.setattr(
            UserSettings, "config_path", staticmethod(lambda: config_file)
        )
        if settings_fields:
            UserSettings(**settings_fields).save()
        monkeypatch.setattr(
            "src.setup.onboarding_window._APPKIT_AVAILABLE", True, raising=False
        )
        return SetupWizard()

    def _answer(self, monkeypatch, response, captured=None):
        def _screen(**kwargs):
            if captured is not None:
                captured.update(kwargs)
            return response

        monkeypatch.setattr(
            "src.setup.onboarding_window.show_onboarding_screen", _screen
        )

    def test_turn_on_enables_and_stamps_consent(self, tmp_path, monkeypatch):
        wizard = self._wizard(tmp_path, monkeypatch)
        self._answer(monkeypatch, 1)
        stamped = []
        monkeypatch.setattr(
            SetupWizard,
            "_stamp_voice_memos_consent",
            staticmethod(lambda: stamped.append(True)),
        )

        assert wizard._show_voice_memos() == "next"

        saved = UserSettings.load()
        assert saved.voice_memos_enabled is True
        # Answering here IS answering the offer — the menu prompt must not
        # ask again 20 seconds after setup.
        assert saved.voice_memos_proposal_shown is True
        # Consent moves the start marker, so the archive stays opt-in.
        assert stamped == [True]

    def test_skip_records_the_answer_without_enabling(self, tmp_path, monkeypatch):
        wizard = self._wizard(tmp_path, monkeypatch)
        self._answer(monkeypatch, 0)

        assert wizard._show_voice_memos() == "next"

        saved = UserSettings.load()
        assert saved.voice_memos_enabled is False
        assert saved.voice_memos_proposal_shown is True

    def test_cancel_aborts_the_wizard(self, tmp_path, monkeypatch):
        wizard = self._wizard(tmp_path, monkeypatch)
        self._answer(monkeypatch, -1)

        assert wizard._show_voice_memos() == "cancel"
        assert UserSettings.load().voice_memos_proposal_shown is False

    def test_already_enabled_skips_the_screen(self, tmp_path, monkeypatch):
        # Wizard re-runs on a major upgrade; do not re-ask a settled question.
        wizard = self._wizard(tmp_path, monkeypatch, voice_memos_enabled=True)
        shown = []
        monkeypatch.setattr(
            "src.setup.onboarding_window.show_onboarding_screen",
            lambda **kw: shown.append(kw) or 1,
        )

        assert wizard._show_voice_memos() == "next"
        assert shown == []

    def test_body_reports_how_many_memos_are_waiting(self, tmp_path, monkeypatch):
        wizard = self._wizard(tmp_path, monkeypatch)
        monkeypatch.setattr(SetupWizard, "_count_voice_memos", staticmethod(lambda: 7))
        captured: dict = {}
        self._answer(monkeypatch, 0, captured)

        wizard._show_voice_memos()

        assert "7" in captured["body"]

    def test_body_explains_icloud_setup_when_nothing_is_visible(
        self, tmp_path, monkeypatch
    ):
        wizard = self._wizard(tmp_path, monkeypatch)
        monkeypatch.setattr(SetupWizard, "_count_voice_memos", staticmethod(lambda: 0))
        captured: dict = {}
        self._answer(monkeypatch, 0, captured)

        wizard._show_voice_memos()

        # An empty folder means iCloud is not set up — say how to fix it
        # instead of implying the feature is broken.
        assert "iCloud" in captured["body"]

    def test_alert_fallback_can_turn_it_on(self, tmp_path, monkeypatch):
        """No AppKit: the source must still be offered, not silently dropped."""
        wizard = self._wizard(tmp_path, monkeypatch)
        monkeypatch.setattr(
            "src.setup.onboarding_window.show_onboarding_screen", lambda **kw: None
        )
        monkeypatch.setattr("rumps.alert", lambda *a, **kw: 1)
        monkeypatch.setattr(
            SetupWizard, "_stamp_voice_memos_consent", staticmethod(lambda: None)
        )

        assert wizard._show_voice_memos() == "next"
        assert UserSettings.load().voice_memos_enabled is True

    def _point_at(self, monkeypatch, folder):
        from src.config import config

        monkeypatch.setattr(
            type(config), "VOICE_MEMOS_RECORDINGS_DIR", folder, raising=False
        )

    def test_missing_folder_counts_as_zero(self, tmp_path, monkeypatch):
        self._point_at(monkeypatch, tmp_path / "not-created-by-icloud-yet")

        assert SetupWizard._count_voice_memos() == 0

    def test_denied_folder_is_unknown_not_empty(self, tmp_path, monkeypatch):
        # A permission gate and an unconfigured iCloud need OPPOSITE advice;
        # glob would have swallowed the error and reported an empty folder.
        denied = tmp_path / "denied"
        denied.mkdir()
        (denied / "20260730 100258-AAAAAAAA.m4a").touch()
        denied.chmod(0o000)
        self._point_at(monkeypatch, denied)
        try:
            assert SetupWizard._count_voice_memos() is None
        finally:
            denied.chmod(0o755)

    def test_denied_folder_body_blames_permissions_not_icloud(
        self, tmp_path, monkeypatch
    ):
        wizard = self._wizard(tmp_path, monkeypatch)
        monkeypatch.setattr(
            SetupWizard, "_count_voice_memos", staticmethod(lambda: None)
        )
        captured: dict = {}
        self._answer(monkeypatch, 0, captured)

        wizard._show_voice_memos()

        assert "Full Disk Access" in captured["body"]
        assert "iCloud" not in captured["body"]

    def test_step_runs_after_the_permission_step(self):
        # Reading another app's container needs Full Disk Access, and that step
        # ends with an app restart: asked earlier, the count is always wrong.
        order = SetupWizard.STEPS_ORDER
        assert order.index(WizardStep.VOICE_MEMOS) > order.index(WizardStep.PERMISSIONS)

    def test_resume_stage_maps_voice_memos(self, tmp_path, monkeypatch):
        config_file = tmp_path / "config.json"
        monkeypatch.setattr(
            UserSettings, "config_path", staticmethod(lambda: config_file)
        )
        UserSettings(setup_stage="voice_memos").save()

        assert SetupWizard().current_step == WizardStep.VOICE_MEMOS

    def test_stamping_consent_never_breaks_setup(self, monkeypatch):
        """A failed marker must not abort the wizard — the daemon repairs it."""
        monkeypatch.setattr(
            "src.voice_memos.VoiceMemosConnector",
            lambda *a, **kw: (_ for _ in ()).throw(OSError("disk full")),
        )
        SetupWizard._stamp_voice_memos_consent()  # must not raise

    def test_alert_fallback_blames_permissions_not_icloud(self, tmp_path, monkeypatch):
        """The no-AppKit path must not send a blocked user to iCloud either."""
        captured: dict = {}
        monkeypatch.setattr(
            "rumps.alert",
            lambda **kw: captured.update(kw) or 1,
        )

        SetupWizard._voice_memos_alert_fallback(None)

        assert "Full Disk Access" in captured["message"]
        assert "iCloud" not in captured["message"]

    def test_alert_fallback_reports_the_count(self, monkeypatch):
        captured: dict = {}
        monkeypatch.setattr("rumps.alert", lambda **kw: captured.update(kw) or 1)

        SetupWizard._voice_memos_alert_fallback(12)

        assert "12" in captured["message"]


class TestWizardRerunOnUpgrade:
    """An upgrade re-run must actually walk the user through the steps."""

    def _settings_on_disk(self, tmp_path, monkeypatch, **fields):
        config_file = tmp_path / "config.json"
        monkeypatch.setattr(
            UserSettings, "config_path", staticmethod(lambda: config_file)
        )
        UserSettings(**fields).save()

    def test_completed_setup_restarts_from_the_beginning(self, tmp_path, monkeypatch):
        # Otherwise the saved "finish" stage drops the user on the closing
        # screen and every new step (Voice Memos) reaches nobody who already
        # had the app installed.
        self._settings_on_disk(
            tmp_path,
            monkeypatch,
            setup_completed=True,
            setup_version="1.9.0",
            setup_stage="finish",
        )

        assert SetupWizard.needs_setup() is True
        assert SetupWizard().current_step == WizardStep.WELCOME

    def test_an_interrupted_run_still_resumes(self, tmp_path, monkeypatch):
        # A crash mid-wizard must not send the user back to square one.
        self._settings_on_disk(
            tmp_path, monkeypatch, setup_completed=False, setup_stage="permissions"
        )

        assert SetupWizard().current_step == WizardStep.PERMISSIONS


class TestRerunPreservesConfiguration:
    """A version-bump re-run walks a CONFIGURED install — it must not reset it."""

    def _wizard(self, tmp_path, monkeypatch, **fields):
        config_file = tmp_path / "config.json"
        monkeypatch.setattr(
            UserSettings, "config_path", staticmethod(lambda: config_file)
        )
        UserSettings(**fields).save()
        monkeypatch.setattr(
            "src.setup.onboarding_window._APPKIT_AVAILABLE", True, raising=False
        )
        return SetupWizard()

    def test_skipping_the_key_screen_keeps_a_stored_key(self, tmp_path, monkeypatch):
        # Turning Insights off during an upgrade, silently, would remove the
        # very thing H1 measures.
        wizard = self._wizard(
            tmp_path, monkeypatch, ai_api_key="sk-ant-STORED", enable_ai_summaries=True
        )
        monkeypatch.setattr(
            "src.setup.onboarding_window.show_onboarding_screen", lambda **kw: 0
        )

        assert wizard._show_ai_config() == "next"
        assert wizard.settings.enable_ai_summaries is True
        assert wizard.settings.ai_api_key == "sk-ant-STORED"

    def test_skipping_without_a_key_still_disables_ai(self, tmp_path, monkeypatch):
        wizard = self._wizard(tmp_path, monkeypatch)
        monkeypatch.setattr(
            "src.setup.onboarding_window.show_onboarding_screen", lambda **kw: 0
        )

        assert wizard._show_ai_config() == "next"
        assert wizard.settings.enable_ai_summaries is False

    def test_legacy_path_also_keeps_a_stored_key(self, tmp_path, monkeypatch):
        wizard = self._wizard(
            tmp_path, monkeypatch, ai_api_key="sk-ant-STORED", enable_ai_summaries=True
        )
        monkeypatch.setattr("rumps.alert", lambda **kw: 1)  # Skip

        assert wizard._ai_config_legacy() == "next"
        assert wizard.settings.enable_ai_summaries is True

    def test_ask_on_new_disk_keeps_legacy_disk_names(self, tmp_path, monkeypatch):
        wizard = self._wizard(
            tmp_path,
            monkeypatch,
            watch_mode="specific",
            watched_volumes=["LS-P1", "ZOOM-H6"],
        )
        monkeypatch.setattr(
            "src.setup.onboarding_window.show_onboarding_screen", lambda **kw: 1
        )

        assert wizard._show_source_config() == "next"
        assert wizard.settings.watch_mode == "manual"
        assert wizard.settings.watched_volumes == ["LS-P1", "ZOOM-H6"]

    def test_fresh_install_starts_with_no_disk_names(self, tmp_path, monkeypatch):
        wizard = self._wizard(tmp_path, monkeypatch)
        monkeypatch.setattr(
            "src.setup.onboarding_window.show_onboarding_screen", lambda **kw: 1
        )

        assert wizard._show_source_config() == "next"
        assert wizard.settings.watched_volumes == []

    def test_disk_name_prompt_is_prefilled_with_the_real_list(
        self, tmp_path, monkeypatch
    ):
        # The old hardcoded "LS-P1" looked like a valid answer, so confirming
        # the screen swapped the user's disks for one they may not own.
        wizard = self._wizard(
            tmp_path,
            monkeypatch,
            watch_mode="specific",
            watched_volumes=["ZOOM-H6", "DR-05"],
        )
        captured: dict = {}

        class _Result:
            clicked = 1
            text = "ZOOM-H6, DR-05"

        class _Window:
            def __init__(self, **kwargs):
                captured.update(kwargs)

            def run(self):
                return _Result()

        monkeypatch.setattr("rumps.Window", _Window)

        assert wizard._prompt_specific_disks() == "next"
        assert captured["default_text"] == "ZOOM-H6, DR-05"
        assert wizard.settings.watched_volumes == ["ZOOM-H6", "DR-05"]

    def test_disk_name_prompt_is_empty_on_a_fresh_install(self, tmp_path, monkeypatch):
        wizard = self._wizard(tmp_path, monkeypatch)
        captured: dict = {}

        class _Result:
            clicked = 0
            text = ""

        class _Window:
            def __init__(self, **kwargs):
                captured.update(kwargs)

            def run(self):
                return _Result()

        monkeypatch.setattr("rumps.Window", _Window)

        wizard._prompt_specific_disks()
        assert captured["default_text"] == ""


class TestFullRerunOnAConfiguredInstall:
    """Capstone: walk EVERY step of a re-run and assert nothing is lost.

    Three review rounds found the same class of defect — the re-run treating a
    configured install as blank — in three different steps. This locks the
    whole family instead of one screen at a time.
    """

    CONFIGURED = dict(
        setup_completed=True,
        setup_version="1.9.0",
        setup_stage="finish",
        language="pl",
        whisper_model="medium",
        ai_api_key="sk-ant-STORED",
        enable_ai_summaries=True,
        watch_mode="specific",
        watched_volumes=["ZOOM-H6", "DR-05"],
        voice_memos_enabled=True,
        tester_mode=True,
    )

    def test_default_answers_preserve_every_setting(self, tmp_path, monkeypatch):
        config_file = tmp_path / "config.json"
        monkeypatch.setattr(
            UserSettings, "config_path", staticmethod(lambda: config_file)
        )
        vault = tmp_path / "vault"
        vault.mkdir()
        UserSettings(output_dir=vault, **self.CONFIGURED).save()
        monkeypatch.setattr(
            "src.setup.onboarding_window._APPKIT_AVAILABLE", True, raising=False
        )

        # Every screen answered with its primary button — the click-through a
        # user in a hurry actually performs. The stub builds the accessory
        # first, exactly as the real window does, so the popups' pre-selection
        # is part of what this test covers rather than something it skips.
        def _screen(**kwargs):
            builder = kwargs.get("accessory")
            if builder is not None:
                builder(444.0, None)
            return 1

        monkeypatch.setattr(
            "src.setup.onboarding_window.show_onboarding_screen", _screen
        )
        monkeypatch.setattr("rumps.alert", lambda *a, **kw: 1)

        wizard = SetupWizard()
        assert wizard.current_step == WizardStep.WELCOME  # a re-run starts over

        wizard._show_source_config()
        wizard._show_basic_config()
        wizard._show_voice_memos()
        wizard._show_ai_config()
        wizard.settings.save()

        saved = UserSettings.load()
        assert saved.ai_api_key == "sk-ant-STORED"
        assert saved.enable_ai_summaries is True
        assert saved.watched_volumes == ["ZOOM-H6", "DR-05"]
        assert saved.output_dir == vault
        assert saved.language == "pl"
        assert saved.whisper_model == "medium"
        assert saved.voice_memos_enabled is True
        # The tester build's instrumentation flag is not the wizard's business.
        assert saved.tester_mode is True
