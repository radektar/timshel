"""Tests for the insight handoff builders + dispatch (ADR-004). No network."""

from __future__ import annotations

from datetime import datetime

from src.connections import handoff as ho

EV = [("17.06", "Haetta", "jakość first"), ("18.06", "8Moons", "budżet 2x")]
DIRS = ["Co wymusiło zmianę?", "Bronić filarów czy zrewidować?"]


# --- pure builders ------------------------------------------------------- #


def test_seeded_prompt_carries_spark_evidence_directions():
    p = ho.seeded_prompt("Sprzeczność w czasie", "Założenie się przesunęło", EV, DIRS)
    assert "Założenie się przesunęło" in p
    assert "17.06 · Haetta: „jakość first”" in p
    assert "1. Co wymusiło zmianę?" in p
    # non-prescriptive close — asks for thinking, not answers
    assert "bez gotowych odpowiedzi" in p


def test_seeded_prompt_handles_no_evidence():
    p = ho.seeded_prompt("", "claim", [], ["A?"])
    assert "Oparte na:" not in p
    assert "„claim”" in p


def test_llm_url_prefills_claude_and_chatgpt():
    cl = ho.llm_url("claude", "hej tam")
    ch = ho.llm_url("chatgpt", "hej tam")
    assert cl.startswith("https://claude.ai/new?q=")
    assert ch.startswith("https://chatgpt.com/?q=")
    assert "hej%20tam" in cl  # space encoded, not '+'


def test_llm_url_unknown_tool_has_no_prefill():
    assert ho.llm_url("gemini", "x") is None  # retired
    assert ho.llm_url("totally-unknown", "x") is None


def test_llm_url_none_when_too_long():
    assert ho.llm_url("claude", "x" * (ho.URL_MAX + 1)) is None


def test_ics_text_is_a_tomorrow_morning_event():
    txt = ho.ics_text("Rozwiń pomysł", "ciało, z; przecinkiem", now=datetime(2026, 6, 27, 10, 0, 0))
    assert "BEGIN:VEVENT" in txt and "END:VEVENT" in txt
    assert "DTSTART:20260628T090000" in txt  # tomorrow 09:00
    assert "SUMMARY:Rozwiń pomysł" in txt
    assert "ciało\\, z\\; przecinkiem" in txt  # escaped


def test_reminders_script_escapes_quotes():
    s = ho.reminders_script('Zrób "to"', "body")
    assert "make new reminder" in s
    assert '\\"to\\"' in s


def test_reminders_script_splices_multiline_body():
    # The seeded prompt is always multi-line; AppleScript can't hold a newline
    # inside a quoted literal, so it must be spliced via `linefeed` or the script
    # fails to compile and the Task handoff silently never works.
    s = ho.reminders_script("t", "line one\nline two")
    assert "\n" not in s.split("make new reminder", 1)[1].split("body:", 1)[1].split("}", 1)[0]
    assert '" & linefeed & "' in s


# --- dispatch (side effects stubbed) ------------------------------------- #


def _stub(monkeypatch):
    calls = {}
    monkeypatch.setattr(ho, "_open_url", lambda u: calls.setdefault("open", u) or True)
    monkeypatch.setattr(ho, "_copy", lambda t: calls.setdefault("copy", t) or True)
    monkeypatch.setattr(ho, "_open_ics", lambda t: calls.setdefault("ics", t) or True)
    monkeypatch.setattr(ho, "_osascript", lambda s: calls.setdefault("osa", s) or True)
    return calls


def test_dispatch_llm_claude_opens_prefill(monkeypatch):
    calls = _stub(monkeypatch)
    r = ho.dispatch(ho.LLM, label="L", rationale="r", evidence=EV, directions=DIRS, tool="claude")
    assert r.ok and r.mode == "open"
    assert r.toast == "Wysłano do Claude"
    assert calls["open"].startswith("https://claude.ai/new?q=")


def test_dispatch_llm_falls_back_to_clipboard_when_payload_too_long(monkeypatch):
    # When the prefill URL would exceed URL_MAX, the handoff degrades to
    # copy-the-prompt + open the bare tool (the same fallback Gemini once used).
    calls = _stub(monkeypatch)
    r = ho.dispatch(ho.LLM, rationale="x" * (ho.URL_MAX + 1), tool="claude")
    assert r.mode == "clipboard"
    assert "wklej w Claude" in r.toast
    assert "copy" in calls and calls["open"] == "https://claude.ai/new"


def test_dispatch_calendar_stages_ics(monkeypatch):
    calls = _stub(monkeypatch)
    r = ho.dispatch(ho.CALENDAR, rationale="r", directions=DIRS, now=datetime(2026, 6, 27, 10, 0, 0))
    assert r.ok and "Kalendarz" in r.toast
    assert "BEGIN:VCALENDAR" in calls["ics"]


def test_dispatch_task_runs_applescript(monkeypatch):
    calls = _stub(monkeypatch)
    r = ho.dispatch(ho.TASK, rationale="r", directions=DIRS)
    assert r.ok and r.toast == "Utworzono zadanie"
    assert "make new reminder" in calls["osa"]


def test_dispatch_clipboard_copies(monkeypatch):
    calls = _stub(monkeypatch)
    r = ho.dispatch(ho.CLIPBOARD, rationale="r", directions=DIRS)
    assert r.ok and "Skopiowano 2 kierunki" in r.toast
    assert "copy" in calls


def test_dispatch_reports_failure(monkeypatch):
    monkeypatch.setattr(ho, "_open_url", lambda u: False)
    r = ho.dispatch(ho.LLM, rationale="r", directions=DIRS, tool="claude")
    assert r.ok is False


def test_run_passes_timeout(monkeypatch):
    """subprocess.run must be bounded — osascript blocks indefinitely on the
    TCC consent prompt / a Reminders cold launch without a timeout."""
    import subprocess as sp

    captured = {}

    def fake_run(args, **kwargs):
        captured.update(kwargs)
        return None

    monkeypatch.setattr(ho.subprocess, "run", fake_run)
    assert ho._run(["true"]) is True
    assert captured.get("timeout") == 15

    def hang(args, **kwargs):
        raise sp.TimeoutExpired(args, kwargs.get("timeout"))

    monkeypatch.setattr(ho.subprocess, "run", hang)
    assert ho._run(["osascript", "-e", "x"]) is False  # timeout → failure, no raise
