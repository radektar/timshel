"""Tests for PRO-gated retranscription versioning behavior."""

from pathlib import Path
from unittest.mock import patch

from src.config.config import Config
from src.config.features import FeatureTier
from src.transcriber import Transcriber
from src.vault_index import IndexEntry


def test_creates_v2_and_v3(tmp_path: Path) -> None:
    """Versioning is available to everyone (tier gating removed)."""
    cfg = Config()
    cfg.TRANSCRIBE_DIR = tmp_path
    transcriber = Transcriber(config=cfg)

    fp = "sha256:file"
    transcriber.vault_index.add(
        fp,
        IndexEntry(
            fingerprint=fp,
            source_filename="file.mp3",
            source_volume="LS-P1",
            markdown_path="file.md",
            versions=[{"version": 1, "markdown_path": "file.md"}],
        ),
    )

    audio = tmp_path / "file.mp3"
    audio.write_bytes(b"hello")
    transcript = tmp_path / "file.txt"

    md_v2 = tmp_path / "file.v2.md"
    md_v3 = tmp_path / "file.v3.md"

    postprocess_calls = []

    def fake_postprocess(
        _audio_file: Path,
        transcript_path: Path,
        fingerprint: str,
        version: int = 1,
        previous_version: str | None = None,
        output_filename: str | None = None,
    ) -> Path:
        postprocess_calls.append(
            {
                "fingerprint": fingerprint,
                "version": version,
                "previous_version": previous_version,
                "output_filename": output_filename,
            }
        )
        if version == 2:
            md_v2.write_text("---\nprevious_version: file.md\n---\n")
            return md_v2
        md_v3.write_text("---\nprevious_version: file.v2.md\n---\n")
        return md_v3

    with patch("src.transcriber.compute_fingerprint", return_value=fp), patch.object(
        transcriber, "_run_macwhisper", return_value=transcript
    ), patch.object(
        transcriber, "_postprocess_transcript", side_effect=fake_postprocess
    ):
        assert transcriber.transcribe_file(audio) is True
        assert transcriber.transcribe_file(audio) is True

    assert md_v2.exists()
    assert md_v3.exists()
    assert "previous_version: file.md" in md_v2.read_text(encoding="utf-8")
    assert "previous_version: file.v2.md" in md_v3.read_text(encoding="utf-8")

    assert len(postprocess_calls) == 2
    assert postprocess_calls[0]["version"] == 2
    assert postprocess_calls[0]["output_filename"] == "file.v2.md"
    assert postprocess_calls[0]["previous_version"] == "file.md"
    assert postprocess_calls[1]["version"] == 3
    assert postprocess_calls[1]["output_filename"] == "file.v3.md"
    assert postprocess_calls[1]["previous_version"] == "file.v2.md"

    entry = transcriber.vault_index.lookup(fp)
    assert entry is not None
    assert len(entry.versions) == 3
    assert entry.versions[1]["markdown_path"] == "file.v2.md"
    assert entry.versions[2]["markdown_path"] == "file.v3.md"

