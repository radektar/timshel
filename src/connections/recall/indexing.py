"""Background indexing status + runner for the recall lens (Faza 5).

Turns recall from "works only after a manual backfill" into "just works": on launch a
daemon thread catches the index up to the vault (incremental — only new/changed notes
are embedded), and a thread-safe :class:`IndexingState` lets the menu status chip and
the window's partial banner reflect Standby / Indexing / Ready / Error honestly, without
blocking anything. Headless and dependency-light — the AppKit surfaces just read it.
"""

from __future__ import annotations

import threading
from typing import Optional

from src.logger import logger

STANDBY = "standby"
INDEXING = "indexing"
READY = "ready"
ERROR = "error"


class IndexingState:
    """Thread-safe snapshot of the recall index build (written by the worker thread,
    read by the AppKit main thread)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state = STANDBY
        self._done = 0
        self._total = 0
        self._error = ""

    def begin(self) -> None:
        with self._lock:
            self._state = INDEXING
            self._done = 0
            self._total = 0
            self._error = ""

    def progress(self, done: int, total: int) -> None:
        with self._lock:
            self._state = INDEXING
            self._done = int(done)
            self._total = int(total)

    def ready(self) -> None:
        with self._lock:
            self._state = READY

    def failed(self, error) -> None:
        with self._lock:
            self._state = ERROR
            self._error = str(error)

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "state": self._state,
                "done": self._done,
                "total": self._total,
                "error": self._error,
            }

    def is_indexing(self) -> bool:
        with self._lock:
            return self._state == INDEXING

    def label(self) -> str:
        """A short human status for the menu chip."""
        s = self.snapshot()
        if s["state"] == INDEXING:
            return f"Indeksuję… {s['done']}/{s['total']}" if s["total"] else "Indeksuję…"
        if s["state"] == READY:
            return "Recall: gotowe"
        if s["state"] == ERROR:
            return "Recall: błąd indeksu"
        return "Recall: standby"


def run_backfill(engine, state: IndexingState, *, incremental: bool = True) -> Optional[int]:
    """Catch the index up to the vault, updating ``state``. Best-effort — never raises.

    Returns the number of notes (re)indexed, or ``None`` on failure. Safe to run on a
    daemon thread: the engine's store is thread-safe and indexing swallows per-note errors.
    """
    state.begin()
    try:
        n = engine.backfill(
            incremental=incremental,
            progress=lambda done, total, _path: state.progress(done, total),
        )
        state.ready()
        return n
    except Exception as exc:  # noqa: BLE001
        logger.warning("recall background index failed: %s", exc)
        state.failed(exc)
        return None
