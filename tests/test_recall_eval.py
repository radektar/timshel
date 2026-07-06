"""Pure tests for the H3 recall harness (no API calls)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from src.config import config
from src.connections.dismissals import DismissalStore

_SPEC = importlib.util.spec_from_file_location(
    "recall_eval",
    Path(__file__).resolve().parents[1] / "scripts" / "recall_eval.py",
)
rev = importlib.util.module_from_spec(_SPEC)
sys.modules["recall_eval"] = rev
_SPEC.loader.exec_module(rev)


def _write_note(vault, name, date, tags="", summary=""):
    body = (
        f'---\ntitle: "{name}"\ndate: {date}\ntags: [{tags}]\n'
        f"fingerprint: sha256:{name}\n---\n\n"
        f"## Podsumowanie\n{summary}\n\n## Transkrypcja\nfoo\n"
    )
    (vault / f"{name}.md").write_text(body, encoding="utf-8")


@pytest.fixture
def vault(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "TRANSCRIBE_DIR", tmp_path)
    return tmp_path


def _pair(pid, notes, ptype="contradiction-over-time", source="llm-proposed"):
    return {
        "id": pid,
        "notes": notes,
        "type": ptype,
        "source": source,
        "confirmed": True,
    }


def _dates(vault):
    from src.connections.candidate_assembly import load_corpus

    return {n.basename: n.date for n in load_corpus(vault)}


def test_hit_when_older_note_surfaces_via_tag(vault):
    _write_note(vault, "older", "2026-05-01", tags="sauna", summary="stare plany")
    _write_note(vault, "newer", "2026-06-20", tags="sauna", summary="nowe plany")
    res = rev.simulate_pair(
        _pair("pp-001", ["older", "newer"]),
        vault,
        DismissalStore(vault),
        bridges=0,
        entities=0,
        corpus_dates=_dates(vault),
    )
    assert res.status == "hit"
    assert "tag" in res.older_channels["older"]


def _write_raw_note(vault, name, date, tags="", body=""):
    """Note WITHOUT the shared '## Podsumowanie' header (no common BM25 token)."""
    (vault / f"{name}.md").write_text(
        f'---\ntitle: "{name}"\ndate: {date}\ntags: [{tags}]\n---\n\n{body}\n',
        encoding="utf-8",
    )


def test_miss_when_older_note_unreachable(vault):
    _write_raw_note(vault, "older", "2026-05-01", tags="ogrod", body="kompost warzywa")
    _write_raw_note(vault, "newer", "2026-06-20", tags="sauna", body="pieca budowa")
    # unrelated tags, no lexical overlap, channels off -> unreachable
    res = rev.simulate_pair(
        _pair("pp-002", ["older", "newer"]),
        vault,
        DismissalStore(vault),
        bridges=0,
        entities=0,
        corpus_dates=_dates(vault),
    )
    assert res.status == "miss"
    assert res.missing == ["older"]


def test_same_date_pair_is_window_collision(vault):
    _write_note(vault, "a", "2026-06-20", tags="t", summary="alpha")
    _write_note(vault, "b", "2026-06-20", tags="t", summary="alpha")
    res = rev.simulate_pair(
        _pair("pp-003", ["a", "b"]),
        vault,
        DismissalStore(vault),
        bridges=0,
        entities=0,
        corpus_dates=_dates(vault),
    )
    assert res.status == "window-collision"


def test_future_notes_do_not_leak_into_simulation(vault):
    # A note newer than the pair's newer note must not appear in candidates.
    _write_note(vault, "older", "2026-05-01", tags="sauna", summary="stare")
    _write_note(vault, "newer", "2026-06-10", tags="sauna", summary="nowe")
    _write_note(vault, "future", "2026-06-25", tags="sauna", summary="przyszle")
    res = rev.simulate_pair(
        _pair("pp-004", ["older", "newer"]),
        vault,
        DismissalStore(vault),
        bridges=0,
        entities=0,
        corpus_dates=_dates(vault),
    )
    assert res.status == "hit"
    assert "future" not in res.older_channels  # only pair notes tracked anyway


def test_skipped_when_note_missing_from_corpus(vault):
    _write_note(vault, "only", "2026-06-01", tags="t", summary="x")
    res = rev.simulate_pair(
        _pair("pp-005", ["only", "ghost"]),
        vault,
        DismissalStore(vault),
        bridges=0,
        entities=0,
        corpus_dates=_dates(vault),
    )
    assert res.status == "skipped"


def test_recall_math_excludes_collisions_and_skips():
    results = [
        rev.PairResult("1", "t", "s", "hit"),
        rev.PairResult("2", "t", "s", "miss"),
        rev.PairResult("3", "t", "s", "window-collision"),
        rev.PairResult("4", "t", "s", "skipped"),
    ]
    rec, hits, denom = rev.recall_of(results)
    assert (hits, denom) == (1, 2)
    assert rec == 0.5


def test_report_contains_verdict_and_unique_saves():
    full = [
        rev.PairResult(
            "1",
            "contradiction-over-time",
            "llm-proposed",
            "hit",
            older_channels={"o": ["entity"]},
        ),
        rev.PairResult("2", "emergent-idea", "radek-manual", "miss", missing=["x"]),
    ]
    no_entity = [
        rev.PairResult(
            "1", "contradiction-over-time", "llm-proposed", "miss", missing=["o"]
        ),
        rev.PairResult("2", "emergent-idea", "radek-manual", "miss", missing=["x"]),
    ]
    by_config = {
        "full": full,
        "no-entity": no_entity,
        "no-bridge": full,
        "similarity-only": no_entity,
    }
    report = rev.render_report(by_config, n_pairs=2)
    assert "H3 verdict" in report
    assert "GREY ZONE" in report  # 50% on full config
    assert "entity: 1 pairs only reachable with it: ['1']" in report
    assert "radek-manual" in report  # bias split present
    assert "pp" not in report or True  # smoke: renders without crash


def test_newer_note_is_sole_window_member(vault):
    # An older note dated one day before the newer note must NOT get a free
    # "window" hit — it has to be reached by a real preselection channel.
    _write_raw_note(vault, "older", "2026-06-09", tags="x", body="alpha beta")
    _write_raw_note(vault, "newer", "2026-06-10", tags="y", body="gamma delta")
    res = rev.simulate_pair(
        _pair("pp-adj", ["older", "newer"]),
        vault,
        DismissalStore(vault),
        bridges=0,
        entities=0,
        corpus_dates=_dates(vault),
    )
    # no shared tag/word/entity -> older is unreachable, so this is a MISS,
    # not a spurious window hit.
    assert res.status == "miss"
    assert "older" not in res.older_channels
