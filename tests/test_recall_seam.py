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
    monkeypatch.setattr(
        seam, "_engine", lambda: _FakeEngine(count=2, result=(["h"], 0.7))
    )
    assert seam.search_safe("q") == (["h"], 0.7)
    monkeypatch.setattr(seam, "_engine", lambda: (_ for _ in ()).throw(RuntimeError()))
    assert seam.search_safe("q") == ([], 0.0)


# --------------------------------------------------------------------------- #
# Singleton init/reset thread-safety.
# --------------------------------------------------------------------------- #


@pytest.fixture(autouse=True)
def _reset_seam_engine():
    """Isolate ALL of seam's module globals between tests — a leaked
    _INDEX_STARTED=True would make bare reset_engine() calls spawn a REAL
    backfill thread over the developer's actual vault."""
    seam._ENGINE = None
    seam._INDEX_STARTED = False
    seam._BACKFILL_ACTIVE = False
    seam._BACKFILL_PENDING = False
    seam._LAST_HEAL_MONO = 0.0
    yield
    seam._ENGINE = None
    seam._INDEX_STARTED = False
    seam._BACKFILL_ACTIVE = False
    seam._BACKFILL_PENDING = False
    seam._LAST_HEAL_MONO = 0.0


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

    monkeypatch.setattr("src.connections.recall.engine.RecallEngine", _SlowEngine)
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


def test_reset_engine_clears_digest_engine_cache(monkeypatch):
    # The digest lane's cached engine would otherwise keep an open handle on a
    # store file the fresh seam engine may have replaced.
    from src.connections import candidate_assembly as ca

    class _Closeable:
        closed = False

        def close(self):
            self.closed = True

    eng = _Closeable()
    monkeypatch.setitem(ca._ENGINE_CACHE, "/some/vault", eng)
    seam.reset_engine()
    assert ca._ENGINE_CACHE == {}
    assert eng.closed is True


def test_reset_engine_restarts_background_index_only_after_launch(monkeypatch):
    # A reset mid-backfill leaves READY over a partial index, and a vault
    # change needs the new vault indexed — reset must restart the background
    # index, but ONLY in a process that actually launched it (never in bare
    # test/CLI resets). It restarts even when NO engine is cached: a failed
    # initial build followed by a settings fix must not stay dead until
    # relaunch.
    calls = {"count": 0}
    monkeypatch.setattr(
        seam,
        "start_background_index",
        lambda: calls.__setitem__("count", calls["count"] + 1),
    )

    class _Eng:
        def close(self):
            pass

    monkeypatch.setattr(seam, "_INDEX_STARTED", False)
    seam._ENGINE = _Eng()
    seam.reset_engine()
    assert calls["count"] == 0  # index never launched -> no restart

    monkeypatch.setattr(seam, "_INDEX_STARTED", True)
    seam._ENGINE = _Eng()
    seam.reset_engine()
    assert calls["count"] == 1  # launched -> reset restarts it

    seam.reset_engine()  # launched + no engine (failed initial build)
    assert calls["count"] == 2  # -> STILL restarts


def test_lexical_only_unknown_is_none():
    # 'Unknown' must stay distinguishable from 'dense': a False here would
    # foreclose the presenter's channel inference and misapply the 0.60 floor.
    seam._ENGINE = None
    assert seam.lexical_only() is None

    class _Eng:
        lexical_only = True

    seam._ENGINE = _Eng()
    assert seam.lexical_only() is True


def test_start_background_index_single_flight(monkeypatch):
    # N rapid requests must not stack N threads: while a pass runs, later
    # calls coalesce into exactly ONE more pass with the current engine.
    import threading as th

    gate = th.Event()
    passes = {"count": 0}

    def _fake_backfill(engine, state, incremental=True):
        passes["count"] += 1
        gate.wait(timeout=5)

    monkeypatch.setattr(seam, "run_backfill", _fake_backfill)
    monkeypatch.setattr(seam, "_engine", lambda: object())

    seam.start_background_index()  # pass 1 starts and blocks on the gate
    for _ in range(20):
        if passes["count"] == 1:
            break
        import time

        time.sleep(0.05)
    assert passes["count"] == 1

    seam.start_background_index()  # coalesces
    seam.start_background_index()  # coalesces into the SAME single pending pass
    assert seam._BACKFILL_PENDING is True

    gate.set()
    for _ in range(40):
        if not seam._BACKFILL_ACTIVE:
            break
        import time

        time.sleep(0.05)
    assert passes["count"] == 2  # 1 initial + 1 coalesced, never 3
    assert seam._BACKFILL_ACTIVE is False


def test_search_detailed_heals_corrupt_store(monkeypatch):
    # Query-time corruption (iCloud rewrote pages) must trigger a rebuild and
    # a backfill restart — not a permanent 'unavailable'.
    import sqlite3

    calls = {"rebuild": 0, "restart": 0}

    class _CorruptEngine:
        def count(self):
            return 5

        def search_scored(self, query, k=8):
            raise sqlite3.DatabaseError("database disk image is malformed")

        def rebuild_store(self):
            calls["rebuild"] += 1

    eng = _CorruptEngine()
    # Identity matters: heal only fires when the failing engine IS the
    # published one — a closed predecessor's error must not wipe a fresh store.
    monkeypatch.setattr(seam, "_engine", lambda: eng)
    seam._ENGINE = eng
    monkeypatch.setattr(
        seam,
        "start_background_index",
        lambda: calls.__setitem__("restart", calls["restart"] + 1),
    )

    assert seam.search_detailed("pytanie") == ([], 0.0, "unavailable")
    assert calls["rebuild"] == 1
    assert calls["restart"] == 1

    # Second corruption within the cooldown window: no second wipe.
    assert seam.search_detailed("pytanie") == ([], 0.0, "unavailable")
    assert calls["rebuild"] == 1


def test_heal_skips_stale_engine(monkeypatch):
    # The failure belongs to a closed predecessor — the fresh engine's healthy
    # store must survive.
    import sqlite3

    calls = {"rebuild": 0}

    class _Eng:
        def rebuild_store(self):
            calls["rebuild"] += 1

    stale, current = _Eng(), _Eng()
    seam._ENGINE = current
    exc = sqlite3.DatabaseError("database disk image is malformed")
    assert seam._heal_if_corrupt(exc, stale) is False
    assert seam._heal_if_corrupt(exc, None) is False
    assert calls["rebuild"] == 0


def test_heal_ignores_transient_and_closed_store_errors(monkeypatch):
    # OperationalError (locked/busy) is transient, and ProgrammingError is a
    # reset closing the store under an in-flight op — wiping the index on
    # either would destroy healthy data.
    import sqlite3

    calls = {"rebuild": 0}

    class _Eng:
        def rebuild_store(self):
            calls["rebuild"] += 1

    eng = _Eng()
    seam._ENGINE = eng
    assert (
        seam._heal_if_corrupt(sqlite3.OperationalError("database is locked"), eng)
        is False
    )
    assert (
        seam._heal_if_corrupt(
            sqlite3.ProgrammingError("Cannot operate on a closed database"), eng
        )
        is False
    )
    assert seam._heal_if_corrupt(RuntimeError("boom"), eng) is False
    assert calls["rebuild"] == 0
