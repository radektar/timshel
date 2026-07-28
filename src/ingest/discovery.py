"""Find importable files in a folder — ONE definition, shared by every caller.

The wizard counts files to ask for consent ("Found N notes"), the
first-session flow imports them, and ``scripts/import_text.py`` walks folders
from the CLI. When those three walked the tree independently they drifted:
different bounds (so the confirmed count and the imported set disagreed) and
no exclusions (so pointing the import at a Timshel vault re-imported its own
notes and digests — each a paid summary).

Rules encoded here once:
  * only ``SUPPORTED_SUFFIXES`` files,
  * skip hidden directories (``.obsidian``, ``.timshel``, ``.git`` …) — they
    hold app state, not the user's notes,
  * skip the Timshel vault itself and its digest folder (see
    :func:`is_vault_path`) so an import can never feed Timshel its own output,
  * bounded traversal so picking a home directory cannot hang the caller.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterator, List, Optional

from src.ingest.adapters import SUPPORTED_SUFFIXES

#: Traversal cap — a user may point at ``~``; we must not walk forever.
MAX_SCANNED_ENTRIES = 50_000


def is_vault_path(path: Path, vault_dir: Optional[Path] = None) -> bool:
    """True when ``path`` is the Timshel vault, or inside it.

    Importing from the vault would re-ingest Timshel's own notes and digests
    as new notes: the text fingerprint differs from the original audio one,
    so dedupe misses, the vault doubles, every copy costs a paid summary and
    digests re-enter the corpus as ordinary notes.
    """
    if vault_dir is None:
        from src.config import config

        vault_dir = Path(config.TRANSCRIBE_DIR)
    try:
        path = Path(path).expanduser().resolve()
        vault = Path(vault_dir).expanduser().resolve()
    except OSError:  # pragma: no cover - unresolvable path
        return False
    return path == vault or vault in path.parents or path in vault.parents


def _skip_dir(part: str) -> bool:
    return part.startswith(".")


def iter_importable(folder: Path, vault_dir: Optional[Path] = None) -> Iterator[Path]:
    """Yield importable files under ``folder`` (bounded, exclusions applied)."""
    from src.config import config

    if vault_dir is None:
        vault_dir = Path(config.TRANSCRIBE_DIR)
    digest_dir = str(config.DIGEST_DIR_NAME)
    sidecar_dir = str(config.SIDECAR_DIR_NAME)
    root = Path(folder).expanduser()
    scanned = 0
    for path in sorted(root.rglob("*")):
        scanned += 1
        if scanned > MAX_SCANNED_ENTRIES:
            break
        if not path.is_file() or path.suffix.lower() not in SUPPORTED_SUFFIXES:
            continue
        rel_parts = path.relative_to(root).parts[:-1]
        if any(_skip_dir(p) or p in (digest_dir, sidecar_dir) for p in rel_parts):
            continue
        if is_vault_path(path.parent, vault_dir):
            continue
        yield path


def list_importable(folder: Path, vault_dir: Optional[Path] = None) -> List[Path]:
    """``iter_importable`` as a list — the count and the import agree."""
    return list(iter_importable(folder, vault_dir))
