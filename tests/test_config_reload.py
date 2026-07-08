"""Regression tests for live config hot-reload (``reload_config``).

The Config singleton caches settings-derived runtime fields (notably
``LLM_API_KEY`` and the AI enable flags) at construction and never re-reads
them. Before ``reload_config`` existed, a key fixed/changed in Settings only
took effect on the next app launch — the running daemon kept sending the stale
key and every AI feature failed with a silent 401. These tests pin the
behaviour that a save is now picked up live.
"""

import json
import sys
from pathlib import Path

import pytest

import src.config.config  # noqa: F401 — ensure the submodule is importable
from src.config import config as config_proxy
from src.config.config import reload_config
from src.config.settings import UserSettings

# The package __init__ binds a `config` proxy that shadows the `config.py`
# submodule as an attribute, so `src.config.config` via attribute access is the
# proxy. Reach the real module (with the `_config_instance` global) by key.
_config_mod = sys.modules["src.config.config"]


@pytest.fixture
def write_settings(tmp_path, monkeypatch):
    """Isolate config.json under a temp HOME; yield a config.json writer.

    The writer mirrors what the Settings window does on save. On teardown the
    temp-home singleton is dropped so unrelated tests rebuild from the real home.
    """
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    cfg_dir = tmp_path / "Library" / "Application Support" / "Timshel"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    path = UserSettings.config_path()
    assert path == cfg_dir / "config.json"

    def _write(api_key):
        path.write_text(
            json.dumps({"output_dir": str(tmp_path / "out"), "ai_api_key": api_key}),
            encoding="utf-8",
        )

    yield _write
    _config_mod._config_instance = None


def test_reload_config_picks_up_changed_key(write_settings):
    """A key edited on disk is reflected live after reload_config — no restart."""
    write_settings("sk-ant-old-AAAA")
    first = reload_config()
    assert first.LLM_API_KEY == "sk-ant-old-AAAA"
    assert first.ENABLE_SUMMARIZATION is True

    # User fixes the key in Settings (rewrites config.json), then we hot-reload.
    write_settings("sk-ant-new-BBBB")
    second = reload_config()

    assert second is not first  # a genuinely fresh instance
    assert second.LLM_API_KEY == "sk-ant-new-BBBB"
    assert config_proxy.LLM_API_KEY == "sk-ant-new-BBBB"  # proxy resolves to it


def test_reload_config_disables_ai_when_key_removed(write_settings):
    """Clearing the key live disables summaries and tags (key presence gates)."""
    write_settings("sk-ant-key-CCCC")
    assert reload_config().ENABLE_SUMMARIZATION is True

    write_settings(None)
    reloaded = reload_config()
    assert reloaded.LLM_API_KEY is None
    assert reloaded.ENABLE_SUMMARIZATION is False
    assert reloaded.ENABLE_LLM_TAGGING is False
