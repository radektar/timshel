"""User-scenario tests for the validation signal — driving the *real*
Zachowaj/Odrzuć handlers headless (AppKit, ui-marked).

Each test acts as the user (clicks a handler) and asserts the observable
artifact: a line in the signal log. The signal path is redirected to a temp
file so no real vault is touched.
"""

from __future__ import annotations

import json

import pytest

from src.connections import validation_signal as vsig
from src.ui import dashboard_window as dw
from src.ui import insight_model as im

pytestmark = pytest.mark.ui

if not dw._APPKIT_AVAILABLE:  # pragma: no cover - non-mac
    pytest.skip("AppKit unavailable", allow_module_level=True)


@pytest.fixture
def log_path(tmp_path, monkeypatch):
    """Redirect the signal log to a temp file for the duration of a test."""
    p = tmp_path / "signal.jsonl"
    monkeypatch.setattr(vsig, "signal_log_path", lambda: p)
    return p


def _rows(path):
    if not path.exists():
        return []
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines()]


def _ctrl():
    ctrl = dw.build_dashboard_window()
    ctrl._ensure_window()
    return ctrl


def test_us1_user_keeps_an_insight(log_path):
    ctrl = _ctrl()
    active = ctrl._deck.active()
    ctrl.keepClicked_(None)  # commits at click (17.07: no deferred flash)
    rows = _rows(log_path)
    assert len(rows) == 1
    # Zachowaj is the quiet archive — a save signal, kind:none (ADR-004).
    assert rows[0]["action"] == "action_taken"
    assert rows[0]["target"] == "save"
    assert rows[0]["kind"] == "none"
    assert rows[0]["conn_type"] == active.synthesis_type
    assert rows[0]["sig"]
    assert ctrl._deck.is_kept(0)  # the keep committed


def test_us2_user_dismisses_an_insight(log_path):
    ctrl = _ctrl()
    active = ctrl._deck.active()  # captured before the retag
    before = len(ctrl._deck._items)
    dismissed_before = ctrl._deck.counts()["dismissed"]
    ctrl.dismissClicked_(None)
    rows = _rows(log_path)
    assert len(rows) == 1
    # Odrzuć is a signal, not a suppressor: kind:none / target:none.
    assert rows[0]["action"] == "action_taken"
    assert rows[0]["target"] == "none"
    assert rows[0]["conn_type"] == active.synthesis_type
    # Nothing is deleted — Odrzuć is reversible (the Dismissed view recovers it).
    assert len(ctrl._deck._items) == before
    assert ctrl._deck.counts()["dismissed"] == dismissed_before + 1


def test_us3_user_triages_a_session(log_path):
    """Keep → Keep → Dismiss across the queue: 3 appended lines, right order."""
    ctrl = _ctrl()
    ctrl.keepClicked_(None)
    ctrl.keepClicked_(None)
    ctrl.dismissClicked_(None)
    targets = [r["target"] for r in _rows(log_path)]
    assert targets == ["save", "save", "none"]


def test_us6_keep_records_and_commits_at_click(log_path):
    """US-6 (17.07): no deferred timer — the signal line AND the retag both
    land at click, so closing the window right after loses nothing."""
    ctrl = _ctrl()
    active_index = ctrl._deck.active_index
    ctrl.keepClicked_(None)
    rows = _rows(log_path)
    assert len(rows) == 1
    assert rows[0]["action"] == "action_taken"
    assert ctrl._deck.is_kept(active_index)


def test_us7_empty_deck_records_nothing(log_path):
    ctrl = dw.build_dashboard_window(deck=im.InsightDeck())
    ctrl._ensure_window()
    ctrl.keepClicked_(None)
    ctrl.dismissClicked_(None)
    assert _rows(log_path) == []
