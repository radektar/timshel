"""Persist a synthesized recall answer to the vault as a markdown note.

The card is grounded (thesis + cited evidence + directions), so saving it keeps a
durable, linkable record with live ``[[wikilinks]]`` back to the source notes —
the "save answer to vault" step of the pull surface. ``render_answer_md`` is pure
(testable); ``save_answer`` writes it under a ``Malinche Recall`` sub-folder.
"""

from __future__ import annotations

import re
from pathlib import Path

RECALL_DIR_NAME = "Malinche Recall"

_SLUG_STRIP = re.compile(r"[^\w\s-]", re.UNICODE)
_SLUG_SPACE = re.compile(r"\s+")


def _slug(text: str, limit: int = 60) -> str:
    s = _SLUG_STRIP.sub("", (text or "").strip())
    s = _SLUG_SPACE.sub(" ", s).strip()
    return s[:limit].strip() or "zapytanie"


def render_answer_md(query: str, answer, *, date_str: str) -> str:
    """Render a synthesized answer as a markdown note (pure — no I/O)."""
    lines = [
        "---",
        'type: malinche-recall-answer',
        f'question: "{(query or "").strip()}"',
        f"date: {date_str}",
        "tags: [malinche-recall]",
        "---",
        "",
        f"> [!question] {(query or '').strip()}",
        "",
        (answer.thesis or "").strip(),
        "",
    ]
    if getattr(answer, "evidence", None):
        lines.append("## Dowód")
        lines.append("")
        for ev in answer.evidence:
            date = f"{ev.date} · " if ev.date else ""
            lines.append(f"- {date}[[{ev.note}]]")
            lines.append(f"  > {(ev.quote or '').strip()}")
        lines.append("")
    if getattr(answer, "directions", None):
        lines.append("## Kierunki")
        lines.append("")
        for d in answer.directions:
            lines.append(f"- {(d or '').strip()}")
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
    filename and the note stays deterministic/testable.
    """
    out_dir = Path(vault_dir) / subdir
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{date_str} Recall - {_slug(query)}.md"
    path.write_text(render_answer_md(query, answer, date_str=date_str), encoding="utf-8")
    return path
