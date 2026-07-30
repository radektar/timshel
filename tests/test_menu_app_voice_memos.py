"""Tests for the Voice Memos offer in the menu app.

No AppKit needed: _run_on_main_thread is monkeypatched and rumps.alert stubbed,
following tests/test_menu_app_volume_prompt.py.
"""

from unittest.mock import MagicMock

from src.config.settings import UserSettings
from src.menu_app import TimshelMenuApp


def _make_app():
    """Bare instance — the offer method needs no initialized state."""
    return TimshelMenuApp.__new__(TimshelMenuApp)


def _settings_on_disk(monkeypatch, tmp_path, **fields):
    monkeypatch.setattr(
        UserSettings, "config_path", staticmethod(lambda: tmp_path / "config.json")
    )
    settings = UserSettings(setup_completed=True, **fields)
    settings.save()
    return settings


def test_offer_keeps_retrying_while_the_daemon_starts(monkeypatch, tmp_path):
    """A slow launch must not cost the user the offer for the whole session."""
    _settings_on_disk(monkeypatch, tmp_path)
    monkeypatch.setattr("src.menu_app._run_on_main_thread", lambda fn: fn())

    app = _make_app()
    app.transcriber = None  # daemon still starting: no connector yet
    timer = MagicMock()

    app._maybe_offer_voice_memos(timer)

    timer.stop.assert_not_called()


def test_offer_gives_up_after_a_bounded_number_of_tries(monkeypatch, tmp_path):
    """A user with no memos is not polled for the lifetime of the app."""
    _settings_on_disk(monkeypatch, tmp_path)
    monkeypatch.setattr("src.menu_app._run_on_main_thread", lambda fn: fn())

    app = _make_app()
    app.transcriber = None
    timer = MagicMock()

    for _ in range(TimshelMenuApp._VOICE_MEMOS_OFFER_ATTEMPTS):
        app._maybe_offer_voice_memos(timer)

    timer.stop.assert_called()


def test_offer_stops_once_already_answered(monkeypatch, tmp_path):
    _settings_on_disk(monkeypatch, tmp_path, voice_memos_proposal_shown=True)
    monkeypatch.setattr("src.menu_app._run_on_main_thread", lambda fn: fn())

    app = _make_app()
    app.transcriber = MagicMock()
    timer = MagicMock()

    app._maybe_offer_voice_memos(timer)

    timer.stop.assert_called_once()


def test_accepting_the_offer_stamps_consent(monkeypatch, tmp_path):
    _settings_on_disk(monkeypatch, tmp_path)
    monkeypatch.setattr("src.menu_app._run_on_main_thread", lambda fn: fn())
    monkeypatch.setattr("src.menu_app.rumps.alert", lambda *a, **k: 1)

    connector = MagicMock()
    connector.has_any_recordings.return_value = True
    app = _make_app()
    app.transcriber = MagicMock(voice_memos=connector)

    app._maybe_offer_voice_memos(MagicMock())

    # consented=True: the mark moves to now, so an off period stays back
    # catalogue instead of being imported the moment the user says yes.
    assert connector.enable.call_args.kwargs == {"consented": True}
    assert UserSettings.load().voice_memos_enabled is True


class TestBackfillKeepsTheDigestCheap:
    """The archive dialog promises local transcription — not a paid digest."""

    def _run(self, monkeypatch, tmp_path, memo_count=10):
        from src.voice_memos import ImportStats

        scheduler = MagicMock()
        monkeypatch.setattr(
            "src.connections.scheduler.get_scheduler", lambda: scheduler
        )
        monkeypatch.setattr("src.menu_app.send_notification", lambda *a, **k: None)
        monkeypatch.setattr(
            "src.voice_memos.process_voice_memos",
            lambda *a, **k: ImportStats(imported=memo_count),
        )

        app = _make_app()
        app.transcriber = MagicMock(voice_memos=MagicMock())
        app._run_voice_memos_backfill([MagicMock() for _ in range(memo_count)])
        return scheduler

    def test_counter_is_clamped_so_no_paid_run_is_triggered(
        self, monkeypatch, tmp_path
    ):
        scheduler = self._run(monkeypatch, tmp_path)

        # Without this, N imported memos push new_notes past
        # CONNECTIONS_PATTERN_TRIGGER_MIN and the next tick pays for Opus.
        assert scheduler.settle_after_import.called

    def test_the_hold_is_taken_and_released(self, monkeypatch, tmp_path):
        scheduler = self._run(monkeypatch, tmp_path)

        scheduler.suspend_auto_digest.assert_called_once()
        scheduler.resume_auto_digest.assert_called_once()

    def test_the_counter_is_settled_before_the_hold_is_released(
        self, monkeypatch, tmp_path
    ):
        scheduler = self._run(monkeypatch, tmp_path)

        order = [c[0] for c in scheduler.method_calls]
        # A tick can fire the instant the hold drops; it must already see a
        # clamped counter.
        assert order.index("settle_after_import") < order.index("resume_auto_digest")

    def test_the_in_flight_flag_is_cleared_when_done(self, monkeypatch, tmp_path):
        from src.voice_memos import ImportStats

        scheduler = MagicMock()
        monkeypatch.setattr(
            "src.connections.scheduler.get_scheduler", lambda: scheduler
        )
        monkeypatch.setattr("src.menu_app.send_notification", lambda *a, **k: None)
        monkeypatch.setattr(
            "src.voice_memos.process_voice_memos",
            lambda *a, **k: ImportStats(imported=1),
        )

        app = _make_app()
        app.transcriber = MagicMock(voice_memos=MagicMock())
        app._voice_memos_backfill_running = True
        app._run_voice_memos_backfill([MagicMock()])

        # A stuck flag would lock the user out of the archive until a restart.
        assert app._voice_memos_backfill_running is False

    def test_a_crashing_import_still_releases_the_hold(self, monkeypatch, tmp_path):
        scheduler = MagicMock()
        monkeypatch.setattr(
            "src.connections.scheduler.get_scheduler", lambda: scheduler
        )
        monkeypatch.setattr("src.menu_app.send_notification", lambda *a, **k: None)
        monkeypatch.setattr(
            "src.voice_memos.process_voice_memos",
            MagicMock(side_effect=RuntimeError("whisper exploded")),
        )

        app = _make_app()
        app.transcriber = MagicMock(voice_memos=MagicMock())

        try:
            app._run_voice_memos_backfill([MagicMock()])
        except RuntimeError:
            pass

        # A frozen hold would silently stop weekly digests for everyone.
        scheduler.resume_auto_digest.assert_called_once()


def test_declining_the_offer_is_remembered(monkeypatch, tmp_path):
    _settings_on_disk(monkeypatch, tmp_path)
    monkeypatch.setattr("src.menu_app._run_on_main_thread", lambda fn: fn())
    monkeypatch.setattr("src.menu_app.rumps.alert", lambda *a, **k: -1)

    connector = MagicMock()
    connector.has_any_recordings.return_value = True
    app = _make_app()
    app.transcriber = MagicMock(voice_memos=connector)

    app._maybe_offer_voice_memos(MagicMock())

    saved = UserSettings.load()
    assert saved.voice_memos_proposal_shown is True
    assert saved.voice_memos_enabled is False
    connector.enable.assert_not_called()
