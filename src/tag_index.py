"""Utilities for indexing existing tags from markdown files."""

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set
import re

from src.config import config
from src.logger import logger
from src.markdown_frontmatter import parse_frontmatter

# The tag THIS app writes on every note it generates (transcriber.py seeds
# the list with it, markdown_generator falls back to it) — LLM tags are
# appended on top. Structural, never a thread between notes: connection
# scoring must be able to tell it apart from a tag the user's material
# actually shares. Single source so the two writers and the reader agree.
GENERATED_TAG = "transcription"

# Frontmatter ``type`` values that mark a note as NOT the user's own material:
# generated digests (pre-rename marker included, as in
# ``connections.candidate_assembly.load_corpus``) and hand-made redirect stubs,
# whose only content is a link to the note that moved. Shared by the tag index
# and the glossary so both agree on what counts as a source note.
NON_SOURCE_TYPES = frozenset({"timshel-digest", "malinche-digest", "redirect"})


@dataclass
class TagIndex:
    """Index tags that already exist in markdown files."""

    root_dir: Optional[Path] = None
    _index: Optional[Dict[str, str]] = None
    # How many notes carry each normalized tag. Filled by build_index; drives
    # existing_tags_ranked so the prompt cap keeps the *reusable* tags.
    _df: Counter = field(default_factory=Counter)

    def __post_init__(self) -> None:
        """Set default root directory."""
        if self.root_dir is None:
            self.root_dir = config.TRANSCRIBE_DIR

    @staticmethod
    def normalize_tag(tag: str) -> str:
        """Normalize tag for deduplication."""
        polish_map = {
            "ą": "a",
            "ć": "c",
            "ę": "e",
            "ł": "l",
            "ń": "n",
            "ó": "o",
            "ś": "s",
            "ź": "z",
            "ż": "z",
            "Ą": "A",
            "Ć": "C",
            "Ę": "E",
            "Ł": "L",
            "Ń": "N",
            "Ó": "O",
            "Ś": "S",
            "Ź": "Z",
            "Ż": "Z",
        }
        normalized = tag.strip()
        for source, target in polish_map.items():
            normalized = normalized.replace(source, target)
        normalized = normalized.lower()
        normalized = re.sub(r"\s+", " ", normalized)
        return normalized.strip()

    @staticmethod
    def sanitize_tag_value(tag: str) -> str:
        """Convert tag into Obsidian-friendly form."""
        normalized = TagIndex.normalize_tag(tag)
        if not normalized:
            return ""

        sanitized = normalized.replace(" ", "-")
        sanitized = re.sub(r"[^a-z0-9_-]", "", sanitized)
        sanitized = re.sub(r"[-_]{2,}", "-", sanitized)
        sanitized = sanitized.strip("-_")
        return sanitized

    def build_index(self, force_refresh: bool = False) -> Dict[str, str]:
        """Build mapping of normalized tag to original value.

        TOP-LEVEL notes only, matching
        :func:`src.connections.candidate_assembly.load_corpus` and
        :class:`src.vocabulary.VocabularyIndex`. The subfolders hold what the
        app wrote about itself — generated digests and, in
        ``.timshel/resummarize-backup``, whole COPIES of notes. Measured on a
        real vault, a recursive scan gave 704 distinct tags instead of 488:
        216 existed only in backups, ``transcription`` counted 311 times for
        153 notes, and the tagger's ``ISTNIEJĄCE TAGI`` list — capped and
        ordered by document frequency — carried ``malinche-digest`` while 35
        of its 150 slots held tags no live note has. The prompt tells the
        model to reuse such a tag EXACTLY, and ``signal_tags`` only strips
        ``GENERATED_TAG``, so a digest marker landing on a user note would
        become a full connection signal.
        """
        if self._index is not None and not force_refresh:
            return self._index

        self._index = {}
        self._df = Counter()
        root = self.root_dir
        if not root or not root.exists():
            logger.debug("TagIndex root directory missing: %s", root)
            return self._index

        for md_path in sorted(root.glob("*.md")):
            try:
                with md_path.open("r", encoding="utf-8") as handle:
                    head = "".join(handle.readline() for _ in range(40))
            except OSError as exc:
                logger.warning(
                    "Could not read markdown file %s for TagIndex: %s",
                    md_path,
                    exc,
                )
                continue

            frontmatter = parse_frontmatter(head)
            if frontmatter.get("type") in NON_SOURCE_TYPES:
                # A stray digest / redirect stub at top level. Its tags are the
                # app's own bookkeeping, not the user's vocabulary.
                continue

            tags_value = frontmatter.get("tags", "").strip()
            if tags_value.startswith("[") and tags_value.endswith("]"):
                tags_value = tags_value[1:-1]
            seen_here: Set[str] = set()
            for raw_tag in tags_value.split(","):
                cleaned = raw_tag.strip().strip('"').strip("'")
                if not cleaned:
                    continue
                sanitized = self.sanitize_tag_value(cleaned)
                if not sanitized:
                    continue
                self._index.setdefault(sanitized, sanitized)
                # Document frequency: notes, not occurrences.
                if sanitized not in seen_here:
                    seen_here.add(sanitized)
                    self._df[sanitized] += 1

        return self._index

    def existing_tags(self, force_refresh: bool = False) -> List[str]:
        """Return original tags from index."""
        return list(self.build_index(force_refresh).values())

    def existing_tags_ranked(self, force_refresh: bool = False) -> List[str]:
        """Existing tags ordered by document frequency, most-used first.

        The tagger prompt is capped (``MAX_EXISTING_TAGS_IN_PROMPT``), and in
        scan order that cap keeps whichever tags ``rglob`` happened to reach
        first. Frequency order makes the cap keep the tags that can actually
        connect notes: connection scoring only counts a tag inside the
        ``2 <= df < ubiquity_cut`` band (``src/connections/candidate_assembly.py``),
        so a one-off tag is worth nothing downstream and a reused one is worth
        the most.
        """
        index = self.build_index(force_refresh)
        return sorted(
            index.values(),
            key=lambda tag: (-self._df[tag], tag),
        )

    def existing_normalized(self, force_refresh: bool = False) -> Set[str]:
        """Return normalized tags from index."""
        return set(self.build_index(force_refresh).keys())


def get_tag_index() -> TagIndex:
    """Factory returning TagIndex with default directory."""
    return TagIndex()
