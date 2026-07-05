"""Proper-noun + wikilink entity extraction for the preselection entity channel.

Challenge #3 of the insights strategy: a contradiction months apart is often
*not* semantically similar — the vocabulary drifts, so BM25 and tag overlap miss
it. What survives the drift is the shared **entity**: the person, project,
organisation, or product the two notes both talk about. This module pulls those
entities out cheaply (regex only, no NER dependency, Polish-aware) so a
preselection channel can join notes on shared entities rather than shared words.

Two signals, both robust to sentence-start capitalisation (the Polish trap where
every sentence-initial word looks like a proper noun):

* **Wikilinks** ``[[Target|alias]]`` — an explicit, unambiguous entity reference.
* **Multi-word capitalised runs** ("Tech to the Rescue", "Radek Taraszka") — a
  run of ≥2 capitalised tokens is a proper noun with very high precision; a lone
  sentence-initial capital never forms one.

Single-word proper nouns are deliberately *not* harvested here — they are noisy
in Polish, and the rare-token bridge channel already catches specific one-word
entities. This channel is the complement, not a replacement.
"""

from __future__ import annotations

import re
from typing import Set

# A capitalised token: one uppercase letter (incl. Polish) then lowercase tail.
# A run is >=2 such tokens back-to-back ("Bank Ochrony Środowiska", "Radek
# Taraszka"). We deliberately do NOT bridge lowercase connectors (of/the, PL
# z/na/w): in Polish a sentence-initial capital + "z"/"w" would glue an ordinary
# sentence opener onto the real name ("Spotkanie z Bank…" -> the whole run).
# Names that genuinely contain lowercase connectors ("Tech to the Rescue") are
# caught precisely via their wikilink instead.
_CAP = r"[A-ZĄĆĘŁŃÓŚŹŻ][a-ząćęłńóśźż]+"
# Separator is spaces/tabs only, never a newline: a run must stay within one
# line, so a markdown heading ("## Podsumowanie") on the line above can't glue
# itself onto the name below.
_RUN_RE = re.compile(rf"{_CAP}(?:[ \t]+{_CAP})+")
_WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")

# Runs shorter than this (after normalisation) are dropped as noise.
_MIN_ENTITY_CHARS = 4


def _normalize(entity: str) -> str:
    """Casefold + collapse whitespace so the same entity matches across notes."""
    return re.sub(r"\s+", " ", entity).strip().casefold()


def extract_entities(text: str) -> Set[str]:
    """Return the normalised entity set of ``text``.

    Entities are wikilink targets (alias stripped) plus multi-word capitalised
    runs. All normalised to a casefolded, whitespace-collapsed key so the same
    name in two notes compares equal regardless of case or spacing.
    """
    entities: Set[str] = set()

    for raw in _WIKILINK_RE.findall(text):
        target = raw.split("|", 1)[0]  # [[Target|alias]] -> Target
        norm = _normalize(target)
        if len(norm) >= _MIN_ENTITY_CHARS:
            entities.add(norm)

    # Strip wikilink brackets before scanning runs so "[[Foo Bar]]" isn't also
    # counted as a raw run (it's already captured above).
    without_links = _WIKILINK_RE.sub(" ", text)
    for match in _RUN_RE.finditer(without_links):
        tokens = match.group(0).split()
        _add_entity(entities, tokens)
        # A run that opens a sentence may have glued a sentence-initial capital
        # ("Ustalenia") onto the real name ("Bank Ochrony Środowiska"). We can't
        # tell which, so keep the full run AND add the name-without-opener form,
        # so the same name matches whether or not it opened a sentence elsewhere.
        # Keep newlines when probing the prefix (a run right after a line break
        # opens a "sentence" too); only trailing spaces/tabs are irrelevant.
        prefix = without_links[: match.start()].rstrip(" \t")
        sentence_initial = (not prefix) or prefix[-1] in ".!?\n"
        if sentence_initial and len(tokens) >= 3:
            _add_entity(entities, tokens[1:])

    return entities


def _add_entity(entities: Set[str], tokens: list) -> None:
    if len(tokens) < 2:
        return
    norm = _normalize(" ".join(tokens))
    if len(norm) >= _MIN_ENTITY_CHARS:
        entities.add(norm)
