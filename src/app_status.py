"""Application status management for Timshel."""

import threading
from enum import Enum
from typing import Optional


class AppStatus(Enum):
    """Application status states."""

    IDLE = "idle"
    SCANNING = "scanning"
    TRANSCRIBING = "transcribing"
    DOWNLOADING = "downloading"
    MIGRATING = "migrating"
    RECORDER_IDLE = "recorder_idle"
    RECORDER_PENDING = "recorder_pending"
    ERROR = "error"


class AppState:
    """Thread-safe application state container.

    Attributes:
        status: Current application status
        current_file: Name of file currently being transcribed (if any)
        error_message: Last error message (if status is ERROR)
    """

    def __init__(self):
        """Initialize application state."""
        self._lock = threading.Lock()
        self._status = AppStatus.IDLE
        self._current_file: Optional[str] = None
        self._error_message: Optional[str] = None
        self._recorder_name: Optional[str] = None
        self._pending_count: Optional[int] = None
        self._digest_ready: Optional[str] = None

    @property
    def status(self) -> AppStatus:
        """Get current status."""
        with self._lock:
            return self._status

    @status.setter
    def status(self, value: AppStatus) -> None:
        """Set current status."""
        with self._lock:
            self._status = value

    @property
    def current_file(self) -> Optional[str]:
        """Get current file being transcribed."""
        with self._lock:
            return self._current_file

    @current_file.setter
    def current_file(self, value: Optional[str]) -> None:
        """Set current file being transcribed."""
        with self._lock:
            self._current_file = value

    @property
    def error_message(self) -> Optional[str]:
        """Get last error message."""
        with self._lock:
            return self._error_message

    @error_message.setter
    def error_message(self, value: Optional[str]) -> None:
        """Set last error message."""
        with self._lock:
            self._error_message = value

    @property
    def recorder_name(self) -> Optional[str]:
        """Get current recorder display name."""
        with self._lock:
            return self._recorder_name

    @recorder_name.setter
    def recorder_name(self, value: Optional[str]) -> None:
        """Set current recorder display name."""
        with self._lock:
            self._recorder_name = value

    @property
    def pending_count(self) -> Optional[int]:
        """Get pending files count for current recorder."""
        with self._lock:
            return self._pending_count

    @pending_count.setter
    def pending_count(self, value: Optional[int]) -> None:
        """Set pending files count for current recorder."""
        with self._lock:
            self._pending_count = value

    @property
    def digest_ready(self) -> Optional[str]:
        """Filename of a freshly written synthesis digest, or None."""
        with self._lock:
            return self._digest_ready

    @digest_ready.setter
    def digest_ready(self, value: Optional[str]) -> None:
        """Set the freshly written synthesis digest filename."""
        with self._lock:
            self._digest_ready = value

    def get_status_string(self) -> str:
        """Get human-readable status string.

        Returns:
            Formatted status string for UI display
        """
        with self._lock:
            if self._status == AppStatus.IDLE:
                return "Waiting for recorder…"
            elif self._status == AppStatus.SCANNING:
                return "Scanning recorder…"
            elif self._status == AppStatus.TRANSCRIBING:
                if self._current_file:
                    return f"Processing: {self._current_file}"
                return "Processing…"
            elif self._status == AppStatus.DOWNLOADING:
                return "Downloading dependencies…"
            elif self._status == AppStatus.MIGRATING:
                return "Migrating index…"
            elif self._status == AppStatus.RECORDER_IDLE:
                recorder_name = self._recorder_name or "Recorder"
                return f"Recorder: {recorder_name} (synced)"
            elif self._status == AppStatus.RECORDER_PENDING:
                recorder_name = self._recorder_name or "Recorder"
                pending_count = self._pending_count or 0
                return f"Recorder: {recorder_name} ({pending_count} to transcribe)"
            elif self._status == AppStatus.ERROR:
                if self._error_message:
                    return f"Error: {self._error_message}"
                return "Error"
            return "Unknown status"

