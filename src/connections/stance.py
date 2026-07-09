"""Stance-flip channel — candidate pairing for contradictions-over-time.

Contradiction detection (de Marneffe): two statements contradict only if they
are about the SAME entity/topic and carry OPPOSITE polarity. Our worst-recall
type (contradiction) is exactly the case where the wording drifted, so
similarity channels are silent — but the shared ANCHOR (a named entity) survives
the drift, and a polarity flip is a cheap, local signal.

Two tiers, structured first:

* **Structured (v2 summaries).** Since 2026-07-07 the summarizer emits a
  ``## Stanowiska`` section — ``- [[Subject]] ✅/❌/🔄 reason`` — where a strong
  LLM already did the hard part at note-creation time: named the subject in
  base form and judged the polarity. Pairing is then near-exact: shared subject
  keys + opposite markers (or an explicit 🔄 change-of-mind against any prior
  stance on the same subject). This tier exists because the lexicon tier scored
  ZERO unique saves in the v2 recall eval — guessing polarity from raw prose at
  query time lost to stating it at write time.
* **Lexicon fallback (pre-v2 notes / no stances).** The original tiny PL/EN
  valence lexicon + negation scope + change cues. Kept for corpora that predate
  the v2 format; mDeBERTa/plWordNet remain the documented upgrade if needed.

Purely local, $0.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import FrozenSet, List, Optional, Set

from src.connections.candidate_assembly import NoteRef
from src.connections.entities import entity_keys

_WORD_RE = re.compile(r"[a-ząćęłńóśźż]+", re.IGNORECASE)

# Valence stems (prefix match, so Polish inflection is covered). Deliberately
# small and high-precision — a v1 signal, not a sentiment model.
# Single-word stems only (prefix match, so Polish inflection is covered).
# Removed as ambiguous prefix-false-positives: "chce/chcę" (neutral intent),
# "pewn" (filler "pewnie"), "działa" (matches "działka"), "za tym" (substring),
# "zł" (currency/złoto/złapać), "strat" (strateg…). Multi-word entries removed
# entirely — the negation-scope flip already covers "nie warto".
_POS_STEMS = {
    # PL
    "dobr",
    "świetn",
    "swietn",
    "warto",
    "zysk",
    "korzyśc",
    "korzysc",
    "sukces",
    "zgadz",
    "popier",
    "wierzę",
    "wierze",
    "sensown",
    "lepsz",
    "najlepsz",
    "optymist",
    "udan",
    # EN
    "good",
    "great",
    "worth",
    "benefit",
    "agree",
    "support",
    "confident",
    "believe",
    "better",
    "best",
    "works",
    "yes",
}
_NEG_STEMS = {
    # PL
    "zły",
    "zła",
    "złe",
    "złego",
    "złej",
    "złych",
    "złym",
    "złą",
    "źle",
    "zle",
    "problem",
    "ryzyk",
    "strata",
    "straty",
    "stratę",
    "stratą",
    "stracił",
    "stracic",
    "stracić",
    "przeciw",
    "rezygn",
    "wątpl",
    "watpl",
    "błąd",
    "blad",
    "porażk",
    "porazk",
    "gorsz",
    "najgorsz",
    "obaw",
    "trudn",
    "pesymist",
    "zagroż",
    "zagroz",
    "przestał",
    "przestal",
    "odrzuc",
    # EN
    "bad",
    "worse",
    "worst",
    "risk",
    "loss",
    "against",
    "doubt",
    "mistake",
    "fail",
    "reject",
}
# Explicit stance-change signals — a strong hint the note revisits a position.
_CHANGE_CUES = (
    "zmieni",
    "zmian zdani",
    "jednak nie",
    "już nie",
    "juz nie",
    "rezygn",
    "przesta",
    "wracam do",
    "nie sądzę",
    "nie sadze",
    "przemyśla",
    "przemysla",
    "no longer",
    "changed my mind",
    "on second thought",
    "used to",
    "reconsider",
)
# "no" deliberately excluded — in Polish it is an affirmative filler ("no
# dobra", "no warto"), not a negator; treating it as one inverts affirmations.
_NEGATORS = {"nie", "not", "bez", "never", "nigdy", "żaden", "zaden"}


def _has_cue(text: str) -> bool:
    low = text.lower()
    return any(cue in low for cue in _CHANGE_CUES)


# --------------------------------------------------------------------------- #
# Structured tier: parse the summarizer's "## Stanowiska" section.
# --------------------------------------------------------------------------- #

_STANCE_SECTION_RE = re.compile(r"^##\s+(Stanowiska|Stances)\s*$", re.MULTILINE)
_NEXT_SECTION_RE = re.compile(r"^##\s+", re.MULTILINE)
# One stance line: "- [[Subject]] ✅ reason" (subject may lack brackets when a
# weaker model drops them — accept both, brackets preferred).
_STANCE_LINE_RE = re.compile(
    r"^-\s*(?:\[\[([^\]|]+)(?:\|[^\]]*)?\]\]|([^✅❌🔄\n]+?))\s*(✅|❌|🔄)\s*(.*)$",
    re.MULTILINE,
)
_MARKER_POLARITY = {"✅": 1, "❌": -1, "🔄": 0}


@dataclass(frozen=True)
class Stance:
    """One parsed stance line from a v2 summary."""

    subject: str  # display form as written
    keys: FrozenSet[str]  # inflection-tolerant match keys (entity_keys)
    polarity: int  # +1 ✅ / -1 ❌ / 0 🔄
    changed: bool  # 🔄 — explicit change of mind


def parse_stances(summary_md: str) -> List[Stance]:
    """Parse the ``## Stanowiska`` / ``## Stances`` section of a v2 summary.

    Returns [] for pre-v2 notes (no section) — callers fall back to the
    lexicon tier. Subject keys come from :func:`entity_keys` (the subject is
    wrapped as a wikilink so single-word subjects qualify too), which makes
    cross-note joins tolerant to Polish inflection.
    """
    match = _STANCE_SECTION_RE.search(summary_md)
    if not match:
        return []
    rest = summary_md[match.end() :]
    nxt = _NEXT_SECTION_RE.search(rest)
    section = rest[: nxt.start()] if nxt else rest

    stances: List[Stance] = []
    for line in _STANCE_LINE_RE.finditer(section):
        subject = (line.group(1) or line.group(2) or "").strip().strip("*_ ")
        if not subject:
            continue
        keys = entity_keys(f"[[{subject}]]")
        if not keys:
            continue
        marker = line.group(3)
        stances.append(
            Stance(
                subject=subject,
                keys=frozenset(keys),
                polarity=_MARKER_POLARITY[marker],
                changed=marker == "🔄",
            )
        )
    return stances


def _stance_conflict(a: Stance, b: Stance) -> Optional[float]:
    """Score when two stances on a shared subject form a contradiction signal.

    None = no signal. Opposite explicit polarities are the strongest pair; an
    explicit 🔄 against ANY prior stance on the same subject also counts (the
    speaker says the position moved — the old note holds the old position).
    Same-polarity pairs are agreement, not contradiction.
    """
    if not (a.keys & b.keys):
        return None
    if a.polarity * b.polarity == -1:  # ✅ vs ❌
        return 2.0
    if a.changed or b.changed:  # 🔄 vs any stance
        return 1.5
    return None


def _stem_hit(token: str, stems: Set[str]) -> bool:
    return any(token.startswith(s) for s in stems if " " not in s)


def polarity_score(text: str) -> float:
    """Signed valence of ``text`` in roughly [-1, 1] (0 = neutral/unknown).

    Sums per-token valence with a 3-token negation-scope flip (covers "nie jest
    to dobry", "nie do końca dobry"); normalized by the count of valence-bearing
    tokens. Lexicon is single-word stems only — no substring prefilter (which
    fired inside unrelated words and double-counted negated phrases).
    """
    pos = neg = 0
    tokens = _WORD_RE.findall(text.lower())
    for i, tok in enumerate(tokens):
        sign = 0
        if _stem_hit(tok, _POS_STEMS):
            sign = 1
        elif _stem_hit(tok, _NEG_STEMS):
            sign = -1
        if sign == 0:
            continue
        # negation in the preceding 3 tokens flips the sign
        if any(tokens[j] in _NEGATORS for j in range(max(0, i - 3), i)):
            sign = -sign
        if sign > 0:
            pos += 1
        else:
            neg += 1
    total = pos + neg
    if total == 0:
        return 0.0
    return (pos - neg) / total


def _anchors(note: NoteRef) -> Set[str]:
    """Drift-surviving anchors: named entities + normalized tags."""
    return entity_keys(note.summary_md) | set(note.norm_tags)


def stance_flip_neighbors(
    window: List[NoteRef],
    older: List[NoteRef],
    exclude: Set[str],
    max_n: int,
) -> List[NoteRef]:
    """Older notes that share an anchor with the window but carry OPPOSITE
    polarity — contradiction candidates the similarity channels miss.

    Structured tier first (parsed ``## Stanowiska`` on both sides — near-exact
    signal), lexicon tier fills the remaining slots. Returns at most ``max_n``.
    """
    if max_n <= 0 or not older:
        return []

    structured = _structured_flip_neighbors(window, older, exclude, max_n)
    if len(structured) >= max_n:
        return structured[:max_n]
    taken = exclude | {n.basename for n in structured}
    lexicon = _lexicon_flip_neighbors(window, older, taken, max_n - len(structured))
    return structured + lexicon


def _structured_flip_neighbors(
    window: List[NoteRef],
    older: List[NoteRef],
    exclude: Set[str],
    max_n: int,
) -> List[NoteRef]:
    """Pair via parsed stances on both sides: shared subject + conflict."""
    win_stances: List[Stance] = []
    for note in window:
        win_stances.extend(parse_stances(note.summary_md))
    if not win_stances:
        return []

    scored: List[tuple] = []
    for note in older:
        if note.basename in exclude:
            continue
        best = 0.0
        for other in parse_stances(note.summary_md):
            for mine in win_stances:
                conflict = _stance_conflict(mine, other)
                if conflict is not None:
                    best = max(best, conflict * len(mine.keys & other.keys))
        if best > 0:
            scored.append((best, note.date, note))
    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [note for _, _, note in scored[:max_n]]


def _lexicon_flip_neighbors(
    window: List[NoteRef],
    older: List[NoteRef],
    exclude: Set[str],
    max_n: int,
) -> List[NoteRef]:
    """Original lexicon tier — polarity guessed from prose at query time."""
    if max_n <= 0:
        return []
    win_anchors: Set[str] = set()
    win_pol = 0.0
    win_cue = False
    for note in window:
        win_anchors |= _anchors(note)
        win_pol += polarity_score(note.summary_md)
        win_cue = win_cue or _has_cue(note.summary_md)
    win_pol = win_pol / max(1, len(window))
    if not win_anchors:
        return []

    scored: List[tuple] = []
    for note in older:
        if note.basename in exclude:
            continue
        shared = win_anchors & _anchors(note)
        if not shared:
            continue
        note_pol = polarity_score(note.summary_md)
        opposition = abs(win_pol - note_pol)
        sign_flip = (win_pol > 0.1 and note_pol < -0.1) or (
            win_pol < -0.1 and note_pol > 0.1
        )
        # A change-cue only counts when the OLDER note actually holds a stance
        # (|note_pol| > 0.1). Otherwise a single "zmieniłem…" in the window would
        # pair every anchor-sharing note regardless of polarity, flooding the
        # channel with non-contradictions.
        cue = (win_cue or _has_cue(note.summary_md)) and abs(note_pol) > 0.1
        if not (sign_flip or cue):
            continue
        score = len(shared) * (opposition + (0.5 if cue else 0.0))
        scored.append((score, note.date, note))
    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [note for _, _, note in scored[:max_n]]
