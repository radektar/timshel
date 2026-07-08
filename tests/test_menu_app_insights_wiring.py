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
