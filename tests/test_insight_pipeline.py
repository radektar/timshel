"""Tests for the digest→window bridge (src/ui/insight_pipeline.py)."""

from __future__ import annotations

import json

from src.ui import insight_model as im
from src.ui import insight_pipeline as ip


def test_map_type_covers_synthesis_types():
    assert ip.map_type("contradiction-over-time") == im.CONTRADICTION
    assert ip.map_type("shared-thread") == im.SHARED
    assert ip.map_type("emergent-idea") == im.EMERGENT
    # unknown / empty fall back rather than raising
    assert ip.map_type("mystery") == im.SHARED
    assert ip.map_type("") == im.SHARED


def test_connection_dict_to_insight_maps_fields():
    d = {
        "type": "contradiction-over-time",
        "notes": ["Note A", "Note B"],
        "rationale": "They disagree over time.",
        "directions": ["Why?", "What changed?"],
    }
    c = ip.connection_dict_to_insight(d)
    assert c.conn_type == im.CONTRADICTION
    assert c.notes == ("Note A", "Note B")
    assert c.directions == ("Why?", "What changed?")
    assert c.rationale == "They disagree over time."
    # layout follows the mapped type
    assert c.layout() == "contradiction"


def test_deck_from_dicts_builds_and_skips_malformed():
    dicts = [
        {"type": "shared-thread", "notes": ["A", "B"], "rationale": "r", "directions": ["x", "y"]},
        {"type": "emergent-idea", "notes": ["C"], "rationale": "too few notes"},  # skipped
        "not-a-dict",  # skipped
        {"type": "contradiction-over-time", "notes": ["D", "E"], "rationale": "r2", "directions": ["q"]},
    ]
    deck = ip.deck_from_dicts(dicts)
    assert len(deck) == 2
    assert [c.conn_type for c in deck.items] == [im.SHARED, im.CONTRADICTION]


def test_deck_from_dicts_empty():
    assert ip.deck_from_dicts([]).is_empty
    assert ip.deck_from_dicts(None).is_empty


def test_latest_deck_reads_sidecar(tmp_path, monkeypatch):
    sidecar = tmp_path / "insights-latest.json"
    sidecar.write_text(
        json.dumps(
            {
                "digest": "2026-06-26 Synthesis.md",
                "connections": [
                    {
                        "type": "emergent-idea",
                        "notes": ["A", "B", "C"],
                        "rationale": "An emergent idea.",
                        "directions": ["One?", "Two?"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(ip, "latest_insights_file", lambda: sidecar)
    deck = ip.latest_deck()
    assert deck is not None
    assert len(deck) == 1
    assert deck.active().conn_type == im.EMERGENT


def test_latest_deck_none_when_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(ip, "latest_insights_file", lambda: tmp_path / "nope.json")
    assert ip.latest_deck() is None


def test_latest_deck_none_on_garbage(tmp_path, monkeypatch):
    bad = tmp_path / "insights-latest.json"
    bad.write_text("{ not json", encoding="utf-8")
    monkeypatch.setattr(ip, "latest_insights_file", lambda: bad)
    assert ip.latest_deck() is None
