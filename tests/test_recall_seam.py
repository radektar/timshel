"""The transcription/search seam: best-effort, never raises; honest status."""

from __future__ import annotations

from src.connections.recall import seam


class _FakeEngine:
    def __init__(self, count=3, result=(["hit"], 0.83)):
        self._count = count
        self._result = result

    def count(self):
        return self._count

    def search_scored(self, query, k=8):
        return self._result


def test_search_detailed_ok_when_index_has_content(monkeypatch):
    monkeypatch.setattr(seam, "_engine", lambda: _FakeEngine(count=3))
    assert seam.search_detailed("pytanie", k=5) == (["hit"], 0.83, "ok")


def test_search_detailed_empty_index_is_not_a_no_match(monkeypatch):
    # An unindexed vault must NOT look like a genuine "nothing found".
    monkeypatch.setattr(seam, "_engine", lambda: _FakeEngine(count=0))
    assert seam.search_detailed("pytanie") == ([], 0.0, "empty")


def test_search_detailed_unavailable_on_engine_failure(monkeypatch):
    def boom():
        raise RuntimeError("model not downloaded")

    monkeypatch.setattr(seam, "_engine", boom)
    assert seam.search_detailed("pytanie") == ([], 0.0, "unavailable")


def test_search_detailed_unavailable_when_search_raises(monkeypatch):
    class _Boom(_FakeEngine):
        def search_scored(self, query, k=8):
            raise RuntimeError("index corrupt")

    monkeypatch.setattr(seam, "_engine", lambda: _Boom(count=5))
    assert seam.search_detailed("pytanie") == ([], 0.0, "unavailable")


def test_search_safe_is_the_two_tuple_wrapper(monkeypatch):
    monkeypatch.setattr(seam, "_engine", lambda: _FakeEngine(count=2, result=(["h"], 0.7)))
    assert seam.search_safe("q") == (["h"], 0.7)
    monkeypatch.setattr(seam, "_engine", lambda: (_ for _ in ()).throw(RuntimeError()))
    assert seam.search_safe("q") == ([], 0.0)
