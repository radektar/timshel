"""Unit tests for permissions module."""

import subprocess
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from src.setup.permissions import (
    check_full_disk_access,
    open_fda_preferences,
    check_volume_access,
)


class TestPermissions:
    """Testy dla modułu permissions."""

    def test_check_fda_with_access(self, monkeypatch):
        """Zwraca True gdy ma dostęp."""

        def mock_iterdir(self):
            return iter([])

        monkeypatch.setattr(Path, "exists", lambda self: True)
        monkeypatch.setattr(Path, "iterdir", mock_iterdir)

        assert check_full_disk_access() is True

    def test_check_fda_without_access(self, monkeypatch):
        """Zwraca False gdy PermissionError."""

        def raise_permission_error(self):
            raise PermissionError("Access denied")

        monkeypatch.setattr(Path, "exists", lambda self: True)
        monkeypatch.setattr(Path, "iterdir", raise_permission_error)

        assert check_full_disk_access() is False

    def test_open_fda_preferences(self, monkeypatch):
        """Wywołuje subprocess.run z poprawnym URL."""
        calls = []

        def mock_run(args):
            calls.append(args)

        monkeypatch.setattr(subprocess, "run", mock_run)

        open_fda_preferences()

        assert len(calls) == 1
        assert calls[0][0] == "open"
        assert "Privacy_AllFiles" in calls[0][1]

    def test_check_volume_access_exists(self, tmp_path, monkeypatch):
        """Zwraca True gdy volumen istnieje i ma dostęp."""
        volume = tmp_path / "test_volume"
        volume.mkdir()
        (volume / "file.txt").touch()

        assert check_volume_access(volume) is True

    def test_check_volume_access_permission_error(self, monkeypatch):
        """Zwraca False gdy PermissionError."""

        def raise_permission_error(self):
            raise PermissionError("Access denied")

        volume = Path("/Volumes/test")
        monkeypatch.setattr(Path, "exists", lambda self: True)
        monkeypatch.setattr(Path, "iterdir", raise_permission_error)

        assert check_volume_access(volume) is False

    def test_check_volume_access_not_exists(self):
        """Zwraca False gdy volumen nie istnieje."""
        volume = Path("/Volumes/nonexistent")
        assert check_volume_access(volume) is False
