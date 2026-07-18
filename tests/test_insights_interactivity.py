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
    # Pin the FALLBACK contract deterministically: when the basename does not
    # resolve to a vault file, the chip click must fire the open_note callback.
    # (Without the patch the outcome would depend on the machine's real vault —
    # the in-app-resolution path is covered in test_note_reader_window.)
    monkeypatch.setattr(dw.obsidian_link, "resolve_note_path", lambda n, v: None)
    opened = {}
    ctrl = _ctrl({"open_note": lambda name: opened.setdefault("name", name)})
    names = ctrl._note_basenames
    assert names, "sample deck should expose source notes"
    ctrl.noteClicked_(_Sender(0))
    assert opened["name"] == names[0]


def test_recent_transcripts_section_is_cut():
    """The 'Ostatnie transkrypty' rail section was cut in the redesign — no rows
    are built regardless of the callback, so _recent_paths stays empty and the
    (kept, no-op) handler never opens anything."""
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
    assert ctrl._recent_paths == []
    ctrl.transcriptClicked_(_Sender(1))  # no rows → no-op
    assert "path" not in opened


def test_unwired_callback_click_is_silent():
    """A click with no callback wired must not raise (best-effort handoff)."""
    ctrl = _ctrl({})
    ctrl.noteClicked_(_Sender(0))  # no open_note callback — should no-op
    ctrl.transcriptClicked_(_Sender(0))  # no rows / callback — should no-op


def test_dismiss_commits_at_click():
    ctrl = _ctrl({})
    before = len(ctrl._deck._items)
    dismissed_before = ctrl._deck.counts()["dismissed"]
    ctrl.dismissClicked_(None)  # 17.07: commits at click, toast carries Cofnij
    # Odrzuć is reversible now: nothing deleted, the item just moves to Dismissed.
    assert len(ctrl._deck._items) == before
    assert ctrl._deck.counts()["dismissed"] == dismissed_before + 1


def test_empty_deck_recent_transcripts_renders_without_rows():
    ctrl = dw.build_dashboard_window(
        deck=im.InsightDeck(), callbacks={"recent_transcripts": lambda: []}
    )
    ctrl._ensure_window()
    assert ctrl._recent_paths == []
