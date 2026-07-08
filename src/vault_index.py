"""Vault index for multi-device deduplication and versioning."""

import json
import logging
import os
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

import fcntl

from src.config.defaults import SIDECAR_DIR_NAME

logger = logging.getLogger(__name__)


@dataclass
class IndexEntry:
    """Single fingerprint entry in index."""

    fingerprint: str
    source_filename: str
    source_volume: str
    markdown_path: str
    versions: list[dict[str, Any]] = field(default_factory=list)
    source_size: int = 0


class VaultIndex:
    """Index manager backed by the vault sidecar dir's index.json."""

    def __init__(self, vault_dir: Path):
        self.vault_dir = Path(vault_dir)
        self.index_dir = self.vault_dir / SIDECAR_DIR_NAME
        self.index_path = self.index_dir / "index.json"
        self.lock_path = self.index_dir / "index.lock"
        self._data: Dict[str, Any] = {"version": 1, "entries": {}}

    def load(self) -> None:
        """Load index from disk, or initialize empty index."""
        self.index_dir.mkdir(parents=True, exist_ok=True)
        if not self.index_path.exists():
            self._save()
            return
        try:
            self._data = json.loads(self.index_path.read_text(encoding="utf-8"))
            if "entries" not in self._data:
                self._data["entries"] = {}
        except (json.JSONDecodeError, OSError) as error:
            logger.warning("Index load failed (%s), rebuilding empty index", error)
            self._data = {"version": 1, "entries": {}}
            self._save()

    def lookup(self, fingerprint: str) -> Optional[IndexEntry]:
        """Return index entry for fingerprint."""
        row = self._data.get("entries", {}).get(fingerprint)
        if not row:
            return None
        return self._row_to_entry(fingerprint, row)

    def lookup_by_filename_size(
        self, filename: str, size: int
    ) -> Optional[IndexEntry]:
        """Cheap metadata-only lookup: match by (source_filename, source_size).

        Used as a fast pre-filter before computing the SHA fingerprint —
        on a recorder with 100+ known files, this avoids 100+ MB of disk
        reads. A match is only returned when ``source_size > 0`` in the
        stored entry; entries with ``source_size == 0`` are pre-migration
        and treated as unknown (forces full fingerprint, which will then
        rewrite the entry with the correct size).
        """
        if size <= 0:
            return None
        for fp, row in self._data.get("entries", {}).items():
            if row.get("source_filename") != filename:
                continue
            stored = int(row.get("source_size", 0) or 0)
            if stored == 0 or stored != size:
                continue
            return self._row_to_entry(fp, row)
        return None

    @staticmethod
    def _row_to_entry(fingerprint: str, row: Dict[str, Any]) -> IndexEntry:
        return IndexEntry(
            fingerprint=row.get("fingerprint", fingerprint),
            source_filename=row.get("source_filename", ""),
            source_volume=row.get("source_volume", ""),
            markdown_path=row.get("markdown_path", ""),
            versions=list(row.get("versions", [])),
            source_size=int(row.get("source_size", 0) or 0),
        )

    def entry_count(self) -> int:
        """Return number of fingerprint entries currently loaded."""
        return len(self._data.get("entries", {}))

    def recent_entries(self, limit: int = 5) -> list:
        """Return up to *limit* entries, most recently transcribed first.

        Ordered by the latest version's ``transcribed_at`` (ISO strings sort
        chronologically). Used by the menu-bar status panel.
        """
        scored = []
        for fingerprint, row in self._data.get("entries", {}).items():
            latest = ""
            for version in row.get("versions", []) or []:
                ts = version.get("transcribed_at", "") or ""
                if ts > latest:
                    latest = ts
            scored.append((latest, fingerprint, row))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [
            self._row_to_entry(fingerprint, row)
            for _, fingerprint, row in scored[:limit]
        ]

    def add(self, fingerprint: str, entry: IndexEntry) -> None:
        """Add or replace entry in index."""
        with self._locked_reload():
            existing = self._data.setdefault("entries", {}).get(fingerprint, {})
            stored_size = int(existing.get("source_size", 0) or 0)
            size = entry.source_size if entry.source_size > 0 else stored_size
            self._data["entries"][fingerprint] = {
                "fingerprint": entry.fingerprint,
                "source_filename": entry.source_filename,
                "source_volume": entry.source_volume,
                "markdown_path": entry.markdown_path,
                "versions": list(entry.versions),
                "source_size": size,
            }
            self._save()

    def remove(self, fingerprint: str) -> bool:
        """Usuń wpis indeksu.

        Returns:
            True jeśli wpis istniał i został usunięty, False jeśli nie był obecny.
        """
        with self._locked_reload():
            entries = self._data.setdefault("entries", {})
            if fingerprint not in entries:
                return False
            del entries[fingerprint]
            self._save()
            return True

    def add_version(self, fingerprint: str, version_info: Dict[str, Any]) -> None:
        """Append version info to an existing fingerprint."""
        with self._locked_reload():
            entries = self._data.setdefault("entries", {})
            if fingerprint not in entries:
                return
            existing = entries[fingerprint].setdefault("versions", [])
            if version_info not in existing:
                existing.append(version_info)
            ts = version_info.get("transcribed_at")
            if ts:
                entries[fingerprint]["markdown_path"] = version_info.get(
                    "markdown_path", entries[fingerprint].get("markdown_path", "")
                )
            self._save()

    @contextmanager
    def _locked_reload(self):
        self.index_dir.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.lock_path, os.O_CREAT | os.O_RDWR)
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            try:
                if self.index_path.exists():
                    self._data = json.loads(self.index_path.read_text(encoding="utf-8"))
                    self._data.setdefault("entries", {})
            except (json.JSONDecodeError, OSError):
                self._data = {"version": 1, "entries": {}}
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def _save(self) -> None:
        self.index_dir.mkdir(parents=True, exist_ok=True)
        tmp_path = self.index_path.with_suffix(".json.tmp")
        tmp_path.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        os.replace(tmp_path, self.index_path)

    @staticmethod
    def current_iso_timestamp() -> str:
        """Return current timestamp for version metadata."""
        return datetime.now().isoformat(timespec="seconds")


def is_icloud_synced(path: Path) -> bool:
    """Check if path is likely inside iCloud synced container."""
    expanded = path.expanduser().resolve()
    iCloud_root = (Path.home() / "Library" / "Mobile Documents").resolve()
    try:
        expanded.relative_to(iCloud_root)
        return True
    except ValueError:
        return False

