"""Pure tests for the planted-pairs bootstrap tool (no API calls)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from src.connections.signature import connection_signature

# Import the script as a module (scripts/ is not a package).
_SPEC = importlib.util.spec_from_file_location(
    "bootstrap_planted_pairs",
    Path(__file__).resolve().parents[1] / "scripts" / "bootstrap_planted_pairs.py",
)
bpp = importlib.util.module_from_spec(_SPEC)
sys.modules["bootstrap_planted_pairs"] = bpp
_SPEC.loader.exec_module(bpp)


def test_load_pairs_tolerant_and_roundtrip(tmp_path):
    p = tmp_path / "planted_pairs.json"
    data = bpp.load_pairs(p)  # missing file -> empty scaffold
    assert data["v"] == bpp.PAIRS_SCHEMA_VERSION
    assert data["pairs"] == []
    data["pairs"].append({"id": "pp-001", "notes": ["a", "b"], "sig": "x"})
    bpp.save_pairs(p, data)
    again = bpp.load_pairs(p)
    assert again["pairs"][0]["id"] == "pp-001"


def test_load_pairs_survives_corrupt_file(tmp_path):
    p = tmp_path / "planted_pairs.json"
    p.write_text("{not json", encoding="utf-8")
    data = bpp.load_pairs(p)
    assert data["pairs"] == []


def _pair(notes, ptype="emergent-idea", why="w"):
    return bpp.PlantedPair(notes=notes, type=ptype, why=why, evidence=[])


def test_filter_drops_hallucinated_basenames():
    kept, halluc, dups = bpp.filter_proposals(
        [_pair(["real1", "ghost"]), _pair(["real1", "real2"])],
        corpus_basenames={"real1", "real2"},
        known_sigs=set(),
        dismissed_sigs=set(),
    )
    assert [p.notes for p in kept] == [["real1", "real2"]]
    assert halluc == 1 and dups == 0


def test_filter_drops_dismissed_and_known_and_internal_dupes():
    a = _pair(["n1", "n2"], "contradiction-over-time")
    sig_a = connection_signature(a.notes, a.type)
    b = _pair(["n3", "n4"])
    sig_b = connection_signature(b.notes, b.type)
    twin = _pair(["n2", "n1"], "contradiction-over-time")  # same sig as a
    kept, _, dups = bpp.filter_proposals(
        [a, b, twin],
        corpus_basenames={"n1", "n2", "n3", "n4"},
        known_sigs={sig_b},  # b already in fixture
        dismissed_sigs={sig_a},  # a was dismissed in the app
    )
    assert kept == [] or all(
        connection_signature(p.notes, p.type) not in {sig_a, sig_b} for p in kept
    )
    assert dups >= 2


def test_filter_normalises_unknown_type():
    kept, _, _ = bpp.filter_proposals(
        [_pair(["n1", "n2"], ptype="totally-new-kind")],
        corpus_basenames={"n1", "n2"},
        known_sigs=set(),
        dismissed_sigs=set(),
    )
    assert kept[0].type == "emergent-idea"


def test_parse_proposals_lenient():
    payload = {
        "pairs": [
            {"notes": ["a", "b"], "type": "emergent-idea", "why": "ok"},
            {"notes": ["only-one"], "type": "emergent-idea", "why": "bad"},
            "garbage",
        ]
    }
    out = bpp._parse_proposals(payload)
    assert len(out.pairs) == 1
    assert bpp._parse_proposals("not-a-dict").pairs == []


def test_confirm_loop_saves_each_answer(tmp_path, monkeypatch):
    p = tmp_path / "planted_pairs.json"
    data = bpp.load_pairs(p)
    for i, conf in enumerate([None, None, None], 1):
        data["pairs"].append(
            {
                "id": f"pp-{i:03d}",
                "notes": [f"a{i}", f"b{i}"],
                "type": "emergent-idea",
                "why": "w",
                "evidence": [],
                "source": "llm-proposed",
                "confirmed": conf,
                "sig": f"s{i}",
            }
        )
    bpp.save_pairs(p, data)
    answers = iter(["t", "n", "q"])  # confirm 1, reject 2, quit before 3
    monkeypatch.setattr("builtins.input", lambda *_: next(answers))
    bpp.confirm_loop(p, data)
    on_disk = json.loads(p.read_text(encoding="utf-8"))["pairs"]
    assert on_disk[0]["confirmed"] is True
    assert on_disk[1]["confirmed"] is False
    assert on_disk[2]["confirmed"] is None  # untouched after quit


def test_add_manual_pair_sets_source_and_confirmed(tmp_path, monkeypatch):
    p = tmp_path / "planted_pairs.json"
    data = bpp.load_pairs(p)
    answers = iter(["noteA", "noteB", "", "", "bo tak"])
    monkeypatch.setattr("builtins.input", lambda *_: next(answers))
    bpp.add_manual_pair(p, data, corpus_basenames={"noteA", "noteB"})
    saved = json.loads(p.read_text(encoding="utf-8"))["pairs"]
    assert len(saved) == 1
    assert saved[0]["source"] == "radek-manual"
    assert saved[0]["confirmed"] is True
    assert saved[0]["type"] == "contradiction-over-time"  # default on empty
    assert saved[0]["sig"] == connection_signature(["noteA", "noteB"], saved[0]["type"])


def test_add_manual_pair_rejects_unknown_basename(tmp_path, monkeypatch):
    p = tmp_path / "planted_pairs.json"
    data = bpp.load_pairs(p)
    answers = iter(["ghost", "noteA", "noteB", "", "", "why"])
    monkeypatch.setattr("builtins.input", lambda *_: next(answers))
    bpp.add_manual_pair(p, data, corpus_basenames={"noteA", "noteB"})
    saved = json.loads(p.read_text(encoding="utf-8"))["pairs"]
    assert saved[0]["notes"] == ["noteA", "noteB"]  # ghost was re-prompted away


def test_normalize_basename_variants():
    n = bpp.normalize_basename
    assert n("26-07-01 - Zmiana nazwy") == "26-07-01 - Zmiana nazwy"
    assert n("[[26-07-01 - Zmiana nazwy]]") == "26-07-01 - Zmiana nazwy"
    assert n("11-Transcripts/26-07-01 - Zmiana nazwy.md") == "26-07-01 - Zmiana nazwy"
    # obsidian:// deep link, URL-encoded, with zsh-escaped \? and \&
    url = (
        "obsidian://open\\?vault=Obsidian\\&file=11-Transcripts%2F"
        "26-07-01%20-%20Zmiana%20nazwy%20projektu%20i%20poszukiwanie"
        "%20inspiracji%20literackiej"
    )
    assert (
        n(url) == "26-07-01 - Zmiana nazwy projektu i poszukiwanie inspiracji"
        " literackiej"
    )


def test_add_manual_pair_accepts_obsidian_link(tmp_path, monkeypatch):
    p = tmp_path / "planted_pairs.json"
    data = bpp.load_pairs(p)
    url = "obsidian://open?vault=Obsidian&file=11-Transcripts%2FnoteA"
    answers = iter([url, "[[noteB]]", "", "", "bo tak"])
    monkeypatch.setattr("builtins.input", lambda *_: next(answers))
    bpp.add_manual_pair(p, data, corpus_basenames={"noteA", "noteB"})
    saved = json.loads(p.read_text(encoding="utf-8"))["pairs"]
    assert saved[0]["notes"] == ["noteA", "noteB"]


def test_next_id_sequential(tmp_path):
    data = bpp.load_pairs(tmp_path / "x.json")
    assert bpp._next_id(data) == "pp-001"
    data["pairs"].append({"id": "pp-001"})
    assert bpp._next_id(data) == "pp-002"
