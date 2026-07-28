"""Tests for application status management."""

import threading
import time
from pathlib import Path

import pytest

from src.app_status import AppStatus, AppState


class TestAppState:
    """Test AppState thread-safe state container."""

    def test_initial_state(self):
        """Test initial state is IDLE."""
        state = AppState()
        assert state.status == AppStatus.IDLE
        assert state.current_file is None
        assert state.error_message is None

    def test_status_update(self):
        """Test status can be updated."""
        state = AppState()
        state.status = AppStatus.SCANNING
        assert state.status == AppStatus.SCANNING

    def test_current_file_update(self):
        """Test current file can be updated."""
        state = AppState()
        state.current_file = "test.mp3"
        assert state.current_file == "test.mp3"
        state.current_file = None
        assert state.current_file is None

    def test_error_message_update(self):
        """Test error message can be updated."""
        state = AppState()
        state.error_message = "Test error"
        assert state.error_message == "Test error"
        state.error_message = None
        assert state.error_message is None

    def test_thread_safety(self):
        """Test thread-safe access to state."""
        state = AppState()
        results = []

        def update_status(status: AppStatus):
            """Update status from thread."""
            for _ in range(100):
                state.status = status
                time.sleep(0.001)

        threads = []
        for status in [AppStatus.IDLE, AppStatus.SCANNING, AppStatus.TRANSCRIBING]:
            thread = threading.Thread(target=update_status, args=(status,))
            threads.append(thread)
            thread.start()

        for thread in threads:
            thread.join()

        # State should be one of the values set
        assert state.status in [
            AppStatus.IDLE,
            AppStatus.SCANNING,
            AppStatus.TRANSCRIBING,
        ]

    def test_get_status_string_idle(self):
        """Test status string for IDLE."""
        state = AppState()
        state.status = AppStatus.IDLE
        status_str = state.get_status_string()
        assert "Waiting" in status_str

    def test_get_status_string_scanning(self):
        """Test status string for SCANNING."""
        state = AppState()
        state.status = AppStatus.SCANNING
        status_str = state.get_status_string()
        assert "Scanning" in status_str

    def test_get_status_string_transcribing(self):
        """Test status string for TRANSCRIBING."""
        state = AppState()
        state.status = AppStatus.TRANSCRIBING
        state.current_file = "test.mp3"
        status_str = state.get_status_string()
        assert "Processing" in status_str
        assert "test.mp3" in status_str

    def test_get_status_string_error(self):
        """Test status string for ERROR."""
        state = AppState()
        state.status = AppStatus.ERROR
        state.error_message = "Test error message"
        status_str = state.get_status_string()
        assert "Error" in status_str
        assert "Test error message" in status_str
