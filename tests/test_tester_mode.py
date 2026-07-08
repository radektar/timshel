"""Tester-build flag: settings round-trip + first-launch bundle adoption."""

from __future__ import annotations

import json
from pathlib import Path

import src.bootstrap as bootstrap
from src.config.settings import UserSettings


def test_tester_mode_round_trips(tmp_path, monkeypatch):
    """tester_mode persists through save/load like any other setting."""
    config_file = tmp_path / "config.json"
    monkeypatch.setattr(
        UserSettings, "config_path", staticmethod(lambda: config_file)
    )

    UserSettings(tester_mode=True).save()
    assert UserSettings.load().tester_mode is True

    UserSettings(tester_mode=False).save()
    assert UserSettings.load().tester_mode is False


def test_tester_mode_defaults_off():
    assert UserSettings().tester_mode is False
    assert UserSettings().to_dict()["tester_mode"] is False


def _patch_config_path(monkeypatch, tmp_path):
    config_file = tmp_path / "config.json"
    monkeypatch.setattr(
        UserSettings, "config_path", staticmethod(lambda: config_file)
    )
    return config_file


def test_adopt_enables_on_tester_bundle_first_launch(tmp_path, monkeypatch):
    """A tester bundle with no persisted tester_mode turns it on once."""
    _patch_config_path(monkeypatch, tmp_path)
    monkeypatch.setattr(bootstrap, "_bundle_tester_flag", lambda: True)

    settings = UserSettings()  # fresh, no tester_mode written yet
    changed = bootstrap._adopt_tester_build_flag(settings, already_configured=False)

    assert changed is True
    assert settings.tester_mode is True
    # Persisted so the next launch's fast path sees it.
    assert UserSettings.load().tester_mode is True


def test_adopt_noop_on_non_tester_bundle(tmp_path, monkeypatch):
    """A normal build never flips the flag."""
    _patch_config_path(monkeypatch, tmp_path)
    monkeypatch.setattr(bootstrap, "_bundle_tester_flag", lambda: False)

    settings = UserSettings()
    assert bootstrap._adopt_tester_build_flag(settings, already_configured=False) is False
    assert settings.tester_mode is False


def test_adopt_respects_explicit_user_choice(tmp_path, monkeypatch):
    """When tester_mode was already persisted, the bundle flag is ignored.

    A tester who deliberately turns instrumentation off must stay off even on a
    tester DMG.
    """
    _patch_config_path(monkeypatch, tmp_path)
    monkeypatch.setattr(bootstrap, "_bundle_tester_flag", lambda: True)

    settings = UserSettings(tester_mode=False)
    assert (
        bootstrap._adopt_tester_build_flag(settings, already_configured=True) is False
    )
    assert settings.tester_mode is False


def test_ensure_ready_enables_tester_mode_on_fresh_tester_build(tmp_path, monkeypatch):
    """Integration: a fresh tester build (no config yet) ends up tester_mode=True.

    Regression for the save()-before-adopt trap: to_dict always writes the key,
    so the full ensure_ready path must capture key-presence BEFORE its save().
    """
    from pathlib import Path

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(bootstrap, "_bundle_tester_flag", lambda: True)
    monkeypatch.setattr(bootstrap, "ensure_importable", lambda *_a, **_k: None)

    settings = bootstrap.ensure_ready()
    assert settings.tester_mode is True

    # And it sticks on the next (fast-path) launch.
    assert bootstrap.ensure_ready().tester_mode is True
