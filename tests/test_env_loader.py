"""Tests for environment loading utilities."""

from pathlib import Path
from typing import Optional

import os
import importlib
import types


def _reload_env_loader(module_path: str = "src.env_loader") -> types.ModuleType:
    """Reload env_loader module to ensure clean state."""
    if module_path in list(importlib.sys.modules.keys()):
        del importlib.sys.modules[module_path]
    return importlib.import_module(module_path)


def test_load_env_file_reads_values(tmp_path, monkeypatch):
    """Ensure load_env_file loads variables from provided path."""
    env_file = tmp_path / ".env"
    env_file.write_text("ANTHROPIC_API_KEY=test-key-123\n", encoding="utf-8")

    # Ensure variable not set
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    # Reload module to avoid cached state
    env_loader = _reload_env_loader()

    assert env_loader.load_env_file(env_path=env_file) is True
    assert os.getenv("ANTHROPIC_API_KEY") == "test-key-123"


def test_load_env_file_missing_file(monkeypatch):
    """load_env_file should return False when file is absent."""
    monkeypatch.delenv("OLYMPUS_ENV_FILE", raising=False)
    env_loader = _reload_env_loader()

    missing_path = Path("/nonexistent/.env")
    assert env_loader.load_env_file(env_path=missing_path) is False
