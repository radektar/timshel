"""Wiring tests for the menu app's Insights glue — the badge count and the
digest-ready notification. This logic (deck → title, top connection →
notification body) was previously untested; it is the aparatura the
insight→action phase extends, so it needs coverage."""

from __future__ import annotations

from types import SimpleNamespace

import src.menu_app as ma
import src.ui.insight_pipeline as ip
from src.menu_app import TimshelMenuApp
from src.ui import insight_model as im


def _app():
    return TimshelMenuApp.__new__(TimshelMenuApp)


def test_refresh_badge_shows_unseen_count(monkeypatch):
    monkeypatch.setattr(ip, "latest_deck", lambda: SimpleNamespace(unseen_count=3))
    app = _app()
    app.insights_item = SimpleNamespace(title="")
    app._refresh_insights_badge()
    assert app._unseen_insights == 3
    assert app.insights_item.title == "Insights (3)"


def test_refresh_badge_plain_when_no_digest(monkeypatch):
    monkeypatch.setattr(ip, "latest_deck", lambda: None)
    app = _app()
    app.insights_item = SimpleNamespace(title="stale")
    app._refresh_insights_badge()
    assert app._unseen_insights == 0
    assert app.insights_item.title == "Insights"  # no "(0)" noise


def test_notify_digest_lands_top_connection_thesis(monkeypatch):
    conn = im.make_connection(
        im.SHARED, "the tension sentence", ["A", "B"], ["A: ?", "B: ?"]
    )
    monkeypatch.setattr(ip, "latest_deck", lambda: im.InsightDeck([conn]))
    seen = {}
    monkeypatch.setattr(ma, "send_notification", lambda *a: seen.update(args=a))
    _app()._notify_digest_ready("digest.md")
    assert seen["args"][0] == "Timshel"
    assert seen["args"][1] == conn.resolved_label()
    assert seen["args"][2] == "the tension sentence"


def test_notify_digest_falls_back_without_deck(monkeypatch):
    monkeypatch.setattr(ip, "latest_deck", lambda: None)
    seen = {}
    monkeypatch.setattr(ma, "send_notification", lambda *a: seen.update(args=a))
    _app()._notify_digest_ready("digest.md")
    assert seen["args"] == ("Timshel", "New synthesis digest ready", "digest.md")


# --- monthly AI-hours line -------------------------------------------------


def _usage_app(tmp_path, monkeypatch):
    from src.config import config as global_config

    monkeypatch.setattr(global_config, "USAGE_LEDGER_FILE", tmp_path / "ledger.json")
    monkeypatch.setattr(global_config, "AI_HOURS_BUDGET", 30)
    app = _app()
    app.ai_usage_item = SimpleNamespace(title="AI this month: —")
    app._ai_usage_key = ()
    return app


def test_ai_usage_line_shows_hours_against_budget(tmp_path, monkeypatch):
    from src import usage_ledger

    app = _usage_app(tmp_path, monkeypatch)
    usage_ledger.add_ai_seconds(4520)  # 1h 15m

    app._refresh_ai_usage()
    assert app.ai_usage_item.title == "AI this month: 1h 15m / 30h"


def test_ai_usage_line_before_any_usage(tmp_path, monkeypatch):
    app = _usage_app(tmp_path, monkeypatch)
    app._refresh_ai_usage()
    assert app.ai_usage_item.title == "AI this month: 0m / 30h"


def test_ai_usage_line_skips_reread_until_ledger_changes(tmp_path, monkeypatch):
    """The 2s status tick must not re-read JSON for an unchanged number."""
    from src import usage_ledger

    app = _usage_app(tmp_path, monkeypatch)
    usage_ledger.add_ai_seconds(600)
    app._refresh_ai_usage()

    reads = []
    real_read = usage_ledger.read_usage
    monkeypatch.setattr(
        usage_ledger,
        "read_usage",
        lambda *a, **kw: (reads.append(1), real_read(*a, **kw))[1],
    )
    app._refresh_ai_usage()
    assert reads == []


def test_ai_usage_line_resets_when_the_month_flips(tmp_path, monkeypatch):
    """The ledger resets lazily ON READ, and nothing writes the file on the
    1st — keyed on mtime alone the menu would show last month's total forever."""
    from src import usage_ledger

    app = _usage_app(tmp_path, monkeypatch)
    usage_ledger.add_ai_seconds(28 * 3600)
    app._refresh_ai_usage()
    assert app.ai_usage_item.title == "AI this month: 28h 0m / 30h"

    monkeypatch.setattr(usage_ledger, "current_month", lambda *a, **kw: "2099-01")
    app._refresh_ai_usage()
    assert app.ai_usage_item.title == "AI this month: 0m / 30h"
