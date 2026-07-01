"""Smoke tests for the Insights dashboard window (AppKit, ui-marked)."""

from __future__ import annotations

import types

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


# ── recall (pull) surface — Faza 3 ─────────────────────────────────────────

from src.connections.recall.retriever import Result  # noqa: E402


def _fake_results(n=3):
    return [
        Result(
            note_id=f"26-06-0{i} - Nota testowa {i}", quote=f"doslowny fragment {i}",
            parent_text=f"fragment {i}", char_start=0, char_end=10,
            score=0.5 - i * 0.01, channels="dense+lexical",
        )
        for i in range(1, n + 1)
    ]


def _complete_search(ctrl, query):
    """Drive the off-thread search synchronously (no run loop in tests): the worker
    builds the payload, applyRecall_ applies it on the 'main thread'."""
    ctrl._query = query
    ctrl._mode = "recall"
    ctrl._recall_loading = True
    ctrl._recall_worker_(query)
    ctrl.applyRecall_(None)


def test_run_recall_shows_loading_off_main_thread():
    ctrl = dw.build_dashboard_window(callbacks={
        "recall_search": lambda q: (_fake_results(3), 0.82, "ok"),
    })
    ctrl._ensure_window()
    ctrl._run_recall("co z dostawa okien")
    # search is dispatched to a daemon thread: mode flips + loading is shown at once,
    # the result is NOT applied synchronously.
    assert ctrl._mode == "recall" and ctrl._recall_loading is True
    _render(ctrl)  # loading state paints without raising


def test_recall_mode_renders_ranked_results():
    ctrl = dw.build_dashboard_window(callbacks={
        "recall_search": lambda q: (_fake_results(3), 0.82, "ok"),
        "open_note": lambda name: None,
    })
    ctrl._ensure_window()
    _complete_search(ctrl, "co z dostawa okien")
    assert ctrl._mode == "recall" and ctrl._recall_loading is False
    assert ctrl._recall is not None and ctrl._recall.count == 3
    assert ctrl._recall_status == "ok"
    _render(ctrl)
    assert len(ctrl._recall_note_ids) == 3


def test_recall_open_invokes_open_note():
    opened = []
    ctrl = dw.build_dashboard_window(callbacks={
        "recall_search": lambda q: (_fake_results(2), 0.82, "ok"),
        "open_note": lambda name: opened.append(name),
    })
    ctrl._ensure_window()
    _complete_search(ctrl, "q")
    _render(ctrl)

    class _Sender:
        def tag(self):
            return 0

    ctrl.recallOpenClicked_(_Sender())
    assert opened == [ctrl._recall_note_ids[0]]


def test_recall_abstinence_renders():
    ctrl = dw.build_dashboard_window(callbacks={
        "recall_search": lambda q: (_fake_results(1), 0.20, "ok"),  # below floor
    })
    ctrl._ensure_window()
    _complete_search(ctrl, "przepis na sernik")
    assert ctrl._recall.is_empty and ctrl._recall.nearest is not None
    assert ctrl._recall_status == "ok"
    _render(ctrl)  # abstinence view paints without raising


def test_recall_notready_state_renders_for_empty_index():
    # A failed/unindexed search must NOT render as a genuine "nothing found".
    ctrl = dw.build_dashboard_window(callbacks={
        "recall_search": lambda q: ([], 0.0, "empty"),
    })
    ctrl._ensure_window()
    _complete_search(ctrl, "cokolwiek")
    assert ctrl._recall.is_empty and ctrl._recall_status == "empty"
    _render(ctrl)  # not-ready view paints without raising


def test_recall_stale_result_is_dropped():
    ctrl = dw.build_dashboard_window(callbacks={
        "recall_search": lambda q: (_fake_results(2), 0.82, "ok"),
    })
    ctrl._ensure_window()
    ctrl._query = "nowe pytanie"           # user has moved on
    ctrl._recall_worker_("stare pytanie")  # an older worker finishes late
    ctrl.applyRecall_(None)
    assert ctrl._recall is None            # stale payload dropped, not applied


def test_wrong_shape_callback_is_unavailable_not_no_match():
    ctrl = dw.build_dashboard_window(callbacks={
        "recall_search": lambda q: ["oops-not-a-tuple"],
    })
    ctrl._ensure_window()
    _complete_search(ctrl, "q")
    assert ctrl._recall.is_empty and ctrl._recall_status == "unavailable"


def test_empty_query_returns_to_insight():
    ctrl = dw.build_dashboard_window(callbacks={
        "recall_search": lambda q: (_fake_results(2), 0.8, "ok"),
    })
    ctrl._ensure_window()
    ctrl._run_recall("q")
    assert ctrl._mode == "recall"
    ctrl._run_recall("   ")
    assert ctrl._mode == "insight" and ctrl._recall is None


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


# ── recall synthesis escalation (the one LLM door) — Faza 4 ────────────────

def _fake_answer():
    return types.SimpleNamespace(
        answered=True,
        thesis="Dostawa okien opozniona, dach czeka.",
        evidence=[types.SimpleNamespace(
            note="26-06-05 - Okna dach", date="26-06-05", quote="dostawa niepewna")],
        directions=["Co z alternatywnym dostawca okien?"],
    )


def _complete_synthesis(ctrl):
    ctrl._answer_loading = True
    ctrl._synth_worker_(ctrl._query, list(ctrl._recall_raw))
    ctrl.applyAnswer_(None)


def test_recall_keeps_raw_hits_for_synthesis():
    ctrl = dw.build_dashboard_window(callbacks={
        "recall_search": lambda q: (_fake_results(2), 0.82, "ok"),
    })
    ctrl._ensure_window()
    _complete_search(ctrl, "co z oknami")
    assert len(ctrl._recall_raw) == 2  # raw Results retained for the escalation
    _render(ctrl)  # results + escalation bar paint without raising


def test_synthesis_renders_answer_card_and_actions():
    saved = {}
    opened = []
    ctrl = dw.build_dashboard_window(callbacks={
        "recall_search": lambda q: (_fake_results(2), 0.82, "ok"),
        "recall_synthesize": lambda q, r: _fake_answer(),
        "recall_save_answer": lambda q, a: "/tmp/answer.md",
        "open_note": lambda n: opened.append(n),
    })
    ctrl._ensure_window()
    _complete_search(ctrl, "co z oknami")
    _complete_synthesis(ctrl)
    assert ctrl._answer is not None and ctrl._answer_loading is False
    _render(ctrl)  # answer card + sources paint without raising
    assert ctrl._synth_note_ids  # evidence ↗ tags populated

    class _S:
        def tag(self):
            return 0

    ctrl.synthOpenClicked_(_S())
    assert opened == [ctrl._synth_note_ids[0]]

    ctrl.saveAnswerClicked_(None)  # invokes recall_save_answer, shows a toast

    ctrl.clearAnswerClicked_(None)
    assert ctrl._answer is None
    _render(ctrl)  # back to plain results


def test_synthesis_none_answer_does_not_crash():
    ctrl = dw.build_dashboard_window(callbacks={
        "recall_search": lambda q: (_fake_results(1), 0.82, "ok"),
        "recall_synthesize": lambda q, r: None,  # soft failure
    })
    ctrl._ensure_window()
    _complete_search(ctrl, "q")
    _complete_synthesis(ctrl)
    assert ctrl._answer is None and ctrl._answer_loading is False
    _render(ctrl)


def test_focus_recall_shows_window_and_can_prefill():
    ctrl = dw.build_dashboard_window(callbacks={
        "recall_search": lambda q: ([], 0.0, "empty"),
    })
    ctrl.focusRecall()
    assert ctrl._window is not None  # window brought up, ask-bar present
    ctrl.focusRecall("co z oknami")  # prefill runs a search
    assert ctrl._mode == "recall" and ctrl._query == "co z oknami"


def test_ask_about_insight_enters_recall_with_rationale():
    ctrl = dw.build_dashboard_window()  # sample deck → an active insight exists
    ctrl._ensure_window()
    conn = ctrl._deck.active()
    assert conn is not None
    ctrl.askAboutInsightClicked_(None)
    assert ctrl._mode == "recall" and ctrl._query == conn.rationale
