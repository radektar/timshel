"""Pure tests for proper-noun + wikilink entity extraction."""

from __future__ import annotations

from src.connections.entities import extract_entities


def test_wikilink_target_extracted_alias_stripped():
    ents = extract_entities("see [[Radek Taraszka|Radek]] and [[Tech to the Rescue]]")
    assert "radek taraszka" in ents
    assert "tech to the rescue" in ents


def test_multiword_proper_noun_run():
    ents = extract_entities("Spotkanie z Bank Ochrony Środowiska w środę.")
    assert "bank ochrony środowiska" in ents


def test_sentence_initial_capital_is_not_an_entity():
    # "Wczoraj" / "Dzisiaj" start sentences — lone capitals must not register.
    ents = extract_entities("Wczoraj padało. Dzisiaj jest słonecznie.")
    assert ents == set()


def test_lowercase_connector_breaks_a_run_use_wikilink_instead():
    # In free text a lowercase connector ends the run (Polish-safety); the full
    # English name survives only when written as a wikilink.
    assert "bank of england" not in extract_entities("The Bank of England moved.")
    assert "bank of england" in extract_entities("[[Bank of England]] moved.")


def test_polish_diacritics_in_entity():
    ents = extract_entities("Rozmowa z Łukasz Żółć była długa.")
    assert "łukasz żółć" in ents


def test_case_and_whitespace_normalised():
    a = extract_entities("[[Ośmiu   Księżyców]]")
    b = extract_entities("[[ośmiu księżyców]]")
    assert a == b == {"ośmiu księżyców"}


def test_shared_entity_across_two_notes_matches():
    n1 = extract_entities("Decyzja z Bank Ochrony Środowiska w marcu.")
    n2 = extract_entities("Wracam do ustaleń Bank Ochrony Środowiska — zmiana zdania.")
    assert "bank ochrony środowiska" in (n1 & n2)


def test_entity_keys_match_across_polish_inflection():
    from src.connections.entities import entity_keys

    # 'Fundacja Ziemi' (mianownik) vs 'Fundacji Ziemi' (dopełniacz) — exact
    # forms differ, stemmed keys must match.
    a = entity_keys("Rozmowa o [[Fundacja Ziemi]] wczoraj.")
    b = entity_keys("Wracam do pomysłu [[Fundacji Ziemi]] — zmiana zdania.")
    assert a & b, f"no shared key: {a} vs {b}"


def test_entity_keys_do_not_overmerge_distinct_names():
    from src.connections.entities import entity_keys

    a = entity_keys("[[Radek Taraszka]]")
    b = entity_keys("[[Radek Tarnowski]]")
    assert not (a & b)
