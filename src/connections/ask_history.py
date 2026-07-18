"""Persistent, fully local ask history (redesign U8 / §12 „askHistory").

Feeds two surfaces of the Konstelacja window: the history sheet under the
toolbar field (3–5 most recent questions) and the rail's „Zapytałeś" section
(entries + counter). One JSON file in the vault's ``.timshel`` sidecar —
``{query, fragmentCount, timestamp}`` per entry, newest first. Nothing here
ever leaves the machine.

Best-effort like the signal log: a broken vault path must never reach a click
handler, so every operation degrades to a no-op with a logged warning.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import List, Optional, TypedDict

from src.config.defaults import SIDECAR_DIR_NAME
from src.logger import logger

#: Hard cap so the file can't grow unbounded over years of questions.
_MAX_ENTRIES = 200


class AskEntry(TypedDict):
    query: str
    fragmentCount: int
    timestamp: str


def history_path(vault_dir: Optional[Path] = None) -> Optional[Path]:
    """``{vault}/.timshel/ask_history.json`` (vault from config when omitted)."""
    try:
        if vault_dir is None:
            from src.config import config

            vault_dir = Path(config.TRANSCRIBE_DIR)
        return Path(vault_dir) / SIDECAR_DIR_NAME / "ask_history.json"
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("ask history path unavailable: %s", exc)
        return None


def load(vault_dir: Optional[Path] = None) -> List[AskEntry]:
    """All entries, newest first. Missing/corrupt file → ``[]``, never raises."""
    path = history_path(vault_dir)
    if path is None or not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        out: List[AskEntry] = []
        for row in data if isinstance(data, list) else []:
            if isinstance(row, dict) and str(row.get("query") or "").strip():
                out.append(
                    AskEntry(
                        query=str(row["query"]),
                        fragmentCount=int(row.get("fragmentCount") or 0),
                        timestamp=str(row.get("timestamp") or ""),
                    )
                )
        return out
    except Exception as exc:  # noqa: BLE001 - a corrupt file must not break the UI
        logger.warning("could not read ask history: %s", exc)
        return []


def append(
    query: str,
    fragment_count: int,
    *,
    vault_dir: Optional[Path] = None,
    now: Optional[datetime] = None,
) -> bool:
    """Prepend one executed question. Re-asking moves it to the top (dedup)."""
    query = (query or "").strip()
    path = history_path(vault_dir)
    if not query or path is None:
        return False
    try:
        entries = [e for e in load(vault_dir) if e["query"] != query]
        entries.insert(
            0,
            AskEntry(
                query=query,
                fragmentCount=max(int(fragment_count), 0),
                timestamp=(now or datetime.now()).isoformat(timespec="seconds"),
            ),
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(entries[:_MAX_ENTRIES], ensure_ascii=False, indent=1),
            encoding="utf-8",
        )
        tmp.replace(path)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("could not append ask history: %s", exc)
        return False


def recent(n: int = 5, vault_dir: Optional[Path] = None) -> List[AskEntry]:
    """The ``n`` most recent questions (sheet shows 3–5)."""
    return load(vault_dir)[: max(n, 0)]


def count(vault_dir: Optional[Path] = None) -> int:
    """Section counter for „Zapytałeś"."""
    return len(load(vault_dir))


def clear(vault_dir: Optional[Path] = None) -> bool:
    """„Wyczyść historię" — removes the file (local data, user-owned)."""
    path = history_path(vault_dir)
    if path is None:
        return False
    try:
        path.unlink(missing_ok=True)
        return True
    except OSError as exc:
        logger.warning("could not clear ask history: %s", exc)
        return False
