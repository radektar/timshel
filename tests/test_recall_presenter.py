"""Presenter for the recall results surface: ranking, per-note cap, abstinence."""

from __future__ import annotations

from src.connections.recall.retriever import Result
from src.ui import recall_presenter as rp


def _res(note_id, quote, score=0.5, channels="dense"):
    return Result(
        note_id=note_id, quote=quote, parent_text=quote,
        char_start=0, char_end=len(quote), score=score, channels=channels,
    )


def test_split_stem_parses_date_prefix():
    assert rp.split_stem("26-06-17 - Haetta - rozmowa z konstruktorem") == (
        "26-06-17", "Haetta - rozmowa z konstruktorem")
    assert rp.split_stem("26-04-20 – Projekt bez daty") == ("26-04-20", "Projekt bez daty")


def test_split_stem_without_date_keeps_whole_title():
    assert rp.split_stem("okna") == ("", "okna")


def test_trim_quote_normalizes_and_caps():
    assert rp.trim_quote("  wiele   spacji \n i nowa linia ") == "wiele spacji i nowa linia"
    long = " ".join(["slowo"] * 100)
    out = rp.trim_quote(long, limit=40)
    assert len(out) <= 41 and out.endswith("…") and "  " not in out


def test_present_ranks_maps_fields_and_caps_per_note():
    results = [
        _res("26-06-05 - Planowanie budowy domu - materialy okna dach", "dostawa okien niepewna"),
        _res("26-06-05 - Planowanie budowy domu - materialy okna dach", "dach stoi w miejscu"),
        _res("26-06-05 - Planowanie budowy domu - materialy okna dach", "trzeci fragment tej samej noty"),
        _res("26-06-17 - Haetta - rozmowa z konstruktorem", "nosnosc belek"),
    ]
    vm = rp.present("co z oknami", results, confidence=0.82, per_note_cap=2)
    assert not vm.is_empty
    assert [r.rank for r in vm.rows] == [1, 2, 3]           # continuous 1-based ranks
    assert sum(r.note_id.startswith("26-06-05") for r in vm.rows) == 2  # capped at 2
    top = vm.rows[0]
    assert top.date == "26-06-05"
    assert top.title == "Planowanie budowy domu - materialy okna dach"
    assert top.quote == "dostawa okien niepewna"
    assert top.channels == "dense"


def test_present_respects_max_rows():
    results = [_res(f"26-01-0{i} - Nota {i}", f"fragment {i}") for i in range(1, 9)]
    vm = rp.present("q", results, confidence=0.9, max_rows=3)
    assert vm.count == 3


def test_present_abstains_below_floor_and_surfaces_nearest():
    results = [_res("26-01-01 - Cos luzno powiazanego", "odlegly fragment")]
    vm = rp.present("pozwolenie na budowe", results, confidence=0.31, floor=0.55)
    assert vm.is_empty
    assert vm.rows == []
    assert vm.nearest is not None and vm.nearest.dimmed
    assert vm.nearest.title == "Cos luzno powiazanego"


def test_present_abstains_on_no_hits():
    vm = rp.present("cokolwiek", [], confidence=0.0)
    assert vm.is_empty and vm.nearest is None and vm.count == 0


def test_confidence_is_carried_through():
    vm = rp.present("q", [_res("n", "t")], confidence=0.77)
    assert vm.confidence == 0.77


def test_abstinence_boundary_at_default_floor():
    """The calibrated 0.60 cutoff is the crux of honest abstinence — guard it."""
    r = [_res("26-01-01 - Nota", "fragment")]
    f = rp.DEFAULT_ABSTAIN_FLOOR
    assert rp.present("q", r, f).is_empty is False       # == floor → shows (strict <)
    assert rp.present("q", r, f - 0.001).is_empty is True  # just below → abstains
