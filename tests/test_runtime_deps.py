"""Tests for runtime dependency safeguards."""

from __future__ import annotations

import builtins
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


def _drift_probe(monkeypatch, runtime_dir_version, *, already_loaded=False):
    """Arrange a runtime-dir install at `runtime_dir_version` (None = absent)."""
    monkeypatch.setattr(
        runtime_deps, "_runtime_dir_version", lambda _dist: runtime_dir_version
    )
    monkeypatch.setattr(builtins, "__import__", lambda name, *a, **k: MagicMock())
    if already_loaded:
        monkeypatch.setitem(runtime_deps.sys.modules, "sqlite_vec", MagicMock())
    else:
        monkeypatch.delitem(runtime_deps.sys.modules, "sqlite_vec", raising=False)
    monkeypatch.setattr(runtime_deps, "_DRIFT_WARNED", set())
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


def test_drifted_install_is_repinned_before_import(monkeypatch):
    """A pre-pin auto-install is repaired while nothing of it is loaded."""
    pip_calls, warnings = _drift_probe(monkeypatch, "0.1.6")

    assert runtime_deps.ensure_importable("sqlite_vec") is True
    assert pip_calls == [runtime_deps.SAFEGUARDED_PACKAGES["sqlite_vec"]]
    assert warnings == []


def test_loaded_module_is_never_repinned_in_place(monkeypatch):
    """Once imported, pip would swap the native extension under the live
    wrapper — so the drift is only reported, once."""
    pip_calls, warnings = _drift_probe(monkeypatch, "0.1.6", already_loaded=True)

    assert runtime_deps.ensure_importable("sqlite_vec") is True
    assert runtime_deps.ensure_importable("sqlite_vec") is True
    assert pip_calls == []
    assert len(warnings) == 1 and "0.1.6" in warnings[0] and "0.1.9" in warnings[0]


def test_no_action_when_dep_is_not_in_the_runtime_dir(monkeypatch):
    """A dev venv or bundle copy is not ours to manage."""
    pip_calls, warnings = _drift_probe(monkeypatch, None)

    assert runtime_deps.ensure_importable("sqlite_vec") is True
    assert pip_calls == [] and warnings == []


def test_no_action_when_pin_matches(monkeypatch):
    """A runtime-dir install already at the pinned version is silent."""
    pip_calls, warnings = _drift_probe(monkeypatch, "0.1.9")

    assert runtime_deps.ensure_importable("sqlite_vec") is True
    assert pip_calls == [] and warnings == []


def test_runtime_dir_version_ignores_other_paths(monkeypatch, tmp_path):
    """The version probe is scoped to the runtime dir, not the whole path."""
    monkeypatch.setattr(runtime_deps, "RUNTIME_DEPS_DIR", tmp_path)
    assert runtime_deps._runtime_dir_version("sqlite-vec") is None

    dist_info = tmp_path / "sqlite_vec-0.1.6.dist-info"
    dist_info.mkdir()
    (dist_info / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: sqlite-vec\nVersion: 0.1.6\n"
    )
    assert runtime_deps._runtime_dir_version("sqlite-vec") == "0.1.6"


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
