"""Tests for the Voice Memos connector core (scanning, state, dedup)."""

import json
import os
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from src.voice_memos import (
    MAX_ATTEMPTS,
    MIN_STABLE_SECONDS,
    ConnectorStatus,
    VoiceMemosConnector,
    parse_memo_filename,
)


@pytest.fixture
def recordings_dir(tmp_path: Path) -> Path:
    folder = tmp_path / "Recordings"
    folder.mkdir()
    return folder


@pytest.fixture
def connector(recordings_dir: Path, tmp_path: Path) -> VoiceMemosConnector:
    return VoiceMemosConnector(
        recordings_dir=recordings_dir,
        state_file=tmp_path / "state" / "voice_memos_state.json",
    )


def make_memo(folder: Path, name: str, content: bytes = b"audio-bytes") -> Path:
    path = folder / name
    path.write_bytes(content)
    return path


def settle(connector: VoiceMemosConnector) -> None:
    """Backdate the stability clock so the next scan accepts what it sees."""
    connector._last_seen = {
        key: (size, first_seen - MIN_STABLE_SECONDS - 1)
        for key, (size, first_seen) in connector._last_seen.items()
    }


# --------------------------------------------------------------- filename


class TestParseMemoFilename:
    def test_parses_date_time_and_id(self, recordings_dir: Path):
        path = make_memo(recordings_dir, "20260730 095901-4E1A2B3C.m4a")

        memo = parse_memo_filename(path)

        assert memo is not None
        assert memo.memo_id == "4E1A2B3C"
        assert memo.recorded_at == datetime(2026, 7, 30, 9, 59, 1)
        assert memo.name_parsed is True

    def test_lowercase_id_is_normalised(self, recordings_dir: Path):
        memo = parse_memo_filename(
            make_memo(recordings_dir, "20260730 095901-4e1a2b3c.m4a")
        )

        assert memo is not None
        assert memo.memo_id == "4E1A2B3C"

    def test_non_m4a_is_not_a_memo(self, recordings_dir: Path):
        assert parse_memo_filename(make_memo(recordings_dir, "notes.txt")) is None

    def test_unexpected_name_falls_back_to_stem_and_mtime(self, recordings_dir: Path):
        path = make_memo(recordings_dir, "Rozmowa o saunie.m4a")
        stamp = datetime(2025, 3, 4, 12, 0, 0)
        os.utime(path, (stamp.timestamp(), stamp.timestamp()))

        memo = parse_memo_filename(path)

        # Never dropped: the name is still a stable id, mtime is a usable date.
        assert memo is not None
        assert memo.memo_id == "Rozmowa o saunie"
        assert memo.recorded_at == stamp
        assert memo.name_parsed is False

    def test_impossible_date_falls_back(self, recordings_dir: Path):
        memo = parse_memo_filename(
            make_memo(recordings_dir, "20261345 995901-AABBCCDD.m4a")
        )

        assert memo is not None
        assert memo.name_parsed is False


# ------------------------------------------------------------------ state


class TestState:
    def test_enable_sets_watermark_once(self, connector: VoiceMemosConnector):
        first = datetime(2026, 7, 30, 10, 0, 0)
        connector.enable(first)
        connector.enable(datetime(2026, 8, 1, 10, 0, 0))

        # Re-enabling must not rewind: otherwise the whole archive would look
        # new and silently queue hours of whisper.
        assert connector.enabled_at == first

    def test_state_round_trips_through_disk(
        self, connector: VoiceMemosConnector, recordings_dir: Path, tmp_path: Path
    ):
        connector.enable(datetime(2026, 7, 1))
        memo = parse_memo_filename(
            make_memo(recordings_dir, "20260730 095901-4E1A2B3C.m4a")
        )
        connector.mark_imported(memo, Path("/vault/note.md"), "sha256:abc")

        reloaded = VoiceMemosConnector(recordings_dir, connector.state_file)

        assert reloaded.enabled_at == datetime(2026, 7, 1)
        assert "4E1A2B3C" in reloaded._state["imported"]

    def test_corrupt_state_starts_fresh_without_crashing(
        self, recordings_dir: Path, tmp_path: Path
    ):
        state_file = tmp_path / "voice_memos_state.json"
        state_file.write_text("{not json at all", encoding="utf-8")

        connector = VoiceMemosConnector(recordings_dir, state_file)

        assert connector.enabled_at is None
        assert connector._state["imported"] == {}

    def test_save_is_atomic(self, connector: VoiceMemosConnector):
        connector.enable(datetime(2026, 7, 1))

        assert connector.state_file.exists()
        assert not connector.state_file.with_suffix(".json.tmp").exists()
        json.loads(connector.state_file.read_text(encoding="utf-8"))

    def test_failures_are_capped(
        self, connector: VoiceMemosConnector, recordings_dir: Path
    ):
        memo = parse_memo_filename(
            make_memo(recordings_dir, "20260730 095901-4E1A2B3C.m4a")
        )

        results = [connector.mark_failed(memo, "boom") for _ in range(MAX_ATTEMPTS)]

        assert results[:-1] == [False] * (MAX_ATTEMPTS - 1)
        assert results[-1] is True

    def test_import_clears_a_previous_failure(
        self, connector: VoiceMemosConnector, recordings_dir: Path
    ):
        memo = parse_memo_filename(
            make_memo(recordings_dir, "20260730 095901-4E1A2B3C.m4a")
        )
        connector.mark_failed(memo, "transient")
        connector.mark_imported(memo)

        assert "4E1A2B3C" not in connector._state["failed"]


# ------------------------------------------------------------------- scan


class TestScan:
    def test_returns_new_memo_after_it_settles(
        self, connector: VoiceMemosConnector, recordings_dir: Path
    ):
        connector.enable(datetime(2026, 7, 1))
        make_memo(recordings_dir, "20260730 095901-4E1A2B3C.m4a")

        # First pass only observes: the file may still be downloading.
        assert connector.scan() == []
        settle(connector)
        found = connector.scan()

        assert [memo.memo_id for memo in found] == ["4E1A2B3C"]

    def test_growing_file_is_not_imported(
        self, connector: VoiceMemosConnector, recordings_dir: Path
    ):
        connector.enable(datetime(2026, 7, 1))
        path = make_memo(recordings_dir, "20260730 095901-4E1A2B3C.m4a", b"partial")
        connector.scan()
        settle(connector)
        path.write_bytes(b"partial-plus-a-lot-more")

        assert connector.scan() == []

    def test_memos_older_than_the_watermark_are_left_alone(
        self, connector: VoiceMemosConnector, recordings_dir: Path
    ):
        connector.enable(datetime(2026, 7, 1))
        make_memo(recordings_dir, "20180101 101010-DEADBEEF.m4a")
        connector.scan()
        settle(connector)

        assert connector.scan() == []
        assert [m.memo_id for m in connector.archive_candidates()] == ["DEADBEEF"]

    def test_imported_memo_never_comes_back(
        self, connector: VoiceMemosConnector, recordings_dir: Path
    ):
        connector.enable(datetime(2026, 7, 1))
        path = make_memo(recordings_dir, "20260730 095901-4E1A2B3C.m4a")
        connector.scan()
        settle(connector)
        connector.mark_imported(connector.scan()[0])

        assert connector.scan() == []

        # iCloud eviction + redownload rewrites mtime; the memo id does not
        # change, so the memo must still be recognised as done.
        os.utime(path, (datetime.now().timestamp(),) * 2)
        settle(connector)
        assert connector.scan() == []

    def test_given_up_memo_is_not_retried(
        self, connector: VoiceMemosConnector, recordings_dir: Path
    ):
        connector.enable(datetime(2026, 7, 1))
        make_memo(recordings_dir, "20260730 095901-4E1A2B3C.m4a")
        connector.scan()
        settle(connector)
        memo = connector.scan()[0]
        for _ in range(MAX_ATTEMPTS):
            connector.mark_failed(memo, "broken")

        assert connector.scan() == []

    def test_non_audio_files_are_ignored(
        self, connector: VoiceMemosConnector, recordings_dir: Path
    ):
        connector.enable(datetime(2026, 7, 1))
        make_memo(recordings_dir, "CloudRecordings.db", b"sqlite")
        make_memo(recordings_dir, "notes.txt")
        connector.scan()
        settle(connector)

        assert connector.scan() == []

    def test_results_are_ordered_oldest_first(
        self, connector: VoiceMemosConnector, recordings_dir: Path
    ):
        connector.enable(datetime(2026, 7, 1))
        make_memo(recordings_dir, "20260730 120000-BBBBBBBB.m4a")
        make_memo(recordings_dir, "20260730 090000-AAAAAAAA.m4a")
        connector.scan()
        settle(connector)

        assert [m.memo_id for m in connector.scan()] == ["AAAAAAAA", "BBBBBBBB"]

    def test_without_a_watermark_nothing_is_archive(
        self, connector: VoiceMemosConnector, recordings_dir: Path
    ):
        make_memo(recordings_dir, "20180101 101010-DEADBEEF.m4a")

        assert connector.archive_candidates() == []

    def test_without_a_watermark_nothing_is_new_either(
        self, connector: VoiceMemosConnector, recordings_dir: Path
    ):
        # Fail closed. A missing marker (settings saved before the connector
        # existed, or a lost state file) must not read as "no filter" — that
        # would sweep a decade of memos into an unasked-for whisper run.
        make_memo(recordings_dir, "20180101 101010-DEADBEEF.m4a")
        make_memo(recordings_dir, "20260730 095901-4E1A2B3C.m4a")
        connector.scan()
        settle(connector)

        assert connector.scan() == []

    def test_vanished_files_leave_no_trace_in_the_stability_map(
        self, connector: VoiceMemosConnector, recordings_dir: Path
    ):
        connector.enable(datetime(2026, 7, 1))
        path = make_memo(recordings_dir, "20260730 095901-4E1A2B3C.m4a")
        connector.scan()
        path.unlink()

        connector.scan()

        assert connector._last_seen == {}


# ----------------------------------------------------------------- status


class TestStatus:
    def test_disabled_wins(self, connector: VoiceMemosConnector, recordings_dir: Path):
        make_memo(recordings_dir, "20260730 095901-4E1A2B3C.m4a")

        assert connector.status(enabled=False) is ConnectorStatus.DISABLED

    def test_missing_folder_reads_as_not_configured(self, tmp_path: Path):
        connector = VoiceMemosConnector(
            tmp_path / "nope", tmp_path / "voice_memos_state.json"
        )

        assert connector.status(enabled=True) is ConnectorStatus.NOT_CONFIGURED
        assert connector.has_any_recordings() is False

    def test_empty_folder_reads_as_not_configured(self, connector: VoiceMemosConnector):
        assert connector.status(enabled=True) is ConnectorStatus.NOT_CONFIGURED

    def test_recordings_present_reads_as_active(
        self, connector: VoiceMemosConnector, recordings_dir: Path
    ):
        make_memo(recordings_dir, "20260730 095901-4E1A2B3C.m4a")

        assert connector.status(enabled=True) is ConnectorStatus.ACTIVE
        assert connector.has_any_recordings() is True

    def test_denied_folder_reads_as_no_access(
        self, connector: VoiceMemosConnector, monkeypatch
    ):
        def deny(_self):
            raise PermissionError("TCC says no")

        monkeypatch.setattr(Path, "iterdir", deny)

        # macOS can gate another app's Group Container: report it, never crash.
        assert connector.status(enabled=True) is ConnectorStatus.NO_ACCESS
        assert connector.scan() == []


class TestWatermarkBoundary:
    def test_memo_recorded_after_enabling_is_new(
        self, connector: VoiceMemosConnector, recordings_dir: Path
    ):
        watermark = datetime(2026, 7, 30, 10, 0, 0)
        connector.enable(watermark)
        later = watermark + timedelta(minutes=1)
        make_memo(recordings_dir, f"{later:%Y%m%d %H%M%S}-CAFEBABE.m4a")
        connector.scan()
        settle(connector)

        assert [m.memo_id for m in connector.scan()] == ["CAFEBABE"]
