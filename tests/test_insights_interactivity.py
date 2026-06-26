"""User-scenario tests for the Insights window interactivity (ui-marked).

Drives the real click handlers headless and asserts the observable effect:
the right Obsidian deep-link callback fires, and dismiss shows feedback before
mutating the deck. The vault/Obsidian is never touched — callbacks are captured.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.ui import dashboard_window as dw
from src.ui import insight_model as im

pytestmark = pytest.mark.ui

if not dw._APPKIT_AVAILABLE:  # pragma: no cover - non-mac
    pytest.skip("AppKit unavailable", allow_module_level=True)


class _Sender:
    """Minimal stand-in for an NSButton sender exposing ``tag()``."""

    def __init__(self, tag):
        self._tag = tag

    def tag(self):
        return self._tag


def _ctrl(callbacks):
    ctrl = dw.build_dashboard_window(callbacks=callbacks)
    ctrl._ensure_window()  # runs _render → populates _note_basenames / _recent_paths
    return ctrl


def test_note_chip_click_opens_that_note(monkeypatch):
    opened = {}
    ctrl = _ctrl({"open_note": lambda name: opened.setdefault("name", name)})
    names = ctrl._note_basenames
    assert names, "sample deck should expose source notes"
    ctrl.noteClicked_(_Sender(0))
    assert opened["name"] == names[0]


def test_transcript_row_click_opens_that_transcript():
    opened = {}
    recents = [
        {"label": "A", "path": Path("/vault/A.md")},
        {"label": "B", "path": Path("/vault/B.md")},
    ]
    ctrl = _ctrl(
        {
            "recent_transcripts": lambda: recents,
            "open_transcript": lambda p: opened.setdefault("path", p),
        }
    )
    assert ctrl._recent_paths == [Path("/vault/A.md"), Path("/vault/B.md")]
    ctrl.transcriptClicked_(_Sender(1))
    assert opened["path"] == Path("/vault/B.md")


def test_unwired_callback_click_is_silent():
    """A click with no callback wired must not raise (best-effort handoff)."""
    ctrl = _ctrl({})
    ctrl.noteClicked_(_Sender(0))  # no open_note callback — should no-op
    ctrl.transcriptClicked_(_Sender(0))  # no rows / callback — should no-op


def test_dismiss_shows_feedback_then_advances():
    ctrl = _ctrl({})
    before = len(ctrl._deck._items)
    ctrl.dismissClicked_(None)
    assert len(ctrl._deck._items) == before  # flash showing, not yet mutated
    ctrl.afterDismissFlash_(None)
    assert len(ctrl._deck._items) == before - 1


def test_empty_deck_recent_transcripts_renders_without_rows():
    ctrl = dw.build_dashboard_window(
        deck=im.InsightDeck(), callbacks={"recent_transcripts": lambda: []}
    )
    ctrl._ensure_window()
    assert ctrl._recent_paths == []
