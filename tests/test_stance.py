"""Tests for the stance-flip contradiction channel."""

from __future__ import annotations

from pathlib import Path

from src.connections.candidate_assembly import NoteRef
from src.connections.stance import (
    _has_cue,
    polarity_score,
    stance_flip_neighbors,
)


def test_polarity_positive_negative_neutral():
    assert polarity_score("to jest świetny pomysł, zdecydowanie warto") > 0
    assert polarity_score("to zły pomysł, same problemy i ryzyko") < 0
    assert polarity_score("spotkanie odbyło się o dziesiątej") == 0.0


def test_polarity_negation_flips_sign():
    # "nie warto" should read negative despite containing a positive stem base.
    assert polarity_score("nie warto tego robić") < 0
    assert polarity_score("nie widzę problemu") > 0  # negated negative -> positive


def test_change_cue_detection():
    assert _has_cue("zmieniłem zdanie w tej sprawie")
    assert _has_cue("już nie chcę tego robić")
    assert _has_cue("I no longer think so")
    assert not _has_cue("zwykła notatka bez zwrotu")


def _note(basename, date, summary, tags=()):
    return NoteRef(
        md_path=Path(f"/x/{basename}.md"),
        basename=basename,
        title=basename,
        date=date,
        tags=list(tags),
        norm_tags=set(tags),
        summary_md=summary,
        fingerprint="",
    )


def test_stance_flip_pairs_on_shared_entity_opposite_polarity():
    window = [
        _note(
            "newer",
            "2026-06-20",
            "Fundacja Ziemi to jednak zły kierunek, rezygnuję z tego pomysłu",
        )
    ]
    hit = _note(
        "older_flip",
        "2026-02-01",
        "Fundacja Ziemi to świetny pomysł, zdecydowanie warto ją założyć",
    )
    miss = _note(
        "older_same",
        "2026-02-01",
        "Ogród warzywny i kompost, oddzielny temat bez związku",
    )
    res = stance_flip_neighbors(window, [miss, hit], exclude=set(), max_n=3)
    assert [n.basename for n in res] == ["older_flip"]


def test_stance_respects_exclude_and_zero():
    window = [_note("w", "2026-06-20", "Bank Ochrony Środowiska to zły wybór")]
    older = [_note("o", "2026-02-01", "Bank Ochrony Środowiska to dobry wybór, warto")]
    assert stance_flip_neighbors(window, older, {"o"}, 3) == []  # excluded
    assert stance_flip_neighbors(window, older, set(), 0) == []  # channel off


def test_stance_no_anchor_no_pairs():
    window = [_note("w", "2026-06-20", "zły pomysł, ryzyko")]
    older = [_note("o", "2026-02-01", "świetny pomysł, warto")]
    # no shared entity/tag anchor -> no pairing even with opposite polarity
    assert stance_flip_neighbors(window, older, set(), 3) == []
