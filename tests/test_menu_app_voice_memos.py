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
