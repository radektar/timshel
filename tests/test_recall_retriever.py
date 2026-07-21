"""Whole-solution test: index real note files -> hybrid search -> ranked results.

Uses a deterministic bag-of-words fake embedder (no model download), so the full
chunk -> embed -> store -> retrieve path is exercised offline and reproducibly.
"""

from __future__ import annotations

import hashlib
import math
import sqlite3
from pathlib import Path

import pytest

# sqlite-vec needs a Python built with loadable sqlite extensions; the
# setup-python CPython on GitHub runners is not. Recall is optional at
# runtime (seam degrades gracefully), so skip rather than fail there.
pytestmark = pytest.mark.skipif(
    not hasattr(sqlite3.Connection, "enable_load_extension"),
    reason="Python built without loadable sqlite extensions (sqlite-vec)",
)

from src.connections.recall.indexer import index_note
from src.connections.recall.retriever import HybridRetriever, reciprocal_rank_fusion
from src.connections.recall.vector_store import VaultVectorStore


class FakeEmbedder:
    """Stable hashing bag-of-words — related text shares dimensions, no model needed."""

    model_id = "fake"
    dim = 96

    def _vec(self, text):
        v = [0.0] * self.dim
        for raw in text.lower().replace("\n", " ").split():
            tok = "".join(ch for ch in raw if ch.isalnum())
            if not tok:
                continue
            idx = int(hashlib.md5(tok.encode("utf-8")).hexdigest(), 16) % self.dim
            v[idx] += 1.0
        norm = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / norm for x in v]

    def embed_documents(self, texts):
        return [self._vec(t) for t in texts]

    def embed_query(self, text):
        return self._vec(text)


def _note(root, name, title, date, body):
    p = Path(root) / f"{name}.md"
    p.write_text(
        f'---\ntitle: "{title}"\ndate: {date}\n---\n\n{body}\n', encoding="utf-8"
    )
    return p


@pytest.fixture()
def engine(tmp_path):
    store = VaultVectorStore(tmp_path / ".timshel" / "v.db", dim=FakeEmbedder.dim)
    emb = FakeEmbedder()
    _note(
        tmp_path,
        "okna",
        "Okna i fundamenty",
        "14.06",
        "Dostepnosc okien przed sierpniem niepewna, producenci okien nie odpowiadaja, dach stoi w miejscu.",
    )
    _note(
        tmp_path,
        "jakosc",
        "Jakosc materialow",
        "18.06",
        "Budzet przekroczony dwukrotnie, rozwazasz obnizenie jakosci materialow naturalnych.",
    )
    _note(
        tmp_path,
        "skala",
        "Strategia skalowania",
        "01.06",
        "Automatyzacja daje zasieg ale gubi reczna robote za ktora ludzie cie ceni.",
    )
    for n in ("okna", "jakosc", "skala"):
        assert index_note(tmp_path / f"{n}.md", store, emb) >= 1
    yield HybridRetriever(store, emb), store
    store.close()


def test_search_returns_topical_note_first(engine):
    retriever, _ = engine
    results = retriever.search("co z dostawa okien i opoznieniem dachu", k=5)
    assert results
    assert results[0].note_id == "okna"


def test_search_targets_the_right_note_for_a_different_topic(engine):
    retriever, _ = engine
    top = retriever.search("obnizenie jakosci materialow budzet", k=3)[0]
    assert top.note_id == "jakosc"
    assert top.char_end > top.char_start
    assert top.parent_text
    assert "dense" in top.channels or "lexical" in top.channels


def test_empty_query_returns_nothing(engine):
    retriever, _ = engine
    assert retriever.search("   ") == []


def test_empty_store_returns_nothing(tmp_path):
    store = VaultVectorStore(tmp_path / ".timshel" / "e.db", dim=FakeEmbedder.dim)
    try:
        assert HybridRetriever(store, FakeEmbedder()).search("cokolwiek") == []
    finally:
        store.close()


def test_reindex_reflects_edits(engine, tmp_path):
    retriever, store = engine
    before = store.count()
    # rewrite the okna note to a new topic and re-index (upsert replaces its chunks)
    _note(
        tmp_path,
        "okna",
        "Notatka",
        "14.06",
        "Kalendarz spotkania rano, ustalenia dotyczace planu.",
    )
    index_note(tmp_path / "okna.md", store, FakeEmbedder())
    assert store.count() == before  # replaced, not appended (each note is 1 chunk here)
    # the NEW content is now retrievable under the okna note
    res = retriever.search("kalendarz spotkania plan", k=3)
    assert res and res[0].note_id == "okna"
    assert "kalendarz" in res[0].quote.lower()


def test_title_proper_noun_retrieves_even_when_absent_from_body(tmp_path):
    """A name that lives in the title/filename but not the spoken body must still hit.

    Mirrors the real-vault miss ("Haetta"): whisper doesn't repeat the proper noun in
    the transcript, so only the note_id/title carries it. The lexical channel folds the
    note_id in, so BM25 can match it.
    """
    store = VaultVectorStore(tmp_path / ".timshel" / "t.db", dim=FakeEmbedder.dim)
    emb = FakeEmbedder()
    _note(
        tmp_path,
        "Haetta - rozmowa z konstruktorem",
        "Haetta - rozmowa z konstruktorem",
        "17.06",
        "Ustalenia dotyczace nosnosci belek i harmonogramu prac na dachu.",
    )
    _note(
        tmp_path,
        "inne-spotkanie",
        "Priorytety projektow",
        "10.06",
        "Przeglad zadan zespolu i strategia rozwoju na kolejny kwartal.",
    )
    for n in ("Haetta - rozmowa z konstruktorem", "inne-spotkanie"):
        assert index_note(tmp_path / f"{n}.md", store, emb) >= 1
    try:
        top = HybridRetriever(store, emb).search(
            "rozmowa z konstruktorem o projekcie Haetta", k=3
        )
        assert top and top[0].note_id == "Haetta - rozmowa z konstruktorem"
        assert "lexical" in top[0].channels
    finally:
        store.close()


def test_search_scored_returns_confidence(engine):
    retriever, _ = engine
    results, conf = retriever.search_scored(
        "co z dostawa okien i opoznieniem dachu", k=5
    )
    assert results and 0.0 < conf <= 1.0
    # search() is the same pipeline without the confidence
    assert [
        r.note_id
        for r in retriever.search("co z dostawa okien i opoznieniem dachu", k=5)
    ] == [r.note_id for r in results]


def test_search_scored_empty_query_is_zero_confidence(engine):
    retriever, _ = engine
    assert retriever.search_scored("   ") == ([], 0.0)


def test_search_scored_confidence_clears_floor_for_relevant_query(engine):
    # A query that literally shares a note's terms must clear the abstinence floor via
    # the lexical-overlap net, else the UI would wrongly abstain on a real match. Binds
    # confidence to the floor (not just a 0<c<=1 bound). Terms are taken verbatim from
    # the 'okna' note so overlap is deterministic under the fake embedder; real models
    # score even higher (validated on the live vault).
    from src.ui.recall_presenter import DEFAULT_ABSTAIN_FLOOR

    retriever, _ = engine
    _, conf = retriever.search_scored("dostepnosc okien producenci dach", k=5)
    assert conf >= DEFAULT_ABSTAIN_FLOOR


def test_rrf_rewards_agreement():
    fused = reciprocal_rank_fusion([[1, 2, 3], [2, 4, 5]], k=60)
    assert fused[0][0] == 2  # ranked highly by both lists


def test_dense_overlap_net_keeps_raw_fraction_semantics(tmp_path):
    """The 0.60 dense floor is calibrated against the RAW matched-token
    fraction — idf-weighting (lexical-only metric) must not leak in: one
    out-of-vocabulary typo'd term would get corpus-max idf and sink a
    legitimate 2-of-3 named-entity match below the floor."""
    store = VaultVectorStore(tmp_path / ".timshel" / "v.db", dim=FakeEmbedder.dim)
    emb = FakeEmbedder()
    (tmp_path / "n.md").write_text(
        "---\ntitle: konstruktor belki\n---\n\nkonstruktor belki stalowej detale",
        encoding="utf-8",
    )
    index_note(tmp_path / "n.md", store, emb)
    try:
        retriever = HybridRetriever(store, emb)
        # 'heatta' is absent from the corpus (a typo) — raw fraction: 2/3.
        _res, conf = retriever.search_scored("konstruktor belki heatta", k=5)
        assert conf >= 2 / 3 - 1e-9
    finally:
        store.close()
