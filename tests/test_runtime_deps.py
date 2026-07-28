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
