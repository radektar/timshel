#!/usr/bin/env python3
"""Retag existing transcript markdown files using LLM tagger."""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.env_loader import load_env_file

load_env_file()

from src.config import config
from src.logger import logger
from src.tag_index import TagIndex
from src.tagger import BaseTagger, get_tagger
from src.vocabulary import VocabularyIndex


@dataclass
class MarkdownSections:
    """Structured representation of markdown parts."""

    frontmatter_lines: List[str]
    body: str


class TranscriptRetagger:
    """Retag existing markdown transcripts using ClaudeTagger."""

    def __init__(
        self,
        root_dir: Path,
        force: bool = False,
        only: Optional[str] = None,
    ) -> None:
        """Initialize retagger state.

        Args:
            root_dir: vault directory to walk.
            force: regenerate even when the existing tags are already
                sanitized. Needed after a tagger-prompt change — otherwise
                every note is skipped as "already fine" and the corpus keeps
                its old tags.
            only: process only notes whose filename contains this substring.
        """
        self.root_dir = root_dir
        self.force = force
        self.only = only
        self.tag_index = TagIndex(root_dir=self.root_dir)
        self.vocabulary = VocabularyIndex(root_dir=self.root_dir)
        self.tagger: BaseTagger = self._require_tagger()
        self.existing_tags: List[str] = self.tag_index.existing_tags_ranked()
        # Built once: the glossary is a whole-vault scan, and it does not
        # change meaningfully while this run is in flight.
        self.known_entities: str = self.vocabulary.canonical_terms_block()
        self.updated = 0
        self.skipped = 0

    def _require_tagger(self) -> BaseTagger:
        """Ensure LLM tagger is available."""
        if not config.ENABLE_LLM_TAGGING:
            raise RuntimeError("LLM tagging disabled in config.")
        tagger = get_tagger()
        if tagger is None:
            raise RuntimeError("Failed to initialize tagger (missing API key?).")
        return tagger

    def run(self) -> None:
        """Process the vault's TOP-LEVEL notes.

        Non-recursive, matching ``connections.candidate_assembly.load_corpus``:
        the subfolders hold generated digests, recall notes and — in
        ``.timshel/resummarize-backup`` — pre-migration copies of notes. A
        recursive walk rewrote those backups on a real run: it burns API calls
        on files nothing reads, and a backup that gets rewritten is no longer a
        backup.
        """
        logger.info("Starting retagging for directory: %s", self.root_dir)
        for md_path in sorted(self.root_dir.glob("*.md")):
            if self.only and self.only.lower() not in md_path.name.lower():
                continue
            self._process_file(md_path)

        logger.info(
            "Retagging finished. Updated: %s, skipped: %s",
            self.updated,
            self.skipped,
        )

    def _process_file(self, md_path: Path) -> None:
        """Process single markdown file."""
        try:
            content = md_path.read_text(encoding="utf-8")
        except OSError as err:
            logger.warning("Cannot read %s: %s", md_path, err)
            self.skipped += 1
            return

        sections = self._split_frontmatter(content)
        if sections is None:
            logger.debug("Skipping %s (missing frontmatter).", md_path.name)
            self.skipped += 1
            return

        current_tags = self._extract_tags(sections.frontmatter_lines)
        if current_tags and not self.force:
            custom_tags = [tag for tag in current_tags if tag != "transcription"]
            if custom_tags:
                needs_regeneration = any(
                    tag != TagIndex.sanitize_tag_value(tag) for tag in custom_tags
                )
                if not needs_regeneration:
                    logger.debug("Skipping %s (tags already sanitized).", md_path.name)
                    self.skipped += 1
                    return

        summary_markdown, transcript_text = self._extract_sections(sections.body)
        if not summary_markdown or not transcript_text:
            logger.debug("Skipping %s (missing summary or transcript).", md_path.name)
            self.skipped += 1
            return

        new_tags = self._generate_tags(summary_markdown, transcript_text)
        if not new_tags:
            logger.debug("No new tags generated for %s.", md_path.name)
            self.skipped += 1
            return

        sanitized_new = []
        for tag in new_tags:
            sanitized = TagIndex.sanitize_tag_value(tag)
            if sanitized:
                sanitized_new.append(sanitized)

        if not sanitized_new:
            logger.debug("Sanitized tags empty for %s.", md_path.name)
            self.skipped += 1
            return

        merged_tags = ["transcription"]
        for tag in sanitized_new:
            if tag not in merged_tags:
                merged_tags.append(tag)

        self._write_updated_file(md_path, sections, merged_tags)
        self.updated += 1

        # Update in-memory existing tags for future calls
        self.existing_tags.extend(merged_tags[1:])

    def _split_frontmatter(self, content: str) -> MarkdownSections | None:
        """Split content into frontmatter lines and body."""
        lines = content.splitlines()
        if not lines or lines[0].strip() != "---":
            return None

        for idx in range(1, len(lines)):
            if lines[idx].strip() == "---":
                frontmatter_lines = lines[1:idx]
                body = "\n".join(lines[idx + 1 :])
                return MarkdownSections(frontmatter_lines=frontmatter_lines, body=body)
        return None

    def _extract_tags(self, frontmatter_lines: List[str]) -> List[str]:
        """Extract tags array from frontmatter lines."""
        for line in frontmatter_lines:
            stripped = line.strip()
            if stripped.startswith("tags:"):
                tags_value = stripped.split(":", 1)[1].strip()
                if tags_value.startswith("[") and tags_value.endswith("]"):
                    inner = tags_value[1:-1]
                else:
                    inner = tags_value
                tags = [
                    tag.strip().strip('"').strip("'")
                    for tag in inner.split(",")
                    if tag.strip()
                ]
                return tags or []
        return []

    def _extract_sections(self, body: str) -> Tuple[str, str]:
        """Extract summary markdown and transcript text sections."""
        marker = "## Transkrypcja"
        if marker not in body:
            return "", ""

        summary_part, transcript_part = body.split(marker, maxsplit=1)
        summary_markdown = summary_part.strip()
        transcript_text = transcript_part.strip()
        return summary_markdown, transcript_text

    def _generate_tags(self, summary: str, transcript: str) -> List[str]:
        """Call tagger to generate tags for given content."""
        try:
            return self.tagger.generate_tags(
                transcript=transcript,
                summary_markdown=summary,
                existing_tags=self.existing_tags,
                known_entities=self.known_entities,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Tag generation failed: %s", exc, exc_info=True)
            return []

    def _write_updated_file(
        self,
        md_path: Path,
        sections: MarkdownSections,
        tags: List[str],
    ) -> None:
        """Rewrite markdown file with updated tags."""
        updated_frontmatter = self._render_frontmatter(sections.frontmatter_lines, tags)
        new_content = "---\n" + "\n".join(updated_frontmatter) + "\n---\n\n" + sections.body
        try:
            md_path.write_text(new_content, encoding="utf-8")
            logger.info("Updated tags for %s", md_path.name)
        except OSError as err:
            logger.error("Failed to write %s: %s", md_path, err)

    def _render_frontmatter(
        self,
        frontmatter_lines: List[str],
        tags: List[str],
    ) -> List[str]:
        """Render new frontmatter lines with updated tags."""
        rendered = frontmatter_lines.copy()
        tags_line = f"tags: [{', '.join(tags)}]"
        for idx, line in enumerate(rendered):
            if line.strip().startswith("tags:"):
                rendered[idx] = tags_line
                break
        else:
            rendered.append(tags_line)
        return rendered


def main() -> int:
    """Entry point for retagger CLI."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "regenerate tags even when the current ones are already sanitized "
            "(required to roll a tagger-prompt change over the corpus)"
        ),
    )
    parser.add_argument(
        "--only",
        metavar="SUBSTR",
        help="process only notes whose filename contains SUBSTR",
    )
    args = parser.parse_args()

    config.ensure_directories()

    try:
        retagger = TranscriptRetagger(
            root_dir=config.TRANSCRIBE_DIR,
            force=args.force,
            only=args.only,
        )
    except RuntimeError as err:
        logger.error("Cannot run retagger: %s", err)
        return 1

    retagger.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())

