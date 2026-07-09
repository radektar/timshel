"""Thin tests for the blind cascade script — rendering + reveal parsing."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

from src.connections.synthesis import Connection, Evidence

_SPEC = importlib.util.spec_from_file_location(
    "blind_cascade_test",
    Path(__file__).resolve().parents[1] / "scripts" / "blind_cascade_test.py",
)
bct = importlib.util.module_from_spec(_SPEC)
sys.modules["blind_cascade_test"] = bct
_SPEC.loader.exec_module(bct)


def _conn(a, b):
    return Connection(
        type="emergent-idea",
        notes=[a, b],
        rationale="spina dwie notatki",
        evidence=[Evidence(note=a, date="2026-06-01", quote="cytat")],
        directions=["A: Czy mógłbyś...?", "B: Co by było...?"],
    )


def _result(key, conns, cost=0.5):
    return {
        "key": key,
        "mix": {"triage": None, "synthesis": "m", "verdict": None},
        "connections": conns,
        "n_candidates": 10,
        "verdict_dropped": 0,
        "cost_usd": cost,
        "tokens_in": 1000,
        "tokens_out": 100,
        "latency_s": 1.0,
    }


def test_rating_file_is_blind():
    shuffled = [
        _result("C", [_conn("n1", "n2")]),
        _result("A", [_conn("n3", "n4"), _conn("n5", "n6")]),
        _result("B", []),
    ]
    text = bct.render_rating_file(shuffled)
    # No model names, no costs, no condition keys as headers.
    assert "claude" not in text.lower()
    assert "cost" not in text.lower() and "$" not in text
    assert "## Digest I" in text and "## Digest III" in text
    assert text.count("ocena: ") == 3  # one per connection


def test_reveal_parses_scores_and_joins_key(tmp_path, capsys):
    ratings = tmp_path / "r.md"
    ratings.write_text(
        "## Digest I\n### I.1\nocena: 2\n### I.2\nocena: 0\n"
        "## Digest II\n### II.1\nocena: -1\n",
        encoding="utf-8",
    )
    key = tmp_path / "k.json"
    key.write_text(
        json.dumps(
            {
                "label_to_condition": {"I": "C", "II": "A"},
                "conditions": [
                    {
                        "key": "C",
                        "mix": {"triage": "h", "synthesis": "s", "verdict": "o"},
                        "cost_usd": 0.5,
                    },
                    {
                        "key": "A",
                        "mix": {"triage": None, "synthesis": "o", "verdict": None},
                        "cost_usd": 0.8,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    assert bct.reveal(ratings, key) == 0
    out = capsys.readouterr().out
    assert "Digest I = C" in out
    assert "mean=1.00" in out  # (2+0)/2
    assert "H4" in out and "PASS" in out  # 0.5 * 30/7 = 2.14 <= 2.60
