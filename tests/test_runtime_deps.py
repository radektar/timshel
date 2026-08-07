"""Tests for runtime dependency safeguards."""

from __future__ import annotations

import builtins
from unittest.mock import MagicMock

from src import runtime_deps

# A sibling of the runtime deps dir sharing its name as a string prefix —
# a plain startswith() check would wrongly claim it as ours.
RUNTIME_DEPS_SIBLING = runtime_deps.RUNTIME_DEPS_DIR.with_name(
    runtime_deps.RUNTIME_DEPS_DIR.name + "-backup"
)


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


def _drift_probe(monkeypatch, origin: str, installed: str):
    """Arrange an already-imported sqlite_vec at `origin` reporting `installed`."""
    module = MagicMock()
    module.__file__ = origin
    monkeypatch.setitem(runtime_deps.sys.modules, "sqlite_vec", module)
    monkeypatch.setattr(builtins, "__import__", lambda name, *a, **k: MagicMock())
    monkeypatch.setattr(
        runtime_deps._importlib_metadata, "version", lambda _dist: installed
    )
    pip_calls = []
    monkeypatch.setattr(
        runtime_deps, "_pip_install", lambda spec, _t: pip_calls.append(spec) or True
    )
    warnings = []
    monkeypatch.setattr(
        runtime_deps.logger,
        "warning",
        lambda msg, *a: warnings.append(msg % a if a else msg),
    )
    return pip_calls, warnings


def test_drifted_runtime_dir_install_warns_and_never_reinstalls(monkeypatch):
    """Drift is reported, NOT repaired in place: pip-ing over a live import
    swaps the native extension under the running wrapper."""
    pip_calls, warnings = _drift_probe(
        monkeypatch,
        str(runtime_deps.RUNTIME_DEPS_DIR / "sqlite_vec" / "__init__.py"),
        "0.1.6",
    )

    assert runtime_deps.ensure_importable("sqlite_vec") is True
    assert pip_calls == []
    assert any("0.1.6" in w and "0.1.9" in w for w in warnings)


def test_drift_check_ignores_installs_outside_runtime_dir(monkeypatch):
    """A dev venv copy is not ours to manage — no warning, no pip."""
    pip_calls, warnings = _drift_probe(
        monkeypatch, "/some/venv/site-packages/sqlite_vec/__init__.py", "0.1.6"
    )

    assert runtime_deps.ensure_importable("sqlite_vec") is True
    assert pip_calls == [] and warnings == []


def test_drift_check_ignores_sibling_directory_prefix(monkeypatch):
    """`python-deps-backup/` is a sibling, not a child, of the runtime dir."""
    sibling = str(RUNTIME_DEPS_SIBLING / "sqlite_vec" / "__init__.py")
    pip_calls, warnings = _drift_probe(monkeypatch, sibling, "0.1.6")

    assert runtime_deps.ensure_importable("sqlite_vec") is True
    assert pip_calls == [] and warnings == []


def test_no_warning_when_pin_matches(monkeypatch):
    """A runtime-dir install already at the pinned version is silent."""
    pip_calls, warnings = _drift_probe(
        monkeypatch,
        str(runtime_deps.RUNTIME_DEPS_DIR / "sqlite_vec" / "__init__.py"),
        "0.1.9",
    )

    assert runtime_deps.ensure_importable("sqlite_vec") is True
    assert pip_calls == [] and warnings == []


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
