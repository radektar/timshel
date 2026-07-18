"""In-app note reader — window-side behavior (ui-marked, AppKit)."""

from __future__ import annotations

import types

import pytest

from src.ui import dashboard_window as dw

pytestmark = pytest.mark.ui

if not dw._APPKIT_AVAILABLE:  # pragma: no cover - non-mac
    pytest.skip("AppKit unavailable", allow_module_level=True)


def _note(tmp_path, name="2026-07-18 - Rozmowa z Heliosem", body=None):
    p = tmp_path / f"{name}.md"
    p.write_text(
        '---\ntitle: "Rozmowa z Heliosem"\ndate: 2026-07-18\n---\n\n'
        + (body or "Podsumowanie.\n\n## Transkrypcja\n\nZapis rozmowy.\n"),
        encoding="utf-8",
    )
    return p


def _fake_sender(tag):
    return types.SimpleNamespace(tag=lambda: tag)


def test_notes_row_opens_inapp_reader(tmp_path):
    ctrl = dw.build_dashboard_window()
    ctrl._ensure_window()
    path = _note(tmp_path)
    ctrl._notes_rows = [{"label": "Rozmowa z Heliosem", "path": path}]
    ctrl.notesRowClicked_(_fake_sender(0))
    assert ctrl._mode == "note"
    assert ctrl._note_path == path
    assert "Rozmowa z Heliosem" in ctrl._note_html
    assert ctrl._webview is not None


def test_back_returns_to_previous_mode(tmp_path):
    ctrl = dw.build_dashboard_window()
    ctrl._ensure_window()
    ctrl._mode = "insight"
    ctrl._open_note_in_reader(_note(tmp_path))
    assert ctrl._mode == "note"
    ctrl.noteBackClicked_(None)
    assert ctrl._mode == "insight"
    assert ctrl._note_path is None


def test_wikilink_breadcrumb_pops_before_exiting(tmp_path):
    ctrl = dw.build_dashboard_window()
    ctrl._ensure_window()
    a = _note(tmp_path, name="A")
    b = _note(tmp_path, name="B")
    ctrl._open_note_in_reader(a)
    ctrl._open_note_in_reader(b)  # simulates wikilink hop
    assert ctrl._note_stack == [a]
    ctrl.noteBackClicked_(None)
    assert ctrl._mode == "note" and ctrl._note_path == a
    ctrl.noteBackClicked_(None)
    assert ctrl._mode == "insight"


def test_rail_row_click_is_fresh_entry_not_breadcrumb_hop(tmp_path):
    # Clicking Notatki rows while reading must not grow the back stack —
    # „← Wróć" exits in ONE press regardless of how many rows were visited.
    ctrl = dw.build_dashboard_window()
    ctrl._ensure_window()
    rows = [{"label": n, "path": _note(tmp_path, name=n)} for n in ("A", "B", "C")]
    for i in range(3):
        ctrl._notes_rows = rows  # _render refreshes the rail; re-pin each click
        ctrl.notesRowClicked_(_fake_sender(i))
    assert ctrl._mode == "note" and ctrl._note_path == rows[2]["path"]
    assert ctrl._note_stack == []
    ctrl.noteBackClicked_(None)
    assert ctrl._mode == "insight"


def test_back_skips_notes_deleted_from_disk(tmp_path):
    ctrl = dw.build_dashboard_window()
    ctrl._ensure_window()
    a = _note(tmp_path, name="A")
    b = _note(tmp_path, name="B")
    c = _note(tmp_path, name="C")
    ctrl._open_note_in_reader(a)
    ctrl._open_note_in_reader(b)
    ctrl._open_note_in_reader(c)
    b.unlink()  # deleted in Obsidian while reading
    ctrl.noteBackClicked_(None)
    # B is gone → back lands on A, view stays consistent (path set, mode note).
    assert ctrl._mode == "note" and ctrl._note_path == a
    ctrl.noteBackClicked_(None)
    assert ctrl._mode == "insight" and ctrl._note_path is None


def test_entering_note_mode_bumps_epoch_and_captures_scroll(tmp_path):
    ctrl = dw.build_dashboard_window()
    ctrl._ensure_window()
    before = ctrl._epoch
    ctrl._open_note_in_reader(_note(tmp_path))
    assert ctrl._epoch == before + 1  # in-flight recall deliveries drop


def test_webview_persists_across_rerenders(tmp_path):
    # Resize / updateDeck_ / setTranscribing_ re-render the window; the note
    # webview must be the SAME object (reading position survives) and the
    # page must not reload when the path did not change.
    ctrl = dw.build_dashboard_window()
    ctrl._ensure_window()
    ctrl._open_note_in_reader(_note(tmp_path))
    web1 = ctrl._webview
    assert web1 is not None and ctrl._webview_path == ctrl._note_path
    ctrl._render()
    ctrl._render()
    assert ctrl._webview is web1


def test_section_switch_tears_note_state_down(tmp_path):
    ctrl = dw.build_dashboard_window()
    ctrl._ensure_window()
    ctrl._open_note_in_reader(_note(tmp_path))
    assert ctrl._webview is not None
    ctrl._section = "notatki"  # entered the reader from the Notatki section
    ctrl.sectionHeaderClicked_(_fake_sender(0))  # switch to Serendypacje
    assert ctrl._mode == "insight"
    assert ctrl._webview is None and ctrl._note_path is None


def test_unreadable_note_degrades_to_opener(tmp_path):
    opened = []
    ctrl = dw.build_dashboard_window(
        callbacks={"open_transcript": lambda p: opened.append(p)}
    )
    ctrl._ensure_window()
    missing = tmp_path / "nope.md"
    ctrl._open_note_in_reader(missing)
    assert ctrl._mode != "note"
    assert opened == [missing]


def test_chip_click_resolves_basename_inapp(tmp_path, monkeypatch):
    ctrl = dw.build_dashboard_window()
    ctrl._ensure_window()
    path = _note(tmp_path)
    monkeypatch.setattr(dw.obsidian_link, "resolve_note_path", lambda name, vault: path)
    ctrl._note_basenames = ["Rozmowa z Heliosem"]
    ctrl.noteClicked_(_fake_sender(0))
    assert ctrl._mode == "note"
    assert ctrl._note_path == path


def test_chip_click_unresolved_falls_back_to_callback(monkeypatch):
    opened = []
    ctrl = dw.build_dashboard_window(
        callbacks={"open_note": lambda n: opened.append(n)}
    )
    ctrl._ensure_window()
    monkeypatch.setattr(dw.obsidian_link, "resolve_note_path", lambda name, vault: None)
    ctrl._note_basenames = ["Nieistniejaca"]
    ctrl.noteClicked_(_fake_sender(0))
    assert ctrl._mode != "note"
    assert opened == ["Nieistniejaca"]


# ── navigation policy ──────────────────────────────────────────────────────


class _FakeURL:
    def __init__(self, s):
        self._s = s

    def absoluteString(self):
        return self._s


class _FakeAction:
    def __init__(self, s, nav_type=-1):  # -1 = WKNavigationTypeOther
        self._s = s
        self._nav = nav_type

    def request(self):
        return types.SimpleNamespace(URL=lambda: _FakeURL(self._s))

    def navigationType(self):
        return self._nav


def _policy(ctrl, url, nav_type=-1):
    decisions = []
    ctrl.webView_decidePolicyForNavigationAction_decisionHandler_(
        None, _FakeAction(url, nav_type), decisions.append
    )
    return decisions[0]


def test_policy_allows_page_and_fragment_jumps(tmp_path):
    ctrl = dw.build_dashboard_window()
    ctrl._ensure_window()
    assert _policy(ctrl, "about:blank") == 1  # the loadHTMLString page
    # In-document anchor jumps are allowed even as link clicks.
    assert _policy(ctrl, "about:blank#transkrypcja", nav_type=0) == 1


def test_policy_denies_about_blank_content_link():
    # A note body containing [x](about:blank) must NOT blank the reader:
    # a *clicked* bare about: URL is denied (nav_type 0 = link activated).
    ctrl = dw.build_dashboard_window()
    ctrl._ensure_window()
    assert _policy(ctrl, "about:blank", nav_type=0) == 0


def test_policy_cancels_external_and_unknown(monkeypatch):
    ctrl = dw.build_dashboard_window()
    ctrl._ensure_window()
    sent = []
    monkeypatch.setattr(dw.obsidian_link, "open_url", lambda u: sent.append(u))
    assert _policy(ctrl, "https://example.com/x") == 0
    assert sent == ["https://example.com/x"]
    assert _policy(ctrl, "file:///etc/passwd") == 0
    assert _policy(ctrl, "ftp://weird") == 0


def test_policy_mailto_and_obsidian_dispatch_to_system(monkeypatch):
    ctrl = dw.build_dashboard_window()
    ctrl._ensure_window()
    sent = []
    monkeypatch.setattr(dw.obsidian_link, "open_url", lambda u: sent.append(u))
    assert _policy(ctrl, "mailto:x@y.z", nav_type=0) == 0
    assert _policy(ctrl, "obsidian://open?vault=V", nav_type=0) == 0
    assert sent == ["mailto:x@y.z", "obsidian://open?vault=V"]


def test_policy_wikilink_cancels_then_renders_inapp(monkeypatch, tmp_path):
    from Foundation import NSDate, NSRunLoop

    ctrl = dw.build_dashboard_window()
    ctrl._ensure_window()
    path = _note(tmp_path)
    monkeypatch.setattr(dw.obsidian_link, "resolve_note_path", lambda name, vault: path)
    assert _policy(ctrl, "timshel-note://Rozmowa%20z%20Heliosem") == 0
    # The in-app open is deferred to the main runloop (re-rendering would tear
    # the webview down mid-delegate-callback). Early spins can be eaten by
    # WebKit's own load machinery from other windows — poll until it lands.
    for _ in range(20):
        if ctrl._mode == "note":
            break
        NSRunLoop.currentRunLoop().runUntilDate_(
            NSDate.dateWithTimeIntervalSinceNow_(0.1)
        )
    assert ctrl._mode == "note"
    assert ctrl._note_path == path
