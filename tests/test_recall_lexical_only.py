"""Lexical-only degradation: recall works without fastembed/sqlite-vec.

The bundled app ships without the dense stack (and has no pip), so the engine
must fall back to pure-BM25 search over a plain-SQLite chunk store. These tests
deliberately carry NO ``enable_load_extension`` skipif — lexical mode is exactly
the path that must work on Pythons without loadable sqlite extensions.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from src.connections.recall import engine as engine_mod
from src.connections.recall.chunking import Chunk
from src.connections.recall.retriever import HybridRetriever
from src.connections.recall.vector_store import VaultVectorStore


def _note(root, name, title, date, body):
    (Path(root) / f"{name}.md").write_text(
        f'---\ntitle: "{title}"\ndate: {date}\n---\n\n{body}\n', encoding="utf-8"
    )


@pytest.fixture()
def vault(tmp_path):
    _note(
        tmp_path,
        "okna",
        "Okna i fundamenty",
        "14.06",
        "Dostepnosc okien niepewna, producenci okien nie odpowiadaja, dach stoi.",
    )
    _note(
        tmp_path,
        "skala",
        "Skalowanie",
        "01.06",
        "Automatyzacja daje zasieg ale gubi reczna robote.",
    )
    d = tmp_path / "Timshel Digests"
    d.mkdir()
    (d / "digest.md").write_text(
        "---\ntype: timshel-digest\n---\n\nignore me okien", encoding="utf-8"
    )
    return tmp_path


# --------------------------------------------------------------------------- #
# Store without sqlite-vec.
# --------------------------------------------------------------------------- #


def _chunk(seq, text):
    return Chunk(
        note_id="n",
        seq=seq,
        text=text,
        parent_text=text,
        char_start=0,
        char_end=len(text),
        version_hash="v1",
    )


def test_lexical_store_upserts_without_vectors(tmp_path):
    store = VaultVectorStore(tmp_path / "v.db", 0, dense=False)
    try:
        store.upsert_note("n", [_chunk(0, "alfa"), _chunk(1, "beta")])
        assert store.count() == 2
        assert store.note_version("n") == "v1"
        store.delete_note("n")
        assert store.count() == 0
    finally:
        store.close()


def test_lexical_store_knn_is_empty(tmp_path):
    store = VaultVectorStore(tmp_path / "v.db", 0, dense=False)
    try:
        store.upsert_note("n", [_chunk(0, "alfa")])
        assert store.knn([0.0, 1.0], k=5) == []
    finally:
        store.close()


def test_lexical_store_has_no_vec_table(tmp_path):
    store = VaultVectorStore(tmp_path / "v.db", 0, dense=False)
    store.close()
    db = sqlite3.connect(str(tmp_path / "v.db"))
    names = {
        r[0]
        for r in db.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table','view')"
        ).fetchall()
    }
    db.close()
    assert "chunks" in names
    assert not any(n.startswith("chunk_vec") for n in names)


def test_dense_store_still_requires_vectors(tmp_path):
    # Guard the dense contract: silently dropping vectors would corrupt search.
    pytest.importorskip("sqlite_vec")
    if not hasattr(sqlite3.Connection, "enable_load_extension"):
        pytest.skip("Python built without loadable sqlite extensions")
    store = VaultVectorStore(tmp_path / "v.db", 4, dense=True)
    try:
        with pytest.raises(ValueError):
            store.upsert_note("n", [_chunk(0, "alfa")])
    finally:
        store.close()


def test_lexical_store_rejects_vectors(tmp_path):
    # Symmetric contract: handing vectors to a lexical store is a mode-wiring
    # bug (full embedding cost paid, vectors dropped) and must be loud.
    store = VaultVectorStore(tmp_path / "v.db", 0, dense=False)
    try:
        with pytest.raises(ValueError):
            store.upsert_note("n", [_chunk(0, "alfa")], [[0.1, 0.2]])
    finally:
        store.close()


def test_dense_store_rejects_nonpositive_dim(tmp_path):
    # dim=0 belongs to lexical mode only; a dense store built from a lexical
    # DB's meta must fail here, not with an obscure vec0 DDL error.
    with pytest.raises(ValueError):
        VaultVectorStore(tmp_path / "v.db", 0, dense=True)


# --------------------------------------------------------------------------- #
# Retriever without an embedder.
# --------------------------------------------------------------------------- #


def test_retriever_lexical_only_ranks_and_scores(tmp_path):
    store = VaultVectorStore(tmp_path / "v.db", 0, dense=False)
    try:
        store.upsert_note(
            "okna", [_chunk(0, "producenci okien nie odpowiadaja dach stoi")]
        )
        store.upsert_note("skala", [_chunk(0, "automatyzacja daje zasieg")])
        retriever = HybridRetriever(store, None)
        results, confidence = retriever.search_scored("producenci okien", k=5)
        assert results and results[0].note_id == "okna"
        assert results[0].channels == "lexical"
        assert confidence == pytest.approx(1.0)  # both query terms literally present
    finally:
        store.close()


def test_retriever_lexical_only_low_confidence_when_terms_absent(tmp_path):
    store = VaultVectorStore(tmp_path / "v.db", 0, dense=False)
    try:
        store.upsert_note("skala", [_chunk(0, "automatyzacja daje zasieg ale gubi")])
        retriever = HybridRetriever(store, None)
        _results, confidence = retriever.search_scored("fundamenty piwnicy", k=5)
        assert confidence == 0.0  # nothing literal to stand on -> honest abstention
    finally:
        store.close()


# --------------------------------------------------------------------------- #
# Engine end to end in lexical mode.
# --------------------------------------------------------------------------- #


def test_engine_lexical_backfill_and_search(vault):
    eng = engine_mod.RecallEngine(vault, dense=False)
    try:
        assert eng.lexical_only
        assert eng.backfill() == 2  # digest folder excluded
        res = eng.search("producenci okien", k=5)
        assert res and res[0].note_id == "okna"
        assert eng.knn_note_ids("okna") == []  # dense seam honestly empty
    finally:
        eng.close()


def test_engine_lexical_incremental_backfill(vault):
    eng = engine_mod.RecallEngine(vault, dense=False)
    try:
        assert eng.backfill() == 2
        assert eng.backfill(incremental=True) == 0
        _note(vault, "okna", "Okna", "14.06", "Zupelnie nowa tresc.")
        assert eng.backfill(incremental=True) == 1
    finally:
        eng.close()


def _fake_dense_db(db_path):
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(db_path))
    db.execute("CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT)")
    db.execute("INSERT INTO meta VALUES ('dim', '384')")  # pre-mode DBs were dense
    db.execute(
        "CREATE TABLE chunks(id INTEGER PRIMARY KEY, note_id TEXT NOT NULL, "
        "seq INTEGER, text TEXT, parent_text TEXT, char_start INTEGER, "
        "char_end INTEGER, version_hash TEXT)"
    )
    db.execute(
        "INSERT INTO chunks(note_id, seq, text, parent_text, char_start, "
        "char_end, version_hash) VALUES ('stale', 0, 'x', 'x', 0, 1, 'h')"
    )
    db.commit()
    db.close()


def test_lexical_engine_leaves_dense_db_untouched(vault):
    # Per-mode store files: a lexical engine must NOT wipe the dense index a
    # dev environment built — the two coexist and a deps flip costs nothing.
    dense_path = Path(vault) / ".timshel" / "vault_vectors.db"
    _fake_dense_db(dense_path)
    before = dense_path.read_bytes()

    eng = engine_mod.RecallEngine(vault, dense=False)
    try:
        eng.backfill()
        assert eng.count() > 0
    finally:
        eng.close()
    assert dense_path.read_bytes() == before  # dense index intact
    assert (Path(vault) / ".timshel" / "vault_lexical.db").exists()


def test_engine_rebuilds_on_mode_mismatch_with_explicit_db_path(vault):
    # An explicit db_path shared across modes is the one remaining mismatch
    # path: the old-mode file must be rebuilt, not half-read (chunk_vec is
    # unreadable without sqlite-vec) — and sqlite sidecars must go with it.
    db_path = Path(vault) / ".timshel" / "shared.db"
    _fake_dense_db(db_path)
    journal = Path(str(db_path) + "-journal")
    journal.write_bytes(b"stale hot journal")

    eng = engine_mod.RecallEngine(vault, db_path=db_path, dense=False)
    try:
        assert eng.count() == 0  # stale dense rows dropped, not misread
        assert not journal.exists()  # sidecar removed with the DB
    finally:
        eng.close()


def test_unreadable_probe_does_not_wipe_index(vault, monkeypatch):
    # A transient meta-read error must mean 'unknown — do not rebuild';
    # defaulting to a mode would wipe a healthy index.
    e1 = engine_mod.RecallEngine(vault, dense=False)
    e1.backfill()
    n = e1.count()
    assert n > 0
    e1.close()

    monkeypatch.setattr(
        engine_mod.RecallEngine, "_probe_meta", lambda self: (None, None)
    )
    e2 = engine_mod.RecallEngine(vault, dense=False)
    try:
        assert e2.count() == n  # index survived the unreadable probe
    finally:
        e2.close()


def test_engine_lexical_reopen_keeps_index(vault):
    e1 = engine_mod.RecallEngine(vault, dense=False)
    e1.backfill()
    assert e1.count() > 0
    e1.close()
    e2 = engine_mod.RecallEngine(vault, dense=False)  # same mode -> no rebuild
    try:
        assert e2.count() > 0
    finally:
        e2.close()


def test_engine_auto_detects_missing_dense_stack(vault, monkeypatch):
    monkeypatch.setattr(engine_mod, "dense_stack_available", lambda: False)
    eng = engine_mod.RecallEngine(vault)  # no dense= override -> probe decides
    try:
        assert eng.lexical_only
        eng.backfill()
        assert eng.search("producenci okien", k=3)
    finally:
        eng.close()


def test_corrupt_store_file_self_heals(vault):
    # The bundle has no CLI escape hatch: a corrupt store must rebuild once,
    # not crash engine construction forever.
    db_path = Path(vault) / ".timshel" / "vault_lexical.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db_path.write_bytes(b"this is not a sqlite database at all")

    eng = engine_mod.RecallEngine(vault, dense=False)
    try:
        assert eng.count() == 0  # fresh store
        assert eng.backfill() == 2  # and it works
    finally:
        eng.close()


def test_idf_weighted_confidence_rejects_generic_word_match(tmp_path):
    # Two-token query sharing only a vault-frequent generic word must score
    # low — a raw matched-token count would fake 0.5 and clear the floor.
    store = VaultVectorStore(tmp_path / "v.db", 0, dense=False)
    try:
        for i in range(8):
            store.upsert_note(f"n{i}", [_chunk(0, f"spotkanie zespolu numer {i}")])
        retriever = HybridRetriever(store, None)
        _res, conf = retriever.search_scored("spotkanie zyrafa", k=5)
        assert conf < 0.45  # generic 'spotkanie' carries almost no idf weight
    finally:
        store.close()


def test_auto_mode_falls_back_when_dense_import_breaks(vault, monkeypatch):
    # Passive probe can pass on a half-installed dep; auto mode must degrade
    # to a WORKING lexical engine, not die 'unavailable'.
    monkeypatch.setattr(engine_mod, "dense_stack_available", lambda: True)
    monkeypatch.setattr(
        engine_mod,
        "resolve_embedder",
        lambda *a, **k: (_ for _ in ()).throw(ImportError("broken onnxruntime")),
    )
    eng = engine_mod.RecallEngine(vault)  # auto
    try:
        assert eng.lexical_only
        assert eng.backfill() == 2
        assert eng.search("producenci okien", k=3)
    finally:
        eng.close()

    with pytest.raises(ImportError):
        engine_mod.RecallEngine(vault, dense=True)  # explicit stays loud


def test_backfill_aborts_quietly_when_store_closed(vault):
    # Engine reset mid-backfill closes the store; the run must abort after the
    # FIRST failure instead of grinding a warning per remaining note. Pinned
    # via the progress callback: a revert to per-note continue would fire it
    # once per note (2), the abort fires it zero times (break skips it).
    eng = engine_mod.RecallEngine(vault, dense=False)
    eng._store.close()
    progressed = []
    try:
        n = eng.backfill(progress=lambda done, total, path: progressed.append(done))
        assert n == 0  # aborted, no raise
        assert progressed == []  # broke out at the FIRST note, no grind
    finally:
        eng.close()


def test_rebuild_store_reopens_empty_and_working(vault):
    eng = engine_mod.RecallEngine(vault, dense=False)
    try:
        eng.backfill()
        assert eng.count() > 0
        eng.rebuild_store()
        assert eng.count() == 0
        assert eng.backfill() == 2  # fresh store works end to end
    finally:
        eng.close()
