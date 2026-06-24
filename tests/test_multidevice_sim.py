"""Simulated multi-device tests on a single machine."""

from pathlib import Path
from unittest.mock import patch

from src.config.config import Config
from src.transcriber import Transcriber
from src.vault_index import IndexEntry, VaultIndex


def test_device_b_versions_after_device_a_transcribed(tmp_path: Path) -> None:
    """Tier gating removed: device B re-processing a synced fingerprint now
    creates a new version (v2) instead of skipping.

    Versioning is available to everyone; cross-device dedup is no longer a
    tier-gated behaviour. (Previously only the FREE tier skipped here, while the
    beta default — PRO — already versioned.)
    """
    vault_dir = tmp_path / "iCloudVault"
    vault_dir.mkdir()

    fingerprint = "sha256:deadbeef"

    # Device A writes the entry that would later be synced through iCloud.
    index_a = VaultIndex(vault_dir)
    index_a.load()
    index_a.add(
        fingerprint,
        IndexEntry(
            fingerprint=fingerprint,
            source_filename="sample.m4a",
            source_volume="Recordings",
            markdown_path="sample.md",
            versions=[{"version": 1, "markdown_path": "sample.md"}],
        ),
    )

    # Device B starts with a fresh VaultIndex instance (simulating another Mac).
    index_b = VaultIndex(vault_dir)
    index_b.load()
    assert index_b.lookup(fingerprint) is not None

    cfg = Config()
    cfg.TRANSCRIBE_DIR = vault_dir
    transcriber_b = Transcriber(config=cfg)
    transcriber_b.whisper_available = True

    audio = vault_dir / "sample.m4a"
    audio.write_bytes(b"same audio")
    transcript = vault_dir / "sample.txt"

    md_v2 = vault_dir / "sample.v2.md"

    def fake_postprocess(
        _audio_file: Path,
        _transcript_path: Path,
        fingerprint: str,
        version: int = 1,
        previous_version: str | None = None,
        output_filename: str | None = None,
    ) -> Path:
        md_v2.write_text("---\nprevious_version: sample.md\n---\n")
        return md_v2

    with patch(
        "src.transcriber.compute_fingerprint", return_value=fingerprint
    ), patch.object(
        transcriber_b, "_run_macwhisper", return_value=transcript
    ) as run_mock, patch.object(
        transcriber_b, "_postprocess_transcript", side_effect=fake_postprocess
    ):
        assert transcriber_b.transcribe_file(audio) is True
        run_mock.assert_called_once()

    assert md_v2.exists()
