"""Smoke tests for the Insights dashboard window (AppKit, ui-marked)."""

from __future__ import annotations

import pytest

from src.ui import dashboard_window as dw
from src.ui import insight_model as im

pytestmark = pytest.mark.ui

if not dw._APPKIT_AVAILABLE:  # pragma: no cover - non-mac
    pytest.skip("AppKit unavailable", allow_module_level=True)

from AppKit import NSImage  # noqa: E402
from Foundation import NSMakeSize  # noqa: E402


def _render(ctrl):
    ctrl._ensure_window()
    cv = ctrl._window.contentView()
    img = NSImage.alloc().initWithSize_(NSMakeSize(860, 560))
    img.lockFocus()
    try:
        cv.displayRectIgnoringOpacity_(cv.bounds())
    finally:
        img.unlockFocus()


def test_builds_with_sample_deck():
    ctrl = dw.build_dashboard_window()
    assert ctrl is not None
    _render(ctrl)
    assert ctrl._window.title() == "Malinche — Konstelacja"


def test_navigation_and_triage_render():
    ctrl = dw.build_dashboard_window()
    ctrl._ensure_window()
    ctrl._deck.select(2)
    ctrl._render()
    ctrl._deck.keep()
    ctrl._render()
    ctrl._deck.dismiss()
    ctrl._render()
    _render(ctrl)  # final paint must not raise


def test_empty_state_renders():
    ctrl = dw.build_dashboard_window(deck=im.InsightDeck())
    assert ctrl is not None
    _render(ctrl)
    assert ctrl._deck.is_empty


def test_update_deck_refreshes():
    ctrl = dw.build_dashboard_window()
    ctrl._ensure_window()
    ctrl.updateDeck_(im.InsightDeck())
    assert ctrl._deck.is_empty
    _render(ctrl)


def test_hex_helper():
    col = dw._hex("#C24010")
    assert col is not None
    # malformed falls back rather than raising
    assert dw._hex("nope") is not None


def test_keep_flash_shows_then_advances():
    ctrl = dw.build_dashboard_window()
    ctrl._ensure_window()
    before = ctrl._deck.active_index
    assert ctrl._show_keep_flash() is True
    _render(ctrl)  # the overlay must paint without raising
    # the timer callback keeps the active connection and advances
    ctrl.afterKeepFlash_(None)
    assert ctrl._deck.is_kept(before)
    assert ctrl._deck.active_index != before


def test_keep_flash_noop_without_window():
    ctrl = dw.build_dashboard_window()
    # no _ensure_window() → no window yet
    assert ctrl._show_keep_flash() is False


def test_skeleton_renders_when_transcribing_and_empty():
    ctrl = dw.build_dashboard_window(deck=im.InsightDeck())
    ctrl._ensure_window()
    ctrl._transcribing = True
    ctrl._render()
    _render(ctrl)  # skeleton must paint without raising


def test_set_transcribing_toggles_flag():
    ctrl = dw.build_dashboard_window()
    assert ctrl._transcribing is False
    ctrl.setTranscribing_(True)
    assert ctrl._transcribing is True
    ctrl.setTranscribing_(False)
    assert ctrl._transcribing is False
