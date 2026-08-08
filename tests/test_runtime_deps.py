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


def _drift_probe(monkeypatch, runtime_dir_versions):
    """Arrange the runtime dir to report `runtime_dir_versions` for sqlite-vec."""
    monkeypatch.setattr(
        runtime_deps, "_runtime_dir_versions", lambda _dist: list(runtime_dir_versions)
    )
    monkeypatch.setattr(builtins, "__import__", lambda name, *a, **k: MagicMock())
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


def test_drift_is_reported_once_and_never_self_repaired(monkeypatch):
    """No pip: repairing in place is unsound (native-extension skew) and
    repairing before import never clears (pip --target leaves the old
    .dist-info), so it would re-run on every launch."""
    pip_calls, warnings = _drift_probe(monkeypatch, ["0.1.6"])

    assert runtime_deps.ensure_importable("sqlite_vec") is True
    assert runtime_deps.ensure_importable("sqlite_vec") is True
    assert pip_calls == []
    assert len(warnings) == 1
    assert "0.1.6" in warnings[0] and "0.1.9" in warnings[0]
    assert str(runtime_deps.RUNTIME_DEPS_DIR) in warnings[0]


def test_superseded_dist_info_alongside_the_pin_is_not_a_drift(monkeypatch):
    """`pip --target --upgrade` leaves the old .dist-info behind; as long as
    the pinned version is present the install is fine."""
    pip_calls, warnings = _drift_probe(monkeypatch, ["0.1.6", "0.1.9"])

    assert runtime_deps.ensure_importable("sqlite_vec") is True
    assert pip_calls == [] and warnings == []


def test_no_action_when_dep_is_not_in_the_runtime_dir(monkeypatch):
    """A dev venv or bundle copy is not ours to manage."""
    pip_calls, warnings = _drift_probe(monkeypatch, [])

    assert runtime_deps.ensure_importable("sqlite_vec") is True
    assert pip_calls == [] and warnings == []


def test_no_action_when_pin_matches(monkeypatch):
    """A runtime-dir install already at the pinned version is silent."""
    pip_calls, warnings = _drift_probe(monkeypatch, ["0.1.9"])

    assert runtime_deps.ensure_importable("sqlite_vec") is True
    assert pip_calls == [] and warnings == []


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
