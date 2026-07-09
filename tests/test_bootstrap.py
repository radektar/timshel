"""End-to-end tests for bootstrap migration (legacy + Malinche→Timshel)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from src.bootstrap import ensure_ready
from src.ui.constants import APP_VERSION


def _timshel_root(tmp_path: Path) -> Path:
    return tmp_path / "Library" / "Application Support" / "Timshel"


def _malinche_root(tmp_path: Path) -> Path:
    return tmp_path / "Library" / "Application Support" / "Malinche"


def test_ensure_ready_migrates_legacy_layout(tmp_path, monkeypatch):
    """Bootstrap migrates legacy Transrec/olympus assets into the Timshel root."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    transrec_root = tmp_path / "Library" / "Application Support" / "Transrec"
    legacy_root = tmp_path / ".olympus_transcriber"
    legacy_logs = tmp_path / "Library" / "Logs"

    (transrec_root / "bin").mkdir(parents=True, exist_ok=True)
    (transrec_root / "models").mkdir(parents=True, exist_ok=True)
    legacy_root.mkdir(parents=True, exist_ok=True)
    legacy_logs.mkdir(parents=True, exist_ok=True)

    (transrec_root / "bin" / "whisper-cli").write_bytes(b"whisper")
    (transrec_root / "models" / "ggml-small.bin").write_bytes(b"model")
    (transrec_root / "config.json").write_text(
        json.dumps({"watch_mode": "auto", "whisper_model": "medium"}),
        encoding="utf-8",
    )
    (legacy_root / "transcriber.lock").write_text("123\n0", encoding="utf-8")
    (legacy_root / "recordings").mkdir(parents=True, exist_ok=True)
    (legacy_root / "recordings" / "a.mp3").write_bytes(b"audio")
    (tmp_path / ".olympus_transcriber_state.json").write_text(
        json.dumps({"last_sync": "2026-04-20T00:00:00"}),
        encoding="utf-8",
    )
    (legacy_logs / "olympus_transcriber.log").write_text("legacy", encoding="utf-8")

    settings = ensure_ready()

    timshel_root = _timshel_root(tmp_path)
    assert (timshel_root / "bin" / "whisper-cli").exists()
    assert (timshel_root / "models" / "ggml-small.bin").exists()
    assert (timshel_root / "runtime" / "transcriber.lock").exists()
    assert (timshel_root / "recordings" / "a.mp3").exists()
    assert (timshel_root / "state.json").exists()
    assert (timshel_root / "logs" / "timshel.log").exists()

    assert not transrec_root.exists()
    assert not legacy_root.exists()
    assert not (tmp_path / ".olympus_transcriber_state.json").exists()

    assert settings.setup_version == APP_VERSION
    assert settings.legacy_migrated is True


def test_ensure_ready_migrates_malinche_app_support_wholesale(tmp_path, monkeypatch):
    """A pre-rename Malinche root moves wholesale to Timshel — no re-download."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    malinche_root = _malinche_root(tmp_path)
    (malinche_root / "bin").mkdir(parents=True, exist_ok=True)
    (malinche_root / "models").mkdir(parents=True, exist_ok=True)
    (malinche_root / "bin" / "whisper-cli").write_bytes(b"whisper")
    (malinche_root / "models" / "ggml-small.bin").write_bytes(b"model")
    (malinche_root / "config.json").write_text(
        json.dumps(
            {
                "output_dir": str(tmp_path / "vault"),
                "ai_api_key": "sk-ant-secret",
                "legacy_migrated": True,
                "setup_version": APP_VERSION,
            }
        ),
        encoding="utf-8",
    )

    settings = ensure_ready()

    timshel_root = _timshel_root(tmp_path)
    # Real data preserved intact under the new root.
    assert (timshel_root / "bin" / "whisper-cli").read_bytes() == b"whisper"
    assert (timshel_root / "models" / "ggml-small.bin").read_bytes() == b"model"
    # Config (with the API key + vault path) survived the move.
    assert settings.ai_api_key == "sk-ant-secret"
    assert Path(settings.output_dir) == tmp_path / "vault"
    # Old root is gone.
    assert not malinche_root.exists()


def test_app_support_merge_when_both_roots_exist(tmp_path, monkeypatch):
    """Both roots present: the real config moves even past an empty Timshel dir."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    malinche_root = _malinche_root(tmp_path)
    timshel_root = _timshel_root(tmp_path)
    malinche_root.mkdir(parents=True, exist_ok=True)
    # A fresh Timshel root that only holds an EMPTY logs dir (as the logger
    # would create at import), plus NO config yet.
    (timshel_root / "logs").mkdir(parents=True, exist_ok=True)

    (malinche_root / "config.json").write_text(
        json.dumps({"ai_api_key": "sk-ant-keep", "legacy_migrated": True}),
        encoding="utf-8",
    )
    (malinche_root / "logs").mkdir(parents=True, exist_ok=True)
    (malinche_root / "logs" / "old.log").write_text("hi", encoding="utf-8")

    settings = ensure_ready()

    assert settings.ai_api_key == "sk-ant-keep"
    # The non-empty real logs dir moved in past the empty placeholder.
    assert (timshel_root / "logs" / "old.log").exists()
    assert not malinche_root.exists()


def test_ensure_ready_migrates_vault_sidecars(tmp_path, monkeypatch):
    """.malinche / Malinche Digests / Malinche Recall rename to Timshel names."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    vault = tmp_path / "vault"
    (vault / ".malinche").mkdir(parents=True, exist_ok=True)
    (vault / ".malinche" / "signal.jsonl").write_text("{}\n", encoding="utf-8")
    (vault / "Malinche Digests").mkdir(parents=True, exist_ok=True)
    (vault / "Malinche Digests" / "d.md").write_text("digest", encoding="utf-8")
    (vault / "Malinche Recall").mkdir(parents=True, exist_ok=True)

    timshel_root = _timshel_root(tmp_path)
    timshel_root.mkdir(parents=True, exist_ok=True)
    (timshel_root / "config.json").write_text(
        json.dumps(
            {
                "output_dir": str(vault),
                "legacy_migrated": True,
                "setup_version": APP_VERSION,
            }
        ),
        encoding="utf-8",
    )

    ensure_ready()

    assert (vault / ".timshel" / "signal.jsonl").exists()
    assert (vault / "Timshel Digests" / "d.md").exists()
    assert (vault / "Timshel Recall").exists()
    assert not (vault / ".malinche").exists()
    assert not (vault / "Malinche Digests").exists()


def test_ensure_ready_is_idempotent(tmp_path, monkeypatch):
    """Second bootstrap run should not perform file moves."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    # Prepare already-migrated config under the Timshel root.
    timshel_root = _timshel_root(tmp_path)
    timshel_root.mkdir(parents=True, exist_ok=True)
    (timshel_root / "config.json").write_text("{}", encoding="utf-8")

    ensure_ready()

    with patch("src.bootstrap.shutil.move") as move_mock:
        ensure_ready()

    move_mock.assert_not_called()


def test_ensure_ready_skips_migration_when_flag_set(tmp_path, monkeypatch):
    """Fast path short-circuits before any legacy scan or cleanup."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    timshel_root = _timshel_root(tmp_path)
    timshel_root.mkdir(parents=True, exist_ok=True)
    (timshel_root / "config.json").write_text(
        json.dumps({"transrec_migrated": True, "setup_version": APP_VERSION}),
        encoding="utf-8",
    )

    with patch("src.bootstrap._move_with_backup") as move_mock, patch(
        "src.bootstrap._cleanup_legacy_root"
    ) as cleanup_mock:
        settings = ensure_ready()

    move_mock.assert_not_called()
    cleanup_mock.assert_not_called()
    assert settings.legacy_migrated is True


def test_ensure_ready_still_saves_setup_version_on_fast_path(tmp_path, monkeypatch):
    """Fast path bumps setup_version when it lags APP_VERSION."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    timshel_root = _timshel_root(tmp_path)
    timshel_root.mkdir(parents=True, exist_ok=True)
    (timshel_root / "config.json").write_text(
        json.dumps({"transrec_migrated": True, "setup_version": "0.0.0-stale"}),
        encoding="utf-8",
    )

    settings = ensure_ready()

    assert settings.setup_version == APP_VERSION
    on_disk = json.loads((timshel_root / "config.json").read_text(encoding="utf-8"))
    assert on_disk["setup_version"] == APP_VERSION
