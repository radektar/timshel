"""Assemble a bounded, relevance-ranked set of notes for one synthesis pass.

We combine several cheap, local preselection channels and round-robin them into
a bounded candidate set:
  * the *recency window* (new material since the last digest — always kept),
  * *tag bridges* + a compact in-process *BM25* (similarity channels),
  * *rare-token bridges*, *shared-entity*, *dense KNN* (recall engine),
    *note-term graph PPR*, and *stance-flip* (distance channels — off by
    default, enabled by the magic-insights prototype).
Deliberately dependency-light for the local signals (no scipy / scikit-learn);
the dense channel reuses the vault's existing embedding index. The corpus is
hundreds of short notes, where these small algorithms are plenty.

We always feed *summaries*, never full transcripts — and when a note has no
summary block (AI summaries were off when it was transcribed) we fall back to a
head/tail excerpt of its body.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional, Set

from src.config import config
from src.connections.dismissals import DismissalStore
from src.connections.entities import entity_keys
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


def note_key(note: NoteRef) -> str:
    """Stable identity key for the digest's seen-set.

    The fingerprint when the note has one; a name-derived key otherwise, so
    even a frontmatter-less note can be marked as seen instead of re-entering
    the window forever.
    """
    return note.fingerprint or f"name:{note.basename}"


@dataclass
class CandidateSet:
    """Ranked candidate notes plus the 'new this week' subset."""

    notes: List[NoteRef]
    window_basenames: Set[str]
    bridge_basenames: Set[str] = None  # type: ignore[assignment]
    # basename -> the preselection channels that surfaced it ("window", "tag",
    # "bm25", "bridge", "entity", "dense"). The prototype's recall instrument
    # (H3): to ask "did preselection reach this planted pair, and via which
    # channel?", score the answer against this map. Empty by default.
    channel_map: Dict[str, Set[str]] = None  # type: ignore[assignment]
    # Every basename ANY channel ranked BEFORE the note-count cap / char budget.
    # Lets the recall eval tell "never found" from "found but cut by budget" —
    # two different failures needing two different fixes.
    precap_basenames: Set[str] = None  # type: ignore[assignment]
    # note_key() of every window note — what the scheduler marks as seen after
    # a run. Populated in every window mode (empty only for an empty set).
    window_keys: Set[str] = None  # type: ignore[assignment]
    # Total unseen notes BEFORE the window cap (seen-set mode only; equals the
    # window size otherwise). unseen_total - len(window) = the backfill leftover
    # that stays pending for the next digest.
    unseen_total: int = 0

    def __post_init__(self) -> None:
        if self.bridge_basenames is None:
            self.bridge_basenames = set()
        if self.channel_map is None:
            self.channel_map = {}
        if self.precap_basenames is None:
            self.precap_basenames = set()
        if self.window_keys is None:
            self.window_keys = set()


# --------------------------------------------------------------------------- #
# Parsing helpers
# --------------------------------------------------------------------------- #
def _frontmatter(full: str) -> Dict[str, str]:
    """Flat key/value frontmatter parse from already-read text (shared impl)."""
    from src.markdown_frontmatter import parse_frontmatter

    return parse_frontmatter(full)


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


@lru_cache(maxsize=8192)
def _tokenize(text: str) -> List[str]:
    # Cached: called by bm25, bridges, doc-freq and the graph channel — several
    # full-corpus passes per assemble, hundreds of assembles per recall run over
    # an unchanging corpus. Pure text->list; callers only read it (set(), len(),
    # Counter()), never mutate, so the shared cached list is safe.
    tokens: List[str] = []
    for raw in _TOKEN_RE.findall(text.lower()):
        tok = TagIndex.normalize_tag(raw)
        if not tok or len(tok) < 3 or tok in _STOPWORDS:
            continue
        tokens.append(tok)
    return tokens


def clear_tokenize_cache() -> None:
    """Drop the _tokenize LRU. The cache keys are whole note texts (up to
    ~2×max_chars each): great within one recall run's many assembles, but in
    the long-lived daemon it otherwise pins up to 8192 note texts + token lists
    forever after a weekly digest. Called at the end of a digest run so the
    speedup is kept where it matters and the retention is bounded to one pass.
    """
    _tokenize.cache_clear()


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
        # Accept the pre-rename marker too: a migrated vault still holds digests
        # stamped ``malinche-digest`` that must keep self-excluding.
        if fm.get("type") in ("timshel-digest", "malinche-digest"):
            continue
        note_date = (fm.get("date") or fm.get("recording_date") or "")[:10]
        # Under a time-travel replay, a note dated after the cutoff — OR with no
        # usable date at all — cannot be placed on the timeline, so it must not
        # leak into the replayed corpus. (as_of is None in production: no effect.)
        if as_of and (not note_date or note_date > as_of):
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
    vocabulary has drifted (so BM25 and tags miss it). Matching uses
    :func:`~src.connections.entities.entity_keys` — inflection-tolerant stems,
    because Polish declension ('Fundacja Ziemi' vs 'Fundacji Ziemi') defeats
    exact-form matching. Ranked by how many entities a note shares with the
    window, then recency. Returns at most ``max_n`` notes.
    """
    if max_n <= 0:
        return []
    window_entities: Set[str] = set()
    for note in window:
        window_entities |= entity_keys(note.summary_md)
    if not window_entities:
        return []

    scored: List[tuple] = []
    for note in older:
        if note.basename in exclude:
            continue
        shared = window_entities & entity_keys(note.summary_md)
        if shared:
            scored.append((len(shared), note.date, note))
    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [note for _, _, note in scored[:max_n]]


def _graph_neighbors(
    corpus: List[NoteRef],
    window: List[NoteRef],
    older: List[NoteRef],
    exclude: Set[str],
    max_n: int,
) -> List[NoteRef]:
    """Notes reached from the window by Personalized PageRank over the note-term
    bridge graph (Swanson ABC / HippoRAG-lite).

    Unlike the entity channel (a single shared entity) this spreads activation
    over MULTIPLE hops of shared bridge terms, so it reaches notes connected to
    the window through a chain of intermediates even when they share no direct
    term with any single window note. Ranked by PPR score. Pure-local, $0.
    """
    if max_n <= 0 or not older:
        return []
    from src.connections.note_graph import NoteGraph, build_note_terms

    graph = NoteGraph(build_note_terms(corpus))
    scores = graph.ppr([n.basename for n in window])
    if not scores:
        return []
    older_by_name = {n.basename: n for n in older if n.basename not in exclude}
    ranked = sorted(
        (b for b in scores if b in older_by_name),
        key=lambda b: scores[b],
        reverse=True,
    )
    return [older_by_name[b] for b in ranked[:max_n]]


# Module-level cache: the recall engine loads an ONNX embedding model — build it
# once per vault path per process, not once per assemble call (the recall eval
# replays assembly hundreds of times).
_ENGINE_CACHE: Dict[str, object] = {}


_CACHE_MISS = object()


def _get_recall_engine(vault_dir: Path):
    """Cached RecallEngine for the dense channel; None when unavailable."""
    key = str(vault_dir)
    # Single .get with a sentinel — a concurrent reset_recall_engines() between
    # a membership check and a lookup would otherwise raise KeyError straight
    # through assemble_candidates (this call sits outside the channel's guard).
    eng = _ENGINE_CACHE.get(key, _CACHE_MISS)
    if eng is _CACHE_MISS:
        try:
            from src.connections.recall.engine import RecallEngine

            eng = RecallEngine(vault_dir)
        except Exception as exc:  # noqa: BLE001 - channel must never break assembly
            logger.warning("dense channel unavailable (%s)", exc)
            eng = None
        _ENGINE_CACHE[key] = eng
    return eng


def reset_recall_engines() -> None:
    """Drop (and close) the cached engines — called on settings changes via
    seam.reset_engine. Without this, a cached engine keeps an open handle on
    a store file that a freshly-built engine may have replaced, silently
    writing to the orphaned inode."""
    # Clear FIRST, close after: a concurrent _get_recall_engine then builds a
    # fresh engine instead of grabbing one that is about to be closed. (A
    # thread already holding an old reference is covered by the channel's
    # never-break-assembly try/except.)
    engines = list(_ENGINE_CACHE.values())
    _ENGINE_CACHE.clear()
    for eng in engines:
        close = getattr(eng, "close", None)
        if close is None:
            continue
        try:
            close()
        except Exception:  # noqa: BLE001 - best-effort teardown
            pass


def _dense_neighbors(
    vault_dir: Path,
    window: List[NoteRef],
    older: List[NoteRef],
    exclude: Set[str],
    max_n: int,
    skip: int = 0,
) -> List[NoteRef]:
    """Semantic neighbours from the local embedding index (recall engine).

    The preselection channel the business strategy promised from day one and
    the digest lane never used: embed the window notes, KNN over the vault's
    existing sqlite-vec index, keep the nearest OLDER notes. Purely local,
    zero API cost. Fails soft: no index / no deps -> empty contribution.

    ``skip`` drops the ``skip`` nearest neighbours before taking ``max_n`` — the
    Goldilocks / "one step beyond the profile" band (Orwig 2025): the very
    closest notes are near-duplicates of the window and carry no surprise. 0 =
    plain top-K (default; recall harness sweeps this).
    """
    if max_n <= 0 or not older:
        return []
    engine = _get_recall_engine(vault_dir)
    if engine is None:
        return []
    if getattr(engine, "lexical_only", False):
        # Silent zeros here would read as "dense channel found nothing" in a
        # digest quality report. Debug level: the eval harness replays assembly
        # hundreds of times, and the engine already logs its mode once at init.
        logger.debug("dense channel skipped — recall engine is lexical-only")
        return []
    older_by_name = {n.basename: n for n in older if n.basename not in exclude}
    if not older_by_name:
        return []

    # Aggregate best rank per note across up to 3 window queries.
    best_rank: Dict[str, int] = {}
    try:
        for note in window[:3]:
            query = note.summary_md.strip()[:800]
            if not query:
                continue
            for rank, note_id in enumerate(
                engine.knn_note_ids(query, k=(skip + max_n) * 3)
            ):
                if note_id in older_by_name:
                    if note_id not in best_rank or rank < best_rank[note_id]:
                        best_rank[note_id] = rank
    except Exception as exc:  # noqa: BLE001 - channel must never break assembly
        logger.warning("dense channel query failed (%s)", exc)
        return []
    ranked = sorted(best_rank.items(), key=lambda kv: kv[1])
    return [older_by_name[name] for name, _ in ranked[skip : skip + max_n]]


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


def _round_robin(channels: List[List[NoteRef]]) -> List[NoteRef]:
    """Interleave N ranked channel lists one item at a time (channel quotas).

    Round-robin gives every channel a fair share of the note-count cap, so no
    single dominant channel (bm25/tags) can crowd out the weak-signal ones —
    and no pile of distance channels can starve similarity. Order within a round
    follows the ``channels`` order (earlier = slight priority). With exactly two
    lists this is byte-identical to :func:`_interleave`, so the baseline (only
    tag + bm25 populated) is unchanged.
    """
    out: List[NoteRef] = []
    idx = [0] * len(channels)
    remaining = True
    while remaining:
        remaining = False
        for c, ch in enumerate(channels):
            if idx[c] < len(ch):
                out.append(ch[idx[c]])
                idx[c] += 1
                remaining = True
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
    inject_dense: int = 0,
    inject_graph: int = 0,
    inject_stance: int = 0,
    dense_skip: int = 0,
    as_of: Optional[str] = None,
    seen_keys: Optional[Set[str]] = None,
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
        inject_dense: semantic KNN notes from the local embedding index
            (0 = off; requires the recall index — fails soft without it).
        inject_graph: notes reached by PPR over the note-term bridge graph
            (0 = off; pure-local ABC/HippoRAG-lite channel).
        inject_stance: older notes sharing an anchor with the window but of
            opposite polarity (0 = off; contradiction-candidate channel).
        as_of: time-travel cutoff (YYYY-MM-DD, inclusive) for the recall
            harness — see :func:`load_corpus`. Production callers omit it.
        seen_keys: the digest's seen-set (:func:`note_key` values). When given,
            the window = notes NOT in the set (newest first, capped at
            ``first_run_window``) — so a backfilled old note counts as new
            material exactly once, regardless of its recording date. ``None``
            keeps the legacy date-based window (recall harness / older callers).
    """
    corpus = [
        n
        for n in load_corpus(vault_dir, as_of=as_of)
        if not dismissals.note_muted(n.basename)
    ]
    if not corpus:
        return CandidateSet([], set())

    if seen_keys is not None:
        unseen = sorted(
            (n for n in corpus if note_key(n) not in seen_keys),
            key=lambda n: n.date,
            reverse=True,
        )
        unseen_total = len(unseen)
        # Cap the window so a bulk backfill catches up incrementally (15 notes
        # per digest) instead of blowing one giant prompt; the leftover stays
        # unseen and enters the next runs.
        window = unseen[:first_run_window]
    elif last_digest_at:
        cutoff = last_digest_at[:10]
        window = [n for n in corpus if n.date and n.date >= cutoff]
        unseen_total = len(window)
    else:
        window = sorted(corpus, key=lambda n: n.date, reverse=True)[:first_run_window]
        unseen_total = len(window)

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

    # Dense semantic channel: KNN over the vault's local embedding index (the
    # recall engine). Injected alongside bridges/entities so it survives the
    # cap/budget. Default 0 -> baseline unchanged; fails soft without an index.
    dense: List[NoteRef] = []
    dense_basenames: Set[str] = set()
    if inject_dense > 0:
        dense = _dense_neighbors(
            Path(vault_dir),
            window,
            older,
            window_basenames | bridge_basenames | entity_basenames,
            inject_dense,
            skip=dense_skip,
        )
        dense_basenames = {n.basename for n in dense}

    # Graph channel: Personalized PageRank over the note-term bridge graph
    # (Swanson ABC / HippoRAG-lite) — multi-hop reach the single-entity channel
    # misses. Default 0 -> baseline unchanged.
    graph: List[NoteRef] = []
    graph_basenames: Set[str] = set()
    if inject_graph > 0:
        graph = _graph_neighbors(
            corpus,
            window,
            older,
            window_basenames | bridge_basenames | entity_basenames | dense_basenames,
            inject_graph,
        )
        graph_basenames = {n.basename for n in graph}

    # Stance-flip channel: older notes sharing an anchor (entity/tag) with the
    # window but carrying OPPOSITE polarity — contradiction candidates the
    # similarity channels miss. Default 0 -> baseline unchanged.
    stance: List[NoteRef] = []
    stance_basenames: Set[str] = set()
    if inject_stance > 0:
        from src.connections.stance import stance_flip_neighbors

        stance = stance_flip_neighbors(
            window,
            older,
            window_basenames
            | bridge_basenames
            | entity_basenames
            | dense_basenames
            | graph_basenames,
            inject_stance,
        )
        stance_basenames = {n.basename for n in stance}

    # Fair round-robin across all channels (quotas), so neither the dominant
    # similarity channels nor the pile of distance channels can monopolize the
    # note-count cap. Two-list baseline (only tag+bm25) stays byte-identical.
    ranked: List[NoteRef] = list(window)
    seen = set(window_basenames)
    for note in _round_robin(
        [
            stance,
            bridges,
            entities,
            dense,
            graph,
            tag_neighbors,
            lexical_neighbors,
        ]
    ):
        if note.basename in seen:
            continue
        seen.add(note.basename)
        ranked.append(note)

    # Everything ANY channel ranked, before cap/budget (recall-eval diagnostic).
    precap_basenames = set(seen)

    protected = (
        window_basenames
        | bridge_basenames
        | entity_basenames
        | dense_basenames
        | graph_basenames
        | stance_basenames
    )
    # The note-count cap must not drop the weak-signal distance channels in
    # favour of the abundant similarity channels (bm25/tags). Round-robin fairly
    # interleaves them, but a distance note landing deep in the round order would
    # otherwise fall past the cap. Stable-partition protected (window + distance)
    # ahead of the rest — preserving round-robin order within each group — so the
    # cap trims similarity overflow first. (Without this, step-D's round-robin
    # could REGRESS prototype recall vs the old distance-first concat.)
    ranked.sort(key=lambda n: n.basename not in protected)
    ranked = ranked[: config.MAX_SYNTHESIS_NOTES]
    ranked = _enforce_char_budget(ranked, protected)

    # Channel attribution for the surfaced notes (H3 recall instrument).
    channel_sources = [
        ("window", window),
        ("tag", tag_neighbors),
        ("bm25", lexical_neighbors),
        ("bridge", bridges),
        ("entity", entities),
        ("dense", dense),
        ("graph", graph),
        ("stance", stance),
    ]
    kept = {n.basename for n in ranked}
    channel_map: Dict[str, Set[str]] = {}
    for channel, notes in channel_sources:
        for note in notes:
            if note.basename in kept:
                channel_map.setdefault(note.basename, set()).add(channel)

    logger.info(
        "connection assembly: %d candidates (%d new, %d bridges, %d entities, "
        "%d dense, %d graph, %d stance) from %d-note corpus",
        len(ranked),
        len(window_basenames),
        len(bridge_basenames),
        len(entity_basenames),
        len(dense_basenames),
        len(graph_basenames),
        len(stance_basenames),
        len(corpus),
    )
    return CandidateSet(
        ranked,
        window_basenames,
        bridge_basenames,
        channel_map=channel_map,
        precap_basenames=precap_basenames,
        window_keys={note_key(n) for n in window},
        unseen_total=unseen_total,
    )
