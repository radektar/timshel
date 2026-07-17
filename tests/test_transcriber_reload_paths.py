"""reload_paths() re-points the vault index after an output-folder change.

Regression: vault_index is bound to TRANSCRIBE_DIR at construction, so a folder
change in Settings left dedup/lookup reading the OLD folder while writes went to
the new one.
"""

from pathlib import Path

from src.transcriber import Transcriber


class _FakeConfig:
    def __init__(self, transcribe_dir: Path):
        self.TRANSCRIBE_DIR = transcribe_dir


def _make_transcriber(tmp_path: Path) -> Transcriber:
    old = tmp_path / "old_vault"
    old.mkdir()
    t = Transcriber.__new__(Transcriber)  # skip heavy __init__
    t.config = _FakeConfig(old)
    from src.vault_index import VaultIndex

    t.vault_index = VaultIndex(old)
    t.vault_index.load()
    return t


def test_reload_paths_repoints_index_to_new_folder(tmp_path):
    t = _make_transcriber(tmp_path)
    assert Path(t.vault_index.vault_dir) == tmp_path / "old_vault"

    new = tmp_path / "new_vault"
    new.mkdir()
    t.config.TRANSCRIBE_DIR = new
    t.reload_paths()

    assert Path(t.vault_index.vault_dir) == new


def test_reload_paths_is_noop_when_folder_unchanged(tmp_path):
    t = _make_transcriber(tmp_path)
    index_before = t.vault_index
    t.reload_paths()  # same folder
    assert t.vault_index is index_before  # not rebuilt
