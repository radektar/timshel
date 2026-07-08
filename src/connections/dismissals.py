"""Persistence for user-dismissed connections (the 'not relevant' affordance).

Stored in ``{vault}/.timshel/connections.json`` using the same fcntl-locked,
atomic read-modify-write pattern as :class:`VaultIndex`, so the daemon and the
menu app never corrupt it. A dismissed connection is filtered out at candidate
assembly *and* fed back to the synthesis prompt as "do not re-surface" — which
is what stops a noisy feature from poisoning trust (POSITIONING: "false
positives tolerable IF dismissible").
"""

from __future__ import annotations

import fcntl
import json
import os
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List

from src.config.defaults import SIDECAR_DIR_NAME
from src.connections.signature import connection_signature  # canonical (ADR-004)
from src.logger import logger

__all__ = ["DismissalStore", "connection_signature"]


def _parse_int_list(raw: str) -> List[int]:
    """Parse a frontmatter list like ``[1, 3]`` into ``[1, 3]`` (ignores junk)."""
    raw = (raw or "").strip()
    if raw.startswith("[") and raw.endswith("]"):
        raw = raw[1:-1]
    out: List[int] = []
    for tok in raw.split(","):
        tok = tok.strip()
        if tok.isdigit():
            out.append(int(tok))
    return out


class DismissalStore:
    """Tracks dismissed connection signatures and muted notes (fcntl-safe)."""

    def __init__(self, vault_dir: Path):
        self.vault_dir = Path(vault_dir)
        self.dir = self.vault_dir / SIDECAR_DIR_NAME
        self.path = self.dir / "connections.json"
        self.lock_path = self.dir / "connections.lock"
        self._data: Dict[str, Any] = self._empty()

    @staticmethod
    def _empty() -> Dict[str, Any]:
        return {
            "version": 1,
            "dismissed_signatures": {},
            "muted_notes": [],
            "digests": [],
        }

    def load(self) -> "DismissalStore":
        self.dir.mkdir(parents=True, exist_ok=True)
        try:
            if self.path.exists():
                self._data = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("DismissalStore load failed (%s); starting empty", exc)
            self._data = self._empty()
        self._ensure_keys()
        return self

    def _ensure_keys(self) -> None:
        self._data.setdefault("dismissed_signatures", {})
        self._data.setdefault("muted_notes", [])
        self._data.setdefault("digests", [])

    # --- read-only queries (used by candidate assembly) ---
    def is_dismissed(self, signature: str) -> bool:
        return signature in self._data.get("dismissed_signatures", {})

    def note_muted(self, basename: str) -> bool:
        return basename in set(self._data.get("muted_notes", []))

    def dismissed_descriptions(self) -> List[str]:
        """Human-readable lines fed to the prompt as 'do not re-surface'."""
        out: List[str] = []
        for meta in self._data.get("dismissed_signatures", {}).values():
            notes = ", ".join(meta.get("notes", []))
            out.append(f"[{meta.get('type', '?')}] {notes}")
        return out

    # --- mutations (locked) ---
    def dismiss(self, notes: Iterable[str], conn_type: str) -> str:
        notes = list(notes)
        sig = connection_signature(notes, conn_type)
        with self._locked():
            self._data["dismissed_signatures"][sig] = {
                "at": datetime.now().isoformat(timespec="seconds"),
                "notes": notes,
                "type": conn_type,
            }
            self._save()
        return sig

    def mute_note(self, basename: str) -> None:
        with self._locked():
            muted = self._data["muted_notes"]
            if basename not in muted:
                muted.append(basename)
            self._save()

    def record_digest(
        self, digest_path: Path, connections_meta: Iterable[dict]
    ) -> None:
        with self._locked():
            self._data["digests"].append(
                {
                    "path": str(digest_path),
                    "created_at": datetime.now().isoformat(timespec="seconds"),
                    "connections": [dict(m) for m in connections_meta],
                }
            )
            self._save()

    def sync_frontmatter_dismissals(self) -> None:
        """Fold any ``dismissed: [..]`` edits in past digests into the store.

        The Obsidian-native dismiss path: the user adds a connection's number to
        the digest note's frontmatter, and the next run respects it.
        """
        from src.markdown_frontmatter import read_frontmatter

        for entry in list(self._data.get("digests", [])):
            conns = entry.get("connections") or []
            if not conns:
                continue
            try:
                fm = read_frontmatter(Path(entry["path"]))
            except Exception:  # noqa: BLE001
                continue
            for idx in _parse_int_list(fm.get("dismissed", "")):
                if 1 <= idx <= len(conns):
                    meta = conns[idx - 1]
                    self.dismiss(meta.get("notes", []), meta.get("type", "?"))

    @contextmanager
    def _locked(self):
        self.dir.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.lock_path, os.O_CREAT | os.O_RDWR)
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            try:
                if self.path.exists():
                    self._data = json.loads(self.path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                self._data = self._empty()
            self._ensure_keys()
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def _save(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        os.replace(tmp, self.path)
