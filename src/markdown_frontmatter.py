"""Utilities for reading YAML-like frontmatter from markdown notes."""

from pathlib import Path


def parse_frontmatter(text: str) -> dict[str, str]:
    """Top-of-text frontmatter block as a flat key/value dict (no file I/O)."""
    data: dict[str, str] = {}
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return data

    for line in lines[1:]:
        if line.strip() == "---":
            break
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        data[key.strip()] = value.strip().strip('"')
    return data


def read_frontmatter(md_path: Path) -> dict[str, str]:
    """Read top-of-file frontmatter block as a flat key/value dict."""
    try:
        text = md_path.read_text(encoding="utf-8")
    except OSError:
        return {}
    return parse_frontmatter(text)
