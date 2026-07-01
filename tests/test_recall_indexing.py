"""Background indexing status + runner (Faza 5) — headless, no model."""

from __future__ import annotations

from src.connections.recall.indexing import (
    ERROR, INDEXING, READY, STANDBY, IndexingState, run_backfill,
)


class _FakeEngine:
    def __init__(self, notes=3, boom=False):
        self.notes = notes
        self.boom = boom

    def backfill(self, *, incremental, progress):
        assert incremental is True
        if self.boom:
            raise RuntimeError("index blew up")
        for i in range(1, self.notes + 1):
            progress(i, self.notes, f"note-{i}")
        return self.notes


def test_run_backfill_reports_progress_then_ready():
    st = IndexingState()
    assert run_backfill(_FakeEngine(3), st) == 3
    snap = st.snapshot()
    assert snap["state"] == READY and snap["done"] == 3 and snap["total"] == 3


def test_run_backfill_failure_sets_error_and_never_raises():
    st = IndexingState()
    assert run_backfill(_FakeEngine(boom=True), st) is None  # swallowed
    assert st.snapshot()["state"] == ERROR and st.snapshot()["error"]


def test_state_starts_standby_and_labels_each_phase():
    st = IndexingState()
    assert st.snapshot()["state"] == STANDBY
    assert "standby" in st.label().lower()
    st.progress(2, 10)
    assert st.is_indexing() and "2/10" in st.label()
    st.ready()
    assert "gotowe" in st.label().lower() and not st.is_indexing()
    st.failed("boom")
    assert "błąd" in st.label().lower()
