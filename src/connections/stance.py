"""Stance-flip channel — cheap candidate pairing for contradictions-over-time.

Contradiction detection (de Marneffe): two statements contradict only if they
are about the SAME entity/topic and carry OPPOSITE polarity. Our worst-recall
type (contradiction, ~46%) is exactly the case where the wording drifted, so
similarity channels are silent — but the shared ANCHOR (a named entity or tag)
survives the drift, and a polarity flip is a cheap, local signal.

This is the "easy tier" of de Marneffe's typology (negation, sentiment flip)
reframed as a *pairing* score, computed with a tiny built-in PL/EN valence
lexicon + negation scope + stance-change cue phrases. No model, no download —
mDeBERTa/plWordNet are the documented fallback if this proves too blunt.

Score(window_note, older_note) = anchor_overlap × polarity_opposition, boosted
when either note carries an explicit "changed my mind" cue. Purely local, $0.
"""

from __future__ import annotations

import re
from typing import List, Set

from src.connections.candidate_assembly import NoteRef
from src.connections.entities import entity_keys

_WORD_RE = re.compile(r"[a-ząćęłńóśźż]+", re.IGNORECASE)

# Valence stems (prefix match, so Polish inflection is covered). Deliberately
# small and high-precision — a v1 signal, not a sentiment model.
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
    "chcę",
    "chce",
    "wierzę",
    "wierze",
    "pewn",
    "sens",
    "lepsz",
    "najlepsz",
    "za tym",
    "optymist",
    "udan",
    "działa",
    "dziala",
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
    "zł",
    "źle",
    "zle",
    "problem",
    "ryzyk",
    "strat",
    "przeciw",
    "rezygn",
    "wątpl",
    "watpl",
    "nie warto",
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
    "problem",
    "mistake",
    "fail",
    "reject",
    "no longer",
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
_NEGATORS = {"nie", "not", "no", "bez", "never", "nigdy", "żaden", "zaden"}


def _has_cue(text: str) -> bool:
    low = text.lower()
    return any(cue in low for cue in _CHANGE_CUES)


def _stem_hit(token: str, stems: Set[str]) -> bool:
    return any(token.startswith(s) for s in stems if " " not in s)


def polarity_score(text: str) -> float:
    """Signed valence of ``text`` in roughly [-1, 1] (0 = neutral/unknown).

    Sums per-token valence with a 2-token negation-scope flip; normalized by the
    count of valence-bearing tokens. Multi-word lexicon entries (e.g. "nie
    warto", "no longer") are matched on the raw lowercased text as a prefilter.
    """
    low = text.lower()
    pos = sum(1 for p in _POS_STEMS if " " in p and p in low)
    neg = sum(1 for n in _NEG_STEMS if " " in n and n in low)
    tokens = _WORD_RE.findall(low)
    for i, tok in enumerate(tokens):
        sign = 0
        if _stem_hit(tok, _POS_STEMS):
            sign = 1
        elif _stem_hit(tok, _NEG_STEMS):
            sign = -1
        if sign == 0:
            continue
        # negation in the preceding 2 tokens flips the sign
        if any(tokens[j] in _NEGATORS for j in range(max(0, i - 2), i)):
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

    Ranked by anchor_overlap × |Δpolarity|, boosted when either side has an
    explicit stance-change cue. Returns at most ``max_n`` notes.
    """
    if max_n <= 0 or not older:
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
        # Require a genuine sign flip OR an explicit change cue on either side;
        # same-sign near-zero pairs are not contradictions.
        sign_flip = (win_pol > 0.1 and note_pol < -0.1) or (
            win_pol < -0.1 and note_pol > 0.1
        )
        cue = win_cue or _has_cue(note.summary_md)
        if not (sign_flip or cue):
            continue
        score = len(shared) * (opposition + (0.5 if cue else 0.0))
        scored.append((score, note.date, note))
    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [note for _, _, note in scored[:max_n]]
