"""Tests for lightweight download window wrapper."""

import time

from src.ui.download_window import DownloadWindow


def test_download_window_state_updates_without_appkit():
    window = DownloadWindow(title="Test", detail="Start")
    window.update(detail="Half", progress=0.5)
    assert window.state.detail == "Half"
    assert window.state.progress == 0.5
    window.close()
    assert window.state.closed is True


def test_download_window_close_is_idempotent():
    """Drugie wywołanie close() nie rzuca ani nie zmienia stanu ponownie."""
    window = DownloadWindow(title="Test", detail="Start")
    window.close()
    assert window.state.closed is True
    window.close()
    assert window.state.closed is True


def test_download_window_close_after_delays_then_closes():
    """close_after czeka zadany czas i oznacza okno jako zamknięte."""
    window = DownloadWindow(title="Test", detail="Start")
    window.close_after(0.05)
    assert window.state.closed is False
    time.sleep(0.2)
    assert window.state.closed is True
