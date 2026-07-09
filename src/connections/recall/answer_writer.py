"""Persist a synthesized recall answer to the vault as a markdown note.

The card is grounded (thesis + cited evidence + directions), so saving it keeps a
durable, linkable record with live ``[[wikilinks]]`` back to the source notes —
the "save answer to vault" step of the pull surface. ``render_answer_md`` is pure
(testable); ``save_answer`` writes it under a ``Timshel Recall`` sub-folder.
"""

from __future__ import annotations

import re
from pathlib import Path

from src.connections.digest_writer import _unique_path

RECALL_DIR_NAME = "Timshel Recall"

_SLUG_STRIP = re.compile(r"[^\w\s-]", re.UNICODE)
_SLUG_SPACE = re.compile(r"\s+")


def _slug(text: str, limit: int = 60) -> str:
    s = _SLUG_STRIP.sub("", (text or "").strip())
    s = _SLUG_SPACE.sub(" ", s).strip()
    return s[:limit].strip() or "zapytanie"


def _oneline(text: str) -> str:
    """Collapse all whitespace (incl. newlines) to single spaces — for one-line fields
    (callout, list items) that a raw newline would otherwise break."""
    return " ".join((text or "").split())


def _yaml_str(text: str) -> str:
    """A YAML-safe double-quoted scalar body for user text: single-line, with `\\` and
    `"` escaped so a query containing a quote/backslash can't corrupt the frontmatter."""
    return _oneline(text).replace("\\", "\\\\").replace('"', '\\"')


def _blockquote(text: str) -> str:
    """Render a possibly-multiline fragment as a markdown blockquote — every physical
    line gets the `> ` marker, so a newline in the quote can't drop out of the quote."""
    body = (text or "").strip()
    return "\n".join(f"  > {ln}" for ln in (body.splitlines() or [""]))


def render_answer_md(query: str, answer, *, date_str: str) -> str:
    """Render a synthesized answer as a markdown note (pure — no I/O)."""
    lines = [
        "---",
        "type: timshel-recall-answer",
        f'question: "{_yaml_str(query)}"',
        f"date: {date_str}",
        "tags: [timshel-recall]",
        "---",
        "",
        f"> [!question] {_oneline(query)}",
        "",
        (getattr(answer, "thesis", "") or "").strip(),
        "",
    ]
    if getattr(answer, "evidence", None):
        lines.append("## Dowód")
        lines.append("")
        for ev in answer.evidence:
            date = f"{_oneline(ev.date)} · " if ev.date else ""
            lines.append(f"- {date}[[{_oneline(ev.note)}]]")
            lines.append(_blockquote(ev.quote))
        lines.append("")
    if getattr(answer, "directions", None):
        lines.append("## Kierunki")
        lines.append("")
        for d in answer.directions:
            lines.append(f"- {_oneline(d)}")
        lines.append("")
    if not getattr(answer, "answered", True):
        lines.append("*Notatki nie pokrywają tego pytania — odpowiedź powyżej mówi to wprost.*")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def save_answer(
    query: str,
    answer,
    vault_dir,
    *,
    date_str: str,
    subdir: str = RECALL_DIR_NAME,
) -> Path:
    """Write the rendered answer under ``<vault>/<subdir>/`` and return its path.

    ``date_str`` is passed in (not read from the clock) so the caller controls the
    filename and the note stays deterministic/testable. Reuses ``digest_writer.
    _unique_path`` so a second answer to the same question on the same day gets a
    ``(2)`` suffix instead of silently overwriting the first.
    """
    out_dir = Path(vault_dir) / subdir
    out_dir.mkdir(parents=True, exist_ok=True)
    path = _unique_path(out_dir, f"{date_str} Recall - {_slug(query)}")
    path.write_text(render_answer_md(query, answer, date_str=date_str), encoding="utf-8")
    return path
