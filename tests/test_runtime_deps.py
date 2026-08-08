"""Tests for runtime dependency safeguards."""

from __future__ import annotations

import builtins
from contextlib import contextmanager
from unittest.mock import MagicMock

from src import runtime_deps


def test_ensure_importable_already_available(monkeypatch):
    """Should return True and skip pip when import already works."""
    import_calls = []

    def fake_import(name, *args, **kwargs):
        import_calls.append(name)
        return MagicMock()

    pip_called = {"value": False}

    def fake_pip_install(_spec, _target):
        pip_called["value"] = True
        return True

    monkeypatch.setattr(builtins, "__import__", fake_import)
    monkeypatch.setattr(runtime_deps, "_pip_install", fake_pip_install)

    assert runtime_deps.ensure_importable("anthropic") is True
    assert pip_called["value"] is False
    assert "anthropic" in import_calls


def test_ensure_importable_installs_then_imports(monkeypatch):
    """Should install once and return True when retry import succeeds."""
    state = {"attempt": 0}

    def fake_import(name, *args, **kwargs):
        if name == "anthropic":
            state["attempt"] += 1
            if state["attempt"] == 1:
                raise ImportError("missing anthropic")
        return MagicMock()

    monkeypatch.setattr(builtins, "__import__", fake_import)
    monkeypatch.setattr(runtime_deps, "_pip_install", lambda _spec, _target: True)

    assert runtime_deps.ensure_importable("anthropic") is True
    assert state["attempt"] == 2


def test_ensure_importable_returns_false_when_pip_fails(monkeypatch):
    """Should return False when installation fails."""

    def fake_import(name, *args, **kwargs):
        if name == "anthropic":
            raise ImportError("missing anthropic")
        return MagicMock()

    monkeypatch.setattr(builtins, "__import__", fake_import)
    monkeypatch.setattr(runtime_deps, "_pip_install", lambda _spec, _target: False)

    assert runtime_deps.ensure_importable("anthropic") is False


@contextmanager
def _drift_probe(monkeypatch, runtime_dir_versions):
    """Arrange the runtime dir to report `runtime_dir_versions` for sqlite-vec.

    A context manager on purpose: patching ``builtins.__import__`` for the
    whole test means pytest is still running under the fake importer when it
    builds a failure report, which turns any red assertion into an
    INTERNALERROR that aborts the entire session. Undoing the patch before
    the assertions keeps a failure readable.
    """
    pip_calls: list = []
    warnings: list = []
    with monkeypatch.context() as patch:
        patch.setattr(
            runtime_deps,
            "_runtime_dir_versions",
            lambda _dist: list(runtime_dir_versions),
        )
        patch.setattr(builtins, "__import__", lambda name, *a, **k: MagicMock())
        patch.setattr(runtime_deps, "_DRIFT_WARNED", set())
        patch.setattr(
            runtime_deps,
            "_pip_install",
            lambda spec, _t: pip_calls.append(spec) or True,
        )
        patch.setattr(
            runtime_deps.logger,
            "warning",
            lambda msg, *a: warnings.append(msg % a if a else msg),
        )
        yield pip_calls, warnings


def test_drift_is_reported_once_and_never_self_repaired(monkeypatch):
    """No pip: repairing in place is unsound (native-extension skew) and
    repairing before import never clears (pip --target leaves the old
    .dist-info), so it would re-run on every launch."""
    with _drift_probe(monkeypatch, ["0.1.6"]) as (pip_calls, warnings):
        first = runtime_deps.ensure_importable("sqlite_vec")
        second = runtime_deps.ensure_importable("sqlite_vec")

    assert first is True and second is True
    assert pip_calls == []
    assert len(warnings) == 1
    assert "0.1.6" in warnings[0] and "0.1.9" in warnings[0]
    assert str(runtime_deps.RUNTIME_DEPS_DIR) in warnings[0]


def test_superseded_dist_info_alongside_the_pin_is_not_a_drift(monkeypatch):
    """`pip --target --upgrade` leaves the old .dist-info behind; as long as
    the pinned version is present the install is fine."""
    with _drift_probe(monkeypatch, ["0.1.6", "0.1.9"]) as (pip_calls, warnings):
        result = runtime_deps.ensure_importable("sqlite_vec")

    assert result is True
    assert pip_calls == [] and warnings == []


def test_no_action_when_dep_is_not_in_the_runtime_dir(monkeypatch):
    """A dev venv or bundle copy is not ours to manage."""
    with _drift_probe(monkeypatch, []) as (pip_calls, warnings):
        result = runtime_deps.ensure_importable("sqlite_vec")

    assert result is True
    assert pip_calls == [] and warnings == []


def test_no_action_when_pin_matches(monkeypatch):
    """A runtime-dir install already at the pinned version is silent."""
    with _drift_probe(monkeypatch, ["0.1.9"]) as (pip_calls, warnings):
        result = runtime_deps.ensure_importable("sqlite_vec")

    assert result is True
    assert pip_calls == [] and warnings == []


def test_damaged_dist_info_never_breaks_the_probe(monkeypatch, tmp_path):
    """One interrupted install must not take down ensure_importable — this
    runs on the startup path, where callers treat it as best-effort."""
    monkeypatch.setattr(runtime_deps, "RUNTIME_DEPS_DIR", tmp_path)

    garbled = tmp_path / "broken-0.1.6.dist-info"
    garbled.mkdir()
    (garbled / "METADATA").write_bytes(b"\x80\x81not utf-8")
    headerless = tmp_path / "sqlite_vec-0.1.9.dist-info"
    headerless.mkdir()
    (headerless / "METADATA").write_text("Metadata-Version: 2.1\nName: sqlite-vec\n")

    # No exception, and the version-less entry is dropped rather than
    # returned as None (which would blow up formatting the warning).
    assert runtime_deps._runtime_dir_versions("sqlite-vec") == []


def test_runtime_dir_versions_are_scoped_and_collect_every_dist_info(
    monkeypatch, tmp_path
):
    """The probe reads only the runtime dir — and sees ALL its dist-infos."""
    monkeypatch.setattr(runtime_deps, "RUNTIME_DEPS_DIR", tmp_path)
    assert runtime_deps._runtime_dir_versions("sqlite-vec") == []

    for version in ("0.1.6", "0.1.9"):
        dist_info = tmp_path / f"sqlite_vec-{version}.dist-info"
        dist_info.mkdir()
        (dist_info / "METADATA").write_text(
            f"Metadata-Version: 2.1\nName: sqlite-vec\nVersion: {version}\n"
        )
    assert sorted(runtime_deps._runtime_dir_versions("sqlite-vec")) == [
        "0.1.6",
        "0.1.9",
    ]


def test_runtime_dir_added_to_sys_path_once(monkeypatch):
    """Runtime path should not be duplicated in sys.path."""
    original = list(runtime_deps.sys.path)
    try:
        runtime_str = str(runtime_deps.RUNTIME_DEPS_DIR)
        monkeypatch.setattr(
            runtime_deps.sys,
            "path",
            [p for p in runtime_deps.sys.path if p != runtime_str],
        )
        runtime_deps._ensure_runtime_dir_on_path()
        runtime_deps._ensure_runtime_dir_on_path()
        assert runtime_deps.sys.path.count(runtime_str) == 1
    finally:
        runtime_deps.sys.path[:] = original
