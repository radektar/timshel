"""Daemon start must read the freshly-persisted UserSettings, not a stale
Config singleton.

Regression: the singleton is built at app launch, BEFORE the wizard persists
the user's choices. Starting the daemon straight after "Wizard finished"
therefore used the default output folder — the user picked a vault in the
wizard, yet every note landed in ~/Documents/Timshel. `_start_daemon` is the
single choke point every daemon start goes through, so it refreshes config
itself instead of relying on each caller to remember `reload_config()`.
"""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import src.config.config  # noqa: F401 — ensure the submodule is importable
from src.config import config as config_proxy
from src.config.config import reload_config
from src.config.settings import UserSettings
from src.menu_app import TimshelMenuApp

_config_mod = sys.modules["src.config.config"]


@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    """Temp-HOME config.json writer; drops the singleton on teardown."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    cfg_dir = tmp_path / "Library" / "Application Support" / "Timshel"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    path = UserSettings.config_path()

    def _write(output_dir: Path) -> None:
        path.write_text(
            json.dumps({"output_dir": str(output_dir)}), encoding="utf-8"
        )

    yield _write
    _config_mod._config_instance = None


def _app() -> TimshelMenuApp:
    app = TimshelMenuApp.__new__(TimshelMenuApp)
    app._running = False
    app.daemon_thread = None
    return app


def test_start_daemon_picks_up_folder_saved_after_config_was_built(
    isolated_config, tmp_path
):
    default_dir = tmp_path / "Documents" / "Timshel"
    chosen_dir = tmp_path / "Vault" / "Notes"

    # App launch: singleton built while config.json still has the default.
    isolated_config(default_dir)
    reload_config()
    assert Path(config_proxy.TRANSCRIBE_DIR) == default_dir

    # Wizard: user picks a folder, settings.save() rewrites config.json —
    # but the in-memory singleton is still the stale launch-time one.
    isolated_config(chosen_dir)
    assert Path(config_proxy.TRANSCRIBE_DIR) == default_dir

    app = _app()
    with patch("src.menu_app.threading.Thread", return_value=MagicMock()):
        app._start_daemon()

    # The daemon must see the wizard's choice, not the launch-time default.
    assert Path(config_proxy.TRANSCRIBE_DIR) == chosen_dir


def test_start_daemon_noop_when_already_running(isolated_config, tmp_path):
    isolated_config(tmp_path / "a")
    reload_config()
    isolated_config(tmp_path / "b")

    app = _app()
    app._running = True
    with patch("src.menu_app.threading.Thread", return_value=MagicMock()) as thread:
        app._start_daemon()

    # Guard path: no thread spawned, no reload either.
    thread.assert_not_called()
    assert Path(config_proxy.TRANSCRIBE_DIR) == tmp_path / "a"
