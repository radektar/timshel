"""Unit tests for UserSettings."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from src.config.settings import UserSettings
from src.config.defaults import (
    DEFAULT_WATCH_MODE,
    DEFAULT_LANGUAGE,
    DEFAULT_OUTPUT_DIR,
)


class TestUserSettings:
    """Testy dla klasy UserSettings."""

    def test_default_values(self):
        """Domyślne wartości są poprawne."""
        settings = UserSettings()
        assert settings.watch_mode == DEFAULT_WATCH_MODE
        assert settings.language == DEFAULT_LANGUAGE
        assert settings.output_dir == DEFAULT_OUTPUT_DIR
        assert settings.setup_completed is False
        assert settings.watched_volumes == []
        assert settings.enable_ai_summaries is False

    def test_save_load_roundtrip(self, tmp_path, monkeypatch):
        """Zapis i odczyt zachowuje wszystkie wartości."""
        # Monkeypatch config_path
        config_file = tmp_path / "config.json"
        monkeypatch.setattr(
            UserSettings, "config_path", staticmethod(lambda: config_file)
        )

        settings = UserSettings(
            watch_mode="specific",
            language="en",
            watched_volumes=["LS-P1", "ZOOM-H6"],
            setup_completed=True,
        )
        settings.save()

        loaded = UserSettings.load()
        assert loaded.watch_mode == "specific"
        assert loaded.language == "en"
        assert loaded.watched_volumes == ["LS-P1", "ZOOM-H6"]
        assert loaded.setup_completed is True

    def test_load_nonexistent_file(self, tmp_path, monkeypatch):
        """Brak pliku zwraca domyślne ustawienia."""
        config_file = tmp_path / "nonexistent.json"
        monkeypatch.setattr(
            UserSettings, "config_path", staticmethod(lambda: config_file)
        )

        settings = UserSettings.load()
        assert settings.watch_mode == DEFAULT_WATCH_MODE  # default
        assert settings.language == DEFAULT_LANGUAGE
        assert settings.setup_completed is False

    def test_save_creates_directory(self, tmp_path, monkeypatch):
        """Save tworzy katalog jeśli nie istnieje."""
        config_file = tmp_path / "subdir" / "config.json"
        monkeypatch.setattr(
            UserSettings, "config_path", staticmethod(lambda: config_file)
        )

        settings = UserSettings()
        settings.save()

        assert config_file.exists()
        assert config_file.parent.exists()

    def test_config_path(self):
        """Ścieżka wskazuje na właściwą lokalizację."""
        path = UserSettings.config_path()
        assert "Application Support" in str(path)
        assert "Malinche" in str(path)
        assert path.name == "config.json"

    def test_load_invalid_json(self, tmp_path, monkeypatch):
        """Nieprawidłowy JSON zwraca domyślne ustawienia."""
        config_file = tmp_path / "config.json"
        monkeypatch.setattr(
            UserSettings, "config_path", staticmethod(lambda: config_file)
        )

        # Zapisz nieprawidłowy JSON
        config_file.parent.mkdir(parents=True, exist_ok=True)
        config_file.write_text("invalid json {")

        settings = UserSettings.load()
        assert settings.watch_mode == DEFAULT_WATCH_MODE  # fallback to default





class TestUserSettingsMutate:
    """UserSettings.mutate — atomic load→fn→save under the write lock."""

    def test_mutate_serializes_writers(self, tmp_path, monkeypatch):
        """Writer B must not start until writer A's load→fn→save finished."""
        import threading

        config_file = tmp_path / "config.json"
        monkeypatch.setattr(
            UserSettings, "config_path", staticmethod(lambda: config_file)
        )

        order = []
        a_inside = threading.Event()
        a_release = threading.Event()

        def fn_a(settings):
            order.append("a-start")
            a_inside.set()
            a_release.wait(timeout=5)
            settings.add_trusted_volume("UUID-A", "DiskA", "trusted")
            order.append("a-end")

        def fn_b(settings):
            order.append("b-start")
            settings.add_trusted_volume("UUID-B", "DiskB", "blocked")
            order.append("b-end")

        t_a = threading.Thread(target=lambda: UserSettings.mutate(fn_a))
        t_a.start()
        assert a_inside.wait(timeout=5)

        t_b = threading.Thread(target=lambda: UserSettings.mutate(fn_b))
        t_b.start()
        a_release.set()
        t_a.join(timeout=5)
        t_b.join(timeout=5)

        assert order == ["a-start", "a-end", "b-start", "b-end"]
        final = UserSettings.load()
        assert final.find_trusted_volume("UUID-A") is not None
        assert final.find_trusted_volume("UUID-B") is not None

    def test_concurrent_mutates_both_land(self, tmp_path, monkeypatch):
        """Two concurrent persists of different volumes must BOTH survive —
        the bare load-modify-save this replaces was last-writer-wins."""
        import threading

        config_file = tmp_path / "config.json"
        monkeypatch.setattr(
            UserSettings, "config_path", staticmethod(lambda: config_file)
        )

        barrier = threading.Barrier(2)

        def persist(uuid, name):
            barrier.wait(timeout=5)
            UserSettings.mutate(
                lambda s: s.add_trusted_volume(uuid, name, "trusted")
            )

        threads = [
            threading.Thread(target=persist, args=(f"UUID-{i}", f"Disk{i}"))
            for i in range(2)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        final = UserSettings.load()
        assert final.find_trusted_volume("UUID-0") is not None
        assert final.find_trusted_volume("UUID-1") is not None
