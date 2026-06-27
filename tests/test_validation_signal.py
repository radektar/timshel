"""Pure tests for the action_taken recorder (no AppKit, ADR-004)."""

from __future__ import annotations

import json
from datetime import datetime

from src.connections import validation_signal as vsig
from src.connections.signature import connection_signature


def _lines(path):
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines()]


def test_record_action_writes_v2_event(tmp_path):
    p = tmp_path / "signal.jsonl"
    ok = vsig.record_action(
        vsig.TARGET_LLM,
        sig="abc123",
        conn_type="contradiction-over-time",
        directions=[0, 2],
        tool="claude",
        path=p,
        now=datetime(2026, 6, 27, 10, 0, 0),
    )
    assert ok is True
    r = _lines(p)[0]
    assert r["v"] == 2
    assert r["action"] == "action_taken"
    assert r["kind"] == "develop"  # derived from target=llm
    assert r["target"] == "llm"
    assert r["sig"] == "abc123"
    assert r["directions"] == [0, 2]
    assert r["n_dir"] == 2
    assert r["tool"] == "claude"
    assert r["ts"] == "2026-06-27T10:00:00"


def test_record_action_appends_rather_than_overwrites(tmp_path):
    p = tmp_path / "signal.jsonl"
    vsig.record_action(vsig.TARGET_LLM, sig="a", path=p)
    vsig.record_action(vsig.TARGET_TASK, sig="b", path=p)
    rows = _lines(p)
    assert [r["target"] for r in rows] == ["llm", "task"]


def test_record_action_creates_missing_directory(tmp_path):
    p = tmp_path / "nested" / "deeper" / "signal.jsonl"
    assert not p.parent.exists()
    assert vsig.record_action(vsig.TARGET_CLIPBOARD, sig="s", path=p) is True
    assert p.exists()


def test_record_action_kind_derives_from_target(tmp_path):
    p = tmp_path / "signal.jsonl"
    vsig.record_action(vsig.TARGET_TASK, sig="s", path=p)
    vsig.record_action(vsig.TARGET_CALENDAR, sig="s", path=p)
    vsig.record_action(vsig.TARGET_NONE, sig="s", path=p)  # dismiss
    assert [r["kind"] for r in _lines(p)] == ["do", "decide", "none"]


def test_record_action_recomputes_canonical_sig_when_absent(tmp_path):
    # No sig carried → fall back to the canonical type-inclusive signature, NOT
    # the legacy notes-only key, so the event still joins back to the connection.
    p = tmp_path / "signal.jsonl"
    vsig.record_action(
        vsig.TARGET_CLIPBOARD,
        conn_type="emergent-idea",
        notes=["b", "a"],
        path=p,
    )
    assert _lines(p)[0]["sig"] == connection_signature(["a", "b"], "emergent-idea")


def test_record_action_dismiss_is_none_none(tmp_path):
    # "Odrzuć" is a signal, not a suppressor: kind:none, target:none, no notes.
    p = tmp_path / "signal.jsonl"
    vsig.record_action(vsig.TARGET_NONE, sig="x", path=p)
    r = _lines(p)[0]
    assert r["kind"] == "none" and r["target"] == "none" and r["n_dir"] == 0


def test_record_action_never_raises_on_bad_path(tmp_path):
    blocker = tmp_path / "blocker"
    blocker.write_text("file", encoding="utf-8")
    bad = blocker / "sub" / "signal.jsonl"
    assert vsig.record_action(vsig.TARGET_LLM, sig="x", path=bad) is False
