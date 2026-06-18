"""Tests for the shared volume detection utilities.

These tests cover the strict UUID-based whitelist introduced in
v2.0.0-beta.2. Wcześniej tryb ``auto`` akceptował dowolny volume z plikami
audio, co prowadziło do niezamierzonego skanowania (np. dysku z muzyką).
``has_audio_files`` jest zachowane jako utility, ale nie ma już ścieżki
``watch_mode == "auto"``.
"""

from pathlib import Path
from unittest.mock import patch

import pytest

from src.config.settings import UserSettings
from src.volume_utils import (
    find_matching_volumes,
    has_audio_files,
    should_process_volume,
)


def _make_volume(root: Path, name: str, audio_file: str | None = "rec.mp3") -> Path:
    """Create a fake volume and optionally seed it with an audio file."""
    volume = root / name
    volume.mkdir()
    if audio_file:
        (volume / audio_file).touch()
    else:
        (volume / "notes.txt").touch()
    return volume


def _stub_uuid(uuid: str):
    """Patch get_volume_uuid w module volume_utils."""
    return patch("src.volume_utils.get_volume_uuid", return_value=uuid)


def test_has_audio_files_detects_top_level(tmp_path):
    """A single audio file directly under the volume must be detected."""
    (tmp_path / "memo.wav").touch()
    assert has_audio_files(tmp_path) is True


def test_has_audio_files_detects_within_subdirectory(tmp_path):
    """Audio inside a nested folder (within max_depth) must be detected."""
    nested = tmp_path / "A" / "B"
    nested.mkdir(parents=True)
    (nested / "track.mp3").touch()
    assert has_audio_files(tmp_path) is True


def test_has_audio_files_ignores_non_audio(tmp_path):
    """Volumes with only non-audio files must return False."""
    (tmp_path / "readme.txt").touch()
    assert has_audio_files(tmp_path) is False


def test_has_audio_files_respects_max_depth(tmp_path):
    """Files beyond max_depth must not trigger detection."""
    deep = tmp_path / "a" / "b" / "c" / "d"
    deep.mkdir(parents=True)
    (deep / "far.mp3").touch()
    assert has_audio_files(tmp_path, max_depth=1) is False


def test_should_process_volume_rejects_system_volume(tmp_path):
    """System volumes like 'Macintosh HD' must always be rejected."""
    volume = _make_volume(tmp_path, "Macintosh HD")
    settings = UserSettings(watch_mode="manual", watched_volumes=[])
    with _stub_uuid("UUID-MAC"):
        assert should_process_volume(volume, settings) is False


def test_should_process_volume_manual_blank_rejects_unknown(tmp_path):
    """Manual mode bez wpisu w whitelist musi odmówić (czeka na dialog)."""
    volume = _make_volume(tmp_path, "Foo")
    settings = UserSettings(watch_mode="manual", watched_volumes=[])
    with _stub_uuid("UUID-FOO"):
        assert should_process_volume(volume, settings) is False


def test_should_process_volume_uuid_trusted_accepted(tmp_path):
    """Wpisany w whitelist (decision=trusted) volume jest akceptowany."""
    volume = _make_volume(tmp_path, "LS-P1")
    settings = UserSettings(watch_mode="manual", watched_volumes=[])
    settings.add_trusted_volume("UUID-LS", "LS-P1", "trusted")
    with _stub_uuid("UUID-LS"):
        assert should_process_volume(volume, settings) is True


def test_should_process_volume_uuid_blocked_rejected(tmp_path):
    """Wpisany w whitelist (decision=blocked) volume jest pomijany."""
    volume = _make_volume(tmp_path, "Music SSD")
    settings = UserSettings(watch_mode="manual", watched_volumes=[])
    settings.add_trusted_volume("UUID-MUSIC", "Music SSD", "blocked")
    with _stub_uuid("UUID-MUSIC"):
        assert should_process_volume(volume, settings) is False


def test_should_process_volume_once_approved_accepted(tmp_path):
    """A disk approved 'Once' is processed (the gate AND the worker agree)."""
    from src import volume_session

    volume = _make_volume(tmp_path, "SD_CARD")
    settings = UserSettings(watch_mode="manual", watched_volumes=[])
    volume_session.approve_once("UUID-SD")
    with _stub_uuid("UUID-SD"):
        assert should_process_volume(volume, settings) is True


def test_should_process_volume_blocked_overrides_once(tmp_path):
    """A persisted 'blocked' decision wins over a stale 'Once' approval."""
    from src import volume_session

    volume = _make_volume(tmp_path, "SD_CARD")
    settings = UserSettings(watch_mode="manual", watched_volumes=[])
    settings.add_trusted_volume("UUID-SD", "SD_CARD", "blocked")
    volume_session.approve_once("UUID-SD")
    with _stub_uuid("UUID-SD"):
        assert should_process_volume(volume, settings) is False


def test_find_matching_volumes_includes_once_approved(tmp_path):
    """find_recorders (via find_matching_volumes) picks up an 'Once' disk."""
    from src import volume_session

    _make_volume(tmp_path, "SD_CARD")
    settings = UserSettings(watch_mode="manual", watched_volumes=[])
    volume_session.approve_once("UUID-SD")
    with patch("src.volume_utils.get_volume_uuid", return_value="UUID-SD"):
        result = find_matching_volumes(settings, volumes_root=tmp_path)
    assert [p.name for p in result] == ["SD_CARD"]


def test_should_process_volume_specific_mode_by_name(tmp_path):
    """Specific mode legacy: akceptuje po nazwie z watched_volumes."""
    volume_ok = _make_volume(tmp_path, "LS-P1")
    volume_other = _make_volume(tmp_path, "RANDOM")
    settings = UserSettings(watch_mode="specific", watched_volumes=["LS-P1"])

    with _stub_uuid("UUID-1"):
        assert should_process_volume(volume_ok, settings) is True
    with _stub_uuid("UUID-2"):
        assert should_process_volume(volume_other, settings) is False


def test_should_process_volume_blocked_uuid_overrides_specific_name(tmp_path):
    """UUID-blocked ma pierwszeństwo nad name-based specific."""
    volume = _make_volume(tmp_path, "LS-P1")
    settings = UserSettings(watch_mode="specific", watched_volumes=["LS-P1"])
    settings.add_trusted_volume("UUID-LS", "LS-P1", "blocked")
    with _stub_uuid("UUID-LS"):
        assert should_process_volume(volume, settings) is False


def test_find_matching_volumes_returns_only_trusted(tmp_path):
    """Manual mode + jeden trusted volume → tylko on jest matching."""
    _make_volume(tmp_path, "LS-P1")
    _make_volume(tmp_path, "Music SSD")
    _make_volume(tmp_path, "Macintosh HD")

    settings = UserSettings(watch_mode="manual", watched_volumes=[])
    settings.add_trusted_volume("UUID-LS", "LS-P1", "trusted")

    def _uuid_lookup(volume_path: Path) -> str:
        return {
            "LS-P1": "UUID-LS",
            "Music SSD": "UUID-MUSIC",
            "Macintosh HD": "UUID-MAC",
        }.get(volume_path.name, "UUID-UNK")

    with patch("src.volume_utils.get_volume_uuid", side_effect=_uuid_lookup):
        result = find_matching_volumes(settings, volumes_root=tmp_path)

    assert [v.name for v in result] == ["LS-P1"]


def test_find_matching_volumes_returns_deterministic_order(tmp_path):
    """Results must be sorted alphabetically for deterministic iteration."""
    _make_volume(tmp_path, "ZETA")
    _make_volume(tmp_path, "ALPHA")
    _make_volume(tmp_path, "MIKE")

    settings = UserSettings(watch_mode="specific", watched_volumes=["ZETA", "ALPHA", "MIKE"])

    with _stub_uuid("UUID-X"):
        result = find_matching_volumes(settings, volumes_root=tmp_path)

    assert [v.name for v in result] == ["ALPHA", "MIKE", "ZETA"]


def test_find_matching_volumes_missing_root_returns_empty(tmp_path):
    settings = UserSettings(watch_mode="manual", watched_volumes=[])
    missing = tmp_path / "does-not-exist"
    assert find_matching_volumes(settings, volumes_root=missing) == []
