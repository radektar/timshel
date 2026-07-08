"""Tests for UserSettings module (v2.0.0)."""

import pytest
import json
import tempfile
from pathlib import Path
from unittest.mock import patch, mock_open
from src.config.settings import UserSettings
from src.config.defaults import defaults


class TestUserSettings:
    """Test suite for UserSettings class."""
    
    def test_default_initialization(self):
        """Test UserSettings initializes with defaults."""
        settings = UserSettings()
        
        assert settings.watch_mode == defaults.WATCH_MODE
        assert settings.watched_volumes == []
        assert settings.output_dir == defaults.DEFAULT_OUTPUT_DIR
        assert settings.language == defaults.DEFAULT_LANGUAGE
        assert settings.whisper_model == defaults.DEFAULT_WHISPER_MODEL
        assert settings.enable_ai_summaries == defaults.DEFAULT_ENABLE_AI_SUMMARIES
        assert settings.show_notifications == defaults.DEFAULT_SHOW_NOTIFICATIONS
        assert settings.start_at_login == defaults.DEFAULT_START_AT_LOGIN
        assert settings.setup_completed == defaults.DEFAULT_SETUP_COMPLETED
    
    def test_load_nonexistent_file(self, tmp_path, monkeypatch):
        """Test loading when config file doesn't exist."""
        # Mock home directory to use temp directory
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        
        settings = UserSettings.load()
        
        # Should return default settings
        assert settings.watch_mode == defaults.WATCH_MODE
        assert settings.setup_completed == defaults.DEFAULT_SETUP_COMPLETED
    
    def test_save_and_load(self, tmp_path, monkeypatch):
        """Test saving and loading settings."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        
        # Create and save settings
        original = UserSettings()
        original.watch_mode = "specific"
        original.watched_volumes = ["SD_CARD", "USB_DRIVE"]
        original.language = "en"
        original.setup_completed = True
        original.save()
        
        # Load settings
        loaded = UserSettings.load()
        
        assert loaded.watch_mode == "specific"
        assert loaded.watched_volumes == ["SD_CARD", "USB_DRIVE"]
        assert loaded.language == "en"
        assert loaded.setup_completed is True
    
    def test_save_creates_directory(self, tmp_path, monkeypatch):
        """Test that save creates parent directory if needed."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        
        config_dir = tmp_path / "Library" / "Application Support" / "Timshel"
        config_file = config_dir / "config.json"
        
        settings = UserSettings()
        settings.save()
        
        assert config_dir.exists()
        assert config_file.exists()
    
    def test_load_handles_invalid_json(self, tmp_path, monkeypatch):
        """Test loading handles corrupted JSON gracefully."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        
        config_dir = tmp_path / "Library" / "Application Support" / "Timshel"
        config_dir.mkdir(parents=True)
        config_file = config_dir / "config.json"
        config_file.write_text("invalid json {")
        
        settings = UserSettings.load()
        
        # Should fall back to defaults
        assert settings.watch_mode == defaults.WATCH_MODE
    
    def test_load_handles_path_strings(self, tmp_path, monkeypatch):
        """Test that paths are converted from strings to Path objects."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        
        # Save with string path
        original = UserSettings()
        original.output_dir = Path("/tmp/test")
        original.save()
        
        # Load should convert string back to Path
        loaded = UserSettings.load()
        assert isinstance(loaded.output_dir, Path)
        # Path.resolve() may change /tmp/test to /private/tmp/test on macOS
        assert loaded.output_dir.name == "test" or str(loaded.output_dir).endswith("/test")
    
    def test_ensure_directories(self, tmp_path):
        """Test that ensure_directories creates output directory."""
        settings = UserSettings()
        settings.output_dir = tmp_path / "transcriptions"
        
        assert not settings.output_dir.exists()
        settings.ensure_directories()
        assert settings.output_dir.exists()
    
    def test_post_init_converts_string_paths(self):
        """Test that __post_init__ converts string paths to Path objects."""
        # Create settings with string path (simulating JSON load)
        settings_dict = {
            "watch_mode": "manual",
            "watched_volumes": [],
            "output_dir": "/tmp/test",  # String from JSON
            "language": "pl",
            "whisper_model": "small",
            "enable_ai_summaries": False,
            "ai_api_key": None,
            "show_notifications": True,
            "start_at_login": False,
            "setup_completed": False,
        }
        settings = UserSettings(**settings_dict)

        # Should be converted to Path in __post_init__
        assert isinstance(settings.output_dir, Path)
        # Path.resolve() may change /tmp/test to /private/tmp/test on macOS
        assert settings.output_dir.name == "test" or str(settings.output_dir).endswith("/test")
    
    def test_config_path_location(self):
        """Test that config path is in correct location."""
        config_path = UserSettings._config_path()
        
        assert "Library" in str(config_path)
        assert "Application Support" in str(config_path)
        assert "Timshel" in str(config_path)
        assert config_path.name == "config.json"


class TestUserSettingsWatchModes:
    """Test suite for watch mode functionality."""
    
    def test_manual_mode_default(self):
        """v2.0.0-beta.2: domyślny tryb to 'manual' (auto usunięte ze względów bezpieczeństwa)."""
        settings = UserSettings()
        assert settings.watch_mode == "manual"

    def test_auto_mode_migrates_to_manual_with_onboarding_flag(self):
        """Legacy 'auto' z poprzednich wersji migruje na 'manual' + ustawia onboarding."""
        settings = UserSettings(watch_mode="auto")
        assert settings.watch_mode == "manual"
        assert settings.needs_volume_onboarding is True

    def test_trusted_volume_add_and_lookup(self):
        """add_trusted_volume / find_trusted_volume działają end-to-end."""
        settings = UserSettings()
        entry = settings.add_trusted_volume("UUID-1", "LS-P1", "trusted")
        assert entry.uuid == "UUID-1"
        assert entry.decision == "trusted"
        found = settings.find_trusted_volume("UUID-1")
        assert found is entry
        assert settings.find_trusted_volume("UUID-MISSING") is None

    def test_trusted_volume_add_updates_existing_decision(self):
        """Druga decyzja na ten sam UUID nadpisuje poprzednią."""
        settings = UserSettings()
        settings.add_trusted_volume("UUID-1", "Foo", "trusted")
        settings.add_trusted_volume("UUID-1", "Foo", "blocked")
        assert len(settings.trusted_volumes) == 1
        assert settings.find_trusted_volume("UUID-1").decision == "blocked"

    def test_trusted_volumes_serialize_roundtrip(self):
        """to_dict / load JSON zachowują listę trusted_volumes."""
        settings = UserSettings()
        settings.add_trusted_volume("UUID-A", "LS-P1", "trusted")
        settings.add_trusted_volume("UUID-B", "Music", "blocked")
        data = settings.to_dict()
        assert "trusted_volumes" in data
        assert len(data["trusted_volumes"]) == 2
        roundtrip = UserSettings(**data)
        assert len(roundtrip.trusted_volumes) == 2
        assert roundtrip.find_trusted_volume("UUID-A").decision == "trusted"
        assert roundtrip.find_trusted_volume("UUID-B").decision == "blocked"
    
    def test_specific_mode_with_volumes(self):
        """Test specific mode with watched volumes."""
        settings = UserSettings()
        settings.watch_mode = "specific"
        settings.watched_volumes = ["SD_CARD", "USB_DRIVE"]
        
        assert settings.watch_mode == "specific"
        assert len(settings.watched_volumes) == 2
        assert "SD_CARD" in settings.watched_volumes
    
    def test_manual_mode(self):
        """Test manual mode."""
        settings = UserSettings()
        settings.watch_mode = "manual"
        
        assert settings.watch_mode == "manual"


class TestUserSettingsAI:
    """Test suite for AI settings (PRO features)."""
    
    def test_ai_disabled_by_default(self):
        """Test that AI summaries are disabled by default."""
        settings = UserSettings()
        assert settings.enable_ai_summaries is False
        assert settings.ai_api_key is None
    
    def test_ai_enabled_with_key(self):
        """Test enabling AI with API key."""
        settings = UserSettings()
        settings.enable_ai_summaries = True
        settings.ai_api_key = "sk-test-key"
        
        assert settings.enable_ai_summaries is True
        assert settings.ai_api_key == "sk-test-key"
    
    def test_ai_settings_save_and_load(self, tmp_path, monkeypatch):
        """Test that AI settings persist."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        
        original = UserSettings()
        original.enable_ai_summaries = True
        original.ai_api_key = "sk-test-key-123"
        original.save()
        
        loaded = UserSettings.load()
        assert loaded.enable_ai_summaries is True
        assert loaded.ai_api_key == "sk-test-key-123"

