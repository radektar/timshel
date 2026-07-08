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


# -- triage_state_by_sig (cross-session restore of Zachowaj / Odrzuć) -------


def test_triage_state_latest_save_or_none_wins(tmp_path):
    p = tmp_path / "signal.jsonl"
    base = datetime(2026, 6, 27, 10, 0, 0)
    # sig a: dismissed, then later saved → latest (save) wins → kept
    vsig.record_action(vsig.TARGET_NONE, sig="a", path=p, now=base)
    vsig.record_action(
        vsig.TARGET_SAVE, sig="a", path=p, now=datetime(2026, 6, 27, 11, 0, 0)
    )
    # sig b: saved once → kept
    vsig.record_action(vsig.TARGET_SAVE, sig="b", path=p, now=base)
    # sig c: dismissed → dismissed
    vsig.record_action(vsig.TARGET_NONE, sig="c", path=p, now=base)
    state = vsig.triage_state_by_sig(p)
    assert state == {"a": "kept", "b": "kept", "c": "dismissed"}


def test_triage_state_ignores_handoff_actions(tmp_path):
    p = tmp_path / "signal.jsonl"
    # A handoff (llm/task/...) is engagement, not triage — it must not set state.
    vsig.record_action(vsig.TARGET_LLM, sig="a", path=p)
    vsig.record_action(vsig.TARGET_TASK, sig="b", path=p)
    assert vsig.triage_state_by_sig(p) == {}


def test_triage_state_skips_empty_sig_and_missing_file(tmp_path):
    p = tmp_path / "signal.jsonl"
    assert vsig.triage_state_by_sig(p) == {}  # missing file
    vsig.record_action(vsig.TARGET_SAVE, sig="", path=p)  # no sig → unjoinable
    assert vsig.triage_state_by_sig(p) == {}


def test_triage_state_cached_by_mtime_size(tmp_path, monkeypatch):
    """An unchanged log must not be re-parsed — the cache serves it; a new
    append (size change) invalidates and re-reads."""
    p = tmp_path / "signal.jsonl"
    vsig._TRIAGE_CACHE.clear()
    vsig.record_action(vsig.TARGET_SAVE, sig="a", path=p)

    first = vsig.triage_state_by_sig(p)
    assert first == {"a": "kept"}

    # Second call with an unchanged file must hit the cache (no re-parse).
    calls = {"n": 0}
    real_read = type(p).read_text

    def counting_read(self, *a, **k):
        calls["n"] += 1
        return real_read(self, *a, **k)

    monkeypatch.setattr(type(p), "read_text", counting_read)
    assert vsig.triage_state_by_sig(p) == {"a": "kept"}
    assert calls["n"] == 0  # served from cache

    # A new append changes the size → cache invalidates → re-read.
    vsig.record_action(vsig.TARGET_NONE, sig="a", path=p)
    assert vsig.triage_state_by_sig(p) == {"a": "dismissed"}
    assert calls["n"] >= 1


def test_triage_cache_returns_independent_copy(tmp_path):
    """A caller mutating the returned dict must not poison the cache."""
    p = tmp_path / "signal.jsonl"
    vsig._TRIAGE_CACHE.clear()
    vsig.record_action(vsig.TARGET_SAVE, sig="a", path=p)

    first = vsig.triage_state_by_sig(p)
    first["a"] = "TAMPERED"
    assert vsig.triage_state_by_sig(p) == {"a": "kept"}
