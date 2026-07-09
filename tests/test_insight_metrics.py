"""Pure tests for the magic-insights per-digest metrics instrument."""

from __future__ import annotations

import json
from datetime import datetime

from src.connections import insight_metrics as im


class _Usage:
    """Minimal stand-in for an Anthropic ``usage`` object."""

    def __init__(self, i=0, o=0, cr=0, cw=0):
        self.input_tokens = i
        self.output_tokens = o
        self.cache_read_input_tokens = cr
        self.cache_creation_input_tokens = cw


def _lines(path):
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines()]


def test_cost_opus_list_price():
    # 1M input @ $5 + 1M output @ $25 = $30 exactly.
    assert im.estimate_cost_usd("claude-opus-4-8", 1_000_000, 1_000_000) == 30.0


def test_cost_batch_halves():
    full = im.estimate_cost_usd("claude-opus-4-8", 200_000, 50_000)
    batched = im.estimate_cost_usd("claude-opus-4-8", 200_000, 50_000, batch=True)
    assert round(batched, 6) == round(full * 0.5, 6)


def test_cost_cache_read_is_tenth_of_input():
    # 1M cache-read tokens @ opus input $5 * 0.1 = $0.50.
    assert (
        im.estimate_cost_usd("claude-opus-4-8", 0, 0, cache_read_tokens=1_000_000)
        == 0.5
    )


def test_unknown_model_falls_back_to_opus():
    unknown = im.estimate_cost_usd("claude-future-9", 1_000_000, 0)
    opus = im.estimate_cost_usd("claude-opus-4-8", 1_000_000, 0)
    assert unknown == opus  # over-estimate, not crash


def test_usage_tokens_defensive_on_none():
    t = im.usage_tokens(None)
    assert t == {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
    }


def test_build_record_shape():
    rec = im.build_record(
        model="claude-opus-4-8",
        usage=_Usage(i=12_000, o=800, cr=4_000),
        candidates=18,
        connections=3,
        connection_types=["contradiction-over-time", "shared-thread", "emergent-idea"],
        digest="2026-07-05 Synthesis.md",
        now=datetime(2026, 7, 5, 12, 0, 0),
    )
    assert rec["v"] == im.METRICS_SCHEMA_VERSION
    assert rec["model"] == "claude-opus-4-8"
    assert rec["candidates"] == 18
    assert rec["connections"] == 3
    assert rec["input_tokens"] == 12_000
    assert rec["cache_read_tokens"] == 4_000
    assert rec["cost_usd"] > 0
    assert rec["ts"] == "2026-07-05T12:00:00"


def test_build_record_v2_verdict_fields_and_total():
    rec = im.build_record(
        model="claude-sonnet-4-6",
        usage=_Usage(i=100_000, o=10_000),
        candidates=20,
        connections=2,
        digest="d.md",
        verdict_model="claude-opus-4-8",
        verdict_usage=_Usage(i=10_000, o=1_000),
        verdict_dropped=1,
    )
    assert rec["v"] == 2
    assert rec["verdict_model"] == "claude-opus-4-8"
    assert rec["verdict_dropped"] == 1
    assert rec["verdict_cost_usd"] > 0
    assert rec["cost_usd"] == round(
        rec["synthesis_cost_usd"] + rec["verdict_cost_usd"], 6
    )


def test_build_record_without_verdict_has_zero_verdict_cost():
    rec = im.build_record(
        model="claude-opus-4-8",
        usage=_Usage(i=10_000, o=500),
        candidates=5,
        connections=1,
    )
    assert rec["verdict_model"] == ""
    assert rec["verdict_cost_usd"] == 0.0
    assert rec["cost_usd"] == rec["synthesis_cost_usd"]


class _FakeSynth:
    def __init__(self, model, usage):
        self.model = model
        self.last_usage = usage


class _Conn:
    def __init__(self, type_):
        self.type = type_


class _Candidates:
    def __init__(self, n):
        self.notes = list(range(n))


def test_scheduler_helper_writes_metrics(tmp_path, monkeypatch):
    """The scheduler seam appends a record derived from the live synthesizer."""
    from pathlib import Path

    from src.config.config import config
    from src.connections import scheduler

    monkeypatch.setattr(config, "TRANSCRIBE_DIR", str(tmp_path))
    monkeypatch.setattr(config, "INSIGHT_METRICS_ENABLED", True)  # off by default now
    synth = _FakeSynth("claude-opus-4-8", _Usage(i=15_000, o=900, cr=6_000))
    conns = [_Conn("contradiction-over-time"), _Conn("shared-thread")]

    scheduler._record_digest_metrics(
        synth, _Candidates(20), conns, Path("2026-07-05 Synthesis.md")
    )

    out = tmp_path / ".timshel" / "metrics.jsonl"
    rows = _lines(out)
    assert len(rows) == 1
    assert rows[0]["model"] == "claude-opus-4-8"
    assert rows[0]["candidates"] == 20
    assert rows[0]["connections"] == 2
    assert rows[0]["connection_types"] == ["contradiction-over-time", "shared-thread"]
    assert rows[0]["cost_usd"] > 0


def test_record_appends_and_is_readable(tmp_path, monkeypatch):
    monkeypatch.setattr(im.config, "INSIGHT_METRICS_ENABLED", True)  # off by default
    p = tmp_path / "metrics.jsonl"
    ok1 = im.record_digest_metrics(
        model="claude-opus-4-8",
        usage=_Usage(i=10_000, o=500),
        candidates=12,
        connections=2,
        connection_types=["shared-thread", "emergent-idea"],
        digest="d1.md",
        path=p,
    )
    ok2 = im.record_digest_metrics(
        model="claude-haiku-4-5-20251001",
        usage=_Usage(i=8_000, o=200),
        candidates=9,
        connections=0,
        digest="d2.md",
        path=p,
    )
    assert ok1 and ok2
    rows = _lines(p)
    assert [r["digest"] for r in rows] == ["d1.md", "d2.md"]
    assert rows[0]["connection_types"] == ["shared-thread", "emergent-idea"]
    assert rows[1]["connections"] == 0
