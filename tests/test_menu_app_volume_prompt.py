"""Tests for the unknown-volume prompt flow in the menu app.

Covers the timeout contract: an unanswered Tak/Nie/Raz dialog must NOT
persist anything (DECISION_NONE), and an answer clicked AFTER the timeout
is recorded via _record_late_decision instead of mutating a dead dict.

No AppKit needed: _run_on_main_thread is monkeypatched to capture the
dialog closure, and rumps.alert is stubbed.
"""

from pathlib import Path

from src.config.settings import UserSettings
from src.file_monitor import DECISION_NONE
from src.menu_app import MalincheMenuApp


def _make_app():
    """Bare instance — the prompt method needs no initialized state."""
    return MalincheMenuApp.__new__(MalincheMenuApp)


def test_prompt_timeout_returns_none_decision(monkeypatch):
    """An unanswered dialog times out to DECISION_NONE — never 'blocked'."""
    captured = {}
    monkeypatch.setattr(
        "src.menu_app._run_on_main_thread",
        lambda fn: captured.setdefault("closure", fn),  # captured, NOT run
    )

    app = _make_app()
    decision = app._prompt_unknown_volume(
        Path("/Volumes/SD_CARD"), "UUID-SD", timeout=0.05
    )

    assert decision == DECISION_NONE
    assert "closure" in captured  # dialog was scheduled, just never answered


def test_late_answer_is_recorded(monkeypatch, tmp_path):
    """A 'Yes' clicked after the timeout must still be persisted."""
    config_file = tmp_path / "config.json"
    monkeypatch.setattr(
        UserSettings, "config_path", staticmethod(lambda: config_file)
    )

    captured = {}
    monkeypatch.setattr(
        "src.menu_app._run_on_main_thread",
        lambda fn: captured.setdefault("closure", fn),
    )
    monkeypatch.setattr("src.menu_app.rumps.alert", lambda **kwargs: 1)  # "Yes"

    app = _make_app()
    decision = app._prompt_unknown_volume(
        Path("/Volumes/SD_CARD"), "UUID-LATE", timeout=0.05
    )
    assert decision == DECISION_NONE  # monitor thread already gave up

    captured["closure"]()  # user clicks "Yes" in the still-visible dialog

    entry = UserSettings.load().find_trusted_volume("UUID-LATE")
    assert entry is not None and entry.decision == "trusted"


def test_answer_before_timeout_returned_not_late_recorded(monkeypatch, tmp_path):
    """The normal path: dialog answered in time → decision returned inline,
    _record_late_decision not involved."""
    config_file = tmp_path / "config.json"
    monkeypatch.setattr(
        UserSettings, "config_path", staticmethod(lambda: config_file)
    )

    # Run the closure IMMEDIATELY (as the main thread would).
    monkeypatch.setattr("src.menu_app._run_on_main_thread", lambda fn: fn())
    monkeypatch.setattr("src.menu_app.rumps.alert", lambda **kwargs: 1)  # "Yes"

    app = _make_app()
    decision = app._prompt_unknown_volume(
        Path("/Volumes/SD_CARD"), "UUID-FAST", timeout=5
    )

    assert decision == "trusted"
    # Persisting the in-time answer belongs to FileMonitor._authorize_volume,
    # not to the prompt: nothing should have been written here.
    assert UserSettings.load().find_trusted_volume("UUID-FAST") is None


def test_dialog_exception_returns_none_decision(monkeypatch):
    """A UI failure must not permanently block a disk: DECISION_NONE."""

    def boom(**kwargs):
        raise RuntimeError("no display")

    monkeypatch.setattr("src.menu_app._run_on_main_thread", lambda fn: fn())
    monkeypatch.setattr("src.menu_app.rumps.alert", boom)

    app = _make_app()
    decision = app._prompt_unknown_volume(
        Path("/Volumes/SD_CARD"), "UUID-ERR", timeout=5
    )

    assert decision == DECISION_NONE
