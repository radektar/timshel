"""Per-note cost metering and the monthly AI-hours counter, end to end.

Drives the real ``_finalize_note`` tail with fake summarizer/tagger objects so
the wiring — one row per paid call, hours counted once, retry billed
separately — is exercised on the production path, not on a mock of it.
"""

from __future__ import annotations

import json
from datetime import datetime
from unittest.mock import patch

import pytest

from src import usage_ledger
from src.transcriber import Transcriber


class _Usage:
    def __init__(self, i: int, o: int) -> None:
        self.input_tokens = i
        self.output_tokens = o


class FakeSummarizer:
    """Returns a summary; records how many times it was called."""

    model = "claude-haiku-4-5-20251001"

    def __init__(self, summary_text: str = "## Podsumowanie\n\nTreść notatki.") -> None:
        self._summary = summary_text
        self.calls = 0
        self.last_usage = None

    def generate(self, transcript, known_terms_block="", correction=""):
        self.calls += 1
        self.last_usage = _Usage(100_000 * self.calls, 1_000)
        return {"title": "Tytuł", "summary": self._summary}


class FakeTagger:
    model = "claude-haiku-4-5-20251001"

    def __init__(self) -> None:
        self.last_usage = None

    def generate_tags(self, **_kwargs):
        self.last_usage = _Usage(5_000, 50)
        return ["projekt-x"]


@pytest.fixture
def transcriber(tmp_path, monkeypatch):
    from src.config.config import Config

    cfg = Config()
    cfg.TRANSCRIBE_DIR = tmp_path / "vault"
    cfg.TRANSCRIBE_DIR.mkdir(parents=True, exist_ok=True)
    cfg.LOCAL_RECORDINGS_DIR = tmp_path / "staging"
    cfg.ENABLE_RECALL_INDEX = False
    cfg.ENABLE_LLM_TAGGING = True
    cfg.INSIGHT_METRICS_ENABLED = True
    cfg.AI_HOURS_BUDGET = 30
    cfg.USAGE_LEDGER_FILE = tmp_path / "usage_ledger.json"
    # The ledger and the metrics writer read the *module-level* config.
    from src.config import config as global_config

    monkeypatch.setattr(global_config, "USAGE_LEDGER_FILE", cfg.USAGE_LEDGER_FILE)
    monkeypatch.setattr(global_config, "AI_HOURS_BUDGET", 30)
    monkeypatch.setattr(global_config, "INSIGHT_METRICS_ENABLED", True)
    monkeypatch.setattr(global_config, "TRANSCRIBE_DIR", cfg.TRANSCRIBE_DIR)
    with patch("src.transcriber.logger"):
        t = Transcriber(config=cfg)
    t.summarizer = FakeSummarizer()
    t.tagger = FakeTagger()
    return t


def _metrics(transcriber) -> list[dict]:
    path = transcriber.config.TRANSCRIBE_DIR / ".timshel" / "metrics.jsonl"
    if not path.exists():
        return []
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines()]


def _audio_metadata(duration_seconds=1800):
    return {
        "source_file": "REC001.wav",
        "recording_datetime": datetime(2026, 8, 6, 10, 0, 0),
        "duration_seconds": duration_seconds,
        "duration_formatted": "00:30:00",
    }


def _finalize(transcriber, *, duration=1800, source_type=None):
    extra = {"source_type": source_type} if source_type else None
    return transcriber._finalize_note(
        "Rozmowa o projekcie X i o wycenach.",
        _audio_metadata(duration),
        fingerprint="fp-test-1",
        extra_frontmatter=extra,
    )


def test_summary_and_tags_each_get_a_row(transcriber):
    _finalize(transcriber)

    rows = [r for r in _metrics(transcriber) if r.get("kind") == "note-llm"]
    assert [r["call"] for r in rows] == ["summary", "tags"]
    assert all(r["note"] == "fp-test-1" for r in rows)
    assert all(r["duration_seconds"] == 1800 for r in rows)
    # No explicit source_type on the recorder path.
    assert rows[0]["source_type"] == "recorder"
    assert rows[0]["cost_usd"] > 0


def test_source_type_flows_through(transcriber):
    _finalize(transcriber, source_type="voice-memo")
    rows = [r for r in _metrics(transcriber) if r.get("kind") == "note-llm"]
    assert {r["source_type"] for r in rows} == {"voice-memo"}


def test_alias_retry_is_billed_as_its_own_row(transcriber, monkeypatch):
    """The retry doubles a note's summary spend — it must be visible."""
    monkeypatch.setattr(
        "src.transcriber.find_alias_misses",
        lambda summary, vocab: [("tektutoreski", "Tech to the Rescue")],
    )
    _finalize(transcriber)

    rows = [r for r in _metrics(transcriber) if r.get("kind") == "note-llm"]
    assert [r["call"] for r in rows] == ["summary", "alias_retry", "tags"]
    # Separate rows carry separate token counts (second call, bigger input).
    assert rows[1]["input_tokens"] > rows[0]["input_tokens"]


def test_hours_counted_once_per_note_not_per_call(transcriber, monkeypatch):
    monkeypatch.setattr(
        "src.transcriber.find_alias_misses",
        lambda summary, vocab: [("a", "B")],
    )
    _finalize(transcriber, duration=1800)
    assert usage_ledger.read_usage().ai_seconds == 1800


def test_hours_accumulate_across_notes(transcriber):
    _finalize(transcriber, duration=1800)
    transcriber._finalize_note(
        "Druga rozmowa.",
        _audio_metadata(600),
        fingerprint="fp-test-2",
    )
    assert usage_ledger.read_usage().ai_seconds == 2400


def test_no_ai_means_no_rows_and_no_hours(transcriber):
    """Fallback-summary notes are free — nothing to bill, nothing to count."""
    transcriber.summarizer = None
    transcriber.tagger = None
    _finalize(transcriber)

    assert [r for r in _metrics(transcriber) if r.get("kind") == "note-llm"] == []
    assert usage_ledger.read_usage().ai_seconds == 0


def test_missing_duration_does_not_break_the_note(transcriber):
    """Text imports have no audio: the note is written, hours stay put."""
    path = transcriber._finalize_note(
        "Zaimportowany tekst.",
        {
            "source_file": "note.txt",
            "recording_datetime": datetime(2026, 8, 6, 10, 0, 0),
            "duration_seconds": None,
            "duration_formatted": "00:00:00",
        },
        fingerprint="fp-import",
        extra_frontmatter={"source_type": "import"},
    )
    assert path is not None and path.exists()
    rows = [r for r in _metrics(transcriber) if r.get("kind") == "note-llm"]
    assert rows and rows[0]["duration_seconds"] is None
    assert usage_ledger.read_usage().ai_seconds == 0


def test_metrics_flag_off_still_counts_hours(transcriber, monkeypatch):
    """The budget is a product feature; the metrics file is a tester instrument."""
    from src.config import config as global_config

    monkeypatch.setattr(global_config, "INSIGHT_METRICS_ENABLED", False)
    _finalize(transcriber, duration=900)

    assert _metrics(transcriber) == []
    assert usage_ledger.read_usage().ai_seconds == 900


def test_eighty_percent_notification_fires_once(transcriber, monkeypatch):
    seen = []
    monkeypatch.setattr(
        "src.transcriber.send_notification",
        lambda *args, **kwargs: seen.append(args),
    )
    # 24h of a 30h budget = 80%.
    usage_ledger.add_ai_seconds(24 * 3600 - 60)
    _finalize(transcriber, duration=120)
    assert len(seen) == 1
    assert "30h" in seen[0][1]

    transcriber._finalize_note("Kolejna.", _audio_metadata(600), fingerprint="fp-3")
    assert len(seen) == 1  # latched for the month


def test_broken_ledger_does_not_break_the_note(transcriber, monkeypatch):
    def boom(*_a, **_kw):
        raise RuntimeError("ledger exploded")

    monkeypatch.setattr(usage_ledger, "add_ai_seconds", boom)
    path = _finalize(transcriber)
    assert path is not None and path.exists()
