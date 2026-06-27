"""Open vault files in Obsidian via the ``obsidian://`` URL scheme.

Kept AppKit-free and config-light so URL building and path resolution stay
unit-testable on their own; only :func:`open_url` touches the OS. Malinche is a
lens over the vault, not a second reader — clicking a note or transcript hands
off to Obsidian rather than rendering it in-app.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Optional
from urllib.parse import quote

from src.logger import logger


def obsidian_url(path: Path) -> str:
    """Build an ``obsidian://open?path=…`` URL for an absolute vault file path.

    The ``path`` form needs no vault name — Obsidian resolves which open vault
    contains the file — so it survives the user renaming their vault.
    """
    abs_path = str(Path(path).expanduser().resolve())
    return "obsidian://open?path=" + quote(abs_path, safe="")


def resolve_note_path(basename: str, vault_dir: Path) -> Optional[Path]:
    """Find the markdown file for a bare ``basename`` inside the vault.

    Synthesis returns note ids as bare basenames (e.g. ``"Cooling v1"``); the
    file may sit in any subfolder, so we search rather than assume a flat
    layout. Returns the first match, or ``None`` if nothing matches.
    """
    basename = (basename or "").strip().strip("[]").strip()
    if not basename:
        return None
    vault_dir = Path(vault_dir).expanduser()
    direct = vault_dir / f"{basename}.md"
    if direct.exists():
        return direct
    try:
        for hit in vault_dir.rglob(f"{basename}.md"):
            return hit
        # Exact match failed — try a tolerant pass. Synthesis echoes note ids as
        # the model saw them, so case or whitespace can drift from the real
        # filename; match on a normalized stem before giving up to search.
        want = _normalize(basename)
        for hit in vault_dir.rglob("*.md"):
            if _normalize(hit.stem) == want:
                return hit
    except OSError as exc:  # pragma: no cover - defensive
        logger.debug("note path search failed for %r: %s", basename, exc)
    return None


def _normalize(name: str) -> str:
    """Lowercase and collapse internal whitespace for tolerant stem matching."""
    return " ".join((name or "").split()).casefold()


def open_url(url: str) -> bool:
    """Open a URL via the macOS ``open`` command. Best-effort; logs on failure."""
    try:
        subprocess.run(["open", url], check=True)
        return True
    except (OSError, subprocess.CalledProcessError) as exc:
        logger.warning("could not open Obsidian URL (%s): %s", url, exc)
        return False


def open_path(path: Path) -> bool:
    """Resolve and open an absolute vault file path in Obsidian."""
    return open_url(obsidian_url(path))


def open_note(basename: str, vault_dir: Path) -> bool:
    """Resolve a bare note basename inside ``vault_dir`` and open it in Obsidian.

    Falls back to an ``obsidian://search`` so a click never silently does
    nothing when the exact file can't be located (e.g. a renamed note).
    """
    path = resolve_note_path(basename, vault_dir)
    if path is not None:
        return open_path(path)
    query = (basename or "").strip().strip("[]").strip()
    if not query:
        return False
    logger.debug("note %r not found on disk — falling back to Obsidian search", query)
    return open_url("obsidian://search?query=" + quote(query, safe=""))
