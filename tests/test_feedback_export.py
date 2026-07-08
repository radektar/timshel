"""Tests for the H1 feedback bundle (src/feedback_export.py)."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from src.config import config
from src.feedback_export import NothingToExportError, build_feedback_zip


def _seed_vault(vault: Path) -> None:
    sidecar = vault / config.SIDECAR_DIR_NAME
    sidecar.mkdir(parents=True, exist_ok=True)
    (sidecar / "signal.jsonl").write_text('{"action":"action_taken"}\n', encoding="utf-8")
    (sidecar / "metrics.jsonl").write_text('{"cost_usd":0.01}\n', encoding="utf-8")
    (sidecar / "vocabulary.json").write_text("{}", encoding="utf-8")
    digests = vault / config.DIGEST_DIR_NAME
    digests.mkdir(parents=True, exist_ok=True)
    (digests / "2026-07-08 Synthesis.md").write_text("# digest", encoding="utf-8")


def test_zip_contains_sidecar_digests_and_manifest(tmp_path):
    vault = tmp_path / "vault"
    _seed_vault(vault)
    dest = tmp_path / "out"

    zip_path = build_feedback_zip(vault, dest, timestamp="20260708-1200")

    assert zip_path.name == "Timshel-feedback-20260708-1200.zip"
    with zipfile.ZipFile(zip_path) as zf:
        names = set(zf.namelist())
        assert "manifest.json" in names
        assert "sidecar/signal.jsonl" in names
        assert "sidecar/metrics.jsonl" in names
        assert "sidecar/vocabulary.json" in names
        assert "digests/2026-07-08 Synthesis.md" in names
        manifest = json.loads(zf.read("manifest.json"))
    assert manifest["created"] == "20260708-1200"
    assert manifest["counts"]["digests"] == 1
    assert manifest["counts"]["sidecar_files"] == 3


def test_missing_files_are_tolerated(tmp_path):
    vault = tmp_path / "vault"
    # Only a digest, no sidecar at all.
    digests = vault / config.DIGEST_DIR_NAME
    digests.mkdir(parents=True, exist_ok=True)
    (digests / "d.md").write_text("x", encoding="utf-8")

    zip_path = build_feedback_zip(vault, tmp_path / "out", timestamp="20260708-1300")
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
    assert any(n.startswith("digests/") for n in names)
    assert not any(n.startswith("sidecar/") for n in names)


def test_empty_vault_raises(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    with pytest.raises(NothingToExportError):
        build_feedback_zip(vault, tmp_path / "out", timestamp="20260708-1400")


def test_context_files_alone_do_not_satisfy_the_guard(tmp_path):
    """A glossary created before any digest is NOT exportable evidence."""
    vault = tmp_path / "vault"
    sidecar = vault / config.SIDECAR_DIR_NAME
    sidecar.mkdir(parents=True, exist_ok=True)
    (sidecar / "vocabulary.json").write_text('{"terms":[]}', encoding="utf-8")
    with pytest.raises(NothingToExportError):
        build_feedback_zip(vault, tmp_path / "out", timestamp="20260708-1500")
