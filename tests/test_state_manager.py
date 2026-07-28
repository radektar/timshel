"""Tests for state management."""

import json
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from src.state_manager import reset_state, get_last_sync_time, save_sync_time
from src.config import config


class TestStateManager:
    """Test state management functions."""

    @pytest.fixture
    def temp_state_file(self, tmp_path):
        """Create temporary state file."""
        original_state_file = config.STATE_FILE
        temp_file = tmp_path / "test_state.json"
        config.STATE_FILE = temp_file
        yield temp_file
        config.STATE_FILE = original_state_file

    def test_reset_state_default_date(self, temp_state_file):
        """Test reset_state with default date (7 days ago)."""
        success = reset_state()
        assert success is True
        assert temp_state_file.exists()

        with open(temp_state_file, "r") as f:
            data = json.load(f)
            assert "last_sync" in data
            last_sync = datetime.fromisoformat(data["last_sync"])
            # Should be approximately 7 days ago (within 1 minute tolerance)
            expected = datetime.now() - timedelta(days=7)
            diff = abs((last_sync - expected).total_seconds())
            assert diff < 60

    def test_reset_state_custom_date(self, temp_state_file):
        """Test reset_state with custom date."""
        target_date = datetime(2025, 1, 15, 12, 30, 0)
        success = reset_state(target_date)
        assert success is True

        with open(temp_state_file, "r") as f:
            data = json.load(f)
            last_sync = datetime.fromisoformat(data["last_sync"])
            assert last_sync == target_date

    def test_reset_state_creates_backup(self, temp_state_file):
        """Test reset_state creates backup of existing file."""
        # Create initial state file
        initial_date = datetime(2025, 1, 1)
        with open(temp_state_file, "w") as f:
            json.dump({"last_sync": initial_date.isoformat()}, f)

        # Reset to new date
        new_date = datetime(2025, 1, 15)
        reset_state(new_date)

        # Check backup exists
        backup_file = Path(str(temp_state_file) + ".backup")
        assert backup_file.exists()

        # Check backup contains original date
        with open(backup_file, "r") as f:
            backup_data = json.load(f)
            backup_date = datetime.fromisoformat(backup_data["last_sync"])
            assert backup_date == initial_date

    def test_get_last_sync_time_existing_file(self, temp_state_file):
        """Test get_last_sync_time with existing state file."""
        target_date = datetime(2025, 1, 15, 12, 0, 0)
        with open(temp_state_file, "w") as f:
            json.dump({"last_sync": target_date.isoformat()}, f)

        last_sync = get_last_sync_time()
        assert last_sync == target_date

    def test_get_last_sync_time_no_file(self, temp_state_file):
        """Test get_last_sync_time when state file doesn't exist."""
        if temp_state_file.exists():
            temp_state_file.unlink()

        last_sync = get_last_sync_time()
        # Should default to 7 days ago (within 1 minute tolerance)
        expected = datetime.now() - timedelta(days=7)
        diff = abs((last_sync - expected).total_seconds())
        assert diff < 60

    def test_get_last_sync_time_corrupted_file(self, temp_state_file):
        """Test get_last_sync_time with corrupted state file."""
        # Write invalid JSON
        with open(temp_state_file, "w") as f:
            f.write("invalid json{")

        last_sync = get_last_sync_time()
        # Should default to 7 days ago
        expected = datetime.now() - timedelta(days=7)
        diff = abs((last_sync - expected).total_seconds())
        assert diff < 60

    def test_save_sync_time(self, temp_state_file):
        """Test save_sync_time saves current time."""
        save_sync_time()
        assert temp_state_file.exists()

        with open(temp_state_file, "r") as f:
            data = json.load(f)
            assert "last_sync" in data
            saved_time = datetime.fromisoformat(data["last_sync"])
            # Should be approximately now (within 1 second tolerance)
            now = datetime.now()
            diff = abs((saved_time - now).total_seconds())
            assert diff < 1

    def test_reset_state_timezone_aware(self, temp_state_file):
        """Test reset_state handles timezone-aware datetime."""
        from datetime import timezone

        target_date = datetime(2025, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
        success = reset_state(target_date)
        assert success is True

        with open(temp_state_file, "r") as f:
            data = json.load(f)
            last_sync = datetime.fromisoformat(data["last_sync"])
            # Should be timezone-naive
            assert last_sync.tzinfo is None
            # But date/time should match (ignoring timezone)
            assert last_sync.replace(tzinfo=timezone.utc) == target_date
