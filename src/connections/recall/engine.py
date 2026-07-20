"""RecallEngine — the one entry point wiring embedder + store + retriever from config.

Search is local and LLM-free. ``backfill`` indexes an existing vault once;
``index_path`` keeps the store fresh at transcription time. If the configured
embedding model changes (different dim), the store is rebuilt rather than corrupted.

When the dense stack (fastembed + sqlite-vec) is unavailable — the bundled app
ships without it and has no pip — the engine degrades to **lexical-only** mode:
chunks without vectors, pure-BM25 search, in its OWN store file
(``vault_lexical.db``). The two mode files coexist on purpose: a deps flip
rebuilds nothing on default paths, and each mode's index survives the other
environment untouched. Mode-mismatch rebuilds only apply to an explicit
``db_path`` shared across modes. The probe is passive (no pip) — a dev setup
gets dense mode by installing the deps (``make install``), not as a side
effect of searching.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from src.connections.recall.embedding import EmbeddingProvider, resolve_embedder
from src.connections.recall.indexer import index_note
from src.connections.recall.retriever import HybridRetriever, Result
from src.connections.recall.vector_store import VaultVectorStore
from src.config.defaults import SIDECAR_DIR_NAME
from src.logger import logger

DB_FILENAME = "vault_vectors.db"
# Lexical mode gets its OWN default store file. One shared file would make the
# modes destroy each other's index whenever the same vault is touched from two
# environments (bundled app = lexical, dev venv/CLI = dense) — with separate
# files both indexes coexist and a deps flip costs nothing.
LEXICAL_DB_FILENAME = "vault_lexical.db"


def dense_stack_available() -> bool:
    """True when the dense channel can actually run: a Python with loadable
    sqlite extensions AND importable fastembed + sqlite-vec. The extension
    check comes first — with deps installed on a Python that can't load them,
    the dense path would crash in ``_load_extension`` instead of degrading.

    Passive on purpose (``find_spec``, no pip): a probe that shells out to a
    180s-timeout install would block the ⌘K search worker and make the mode
    depend on network state."""
    import sqlite3

    if not hasattr(sqlite3.Connection, "enable_load_extension"):
        return False
    from src.runtime_deps import importable

    return importable("sqlite_vec") and importable("fastembed")


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
            if provider or model:
                logger.warning(
                    "recall: explicit provider/model (%s/%s) ignored — dense "
                    "stack unavailable, running lexical-only",
                    provider,
                    model,
                )
            logger.info("recall: dense stack unavailable — lexical-only mode")
        default_name = DB_FILENAME if self._dense else LEXICAL_DB_FILENAME
        self._db_path = (
            Path(db_path)
            if db_path
            else self._vault / SIDECAR_DIR_NAME / default_name
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
            # A None (unreadable) probe must NOT rebuild: a transient error
            # (locked DB, second process) defaulting to a mode would wipe a
            # healthy index. Mode mismatch is only reachable with an explicit
            # db_path shared across modes — default paths are per-mode.
            mode_mismatch = stored_mode is not None and stored_mode != mode
            dim_mismatch = (
                self._dense and stored_dim is not None and stored_dim != dim
            )
            if mode_mismatch or dim_mismatch:
                logger.info(
                    "recall: store mode/dim changed (%s/%s -> %s/%s); rebuilding",
                    stored_mode,
                    stored_dim,
                    mode,
                    dim,
                )
                self._remove_db_files()
        try:
            store = VaultVectorStore(self._db_path, dim, dense=self._dense)
        except sqlite3.DatabaseError as exc:
            # A truly unreadable FILE ("file is not a database") self-heals by
            # rebuilding once — the bundle has no CLI escape hatch, so a
            # permanent crash here means search dead until the user hand-deletes
            # a hidden file. OperationalError (locked/busy) stays fatal for this
            # construction: transient, and rebuilding would wipe a healthy index.
            if isinstance(exc, sqlite3.OperationalError):
                raise
            logger.warning("recall: store file unreadable (%s); rebuilding", exc)
            self._remove_db_files()
            store = VaultVectorStore(self._db_path, dim, dense=self._dense)
        store.set_meta("mode", mode)
        if self._embedder is not None:
            store.set_meta("dim", str(dim))
            store.set_meta("model", self._embedder.model_id)
        return store

    def _remove_db_files(self) -> None:
        """Drop the store file AND its sqlite sidecars. A leftover hot
        -journal would roll stale pages of the old store into the freshly
        created file — which then gets stamped with the new mode/dim meta
        and the corruption becomes undetectable."""
        for suffix in ("", "-journal", "-wal", "-shm"):
            Path(str(self._db_path) + suffix).unlink(missing_ok=True)

    def _probe_meta(self) -> Tuple[Optional[str], Optional[int]]:
        """(mode, dim) stored in an existing DB; (None, None) when unreadable.

        Pre-mode DBs carry only ``dim`` and were always dense.
        """
        import sqlite3

        db = None
        try:
            db = sqlite3.connect(str(self._db_path))
            rows = dict(
                db.execute(
                    "SELECT key, value FROM meta WHERE key IN ('mode', 'dim')"
                ).fetchall()
            )
        except sqlite3.Error:
            return None, None
        finally:
            if db is not None:
                db.close()
        try:
            dim = int(rows["dim"]) if "dim" in rows else None
        except ValueError:  # pragma: no cover - defensive
            dim = None
        return rows.get("mode", "dense"), dim

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
