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


def test_app_core_stop_calls_transcriber_stop():
    """stop() must kill an in-flight whisper via Transcriber.stop()."""
    app = MalincheTranscriber(setup_signals=False)
    app.transcriber = MagicMock()
    app.monitor = MagicMock()
    app.running = True

    app.stop()

    app.transcriber.stop.assert_called_once()


def test_app_core_stop_survives_transcriber_stop_error():
    """A failing transcriber.stop() must not abort the rest of shutdown."""
    app = MalincheTranscriber(setup_signals=False)
    app.transcriber = MagicMock()
    app.transcriber.stop.side_effect = OSError("boom")
    app.monitor = MagicMock()
    app.running = True

    app.stop()  # no raise

    app.monitor.stop.assert_called_once()


def test_vault_index_property_delegates_to_inner_transcriber():
    """menu_app reads ``app.transcriber.vault_index`` — it must forward to the
    inner Transcriber rather than raising (the recent-transcripts rail bug)."""
    app = MalincheTranscriber(setup_signals=False)
    sentinel = object()
    app.transcriber = type("Inner", (), {"vault_index": sentinel})()
    assert app.vault_index is sentinel


def test_vault_index_property_raises_before_transcriber_built():
    """Before the daemon builds its Transcriber, the property raises
    AttributeError — which the menu caller catches and falls back to disk."""
    app = MalincheTranscriber(setup_signals=False)
    app.transcriber = None
    import pytest

    with pytest.raises(AttributeError):
        _ = app.vault_index
