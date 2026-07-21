"""Tests for file monitor module."""

import pytest
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
from src.file_monitor import (
    FileMonitor,
    DECISION_BLOCKED,
    DECISION_NONE,
    DECISION_ONCE,
    DECISION_TRUSTED,
)
from src.config.settings import UserSettings
from src.config.defaults import defaults


def _uuid_for(path) -> str:
    """Deterministic per-name UUID map for volume-polling tests."""
    return {
        "Macintosh HD": "UUID-SYS",
        "LS-P1": "UUID-LS",
        "SD_CARD": "UUID-SD",
    }.get(Path(path).name, f"UUID-{Path(path).name}")


@pytest.fixture
def mock_callback():
    """Create a mock callback function."""
    return Mock()


def test_file_monitor_initialization(mock_callback):
    """Test FileMonitor initializes correctly."""
    monitor = FileMonitor(mock_callback)

    assert monitor.callback == mock_callback
    assert monitor.observer is None
    assert not monitor.is_monitoring


def test_file_monitor_start_without_fsevents(mock_callback):
    """Test start when FSEvents is not available."""
    with patch("src.file_monitor.FSEVENTS_AVAILABLE", False):
        monitor = FileMonitor(mock_callback)
        monitor.start()

        assert not monitor.is_monitoring


@patch("src.file_monitor.FSEVENTS_AVAILABLE", True)
@patch("src.file_monitor.Observer")
@patch("src.file_monitor.Stream")
def test_file_monitor_start_success(mock_stream, mock_observer, mock_callback):
    """Test successful start of file monitor."""
    monitor = FileMonitor(mock_callback)

    mock_observer_instance = MagicMock()
    mock_observer.return_value = mock_observer_instance

    monitor.start()

    assert monitor.is_monitoring
    mock_observer_instance.start.assert_called_once()


@patch("src.file_monitor.FSEVENTS_AVAILABLE", True)
def test_file_monitor_start_already_running(mock_callback):
    """Test start when already monitoring."""
    monitor = FileMonitor(mock_callback)
    monitor.is_monitoring = True

    with patch("src.file_monitor.Observer"):
        monitor.start()
        # Should not create new observer


def test_file_monitor_stop(mock_callback):
    """Test stop method."""
    monitor = FileMonitor(mock_callback)

    mock_observer = MagicMock()
    monitor.observer = mock_observer
    monitor.is_monitoring = True

    monitor.stop()

    mock_observer.stop.assert_called_once()
    mock_observer.join.assert_called_once()
    assert not monitor.is_monitoring


def test_file_monitor_stop_no_observer(mock_callback):
    """Test stop when no observer exists."""
    monitor = FileMonitor(mock_callback)
    monitor.observer = None

    # Should not raise any errors
    monitor.stop()


@patch("src.file_monitor.FSEVENTS_AVAILABLE", True)
@patch("src.file_monitor.Observer")
@patch("src.file_monitor.Stream")
@patch("src.file_monitor.find_matching_volumes", return_value=[])
def test_file_monitor_ignores_system_directories(
    mock_find, mock_stream, mock_observer, mock_callback
):
    """Test that system directories like .Spotlight-V100 are ignored."""
    from src.file_monitor import FileMonitor
    import time

    monitor = FileMonitor(mock_callback)
    monitor._last_trigger_time = 0.0  # Reset debounce timer

    mock_observer_instance = MagicMock()
    mock_observer.return_value = mock_observer_instance

    # Capture the on_change callback
    on_change_callback = None

    def capture_stream(callback, path, **kwargs):
        nonlocal on_change_callback
        on_change_callback = callback
        return MagicMock()

    mock_stream.side_effect = capture_stream

    monitor.start()

    # Simulate FSEvents callback with system directory path
    if on_change_callback:
        on_change_callback("/Volumes/LS-P1/.Spotlight-V100/Store-V2", 0)
        time.sleep(0.1)  # Small delay to ensure callback processing

    # Callback should not have been called
    mock_callback.assert_not_called()


@patch("src.file_monitor.FSEVENTS_AVAILABLE", True)
@patch("src.file_monitor.Observer")
@patch("src.file_monitor.Stream")
@patch("src.file_monitor.time.sleep")
@patch("src.file_monitor.UserSettings")
@patch("src.file_monitor.find_matching_volumes", return_value=[])
def test_file_monitor_triggers_on_valid_path(
    mock_find,
    mock_user_settings,
    mock_sleep,
    mock_stream,
    mock_observer,
    mock_callback,
    tmp_path,
):
    """Test that valid recorder paths trigger the callback."""
    from src.file_monitor import FileMonitor
    from src.config.settings import UserSettings
    import time

    # Create mock volume structure
    volumes_dir = tmp_path / "Volumes"
    volumes_dir.mkdir()
    ls_p1_volume = volumes_dir / "LS-P1"
    ls_p1_volume.mkdir()
    (ls_p1_volume / "Folder").mkdir()
    (ls_p1_volume / "Folder" / "audio.mp3").touch()

    # Mock UserSettings z trybem manual + zaufanym dyskem (UUID-LS)
    mock_settings = UserSettings()
    mock_settings.watch_mode = "manual"
    mock_settings.add_trusted_volume("UUID-LS", "LS-P1", "trusted")
    mock_user_settings.load.return_value = mock_settings

    # Mock Path("/Volumes") to return our test volumes directory
    original_path = Path

    def mock_path_constructor(path_str):
        if path_str == "/Volumes":
            return volumes_dir
        return original_path(path_str)

    monitor = FileMonitor(mock_callback)
    monitor._last_trigger_time = 0.0  # Reset debounce timer

    mock_observer_instance = MagicMock()
    mock_observer.return_value = mock_observer_instance

    # Capture the on_change callback
    on_change_callback = None

    def capture_stream(callback, path, **kwargs):
        nonlocal on_change_callback
        on_change_callback = callback
        return MagicMock()

    mock_stream.side_effect = capture_stream

    # Patch Path("/Volumes") in file_monitor module + UUID lookup w volume_utils
    # (file_monitor._authorize_volume → should_process_volume → get_volume_uuid)
    with patch("src.file_monitor.Path", side_effect=mock_path_constructor), patch(
        "src.volume_utils.get_volume_uuid", return_value="UUID-LS"
    ):
        monitor.start()

        # Simulate FSEvents callback with valid audio file path
        if on_change_callback:
            on_change_callback(str(ls_p1_volume / "Folder" / "audio.mp3"), 0)
            time.sleep(0.1)  # Small delay to ensure callback processing

        # Callback should have been called
        mock_callback.assert_called_once()


@patch("src.file_monitor.FSEVENTS_AVAILABLE", True)
@patch("src.file_monitor.Observer")
@patch("src.file_monitor.Stream")
@patch("src.file_monitor.find_matching_volumes", return_value=[])
def test_file_monitor_ignores_non_recorder_paths(
    mock_find, mock_stream, mock_observer, mock_callback
):
    """Test that paths not under recorder volumes are ignored."""
    from src.file_monitor import FileMonitor
    import time

    monitor = FileMonitor(mock_callback)
    monitor._last_trigger_time = 0.0  # Reset debounce timer

    mock_observer_instance = MagicMock()
    mock_observer.return_value = mock_observer_instance

    # Capture the on_change callback
    on_change_callback = None

    def capture_stream(callback, path, **kwargs):
        nonlocal on_change_callback
        on_change_callback = callback
        return MagicMock()

    mock_stream.side_effect = capture_stream

    monitor.start()

    # Simulate FSEvents callback with path not under recorder
    if on_change_callback:
        on_change_callback("/Volumes/OtherDisk/file.txt", 0)
        time.sleep(0.1)  # Small delay to ensure callback processing

    # Callback should not have been called
    mock_callback.assert_not_called()


class TestFileMonitorVolumeDetection:
    """Test suite for universal volume detection (v2.0.0)."""

    def test_manual_mode_blank_rejects_unknown(self, tmp_path):
        """v2.0.0-beta.2: tryb manual bez whitelist odrzuca każdy nieznany dysk."""
        monitor = FileMonitor(Mock())

        test_volume = tmp_path / "USB_DRIVE"
        test_volume.mkdir()
        (test_volume / "audio.mp3").touch()

        settings = UserSettings()  # default = manual

        with patch("src.volume_utils.get_volume_uuid", return_value="UUID-USB"):
            result = monitor._should_process_volume(test_volume, settings)
        assert result is False

    def test_manual_mode_trusted_uuid_accepts(self, tmp_path):
        """Manual + UUID na whitelist → accept."""
        monitor = FileMonitor(Mock())

        test_volume = tmp_path / "LS-P1"
        test_volume.mkdir()

        settings = UserSettings()
        settings.add_trusted_volume("UUID-LS", "LS-P1", "trusted")

        with patch("src.volume_utils.get_volume_uuid", return_value="UUID-LS"):
            result = monitor._should_process_volume(test_volume, settings)
        assert result is True

    def test_should_process_volume_specific_mode_in_list(self, tmp_path):
        """Test specific mode processes volumes in watched list."""
        monitor = FileMonitor(Mock())

        test_volume = tmp_path / "SD_CARD"
        test_volume.mkdir()

        settings = UserSettings()
        settings.watch_mode = "specific"
        settings.watched_volumes = ["SD_CARD", "USB_DRIVE"]

        with patch("src.volume_utils.get_volume_uuid", return_value="UUID-SD"):
            result = monitor._should_process_volume(test_volume, settings)
        assert result is True

    def test_should_process_volume_specific_mode_not_in_list(self, tmp_path):
        """Test specific mode ignores volumes not in watched list."""
        monitor = FileMonitor(Mock())

        test_volume = tmp_path / "OTHER_DRIVE"
        test_volume.mkdir()

        settings = UserSettings()
        settings.watch_mode = "specific"
        settings.watched_volumes = ["SD_CARD", "USB_DRIVE"]

        with patch("src.volume_utils.get_volume_uuid", return_value="UUID-OTHER"):
            result = monitor._should_process_volume(test_volume, settings)
        assert result is False

    def test_should_process_volume_manual_mode(self, tmp_path):
        """Test manual mode never auto-processes."""
        monitor = FileMonitor(Mock())

        test_volume = tmp_path / "ANY_DRIVE"
        test_volume.mkdir()
        (test_volume / "audio.mp3").touch()

        settings = UserSettings()
        settings.watch_mode = "manual"

        with patch("src.volume_utils.get_volume_uuid", return_value="UUID-ANY"):
            result = monitor._should_process_volume(test_volume, settings)
        assert result is False

    def test_should_process_volume_ignores_system_volumes(self, tmp_path):
        """Test that system volumes are always ignored."""
        monitor = FileMonitor(Mock())

        # Test with system volume name
        test_volume = tmp_path / "Macintosh HD"
        test_volume.mkdir()
        (test_volume / "audio.mp3").touch()  # Even with audio

        settings = UserSettings()  # default = manual

        with patch("src.volume_utils.get_volume_uuid", return_value="UUID-SYS"):
            result = monitor._should_process_volume(test_volume, settings)
        assert result is False

    def test_should_process_volume_unknown_mode(self, tmp_path, caplog):
        """Test that unknown watch mode defaults to False."""
        monitor = FileMonitor(Mock())

        test_volume = tmp_path / "TEST_DRIVE"
        test_volume.mkdir()

        settings = UserSettings()
        settings.watch_mode = "invalid_mode"

        with patch("src.volume_utils.get_volume_uuid", return_value="UUID-X"):
            result = monitor._should_process_volume(test_volume, settings)
        assert result is False
        assert "Unknown watch_mode" in caplog.text


class TestFileMonitorAudioDetection:
    """Test suite for audio file detection."""

    def test_has_audio_files_detects_mp3(self, tmp_path):
        """Test detection of .mp3 files."""
        monitor = FileMonitor(Mock())

        test_dir = tmp_path / "test"
        test_dir.mkdir()
        (test_dir / "audio.mp3").touch()

        result = monitor._has_audio_files(test_dir)
        assert result is True

    def test_has_audio_files_detects_wav(self, tmp_path):
        """Test detection of .wav files."""
        monitor = FileMonitor(Mock())

        test_dir = tmp_path / "test"
        test_dir.mkdir()
        (test_dir / "recording.wav").touch()

        result = monitor._has_audio_files(test_dir)
        assert result is True

    def test_has_audio_files_detects_m4a(self, tmp_path):
        """Test detection of .m4a files."""
        monitor = FileMonitor(Mock())

        test_dir = tmp_path / "test"
        test_dir.mkdir()
        (test_dir / "audio.m4a").touch()

        result = monitor._has_audio_files(test_dir)
        assert result is True

    def test_has_audio_files_detects_flac(self, tmp_path):
        """Test detection of .flac files."""
        monitor = FileMonitor(Mock())

        test_dir = tmp_path / "test"
        test_dir.mkdir()
        (test_dir / "audio.flac").touch()

        result = monitor._has_audio_files(test_dir)
        assert result is True

    def test_has_audio_files_detects_aac(self, tmp_path):
        """Test detection of .aac files."""
        monitor = FileMonitor(Mock())

        test_dir = tmp_path / "test"
        test_dir.mkdir()
        (test_dir / "audio.aac").touch()

        result = monitor._has_audio_files(test_dir)
        assert result is True

    def test_has_audio_files_detects_ogg(self, tmp_path):
        """Test detection of .ogg files."""
        monitor = FileMonitor(Mock())

        test_dir = tmp_path / "test"
        test_dir.mkdir()
        (test_dir / "audio.ogg").touch()

        result = monitor._has_audio_files(test_dir)
        assert result is True

    def test_has_audio_files_case_insensitive(self, tmp_path):
        """Test that audio detection is case-insensitive."""
        monitor = FileMonitor(Mock())

        test_dir = tmp_path / "test"
        test_dir.mkdir()
        (test_dir / "AUDIO.MP3").touch()  # Uppercase extension

        result = monitor._has_audio_files(test_dir)
        assert result is True

    def test_has_audio_files_ignores_non_audio(self, tmp_path):
        """Test that non-audio files are ignored."""
        monitor = FileMonitor(Mock())

        test_dir = tmp_path / "test"
        test_dir.mkdir()
        (test_dir / "document.txt").touch()
        (test_dir / "image.jpg").touch()
        (test_dir / "video.mp4").touch()

        result = monitor._has_audio_files(test_dir)
        assert result is False

    def test_has_audio_files_nested_directories(self, tmp_path):
        """Test detection in nested directories."""
        monitor = FileMonitor(Mock())

        test_dir = tmp_path / "test"
        test_dir.mkdir()
        (test_dir / "folder1" / "folder2").mkdir(parents=True)
        (test_dir / "folder1" / "folder2" / "audio.mp3").touch()

        result = monitor._has_audio_files(test_dir)
        assert result is True

    def test_has_audio_files_respects_max_depth(self, tmp_path):
        """Test that max_depth limits scanning depth."""
        monitor = FileMonitor(Mock())

        test_dir = tmp_path / "test"
        test_dir.mkdir()

        # Create file beyond max_depth (default is 3)
        deep_path = test_dir
        for i in range(5):  # 5 levels deep
            deep_path = deep_path / f"level{i}"
            deep_path.mkdir()
        (deep_path / "audio.mp3").touch()

        # Should not find it due to depth limit
        result = monitor._has_audio_files(test_dir, max_depth=3)
        assert result is False

        # Should find it with higher depth
        result = monitor._has_audio_files(test_dir, max_depth=6)
        assert result is True

    def test_has_audio_files_handles_permission_error(self, tmp_path, monkeypatch):
        """Test that permission errors are handled gracefully."""
        monitor = FileMonitor(Mock())

        test_dir = tmp_path / "test"
        test_dir.mkdir()

        # Mock Path.rglob to raise PermissionError when called on test_dir
        original_rglob = Path.rglob

        def mock_rglob(self, pattern):
            if self == test_dir:
                raise PermissionError("Access denied")
            return original_rglob(self, pattern)

        monkeypatch.setattr(Path, "rglob", mock_rglob)

        result = monitor._has_audio_files(test_dir)
        assert result is False

    def test_has_audio_files_empty_directory(self, tmp_path):
        """Test that empty directory returns False."""
        monitor = FileMonitor(Mock())

        test_dir = tmp_path / "test"
        test_dir.mkdir()

        result = monitor._has_audio_files(test_dir)
        assert result is False

    def test_has_audio_files_only_directories(self, tmp_path):
        """Test that directories without files return False."""
        monitor = FileMonitor(Mock())

        test_dir = tmp_path / "test"
        test_dir.mkdir()
        (test_dir / "subfolder").mkdir()

        result = monitor._has_audio_files(test_dir)
        assert result is False


class TestScanUnknownVolumes:
    """Polling fallback: surface unknown disks the FSEvents stream missed.

    FSEvents can coalesce a mount event, or report it against the ``/Volumes``
    parent rather than the mountpoint, so an unknown SD card can stay invisible
    until remount. ``scan_unknown_volumes`` (driven by the periodic checker)
    closes that gap by prompting for any unknown, non-system volume.
    """

    @pytest.fixture
    def volumes_root(self, tmp_path):
        """A fake /Volumes with a system, a trusted, and an unknown disk."""
        root = tmp_path / "Volumes"
        root.mkdir()
        (root / "Macintosh HD").mkdir()  # system
        (root / "LS-P1").mkdir()  # already trusted
        (root / "SD_CARD").mkdir()  # unknown → should prompt
        return root

    @pytest.fixture
    def manual_settings(self):
        settings = UserSettings()
        settings.watch_mode = "manual"
        settings.add_trusted_volume("UUID-LS", "LS-P1", "trusted")
        return settings

    def _run(self, monitor, volumes_root, settings):
        with patch("src.file_monitor.UserSettings.load", return_value=settings), patch(
            "src.file_monitor.get_volume_uuid", side_effect=_uuid_for
        ), patch("src.volume_utils.get_volume_uuid", side_effect=_uuid_for):
            monitor.scan_unknown_volumes(volumes_root=volumes_root)

    def test_prompts_only_for_unknown_volume(self, volumes_root, manual_settings):
        """Only the unknown, non-system, non-trusted disk triggers the prompt."""
        handler = Mock(return_value=DECISION_ONCE)
        monitor = FileMonitor(Mock(), on_unknown_volume=handler)

        self._run(monitor, volumes_root, manual_settings)

        handler.assert_called_once()
        prompted_path = handler.call_args.args[0]
        assert Path(prompted_path).name == "SD_CARD"

    def test_disk_image_volume_is_skipped_silently(
        self, volumes_root, manual_settings, caplog
    ):
        """A mounted DMG (e.g. Timshel's own installer) must be filtered
        BEFORE the 'unknown volume — prompting' log — otherwise every 30s
        periodic cycle spams the log for as long as the image stays mounted."""
        import logging

        (volumes_root / "Timshel Installer").mkdir()
        handler = Mock(return_value=DECISION_ONCE)
        monitor = FileMonitor(Mock(), on_unknown_volume=handler)

        with patch(
            "src.file_monitor.is_disk_image_volume",
            side_effect=lambda p: p.name == "Timshel Installer",
        ), caplog.at_level(logging.INFO):
            self._run(monitor, volumes_root, manual_settings)

        # Prompted only for the real unknown disk, never for the DMG…
        prompted = [c.args[0] for c in handler.call_args_list]
        assert all(Path(p).name != "Timshel Installer" for p in prompted)
        # …and the DMG produced ZERO log lines in the scan.
        assert not [r for r in caplog.records if "Timshel Installer" in r.getMessage()]

    def test_persists_trusted_decision(self, volumes_root, manual_settings):
        """A 'Yes' for an unknown disk is persisted as trusted."""
        handler = Mock(return_value=DECISION_TRUSTED)
        monitor = FileMonitor(Mock(), on_unknown_volume=handler)

        with patch.object(FileMonitor, "_persist_decision") as mock_persist:
            self._run(monitor, volumes_root, manual_settings)

        mock_persist.assert_called_once_with("UUID-SD", "SD_CARD", "trusted")

    def test_no_handler_is_noop(self, volumes_root, manual_settings):
        """Without an on_unknown_volume handler the scan does nothing."""
        monitor = FileMonitor(Mock())  # no handler
        # Should not raise; nothing to assert beyond a clean return.
        self._run(monitor, volumes_root, manual_settings)

    def test_skips_in_non_manual_mode(self, volumes_root, manual_settings):
        """In specific/legacy mode the prompt path is not used."""
        manual_settings.watch_mode = "specific"
        handler = Mock(return_value=DECISION_ONCE)
        monitor = FileMonitor(Mock(), on_unknown_volume=handler)

        self._run(monitor, volumes_root, manual_settings)

        handler.assert_not_called()

    def test_skips_session_once_volumes(self, volumes_root, manual_settings):
        """A disk already approved 'Once' this session is not re-prompted."""
        from src import volume_session

        handler = Mock(return_value=DECISION_ONCE)
        monitor = FileMonitor(Mock(), on_unknown_volume=handler)
        volume_session.approve_once("UUID-SD")

        self._run(monitor, volumes_root, manual_settings)

        handler.assert_not_called()

    def test_once_decision_registers_session_approval(
        self, volumes_root, manual_settings
    ):
        """Choosing 'Once' records a session approval (not a persisted decision)."""
        from src import volume_session

        handler = Mock(return_value=DECISION_ONCE)
        monitor = FileMonitor(Mock(), on_unknown_volume=handler)

        with patch.object(FileMonitor, "_persist_decision") as mock_persist:
            self._run(monitor, volumes_root, manual_settings)

        handler.assert_called_once()
        mock_persist.assert_not_called()  # 'Once' is never persisted
        assert volume_session.is_approved_once("UUID-SD") is True

    def test_none_decision_persists_nothing(self, volumes_root, manual_settings):
        """DECISION_NONE (prompt timeout / UI error) must persist NOTHING —
        the periodic scan re-asks later. Only a real click may write."""
        from src import volume_session

        handler = Mock(return_value=DECISION_NONE)
        monitor = FileMonitor(Mock(), on_unknown_volume=handler)

        with patch.object(FileMonitor, "_persist_decision") as mock_persist:
            self._run(monitor, volumes_root, manual_settings)

        handler.assert_called_once()
        mock_persist.assert_not_called()
        assert volume_session.is_approved_once("UUID-SD") is False

    def test_authorize_volume_single_prompt_for_concurrent_calls(
        self, volumes_root, manual_settings
    ):
        """FSEvents and the periodic checker racing on the same unknown UUID
        must produce exactly ONE dialog (per-UUID in-flight guard)."""
        import threading

        release = threading.Event()
        calls = []

        def blocking_handler(volume_path, uuid):
            calls.append(uuid)
            release.wait(timeout=5)
            return DECISION_ONCE

        monitor = FileMonitor(Mock(), on_unknown_volume=blocking_handler)
        sd_card = volumes_root / "SD_CARD"
        results = {}

        def call_authorize(key):
            with patch(
                "src.file_monitor.get_volume_uuid", return_value="UUID-SD"
            ), patch("src.file_monitor.should_process_volume", return_value=False):
                results[key] = monitor._authorize_volume(sd_card, manual_settings)

        t1 = threading.Thread(target=call_authorize, args=("a",))
        t2 = threading.Thread(target=call_authorize, args=("b",))
        t1.start()
        t2.start()
        # Let the second thread hit the in-flight guard, then release the dialog.
        import time

        time.sleep(0.2)
        release.set()
        t1.join(timeout=5)
        t2.join(timeout=5)

        assert len(calls) == 1  # exactly one dialog
        assert sorted(results.values()) == [False, True]  # loser skipped

    def test_ejected_once_disk_is_forgotten(self, tmp_path, manual_settings):
        """A 'Once' disk that is no longer mounted is forgotten (re-ask later)."""
        from src import volume_session

        # SD approved Once, but /Volumes now only has the system + trusted disks.
        volume_session.approve_once("UUID-SD")
        root = tmp_path / "Volumes"
        root.mkdir()
        (root / "Macintosh HD").mkdir()
        (root / "LS-P1").mkdir()  # trusted, still mounted; SD_CARD is gone

        monitor = FileMonitor(
            Mock(), on_unknown_volume=Mock(return_value=DECISION_ONCE)
        )
        self._run(monitor, root, manual_settings)

        assert volume_session.is_approved_once("UUID-SD") is False

    def test_still_mounted_once_disk_is_kept(self, volumes_root, manual_settings):
        """A 'Once' disk that is still mounted stays approved."""
        from src import volume_session

        volume_session.approve_once("UUID-SD")  # SD_CARD is present in volumes_root
        monitor = FileMonitor(
            Mock(), on_unknown_volume=Mock(return_value=DECISION_ONCE)
        )

        self._run(monitor, volumes_root, manual_settings)

        assert volume_session.is_approved_once("UUID-SD") is True

    def test_missing_volumes_root_is_noop(self, tmp_path, manual_settings):
        """A non-existent /Volumes is handled gracefully."""
        handler = Mock(return_value=DECISION_ONCE)
        monitor = FileMonitor(Mock(), on_unknown_volume=handler)

        self._run(monitor, tmp_path / "nope", manual_settings)

        handler.assert_not_called()

    def test_blocked_volume_not_reprompted(self, volumes_root, manual_settings):
        """A previously blocked disk is skipped, not prompted again."""
        manual_settings.add_trusted_volume("UUID-SD", "SD_CARD", "blocked")
        handler = Mock(return_value=DECISION_ONCE)
        monitor = FileMonitor(Mock(), on_unknown_volume=handler)

        self._run(monitor, volumes_root, manual_settings)

        handler.assert_not_called()


class TestFileMonitorInitialScan:
    """Regression tests for initial volume scan at daemon startup.

    Bug: FSEvents only fires on mount/change events, so a recorder that is
    already mounted before ``FileMonitor.start()`` was never detected. These
    tests lock in the fix that ``start()`` runs a one-shot scan right after
    the observer is up.
    """

    @patch("src.file_monitor.FSEVENTS_AVAILABLE", True)
    @patch("src.file_monitor.Observer")
    @patch("src.file_monitor.Stream")
    @patch("src.file_monitor.find_matching_volumes")
    def test_start_triggers_callback_when_volume_preexists(
        self,
        mock_find,
        mock_stream,
        mock_observer,
        mock_callback,
        tmp_path,
    ):
        """If a matching volume is already mounted, callback runs once."""
        mock_find.return_value = [tmp_path / "LS-P1"]
        mock_observer.return_value = MagicMock()

        monitor = FileMonitor(mock_callback)
        monitor.start()

        mock_callback.assert_called_once()

    @patch("src.file_monitor.FSEVENTS_AVAILABLE", True)
    @patch("src.file_monitor.Observer")
    @patch("src.file_monitor.Stream")
    @patch("src.file_monitor.find_matching_volumes")
    def test_start_does_not_trigger_when_no_volumes(
        self,
        mock_find,
        mock_stream,
        mock_observer,
        mock_callback,
    ):
        """When no matching volumes are mounted, callback must not run."""
        mock_find.return_value = []
        mock_observer.return_value = MagicMock()

        monitor = FileMonitor(mock_callback)
        monitor.start()

        mock_callback.assert_not_called()

    @patch("src.file_monitor.FSEVENTS_AVAILABLE", True)
    @patch("src.file_monitor.Observer")
    @patch("src.file_monitor.Stream")
    @patch("src.file_monitor.find_matching_volumes")
    def test_start_calls_callback_once_regardless_of_volume_count(
        self,
        mock_find,
        mock_stream,
        mock_observer,
        mock_callback,
        tmp_path,
    ):
        """Callback is invoked exactly once even with multiple volumes.

        ``Transcriber.process_recorder`` handles iteration internally via
        ``find_recorders``, so the monitor must not call back per-volume.
        """
        mock_find.return_value = [
            tmp_path / "LS-P1",
            tmp_path / "SD_CARD",
            tmp_path / "USB_DRIVE",
        ]
        mock_observer.return_value = MagicMock()

        monitor = FileMonitor(mock_callback)
        monitor.start()

        assert mock_callback.call_count == 1

    @patch("src.file_monitor.FSEVENTS_AVAILABLE", True)
    @patch("src.file_monitor.Observer")
    @patch("src.file_monitor.Stream")
    @patch("src.file_monitor.find_matching_volumes")
    def test_initial_scan_sets_debounce_timer(
        self,
        mock_find,
        mock_stream,
        mock_observer,
        mock_callback,
        tmp_path,
    ):
        """Initial scan must update ``_last_trigger_time`` to debounce
        any FSEvents that fire right after (mount-triggered churn)."""
        mock_find.return_value = [tmp_path / "LS-P1"]
        mock_observer.return_value = MagicMock()

        monitor = FileMonitor(mock_callback)
        assert monitor._last_trigger_time == 0.0

        monitor.start()

        assert monitor._last_trigger_time > 0.0

    @patch("src.file_monitor.FSEVENTS_AVAILABLE", True)
    @patch("src.file_monitor.Observer")
    @patch("src.file_monitor.Stream")
    @patch("src.file_monitor.find_matching_volumes")
    def test_initial_scan_swallows_callback_exceptions(
        self,
        mock_find,
        mock_stream,
        mock_observer,
        tmp_path,
    ):
        """A raising callback must not prevent the monitor from running."""
        mock_find.return_value = [tmp_path / "LS-P1"]
        mock_observer.return_value = MagicMock()

        failing_callback = Mock(side_effect=RuntimeError("boom"))

        monitor = FileMonitor(failing_callback)
        monitor.start()

        assert monitor.is_monitoring is True
        failing_callback.assert_called_once()
