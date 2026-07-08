"""Unit tests for the sqlite-vec vector store (fake vectors, no model)."""

from __future__ import annotations

import math

import pytest

from src.connections.recall.chunking import Chunk
from src.connections.recall.vector_store import VaultVectorStore


def _unit(vec):
    n = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / n for x in vec]


def _chunk(note_id, seq, text):
    return Chunk(
        note_id=note_id, seq=seq, text=text, parent_text=text,
        char_start=seq * 10, char_end=seq * 10 + len(text), version_hash="v1",
    )


@pytest.fixture()
def store(tmp_path):
    s = VaultVectorStore(tmp_path / ".timshel" / "vectors.db", dim=4)
    yield s
    s.close()


def test_upsert_and_knn_returns_closest_first(store):
    chunks = [_chunk("A", 0, "okna dach"), _chunk("A", 1, "budżet jakość")]
    vecs = [_unit([1, 0, 0, 0]), _unit([0, 1, 0, 0])]
    store.upsert_note("A", chunks, vecs)
    assert store.count() == 2

    hits = store.knn(_unit([0.9, 0.1, 0, 0]), k=2)
    assert len(hits) == 2
    assert hits[0].text == "okna dach"  # closest to [1,0,0,0]
    assert hits[0].distance <= hits[1].distance
    assert hits[0].note_id == "A"


def test_upsert_replaces_not_appends(store):
    store.upsert_note("A", [_chunk("A", 0, "one")], [_unit([1, 0, 0, 0])])
    store.upsert_note("A", [_chunk("A", 0, "two"), _chunk("A", 1, "three")],
                      [_unit([1, 0, 0, 0]), _unit([0, 1, 0, 0])])
    assert store.count() == 2
    assert {h.text for h in store.all_chunks()} == {"two", "three"}


def test_delete_note(store):
    store.upsert_note("A", [_chunk("A", 0, "x")], [_unit([1, 0, 0, 0])])
    store.upsert_note("B", [_chunk("B", 0, "y")], [_unit([0, 1, 0, 0])])
    assert store.count() == 2
    store.delete_note("A")
    assert store.count() == 1
    assert store.note_ids() == ["B"]


def test_dim_mismatch_raises(store):
    with pytest.raises(ValueError):
        store.upsert_note("A", [_chunk("A", 0, "x")], [[1, 0, 0]])  # dim 3 != 4


def test_persists_across_reopen(tmp_path):
    db = tmp_path / ".timshel" / "v.db"
    s1 = VaultVectorStore(db, dim=4)
    s1.upsert_note("A", [_chunk("A", 0, "persisted")], [_unit([1, 0, 0, 0])])
    s1.close()
    s2 = VaultVectorStore(db, dim=4)
    try:
        assert s2.count() == 1
        assert s2.knn(_unit([1, 0, 0, 0]), k=1)[0].text == "persisted"
    finally:
        s2.close()


def test_store_is_usable_from_another_thread(tmp_path):
    """The lazy engine is shared across the UI-search thread and the daemon indexing
    thread, so the connection must allow cross-thread use (check_same_thread=False).
    Before the fix this raised 'SQLite objects created in a thread...' in the worker."""
    import threading

    store = VaultVectorStore(tmp_path / ".timshel" / "th.db", dim=4)
    errors = []

    def worker():
        try:
            store.count()
            store.knn(_unit([1, 0, 0, 0]), k=3)
        except Exception as exc:  # pragma: no cover - fails only on regression
            errors.append(exc)

    t = threading.Thread(target=worker)
    t.start()
    t.join()
    store.close()
    assert errors == []
