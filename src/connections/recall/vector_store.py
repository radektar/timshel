"""Local single-file vector store over ``sqlite-vec`` (brute-force cosine KNN).

At personal-vault scale (thousands of notes -> tens of thousands of chunks) exact
KNN is sub-millisecond, so no ANN index is needed. One ``sqlite-vec`` file lives in
``.timshel/`` beside the other local state. Vectors are L2-normalized upstream, so
``sqlite-vec``'s L2 distance orders identically to cosine.

Incremental by note: ``upsert_note`` replaces a note's chunks; ``delete_note``
drops them. Pin the ``sqlite-vec`` version you ship — it is pre-1.0.

``dense=False`` opens the store without sqlite-vec at all (plain ``chunks`` table
only) — the lexical-only degradation the bundled app runs when the optional dense
deps aren't shipped. ``knn`` then honestly returns nothing.
"""

from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence

from src.connections.recall.chunking import Chunk
from src.logger import logger


@dataclass(frozen=True)
class Hit:
    """A stored chunk plus its distance to the query (lower = closer)."""

    chunk_id: int
    note_id: str
    seq: int
    text: str
    parent_text: str
    char_start: int
    char_end: int
    version_hash: str
    distance: float


class VaultVectorStore:
    """sqlite-vec store: metadata in ``chunks``, vectors in the ``chunk_vec`` vec0 table."""

    def __init__(self, db_path: Path, dim: int, *, dense: bool = True):
        self.dense = bool(dense)
        self.dim = int(dim)
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        # The lazy engine is shared across threads (UI search + daemon indexing),
        # so the connection must allow cross-thread use and a lock must serialize
        # access — sqlite3 is not safe for concurrent use of one connection.
        self._db = sqlite3.connect(str(self._path), check_same_thread=False)
        self._lock = threading.RLock()
        if self.dense:
            self._load_extension()
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS chunks("
            "id INTEGER PRIMARY KEY, note_id TEXT NOT NULL, seq INTEGER, "
            "text TEXT, parent_text TEXT, char_start INTEGER, char_end INTEGER, "
            "version_hash TEXT)"
        )
        self._db.execute("CREATE INDEX IF NOT EXISTS ix_chunks_note ON chunks(note_id)")
        if self.dense:
            self._db.execute(
                f"CREATE VIRTUAL TABLE IF NOT EXISTS chunk_vec USING vec0(embedding float[{self.dim}])"
            )
        self._db.execute("CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT)")
        self._db.commit()

    def _load_extension(self) -> None:
        from src.runtime_deps import ensure_importable

        ensure_importable("sqlite_vec")
        import sqlite_vec  # lazy: only when a store is actually opened

        self._db.enable_load_extension(True)
        sqlite_vec.load(self._db)
        self._db.enable_load_extension(False)

    @staticmethod
    def _serialize(vec: Sequence[float]) -> bytes:
        import sqlite_vec

        return sqlite_vec.serialize_float32(list(vec))

    def upsert_note(
        self,
        note_id: str,
        chunks: Sequence[Chunk],
        vectors: Optional[Sequence[Sequence[float]]] = None,
    ) -> None:
        """Replace all stored chunks for ``note_id`` with a fresh set (incremental).

        ``vectors`` is required in dense mode and ignored in lexical-only mode.
        """
        if self.dense:
            if vectors is None:
                raise ValueError("dense store requires vectors")
            if len(chunks) != len(vectors):
                raise ValueError("chunks and vectors length mismatch")
        with self._lock:
            self.delete_note(note_id)
            cur = self._db.cursor()
            for i, ch in enumerate(chunks):
                cur.execute(
                    "INSERT INTO chunks(note_id, seq, text, parent_text, char_start, char_end, version_hash) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (note_id, ch.seq, ch.text, ch.parent_text, ch.char_start, ch.char_end, ch.version_hash),
                )
                if self.dense and vectors is not None:
                    vec = vectors[i]
                    if len(vec) != self.dim:
                        raise ValueError(f"vector dim {len(vec)} != store dim {self.dim}")
                    cur.execute(
                        "INSERT INTO chunk_vec(rowid, embedding) VALUES (?, ?)",
                        (cur.lastrowid, self._serialize(vec)),
                    )
            self._db.commit()

    def delete_note(self, note_id: str) -> None:
        with self._lock:
            cur = self._db.cursor()
            if self.dense:
                ids = [r[0] for r in cur.execute("SELECT id FROM chunks WHERE note_id=?", (note_id,)).fetchall()]
                for cid in ids:
                    cur.execute("DELETE FROM chunk_vec WHERE rowid=?", (cid,))
            cur.execute("DELETE FROM chunks WHERE note_id=?", (note_id,))
            self._db.commit()

    def knn(self, query_vec: Sequence[float], k: int = 50) -> List[Hit]:
        """Top-``k`` chunks by vector distance (ascending). Empty in lexical-only mode."""
        if not self.dense:
            return []
        with self._lock:
            rows = self._db.execute(
                "SELECT rowid, distance FROM chunk_vec WHERE embedding MATCH ? ORDER BY distance LIMIT ?",
                (self._serialize(query_vec), int(k)),
            ).fetchall()
            if not rows:
                return []
            by_id = {r[0]: r[1] for r in rows}
            placeholders = ",".join("?" for _ in by_id)
            meta = self._db.execute(
                f"SELECT id, note_id, seq, text, parent_text, char_start, char_end, version_hash "
                f"FROM chunks WHERE id IN ({placeholders})",
                tuple(by_id.keys()),
            ).fetchall()
        hits = [
            Hit(
                chunk_id=m[0], note_id=m[1], seq=m[2], text=m[3], parent_text=m[4],
                char_start=m[5], char_end=m[6], version_hash=m[7], distance=float(by_id[m[0]]),
            )
            for m in meta
        ]
        hits.sort(key=lambda h: h.distance)
        return hits

    def all_chunks(self) -> List[Hit]:
        """Every stored chunk (distance=0) — the corpus for the lexical channel."""
        with self._lock:
            rows = self._db.execute(
                "SELECT id, note_id, seq, text, parent_text, char_start, char_end, version_hash FROM chunks"
            ).fetchall()
        return [
            Hit(chunk_id=r[0], note_id=r[1], seq=r[2], text=r[3], parent_text=r[4],
                char_start=r[5], char_end=r[6], version_hash=r[7], distance=0.0)
            for r in rows
        ]

    def count(self) -> int:
        with self._lock:
            return int(self._db.execute("SELECT COUNT(*) FROM chunks").fetchone()[0])

    def note_ids(self) -> List[str]:
        with self._lock:
            return [r[0] for r in self._db.execute("SELECT DISTINCT note_id FROM chunks").fetchall()]

    def note_version(self, note_id: str) -> Optional[str]:
        """The stored ``version_hash`` for a note (any chunk — they share it), or None
        if the note isn't indexed. Lets an incremental backfill skip unchanged notes."""
        with self._lock:
            row = self._db.execute(
                "SELECT version_hash FROM chunks WHERE note_id=? LIMIT 1", (note_id,)
            ).fetchone()
        return row[0] if row else None

    def set_meta(self, key: str, value: str) -> None:
        with self._lock:
            self._db.execute(
                "INSERT INTO meta(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, str(value)),
            )
            self._db.commit()

    def get_meta(self, key: str) -> Optional[str]:
        with self._lock:
            row = self._db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row[0] if row else None

    def close(self) -> None:
        with self._lock:
            try:
                self._db.close()
            except sqlite3.Error as exc:  # pragma: no cover - defensive
                logger.debug("vector store close failed: %s", exc)
