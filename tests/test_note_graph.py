"""Pure tests for the note-term graph + Personalized PageRank (no domain deps)."""

from __future__ import annotations

from src.connections.note_graph import NoteGraph, _in_band


def test_ppr_reaches_two_hop_note_sharing_no_direct_term():
    # A (seed) shares term X with B; B shares term Y with C. A and C share NO
    # term directly. PPR must still reach C through the A-B-C chain.
    note_terms = {
        "A": {"X": 1.0},
        "B": {"X": 1.0, "Y": 1.0},
        "C": {"Y": 1.0},
        "Z": {"Q": 1.0},  # disconnected
    }
    scores = NoteGraph(note_terms).ppr(["A"])
    assert "B" in scores and "C" in scores
    assert "Z" not in scores  # unreachable
    assert scores["B"] > scores["C"]  # one hop beats two hops
    assert "A" not in scores  # seed excluded from its own result


def test_ppr_empty_on_empty_seed_or_graph():
    g = NoteGraph({"A": {"X": 1.0}, "B": {"X": 1.0}})
    assert g.ppr([]) == {}
    assert g.ppr(["missing"]) == {}
    assert NoteGraph({}).ppr(["A"]) == {}


def test_ppr_weights_favour_stronger_bridge():
    # B shares a HEAVY term with the seed, C a light one -> B ranks higher.
    note_terms = {
        "A": {"heavy": 3.0, "light": 1.0},
        "B": {"heavy": 3.0},
        "C": {"light": 1.0},
    }
    scores = NoteGraph(note_terms).ppr(["A"])
    assert scores["B"] > scores["C"]


def test_multi_seed_aggregates():
    note_terms = {
        "S1": {"X": 1.0},
        "S2": {"Y": 1.0},
        "T": {"X": 1.0, "Y": 1.0},  # shared by both seeds
        "U": {"X": 1.0},  # only S1
    }
    scores = NoteGraph(note_terms).ppr(["S1", "S2"])
    assert scores["T"] > scores["U"]  # reachable from both seeds


def test_in_band():
    assert _in_band(2, (2, 8)) and _in_band(8, (2, 8))
    assert not _in_band(1, (2, 8)) and not _in_band(9, (2, 8))


def test_build_note_terms_band_filters(tmp_path):
    from src.connections.candidate_assembly import load_corpus

    # 'wspolny' appears in 3 notes (in band), a unique word appears once (out).
    for i in range(3):
        (tmp_path / f"n{i}.md").write_text(
            f"---\ntitle: n{i}\ndate: 2026-06-0{i+1}\ntags: [wspolnytag]\n---\n\n"
            f"## Podsumowanie\nwspolny motyw oraz unikalne{i} slowo tutaj\n\n"
            f"## Transkrypcja\nx\n",
            encoding="utf-8",
        )
    from src.connections.note_graph import build_note_terms

    corpus = load_corpus(tmp_path)
    nt = build_note_terms(corpus)
    all_terms = set().union(*nt.values())
    assert any(t.startswith("t:wspolny") for t in all_terms)  # df=3, in band
    assert any(t.startswith("g:wspolnytag") for t in all_terms)  # tag df=3
    assert not any("unikalne" in t for t in all_terms)  # df=1, out of band
