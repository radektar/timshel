"""Tests for the Voice Memos FSEvents shell and its wiring into app_core."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.voice_memos import VoiceMemosWatcher


@pytest.fixture
def recordings_dir(tmp_path: Path) -> Path:
    folder = tmp_path / "Recordings"
    folder.mkdir()
    return folder


class TestWatcher:
    @patch("src.voice_memos.FSEVENTS_AVAILABLE", True)
    @patch("src.voice_memos.Stream")
    @patch("src.voice_memos.Observer")
    def test_start_watches_the_recordings_folder(
        self, observer_cls, stream_cls, recordings_dir
    ):
        watcher = VoiceMemosWatcher(recordings_dir, MagicMock())

        assert watcher.start() is True
        assert watcher.is_watching is True
        observer_cls.return_value.start.assert_called_once()
        # Per-file events: a memo landing in the folder must be visible, not
        # just the folder itself changing.
        assert stream_cls.call_args.kwargs["file_events"] is True

    @patch("src.voice_memos.FSEVENTS_AVAILABLE", True)
    @patch("src.voice_memos.Stream")
    @patch("src.voice_memos.Observer")
    def test_stop_releases_the_observer(self, observer_cls, _stream, recordings_dir):
        watcher = VoiceMemosWatcher(recordings_dir, MagicMock())
        watcher.start()

        watcher.stop()

        observer_cls.return_value.stop.assert_called_once()
        assert watcher.is_watching is False
        assert watcher.observer is None

    @patch("src.voice_memos.FSEVENTS_AVAILABLE", False)
    def test_without_fsevents_it_degrades_quietly(self, recordings_dir):
        # The periodic tick still covers everything; this is only an accelerator.
        watcher = VoiceMemosWatcher(recordings_dir, MagicMock())

        assert watcher.start() is False
        assert watcher.is_watching is False

    @patch("src.voice_memos.FSEVENTS_AVAILABLE", True)
    def test_missing_folder_is_not_an_error(self, tmp_path):
        watcher = VoiceMemosWatcher(tmp_path / "not-yet", MagicMock())

        assert watcher.start() is False

    @patch("src.voice_memos.FSEVENTS_AVAILABLE", True)
    @patch("src.voice_memos.Stream")
    @patch("src.voice_memos.Observer")
    def test_events_are_debounced(self, _observer, _stream, recordings_dir):
        callback = MagicMock()
        watcher = VoiceMemosWatcher(recordings_dir, callback, debounce_seconds=60.0)
        watcher.start()

        watcher._handle_event("path", 0)
        watcher._handle_event("path", 0)
        watcher._handle_event("path", 0)

        assert callback.call_count == 1

    @patch("src.voice_memos.FSEVENTS_AVAILABLE", True)
    @patch("src.voice_memos.Stream")
    @patch("src.voice_memos.Observer")
    def test_a_failing_callback_never_kills_the_stream(
        self, _observer, _stream, recordings_dir
    ):
        watcher = VoiceMemosWatcher(
            recordings_dir, MagicMock(side_effect=RuntimeError("boom"))
        )
        watcher.start()

        watcher._handle_event("path", 0)  # must not raise


class TestAppCoreWiring:
    def _app(self, tmp_path):
        from src.app_core import TimshelTranscriber
        from src.voice_memos import VoiceMemosConnector

        app = TimshelTranscriber(setup_signals=False)
        app.transcriber = MagicMock()
        app.voice_memos = VoiceMemosConnector(
            tmp_path / "Recordings", tmp_path / "state.json"
        )
        return app

    @patch("src.app_core.process_voice_memos")
    def test_disabled_connector_does_no_work(self, process, tmp_path):
        app = self._app(tmp_path)

        with patch.object(app, "_voice_memos_enabled", return_value=False):
            app._sync_voice_memos()

        process.assert_not_called()

    @patch("src.app_core.process_voice_memos")
    @patch("src.voice_memos.FSEVENTS_AVAILABLE", True)
    @patch("src.voice_memos.Stream")
    @patch("src.voice_memos.Observer")
    def test_enabled_connector_imports_and_arms_the_watcher(
        self, _observer, _stream, process, tmp_path
    ):
        app = self._app(tmp_path)
        app.voice_memos.recordings_dir.mkdir()

        with patch.object(app, "_voice_memos_enabled", return_value=True):
            app._sync_voice_memos()

        process.assert_called_once()
        assert app.voice_memos_watcher is not None

    @patch("src.app_core.process_voice_memos")
    @patch("src.voice_memos.FSEVENTS_AVAILABLE", False)
    def test_a_watcher_that_failed_to_arm_is_retried(self, _process, tmp_path):
        # iCloud may not have created the folder yet; keeping a dead watcher
        # would silently disable live events until the app restarts.
        app = self._app(tmp_path)

        with patch.object(app, "_voice_memos_enabled", return_value=True):
            app._sync_voice_memos()

        assert app.voice_memos_watcher is None

    @patch("src.app_core.process_voice_memos")
    @patch("src.voice_memos.FSEVENTS_AVAILABLE", False)
    def test_enabling_stamps_the_start_marker(self, _process, tmp_path):
        # Self-healing: the toggle may have been saved while the connector did
        # not exist yet, leaving no marker — without one, scan() imports nothing.
        app = self._app(tmp_path)
        assert app.voice_memos.enabled_at is None

        with patch.object(app, "_voice_memos_enabled", return_value=True):
            app._sync_voice_memos()

        assert app.voice_memos.enabled_at is not None

    @patch("src.app_core.process_voice_memos")
    @patch("src.voice_memos.FSEVENTS_AVAILABLE", True)
    @patch("src.voice_memos.Stream")
    @patch("src.voice_memos.Observer")
    def test_turning_the_toggle_off_stops_the_watcher(
        self, observer, _stream, _process, tmp_path
    ):
        app = self._app(tmp_path)
        app.voice_memos.recordings_dir.mkdir()
        with patch.object(app, "_voice_memos_enabled", return_value=True):
            app._sync_voice_memos()
        assert app.voice_memos_watcher is not None

        with patch.object(app, "_voice_memos_enabled", return_value=False):
            app._sync_voice_memos()

        assert app.voice_memos_watcher is None
        observer.return_value.stop.assert_called_once()

    def test_no_transcriber_yet_is_harmless(self, tmp_path):
        app = self._app(tmp_path)
        app.transcriber = None

        app._sync_voice_memos()  # must not raise
