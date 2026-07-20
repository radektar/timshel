"""RecallEngine — the one entry point wiring embedder + store + retriever from config.

Search is local and LLM-free. ``backfill`` indexes an existing vault once;
``index_path`` keeps the store fresh at transcription time. If the configured
embedding model changes (different dim), the store is rebuilt rather than corrupted.

When the dense stack (fastembed + sqlite-vec) is unavailable — the bundled app
ships without it and has no pip — the engine degrades to **lexical-only** mode:
same store file, chunks without vectors, pure-BM25 search. Switching modes
(deps appear or disappear) rebuilds the store; the background backfill refills it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, List, Optional, Tuple

from src.connections.recall.embedding import EmbeddingProvider, resolve_embedder
from src.connections.recall.indexer import index_note
from src.connections.recall.retriever import HybridRetriever, Result
from src.connections.recall.vector_store import VaultVectorStore
from src.config.defaults import SIDECAR_DIR_NAME
from src.logger import logger

DB_FILENAME = "vault_vectors.db"


def dense_stack_available() -> bool:
    """True when the dense channel's optional deps import (fastembed + sqlite-vec)."""
    from src.runtime_deps import ensure_importable

    return ensure_importable("fastembed") and ensure_importable("sqlite_vec")


class RecallEngine:
    """Local recall over a vault: backfill/index -> hybrid search. No LLM."""

    def __init__(
        self, vault_dir, *, db_path=None, provider=None, model=None, dense=None
    ):
        self._vault = Path(vault_dir)
        self._dense = dense_stack_available() if dense is None else bool(dense)
        self._embedder: Optional[EmbeddingProvider] = (
            resolve_embedder(provider, model) if self._dense else None
        )
        if not self._dense:
            logger.info("recall: dense stack unavailable — lexical-only mode")
        self._db_path = (
            Path(db_path)
            if db_path
            else self._vault / SIDECAR_DIR_NAME / DB_FILENAME
        )
        self._store = self._open_store()
        self._retriever = HybridRetriever(self._store, self._embedder)

    @property
    def lexical_only(self) -> bool:
        return not self._dense

    def _open_store(self) -> VaultVectorStore:
        mode = "dense" if self._dense else "lexical"
        dim = self._embedder.dim if self._embedder is not None else 0
        if self._db_path.exists():
            stored_mode, stored_dim = self._probe_meta()
            if stored_mode != mode or (self._dense and stored_dim not in (None, dim)):
                logger.info(
                    "recall: store mode/dim changed (%s/%s -> %s/%s); rebuilding",
                    stored_mode,
                    stored_dim,
                    mode,
                    dim,
                )
                self._db_path.unlink()
        store = VaultVectorStore(self._db_path, dim, dense=self._dense)
        store.set_meta("mode", mode)
        store.set_meta("dim", str(dim))
        if self._embedder is not None:
            store.set_meta("model", self._embedder.model_id)
        return store

    def _probe_meta(self) -> Tuple[str, Optional[int]]:
        """(mode, dim) stored in an existing DB. Pre-mode DBs were always dense."""
        import sqlite3

        mode, dim = "dense", None
        try:
            db = sqlite3.connect(str(self._db_path))
            for key, value in db.execute(
                "SELECT key, value FROM meta WHERE key IN ('mode', 'dim')"
            ).fetchall():
                if key == "mode":
                    mode = value
                elif key == "dim":
                    dim = int(value)
            db.close()
        except sqlite3.Error:  # pragma: no cover - defensive
            pass
        return mode, dim

    def search(self, query: str, k: int = 8) -> List[Result]:
        return self._retriever.search(query, k=k)

    def search_scored(self, query: str, k: int = 8) -> Tuple[List[Result], float]:
        """Hybrid search plus the top dense cosine similarity (confidence signal)."""
        return self._retriever.search_scored(query, k=k)

    def knn_note_ids(self, query: str, k: int = 20) -> List[str]:
        """Pure-dense neighbours: unique note ids by ascending vector distance.

        The seam the digest lane's dense preselection channel uses — no BM25,
        no fusion, just 'which notes live near this text in embedding space'.
        Empty in lexical-only mode — the digest lane's other channels still run.
        """
        if self._embedder is None:
            return []
        hits = self._store.knn(self._embedder.embed_query(query), k=k * 4)
        out: List[str] = []
        seen = set()
        for h in hits:
            if h.note_id in seen:
                continue
            seen.add(h.note_id)
            out.append(h.note_id)
            if len(out) >= k:
                break
        return out

    def index_path(self, path) -> int:
        return index_note(Path(path), self._store, self._embedder)

    def backfill(
        self, *, progress: Optional[Callable] = None, incremental: bool = False
    ) -> int:
        """Index every top-level transcript in the vault. One bad note never stops it.

        ``incremental`` skips notes already indexed at their current content hash — so
        a background catch-up on every launch only embeds what's new or changed. Returns
        the number of notes actually (re)indexed. ``progress(done, total, path)`` fires
        for every note, skipped or not, so a first-run UI can show honest coverage.
        """
        notes = self._iter_notes()
        total = len(notes)
        indexed = 0
        for i, path in enumerate(notes, 1):
            try:
                if incremental and self._is_current(path):
                    pass  # already indexed at this content hash — skip the embed
                else:
                    self.index_path(path)
                    indexed += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning("recall backfill failed for %s: %s", path, exc)
            if progress:
                progress(i, total, path)
        return indexed

    def _is_current(self, path) -> bool:
        """True if ``path`` is already indexed at its current content hash."""
        from src.connections.recall.chunking import content_hash
        from src.connections.recall.indexer import split_frontmatter

        stored = self._store.note_version(Path(path).stem)
        if not stored:
            return False
        try:
            text = Path(path).read_text(encoding="utf-8", errors="replace")
        except OSError:  # pragma: no cover - defensive
            return False
        _, body = split_frontmatter(text)
        return stored == content_hash(body.strip())

    def _iter_notes(self) -> List[Path]:
        digest_dir_name = "Timshel Digests"
        try:
            from src.config.config import get_config

            digest_dir_name = get_config().DIGEST_DIR_NAME
        except Exception:  # pragma: no cover
            pass
        return [
            p
            for p in sorted(self._vault.glob("*.md"))
            if p.parent.name != digest_dir_name
        ]

    def count(self) -> int:
        return self._store.count()

    def close(self) -> None:
        self._store.close()
