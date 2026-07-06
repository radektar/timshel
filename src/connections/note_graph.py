"""Note-term bipartite graph + Personalized PageRank — the ABC bridge channel.

Literature-Based Discovery (Swanson): two documents that connect through a
shared BRIDGE concept — not through direct similarity — are exactly the
non-obvious pairs. Embedding-KNN and BM25 rank by direct A-C proximity, so they
structurally miss them. This module builds a bipartite graph (note nodes <->
term nodes) and runs Personalized PageRank seeded from the recency window:
activation spreads note -> shared term -> other note, reaching notes that share
ZERO surface words with the window via a chain of bridge terms (the mechanism
HippoRAG uses, minus the LLM).

Deliberately dependency-light — pure-Python dicts, power iteration, no numpy /
networkx (the assembly module's standing rule). At ~200 notes and a few
thousand terms the graph is tiny; ~30 iterations run in well under 100 ms.

The module is domain-agnostic on purpose: it takes a plain
``{note_id: {term: weight}}`` map and knows nothing about NoteRef, tokenizing,
or entities — the caller (candidate_assembly) supplies the terms. That keeps it
unit-testable in isolation and avoids an import cycle.
"""

from __future__ import annotations

from typing import Dict, List, Set

# --------------------------------------------------------------------------- #
# Bridge-term frequency bands (B-term filtering, per LBD/LION practice).
# A term only becomes a graph edge when its document frequency sits in a band:
# too rare (df<2) links nothing; too common is background knowledge. Entities
# and tags tolerate a wider top than raw tokens — a proper noun in 15 notes is
# still a specific thread, whereas a common word in 15 notes is a topic.
# --------------------------------------------------------------------------- #
TOKEN_DF_BAND = (2, 8)
ENTITY_DF_BAND = (2, 20)
TAG_DF_BAND = (2, 15)
# Relative edge weights per term kind: entities carry the most bridge signal.
W_ENTITY = 2.0
W_TAG = 1.5
W_TOKEN = 1.0


class NoteGraph:
    """Bipartite note<->term graph with column-normalized PPR transitions."""

    def __init__(self, note_terms: Dict[str, Dict[str, float]]) -> None:
        # Forward: note -> {term: weight}; reverse: term -> {note: weight}.
        self._note_terms: Dict[str, Dict[str, float]] = {}
        self._term_notes: Dict[str, Dict[str, float]] = {}
        for note, terms in note_terms.items():
            clean = {t: float(w) for t, w in terms.items() if w > 0}
            if not clean:
                continue
            self._note_terms[note] = clean
            for term, w in clean.items():
                self._term_notes.setdefault(term, {})[note] = w
        # Out-weight sums for stochastic normalization of each node's edges.
        self._note_out = {n: sum(t.values()) for n, t in self._note_terms.items()}
        self._term_out = {t: sum(n.values()) for t, n in self._term_notes.items()}

    @property
    def notes(self) -> Set[str]:
        return set(self._note_terms)

    def ppr(
        self,
        seed: List[str],
        damping: float = 0.85,
        iters: int = 30,
        tol: float = 1e-6,
    ) -> Dict[str, float]:
        """Personalized PageRank restricted to NOTE nodes, seeded on ``seed``.

        Returns ``{note_id: score}`` for every reachable note EXCEPT the seeds
        themselves (a seed always ranks itself highest — useless for finding
        neighbours). Empty when the graph or seed is empty.
        """
        seed_notes = [n for n in seed if n in self._note_terms]
        if not seed_notes or not self._note_terms:
            return {}
        reset = 1.0 / len(seed_notes)
        seed_vec = {n: reset for n in seed_notes}

        # Rank vector over ALL nodes (notes + terms); start on the seed.
        note_rank: Dict[str, float] = dict(seed_vec)
        term_rank: Dict[str, float] = {}

        for _ in range(iters):
            new_note: Dict[str, float] = {
                n: (1 - damping) * seed_vec.get(n, 0.0) for n in seed_notes
            }
            # term -> note flow
            for term, r in term_rank.items():
                if r <= 0:
                    continue
                out = self._term_out[term]
                share = damping * r / out
                for note, w in self._term_notes[term].items():
                    new_note[note] = new_note.get(note, 0.0) + share * w
            # note -> term flow (next term_rank)
            new_term: Dict[str, float] = {}
            for note, r in note_rank.items():
                if r <= 0:
                    continue
                out = self._note_out[note]
                share = damping * r / out
                for term, w in self._note_terms[note].items():
                    new_term[term] = new_term.get(term, 0.0) + share * w

            delta = sum(
                abs(new_note.get(n, 0.0) - note_rank.get(n, 0.0)) for n in new_note
            )
            note_rank, term_rank = new_note, new_term
            if delta < tol:
                break

        seed_set = set(seed_notes)
        return {n: s for n, s in note_rank.items() if n not in seed_set and s > 0}


def _in_band(df: int, band) -> bool:
    return band[0] <= df <= band[1]


def build_note_terms(corpus) -> Dict[str, Dict[str, float]]:
    """Map each note to its band-filtered bridge terms with edge weights.

    Terms are namespaced ("e:" entity key, "g:" tag, "t:" token) so an entity
    and a token that happen to share a string never collide. Only terms whose
    corpus document-frequency sits in the band survive — that is the B-term
    filter. ``corpus`` is a list of NoteRef (imported lazily to keep this module
    domain-agnostic and cycle-free).
    """
    from collections import Counter

    from src.connections.candidate_assembly import _tokenize
    from src.connections.entities import entity_keys

    per_note_tokens: Dict[str, Set[str]] = {}
    per_note_entities: Dict[str, Set[str]] = {}
    tok_df: Counter = Counter()
    ent_df: Counter = Counter()
    tag_df: Counter = Counter()
    for note in corpus:
        toks = set(_tokenize(note.summary_md))
        ents = entity_keys(note.summary_md)
        per_note_tokens[note.basename] = toks
        per_note_entities[note.basename] = ents
        tok_df.update(toks)
        ent_df.update(ents)
        tag_df.update(note.norm_tags)

    note_terms: Dict[str, Dict[str, float]] = {}
    for note in corpus:
        terms: Dict[str, float] = {}
        for t in per_note_tokens[note.basename]:
            if _in_band(tok_df[t], TOKEN_DF_BAND):
                terms["t:" + t] = W_TOKEN
        for e in per_note_entities[note.basename]:
            if _in_band(ent_df[e], ENTITY_DF_BAND):
                terms["e:" + e] = W_ENTITY
        for g in note.norm_tags:
            if _in_band(tag_df[g], TAG_DF_BAND):
                terms["g:" + g] = W_TAG
        if terms:
            note_terms[note.basename] = terms
    return note_terms
