"""Tests for migration wrapper and migration-trigger behavior."""

import json
from pathlib import Path
from unittest.mock import patch

from src.config.config import Config
from src.config.migration import migrate_from_old_config, perform_migration_if_needed
from src.config.settings import UserSettings
from src.transcriber import Transcriber
from src.vault_index import IndexEntry, VaultIndex


class TestMigrationWrappers:
    """Test suite for backward-compatible migration wrapper API."""

    def test_migrate_from_old_config_wrapper(self, tmp_path, monkeypatch):
        """Wrapper should return migrated settings from old state file."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        (tmp_path / ".olympus_transcriber_state.json").write_text(
            json.dumps(
                {"transcribe_dir": str(tmp_path / "old"), "recorder_names": ["LS-P1"]}
            ),
            encoding="utf-8",
        )

        migrated = migrate_from_old_config()

        assert migrated is not None
        assert migrated.watch_mode == "specific"
        assert migrated.watched_volumes == ["LS-P1"]

    def test_perform_migration_if_needed_wrapper(self, tmp_path, monkeypatch):
        """Wrapper should delegate to bootstrap and return settings."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        result = perform_migration_if_needed()
        assert isinstance(result, UserSettings)


class TestVaultIndexMigrationTrigger:
    """Tests for transcriber-triggered vault index migration behavior."""

    def test_reruns_migration_when_index_empty_but_vault_has_markdown(self, tmp_path):
        cfg = Config()
        cfg.TRANSCRIBE_DIR = tmp_path

        (tmp_path / "legacy.md").write_text(
            "---\nsource: DS1.mp3\n---\nlegacy",
            encoding="utf-8",
        )

        settings = UserSettings(output_dir=tmp_path, index_migrated=True)
        with patch("src.transcriber.UserSettings.load", return_value=settings), patch(
            "src.transcriber.subprocess.run"
        ) as run_mock:
            Transcriber(config=cfg)

        run_mock.assert_called_once()

    def test_does_not_rerun_when_index_has_entries(self, tmp_path):
        cfg = Config()
        cfg.TRANSCRIBE_DIR = tmp_path

        idx = VaultIndex(tmp_path)
        idx.load()
        idx.add(
            "sha256:seed",
            IndexEntry(
                fingerprint="sha256:seed",
                source_filename="a.mp3",
                source_volume="LS-P1",
                markdown_path="a.md",
                versions=[{"version": 1}],
            ),
        )

        (tmp_path / "legacy.md").write_text(
            "---\nsource: DS1.mp3\n---\nlegacy",
            encoding="utf-8",
        )

        settings = UserSettings(output_dir=tmp_path, index_migrated=True)
        with patch("src.transcriber.UserSettings.load", return_value=settings), patch(
            "src.transcriber.subprocess.run"
        ) as run_mock:
            Transcriber(config=cfg)

        run_mock.assert_not_called()
