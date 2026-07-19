"""Utilities for reading YAML-like frontmatter from markdown notes."""

from pathlib import Path


def split_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """One delimiter walk → ``(frontmatter, body)``.

    An UNCLOSED opening ``---`` (note truncated mid-write) harvests keys until
    EOF while the body keeps the full text. The harvest is load-bearing: the
    transcriber's dedupe (``source``/``fingerprint``) and Obsidian-edited
    ``dismissed:`` lists must survive a missing closing delimiter, or a
    truncated note gets re-transcribed as a duplicate and hand-made dismissals
    silently vanish. (Different helper than
    ``src.connections.recall.indexer.split_frontmatter``, which returns the
    RAW frontmatter string for indexing.)
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    data: dict[str, str] = {}
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            body = "\n".join(lines[i + 1 :]).lstrip("\n")
            return data, body
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        data[key.strip()] = value.strip().strip('"')
    return data, text  # unclosed block: harvested keys + full text as body


def parse_frontmatter(text: str) -> dict[str, str]:
    """Top-of-text frontmatter block as a flat key/value dict (no file I/O)."""
    return split_frontmatter(text)[0]


def read_frontmatter(md_path: Path) -> dict[str, str]:
    """Read top-of-file frontmatter block as a flat key/value dict."""
    try:
        text = md_path.read_text(encoding="utf-8")
    except OSError:
        return {}
    return parse_frontmatter(text)
