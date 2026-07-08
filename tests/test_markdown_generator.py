"""Tests for markdown generator module."""

import pytest
from pathlib import Path
from datetime import datetime
from unittest.mock import Mock, patch, MagicMock
from src.markdown_generator import MarkdownGenerator
from src.config import config


@pytest.fixture
def generator():
    """Create MarkdownGenerator instance."""
    return MarkdownGenerator()


@pytest.fixture
def sample_audio_file(tmp_path):
    """Create sample audio file for testing."""
    audio_file = tmp_path / "test_recording.mp3"
    audio_file.touch()
    return audio_file


@pytest.fixture
def sample_transcript():
    """Sample transcript text."""
    return """To jest przykładowa transkrypcja nagrania.
Zawiera kilka zdań do testowania funkcjonalności.
Trzecie zdanie dla pełności przykładu."""


@pytest.fixture
def sample_summary():
    """Sample summary dict with markdown format."""
    return {
        "title": "Rozmowa o projekcie",
        "summary": """## Podsumowanie

Dyskusja na temat implementacji nowych funkcji w systemie. Omówiono kluczowe aspekty projektu.

## Lista działań (To-do)

- Przygotować dokumentację techniczną
- Skontaktować się z zespołem deweloperskim"""
    }


@pytest.fixture
def sample_metadata():
    """Sample metadata dict."""
    return {
        "source_file": "test_recording.mp3",
        "extension": ".mp3",
        "recording_datetime": datetime(2025, 11, 19, 14, 30, 0),
        "duration_seconds": 900,
        "duration_formatted": "00:15:00"
    }


class TestExtractAudioMetadata:
    """Test audio metadata extraction."""
    
    def test_extract_metadata_fallback_to_mtime(
        self, generator, sample_audio_file
    ):
        """Test metadata extraction falls back to file mtime."""
        metadata = generator.extract_audio_metadata(sample_audio_file)
        
        assert metadata["source_file"] == "test_recording.mp3"
        assert metadata["extension"] == ".mp3"
        assert metadata["recording_datetime"] is not None
        assert isinstance(metadata["recording_datetime"], datetime)
    
    @patch('src.markdown_generator.MUTAGEN_AVAILABLE', True)
    @patch('src.markdown_generator.MutagenFile')
    def test_extract_metadata_with_mutagen(
        self, mock_mutagen_file, generator, sample_audio_file
    ):
        """Test metadata extraction with mutagen."""
        # Mock mutagen file
        mock_audio = MagicMock()
        mock_audio.info.length = 1200  # 20 minutes
        mock_audio.tags = {}
        mock_mutagen_file.return_value = mock_audio
        
        metadata = generator.extract_audio_metadata(sample_audio_file)
        
        assert metadata["duration_seconds"] == 1200
        assert metadata["duration_formatted"] == "00:20:00"
    
    def test_format_duration(self, generator):
        """Test duration formatting."""
        assert generator._format_duration(0) == "00:00:00"
        assert generator._format_duration(65) == "00:01:05"
        assert generator._format_duration(3665) == "01:01:05"
        assert generator._format_duration(900) == "00:15:00"


class TestSanitizeFilename:
    """Test filename sanitization."""
    
    def test_sanitize_basic(self, generator):
        """Test basic filename sanitization."""
        result = generator._sanitize_filename("Test Title")
        assert result == "Test Title"
    
    def test_sanitize_polish_chars(self, generator):
        """Test Polish character normalization."""
        result = generator._sanitize_filename("Rozmowa o projekcie")
        assert "ą" not in result
        assert "ć" not in result
        assert "_" not in result
    
    def test_sanitize_special_chars(self, generator):
        """Test removal of special characters."""
        result = generator._sanitize_filename("Test@#$%^&*()Title")
        assert "@" not in result
        assert "#" not in result
        assert "Test" in result
        assert "Title" in result
    
    def test_sanitize_multiple_spaces(self, generator):
        """Test handling of multiple spaces."""
        result = generator._sanitize_filename("Test    Title")
        assert "  " not in result
        assert result == "Test Title"
    
    def test_sanitize_leading_trailing_underscores(self, generator):
        """Test removal of leading/trailing underscores."""
        result = generator._sanitize_filename("_Test_Title_")
        assert result == "Test Title"


class TestGenerateFilename:
    """Test filename generation."""
    
    def test_generate_filename_basic(self, generator):
        """Test basic filename generation."""
        title = "Test Title"
        date = datetime(2025, 11, 19, 14, 30, 0)
        
        filename = generator._generate_filename(title, date)
        
        assert filename == "25-11-19 - Test Title.md"
    
    def test_generate_filename_long_title(self, generator):
        """Test filename generation with long title."""
        long_title = "A" * 200
        date = datetime(2025, 11, 19)
        
        filename = generator._generate_filename(long_title, date)
        
        # Should be truncated
        assert len(filename) < 300  # Reasonable limit
        assert filename.endswith(".md")
    
    def test_generate_filename_empty_title(self, generator):
        """Test filename generation with empty title."""
        date = datetime(2025, 11, 19)
        
        filename = generator._generate_filename("", date)
        
        assert filename == "25-11-19 - Nagranie.md"


class TestCreateMarkdownDocument:
    """Test markdown document creation."""
    
    def test_create_document_success(
        self, generator, sample_transcript, sample_summary,
        sample_metadata, tmp_path
    ):
        """Test successful markdown document creation."""
        output_dir = tmp_path / "output"
        
        md_path = generator.create_markdown_document(
            transcript=sample_transcript,
            summary=sample_summary,
            metadata=sample_metadata,
            output_dir=output_dir
        )
        
        assert md_path.exists()
        assert md_path.suffix == ".md"
        
        # Read and verify content
        content = md_path.read_text(encoding='utf-8')
        assert "---" in content  # YAML frontmatter
        assert "title:" in content
        assert sample_summary["title"] in content
        assert "## Podsumowanie" in content
        assert "## Lista działań (To-do)" in content
        assert sample_summary["summary"] in content
        assert "## Transkrypcja" in content
        assert sample_transcript in content
    
    def test_create_document_collision_appends_numbered_suffix(
        self, generator, sample_transcript, sample_summary,
        sample_metadata, tmp_path
    ):
        """Two same-day recordings with colliding titles must NOT overwrite:
        the second gets a ' (2)' suffix and both contents survive."""
        output_dir = tmp_path / "output"

        first = generator.create_markdown_document(
            transcript="pierwsze nagranie",
            summary=sample_summary,
            metadata=sample_metadata,
            output_dir=output_dir,
        )
        second = generator.create_markdown_document(
            transcript="drugie nagranie",
            summary=sample_summary,
            metadata=sample_metadata,
            output_dir=output_dir,
        )

        assert first != second
        assert second.stem.endswith(" (2)")
        assert "pierwsze nagranie" in first.read_text(encoding="utf-8")
        assert "drugie nagranie" in second.read_text(encoding="utf-8")

    def test_create_document_collision_third_copy(
        self, generator, sample_transcript, sample_summary,
        sample_metadata, tmp_path
    ):
        """A third collision gets ' (3)'."""
        output_dir = tmp_path / "output"
        paths = [
            generator.create_markdown_document(
                transcript=f"nagranie {i}",
                summary=sample_summary,
                metadata=sample_metadata,
                output_dir=output_dir,
            )
            for i in range(3)
        ]
        assert paths[2].stem.endswith(" (3)")
        assert len({p.name for p in paths}) == 3

    def test_create_document_explicit_filename_deduped(
        self, generator, sample_transcript, sample_summary,
        sample_metadata, tmp_path
    ):
        """An explicit output_filename (.vN path) colliding with an existing
        file is suffixed too; the original is untouched."""
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        existing = output_dir / "rec.v2.md"
        existing.write_text("oryginał", encoding="utf-8")

        md_path = generator.create_markdown_document(
            transcript=sample_transcript,
            summary=sample_summary,
            metadata=sample_metadata,
            output_dir=output_dir,
            output_filename="rec.v2.md",
        )

        assert md_path.name == "rec.v2 (2).md"
        assert existing.read_text(encoding="utf-8") == "oryginał"

    def test_create_document_preserves_braces_in_content(
        self, generator, sample_summary, sample_metadata, tmp_path
    ):
        """Literal braces in transcript/summary/title must round-trip
        unchanged — the old escaping doubled them in the written note."""
        output_dir = tmp_path / "output"
        transcript = 'kod: {"a": 1} i {nawiasy} w tekście'
        summary = {
            "title": "Tytuł {z klamrą}",
            "summary": 'ustaw {"mode": 1}',
        }

        md_path = generator.create_markdown_document(
            transcript=transcript,
            summary=summary,
            metadata=sample_metadata,
            output_dir=output_dir,
        )

        content = md_path.read_text(encoding="utf-8")
        assert 'kod: {"a": 1} i {nawiasy} w tekście' in content
        assert 'ustaw {"mode": 1}' in content
        assert "Tytuł {z klamrą}" in content
        assert "{{" not in content and "}}" not in content

    def test_create_document_missing_summary(
        self, generator, sample_transcript, sample_metadata, tmp_path
    ):
        """Test document creation with missing summary."""
        output_dir = tmp_path / "output"
        incomplete_summary = {"title": "Test"}
        
        md_path = generator.create_markdown_document(
            transcript=sample_transcript,
            summary=incomplete_summary,
            metadata=sample_metadata,
            output_dir=output_dir
        )
        
        assert md_path.exists()
        content = md_path.read_text(encoding='utf-8')
        assert "Brak podsumowania" in content

    def test_create_document_with_custom_tags(
        self,
        generator,
        sample_transcript,
        sample_summary,
        sample_metadata,
        tmp_path
    ):
        """Document should render provided tags in YAML frontmatter."""
        output_dir = tmp_path / "output"

        md_path = generator.create_markdown_document(
            transcript=sample_transcript,
            summary=sample_summary,
            metadata=sample_metadata,
            output_dir=output_dir,
            tags=["transcription", "sauna", "zdrowie"]
        )

        content = md_path.read_text(encoding='utf-8')
        assert "tags: [transcription, sauna, zdrowie]" in content
    
    def test_create_document_io_error(
        self, generator, sample_transcript, sample_summary,
        sample_metadata, tmp_path
    ):
        """Test handling of IO errors."""
        # Create read-only directory
        output_dir = tmp_path / "readonly"
        output_dir.mkdir()
        output_dir.chmod(0o444)  # Read-only
        
        try:
            with pytest.raises(IOError):
                generator.create_markdown_document(
                    transcript=sample_transcript,
                    summary=sample_summary,
                    metadata=sample_metadata,
                    output_dir=output_dir
                )
        finally:
            # Restore permissions for cleanup
            output_dir.chmod(0o755)

