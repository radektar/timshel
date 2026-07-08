"""Open vault notes in the user's markdown app — Obsidian, Pile, Finder, or the
system default — not Obsidian by assumption.

Notes are plain markdown files, so the opener is a configurable strategy
(``note_opener`` setting / ``Config.NOTE_OPENER``): the ``obsidian://`` deep link
is one option among several, and stays the default for existing users.

Kept AppKit-free; URL/argv building and path resolution stay config-free and
unit-testable on their own — only the ``open_*`` helpers touch the OS. Timshel
is a lens over the vault, not a second reader: clicking a note hands off to the
chosen app rather than rendering it in-app.
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


def _run_open(argv: list, what: str) -> bool:
    """Run ``open …`` best-effort via the macOS ``open`` command; log on failure."""
    try:
        subprocess.run(argv, check=True)
        return True
    except (OSError, subprocess.CalledProcessError) as exc:
        logger.warning("could not open %r (%s): %s", what, argv, exc)
        return False


def file_open_argv(path: Path, opener: str = "obsidian") -> list:
    """Build the ``open`` argv to open ``path`` per the chosen markdown app.

    Strategies (the ``note_opener`` setting):

    - ``"obsidian"`` — ``obsidian://open?path=…`` deep link (default, legacy)
    - ``"finder"``   — reveal the file in Finder (``open -R``)
    - ``"default"``  — hand to the system default ``.md`` handler (``open``)
    - ``"app:<Name>"`` — open with a named app (``open -a <Name>``), e.g.
      ``"app:Pile"`` or ``"app:Typora"``

    Notes are plain files, so every strategy works on any vault — Obsidian is
    one option, not an assumption.
    """
    abs_path = str(Path(path).expanduser().resolve())
    if opener == "finder":
        return ["open", "-R", abs_path]
    if opener and opener.startswith("app:"):
        app = opener[4:].strip()
        if app:
            return ["open", "-a", app, abs_path]
    if opener in ("default", "system"):
        return ["open", abs_path]
    # "obsidian" or unknown → Obsidian deep link (preserves legacy behaviour).
    return ["open", obsidian_url(Path(abs_path))]


def open_url(url: str) -> bool:
    """Open a URL (e.g. an ``obsidian://`` deep link) via macOS ``open``."""
    return _run_open(["open", url], url)


def open_path(path: Path, opener: str = "obsidian") -> bool:
    """Open an absolute vault file path in the configured markdown app."""
    return _run_open(file_open_argv(path, opener), str(path))


def open_note(basename: str, vault_dir: Path, opener: str = "obsidian") -> bool:
    """Resolve a bare note basename inside ``vault_dir`` and open it.

    When the file can't be located and the opener is Obsidian, falls back to an
    ``obsidian://search`` so a click never silently does nothing. Other openers
    have no search equivalent, so a miss just logs (best-effort).
    """
    path = resolve_note_path(basename, vault_dir)
    if path is not None:
        return open_path(path, opener)
    query = (basename or "").strip().strip("[]").strip()
    if not query:
        return False
    if opener in (None, "", "obsidian"):
        logger.debug("note %r not found on disk — falling back to Obsidian search", query)
        return open_url("obsidian://search?query=" + quote(query, safe=""))
    logger.debug("note %r not found on disk (opener=%r) — no-op", query, opener)
    return False
