"""Tests for the MalincheTranscriber orchestrator (app_core).

Focus: the periodic checker now also surfaces unknown disks the FSEvents
stream missed, by calling ``FileMonitor.scan_unknown_volumes`` before
``process_recorder`` on each tick.
"""

from unittest.mock import MagicMock, patch

from src.app_core import MalincheTranscriber


def _stop_after_first(app):
    """Return a process_recorder side-effect that ends the loop after one tick."""

    def _process():
        app.running = False

    return _process


def test_periodic_check_scans_unknown_then_processes():
    """Each tick scans for unknown volumes, then processes recorders — in order."""
    app = MalincheTranscriber(setup_signals=False)
    app.monitor = MagicMock()
    app.transcriber = MagicMock()
    app.running = True

    order = []
    app.monitor.scan_unknown_volumes.side_effect = lambda: order.append("scan")

    def _process():
        order.append("process")
        app.running = False

    app.transcriber.process_recorder.side_effect = _process

    with patch("src.app_core.time.sleep"):
        app._periodic_check()

    assert order == ["scan", "process"]


def test_periodic_check_survives_scan_error():
    """A failing volume scan must not prevent the recorder from being processed."""
    app = MalincheTranscriber(setup_signals=False)
    app.monitor = MagicMock()
    app.transcriber = MagicMock()
    app.running = True

    app.monitor.scan_unknown_volumes.side_effect = RuntimeError("boom")
    app.transcriber.process_recorder.side_effect = _stop_after_first(app)

    with patch("src.app_core.time.sleep"), patch("src.app_core.logger"):
        app._periodic_check()

    app.transcriber.process_recorder.assert_called_once()


def test_periodic_check_without_monitor_still_processes():
    """If no monitor is wired, the periodic check still processes recorders."""
    app = MalincheTranscriber(setup_signals=False)
    app.monitor = None
    app.transcriber = MagicMock()
    app.running = True

    app.transcriber.process_recorder.side_effect = _stop_after_first(app)

    with patch("src.app_core.time.sleep"):
        app._periodic_check()

    app.transcriber.process_recorder.assert_called_once()
