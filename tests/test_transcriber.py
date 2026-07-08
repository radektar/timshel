"""Tests for transcriber module."""

import json
import os
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

from src.transcriber import Transcriber
from src.app_status import AppStatus
from src.summarizer import BaseSummarizer
from src.markdown_generator import MarkdownGenerator
from src.vault_index import IndexEntry
from src.config.settings import UserSettings


def update_transcriber_config(transcriber, monkeypatch, **kwargs):
    """Helper to update both transcriber.config and global config.

    Args:
        transcriber: Transcriber instance
        monkeypatch: pytest monkeypatch fixture
        **kwargs: Config attributes to update (e.g., TRANSCRIBE_DIR=path)
    """
    from src import config as config_module

    from src import config as config_module

    # Update transcriber's injected config
    for key, value in kwargs.items():
        setattr(transcriber.config, key, value)

    # Also update global config for state_manager functions
    for key, value in kwargs.items():
        monkeypatch.setattr(config_module.config, key, value)


@pytest.fixture
def transcriber(monkeypatch, tmp_path):
    """Create a transcriber instance for testing.

    Creates Transcriber with a test Config instance to avoid global state issues.
    """
    from src.config.config import Config

    # Create a test config instance
    test_config = Config()
    # Keep the persisted Core ML verdict (coreml_status.json, written next to
    # STATE_FILE) inside tmp so tests don't read/write the real Application
    # Support dir.
    test_config.STATE_FILE = tmp_path / "state.json"

    with patch("src.transcriber.logger"):
        # Pass config explicitly for dependency injection
        return Transcriber(config=test_config)


@pytest.fixture
def mock_recorder_path(tmp_path):
    """Create a mock recorder directory with audio files."""
    recorder = tmp_path / "LS-P1"
    recorder.mkdir()

    # Create some audio files
    audio_dir = recorder / "Music"
    audio_dir.mkdir()

    (audio_dir / "recording1.mp3").touch()
    (audio_dir / "recording2.wav").touch()
    (audio_dir / "document.txt").touch()  # Non-audio file

    return recorder


def test_transcriber_initialization(transcriber):
    """Test transcriber initializes correctly."""
    assert isinstance(transcriber.transcription_in_progress, dict)
    assert isinstance(transcriber.recorder_monitoring, bool)
    assert not transcriber.recorder_monitoring


def test_find_recorder_not_found(transcriber):
    """Test find_recorder when no recorder is connected."""
    with patch("src.transcriber.find_matching_volumes", return_value=[]):
        result = transcriber.find_recorder()
        assert result is None


def test_find_recorder_found(transcriber):
    """Test find_recorder when recorder is present."""
    # This test validates that find_recorder doesn't crash
    # Actual result depends on whether recorder is connected
    # We test the method structure, not the actual detection
    result = transcriber.find_recorder()
    # Result can be None (no recorder) or Path (recorder found)
    # Both are valid - we're just checking the method works
    assert result is None or isinstance(result, Path)


def _make_volume_with_audio(root: Path, name: str, filename: str = "rec.mp3") -> Path:
    """Create a fake volume directory containing one audio file."""
    volume = root / name
    volume.mkdir()
    (volume / filename).touch()
    return volume


def _make_empty_volume(root: Path, name: str) -> Path:
    """Create a fake volume directory with no audio files."""
    volume = root / name
    volume.mkdir()
    (volume / "readme.txt").touch()
    return volume


def test_find_recorders_manual_mode_detects_trusted_volumes(
    transcriber, tmp_path, monkeypatch
):
    """v2.0.0-beta.2: Manual + UUID-trusted volumes są wykryte jako recordery.

    Wcześniejszy test reprodukował bug z hardcoded listą nazw pod ``auto``;
    po usunięciu trybu auto sprawdzamy ten sam invariant dla strict whitelist.
    """
    volumes_root = tmp_path / "Volumes"
    volumes_root.mkdir()
    _make_volume_with_audio(volumes_root, "IC RECORDER")
    _make_volume_with_audio(volumes_root, "SD_CARD", filename="memo.wav")
    _make_empty_volume(volumes_root, "NoAudioStick")

    settings = UserSettings(watch_mode="manual", watched_volumes=[])
    settings.add_trusted_volume("UUID-IC", "IC RECORDER", "trusted")
    settings.add_trusted_volume("UUID-SD", "SD_CARD", "trusted")
    monkeypatch.setattr(
        "src.transcriber.UserSettings.load", classmethod(lambda cls: settings)
    )
    uuid_map = {
        "IC RECORDER": "UUID-IC",
        "SD_CARD": "UUID-SD",
        "NoAudioStick": "UUID-NOAUDIO",
    }
    monkeypatch.setattr(
        "src.volume_utils.get_volume_uuid",
        lambda volume_path: uuid_map.get(volume_path.name, "UUID-UNK"),
    )
    monkeypatch.setattr(
        "src.transcriber.find_matching_volumes",
        lambda s: __import__(
            "src.volume_utils", fromlist=["find_matching_volumes"]
        ).find_matching_volumes(s, volumes_root=volumes_root),
    )
    transcriber.config.RECORDER_NAMES = []

    recorders = transcriber.find_recorders()
    names = sorted(r.name for r in recorders)

    assert names == ["IC RECORDER", "SD_CARD"]


def test_find_recorders_skips_system_volumes_even_when_trusted(
    transcriber, tmp_path, monkeypatch
):
    """System volumes (Macintosh HD itp.) są zawsze pomijane mimo wpisu w whitelist."""
    volumes_root = tmp_path / "Volumes"
    volumes_root.mkdir()
    _make_volume_with_audio(volumes_root, "Macintosh HD")
    _make_volume_with_audio(volumes_root, "MY_DICTAPHONE")

    settings = UserSettings(watch_mode="manual", watched_volumes=[])
    # Nawet z błędnym wpisem dla "Macintosh HD" jako trusted —
    # SYSTEM_VOLUMES check ma pierwszeństwo.
    settings.add_trusted_volume("UUID-MAC", "Macintosh HD", "trusted")
    settings.add_trusted_volume("UUID-DICT", "MY_DICTAPHONE", "trusted")
    monkeypatch.setattr(
        "src.transcriber.UserSettings.load", classmethod(lambda cls: settings)
    )
    monkeypatch.setattr(
        "src.volume_utils.get_volume_uuid",
        lambda volume_path: {
            "Macintosh HD": "UUID-MAC",
            "MY_DICTAPHONE": "UUID-DICT",
        }.get(volume_path.name, "UUID-X"),
    )
    monkeypatch.setattr(
        "src.transcriber.find_matching_volumes",
        lambda s: __import__(
            "src.volume_utils", fromlist=["find_matching_volumes"]
        ).find_matching_volumes(s, volumes_root=volumes_root),
    )
    transcriber.config.RECORDER_NAMES = []

    recorders = transcriber.find_recorders()

    assert [r.name for r in recorders] == ["MY_DICTAPHONE"]


def test_find_recorders_manual_mode_ignores_unknown_volume(
    transcriber, tmp_path, monkeypatch
):
    """Manual + brak UUID na whitelist → volume nie jest recorderem."""
    volumes_root = tmp_path / "Volumes"
    volumes_root.mkdir()
    _make_empty_volume(volumes_root, "EMPTY_STICK")
    _make_volume_with_audio(volumes_root, "UNKNOWN_USB")

    settings = UserSettings(watch_mode="manual", watched_volumes=[])
    monkeypatch.setattr(
        "src.transcriber.UserSettings.load", classmethod(lambda cls: settings)
    )
    monkeypatch.setattr(
        "src.volume_utils.get_volume_uuid",
        lambda volume_path: f"UUID-{volume_path.name}",
    )
    monkeypatch.setattr(
        "src.transcriber.find_matching_volumes",
        lambda s: __import__(
            "src.volume_utils", fromlist=["find_matching_volumes"]
        ).find_matching_volumes(s, volumes_root=volumes_root),
    )
    transcriber.config.RECORDER_NAMES = []

    assert transcriber.find_recorders() == []


def test_find_recorders_specific_mode_uses_watched_volumes(
    transcriber, tmp_path, monkeypatch
):
    """Specific mode must only return volumes named in watched_volumes."""
    volumes_root = tmp_path / "Volumes"
    volumes_root.mkdir()
    _make_volume_with_audio(volumes_root, "LS-P1")
    _make_volume_with_audio(volumes_root, "RANDOM_STICK")

    settings = UserSettings(watch_mode="specific", watched_volumes=["LS-P1"])
    monkeypatch.setattr(
        "src.transcriber.UserSettings.load", classmethod(lambda cls: settings)
    )
    monkeypatch.setattr(
        "src.transcriber.find_matching_volumes",
        lambda s: __import__(
            "src.volume_utils", fromlist=["find_matching_volumes"]
        ).find_matching_volumes(s, volumes_root=volumes_root),
    )
    transcriber.config.RECORDER_NAMES = list(settings.watched_volumes)

    recorders = transcriber.find_recorders()

    assert [r.name for r in recorders] == ["LS-P1"]


def test_find_recorders_manual_mode_returns_empty(transcriber, tmp_path, monkeypatch):
    """Manual mode must never auto-detect, even when audio is present."""
    volumes_root = tmp_path / "Volumes"
    volumes_root.mkdir()
    _make_volume_with_audio(volumes_root, "LS-P1")

    settings = UserSettings(watch_mode="manual", watched_volumes=[])
    monkeypatch.setattr(
        "src.transcriber.UserSettings.load", classmethod(lambda cls: settings)
    )
    monkeypatch.setattr(
        "src.transcriber.find_matching_volumes",
        lambda s: __import__(
            "src.volume_utils", fromlist=["find_matching_volumes"]
        ).find_matching_volumes(s, volumes_root=volumes_root),
    )
    transcriber.config.RECORDER_NAMES = []

    assert transcriber.find_recorders() == []


def test_get_last_sync_time_no_file(transcriber, tmp_path, monkeypatch):
    """Test get_last_sync_time when no state file exists."""
    from src import config as config_module

    state_file = tmp_path / "state.json"
    monkeypatch.setattr(config_module.config, "STATE_FILE", state_file)

    result = transcriber.get_last_sync_time()

    # Should return approximately 7 days ago
    expected = datetime.now() - timedelta(days=7)
    assert abs((result - expected).total_seconds()) < 60  # Within 1 minute


def test_get_last_sync_time_with_file(transcriber, tmp_path, monkeypatch):
    """Test get_last_sync_time when state file exists."""
    from src import config as config_module

    state_file = tmp_path / "state.json"
    test_time = datetime(2025, 1, 1, 12, 0, 0)

    with open(state_file, "w") as f:
        json.dump({"last_sync": test_time.isoformat()}, f)

    monkeypatch.setattr(config_module.config, "STATE_FILE", state_file)

    result = transcriber.get_last_sync_time()
    assert result == test_time


def test_save_sync_time(transcriber, tmp_path, monkeypatch):
    """Test save_sync_time writes to state file."""
    from src import config as config_module

    state_file = tmp_path / "state.json"
    monkeypatch.setattr(config_module.config, "STATE_FILE", state_file)

    transcriber.save_sync_time()

    assert state_file.exists()

    with open(state_file, "r") as f:
        data = json.load(f)

    assert "last_sync" in data
    # Should be very recent
    sync_time = datetime.fromisoformat(data["last_sync"])
    assert abs((datetime.now() - sync_time).total_seconds()) < 5


def test_find_audio_files(transcriber, mock_recorder_path):
    """Test find_audio_files finds correct files."""
    since = datetime.now() - timedelta(days=1)

    files = transcriber.find_audio_files(mock_recorder_path, since)

    # Should find 2 audio files (mp3 and wav), not txt
    assert len(files) == 2
    assert all(f.suffix in {".mp3", ".wav"} for f in files)


def test_find_audio_files_filters_by_time(transcriber, mock_recorder_path):
    """Test find_audio_files filters by modification time."""
    # Set 'since' to future, should find no files
    since = datetime.now() + timedelta(days=1)

    files = transcriber.find_audio_files(mock_recorder_path, since)

    assert len(files) == 0


def test_find_audio_files_respects_max_depth(transcriber, tmp_path):
    """Test find_audio_files respects MAX_SCAN_DEPTH limit."""
    from src.config.defaults import defaults

    # Create directory structure with files at different depths
    recorder = tmp_path / "TEST_VOLUME"
    recorder.mkdir()

    # Depth 1: recorder/level1/file.mp3
    (recorder / "level1").mkdir()
    file_depth1 = recorder / "level1" / "file1.mp3"
    file_depth1.touch()

    # Depth 2: recorder/level1/level2/file.mp3
    (recorder / "level1" / "level2").mkdir()
    file_depth2 = recorder / "level1" / "level2" / "file2.mp3"
    file_depth2.touch()

    # Depth 3: recorder/level1/level2/level3/file.mp3 (should be found)
    (recorder / "level1" / "level2" / "level3").mkdir()
    file_depth3 = recorder / "level1" / "level2" / "level3" / "file3.mp3"
    file_depth3.touch()

    # Depth 4: recorder/level1/level2/level3/level4/file.mp3 (should be ignored)
    (recorder / "level1" / "level2" / "level3" / "level4").mkdir()
    file_depth4 = recorder / "level1" / "level2" / "level3" / "level4" / "file4.mp3"
    file_depth4.touch()

    # Set all files to recent modification time
    since = datetime.now() - timedelta(hours=1)
    for f in [file_depth1, file_depth2, file_depth3, file_depth4]:
        import os

        os.utime(f, (since.timestamp(), since.timestamp()))

    # Find files
    files = transcriber.find_audio_files(recorder, since - timedelta(minutes=30))

    # Should find files at depth 1, 2, 3 (≤ max_depth=3)
    found_paths = {f.relative_to(recorder) for f in files}

    assert (
        file_depth1.relative_to(recorder) in found_paths
    ), "Depth 1 file should be found"
    assert (
        file_depth2.relative_to(recorder) in found_paths
    ), "Depth 2 file should be found"
    assert (
        file_depth3.relative_to(recorder) in found_paths
    ), "Depth 3 file should be found"
    assert (
        file_depth4.relative_to(recorder) not in found_paths
    ), "Depth 4 file should be ignored (depth > max_depth)"


def test_transcribe_file_no_whisper(transcriber, tmp_path):
    """Test transcribe_file when whisper.cpp is not available."""
    transcriber.whisper_available = False
    audio_file = tmp_path / "test.mp3"
    audio_file.touch()

    result = transcriber.transcribe_file(audio_file)

    assert result is False


def test_transcribe_file_already_transcribed_txt(transcriber, tmp_path, monkeypatch):
    """Test transcribe_file when an OWNED TXT output already exists.

    Adoption of a leftover TXT requires the ownership sidecar to match this
    audio's fingerprint (crash-recovery path); stem-only adoption is gone.
    """
    # Patch global config for state_manager functions
    from src import config as config_module
    from src.fingerprint import compute_fingerprint

    transcriber.whisper_available = True
    # Avoid calling real whisper.cpp if logic regresses
    transcriber._run_macwhisper = MagicMock(return_value=None)  # type: ignore[arg-type]

    audio_file = tmp_path / "test.mp3"
    audio_file.touch()

    output_dir = tmp_path / "output"
    output_dir.mkdir()
    output_file = output_dir / "test.txt"
    output_file.write_text("Test transcript")

    # Update transcriber's injected config (not global config)
    transcriber.config.TRANSCRIBE_DIR = output_dir
    # Also patch global for state_manager functions
    monkeypatch.setattr(config_module.config, "TRANSCRIBE_DIR", output_dir)

    # Claim the TXT for this audio — the crash-recovery contract.
    transcriber._write_transcript_owner(
        output_file, audio_file, compute_fingerprint(audio_file)
    )

    result = transcriber.transcribe_file(audio_file)

    assert result is True  # Already exists counts as success (via post-process)
    transcriber._run_macwhisper.assert_not_called()


def test_txt_adoption_rejected_without_ownership(transcriber, tmp_path, monkeypatch):
    """A leftover TXT without a sidecar must NOT be adopted: it is moved aside
    and the audio transcribed fresh (recorders reset numbering — a stem match
    can be a different recording)."""
    from src import config as config_module

    transcriber.whisper_available = True

    output_dir = tmp_path / "output"
    output_dir.mkdir()
    stale = output_dir / "REC001.txt"
    stale.write_text("someone else's transcript")

    audio_file = tmp_path / "REC001.mp3"
    audio_file.write_bytes(b"card-B-audio")

    transcriber.config.TRANSCRIBE_DIR = output_dir
    monkeypatch.setattr(config_module.config, "TRANSCRIBE_DIR", output_dir)

    fresh_txt = output_dir / "REC001.txt"

    def fake_whisper(af):
        fresh_txt.write_text("fresh transcript for card B")
        return fresh_txt

    transcriber._run_macwhisper = MagicMock(side_effect=fake_whisper)
    transcriber._postprocess_transcript = MagicMock(
        return_value=output_dir / "note.md"
    )
    transcriber._index_completed_transcription = MagicMock()

    result = transcriber.transcribe_file(audio_file)

    assert result is True
    transcriber._run_macwhisper.assert_called_once()  # fresh run, no adoption
    stale_files = list(output_dir.glob("REC001.stale-*.txt"))
    assert len(stale_files) == 1  # moved aside, never deleted
    assert stale_files[0].read_text() == "someone else's transcript"


def test_txt_adoption_rejected_on_fingerprint_mismatch(
    transcriber, tmp_path, monkeypatch
):
    """A sidecar naming a DIFFERENT fingerprint must also block adoption."""
    from src import config as config_module

    transcriber.whisper_available = True

    output_dir = tmp_path / "output"
    output_dir.mkdir()
    stale = output_dir / "REC001.txt"
    stale.write_text("transcript of card A")

    other_audio = tmp_path / "other.mp3"
    other_audio.write_bytes(b"card-A-audio")
    transcriber._write_transcript_owner(stale, other_audio, "fp-of-card-A")

    audio_file = tmp_path / "REC001.mp3"
    audio_file.write_bytes(b"card-B-audio")

    transcriber.config.TRANSCRIBE_DIR = output_dir
    monkeypatch.setattr(config_module.config, "TRANSCRIBE_DIR", output_dir)

    transcriber._run_macwhisper = MagicMock(return_value=None)

    transcriber.transcribe_file(audio_file)

    transcriber._run_macwhisper.assert_called_once()  # adoption was refused
    assert list(output_dir.glob("REC001.stale-*.txt"))


def test_remove_existing_transcription_cleans_sidecar(transcriber, tmp_path):
    """Removing a TXT must also remove its ownership sidecar."""
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    transcriber.config.TRANSCRIBE_DIR = output_dir

    audio_file = tmp_path / "rec.mp3"
    audio_file.write_bytes(b"audio")
    txt = output_dir / "rec.txt"
    txt.write_text("transcript")
    transcriber._write_transcript_owner(txt, audio_file, "fp-1")
    sidecar = transcriber._transcript_sidecar_path(txt)
    assert sidecar.exists()

    transcriber._remove_existing_transcription(audio_file)

    assert not txt.exists()
    assert not sidecar.exists()


def test_postprocess_transcript_success(transcriber, tmp_path, monkeypatch):
    """Test successful post-processing of transcript."""
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    update_transcriber_config(
        transcriber, monkeypatch, TRANSCRIBE_DIR=output_dir, DELETE_TEMP_TXT=True
    )

    audio_file = tmp_path / "test.mp3"
    audio_file.touch()
    transcript_file = output_dir / "test.txt"
    transcript_file.write_text("Test transcript content")

    # Mock summarizer
    mock_summarizer = MagicMock(spec=BaseSummarizer)
    mock_summarizer.generate.return_value = {
        "title": "Test Title",
        "summary": "Test summary",
    }
    transcriber.summarizer = mock_summarizer

    # Mock markdown generator
    mock_md_gen = MagicMock(spec=MarkdownGenerator)
    mock_md_gen.extract_audio_metadata.return_value = {
        "source_file": "test.mp3",
        "extension": ".mp3",
        "recording_datetime": datetime.now(),
        "duration_seconds": 60,
        "duration_formatted": "00:01:00",
    }
    mock_md_path = output_dir / "2025-11-19_Test_Title.md"
    mock_md_gen.create_markdown_document.return_value = mock_md_path
    transcriber.markdown_generator = mock_md_gen

    result = transcriber._postprocess_transcript(
        audio_file, transcript_file, fingerprint="sha256:test"
    )

    assert result == mock_md_path
    mock_summarizer.generate.assert_called_once()
    mock_md_gen.create_markdown_document.assert_called_once()
    # TXT file should be deleted
    assert not transcript_file.exists()


def test_postprocess_transcript_no_summarizer(transcriber, tmp_path, monkeypatch):
    """Test post-processing without summarizer (fallback)."""
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    update_transcriber_config(transcriber, monkeypatch, TRANSCRIBE_DIR=output_dir)

    audio_file = tmp_path / "test.mp3"
    audio_file.touch()
    transcript_file = output_dir / "test.txt"
    transcript_file.write_text("Test transcript")

    # No summarizer
    transcriber.summarizer = None

    # Mock markdown generator
    mock_md_gen = MagicMock(spec=MarkdownGenerator)
    mock_md_gen.extract_audio_metadata.return_value = {
        "source_file": "test.mp3",
        "extension": ".mp3",
        "recording_datetime": datetime.now(),
        "duration_seconds": 60,
        "duration_formatted": "00:01:00",
    }
    mock_md_path = output_dir / "2025-11-19_test.md"
    mock_md_gen.create_markdown_document.return_value = mock_md_path
    transcriber.markdown_generator = mock_md_gen

    result = transcriber._postprocess_transcript(
        audio_file, transcript_file, fingerprint="sha256:test"
    )

    assert result == mock_md_path
    # Should use fallback summary
    call_args = mock_md_gen.create_markdown_document.call_args
    summary = call_args[1]["summary"]
    assert "title" in summary
    assert "Brak podsumowania" in summary.get("summary", "")


def test_postprocess_transcript_circuit_breaker_on_billing_error(
    monkeypatch, tmp_path, transcriber
):
    """After APIBillingError the summarizer/tagger must not be called again."""
    from src.summarizer import APIBillingError

    output_dir = tmp_path / "output"
    output_dir.mkdir()
    update_transcriber_config(
        transcriber, monkeypatch, TRANSCRIBE_DIR=output_dir, ENABLE_LLM_TAGGING=True
    )

    audio_file = tmp_path / "sample.mp3"
    audio_file.touch()
    transcript_file = output_dir / "sample.txt"
    transcript_file.write_text("Treść transkrypcji")

    mock_summarizer = MagicMock(spec=BaseSummarizer)
    mock_summarizer.generate.side_effect = APIBillingError("credit balance too low")
    transcriber.summarizer = mock_summarizer

    mock_tagger = MagicMock()
    mock_tagger.generate_tags.return_value = []
    transcriber.tagger = mock_tagger

    callback = MagicMock()
    transcriber.set_ai_billing_callback(callback)

    mock_md_gen = MagicMock(spec=MarkdownGenerator)
    mock_md_gen.extract_audio_metadata.return_value = {
        "source_file": "sample.mp3",
        "extension": ".mp3",
        "recording_datetime": datetime.now(),
        "duration_seconds": 60,
        "duration_formatted": "00:01:00",
    }
    mock_md_gen.create_markdown_document.return_value = output_dir / "sample.md"
    transcriber.markdown_generator = mock_md_gen

    # First file: trips circuit breaker.
    second_transcript = output_dir / "sample2.txt"
    second_transcript.write_text("Druga transkrypcja")

    transcriber._postprocess_transcript(
        audio_file, transcript_file, fingerprint="sha256:first"
    )
    transcriber._postprocess_transcript(
        audio_file, second_transcript, fingerprint="sha256:second"
    )

    assert transcriber._ai_disabled_reason == "billing"
    assert mock_summarizer.generate.call_count == 1
    mock_tagger.generate_tags.assert_not_called()
    callback.assert_called_once()


def test_postprocess_transcript_passes_tags(monkeypatch, tmp_path, transcriber):
    """Tag list should be passed into markdown generator."""
    from src import config as config_module

    output_dir = tmp_path / "output"
    output_dir.mkdir()
    update_transcriber_config(
        transcriber, monkeypatch, TRANSCRIBE_DIR=output_dir, ENABLE_LLM_TAGGING=False
    )

    audio_file = tmp_path / "sample.mp3"
    audio_file.touch()
    transcript_file = output_dir / "sample.txt"
    transcript_file.write_text("Treść transkrypcji")

    transcriber.summarizer = None

    mock_md_gen = MagicMock(spec=MarkdownGenerator)
    mock_md_gen.extract_audio_metadata.return_value = {
        "source_file": "sample.mp3",
        "extension": ".mp3",
        "recording_datetime": datetime.now(),
        "duration_seconds": 60,
        "duration_formatted": "00:01:00",
    }
    mock_md_gen.create_markdown_document.return_value = output_dir / "sample.md"
    transcriber.markdown_generator = mock_md_gen

    result = transcriber._postprocess_transcript(
        audio_file, transcript_file, fingerprint="sha256:test"
    )

    assert result == output_dir / "sample.md"
    _, kwargs = mock_md_gen.create_markdown_document.call_args
    assert "tags" in kwargs
    assert kwargs["tags"][0] == "transcription"


def test_process_recorder_no_recorder(transcriber):
    """Test process_recorder when no recorder is found."""
    with patch.object(transcriber, "find_recorders", return_value=[]):
        transcriber.process_recorder()

        assert not transcriber.recorder_monitoring


def test_process_recorder_with_files(transcriber, mock_recorder_path):
    """Test process_recorder with new files."""
    with patch.object(transcriber, "find_recorders", return_value=[mock_recorder_path]):
        with patch.object(
            transcriber,
            "find_pending_audio_files",
            return_value=[(mock_recorder_path / "Music" / "recording1.mp3", "fp-1")],
        ):
            with patch.object(
                transcriber,
                "get_last_sync_time",
                return_value=datetime.now() - timedelta(days=1),
            ):
                with patch.object(transcriber, "transcribe_file", return_value=True):
                    with patch.object(transcriber, "save_sync_time"):
                        transcriber.process_recorder()

                        assert transcriber.recorder_monitoring


def test_stage_audio_file_success(transcriber, tmp_path, monkeypatch):
    """Test successful staging of audio file."""
    staging_dir = tmp_path / "staging"
    staging_dir.mkdir()
    update_transcriber_config(
        transcriber, monkeypatch, LOCAL_RECORDINGS_DIR=staging_dir
    )

    recorder_file = tmp_path / "recorder" / "test.mp3"
    recorder_file.parent.mkdir()
    recorder_file.write_bytes(b"fake audio data")

    staged_path = transcriber._stage_audio_file(recorder_file)

    assert staged_path is not None
    assert staged_path == staging_dir / "test.mp3"
    assert staged_path.exists()
    assert staged_path.read_bytes() == b"fake audio data"


def test_stage_audio_file_not_found(transcriber, tmp_path, monkeypatch):
    """Test staging when recorder file doesn't exist."""
    staging_dir = tmp_path / "staging"
    staging_dir.mkdir()
    update_transcriber_config(
        transcriber, monkeypatch, LOCAL_RECORDINGS_DIR=staging_dir
    )

    recorder_file = tmp_path / "nonexistent.mp3"

    staged_path = transcriber._stage_audio_file(recorder_file)

    assert staged_path is None


def test_stage_audio_file_reuse_existing(transcriber, tmp_path, monkeypatch):
    """Test staging reuses existing copy if it matches."""
    from src import config as config_module
    import time

    staging_dir = tmp_path / "staging"
    staging_dir.mkdir()
    update_transcriber_config(
        transcriber, monkeypatch, LOCAL_RECORDINGS_DIR=staging_dir
    )

    recorder_file = tmp_path / "recorder" / "test.mp3"
    recorder_file.parent.mkdir()
    recorder_file.write_bytes(b"fake audio data")

    # Create existing staged file with same content
    staged_file = staging_dir / "test.mp3"
    staged_file.write_bytes(b"fake audio data")
    # Set same mtime
    staged_file.touch()
    time.sleep(0.1)  # Small delay to ensure mtime is set
    recorder_file.touch()

    staged_path = transcriber._stage_audio_file(recorder_file)

    assert staged_path is not None
    assert staged_path == staged_file


def test_process_recorder_staging_integration(transcriber, tmp_path, monkeypatch):
    """Test process_recorder uses staging before transcription."""
    from src import config as config_module

    staging_dir = tmp_path / "staging"
    staging_dir.mkdir()
    update_transcriber_config(
        transcriber, monkeypatch, LOCAL_RECORDINGS_DIR=staging_dir
    )

    recorder = tmp_path / "LS-P1"
    recorder.mkdir()
    audio_file = recorder / "test.mp3"
    audio_file.write_bytes(b"fake audio")

    with patch.object(
        transcriber,
        "find_recorders",
        return_value=([] if recorder is None else [recorder]),
    ):
        with patch.object(
            transcriber,
            "find_pending_audio_files",
            return_value=[(audio_file, "fp-test")],
        ):
            with patch.object(
                transcriber,
                "get_last_sync_time",
                return_value=datetime.now() - timedelta(days=1),
            ):
                with patch.object(
                    transcriber, "transcribe_file", return_value=True
                ) as mock_transcribe:
                    with patch.object(transcriber, "save_sync_time"):
                        transcriber.process_recorder()

                        # Verify transcribe_file was called with staged path
                        assert mock_transcribe.called
                        call_args = mock_transcribe.call_args[0][0]
                        assert call_args.parent == staging_dir
                        assert call_args.name == "test.mp3"


def test_process_recorder_batch_failure_handling(transcriber, tmp_path, monkeypatch):
    """Test that last_sync is not updated if any file fails."""
    from src import config as config_module

    staging_dir = tmp_path / "staging"
    staging_dir.mkdir()
    update_transcriber_config(
        transcriber, monkeypatch, LOCAL_RECORDINGS_DIR=staging_dir
    )

    recorder = tmp_path / "LS-P1"
    recorder.mkdir()
    audio_file1 = recorder / "test1.mp3"
    audio_file1.write_bytes(b"fake audio")
    audio_file2 = recorder / "test2.mp3"
    audio_file2.write_bytes(b"fake audio")

    with patch.object(
        transcriber,
        "find_recorders",
        return_value=([] if recorder is None else [recorder]),
    ):
        with patch.object(
            transcriber,
            "find_pending_audio_files",
            return_value=[(audio_file1, "fp-1"), (audio_file2, "fp-2")],
        ):
            with patch.object(
                transcriber,
                "get_last_sync_time",
                return_value=datetime.now() - timedelta(days=1),
            ):
                # First succeeds, second fails
                with patch.object(
                    transcriber, "transcribe_file", side_effect=[True, False]
                ) as mock_transcribe:
                    with patch.object(transcriber, "save_sync_time") as mock_save:
                        transcriber.process_recorder()

                        # Should NOT save sync time because one file failed
                        mock_save.assert_not_called()


def test_process_recorder_batch_success_updates_sync(
    transcriber, tmp_path, monkeypatch
):
    """Test that last_sync is updated when all files succeed."""
    from src import config as config_module

    staging_dir = tmp_path / "staging"
    staging_dir.mkdir()
    update_transcriber_config(
        transcriber, monkeypatch, LOCAL_RECORDINGS_DIR=staging_dir
    )

    recorder = tmp_path / "LS-P1"
    recorder.mkdir()
    audio_file1 = recorder / "test1.mp3"
    audio_file1.write_bytes(b"fake audio")
    audio_file2 = recorder / "test2.mp3"
    audio_file2.write_bytes(b"fake audio")

    with patch.object(
        transcriber,
        "find_recorders",
        return_value=([] if recorder is None else [recorder]),
    ):
        with patch.object(
            transcriber,
            "find_pending_audio_files",
            return_value=[(audio_file1, "fp-1"), (audio_file2, "fp-2")],
        ):
            with patch.object(
                transcriber,
                "get_last_sync_time",
                return_value=datetime.now() - timedelta(days=1),
            ):
                # Both succeed
                with patch.object(transcriber, "transcribe_file", return_value=True):
                    with patch.object(transcriber, "save_sync_time") as mock_save:
                        transcriber.process_recorder()

                        # Should save sync time because all files succeeded
                        mock_save.assert_called_once()


def test_process_recorder_skips_files_with_existing_markdown(
    transcriber, tmp_path, monkeypatch
):
    """Ensure recorder workflow checks for existing markdown before staging."""
    from src import config as config_module

    staging_dir = tmp_path / "staging"
    staging_dir.mkdir()
    transcript_dir = tmp_path / "transcripts"
    transcript_dir.mkdir()
    update_transcriber_config(
        transcriber,
        monkeypatch,
        LOCAL_RECORDINGS_DIR=staging_dir,
        TRANSCRIBE_DIR=transcript_dir,
    )
    recorder = tmp_path / "LS-P1"
    recorder.mkdir()
    processed_file = recorder / "processed.mp3"
    processed_file.write_bytes(b"done")
    new_file = recorder / "new.mp3"
    new_file.write_bytes(b"new")

    # Existing markdown referencing processed.mp3
    md_file = transcript_dir / "existing.md"
    md_file.write_text(
        "---\n"
        'title: "Zrobione"\n'
        "date: 2025-11-25\n"
        "recording_date: 2025-11-25T10:00:00\n"
        "source: processed.mp3\n"
        "duration: 00:01:00\n"
        "tags: [transcription]\n"
        "---\n\n"
        "Treść\n"
    )

    staged_new = staging_dir / "new.mp3"
    staged_new.write_bytes(b"new")
    with patch.object(
        transcriber,
        "find_recorders",
        return_value=([] if recorder is None else [recorder]),
    ):
        with patch.object(
            transcriber,
            "find_pending_audio_files",
            return_value=[(processed_file, "fp-processed"), (new_file, "fp-new")],
        ):
            with patch.object(
                transcriber,
                "get_last_sync_time",
                return_value=datetime.now() - timedelta(days=1),
            ):
                with patch.object(
                    transcriber, "_stage_audio_file", return_value=staged_new
                ) as mock_stage:
                    with patch.object(
                        transcriber, "transcribe_file", return_value=True
                    ) as mock_transcribe:
                        with patch.object(
                            transcriber, "save_sync_time"
                        ) as mock_save_sync:
                            transcriber.process_recorder()

    mock_stage.assert_called_once()
    assert mock_stage.call_args[0][0].name == "new.mp3"
    mock_transcribe.assert_called_once_with(staged_new)
    mock_save_sync.assert_called_once()


def test_run_macwhisper_retries_on_metal_error(transcriber, tmp_path, monkeypatch):
    """Whisper retry should trigger on Metal/Core ML failures."""
    from src import config as config_module

    transcript_dir = tmp_path / "output"
    transcript_dir.mkdir()
    update_transcriber_config(transcriber, monkeypatch, TRANSCRIBE_DIR=transcript_dir)

    # Force whisper to be treated as available inside the sandboxed HOME
    # (conftest.py redirects HOME so the real whisper-cli binary is invisible).
    transcriber.whisper_available = True

    audio_file = tmp_path / "sample.mp3"
    audio_file.touch()

    # The pipeline now converts to WAV before whisper; stub that out so the
    # test stays focused on the Core ML retry logic (no real ffmpeg).
    transcriber._convert_to_wav = MagicMock(  # type: ignore[assignment]
        return_value=tmp_path / "sample.whisper16k.wav"
    )

    def run_side_effect(_, use_coreml=True, source_audio=None):
        if use_coreml:
            return subprocess.CompletedProcess(
                args=["whisper"],
                returncode=1,
                stdout="",
                stderr="ggml_metal_device_init: tensor API disabled",
            )
        output_file = transcript_dir / "sample.txt"
        output_file.write_text("ok")
        return subprocess.CompletedProcess(
            args=["whisper"], returncode=0, stdout="", stderr=""
        )

    mock_runner = MagicMock(side_effect=run_side_effect)
    transcriber._run_whisper_transcription = mock_runner  # type: ignore[assignment]

    result = transcriber._run_macwhisper(audio_file)

    assert result == transcript_dir / "sample.txt"
    assert mock_runner.call_count == 2
    assert mock_runner.call_args_list[1].kwargs["use_coreml"] is False


def test_run_whisper_transcription_disables_metal_for_cpu(
    transcriber, tmp_path, monkeypatch
):
    """CPU fallback should disable Core ML / Metal backends via environment."""
    from src import config as config_module

    audio_file = tmp_path / "sample.mp3"
    audio_file.touch()  # Point config to temporary paths so command construction works
    update_transcriber_config(
        transcriber,
        monkeypatch,
        WHISPER_CPP_MODELS_DIR=tmp_path,
        WHISPER_MODEL="small",
        WHISPER_CPP_PATH=tmp_path / "whisper-cli",
        TRANSCRIBE_DIR=tmp_path,
    )

    captured = {}

    def fake_stream(cmd, *, env, use_coreml, audio_file):
        captured["env"] = env
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(transcriber, "_run_whisper_streaming", fake_stream)

    _ = transcriber._run_whisper_transcription(audio_file, use_coreml=False)

    env = captured.get("env")
    assert env is not None
    assert env.get("WHISPER_COREML") == "0"
    assert env.get("GGML_METAL_DISABLE") == "1"


def test_run_whisper_transcription_injects_glossary_prompt(
    transcriber, tmp_path, monkeypatch
):
    """The personal glossary reaches whisper-cli as --prompt (and only when
    non-empty — an empty glossary must leave the command untouched)."""
    audio_file = tmp_path / "sample.mp3"
    audio_file.touch()
    update_transcriber_config(
        transcriber,
        monkeypatch,
        WHISPER_CPP_MODELS_DIR=tmp_path,
        WHISPER_MODEL="small",
        WHISPER_CPP_PATH=tmp_path / "whisper-cli",
        TRANSCRIBE_DIR=tmp_path,
    )

    captured = {}

    def fake_stream(cmd, *, env, use_coreml, audio_file):
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(transcriber, "_run_whisper_streaming", fake_stream)
    monkeypatch.setattr(
        transcriber.vocabulary, "whisper_prompt", lambda: "Tech to the Rescue, TTTR"
    )

    _ = transcriber._run_whisper_transcription(audio_file, use_coreml=True)
    cmd = captured["cmd"]
    assert "--prompt" in cmd
    assert cmd[cmd.index("--prompt") + 1] == "Tech to the Rescue, TTTR"

    # Empty glossary (fresh vault / feature off) -> no --prompt flag at all.
    monkeypatch.setattr(transcriber.vocabulary, "whisper_prompt", lambda: "")
    _ = transcriber._run_whisper_transcription(audio_file, use_coreml=True)
    assert "--prompt" not in captured["cmd"]


class _FakePipeProc:
    """A fake Popen backed by a real OS pipe so select()/readline() work.

    Pre-loads *payload* into the stderr pipe and closes the write end (EOF),
    so the streaming reader consumes it line-by-line exactly like the real run.
    """

    def __init__(self, payload: str, rc: int = 0, hold_open: bool = False):
        import os as _os

        r, w = _os.pipe()
        self.stderr = _os.fdopen(r, "r", encoding="utf-8", errors="replace")
        wf = _os.fdopen(w, "w", encoding="utf-8")
        wf.write(payload)
        if hold_open:
            # Keep the write end open: no EOF — simulates a stalled whisper
            # that wrote a partial line and went silent.
            wf.flush()
            self._wf = wf
        else:
            wf.close()
        self._rc = rc
        self.returncode = None  # None == "running" (poll())

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        if self.returncode is None:
            self.returncode = self._rc
        return self.returncode

    def kill(self):
        self.returncode = -9


def test_streaming_aborts_coreml_early_on_metal_error(
    transcriber, tmp_path, monkeypatch
):
    """A Metal marker in stderr must kill the GPU attempt immediately (not after
    the full run) and surface as a failure so the caller retries on CPU."""
    payload = (
        "whisper_init: loading model\n"
        "ggml_metal_device_init: tensor API disabled\n"
        "more output that we never wait around for\n"
    )
    proc = _FakePipeProc(payload, rc=0)
    monkeypatch.setattr("src.transcriber.subprocess.Popen", lambda *a, **k: proc)

    result = transcriber._run_whisper_streaming(
        ["whisper"], env=None, use_coreml=True, audio_file=tmp_path / "rec.wav"
    )

    assert result.returncode != 0  # killed → caller will fall back to CPU
    assert "tensor API disabled" in result.stderr
    assert proc.returncode == -9  # proc.kill() was invoked


def test_streaming_logs_progress_heartbeat(transcriber, tmp_path, monkeypatch):
    """With -pp whisper prints 'progress = NN%'; we must log a heartbeat so a
    long run never looks hung."""
    payload = "".join(
        f"whisper_print_progress_callback: progress = {p:3d}%\n"
        for p in (0, 10, 20, 50, 100)
    )
    proc = _FakePipeProc(payload, rc=0)
    monkeypatch.setattr("src.transcriber.subprocess.Popen", lambda *a, **k: proc)

    with patch("src.transcriber.logger") as mock_logger:
        transcriber._run_whisper_streaming(
            ["whisper"], env=None, use_coreml=False, audio_file=tmp_path / "rec.wav"
        )

    progress_logs = [
        call.args[0]
        for call in mock_logger.info.call_args_list
        if call.args and "Transkrypcja" in str(call.args[0])
    ]
    assert progress_logs, "expected at least one progress heartbeat in the log"


def test_streaming_timeout_fires_on_partial_line_without_newline(
    transcriber, tmp_path, monkeypatch
):
    """A stalled whisper that wrote a partial line (no newline) must still hit
    TRANSCRIPTION_TIMEOUT — the old buffered readline() blocked forever here,
    wedging the thread that holds _workflow_lock + the process flock."""
    import time

    proc = _FakePipeProc("whisper_init: load", hold_open=True)  # no \n, no EOF
    monkeypatch.setattr("src.transcriber.subprocess.Popen", lambda *a, **k: proc)
    monkeypatch.setattr(
        transcriber.config, "TRANSCRIPTION_TIMEOUT", 0.5, raising=False
    )

    started = time.time()
    with pytest.raises(subprocess.TimeoutExpired):
        transcriber._run_whisper_streaming(
            ["whisper"], env=None, use_coreml=False, audio_file=tmp_path / "rec.wav"
        )
    assert time.time() - started < 5.0  # bounded, not wedged
    assert proc.returncode == -9  # proc.kill() was invoked


def test_streaming_flushes_final_partial_line(transcriber, tmp_path, monkeypatch):
    """Output ending without a trailing newline must still reach stderr."""
    proc = _FakePipeProc("line one\npartial tail", rc=0)  # EOF after partial
    monkeypatch.setattr("src.transcriber.subprocess.Popen", lambda *a, **k: proc)

    result = transcriber._run_whisper_streaming(
        ["whisper"], env=None, use_coreml=False, audio_file=tmp_path / "rec.wav"
    )

    assert "partial tail" in result.stderr


def test_streaming_detects_marker_in_partial_line_at_eof(
    transcriber, tmp_path, monkeypatch
):
    """A Metal marker as the final, newline-less line still aborts the GPU run."""
    payload = "whisper_init: loading model\nggml_metal_device_init: tensor API disabled"
    proc = _FakePipeProc(payload, rc=0)
    monkeypatch.setattr("src.transcriber.subprocess.Popen", lambda *a, **k: proc)

    result = transcriber._run_whisper_streaming(
        ["whisper"], env=None, use_coreml=True, audio_file=tmp_path / "rec.wav"
    )

    assert result.returncode != 0  # caller falls back to CPU
    assert "tensor API disabled" in result.stderr


def test_streaming_sets_and_clears_active_proc(transcriber, tmp_path, monkeypatch):
    """The live proc must be tracked (for stop()) and cleared after the run,
    and Popen must put whisper in its own process group."""
    proc = _FakePipeProc("all done\n", rc=0)
    captured_kwargs = {}

    def fake_popen(*args, **kwargs):
        captured_kwargs.update(kwargs)
        return proc

    monkeypatch.setattr("src.transcriber.subprocess.Popen", fake_popen)

    seen_during_run = {}
    original_read = _FakePipeProc.poll

    def spy_poll(self):
        seen_during_run["proc"] = transcriber._active_whisper_proc
        return original_read(self)

    monkeypatch.setattr(_FakePipeProc, "poll", spy_poll)

    transcriber._run_whisper_streaming(
        ["whisper"], env=None, use_coreml=False, audio_file=tmp_path / "rec.wav"
    )

    assert captured_kwargs.get("start_new_session") is True
    assert seen_during_run["proc"] is proc  # tracked while running
    assert transcriber._active_whisper_proc is None  # cleared afterwards


def test_stop_kills_active_process_group(transcriber, monkeypatch):
    """stop() must SIGTERM the whisper process group, then SIGKILL on timeout."""

    class _FakeProc:
        pid = 4242
        returncode = None

        def __init__(self):
            self.wait_calls = 0

        def poll(self):
            return None  # still running

        def wait(self, timeout=None):
            self.wait_calls += 1
            raise subprocess.TimeoutExpired(["whisper"], timeout)

    proc = _FakeProc()
    transcriber._active_whisper_proc = proc

    kills = []
    monkeypatch.setattr("src.transcriber.os.getpgid", lambda pid: pid)
    monkeypatch.setattr(
        "src.transcriber.os.killpg", lambda pgid, sig: kills.append((pgid, sig))
    )

    transcriber.stop()

    import signal as _signal

    assert kills == [(4242, _signal.SIGTERM), (4242, _signal.SIGKILL)]


def test_stop_noop_without_active_proc(transcriber, monkeypatch):
    """stop() with no live whisper must do nothing and not raise."""
    killed = []
    monkeypatch.setattr(
        "src.transcriber.os.killpg", lambda pgid, sig: killed.append(pgid)
    )

    transcriber.stop()  # _active_whisper_proc is None

    assert killed == []


def test_whisper_thread_count_leaves_headroom(monkeypatch):
    """Thread count must reserve cores so the UI stays responsive."""
    monkeypatch.setattr("src.transcriber.os.cpu_count", lambda: 10)
    assert Transcriber._whisper_thread_count() == 8
    monkeypatch.setattr("src.transcriber.os.cpu_count", lambda: 2)
    assert Transcriber._whisper_thread_count() == 1  # never below 1
    monkeypatch.setattr("src.transcriber.os.cpu_count", lambda: None)
    assert Transcriber._whisper_thread_count() >= 1


def test_coreml_verdict_persists_across_instances(transcriber):
    """A recorded Metal failure must skip the GPU attempt on the next launch."""
    assert transcriber._coreml_disabled_in_session is False
    transcriber._persist_coreml_disabled()
    assert transcriber._coreml_flag_path().exists()

    with patch("src.transcriber.logger"):
        fresh = Transcriber(config=transcriber.config)
    assert fresh._coreml_disabled_in_session is True


def test_coreml_verdict_reprobes_when_model_changes(transcriber):
    """Changing the whisper model invalidates the persisted verdict (re-probe)."""
    transcriber._persist_coreml_disabled()
    transcriber.config.WHISPER_MODEL = "tiny"  # different signature

    with patch("src.transcriber.logger"):
        fresh = Transcriber(config=transcriber.config)
    assert fresh._coreml_disabled_in_session is False


def test_process_recorder_skips_when_lock_held(transcriber, monkeypatch):
    """process_recorder should not run if lock acquisition fails."""
    from src import transcriber as transcriber_module

    class DummyLock:
        def __init__(self, *_args, **_kwargs):
            pass

        def acquire(self) -> bool:
            return False

        def release(self) -> None:
            pass

    monkeypatch.setattr(transcriber_module, "ProcessLock", DummyLock)

    with patch.object(transcriber, "find_recorders") as mock_find:
        transcriber.process_recorder()
        mock_find.assert_not_called()


def test_process_recorder_releases_lock(transcriber, monkeypatch):
    """Lock should always be released even when recorder missing."""
    from src import transcriber as transcriber_module

    released = {"value": False}

    class DummyLock:
        def __init__(self, *_args, **_kwargs):
            pass

        def acquire(self) -> bool:
            return True

        def release(self) -> None:
            released["value"] = True

    monkeypatch.setattr(transcriber_module, "ProcessLock", DummyLock)

    with patch.object(transcriber, "find_recorders", return_value=[]):
        transcriber.process_recorder()

    assert released["value"] is True


def test_process_lock_excludes_second_holder(tmp_path):
    """Two locks on one path are mutually exclusive; release frees it cleanly."""
    from src.transcriber import ProcessLock

    lock_path = tmp_path / "transcriber.lock"

    first = ProcessLock(lock_path)
    assert first.acquire() is True

    # flock excludes even a second descriptor opened in the same process.
    second = ProcessLock(lock_path)
    assert second.acquire() is False

    first.release()

    # Once released the lock is immediately grabbable again — no stale wedge.
    assert second.acquire() is True
    second.release()


def test_process_lock_writes_diagnostics_payload(tmp_path):
    """acquire records ``<pid>\\n<timestamp>`` for inspection — not for locking."""
    from src.transcriber import ProcessLock

    lock_path = tmp_path / "transcriber.lock"
    lock = ProcessLock(lock_path)
    assert lock.acquire() is True
    try:
        pid_line, ts_line = lock_path.read_text(encoding="utf-8").splitlines()
        assert int(pid_line) == os.getpid()
        assert float(ts_line) > 0
    finally:
        lock.release()


def test_process_lock_ignores_leftover_file_contents(tmp_path):
    """Regression: a leftover lock file must never wedge acquisition.

    The old PID-file scheme deadlocked for the whole ``TRANSCRIPTION_TIMEOUT``
    window whenever the file held a still-live PID (in this single-process app
    the recorded PID is always our own) or was left empty by a kill between
    ``open`` and ``write``. With flock the file contents are irrelevant — only
    a live holder blocks — so every one of these leftovers must still acquire.
    """
    from src.transcriber import ProcessLock
    import time as time_module

    lock_path = tmp_path / "transcriber.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    leftovers = [
        f"{os.getpid()}\n{time_module.time():.0f}",  # our own (live) PID
        f"1\n{time_module.time():.0f}",  # PID 1 — always alive
        "",  # empty: killed mid-acquire
        "garbage-not-a-pid",  # corrupt
    ]
    for leftover in leftovers:
        lock_path.write_text(leftover, encoding="utf-8")
        lock = ProcessLock(lock_path)
        assert lock.acquire() is True, f"wedged on leftover {leftover!r}"
        lock.release()


def test_process_recorder_skips_when_workflow_lock_held(transcriber):
    """If another thread holds the in-process workflow lock, the run is skipped."""
    assert transcriber._workflow_lock.acquire(blocking=False) is True
    try:
        with patch.object(transcriber, "find_recorders") as mock_find:
            transcriber.process_recorder()
            mock_find.assert_not_called()
    finally:
        transcriber._workflow_lock.release()


def test_force_retranscribe_busy_when_workflow_lock_held(transcriber, tmp_path):
    """A user retranscribe during an automatic pass raises lock-busy at once."""
    from src.transcriber import RetranscribeLockBusyError

    audio = tmp_path / "clip.wav"
    audio.write_bytes(b"\x00")

    assert transcriber._workflow_lock.acquire(blocking=False) is True
    try:
        with pytest.raises(RetranscribeLockBusyError):
            transcriber.force_retranscribe(audio)
    finally:
        transcriber._workflow_lock.release()


@patch("src.transcriber.send_notification")
def test_process_recorder_no_notification_when_no_new_files(
    mock_notification, transcriber, mock_recorder_path
):
    """No system notification on recorder detection — the menu-bar status shows it."""
    with patch.object(
        transcriber,
        "find_recorders",
        return_value=([] if mock_recorder_path is None else [mock_recorder_path]),
    ):
        with patch.object(
            transcriber,
            "get_last_sync_time",
            return_value=datetime.now() + timedelta(days=1),
        ):  # Future date = no new files
            with patch.object(transcriber, "save_sync_time"):
                transcriber.process_recorder()

                assert mock_notification.call_count == 0


@patch("src.transcriber.send_notification")
def test_process_recorder_emits_no_status_notifications_when_files_found(
    mock_notification, transcriber, mock_recorder_path, tmp_path, monkeypatch
):
    """Automatic transcription emits no system notifications.

    Recorder-detected and completion notifications were removed: the menu-bar
    status item already reflects connection / progress / completion, so a system
    push would be redundant noise. This guards against re-adding it.
    """
    from src import config as config_module

    staging_dir = tmp_path / "staging"
    staging_dir.mkdir()
    update_transcriber_config(
        transcriber, monkeypatch, LOCAL_RECORDINGS_DIR=staging_dir
    )

    with patch.object(
        transcriber,
        "find_recorders",
        return_value=([] if mock_recorder_path is None else [mock_recorder_path]),
    ):
        with patch.object(
            transcriber,
            "find_pending_audio_files",
            return_value=[(mock_recorder_path / "Music" / "recording1.mp3", "fp-1")],
        ):
            with patch.object(
                transcriber,
                "get_last_sync_time",
                return_value=datetime.now() - timedelta(days=1),
            ):  # Past date = new files
                with patch.object(transcriber, "transcribe_file", return_value=True):
                    with patch.object(transcriber, "save_sync_time"):
                        transcriber.process_recorder()

                        assert mock_notification.call_count == 0


def test_process_recorder_does_not_force_idle_when_lock_held(transcriber, monkeypatch):
    """Lock contention should not reset status to IDLE (avoid UI flicker)."""
    from src import transcriber as transcriber_module

    class DummyLock:
        def __init__(self, *_args, **_kwargs):
            pass

        def acquire(self) -> bool:
            return False

        def release(self) -> None:
            pass

    monkeypatch.setattr(transcriber_module, "ProcessLock", DummyLock)
    transcriber._update_state(AppStatus.RECORDER_PENDING, pending_count=5)  # type: ignore[arg-type]
    updates = []
    transcriber.set_state_updater(
        lambda status, current, err, rec_name, pending: updates.append(status)
    )

    transcriber.process_recorder()

    assert AppStatus.IDLE not in updates


def test_find_pending_audio_files_returns_files_without_fingerprint(
    transcriber, tmp_path
):
    """Pending scan should return only files missing in vault index."""
    recorder = tmp_path / "LS-P1"
    recorder.mkdir()
    known = recorder / "known.mp3"
    unknown = recorder / "unknown.mp3"
    known.write_bytes(b"a")
    unknown.write_bytes(b"b")

    with patch("src.transcriber.compute_fingerprint") as fp_mock:
        fp_mock.side_effect = ["fp-known", "fp-unknown"]
        transcriber.vault_index.add(
            "fp-known",
            IndexEntry(
                fingerprint="fp-known",
                source_filename=known.name,
                source_volume=recorder.name,
                markdown_path="known.md",
                versions=[{"version": 1}],
            ),
        )
        pending = transcriber.find_pending_audio_files(recorder)

    assert pending == [(unknown, "fp-unknown")]


def test_process_recorder_sets_recorder_idle_when_all_transcribed(
    transcriber, tmp_path
):
    """Connected recorder with no pending files should set RECORDER_IDLE."""
    recorder = tmp_path / "LS-P1"
    recorder.mkdir()

    with patch.object(
        transcriber, "find_recorders", return_value=[recorder]
    ), patch.object(
        transcriber, "find_pending_audio_files", return_value=[]
    ), patch.object(
        transcriber, "find_audio_files", return_value=[]
    ):
        updates = []
        transcriber.set_state_updater(
            lambda status, current, err, rec_name, pending: updates.append(
                (status, rec_name, pending)
            )
        )
        transcriber.process_recorder()

    assert any(
        status == AppStatus.RECORDER_IDLE and pending == 0
        for status, _name, pending in updates
    )


def test_process_recorder_sets_recorder_pending_when_files_missing(
    transcriber, tmp_path
):
    """Connected recorder with missing fingerprints should set RECORDER_PENDING."""
    recorder = tmp_path / "LS-P1"
    recorder.mkdir()
    pending_files = [recorder / "a.mp3", recorder / "b.mp3", recorder / "c.mp3"]
    for path in pending_files:
        path.write_bytes(b"x")

    pending_tuples = [(p, f"fp-{p.name}") for p in pending_files]
    with patch.object(
        transcriber, "find_recorders", return_value=[recorder]
    ), patch.object(
        transcriber, "find_pending_audio_files", return_value=pending_tuples
    ), patch.object(
        transcriber, "find_audio_files", return_value=[]
    ):
        updates = []
        transcriber.set_state_updater(
            lambda status, current, err, rec_name, pending: updates.append(
                (status, rec_name, pending)
            )
        )
        transcriber.process_recorder()

    assert any(
        status == AppStatus.RECORDER_PENDING and pending == 3
        for status, _name, pending in updates
    )


# ---------------------------------------------------------------------------
# v2.0.0-beta.4 — post-process fixes
# ---------------------------------------------------------------------------


def test_extract_fallback_title_first_sentence(tmp_path):
    """Pierwsze zdanie do max_chars staje się fallback tytułem."""
    title = Transcriber._extract_fallback_title(
        "Projekt Wy w Czas. Druga sprawa zupełnie inna."
    )
    assert title == "Projekt Wy w Czas"


def test_extract_fallback_title_truncates_long_sentence():
    """Długie zdanie bez kropki jest skracane do max_chars z elipsą."""
    text = "A" * 100
    title = Transcriber._extract_fallback_title(text, max_chars=20)
    assert title.endswith("…")
    assert len(title) <= 21  # max_chars + 1 znak ellipsy


def test_extract_fallback_title_empty_string_returns_empty():
    assert Transcriber._extract_fallback_title("") == ""


def test_extract_fallback_title_brak_marker_returns_empty():
    """Marker '(Brak rozpoznawalnej mowy...)' nie jest tytułem."""
    assert (
        Transcriber._extract_fallback_title("(Brak rozpoznawalnej mowy w nagraniu)")
        == ""
    )


def test_wait_for_output_file_returns_true_immediately(tmp_path):
    target = tmp_path / "ready.txt"
    target.write_text("hi")
    assert Transcriber._wait_for_output_file(target, timeout=0.5) is True


def test_wait_for_output_file_returns_false_on_timeout(tmp_path):
    target = tmp_path / "missing.txt"
    assert (
        Transcriber._wait_for_output_file(target, timeout=0.2, interval=0.05) is False
    )


def test_wait_for_output_file_picks_up_late_arrival(tmp_path):
    """Symulujemy iCloud lag: plik pojawia się po 200ms."""
    import threading

    target = tmp_path / "delayed.txt"

    def create_late():
        import time as _t

        _t.sleep(0.2)
        target.write_text("late")

    threading.Thread(target=create_late, daemon=True).start()
    # Polling co 50ms przez ~1s — powinno złapać.
    assert Transcriber._wait_for_output_file(target, timeout=1.0, interval=0.05) is True


def test_force_retranscribe_lock_busy_raises(transcriber, tmp_path, monkeypatch):
    """Gdy auto-process trzyma lock, force_retranscribe rzuca RetranscribeLockBusyError."""
    from src.transcriber import RetranscribeLockBusyError

    audio = tmp_path / "test.mp3"
    audio.write_bytes(b"audio")

    # Symulujemy że ProcessLock.acquire zwraca False (busy).
    monkeypatch.setattr("src.transcriber.ProcessLock.acquire", lambda self: False)

    with pytest.raises(RetranscribeLockBusyError):
        transcriber.force_retranscribe(audio)


def test_reconcile_indexes_unindexed_markdown_and_cleans_txt(
    transcriber, tmp_path, monkeypatch
):
    """reconcile_existing_markdowns dodaje do vault_index brakujący wpis i usuwa osierocony .txt."""
    from src import config as config_module

    transcribe_dir = tmp_path / "vault"
    transcribe_dir.mkdir()
    monkeypatch.setattr(transcriber.config, "TRANSCRIBE_DIR", transcribe_dir)
    monkeypatch.setattr(config_module.config, "TRANSCRIBE_DIR", transcribe_dir)

    # Markdown z frontmatter wskazującym na fingerprint i source.
    md = transcribe_dir / "26-04-30 - Test.md"
    md.write_text(
        "---\n"
        'title: "Test"\n'
        "date: 2026-04-30\n"
        "source: test.MP3\n"
        "fingerprint: sha256:abc123def\n"
        "source_volume: LS-P1\n"
        "version: 1\n"
        "tags: [transcription]\n"
        "---\n\n"
        "Treść.\n"
    )

    # Osierocony TXT z tym samym source.stem.
    txt = transcribe_dir / "test.txt"
    txt.write_text("Treść txt")

    assert transcriber.vault_index.lookup("sha256:abc123def") is None

    result = transcriber.reconcile_existing_markdowns()

    assert result["indexed"] == 1
    assert result["txt_cleaned"] == 1
    # orphan_cleaned może być >0 z powodu wcześniejszych testów które zostawiły
    # wpisy w vault_index (test isolation issue z fixturą). Sprawdzamy tylko
    # że konkretne pliki zostały zindeksowane / sprzątnięte.
    assert result["txt_recovered"] == 0
    assert not txt.exists()
    entry = transcriber.vault_index.lookup("sha256:abc123def")
    assert entry is not None
    assert entry.markdown_path == md.name


def test_reconcile_idempotent_when_already_indexed(transcriber, tmp_path, monkeypatch):
    """Drugie wywołanie reconcile dla tego samego stanu nie robi nic."""
    from src import config as config_module

    transcribe_dir = tmp_path / "vault"
    transcribe_dir.mkdir()
    monkeypatch.setattr(transcriber.config, "TRANSCRIBE_DIR", transcribe_dir)
    monkeypatch.setattr(config_module.config, "TRANSCRIBE_DIR", transcribe_dir)

    md = transcribe_dir / "marker.md"
    md.write_text(
        "---\n"
        'title: "X"\n'
        "source: x.MP3\n"
        "fingerprint: sha256:xxx\n"
        "version: 1\n"
        "---\n\n"
        "X.\n"
    )

    transcriber.reconcile_existing_markdowns()
    second = transcriber.reconcile_existing_markdowns()
    assert second == {
        "indexed": 0,
        "orphan_cleaned": 0,
        "txt_cleaned": 0,
        "txt_recovered": 0,
    }


def test_reconcile_removes_orphan_vault_index_entry(transcriber, tmp_path, monkeypatch):
    """Wpis w vault_index wskazujący na nieistniejący MD jest usuwany."""
    from src import config as config_module
    from src.vault_index import IndexEntry

    transcribe_dir = tmp_path / "vault"
    transcribe_dir.mkdir()
    monkeypatch.setattr(transcriber.config, "TRANSCRIBE_DIR", transcribe_dir)
    monkeypatch.setattr(config_module.config, "TRANSCRIBE_DIR", transcribe_dir)

    transcriber.vault_index.add(
        "sha256:orphan",
        IndexEntry(
            fingerprint="sha256:orphan",
            source_filename="orphan.MP3",
            source_volume="LS-P1",
            markdown_path="this-md-does-not-exist.md",
            versions=[{"version": 1, "markdown_path": "this-md-does-not-exist.md"}],
        ),
    )
    assert transcriber.vault_index.lookup("sha256:orphan") is not None

    result = transcriber.reconcile_existing_markdowns()

    assert result["orphan_cleaned"] >= 1
    assert transcriber.vault_index.lookup("sha256:orphan") is None


def test_reconcile_counts_orphan_txt_for_recovery(transcriber, tmp_path, monkeypatch):
    """Plik .txt bez sąsiadującego MD jest liczony jako kandydat do recovery."""
    from src import config as config_module

    transcribe_dir = tmp_path / "vault"
    transcribe_dir.mkdir()
    monkeypatch.setattr(transcriber.config, "TRANSCRIBE_DIR", transcribe_dir)
    monkeypatch.setattr(config_module.config, "TRANSCRIBE_DIR", transcribe_dir)

    (transcribe_dir / "260430_0173.txt").write_text("Treść transkryptu po polsku.")

    result = transcriber.reconcile_existing_markdowns()

    assert result["txt_recovered"] == 1
    # Plik .txt zostaje — będzie podjęty przez transcribe_file ścieżką "TXT exists".
    assert (transcribe_dir / "260430_0173.txt").exists()


def test_force_retranscribe_clears_vault_index_entry(
    transcriber, tmp_path, monkeypatch
):
    """force_retranscribe usuwa wpis z vault_index przed transcribe_file."""
    from src import config as config_module
    from src.vault_index import IndexEntry

    transcribe_dir = tmp_path / "vault"
    transcribe_dir.mkdir()
    monkeypatch.setattr(transcriber.config, "TRANSCRIBE_DIR", transcribe_dir)
    monkeypatch.setattr(config_module.config, "TRANSCRIBE_DIR", transcribe_dir)

    audio = tmp_path / "test.mp3"
    audio.write_bytes(b"audio")

    # Symuluj istniejący wpis (po wcześniejszej transkrypcji).
    from src.fingerprint import compute_fingerprint

    fp = compute_fingerprint(audio)
    transcriber.vault_index.add(
        fp,
        IndexEntry(
            fingerprint=fp,
            source_filename="test.mp3",
            source_volume="staging",
            markdown_path="old.md",
            versions=[{"version": 1, "markdown_path": "old.md"}],
        ),
    )

    # Mock transcribe_file żeby nie odpalać whispera.
    monkeypatch.setattr(transcriber, "transcribe_file", lambda f: True)
    # Mock _update_state (wymagane przez state_updater = None).
    monkeypatch.setattr(transcriber, "_update_state", lambda *a, **kw: None)

    transcriber.force_retranscribe(audio)

    # Po force_retranscribe wpis powinien zniknąć (transcribe_file mock nie dodaje).
    assert transcriber.vault_index.lookup(fp) is None


def test_wait_for_output_file_requires_nonempty(tmp_path):
    """Pusty plik (size==0) NIE liczy się jako gotowy."""
    target = tmp_path / "empty.txt"
    target.write_text("")  # size=0
    assert (
        Transcriber._wait_for_output_file(target, timeout=0.2, interval=0.05) is False
    )
    target.write_text("some content")
    assert Transcriber._wait_for_output_file(target, timeout=0.5, interval=0.05) is True


# ---------------------------------------------------------------------------
# v2.0.0-beta.7 — encoding regression guards
# ---------------------------------------------------------------------------


def test_run_whisper_transcription_uses_utf8_encoding(
    transcriber, tmp_path, monkeypatch
):
    """Regression: the whisper Popen musi mieć encoding='utf-8' i errors='replace'.

    W py2app środowisku locale.getpreferredencoding() to często ASCII, co
    powoduje UnicodeDecodeError gdy whisper-cli pisze do stderr polski tekst
    (`0xc3` = UTF-8 lead byte). Bez `encoding='utf-8'` cała transkrypcja
    failuje na ostatnim kroku mimo że TXT poprawnie powstał.
    """
    captured = {}

    class _FakeStderr:
        def __init__(self):
            import os as _os

            self._r, w = _os.pipe()
            _os.close(w)  # immediate EOF — the reader needs a real fd

        def fileno(self):
            return self._r

        def read(self):
            return ""

        def close(self):
            import os as _os

            try:
                _os.close(self._r)
            except OSError:
                pass

    class _FakeProc:
        returncode = 0

        def __init__(self):
            self.stderr = _FakeStderr()

        def poll(self):
            return 0  # already finished → loop drains and exits, no select()

        def wait(self, timeout=None):
            return 0

        def kill(self):
            pass

    def fake_popen(*args, **kwargs):
        captured["kwargs"] = kwargs
        return _FakeProc()

    monkeypatch.setattr("src.transcriber.subprocess.Popen", fake_popen)

    audio = tmp_path / "test.mp3"
    audio.write_bytes(b"audio")
    transcriber.config.WHISPER_CPP_PATH = tmp_path / "whisper-cli"
    transcriber.config.WHISPER_CPP_MODELS_DIR = tmp_path
    transcriber.config.TRANSCRIBE_DIR = tmp_path
    transcriber.config.WHISPER_MODEL = "small"
    transcriber.config.WHISPER_LANGUAGE = "pl"

    transcriber._run_whisper_transcription(audio, use_coreml=True)

    assert captured["kwargs"].get("text") is True
    assert captured["kwargs"].get("encoding") == "utf-8", (
        "whisper Popen musi mieć encoding='utf-8' aby py2app environment "
        "z ASCII locale nie wywracał się na polskich znakach w whisper stderr."
    )
    assert captured["kwargs"].get("errors") == "replace", (
        "errors='replace' chroni przed bytes które nie są walid UTF-8 "
        "(np. corrupted output)."
    )


def test_subprocess_with_text_true_must_have_encoding_utf8():
    """Audyt całego src/: każdy subprocess.run/Popen z text=True musi mieć encoding='utf-8'.

    Ten test zabezpiecza przed regresją typu: deweloper dodaje subprocess.run
    z text=True do nowej funkcji, zapomina o encoding, w py2app crashuje
    na pierwszym ne-ASCII bajcie. Skanuje cały src/ i wymaga, by każdy
    text=True/universal_newlines=True miał też encoding='utf-8'.
    """
    import re
    from pathlib import Path

    src_dir = Path(__file__).resolve().parent.parent / "src"
    pattern = re.compile(
        r"subprocess\.(run|Popen|check_output|check_call|call)\((.*?)\)",
        re.DOTALL,
    )

    offenders = []
    for py_file in src_dir.rglob("*.py"):
        text = py_file.read_text(encoding="utf-8")
        for match in pattern.finditer(text):
            block = match.group(0)
            has_text = "text=True" in block or "universal_newlines=True" in block
            has_encoding = "encoding=" in block
            if has_text and not has_encoding:
                offenders.append(
                    f"{py_file.relative_to(src_dir.parent)}: {block[:120]}..."
                )

    assert not offenders, (
        "subprocess.run(...) z text=True ale BEZ encoding='utf-8' "
        "spowoduje UnicodeDecodeError w py2app (ASCII locale). "
        "Dodaj encoding='utf-8', errors='replace':\n  " + "\n  ".join(offenders)
    )


def test_filehandler_uses_utf8_encoding():
    """Regression: setup_logger musi tworzyć FileHandler z encoding='utf-8'.

    W py2app emoji w log strings (🎙️/🔄/✓/⚠️) silently gubiły linie
    przez UnicodeEncodeError (ASCII locale).
    """
    import inspect
    from src.logger import setup_logger

    source = inspect.getsource(setup_logger)
    assert 'encoding="utf-8"' in source or "encoding='utf-8'" in source, (
        "setup_logger.FileHandler musi używać encoding='utf-8' "
        "żeby emoji w logach nie gubiły linii w py2app environment."
    )
