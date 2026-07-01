"""RecallEngine — the one entry point wiring embedder + store + retriever from config.

Search is local and LLM-free. ``backfill`` indexes an existing vault once;
``index_path`` keeps the store fresh at transcription time. If the configured
embedding model changes (different dim), the store is rebuilt rather than corrupted.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, List, Optional

from src.connections.recall.embedding import resolve_embedder
from src.connections.recall.indexer import index_note
from src.connections.recall.retriever import HybridRetriever, Result
from src.connections.recall.vector_store import VaultVectorStore
from src.logger import logger

DB_FILENAME = "vault_vectors.db"


class RecallEngine:
    """Local recall over a vault: backfill/index -> hybrid search. No LLM."""

    def __init__(self, vault_dir, *, db_path=None, provider=None, model=None):
        self._vault = Path(vault_dir)
        self._embedder = resolve_embedder(provider, model)
        self._db_path = Path(db_path) if db_path else self._vault / ".malinche" / DB_FILENAME
        self._store = self._open_store()
        self._retriever = HybridRetriever(self._store, self._embedder)

    def _open_store(self) -> VaultVectorStore:
        if self._db_path.exists():
            existing = self._probe_dim()
            if existing is not None and existing != self._embedder.dim:
                logger.info(
                    "recall: embedding dim changed (%s -> %s); rebuilding store",
                    existing, self._embedder.dim,
                )
                self._db_path.unlink()
        store = VaultVectorStore(self._db_path, self._embedder.dim)
        store.set_meta("dim", str(self._embedder.dim))
        store.set_meta("model", self._embedder.model_id)
        return store

    def _probe_dim(self) -> Optional[int]:
        import sqlite3

        try:
            db = sqlite3.connect(str(self._db_path))
            row = db.execute("SELECT value FROM meta WHERE key='dim'").fetchone()
            db.close()
            return int(row[0]) if row else None
        except sqlite3.Error:  # pragma: no cover - defensive
            return None

    def search(self, query: str, k: int = 8) -> List[Result]:
        return self._retriever.search(query, k=k)

    def index_path(self, path) -> int:
        return index_note(Path(path), self._store, self._embedder)

    def backfill(self, *, progress: Optional[Callable] = None) -> int:
        """Index every top-level transcript in the vault. One bad note never stops it."""
        notes = self._iter_notes()
        total = len(notes)
        indexed = 0
        for i, path in enumerate(notes, 1):
            try:
                self.index_path(path)
                indexed += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning("recall backfill failed for %s: %s", path, exc)
            if progress:
                progress(i, total, path)
        return indexed

    def _iter_notes(self) -> List[Path]:
        digest_dir_name = "Malinche Digests"
        try:
            from src.config.config import get_config

            digest_dir_name = get_config().DIGEST_DIR_NAME
        except Exception:  # pragma: no cover
            pass
        return [
            p for p in sorted(self._vault.glob("*.md")) if p.parent.name != digest_dir_name
        ]

    def count(self) -> int:
        return self._store.count()

    def close(self) -> None:
        self._store.close()
