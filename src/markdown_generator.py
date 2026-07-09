"""Markdown document generator for transcriptions."""

import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

try:
    from mutagen import File as MutagenFile
    from mutagen.id3 import ID3NoHeaderError
    MUTAGEN_AVAILABLE = True
except ImportError:
    MUTAGEN_AVAILABLE = False

from src.config import config
from src.logger import logger


class MarkdownGenerator:
    """Generate markdown documents with YAML frontmatter from transcripts.
    
    Handles extraction of audio metadata, filename sanitization, and
    creation of Obsidian-ready markdown documents.
    """
    
    def __init__(self):
        """Initialize markdown generator."""
        self.template = config.MD_TEMPLATE
        self.title_max_length = config.TITLE_MAX_LENGTH
    
    def extract_audio_metadata(self, audio_file: Path) -> Dict[str, str]:
        """Extract metadata from audio file.
        
        Attempts to extract recording date and duration from audio file
        metadata. Falls back to file modification time if metadata unavailable.
        
        Args:
            audio_file: Path to audio file
            
        Returns:
            Dict with metadata keys: recording_datetime, duration_seconds,
            duration_formatted, extension, source_file
        """
        metadata = {
            "source_file": audio_file.name,
            "extension": audio_file.suffix.lower(),
            "recording_datetime": None,
            "duration_seconds": None,
            "duration_formatted": "00:00:00"
        }
        
        # Try to extract metadata using mutagen
        if MUTAGEN_AVAILABLE:
            try:
                audio = MutagenFile(str(audio_file))
                if audio is not None:
                    # Extract duration
                    if hasattr(audio, 'info') and hasattr(audio.info, 'length'):
                        duration_sec = int(audio.info.length)
                        metadata["duration_seconds"] = duration_sec
                        metadata["duration_formatted"] = self._format_duration(
                            duration_sec
                        )
                    
                    # Try to extract date from tags
                    if hasattr(audio, 'tags'):
                        date_str = self._extract_date_from_tags(audio.tags)
                        if date_str:
                            try:
                                metadata["recording_datetime"] = datetime.fromisoformat(
                                    date_str
                                )
                            except (ValueError, TypeError):
                                pass
            except (ID3NoHeaderError, Exception) as e:
                logger.debug(f"Could not extract metadata from {audio_file.name}: {e}")
        
        # Fallback to file modification time
        if metadata["recording_datetime"] is None:
            try:
                mtime = datetime.fromtimestamp(audio_file.stat().st_mtime)
                metadata["recording_datetime"] = mtime
            except OSError as e:
                logger.warning(f"Could not get file mtime: {e}")
                metadata["recording_datetime"] = datetime.now()
        
        return metadata
    
    def _extract_date_from_tags(self, tags) -> Optional[str]:
        """Extract date from audio file tags.
        
        Args:
            tags: Mutagen tags object
            
        Returns:
            ISO format date string or None
        """
        # Common tag keys for date
        date_keys = [
            'TDRC',  # ID3v2.4 Recording time
            'TDOR',  # ID3v2.4 Original release time
            'TDRL',  # ID3v2.4 Release time
            'date',
            'DATE',
            'creation_date'
        ]
        
        for key in date_keys:
            try:
                if key in tags:
                    value = tags[key][0] if isinstance(tags[key], list) else tags[key]
                    # Try to parse various date formats
                    if isinstance(value, str):
                        # Try ISO format first
                        if 'T' in value or len(value) >= 10:
                            return value[:19]  # YYYY-MM-DDTHH:MM:SS
            except (KeyError, IndexError, AttributeError):
                continue
        
        return None
    
    def _format_duration(self, seconds: int) -> str:
        """Format duration in seconds to HH:MM:SS format.
        
        Args:
            seconds: Duration in seconds
            
        Returns:
            Formatted duration string
        """
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        secs = seconds % 60
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    
    def create_markdown_document(
        self,
        transcript: str,
        summary: Dict[str, str],
        metadata: Dict[str, str],
        output_dir: Path,
        tags: Optional[List[str]] = None,
        extra_frontmatter: Optional[Dict[str, str]] = None,
        output_filename: Optional[str] = None,
    ) -> Path:
        """Create markdown document from transcript and metadata.
        
        Args:
            transcript: Full transcription text
            summary: Dict with 'title' and 'summary' keys
            metadata: Audio file metadata dict
            output_dir: Directory to save markdown file
            
        Returns:
            Path to created markdown file
            
        Raises:
            IOError: If file cannot be written
        """
        # Generate safe filename; never overwrite an existing note — two
        # same-day recordings can sanitize to the same title.
        filename = output_filename or self._generate_filename(
            summary.get("title", "Nagranie"),
            metadata["recording_datetime"],
        )
        output_path = self._dedupe_output_path(output_dir, filename)
        
        # Format date strings
        date_str = metadata["recording_datetime"].strftime("%Y-%m-%d")
        recording_date_str = metadata["recording_datetime"].isoformat()
        
        # Prepare tag list
        tag_list = tags or ["transcription"]
        tags_str = ", ".join(tag_list)

        extra_frontmatter = extra_frontmatter or {}
        previous_version_line = ""
        if extra_frontmatter.get("previous_version"):
            previous_version_line = (
                f"\nprevious_version: {extra_frontmatter['previous_version']}"
            )

        # Provenance for imported notes (txt/vtt/…). Empty for audio, so the
        # rendered frontmatter stays byte-identical there. Lets digests and the
        # UI tell an imported meeting apart from your own voice note.
        provenance_line = ""
        if extra_frontmatter.get("source_type"):
            provenance_line = f"\nsource_type: {extra_frontmatter['source_type']}"
            if extra_frontmatter.get("origin"):
                provenance_line += f"\norigin: {extra_frontmatter['origin']}"

        # Fill template. Values are substituted VERBATIM — str.format() never
        # re-parses substituted values, only the (code-owned) template — so no
        # escaping is needed. The old brace-doubling "escape" here actively
        # corrupted every note whose content contained literal { or }.
        content = self.template.format(
            title=summary.get("title", "Nagranie"),
            date=date_str,
            recording_date=recording_date_str,
            source_file=metadata["source_file"],
            fingerprint=extra_frontmatter.get("fingerprint", ""),
            source_volume=extra_frontmatter.get("source_volume", ""),
            version=extra_frontmatter.get("version", 1),
            hostname=extra_frontmatter.get("transcribed_on", ""),
            model=extra_frontmatter.get("model", ""),
            language=extra_frontmatter.get("language", ""),
            previous_version_line=previous_version_line,
            provenance_line=provenance_line,
            duration=metadata["duration_formatted"],
            tags=tags_str,
            summary=summary.get("summary", "Brak podsumowania."),
            transcript=transcript,
        )
        
        # Write file
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(content)
            
            logger.info(f"✓ Created markdown document: {output_path.name}")
            return output_path
            
        except IOError as e:
            logger.error(f"Failed to write markdown file: {e}")
            raise
    
    @staticmethod
    def _dedupe_output_path(output_dir: Path, filename: str) -> Path:
        """First non-existing path for *filename*: append " (2)", " (3)"…

        Applies to explicit (``.vN``) filenames too — every caller consumes
        the returned path, so a suffixed name can never desynchronize the
        index, and it only fires on a genuine would-be overwrite.
        """
        candidate = output_dir / filename
        if not candidate.exists():
            return candidate
        stem = Path(filename).stem
        suffix = Path(filename).suffix
        counter = 2
        while True:
            candidate = output_dir / f"{stem} ({counter}){suffix}"
            if not candidate.exists():
                return candidate
            counter += 1

    def _generate_filename(self, title: str, recording_date: datetime) -> str:
        """Generate safe filename from title and date.
        
        Args:
            title: Document title
            recording_date: Recording datetime
            
        Returns:
            Safe filename string (e.g., "2025-11-19_Rozmowa_o_projekcie.md")
        """
        # Sanitize title
        safe_title = self._sanitize_filename(title)
        
        # Truncate if too long
        max_title_length = self.title_max_length
        if len(safe_title) > max_title_length:
            safe_title = safe_title[:max_title_length - 3] + "..."
        
        # Format date (YY-MM-DD for readability)
        date_str = recording_date.strftime("%y-%m-%d")
        
        title_part = safe_title if safe_title else "Nagranie"
        
        return f"{date_str} - {title_part}.md"
    
    def _sanitize_filename(self, title: str) -> str:
        """Sanitize title for use in filename.
        
        Removes invalid characters, normalizes Polish diacritics,
        and converts to safe format.
        
        Args:
            title: Original title
            
        Returns:
            Sanitized title string
        """
        # Polish diacritics normalization map
        polish_map = {
            'ą': 'a', 'ć': 'c', 'ę': 'e', 'ł': 'l', 'ń': 'n',
            'ó': 'o', 'ś': 's', 'ź': 'z', 'ż': 'z',
            'Ą': 'A', 'Ć': 'C', 'Ę': 'E', 'Ł': 'L', 'Ń': 'N',
            'Ó': 'O', 'Ś': 'S', 'Ź': 'Z', 'Ż': 'Z'
        }
        
        # Normalize Polish characters
        normalized = title
        for polish_char, ascii_char in polish_map.items():
            normalized = normalized.replace(polish_char, ascii_char)
        
        # Remove invalid filename characters
        # Keep: letters, numbers, spaces, hyphens
        normalized = re.sub(r'[^\w\s\-]', '', normalized)
        
        # Replace underscores with spaces (prefer readable titles)
        normalized = normalized.replace('_', ' ')
        
        # Collapse multiple spaces
        normalized = re.sub(r'\s+', ' ', normalized)
        
        # Remove leading/trailing spaces and hyphens
        normalized = normalized.strip(' -')
        
        return normalized

