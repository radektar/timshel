"""Tests for the stance-flip contradiction channel."""

from __future__ import annotations

from pathlib import Path

from src.connections.candidate_assembly import NoteRef
from src.connections.stance import (
    _has_cue,
    parse_stances,
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


def test_no_is_not_a_negator_in_polish():
    # "no" is an affirmative filler in Polish; it must not invert the sign.
    assert polarity_score("no dobra, warto to zrobić") > 0


def test_business_words_not_false_negative():
    # "zł" (currency), "strategia" must NOT read as negative anymore.
    assert polarity_score("budżet 5000 zł, dobra strategia inwestycji") >= 0
    assert polarity_score("złożyć wniosek o dotację") == 0.0


def test_negation_scope_three_tokens():
    # "nie jest to dobry" — negator is 3 tokens before the valence word.
    assert polarity_score("nie jest to dobry pomysł") < 0
    assert polarity_score("to jest dobry pomysł") > 0


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


_V2 = (
    "## Podsumowanie\n\nTreść.\n\n"
    "## Stanowiska\n\n"
    "- [[Fundacja Ziemi]] ✅ warto założyć, daje niezależność\n"
    "- [[Kredyt hipoteczny]] ❌ za duże ryzyko\n"
    "- Moduły ścienne 🔄 zmiana zdania — jednak tak\n\n"
    "## Wątki otwarte\n\n- Czy X?\n"
)


class TestParseStances:
    def test_parses_markers_subjects_and_section_bounds(self):
        stances = parse_stances(_V2)
        assert [(s.subject, s.polarity, s.changed) for s in stances] == [
            ("Fundacja Ziemi", 1, False),
            ("Kredyt hipoteczny", -1, False),
            ("Moduły ścienne", 0, True),  # unbracketed subject accepted
        ]

    def test_pre_v2_note_returns_empty(self):
        assert parse_stances("## Podsumowanie\n\nStara notatka bez sekcji.\n") == []

    def test_english_heading_supported(self):
        stances = parse_stances("## Stances\n\n- [[Impact Log]] ✅ good\n")
        assert [s.subject for s in stances] == ["Impact Log"]

    def test_keys_are_inflection_tolerant(self):
        (fundacja, *_), _ = parse_stances(_V2), None
        # "Fundacji Ziemi" (genitive) must share keys with "Fundacja Ziemi".
        other = parse_stances("## Stanowiska\n\n- [[Fundacji Ziemi]] ❌ jednak nie\n")
        assert fundacja.keys & other[0].keys


class TestStructuredTier:
    def test_opposite_stances_pair_across_inflection(self):
        window = [
            _note("newer", "2026-06-20", "## Stanowiska\n\n- [[Fundacji Ziemi]] ❌ x\n")
        ]
        hit = _note(
            "older_flip", "2026-02-01", "## Stanowiska\n\n- [[Fundacja Ziemi]] ✅ y\n"
        )
        same = _note(
            "older_same", "2026-02-01", "## Stanowiska\n\n- [[Fundacja Ziemi]] ❌ z\n"
        )
        res = stance_flip_neighbors(window, [same, hit], set(), 3)
        assert res[0].basename == "older_flip"
        # Same-polarity note may only arrive via the lexicon fallback, never
        # as a structured pair; with these bare summaries it does not pair.
        assert all(n.basename != "older_same" for n in res)

    def test_changed_mind_pairs_with_any_prior_stance(self):
        window = [
            _note("newer", "2026-06-20", "## Stanowiska\n\n- [[Moon 8]] 🔄 zmiana\n")
        ]
        prior = _note(
            "older", "2026-02-01", "## Stanowiska\n\n- [[Moon 8]] ✅ świetny kierunek\n"
        )
        res = stance_flip_neighbors(window, [prior], set(), 3)
        assert [n.basename for n in res] == ["older"]

    def test_structured_outranks_lexicon(self):
        # Window: structured ❌ on Fundacja Ziemi AND prose that the lexicon
        # could pair with older_lex. The structured hit must come first.
        window = [
            _note(
                "newer",
                "2026-06-20",
                "Bank Ochrony Środowiska to zły wybór, same problemy.\n\n"
                "## Stanowiska\n\n- [[Fundacja Ziemi]] ❌ rezygnuję\n",
            )
        ]
        structured_hit = _note(
            "older_struct",
            "2026-01-01",
            "## Stanowiska\n\n- [[Fundacja Ziemi]] ✅ tak\n",
        )
        lexicon_hit = _note(
            "older_lex",
            "2026-02-01",
            "Bank Ochrony Środowiska to dobry wybór, warto i sensownie",
        )
        res = stance_flip_neighbors(window, [lexicon_hit, structured_hit], set(), 2)
        assert [n.basename for n in res] == ["older_struct", "older_lex"]

    def test_no_structured_stances_falls_back_to_lexicon(self):
        window = [_note("w", "2026-06-20", "Bank Ochrony Środowiska to zły wybór")]
        older = [
            _note("o", "2026-02-01", "Bank Ochrony Środowiska to dobry wybór, warto")
        ]
        assert [n.basename for n in stance_flip_neighbors(window, older, set(), 3)] == [
            "o"
        ]

    def test_structured_respects_exclude_and_cap(self):
        window = [
            _note("newer", "2026-06-20", "## Stanowiska\n\n- [[Fundacja Ziemi]] ❌ x\n")
        ]
        a = _note("a", "2026-01-01", "## Stanowiska\n\n- [[Fundacja Ziemi]] ✅ y\n")
        b = _note("b", "2026-02-01", "## Stanowiska\n\n- [[Fundacja Ziemi]] ✅ z\n")
        assert stance_flip_neighbors(window, [a, b], {"a", "b"}, 3) == []
        assert len(stance_flip_neighbors(window, [a, b], set(), 1)) == 1


def test_cue_does_not_pair_neutral_older_note():
    # A change-cue in the window must NOT pair an older note that holds no
    # stance (neutral) — that would flood the channel with non-contradictions.
    window = [_note("w", "2026-06-20", "Zmieniłem zdanie o Bank Ochrony Środowiska")]
    neutral = _note(
        "neutral", "2026-02-01", "Bank Ochrony Środowiska — notatka ze spotkania"
    )
    opinion = _note(
        "opinion", "2026-02-01", "Bank Ochrony Środowiska to świetny wybór, warto"
    )
    res = stance_flip_neighbors(window, [neutral, opinion], set(), 3)
    assert [n.basename for n in res] == ["opinion"]  # neutral dropped
