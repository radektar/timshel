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
from src.logger import logger

#: Traversal cap — a user may point at ``~``; we must not walk forever.
MAX_SCANNED_ENTRIES = 50_000


def is_vault_path(path: Path, vault_dir: Optional[Path] = None) -> bool:
    """True when ``path`` IS the Timshel vault or lies inside it.

    Importing from the vault would re-ingest Timshel's own notes and digests
    as new notes: the text fingerprint differs from the original audio one,
    so dedupe misses, the vault doubles, every copy costs a paid summary and
    digests re-enter the corpus as ordinary notes.

    A parent of the vault is NOT refused — the flagship case is transcripts
    living as a subfolder of an Obsidian vault, so "import my Obsidian
    vault" must work; :func:`iter_importable` drops the vault subtree
    per-file instead.
    """
    if vault_dir is None:
        from src.config import config

        vault_dir = Path(config.TRANSCRIBE_DIR)
    try:
        path = Path(path).expanduser().resolve()
        vault = Path(vault_dir).expanduser().resolve()
    except OSError:  # pragma: no cover - unresolvable path
        return False
    return path == vault or vault in path.parents


def _skip_dir(part: str) -> bool:
    return part.startswith(".")


def iter_importable(folder: Path, vault_dir: Optional[Path] = None) -> Iterator[Path]:
    """Yield importable files under ``folder`` (bounded, exclusions applied).

    Walks lazily and stops after :data:`MAX_SCANNED_ENTRIES` entries — the
    wizard counts on the UI path, so picking a home directory must never hang
    it. (Sorting the whole tree first would defeat the bound: the walk would
    complete before the cap could apply. Callers wanting deterministic order
    use :func:`list_importable`, which sorts the bounded RESULT.)
    """
    from src.config import config

    if vault_dir is None:
        vault_dir = Path(config.TRANSCRIBE_DIR)
    digest_dir = str(config.DIGEST_DIR_NAME)
    sidecar_dir = str(config.SIDECAR_DIR_NAME)
    root = Path(folder).expanduser()
    # Resolve the vault ONCE: a per-file resolve() made the wizard's count
    # ~20x slower on a few thousand files.
    try:
        vault_resolved = Path(vault_dir).expanduser().resolve()
        root_resolved = root.resolve()
    except OSError:  # pragma: no cover - unresolvable path
        return
    scanned = 0
    for path in root.rglob("*"):
        scanned += 1
        if scanned > MAX_SCANNED_ENTRIES:
            logger.info("import scan stopped at %d entries under %s", scanned - 1, root)
            break
        if path.suffix.lower() not in SUPPORTED_SUFFIXES or not path.is_file():
            continue
        rel_parts = path.relative_to(root).parts[:-1]
        if any(_skip_dir(p) or p in (digest_dir, sidecar_dir) for p in rel_parts):
            continue
        # Vault subtree: drop the FILE (its parent is the vault or inside it),
        # while still importing everything else under a parent folder.
        parent = root_resolved.joinpath(*rel_parts) if rel_parts else root_resolved
        if parent == vault_resolved or vault_resolved in parent.parents:
            continue
        yield path


def list_importable(folder: Path, vault_dir: Optional[Path] = None) -> List[Path]:
    """``iter_importable`` as a sorted list — the count and the import agree."""
    return sorted(iter_importable(folder, vault_dir))
