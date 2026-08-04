"""Deterministic guard for the ``[[Subject]]`` links in "## Stanowiska".

Why this exists: a stance subject is not decoration. Every ``[[Subject]]`` a
summary emits is harvested by :mod:`src.vocabulary` as a CONFIRMED glossary
term — ``wikilinked=True`` bypasses the recurrence threshold — and by
:mod:`src.connections.entities` as an entity key. So when the model brackets an
activity or a concept (observed in production: ``[[Assessment]]``,
``[[Automatyzacja rekomendacji]]``), the junk propagates outward: into whisper's
decoding prompt, into the summarizer's KNOWN TERMS block, and into the digest's
entity and stance channels.

The summarizer prompt forbids it and Haiku still does it (see STATE.md). This
module is the cheap net under the prompt: find bracketed subjects that cannot
plausibly be named entities and strip ONLY the brackets. The stance line itself
survives — :func:`src.connections.stance.parse_stances` reads a bracketless
subject too — so the contradiction channel loses nothing while the glossary
stops being poisoned. No API call, so this costs nothing per note.

Deliberately conservative: a false positive (de-bracketing a REAL name) costs
real signal, because a single-word entity reaches the entity channel ONLY via
its wikilink (capitalised-run harvesting needs two or more words). Hence the
glossary exemption, the internal-capital exemption and the length floor on the
suffix rule — the rules below fire on process language, not on names.

If the ``stance-subject de-bracketed`` warnings ever show real entities being
caught, that is the drift signal: escalate to a generalized correction-retry
through the summarizer, then to structured output (B2 in STATE.md).
"""

from __future__ import annotations

import re
from typing import Iterable, List, Optional, Set, Tuple

# Same section boundaries the digest parser uses. Shared on purpose: if the two
# ever disagreed, this guard would clean a region the parser does not read (or
# miss the one it does).
from src.connections.stance import _NEXT_SECTION_RE, _STANCE_SECTION_RE
from src.logger import logger
from src.vocabulary import VocabularyIndex

_WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")

# Lowercase words that legitimately sit inside a proper name ("Tech to the
# Rescue", "Bank of America"). Without this, every such name would trip the
# "non-initial word is lowercase" rule.
_PARTICLES = {
    "i",
    "w",
    "we",
    "na",
    "do",
    "z",
    "ze",
    "o",
    "od",
    "po",
    "dla",
    "the",
    "to",
    "of",
    "and",
    "for",
    "in",
    "on",
    "a",
    "an",
    # Name particles. Without these, "Maria de la Cruz" reads as "a lowercase
    # content word follows" and gets de-bracketed — and a person's name is
    # reachable by the entity channel ONLY via its wikilink (capitalised-run
    # harvesting skips lowercase connectors), so that loses it entirely.
    "de",
    "del",
    "della",
    "di",
    "da",
    "du",
    "el",
    "la",
    "le",
    "van",
    "von",
    "der",
    "den",
}

# Single words that are generic by definition — no recording is "about" them.
_GENERIC_SINGLE = {
    "pomysł",
    "pomysl",
    "projekt",
    "proces",
    "zespół",
    "zespol",
    "plan",
    "temat",
    "problem",
    "narzędzie",
    "narzedzie",
    "spotkanie",
    "rozmowa",
    "decyzja",
    "strategia",
    "praca",
    "idea",
    "plan",
    "tool",
    "process",
    "team",
    "project",
    "meeting",
    "topic",
    "problem",
    "decision",
    "strategy",
    "work",
}

# Deverbal endings — the morphology of "an activity in general" rather than of
# a name. PL first, then EN.
_DEVERBAL_SUFFIXES: Tuple[str, ...] = (
    "anie",
    "enie",
    "owanie",
    "acja",
    "cja",
    "zja",
    "tion",
    "sion",
    "ment",
    "ance",
    "ence",
    "ing",
)

# Length floor for the suffix rule. Short words ending this way are
# disproportionately real product names ("Notion", "Fusion", "Action"), long
# ones are almost always process language ("Assessment", "Automatyzacja").
_MIN_DEVERBAL_CHARS = 8


def _section_bounds(summary_md: str) -> Optional[Tuple[int, int]]:
    """Character span of the stance section's body, or None when absent."""
    match = _STANCE_SECTION_RE.search(summary_md)
    if not match:
        return None
    start = match.end()
    nxt = _NEXT_SECTION_RE.search(summary_md[start:])
    end = start + nxt.start() if nxt else len(summary_md)
    return start, end


def _glossary_keys(vocab: Optional[VocabularyIndex]) -> Set[str]:
    """Casefolded forms of the CURATED glossary only (``vocabulary.json``).

    Deliberately not the whole glossary. :mod:`src.vocabulary` harvests every
    ``[[wikilink]]`` a summary writes as a confirmed term — including the junk
    stance subjects this module exists to catch. Measured on a real note:
    ``[[Assessment]]`` and ``[[Automatyzacja rekomendacji]]`` were already IN
    the glossary, put there by that very note, so a whole-glossary exemption
    would have protected exactly the poison it is supposed to stop.

    Curated entries are the one layer the model did not author, so they are
    the one layer that can vouch for a name. Real entities that are merely
    harvested stay protected by the capitalisation rules below instead.
    """
    if vocab is None:
        return set()
    try:
        terms = vocab.build()
    except Exception as exc:  # noqa: BLE001 — a broken glossary must not block a note
        logger.warning("stance guard: glossary unavailable (%s)", exc)
        return set()
    keys: Set[str] = set()
    for term in terms.values():
        if not term.curated:
            continue
        keys.add(term.canonical.casefold())
        keys.update(alias.casefold() for alias in term.aliases)
    return keys


def _is_junk_subject(subject: str, glossary: Set[str]) -> bool:
    """True when *subject* cannot plausibly be a named entity."""
    text = subject.strip()
    if not text:
        return False

    # Anything the vault already confirmed as a term is a name by definition.
    if text.casefold() in glossary:
        return False

    words = text.split()

    # "proces doboru mentorów" — nothing capitalised, so nothing is a name.
    if text.islower():
        return True

    if len(words) > 1:
        # A real multi-word name capitalises every word that is not a particle
        # ("Fundacja Ziemi", "Tech to the Rescue"). A lowercase content word
        # means a phrase was bracketed ("Automatyzacja rekomendacji").
        for word in words[1:]:
            if word.casefold() in _PARTICLES:
                continue
            if word[:1].islower():
                return True
        return False

    # Single word from here on.
    # An internal capital marks a name, not a common noun: acronyms (TTTR, AI),
    # product spellings (iPhone), mangled proper names (TekTutoreski).
    if any(char.isupper() for char in text[1:]):
        return False

    low = text.casefold()
    if low in _GENERIC_SINGLE:
        return True
    if len(low) >= _MIN_DEVERBAL_CHARS and low.endswith(_DEVERBAL_SUFFIXES):
        return True
    return False


def find_junk_stance_subjects(
    summary_md: str, vocab: Optional[VocabularyIndex] = None
) -> List[str]:
    """Bracketed stance subjects that are activities/concepts, not entities.

    Args:
        summary_md: the generated summary markdown.
        vocab: personal glossary; terms and aliases in it are never flagged.

    Returns:
        Subjects in the order they appear, de-duplicated.
    """
    bounds = _section_bounds(summary_md)
    if not bounds:
        return []
    start, end = bounds
    glossary = _glossary_keys(vocab)

    junk: List[str] = []
    seen: Set[str] = set()
    for raw in _WIKILINK_RE.findall(summary_md[start:end]):
        target = raw.split("|", 1)[0].strip()  # [[Target|alias]] -> Target
        key = target.casefold()
        if key in seen:
            continue
        if _is_junk_subject(target, glossary):
            seen.add(key)
            junk.append(target)
    return junk


def debracket_stance_subjects(summary_md: str, subjects: Iterable[str]) -> str:
    """Rewrite ``[[S]]`` to ``S`` for *subjects*, inside the stance section only.

    Idempotent, and byte-identical outside the section — the rest of the note
    (quotes especially) must never be touched.
    """
    targets = {s.strip().casefold() for s in subjects if s.strip()}
    if not targets:
        return summary_md
    bounds = _section_bounds(summary_md)
    if not bounds:
        return summary_md
    start, end = bounds

    def _replace(match: re.Match) -> str:
        target = str(match.group(1)).split("|", 1)[0].strip()
        if target.casefold() in targets:
            return target
        return str(match.group(0))

    section = _WIKILINK_RE.sub(_replace, summary_md[start:end])
    return summary_md[:start] + section + summary_md[end:]


def guard_stance_subjects(
    summary_md: str, vocab: Optional[VocabularyIndex] = None
) -> str:
    """Find and de-bracket junk stance subjects; log what was caught.

    The WARNING is the drift signal — it is how we learn whether the prompt is
    holding or whether the escalation ladder in this module's docstring is due.
    """
    junk = find_junk_stance_subjects(summary_md, vocab)
    if not junk:
        return summary_md
    logger.warning("stance-subject de-bracketed: %s", ", ".join(junk))
    return debracket_stance_subjects(summary_md, junk)
