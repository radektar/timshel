"""Tests for the log viewer parser layer."""

from pathlib import Path

import pytest

from src.ui.log_viewer import (
    LOG_LINE_RE,
    LogEntry,
    parse_lines,
    read_recent,
)


SAMPLE_LINES = [
    "2026-05-05 08:29:12 - malinche - INFO - Checking for recorder",
    "2026-05-05 08:29:13 - malinche - WARNING - SD card not detected",
    "2026-05-05 08:29:14 - malinche - ERROR - Traceback (most recent call last):",
    "  File \"x.py\", line 10, in foo",
    "    raise RuntimeError('boom')",
    "RuntimeError: boom",
    "2026-05-05 08:29:15 - malinche - INFO - Recovered",
]


def test_regex_matches_basic_line():
    m = LOG_LINE_RE.match(SAMPLE_LINES[0])
    assert m is not None
    assert m.group("ts") == "2026-05-05 08:29:12"
    assert m.group("level") == "INFO"
    assert "Checking for recorder" in m.group("msg")


def test_parse_lines_collapses_traceback_into_previous_entry():
    entries = parse_lines(SAMPLE_LINES)
    assert len(entries) == 4
    assert entries[0].level == "INFO"
    assert entries[1].level == "WARNING"
    err = entries[2]
    assert err.level == "ERROR"
    # Multi-line continuation merged
    assert "RuntimeError: boom" in err.message
    assert "File \"x.py\"" in err.message
    assert entries[3].message == "Recovered"


def test_matches_level_threshold():
    e_info = LogEntry("ts", "x", "INFO", "m")
    e_warn = LogEntry("ts", "x", "WARNING", "m")
    e_err = LogEntry("ts", "x", "ERROR", "m")
    assert e_info.matches_level("DEBUG")
    assert not e_info.matches_level("WARNING")
    assert e_warn.matches_level("WARNING")
    assert e_err.matches_level("ERROR")
    assert e_err.matches_level("WARNING")


def test_matches_search_case_insensitive():
    e = LogEntry("2026-05-05 08:29:12", "x", "INFO", "Recorder mounted")
    assert e.matches_search("recorder")
    assert e.matches_search("MOUNTED")
    assert e.matches_search("08:29")
    assert not e.matches_search("scanner")
    assert e.matches_search("")  # empty needle = always match


def test_read_recent_handles_missing_file(tmp_path):
    missing = tmp_path / "nope.log"
    assert read_recent(missing) == []


def test_read_recent_caps_to_max_entries(tmp_path):
    log_file = tmp_path / "many.log"
    body = "\n".join(
        f"2026-05-05 08:29:{i % 60:02d} - malinche - INFO - line {i}"
        for i in range(200)
    )
    log_file.write_text(body, encoding="utf-8")
    entries = read_recent(log_file, max_entries=50)
    assert len(entries) == 50
    # Caps to most recent — last entry should be 'line 199'
    assert "line 199" in entries[-1].message


def test_read_recent_tail_bounds_bytes_read(tmp_path, monkeypatch):
    """On a file larger than the tail window, only the tail is read — and the
    newest entries still survive (a partial leading line is dropped cleanly)."""
    from src.ui import log_viewer

    monkeypatch.setattr(log_viewer, "_TAIL_BYTES", 2048)
    log_file = tmp_path / "big.log"
    body = "\n".join(
        f"2026-05-05 08:29:{i % 60:02d} - malinche - INFO - line {i}"
        for i in range(2000)
    )
    log_file.write_text(body, encoding="utf-8")
    assert log_file.stat().st_size > 2048  # exceeds the tail window

    entries = read_recent(log_file, max_entries=5000)
    # Newest entry present; oldest (byte-truncated) gone.
    assert "line 1999" in entries[-1].message
    assert not any("line 0 " in e.message or e.message == "line 0" for e in entries)
    # Every returned entry parsed cleanly (no partial-line garbage).
    assert all(e.timestamp for e in entries)


def test_parser_drops_lines_before_first_timestamp():
    junk = ["random pre-amble line", "2026-05-05 08:29:12 - malinche - INFO - first"]
    entries = parse_lines(junk)
    assert len(entries) == 1
    assert entries[0].message == "first"
