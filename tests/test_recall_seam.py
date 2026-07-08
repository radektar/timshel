"""The transcription/search seam: best-effort, never raises; honest status."""

from __future__ import annotations

import pytest

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


# --------------------------------------------------------------------------- #
# Singleton init/reset thread-safety.
# --------------------------------------------------------------------------- #


@pytest.fixture(autouse=True)
def _reset_seam_engine():
    """Isolate the module-global engine between tests."""
    seam._ENGINE = None
    yield
    seam._ENGINE = None


def test_engine_singleton_concurrent_init(monkeypatch):
    """8 threads racing into a SLOW engine construction must build exactly one
    engine — the pre-lock code built one per racing thread (two embedding
    models in RAM, two writers on the same index)."""
    import threading
    import time

    built = {"count": 0}

    class _SlowEngine:
        def __init__(self, _root):
            time.sleep(0.05)  # model load / download window
            built["count"] += 1

        def close(self):
            pass

    monkeypatch.setattr(
        "src.connections.recall.engine.RecallEngine", _SlowEngine
    )
    # get_config() stays real — the fake engine ignores the root path.

    results = []
    barrier = threading.Barrier(8)

    def hit():
        barrier.wait(timeout=5)
        results.append(seam._engine())

    threads = [threading.Thread(target=hit) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)

    assert built["count"] == 1
    assert len(set(map(id, results))) == 1  # everyone got the same object


def test_reset_engine_closes_once():
    """reset_engine closes the cached engine exactly once and clears it."""
    closes = {"count": 0}

    class _Eng:
        def close(self):
            closes["count"] += 1

    seam._ENGINE = _Eng()
    seam.reset_engine()
    seam.reset_engine()  # second call: nothing cached, no double close

    assert closes["count"] == 1
    assert seam._ENGINE is None
