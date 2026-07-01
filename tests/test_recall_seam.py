"""The transcription/search seam: best-effort, never raises into the caller."""

from __future__ import annotations

from src.connections.recall import seam


def test_search_safe_degrades_to_empty_on_engine_failure(monkeypatch):
    def boom():
        raise RuntimeError("no index / model not downloaded")

    monkeypatch.setattr(seam, "_engine", boom)
    assert seam.search_safe("cokolwiek") == ([], 0.0)


def test_search_safe_returns_engine_result(monkeypatch):
    class FakeEngine:
        def search_scored(self, query, k=8):
            return (["hit"], 0.83)

    monkeypatch.setattr(seam, "_engine", lambda: FakeEngine())
    results, conf = seam.search_safe("pytanie", k=5)
    assert results == ["hit"] and conf == 0.83
