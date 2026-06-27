"""Tests for the action-rate readout (src/connections/signal_report.py, ADR-004).

Pure: no AppKit, no vault — events are built inline and fed to summarize(), and
the loader is exercised against a temp jsonl with legacy/malformed pollution.
"""

from __future__ import annotations

import json

from src.connections import signal_report as sr
from src.connections.signature import connection_signature


def _ev(target, *, sig="s1", kind=None, conn_type="shared-thread", tool="", ts="2026-06-27T10:00:00"):
    from src.connections.validation_signal import kind_for_target

    return {
        "v": 2,
        "ts": ts,
        "action": "action_taken",
        "kind": kind or kind_for_target(target),
        "target": target,
        "conn_type": conn_type,
        "sig": sig,
        "directions": [],
        "n_dir": 0,
        "tool": tool,
        "label": "",
    }


# ---- loader -------------------------------------------------------------


def test_load_events_skips_blank_malformed_and_legacy(tmp_path):
    p = tmp_path / "signal.jsonl"
    lines = [
        json.dumps(_ev("llm")),
        "",  # blank
        "{ not json",  # malformed
        json.dumps({"v": 1, "action": "kept", "signal_key": "x"}),  # legacy v1
        json.dumps({"v": 2, "action": "something_else"}),  # wrong action
        json.dumps(_ev("save")),
    ]
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    events, skipped = sr.load_events(p)
    assert len(events) == 2  # only the two v2 action_taken lines
    assert skipped == 3  # malformed + legacy + wrong-action (blank not counted)


def test_load_events_missing_file_is_empty(tmp_path):
    events, skipped = sr.load_events(tmp_path / "nope.jsonl")
    assert events == [] and skipped == 0


# ---- summarize: the KPI -------------------------------------------------


def test_action_rate_basic():
    # 3 connections engaged; 2 produced an action (llm, task), 1 only saved.
    events = [
        _ev("llm", sig="a"),
        _ev("task", sig="b"),
        _ev("save", sig="c"),
    ]
    s = sr.summarize(events)
    assert s.engaged == 3
    assert s.actioned == 2
    assert abs(s.action_rate - 2 / 3) < 1e-9


def test_save_and_none_are_engagement_without_action():
    events = [_ev("save", sig="a"), _ev("none", sig="b")]
    s = sr.summarize(events)
    assert s.engaged == 2
    assert s.actioned == 0
    assert s.action_rate == 0.0


def test_same_connection_counts_once_even_with_multiple_events():
    # one sig, saved first then handed to the LLM → one engaged, one actioned.
    events = [_ev("save", sig="a"), _ev("llm", sig="a")]
    s = sr.summarize(events)
    assert s.engaged == 1
    assert s.actioned == 1
    assert s.action_rate == 1.0


def test_empty_sig_events_excluded_from_rate_but_counted():
    events = [_ev("llm", sig=""), _ev("task", sig="b")]
    s = sr.summarize(events)
    assert s.missing_sig == 1
    assert s.engaged == 1  # only sig="b"
    assert s.actioned == 1
    # the empty-sig event still shows in the kind/target breakdowns
    assert s.by_target.get("llm") == 1
    assert s.by_target.get("task") == 1


def test_by_kind_and_target_count_events():
    events = [_ev("llm", sig="a"), _ev("clipboard", sig="b"), _ev("none", sig="c")]
    s = sr.summarize(events)
    assert s.by_kind == {"develop": 2, "none": 1}
    assert s.by_target == {"llm": 1, "clipboard": 1, "none": 1}


def test_by_tool_only_counts_actions_not_dismissals():
    # a dismissal carrying a stale tool string must NOT inflate the tool tally.
    events = [
        _ev("llm", sig="a", tool="claude"),
        _ev("llm", sig="b", tool="chatgpt"),
        _ev("none", sig="c", tool="claude"),
    ]
    s = sr.summarize(events)
    assert s.by_tool == {"claude": 1, "chatgpt": 1}


def test_by_conn_type_rate_per_type():
    events = [
        _ev("llm", sig="a", conn_type="contradiction-over-time"),
        _ev("save", sig="b", conn_type="contradiction-over-time"),
        _ev("task", sig="c", conn_type="emergent-idea"),
    ]
    s = sr.summarize(events)
    assert s.by_conn_type["contradiction-over-time"] == (1, 2)
    assert s.by_conn_type["emergent-idea"] == (1, 1)


def test_first_and_last_ts_span():
    events = [
        _ev("llm", sig="a", ts="2026-06-27T10:00:00"),
        _ev("task", sig="b", ts="2026-06-20T09:00:00"),
        _ev("save", sig="c", ts="2026-06-30T23:00:00"),
    ]
    s = sr.summarize(events)
    assert s.first_ts == "2026-06-20T09:00:00"
    assert s.last_ts == "2026-06-30T23:00:00"


def test_empty_summary():
    s = sr.summarize([])
    assert s.events == 0 and s.engaged == 0 and s.action_rate == 0.0


def test_signature_joins_back_to_connection():
    # a sig recomputed the canonical way joins the same connection the digest wrote.
    sig = connection_signature(["Note B", "Note A"], "emergent-idea")
    events = [_ev("llm", sig=sig, conn_type="emergent-idea")]
    s = sr.summarize(events)
    assert s.engaged == 1 and s.actioned == 1


# ---- render / CLI -------------------------------------------------------


def test_render_no_data_is_friendly():
    out = sr.render(sr.summarize([]))
    assert "Brak danych" in out


def test_render_shows_rate_and_kill_signal():
    engaged_no_action = sr.render(sr.summarize([_ev("save", sig="a"), _ev("none", sig="b")]))
    assert "kill-signal" in engaged_no_action
    alive = sr.render(sr.summarize([_ev("llm", sig="a")]))
    assert "Brama żyje" in alive
    assert "100%" in alive


def test_main_reads_path_arg(tmp_path, capsys):
    p = tmp_path / "signal.jsonl"
    p.write_text(json.dumps(_ev("llm", sig="a")) + "\n", encoding="utf-8")
    rc = sr.main([str(p)])
    assert rc == 0
    assert "ACTION-RATE" in capsys.readouterr().out


def test_main_json_mode(tmp_path, capsys):
    p = tmp_path / "signal.jsonl"
    p.write_text(json.dumps(_ev("task", sig="a")) + "\n", encoding="utf-8")
    rc = sr.main([str(p), "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["actioned"] == 1
    assert payload["action_rate"] == 1.0
    assert payload["path"] == str(p)
