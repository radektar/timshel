"""Assemble a bounded, relevance-ranked set of notes for one synthesis pass.

No embeddings: we combine three cheap, local signals —
  1. the *recency window* (new material since the last digest — always kept),
  2. *tag bridges* (older notes sharing normalized tags with the window),
  3. *lexical overlap* via a compact in-process BM25 over note summaries —
then bound the result to a token budget. Deliberately dependency-light (no
scipy / scikit-learn): the corpus is hundreds of short notes, where a small
BM25 is plenty. ``bm25s`` is the documented drop-in if scale ever demands it.

We always feed *summaries*, never full transcripts — and when a note has no
summary block (AI summaries were off when it was transcribed) we fall back to a
head/tail excerpt of its body.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Set

from src.config import config
from src.connections.dismissals import DismissalStore
from src.connections.entities import extract_entities
from src.logger import logger
from src.summarizer import _EN_STOPWORDS, _PL_STOPWORDS
from src.tag_index import TagIndex

_TRANSCRIPT_MARKER = "## Transkrypcja"
_STOPWORDS = set(_PL_STOPWORDS) | set(_EN_STOPWORDS)
_TOKEN_RE = re.compile(r"[a-z0-9ąćęłńóśźż]+", re.IGNORECASE)
_BM25_K1 = 1.5
_BM25_B = 0.75

# A token is "rare" (a specific entity/concept, not a topical word) when it
# occurs in at most this many notes corpus-wide. Bridges are built on shared
# rare tokens: far apart in topic, joined by one specific thread.
_BRIDGE_RARE_DF = 4


@dataclass
class NoteRef:
    """A single transcript note, reduced to what synthesis needs."""

    md_path: Path
    basename: str  # filename without .md — the Obsidian [[wikilink]] target
    title: str
    date: str  # YYYY-MM-DD (frontmatter `date`, else `recording_date`)
    tags: List[str]
    norm_tags: Set[str]
    summary_md: str  # summary block, or a head/tail excerpt when none exists
    fingerprint: str


@dataclass
class CandidateSet:
    """Ranked candidate notes plus the 'new this week' subset."""

    notes: List[NoteRef]
    window_basenames: Set[str]
    bridge_basenames: Set[str] = None  # type: ignore[assignment]
    # basename -> the preselection channels that surfaced it ("window", "tag",
    # "bm25", "bridge", "entity"). The prototype's recall instrument (H3): to
    # ask "did preselection reach this planted pair, and via which channel?",
    # score the answer against this map. Empty by default (baseline callers).
    channel_map: Dict[str, Set[str]] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.bridge_basenames is None:
            self.bridge_basenames = set()
        if self.channel_map is None:
            self.channel_map = {}


# --------------------------------------------------------------------------- #
# Parsing helpers
# --------------------------------------------------------------------------- #
def _frontmatter(full: str) -> Dict[str, str]:
    """Flat key/value frontmatter parse from already-read text.

    Mirrors :func:`src.markdown_frontmatter.read_frontmatter` but works on the
    text we already hold, avoiding a second disk read per note.
    """
    data: Dict[str, str] = {}
    lines = full.splitlines()
    if not lines or lines[0].strip() != "---":
        return data
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        data[key.strip()] = value.strip().strip('"')
    return data


def _parse_tags(raw: str) -> List[str]:
    raw = raw.strip()
    if raw.startswith("[") and raw.endswith("]"):
        raw = raw[1:-1]
    return [t.strip().strip('"').strip("'") for t in raw.split(",") if t.strip()]


def _body_after_frontmatter(full: str) -> str:
    if full.startswith("---"):
        parts = full.split("---", 2)
        if len(parts) == 3:
            return parts[2]
    return full


def _excerpt(text: str, max_chars: int) -> str:
    text = text.strip()
    if len(text) <= max_chars * 2:
        return text
    return text[:max_chars] + "\n...\n" + text[-max_chars:]


def _summary_or_excerpt(full: str, max_chars: int) -> str:
    """Summary block if present, else a bounded excerpt of the transcript."""
    body = _body_after_frontmatter(full)
    if _TRANSCRIPT_MARKER in body:
        pre, _, post = body.partition(_TRANSCRIPT_MARKER)
        if pre.strip():
            return pre.strip()[: max_chars * 2]
        return _excerpt(post, max_chars)
    return _excerpt(body, max_chars)


def _tokenize(text: str) -> List[str]:
    tokens: List[str] = []
    for raw in _TOKEN_RE.findall(text.lower()):
        tok = TagIndex.normalize_tag(raw)
        if not tok or len(tok) < 3 or tok in _STOPWORDS:
            continue
        tokens.append(tok)
    return tokens


# --------------------------------------------------------------------------- #
# Corpus loading + ranking
# --------------------------------------------------------------------------- #
def load_corpus(vault_dir: Path, as_of: Optional[str] = None) -> List[NoteRef]:
    """Load top-level transcript notes (digests live in a subfolder, excluded).

    ``as_of`` (YYYY-MM-DD, inclusive) drops notes dated after it — the
    time-travel seam for the recall harness, which replays "what would
    assembly have seen the day note X arrived". Production callers omit it.
    """
    notes: List[NoteRef] = []
    note_chars = config.MAX_SYNTHESIS_NOTE_CHARS
    for md_path in sorted(Path(vault_dir).glob("*.md")):
        try:
            full = md_path.read_text(encoding="utf-8")
        except OSError as exc:
            logger.debug("skip unreadable note %s: %s", md_path, exc)
            continue
        fm = _frontmatter(full)
        if fm.get("type") == "malinche-digest":
            continue
        note_date = (fm.get("date") or fm.get("recording_date") or "")[:10]
        if as_of and note_date and note_date > as_of:
            continue
        tags = _parse_tags(fm.get("tags", ""))
        notes.append(
            NoteRef(
                md_path=md_path,
                basename=md_path.stem,
                title=fm.get("title") or md_path.stem,
                date=note_date,
                tags=tags,
                norm_tags={TagIndex.normalize_tag(t) for t in tags if t},
                summary_md=_summary_or_excerpt(full, note_chars),
                fingerprint=fm.get("fingerprint", ""),
            )
        )
    return notes


def _bm25_ranked(window: List[NoteRef], older: List[NoteRef]) -> List[NoteRef]:
    """Rank *older* notes by BM25 relevance to the *window* notes' text."""
    if not older:
        return []
    docs = [(_tokenize(n.summary_md), n) for n in older]
    n_docs = len(docs)
    doc_freq: Counter = Counter()
    total_len = 0
    for toks, _ in docs:
        total_len += len(toks)
        for term in set(toks):
            doc_freq[term] += 1
    avgdl = (total_len / n_docs) if n_docs else 0.0
    if avgdl == 0:
        return []

    query: Set[str] = set()
    for note in window:
        query |= set(_tokenize(note.summary_md))
    if not query:
        return []

    scored: List[tuple] = []
    for toks, note in docs:
        if not toks:
            continue
        tf = Counter(toks)
        dl = len(toks)
        score = 0.0
        for term in query:
            freq = tf.get(term, 0)
            if not freq:
                continue
            idf = math.log(1 + (n_docs - doc_freq[term] + 0.5) / (doc_freq[term] + 0.5))
            denom = freq + _BM25_K1 * (1 - _BM25_B + _BM25_B * dl / avgdl)
            score += idf * (freq * (_BM25_K1 + 1)) / denom
        if score > 0:
            scored.append((score, note))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [note for _, note in scored]


def _corpus_doc_freq(notes: List[NoteRef]) -> Counter:
    """Document frequency of every content token across the corpus."""
    df: Counter = Counter()
    for note in notes:
        for term in set(_tokenize(note.summary_md)):
            df[term] += 1
    return df


def _bridge_neighbors(
    window: List[NoteRef],
    older: List[NoteRef],
    doc_freq: Counter,
    exclude: Set[str],
    max_n: int,
) -> List[NoteRef]:
    """Mid-distance 'bridge' notes: far from the window in topic, joined by a
    shared *rare* token (a specific entity/concept), not the dominant theme.

    This is the distance channel the similarity signals (tags + BM25) cannot
    produce: serendipity = relevance x unexpectedness. We keep relevance via a
    shared rare token and maximise unexpectedness by ignoring topical overlap.
    Returns at most ``max_n`` notes, ranked by how many rare threads they share
    with the window (then recency).
    """
    if max_n <= 0:
        return []
    rare_window: Set[str] = set()
    for note in window:
        for term in set(_tokenize(note.summary_md)):
            if 0 < doc_freq.get(term, 0) <= _BRIDGE_RARE_DF:
                rare_window.add(term)
    if not rare_window:
        return []

    scored: List[tuple] = []
    for note in older:
        if note.basename in exclude:
            continue
        shared_rare = rare_window & set(_tokenize(note.summary_md))
        if shared_rare:
            scored.append((len(shared_rare), note.date, note))
    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [note for _, _, note in scored[:max_n]]


def _entity_neighbors(
    window: List[NoteRef],
    older: List[NoteRef],
    exclude: Set[str],
    max_n: int,
) -> List[NoteRef]:
    """Notes joined to the window by a shared *named entity*, not shared words.

    The channel Challenge #3 asks for: a contradiction months apart survives on
    the person / project / org both notes name, even after the topical
    vocabulary has drifted (so BM25 and tags miss it). Entities come from
    :func:`~src.connections.entities.extract_entities` (wikilinks + multi-word
    proper nouns). Ranked by how many entities a note shares with the window,
    then recency. Returns at most ``max_n`` notes.
    """
    if max_n <= 0:
        return []
    window_entities: Set[str] = set()
    for note in window:
        window_entities |= extract_entities(note.summary_md)
    if not window_entities:
        return []

    scored: List[tuple] = []
    for note in older:
        if note.basename in exclude:
            continue
        shared = window_entities & extract_entities(note.summary_md)
        if shared:
            scored.append((len(shared), note.date, note))
    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [note for _, _, note in scored[:max_n]]


def _interleave(first: List[NoteRef], second: List[NoteRef]) -> List[NoteRef]:
    out: List[NoteRef] = []
    i = j = 0
    while i < len(first) or j < len(second):
        if i < len(first):
            out.append(first[i])
            i += 1
        if j < len(second):
            out.append(second[j])
            j += 1
    return out


def _enforce_char_budget(
    notes: List[NoteRef], window_basenames: Set[str]
) -> List[NoteRef]:
    """Drop lowest-ranked *non-window* notes until under the prompt budget."""
    budget = config.MAX_SYNTHESIS_PROMPT_CHARS
    order = {n.basename: i for i, n in enumerate(notes)}
    total = 0
    kept: List[NoteRef] = []
    # Window notes are guaranteed in first; consider them before neighbours.
    ordered = [n for n in notes if n.basename in window_basenames] + [
        n for n in notes if n.basename not in window_basenames
    ]
    for note in ordered:
        size = len(note.summary_md)
        if kept and note.basename not in window_basenames and total + size > budget:
            continue
        total += size
        kept.append(note)
    kept.sort(key=lambda n: order[n.basename])
    return kept


def assemble_candidates(
    vault_dir: Path,
    last_digest_at: Optional[str],
    dismissals: DismissalStore,
    first_run_window: int = 15,
    inject_bridges: int = 0,
    inject_entities: int = 0,
    as_of: Optional[str] = None,
) -> CandidateSet:
    """Build the candidate set for one synthesis pass.

    Args:
        vault_dir: the transcript folder (``config.TRANSCRIBE_DIR``).
        last_digest_at: ISO timestamp of the last digest, or ``None`` (first run).
        dismissals: store used to drop muted notes (connection-level filtering
            happens later, on the synthesis output).
        first_run_window: how many recent notes seed the very first digest.
        inject_bridges: rare-token distance-channel notes to inject (0 = off).
        inject_entities: shared-entity distance-channel notes to inject (0 = off,
            byte-identical to the pre-entity baseline).
        as_of: time-travel cutoff (YYYY-MM-DD, inclusive) for the recall
            harness — see :func:`load_corpus`. Production callers omit it.
    """
    corpus = [
        n
        for n in load_corpus(vault_dir, as_of=as_of)
        if not dismissals.note_muted(n.basename)
    ]
    if not corpus:
        return CandidateSet([], set())

    if last_digest_at:
        cutoff = last_digest_at[:10]
        window = [n for n in corpus if n.date and n.date >= cutoff]
    else:
        window = sorted(corpus, key=lambda n: n.date, reverse=True)[:first_run_window]

    if not window:
        return CandidateSet([], set())
    window_basenames = {n.basename for n in window}
    older = [n for n in corpus if n.basename not in window_basenames]

    window_tags: Set[str] = set()
    for note in window:
        window_tags |= note.norm_tags

    def shared(note: NoteRef) -> int:
        return len(note.norm_tags & window_tags)

    tag_neighbors = sorted(
        [n for n in older if shared(n) > 0],
        key=lambda n: (shared(n), n.date),
        reverse=True,
    )
    lexical_neighbors = _bm25_ranked(window, older)

    # Distance channel (experiment): inject cross-topic bridges right after the
    # window so they survive the cap/budget — deliberately displacing the
    # weakest similar neighbours. Default 0 → byte-identical to the baseline.
    bridges: List[NoteRef] = []
    bridge_basenames: Set[str] = set()
    if inject_bridges > 0:
        bridges = _bridge_neighbors(
            window, older, _corpus_doc_freq(corpus), window_basenames, inject_bridges
        )
        bridge_basenames = {n.basename for n in bridges}

    # Entity distance-channel: notes sharing a named entity with the window even
    # when topic vocabulary has drifted (Challenge #3). Injected alongside
    # bridges so it survives the cap/budget. Default 0 -> baseline unchanged.
    entities: List[NoteRef] = []
    entity_basenames: Set[str] = set()
    if inject_entities > 0:
        entities = _entity_neighbors(
            window, older, window_basenames | bridge_basenames, inject_entities
        )
        entity_basenames = {n.basename for n in entities}

    ranked: List[NoteRef] = list(window)
    seen = set(window_basenames)
    for note in bridges + entities + _interleave(tag_neighbors, lexical_neighbors):
        if note.basename in seen:
            continue
        seen.add(note.basename)
        ranked.append(note)

    ranked = ranked[: config.MAX_SYNTHESIS_NOTES]
    protected = window_basenames | bridge_basenames | entity_basenames
    ranked = _enforce_char_budget(ranked, protected)

    # Channel attribution for the surfaced notes (H3 recall instrument).
    channel_sources = [
        ("window", window),
        ("tag", tag_neighbors),
        ("bm25", lexical_neighbors),
        ("bridge", bridges),
        ("entity", entities),
    ]
    kept = {n.basename for n in ranked}
    channel_map: Dict[str, Set[str]] = {}
    for channel, notes in channel_sources:
        for note in notes:
            if note.basename in kept:
                channel_map.setdefault(note.basename, set()).add(channel)

    logger.info(
        "connection assembly: %d candidates (%d new, %d bridges, %d entities) "
        "from %d-note corpus",
        len(ranked),
        len(window_basenames),
        len(bridge_basenames),
        len(entity_basenames),
        len(corpus),
    )
    return CandidateSet(
        ranked, window_basenames, bridge_basenames, channel_map=channel_map
    )
