"""Monthly AI-hours / deep-scan ledger."""

import json
from datetime import datetime

import pytest

from src import usage_ledger
from src.config import config


@pytest.fixture(autouse=True)
def ledger_file(tmp_path, monkeypatch):
    path = tmp_path / "usage_ledger.json"
    monkeypatch.setattr(config, "USAGE_LEDGER_FILE", path)
    monkeypatch.setattr(config, "AI_HOURS_BUDGET", 30)
    return path


def test_missing_file_reads_as_empty_month(ledger_file):
    usage = usage_ledger.read_usage()
    assert usage.ai_seconds == 0
    assert usage.deep_scans == 0
    assert usage.notified_80 is False
    assert not ledger_file.exists()  # a read must not create state


def test_add_ai_seconds_accumulates_and_persists(ledger_file):
    usage_ledger.add_ai_seconds(600)
    usage = usage_ledger.add_ai_seconds(1200)
    assert usage.ai_seconds == 1800
    on_disk = json.loads(ledger_file.read_text(encoding="utf-8"))
    assert on_disk["ai_seconds"] == 1800
    assert on_disk["month"] == usage_ledger.current_month()
    assert on_disk["v"] == usage_ledger.LEDGER_SCHEMA


def test_none_and_nonpositive_durations_are_ignored(ledger_file):
    """Text imports have no audio — they must not corrupt the counter."""
    assert usage_ledger.add_ai_seconds(None).ai_seconds == 0
    assert usage_ledger.add_ai_seconds(0).ai_seconds == 0
    assert usage_ledger.add_ai_seconds(-5).ai_seconds == 0
    assert not ledger_file.exists()


def test_calendar_month_rollover_resets_counters(ledger_file):
    july = datetime(2026, 7, 20, 12, 0, 0)
    august = datetime(2026, 8, 1, 0, 5, 0)
    usage_ledger.add_ai_seconds(3600, now=july)
    usage_ledger.increment_deep_scan(now=july)
    usage_ledger.mark_notified_80(now=july)

    fresh = usage_ledger.read_usage(now=august)
    assert fresh.month == "2026-08"
    assert fresh.ai_seconds == 0
    assert fresh.deep_scans == 0
    assert fresh.notified_80 is False


def test_deep_scan_counter_increments(ledger_file):
    assert usage_ledger.increment_deep_scan().deep_scans == 1
    assert usage_ledger.increment_deep_scan().deep_scans == 2


def test_notified_80_latches_once(ledger_file):
    first = usage_ledger.mark_notified_80()
    assert first.notified_80 is True
    written = ledger_file.stat().st_mtime_ns
    again = usage_ledger.mark_notified_80()
    assert again.notified_80 is True
    # Already latched — no second write.
    assert ledger_file.stat().st_mtime_ns == written


def test_corrupt_file_starts_a_fresh_month_instead_of_raising(ledger_file):
    ledger_file.write_text("{not json", encoding="utf-8")
    usage = usage_ledger.read_usage()
    assert usage.ai_seconds == 0
    # And the next increment repairs the file.
    assert usage_ledger.add_ai_seconds(60).ai_seconds == 60
    assert json.loads(ledger_file.read_text(encoding="utf-8"))["ai_seconds"] == 60


def test_bad_field_types_do_not_raise(ledger_file):
    ledger_file.write_text(
        json.dumps({"month": usage_ledger.current_month(), "ai_seconds": "lots"}),
        encoding="utf-8",
    )
    assert usage_ledger.read_usage().ai_seconds == 0


def test_write_failure_is_swallowed(ledger_file, monkeypatch):
    """A read-only disk must not stop a note from being written."""

    def boom(*_a, **_kw):
        raise OSError("read-only")

    monkeypatch.setattr(usage_ledger, "_write", boom)
    assert usage_ledger.add_ai_seconds(60).ai_seconds == 60  # in-memory value


def test_no_configured_path_degrades_quietly(monkeypatch):
    monkeypatch.setattr(config, "USAGE_LEDGER_FILE", None)
    assert usage_ledger.ledger_path() is None
    assert usage_ledger.read_usage().ai_seconds == 0
    assert usage_ledger.add_ai_seconds(60).ai_seconds == 60


def test_budget_fraction(ledger_file):
    usage_ledger.add_ai_seconds(24 * 3600)  # 24h of 30h
    assert usage_ledger.read_usage().budget_fraction(30) == pytest.approx(0.8)
    assert usage_ledger.read_usage().budget_fraction(0) == 0.0


@pytest.mark.parametrize(
    "seconds,expected",
    [(0, "0m"), (59, "0m"), (600, "10m"), (3600, "1h 0m"), (4520, "1h 15m")],
)
def test_format_hours(seconds, expected):
    assert usage_ledger.format_hours(seconds) == expected


def test_temp_file_is_per_process(ledger_file, monkeypatch):
    """A shared temp name lets two writers interleave into one file, and
    os.replace then publishes mangled JSON — losing the whole month, not one
    increment."""
    import os

    seen = []
    real_replace = os.replace
    monkeypatch.setattr(
        usage_ledger.os,
        "replace",
        lambda src, dst: (seen.append(str(src)), real_replace(src, dst))[1],
    )
    usage_ledger.add_ai_seconds(60)
    assert str(os.getpid()) in seen[0]
