"""Tests for the manual audio-import fallback.

Covers ``Transcriber.stage_audio_file`` / ``import_audio_file`` and the
``TimshelTranscriber`` (app_core) delegation — the path a user takes when
automatic recorder/SD detection misses a file and they import it by hand.

Staging is exercised with real generated audio (mp3/flac/wav) when the
AudioFactory toolchain (``say`` + ffmpeg) is available, and with lightweight
stand-ins otherwise, so the copy/dedup/reject contract is always covered even
on machines without the audio toolchain.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.transcriber import Transcriber
from tests.fixtures.audio_factory import AudioFactory


@pytest.fixture
def transcriber(tmp_path):
    """Transcriber with vault + staging dirs pointed at a throwaway tmp_path."""
    from src.config.config import Config

    cfg = Config()
    cfg.TRANSCRIBE_DIR = tmp_path / "vault"
    cfg.TRANSCRIBE_DIR.mkdir(parents=True, exist_ok=True)
    cfg.LOCAL_RECORDINGS_DIR = tmp_path / "staging"
    with patch("src.transcriber.logger"):
        return Transcriber(config=cfg)


@pytest.fixture(scope="module")
def factory() -> AudioFactory:
    """Shared real-audio factory (cached across the module)."""
    return AudioFactory()


def _real_or_stub(factory: AudioFactory, dest: Path, ext: str) -> Path:
    """Write a source file at *dest*: real generated audio if possible, else a stub.

    Returns *dest*. The staging contract (copy/dedup/reject) does not depend on
    the bytes being decodable, so a stub keeps these tests runnable everywhere;
    when the toolchain is present we still prove real mp3/flac/wav stage cleanly.
    """
    if factory.available:
        generated = factory.make(lang="en_US", ext=ext)
        dest.write_bytes(generated.read_bytes())
    else:
        dest.write_bytes(b"\x00" * 64)
    return dest


# --------------------------------------------------------------------------- #
# stage_audio_file — copy / reject / dedup.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("ext", [".mp3", ".flac", ".wav"])
def test_stage_copies_supported_format(transcriber, factory, tmp_path, ext):
    """A supported file is copied into the staging dir; original untouched."""
    source = _real_or_stub(factory, tmp_path / f"sample{ext}", ext)
    original_bytes = source.read_bytes()

    staged = transcriber.stage_audio_file(source)

    assert staged.exists()
    assert staged.parent == transcriber.config.LOCAL_RECORDINGS_DIR
    assert staged.suffix.lower() == ext
    assert staged.read_bytes() == original_bytes
    # Original must be left in place (we copy, never move).
    assert source.exists()
    assert source.read_bytes() == original_bytes


def test_stage_recreates_staging_dir_if_removed(transcriber, tmp_path):
    """If the staging dir is missing at import time, it is recreated."""
    import shutil

    staging = transcriber.config.LOCAL_RECORDINGS_DIR
    if staging.exists():
        shutil.rmtree(staging)
    assert not staging.exists()

    source = tmp_path / "rec.wav"
    source.write_bytes(b"\x00" * 16)

    transcriber.stage_audio_file(source)

    assert staging.is_dir()


def test_stage_rejects_unsupported_extension(transcriber, tmp_path):
    """A non-audio file raises ValueError and is not staged."""
    bad = tmp_path / "notes.txt"
    bad.write_text("not audio")

    with pytest.raises(ValueError):
        transcriber.stage_audio_file(bad)

    # Nothing copied.
    staging = transcriber.config.LOCAL_RECORDINGS_DIR
    assert not staging.exists() or not any(staging.iterdir())


def test_stage_missing_file_raises(transcriber, tmp_path):
    """A path that does not exist raises FileNotFoundError."""
    with pytest.raises(FileNotFoundError):
        transcriber.stage_audio_file(tmp_path / "does-not-exist.mp3")


def test_stage_directory_raises(transcriber, tmp_path):
    """A directory (not a file) raises FileNotFoundError."""
    folder = tmp_path / "afolder.mp3"  # extension on a dir must still be rejected
    folder.mkdir()
    with pytest.raises(FileNotFoundError):
        transcriber.stage_audio_file(folder)


def test_stage_dedupes_colliding_names(transcriber, tmp_path):
    """Re-importing a same-named file never overwrites the earlier copy."""
    src_a = tmp_path / "a" / "memo.mp3"
    src_b = tmp_path / "b" / "memo.mp3"
    src_a.parent.mkdir()
    src_b.parent.mkdir()
    src_a.write_bytes(b"AAAA")
    src_b.write_bytes(b"BBBB")

    staged_a = transcriber.stage_audio_file(src_a)
    staged_b = transcriber.stage_audio_file(src_b)

    assert staged_a != staged_b
    assert staged_a.name == "memo.mp3"
    assert staged_b.name == "memo (1).mp3"
    # Both copies preserved with their own bytes.
    assert staged_a.read_bytes() == b"AAAA"
    assert staged_b.read_bytes() == b"BBBB"


def test_stage_extension_case_insensitive(transcriber, tmp_path):
    """Uppercase extensions (e.g. .WAV from some recorders) are accepted."""
    source = tmp_path / "REC.WAV"
    source.write_bytes(b"\x00" * 16)

    staged = transcriber.stage_audio_file(source)
    assert staged.exists()


# --------------------------------------------------------------------------- #
# import_audio_file — stage then transcribe.
# --------------------------------------------------------------------------- #


def test_import_stages_then_transcribes(transcriber, tmp_path):
    """import_audio_file stages the file then runs transcribe_file on the copy."""
    source = tmp_path / "voice.mp3"
    source.write_bytes(b"\x00" * 32)

    with patch.object(transcriber, "transcribe_file", return_value=True) as mock_tx:
        result = transcriber.import_audio_file(source)

    assert result is True
    mock_tx.assert_called_once()
    staged_arg = mock_tx.call_args.args[0]
    assert Path(staged_arg).parent == transcriber.config.LOCAL_RECORDINGS_DIR


def test_import_propagates_transcribe_failure(transcriber, tmp_path):
    """A failed transcription returns False (but the file was still staged)."""
    source = tmp_path / "voice.wav"
    source.write_bytes(b"\x00" * 32)

    with patch.object(transcriber, "transcribe_file", return_value=False):
        assert transcriber.import_audio_file(source) is False

    staged = list(transcriber.config.LOCAL_RECORDINGS_DIR.iterdir())
    assert len(staged) == 1


def test_import_rejects_invalid_without_transcribing(transcriber, tmp_path):
    """An unsupported file raises before transcribe_file is ever called."""
    bad = tmp_path / "image.png"
    bad.write_bytes(b"\x89PNG")

    with patch.object(transcriber, "transcribe_file") as mock_tx:
        with pytest.raises(ValueError):
            transcriber.import_audio_file(bad)

    mock_tx.assert_not_called()


# --------------------------------------------------------------------------- #
# Locking: manual import must not run concurrently with the automatic
# workflow — two whisper-cli processes would peg every core (each takes
# cores-2 threads) and race on vault_index.
# --------------------------------------------------------------------------- #


def test_import_busy_when_workflow_lock_held(transcriber, tmp_path):
    """A held workflow lock (automatic run in progress) rejects the import
    BEFORE staging — zero side effects."""
    from src.transcriber import RetranscribeLockBusyError

    source = tmp_path / "voice.mp3"
    source.write_bytes(b"\x00" * 32)

    assert transcriber._workflow_lock.acquire(blocking=False)
    try:
        with pytest.raises(RetranscribeLockBusyError):
            transcriber.import_audio_file(source)
    finally:
        transcriber._workflow_lock.release()

    staging = transcriber.config.LOCAL_RECORDINGS_DIR
    assert not staging.exists() or not list(staging.iterdir())  # nothing staged


def test_import_busy_when_process_lock_held(transcriber, tmp_path, monkeypatch):
    """A held cross-process flock also rejects; the workflow lock is released
    so a later attempt can proceed."""
    from src import transcriber as transcriber_module
    from src.transcriber import RetranscribeLockBusyError

    class DummyLock:
        def __init__(self, *_args, **_kwargs):
            pass

        def acquire(self) -> bool:
            return False

        def release(self) -> None:
            pass

    monkeypatch.setattr(transcriber_module, "ProcessLock", DummyLock)

    source = tmp_path / "voice.mp3"
    source.write_bytes(b"\x00" * 32)

    with pytest.raises(RetranscribeLockBusyError):
        transcriber.import_audio_file(source)

    # Workflow lock must be free again after the rejection.
    assert transcriber._workflow_lock.acquire(blocking=False)
    transcriber._workflow_lock.release()


def test_import_releases_locks_after_success_and_failure(transcriber, tmp_path):
    """Both locks are released after success, failure, and staging errors."""
    source = tmp_path / "voice.mp3"
    source.write_bytes(b"\x00" * 32)

    with patch.object(transcriber, "transcribe_file", return_value=True):
        assert transcriber.import_audio_file(source) is True
    assert transcriber._workflow_lock.acquire(blocking=False)
    transcriber._workflow_lock.release()

    source2 = tmp_path / "voice2.mp3"
    source2.write_bytes(b"\x00" * 32)
    with patch.object(transcriber, "transcribe_file", return_value=False):
        assert transcriber.import_audio_file(source2) is False
    assert transcriber._workflow_lock.acquire(blocking=False)
    transcriber._workflow_lock.release()

    bad = tmp_path / "image.png"
    bad.write_bytes(b"\x89PNG")
    with pytest.raises(ValueError):
        transcriber.import_audio_file(bad)
    assert transcriber._workflow_lock.acquire(blocking=False)
    transcriber._workflow_lock.release()


# --------------------------------------------------------------------------- #
# app_core delegation.
# --------------------------------------------------------------------------- #


def test_app_core_import_forwards_to_transcriber():
    """TimshelTranscriber.import_audio_file delegates to the inner Transcriber."""
    from src.app_core import TimshelTranscriber

    app = TimshelTranscriber(setup_signals=False)
    app.transcriber = MagicMock()
    app.transcriber.import_audio_file.return_value = True

    assert app.import_audio_file(Path("/tmp/x.mp3")) is True
    app.transcriber.import_audio_file.assert_called_once_with(Path("/tmp/x.mp3"))


def test_app_core_import_raises_when_not_started():
    """Importing before the daemon started raises a clear error."""
    from src.app_core import TimshelTranscriber

    app = TimshelTranscriber(setup_signals=False)
    app.transcriber = None

    with pytest.raises(RuntimeError):
        app.import_audio_file(Path("/tmp/x.mp3"))


def test_app_core_reload_ai_config_forwards_to_transcriber():
    """TimshelTranscriber.reload_ai_config delegates to the inner Transcriber.

    Regression: the menu app calls ``reload_ai_config`` on the orchestrator
    after a Settings save; the method lives on the inner Transcriber, so the
    orchestrator must forward it or hot-reload of a fixed API key silently dies
    with an AttributeError.
    """
    from src.app_core import TimshelTranscriber

    app = TimshelTranscriber(setup_signals=False)
    app.transcriber = MagicMock()

    app.reload_ai_config()
    app.transcriber.reload_ai_config.assert_called_once_with()


def test_app_core_reload_ai_config_noop_when_not_started():
    """Reloading before the daemon built its transcriber is a safe no-op.

    A key saved that early is picked up by the start-time client build, so this
    must not raise into the settings handler.
    """
    from src.app_core import TimshelTranscriber

    app = TimshelTranscriber(setup_signals=False)
    app.transcriber = None

    app.reload_ai_config()  # must not raise
