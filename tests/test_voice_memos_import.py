"""Tests for the Voice Memos import loop (process_voice_memos)."""

from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.transcriber import RetranscribeLockBusyError
from src.voice_memos import (
    MAX_ATTEMPTS,
    PROVENANCE,
    VoiceMemosConnector,
    parse_memo_filename,
    process_voice_memos,
)


@pytest.fixture
def recordings_dir(tmp_path: Path) -> Path:
    folder = tmp_path / "Recordings"
    folder.mkdir()
    return folder


@pytest.fixture
def connector(recordings_dir: Path, tmp_path: Path) -> VoiceMemosConnector:
    connector = VoiceMemosConnector(
        recordings_dir=recordings_dir,
        state_file=tmp_path / "voice_memos_state.json",
    )
    connector.enable(datetime(2026, 7, 1))
    return connector


@pytest.fixture
def transcriber() -> MagicMock:
    fake = MagicMock()
    fake.import_audio_file.return_value = True
    fake.vault_index.lookup_by_filename_size.return_value = None
    return fake


def memo(folder: Path, name: str = "20260730 095901-4E1A2B3C.m4a"):
    (folder / name).write_bytes(b"audio")
    return parse_memo_filename(folder / name)


class TestHappyPath:
    def test_imports_and_records_the_memo(self, connector, transcriber, recordings_dir):
        candidate = memo(recordings_dir)

        stats = process_voice_memos(transcriber, connector, candidates=[candidate])

        assert stats.imported == 1
        assert "4E1A2B3C" in connector._state["imported"]

    def test_passes_recording_time_and_provenance_down(
        self, connector, transcriber, recordings_dir
    ):
        candidate = memo(recordings_dir)

        process_voice_memos(transcriber, connector, candidates=[candidate])

        _, kwargs = transcriber.import_audio_file.call_args
        # The filename time, not mtime — mtime is the iCloud sync time.
        assert kwargs["recorded_at"] == datetime(2026, 7, 30, 9, 59, 1)
        assert kwargs["provenance"]["source_type"] == "voice-memo"
        assert kwargs["provenance"] == PROVENANCE

    def test_notifies_once_per_batch(self, connector, transcriber, recordings_dir):
        candidates = [
            memo(recordings_dir, "20260730 095901-AAAAAAAA.m4a"),
            memo(recordings_dir, "20260730 101500-BBBBBBBB.m4a"),
        ]
        notify = MagicMock()

        process_voice_memos(
            transcriber, connector, candidates=candidates, notify=notify
        )

        assert notify.call_count == 1

    def test_no_notification_when_nothing_was_imported(
        self, connector, transcriber, recordings_dir
    ):
        transcriber.import_audio_file.return_value = False
        notify = MagicMock()

        process_voice_memos(
            transcriber,
            connector,
            candidates=[memo(recordings_dir)],
            notify=notify,
        )

        notify.assert_not_called()

    def test_empty_batch_touches_nothing(self, connector, transcriber):
        stats = process_voice_memos(transcriber, connector, candidates=[])

        assert stats.imported == 0
        transcriber.import_audio_file.assert_not_called()


class TestDedup:
    def test_memo_already_in_the_vault_is_not_re_imported(
        self, connector, transcriber, recordings_dir
    ):
        # State was lost (fresh install, shared vault) — the vault index is the
        # backstop. Without it the pipeline would write note ".v2", not skip.
        transcriber.vault_index.lookup_by_filename_size.return_value = object()

        stats = process_voice_memos(
            transcriber, connector, candidates=[memo(recordings_dir)]
        )

        transcriber.import_audio_file.assert_not_called()
        assert stats.skipped == 1
        assert "4E1A2B3C" in connector._state["imported"]

    def test_broken_index_does_not_block_the_import(
        self, connector, transcriber, recordings_dir
    ):
        transcriber.vault_index.lookup_by_filename_size.side_effect = OSError("nope")

        stats = process_voice_memos(
            transcriber, connector, candidates=[memo(recordings_dir)]
        )

        assert stats.imported == 1


class TestFailures:
    def test_busy_lock_aborts_the_batch_without_recording_anything(
        self, connector, transcriber, recordings_dir
    ):
        transcriber.import_audio_file.side_effect = RetranscribeLockBusyError("busy")
        candidate = memo(recordings_dir)

        stats = process_voice_memos(transcriber, connector, candidates=[candidate])

        assert stats.lock_aborted is True
        # A busy recorder is not the memo's fault: no attempt is counted, so the
        # next tick retries it with a clean slate.
        assert connector._state["failed"] == {}
        assert connector._state["imported"] == {}

    def test_busy_lock_stops_before_the_remaining_memos(
        self, connector, transcriber, recordings_dir
    ):
        transcriber.import_audio_file.side_effect = RetranscribeLockBusyError("busy")
        candidates = [
            memo(recordings_dir, "20260730 095901-AAAAAAAA.m4a"),
            memo(recordings_dir, "20260730 101500-BBBBBBBB.m4a"),
        ]

        process_voice_memos(transcriber, connector, candidates=candidates)

        assert transcriber.import_audio_file.call_count == 1

    def test_failed_transcription_counts_an_attempt(
        self, connector, transcriber, recordings_dir
    ):
        transcriber.import_audio_file.return_value = False

        stats = process_voice_memos(
            transcriber, connector, candidates=[memo(recordings_dir)]
        )

        assert stats.failed == 1
        assert connector._state["failed"]["4E1A2B3C"]["attempts"] == 1
        assert connector._state["failed"]["4E1A2B3C"]["gave_up"] is False

    def test_memo_is_parked_after_repeated_failures(
        self, connector, transcriber, recordings_dir
    ):
        transcriber.import_audio_file.return_value = False
        candidate = memo(recordings_dir)

        for _ in range(MAX_ATTEMPTS):
            process_voice_memos(transcriber, connector, candidates=[candidate])

        assert connector._state["failed"]["4E1A2B3C"]["gave_up"] is True

    def test_unexpected_error_fails_one_memo_not_the_batch(
        self, connector, transcriber, recordings_dir
    ):
        candidates = [
            memo(recordings_dir, "20260730 095901-AAAAAAAA.m4a"),
            memo(recordings_dir, "20260730 101500-BBBBBBBB.m4a"),
        ]
        transcriber.import_audio_file.side_effect = [RuntimeError("whisper died"), True]

        stats = process_voice_memos(transcriber, connector, candidates=candidates)

        assert (stats.imported, stats.failed) == (1, 1)

    def test_invalid_file_is_marked_failed(
        self, connector, transcriber, recordings_dir
    ):
        transcriber.import_audio_file.side_effect = FileNotFoundError("gone")

        stats = process_voice_memos(
            transcriber, connector, candidates=[memo(recordings_dir)]
        )

        assert stats.failed == 1


class TestConcurrency:
    def test_a_second_pass_does_not_run_concurrently(
        self, connector, transcriber, recordings_dir
    ):
        # FSEvents and the periodic tick both call in; a reentrant pass would
        # double-count attempts and fight for the workflow lock.
        candidate = memo(recordings_dir)
        reentrant = {}

        def import_and_reenter(*_args, **_kwargs):
            reentrant["stats"] = process_voice_memos(
                transcriber, connector, candidates=[candidate]
            )
            return True

        transcriber.import_audio_file.side_effect = import_and_reenter

        process_voice_memos(transcriber, connector, candidates=[candidate])

        assert reentrant["stats"].imported == 0
        assert transcriber.import_audio_file.call_count == 1


class TestProgress:
    def test_progress_is_reported_per_memo(
        self, connector, transcriber, recordings_dir
    ):
        candidates = [
            memo(recordings_dir, "20260730 095901-AAAAAAAA.m4a"),
            memo(recordings_dir, "20260730 101500-BBBBBBBB.m4a"),
        ]
        progress = MagicMock()

        process_voice_memos(
            transcriber, connector, candidates=candidates, progress=progress
        )

        assert progress.call_count == 2
        assert progress.call_args_list[0][0][:2] == (0, 2)
