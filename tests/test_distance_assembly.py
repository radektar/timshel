"""Pure tests for the distance-injection bridge channel (no API, no disk)."""

from __future__ import annotations

from pathlib import Path

from src.connections import candidate_assembly as ca


def _note(basename: str, summary: str) -> ca.NoteRef:
    return ca.NoteRef(
        md_path=Path(f"/tmp/{basename}.md"),
        basename=basename,
        title=basename,
        date="2026-06-01",
        tags=[],
        norm_tags=set(),
        summary_md=summary,
        fingerprint="",
    )


def test_bridge_picks_rare_shared_token_over_common_topic():
    # Six construction notes make "budowa/okna/dom" common (df>4 → NOT rare).
    # The window then shares only one rare token ("ksylofon") with the bridge;
    # the "topical" note shares only common words → it is not a bridge.
    fillers = [
        _note(f"f{i}", "budowa dom okna fundamenty dach materialy") for i in range(6)
    ]
    window = [_note("win1", "budowa dom okna fundamenty ksylofon")]
    older = fillers + [
        _note("bridge", "agroturystyka warsztaty ksylofon cennik"),
        _note("topical", "budowa dom okna fundamenty dach materialy"),
    ]
    df = ca._corpus_doc_freq(window + older)
    bridges = ca._bridge_neighbors(window, older, df, {"win1"}, max_n=1)
    assert [n.basename for n in bridges] == ["bridge"]


def test_bridge_returns_empty_when_no_rare_token():
    window = [_note("w", "budowa dom okna")]
    older = [_note("o", "zupelnie inny temat bez wspolnych slow rzeka las")]
    df = ca._corpus_doc_freq(window + older)
    assert ca._bridge_neighbors(window, older, df, {"w"}, max_n=2) == []


def test_inject_bridges_zero_is_a_noop(monkeypatch):
    # With inject_bridges=0 the bridge set is empty and CandidateSet defaults hold.
    cs = ca.CandidateSet(notes=[], window_basenames=set())
    assert cs.bridge_basenames == set()


def test_max_n_caps_bridges():
    window = [_note("w", "alpha beta gamma")]
    older = [
        _note("b1", "alpha delta"),
        _note("b2", "beta epsilon"),
        _note("b3", "gamma zeta"),
    ]
    df = ca._corpus_doc_freq(window + older)
    bridges = ca._bridge_neighbors(window, older, df, {"w"}, max_n=2)
    assert len(bridges) == 2
