"""User-scenario tests for the Insights action layer (ui-marked, ADR-004).

Drives the real handlers headless: multi-select directions, the shared handoff
(LLM / task / calendar / clipboard), the evidence toggle and the LLM switcher.
The handoff side effects and the signal log are stubbed — no app is launched.
"""

from __future__ import annotations

import json

import pytest

from src.config import config
from src.connections import handoff as ho
from src.connections import validation_signal as vsig
from src.ui import dashboard_window as dw

pytestmark = pytest.mark.ui

if not dw._APPKIT_AVAILABLE:  # pragma: no cover - non-mac
    pytest.skip("AppKit unavailable", allow_module_level=True)


class _Sender:
    def __init__(self, tag):
        self._tag = tag

    def tag(self):
        return self._tag


def _ctrl():
    ctrl = dw.build_dashboard_window()
    ctrl._ensure_window()
    return ctrl


@pytest.fixture
def log_path(tmp_path, monkeypatch):
    p = tmp_path / "signal.jsonl"
    monkeypatch.setattr(vsig, "signal_log_path", lambda: p)
    return p


def _rows(path):
    if not path.exists():
        return []
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines()]


def test_direction_click_toggles_selection():
    ctrl = _ctrl()
    assert ctrl._selected == set()
    ctrl.directionClicked_(_Sender(0))
    assert ctrl._selected == {0}
    ctrl.directionClicked_(_Sender(1))
    assert ctrl._selected == {0, 1}
    ctrl.directionClicked_(_Sender(0))  # toggle off
    assert ctrl._selected == {1}


def test_evidence_toggle_flips_grounded():
    ctrl = _ctrl()
    assert ctrl._grounded is False
    ctrl.toggleEvidenceClicked_(None)
    assert ctrl._grounded is True


def test_continue_in_llm_dispatches_selection_and_logs(log_path, monkeypatch):
    captured = {}

    def fake_dispatch(target, **kw):
        captured["target"] = target
        captured.update(kw)
        return ho.HandoffResult(True, "open", "Wysłano do Claude")

    monkeypatch.setattr(ho, "dispatch", fake_dispatch)
    monkeypatch.setattr(config, "LLM_HANDOFF_TOOL", "claude")

    ctrl = _ctrl()
    conn = ctrl._deck.active()
    ctrl.directionClicked_(_Sender(0))
    ctrl.continueLLMClicked_(None)
    ctrl._handoff_thread.join(timeout=5)  # dispatch runs off the main thread

    # handoff got the selected direction + the connection's evidence
    assert captured["target"] == ho.LLM
    assert captured["directions"] == [conn.directions[0]]
    assert captured["tool"] == "claude"
    assert captured["evidence"]  # sample deck carries evidence

    # and the action_taken event was logged with the right shape
    rows = _rows(log_path)
    assert len(rows) == 1
    assert rows[0]["action"] == "action_taken"
    assert rows[0]["target"] == "llm"
    assert rows[0]["kind"] == "develop"
    assert rows[0]["directions"] == [0]
    assert rows[0]["tool"] == "claude"
    # end-to-end join (Decision 2): the logged sig is the canonical signature of
    # the very connection the window rendered.
    from src.connections.signature import connection_signature

    assert rows[0]["sig"] == connection_signature(conn.notes, conn.synthesis_type)
    assert rows[0]["conn_type"] == conn.synthesis_type  # raw type, not display


def test_handoff_without_selection_is_noop(log_path, monkeypatch):
    called = {"n": 0}
    monkeypatch.setattr(
        ho, "dispatch",
        lambda *a, **k: called.__setitem__("n", called["n"] + 1)
        or ho.HandoffResult(True, "open", "x"),
    )
    ctrl = _ctrl()
    ctrl.copyClicked_(None)  # nothing selected
    assert called["n"] == 0
    assert _rows(log_path) == []


def test_calendar_handoff_logs_decide(log_path, monkeypatch):
    monkeypatch.setattr(ho, "dispatch", lambda *a, **k: ho.HandoffResult(True, "open", "ok"))
    ctrl = _ctrl()
    ctrl.directionClicked_(_Sender(0))
    ctrl.calendarClicked_(None)
    ctrl._handoff_thread.join(timeout=5)  # dispatch runs off the main thread
    rows = _rows(log_path)
    assert rows[0]["target"] == "calendar" and rows[0]["kind"] == "decide"


def test_handoff_toast_marshalled_back_to_main(log_path, monkeypatch):
    """The worker never touches UI: the toast lands via applyHandoff_ on the
    main thread (worker/apply split, same as recall)."""
    monkeypatch.setattr(
        ho, "dispatch", lambda *a, **k: ho.HandoffResult(True, "open", "toast-msg")
    )
    ctrl = _ctrl()
    shown = []
    monkeypatch.setattr(ctrl, "_show_toast", lambda msg: shown.append(msg), raising=False)

    ctrl.directionClicked_(_Sender(0))
    ctrl.copyClicked_(None)
    ctrl._handoff_thread.join(timeout=5)

    assert shown == []  # nothing shown from the worker thread
    ctrl.applyHandoff_(None)  # what performSelectorOnMainThread delivers
    assert shown == ["toast-msg"]
    ctrl.applyHandoff_(None)  # idempotent: payload consumed
    assert shown == ["toast-msg"]


def test_switch_llm_cycles_and_persists(monkeypatch):
    saved = {}
    monkeypatch.setattr(config, "LLM_HANDOFF_TOOL", "claude")

    class _S:
        ai_handoff_tool = "claude"

        def save(self_inner):
            saved["tool"] = self_inner.ai_handoff_tool

    monkeypatch.setattr("src.config.settings.UserSettings.load", classmethod(lambda cls: _S()))

    ctrl = _ctrl()
    # full wraparound over the prefill-capable tools: claude → chatgpt → claude
    ctrl.switchLLMClicked_(None)
    assert config.LLM_HANDOFF_TOOL == "chatgpt"
    ctrl.switchLLMClicked_(None)
    assert config.LLM_HANDOFF_TOOL == "claude"
    assert saved["tool"] == "claude"


def test_dismiss_is_signal_not_suppressor(log_path, tmp_path, monkeypatch):
    # Odrzuć logs a none-signal but must NOT write the dismissal store
    # (connections.json) — durable suppression stays the Obsidian frontmatter path.
    monkeypatch.setattr(config, "TRANSCRIBE_DIR", tmp_path)
    ctrl = _ctrl()
    ctrl.dismissClicked_(None)
    rows = _rows(log_path)
    assert rows[0]["target"] == "none" and rows[0]["kind"] == "none"
    assert not (tmp_path / ".malinche" / "connections.json").exists()
