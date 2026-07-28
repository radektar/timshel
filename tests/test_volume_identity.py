"""Tests for src.volume_identity (UUID detection from diskutil)."""

import plistlib
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from src.volume_identity import (
    _build_fallback_uuid,
    _run_diskutil_info,
    get_volume_metadata,
    get_volume_uuid,
)


def _make_completed(
    returncode: int, stdout_bytes: bytes = b""
) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=["diskutil"], returncode=returncode, stdout=stdout_bytes, stderr=b""
    )


def _plist_payload(volume_uuid: str | None, **extra) -> bytes:
    data = dict(extra)
    if volume_uuid is not None:
        data["VolumeUUID"] = volume_uuid
    return plistlib.dumps(data)


def test_get_volume_uuid_returns_real_uuid_when_diskutil_succeeds():
    payload = _plist_payload("ABC-123-DEF", VolumeName="LS-P1")
    with patch(
        "src.volume_identity.subprocess.run",
        return_value=_make_completed(0, payload),
    ):
        uuid = get_volume_uuid(Path("/Volumes/LS-P1"))
    assert uuid == "ABC-123-DEF"


def test_get_volume_uuid_falls_back_when_diskutil_fails():
    """diskutil zwraca błąd → fallback identyfikator z nazwą."""
    with patch(
        "src.volume_identity.subprocess.run",
        return_value=_make_completed(1, b""),
    ):
        uuid = get_volume_uuid(Path("/Volumes/Mystery"))
    assert uuid.startswith("fallback:")
    assert "name:Mystery" in uuid


def test_get_volume_uuid_falls_back_when_uuid_field_missing():
    """diskutil zwraca plist ale bez VolumeUUID → fallback z size/fs."""
    payload = _plist_payload(None, TotalSize=1024, FilesystemName="exFAT")
    with patch(
        "src.volume_identity.subprocess.run",
        return_value=_make_completed(0, payload),
    ):
        uuid = get_volume_uuid(Path("/Volumes/NoUUID"))
    assert uuid.startswith("fallback:")
    assert "name:NoUUID" in uuid
    assert "size:1024" in uuid
    assert "fs:exFAT" in uuid


def test_get_volume_uuid_uses_diskuuid_when_volumeuuid_missing():
    """FAT/exFAT cards lack VolumeUUID — fall back to the stable DiskUUID."""
    payload = _plist_payload(
        None,
        DiskUUID="GPT-PART-GUID-1",
        TotalSize=64_000_000,
        FilesystemName="MS-DOS FAT32",
    )
    with patch(
        "src.volume_identity.subprocess.run",
        return_value=_make_completed(0, payload),
    ):
        uuid = get_volume_uuid(Path("/Volumes/NO NAME"))
    assert uuid == "GPT-PART-GUID-1"  # a real id, not the name-based fallback


def test_get_volume_uuid_uses_mediauuid_as_last_real_resort():
    """When only MediaUUID is present, use it before the composite fallback."""
    payload = _plist_payload(None, MediaUUID="MEDIA-GUID-9", FilesystemName="ExFAT")
    with patch(
        "src.volume_identity.subprocess.run",
        return_value=_make_completed(0, payload),
    ):
        uuid = get_volume_uuid(Path("/Volumes/CARD"))
    assert uuid == "MEDIA-GUID-9"


def test_get_volume_uuid_prefers_volumeuuid_over_diskuuid():
    """VolumeUUID stays the first choice when both are present."""
    payload = _plist_payload("VOL-1", DiskUUID="DISK-2")
    with patch(
        "src.volume_identity.subprocess.run",
        return_value=_make_completed(0, payload),
    ):
        uuid = get_volume_uuid(Path("/Volumes/X"))
    assert uuid == "VOL-1"


def test_get_volume_uuid_fallback_when_subprocess_raises():
    with patch(
        "src.volume_identity.subprocess.run",
        side_effect=OSError("not-found"),
    ):
        uuid = get_volume_uuid(Path("/Volumes/Anything"))
    assert uuid == "fallback:name:Anything:size::fs:"


def test_get_volume_uuid_fallback_when_subprocess_times_out():
    with patch(
        "src.volume_identity.subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="diskutil", timeout=3),
    ):
        uuid = get_volume_uuid(Path("/Volumes/SlowMount"))
    assert uuid.startswith("fallback:name:SlowMount")


def test_get_volume_uuid_fallback_when_plist_invalid():
    with patch(
        "src.volume_identity.subprocess.run",
        return_value=_make_completed(0, b"not a plist"),
    ):
        uuid = get_volume_uuid(Path("/Volumes/Garbled"))
    assert uuid.startswith("fallback:name:Garbled")


def test_get_volume_metadata_includes_uuid_and_size():
    payload = _plist_payload(
        "ABC-1",
        VolumeName="LS-P1",
        TotalSize=2048,
        FilesystemName="MS-DOS FAT32",
    )
    with patch(
        "src.volume_identity.subprocess.run",
        return_value=_make_completed(0, payload),
    ):
        meta = get_volume_metadata(Path("/Volumes/LS-P1"))
    assert meta == {
        "name": "LS-P1",
        "size": 2048,
        "filesystem": "MS-DOS FAT32",
        "uuid": "ABC-1",
    }


def test_build_fallback_uuid_deterministic():
    a = _build_fallback_uuid(Path("/Volumes/Foo"), info=None)
    b = _build_fallback_uuid(Path("/Volumes/Foo"), info=None)
    assert a == b
