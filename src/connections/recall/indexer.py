"""Index a note into the recall store: read -> chunk -> embed -> upsert.

Fresh-at-transcription: called at the post-transcript seam so the store is always
current, plus a one-time backfill for an existing vault. The embedding input prepends
a one-line context header (title + date) so decontextualized spoken snippets still
retrieve; the stored quote stays raw.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from src.connections.recall.chunking import chunk_body, content_hash
from src.connections.recall.embedding import EmbeddingProvider
from src.connections.recall.vector_store import VaultVectorStore
from src.logger import logger


def split_frontmatter(text: str) -> tuple:
    """Return (frontmatter, body). Body is everything after the closing ``---``."""
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            return text[3:end], text[end + 4:]
    return "", text


def _title_and_date(frontmatter: str, fallback: str) -> tuple:
    title, date = fallback, ""
    for line in frontmatter.splitlines():
        s = line.strip()
        if s.startswith("title:"):
            title = s[len("title:"):].strip().strip('"').strip("'") or title
        elif s.startswith("date:"):
            date = s[len("date:"):].strip()
    return title, date


def index_note(
    path: Path,
    store: VaultVectorStore,
    embedder: EmbeddingProvider,
    *,
    note_id: Optional[str] = None,
) -> int:
    """(Re)index one note. Returns the number of chunks stored (0 if empty)."""
    path = Path(path)
    nid = note_id or path.stem
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:  # pragma: no cover - defensive
        logger.debug("recall index: cannot read %s: %s", path, exc)
        return 0

    frontmatter, body = split_frontmatter(text)
    body = body.strip()
    if not body:
        store.delete_note(nid)
        return 0

    title, date = _title_and_date(frontmatter, path.stem)
    header = f"{title} ({date})".strip() if date else title
    chunks = chunk_body(nid, body, version_hash=content_hash(body))
    if not chunks:
        store.delete_note(nid)
        return 0

    inputs = [f"{header}\n{c.text}" for c in chunks]
    vectors = embedder.embed_documents(inputs)
    store.upsert_note(nid, chunks, vectors)
    return len(chunks)
