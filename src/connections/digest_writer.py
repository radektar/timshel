"""Render synthesized connections as a calm digest note in the vault.

The digest is a first-class Obsidian note (so ``[[wikilinks]]`` resolve), written
to a dedicated ``Timshel Digests/`` subfolder that candidate assembly excludes —
so a digest never feeds itself. We build the markdown with plain string joins
(no ``str.format``), so literal braces in model text need no escaping.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import List, Tuple

from src.config import config
from src.connections.signature import connection_signature
from src.connections.synthesis import Connection
from src.logger import logger

_TYPE_LABELS = {
    "shared-thread": "Shared thread",
    "contradiction-over-time": "Contradiction over time",
    "emergent-idea": "Emergent idea",
}


def _unique_path(folder: Path, stem: str) -> Path:
    """Collision-safe '<stem>.md', appending ' (n)' as needed."""
    candidate = folder / f"{stem}.md"
    counter = 2
    while candidate.exists():
        candidate = folder / f"{stem} ({counter}).md"
        counter += 1
    return candidate


def _wikilinks(basenames: List[str]) -> str:
    return " · ".join(f"[[{name}]]" for name in basenames)


def render_digest(connections: List[Connection], notes_considered: int) -> str:
    """Return the full markdown body (frontmatter + sections)."""
    date = datetime.now().strftime("%Y-%m-%d")
    out: List[str] = [
        "---",
        f'title: "Synthesis digest — {date}"',
        f"date: {date}",
        "type: timshel-digest",
        "generated_by: timshel",
        f"notes_considered: {notes_considered}",
        "dismissed: []",
        "tags: [timshel-digest]",
        "---",
        "",
        f"> Timshel read {notes_considered} notes and noticed a few things that "
        "may connect.",
        "> These are prompts, not tasks. To dismiss one, add its number to the "
        "`dismissed:` list in this note's frontmatter (e.g. `dismissed: [1, 3]`) "
        "— Timshel won't resurface it.",
        "",
    ]
    for idx, conn in enumerate(connections, start=1):
        label = _TYPE_LABELS.get(conn.type, conn.type)
        out.append(f"## {idx}. {label}: {conn.rationale}")
        out.append(f"Notes: {_wikilinks(conn.notes)}")
        if conn.evidence:
            out.append("Based on:")
            for ev in conn.evidence:
                date = f"{ev.date} · " if ev.date else ""
                out.append(f"- {date}[[{ev.note}]]: „{ev.quote}”")
        out.append("Directions you could take this:")
        for direction in conn.directions:
            out.append(f"- {direction}")
        out.append(f"`dismiss: {idx}`")
        out.append("")
    return "\n".join(out)


def _write_insights_sidecar(connections: List[Connection], digest_path: Path) -> None:
    """Persist the full connections for the Insights window.

    The digest ``.md`` is lossy for the UI (the window needs the structured
    type / notes / rationale / directions). This drops a single
    ``{vault}/.timshel/insights-latest.json`` the dashboard reads. Best-effort:
    a failure here must never disturb the digest write itself.
    """
    import json

    try:
        out_dir = Path(config.TRANSCRIBE_DIR) / config.SIDECAR_DIR_NAME
        out_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "digest": digest_path.name,
            "connections": [
                {
                    "type": c.type,
                    "sig": connection_signature(c.notes, c.type),
                    "notes": list(c.notes),
                    "rationale": c.rationale,
                    "evidence": [
                        {"note": e.note, "date": e.date, "quote": e.quote}
                        for e in c.evidence
                    ],
                    "directions": list(c.directions),
                }
                for c in connections
            ],
        }
        target = out_dir / "insights-latest.json"
        tmp = target.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        tmp.replace(target)
    except Exception as exc:  # noqa: BLE001
        logger.warning("insights sidecar write failed (non-fatal): %s", exc)


def write_digest_note(
    connections: List[Connection], notes_considered: int
) -> Tuple[Path, List[dict]]:
    """Write the digest note and return (path, ordered connection metadata).

    Each metadata dict is ``{"sig", "notes", "type"}`` in the same order as the
    rendered sections (1-based), so a frontmatter ``dismissed: [n]`` edit maps
    back to a connection signature.
    """
    folder = Path(config.TRANSCRIBE_DIR) / config.DIGEST_DIR_NAME
    folder.mkdir(parents=True, exist_ok=True)
    date = datetime.now().strftime("%Y-%m-%d")
    path = _unique_path(folder, f"{date} Synthesis")

    body = render_digest(connections, notes_considered)
    tmp = path.with_suffix(".md.tmp")
    tmp.write_text(body, encoding="utf-8")
    tmp.replace(path)

    _write_insights_sidecar(connections, path)

    conn_meta = [
        {
            "sig": connection_signature(c.notes, c.type),
            "notes": list(c.notes),
            "type": c.type,
        }
        for c in connections
    ]
    logger.info("wrote synthesis digest: %s (%d connections)", path, len(connections))
    return path, conn_meta
