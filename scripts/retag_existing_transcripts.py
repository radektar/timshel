#!/usr/bin/env python3
"""Retag existing transcript markdown files using LLM tagger."""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.env_loader import load_env_file

load_env_file()

from src.config import config
from src.logger import logger
from src.summarizer import APIBillingError
from src.tag_index import TagIndex
from src.tagger import BaseTagger, get_tagger
from src.vocabulary import VocabularyIndex


@dataclass
class MarkdownSections:
    """Structured representation of markdown parts."""

    body: str


# Frontmatter tags, in both styles Obsidian round-trips: inline
# ``tags: [a, b]`` and the block list its property editor writes
# (``tags:`` followed by indented ``- item`` lines).
_INLINE_TAGS_RE = re.compile(r"^tags:[ \t]*\[(.*)\][ \t]*\r?$", re.MULTILINE)
_BLOCK_TAGS_RE = re.compile(
    r"^tags:[ \t]*\r?\n((?:[ \t]*-[ \t]+.*\r?\n)+)", re.MULTILINE
)


def _frontmatter_span(text: str) -> Optional[Tuple[int, int]]:
    """Character span of the frontmatter block, or None when there is none."""
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    return (0, end + 4) if end != -1 else None


def parse_tags(text: str) -> List[str]:
    """Tags declared in the frontmatter, in either style ([] when none).

    Block style matters: Obsidian's property editor rewrites ``tags:`` as an
    indented list, and a parser that only understands the inline form reads
    those notes as untagged.
    """
    span = _frontmatter_span(text)
    if not span:
        return []
    front = text[span[0] : span[1]]
    inline = _INLINE_TAGS_RE.search(front)
    if inline:
        return [
            t.strip().strip('"').strip("'")
            for t in inline.group(1).split(",")
            if t.strip()
        ]
    block = _BLOCK_TAGS_RE.search(front)
    if block:
        return [
            line.strip()[1:].strip().strip('"').strip("'")
            for line in block.group(1).splitlines()
            if line.strip()
        ]
    return []


def replace_tags(text: str, tags: List[str]) -> Optional[str]:
    """*text* with only its tags replaced — byte-identical everywhere else.

    Substitution on the original string, never a re-assembly from parsed
    parts: the old rewriter rebuilt the note and silently injected a blank
    line after the frontmatter, dropped the trailing newline, and (for block
    style) left the previous list items dangling under the new inline line,
    producing invalid YAML. The note's own style is preserved, so a vault
    edited in Obsidian keeps its formatting.
    """
    span = _frontmatter_span(text)
    if not span:
        return None
    head, front, tail = text[: span[0]], text[span[0] : span[1]], text[span[1] :]

    block = _BLOCK_TAGS_RE.search(front)
    if block:
        indent_match = re.match(r"[ \t]*", block.group(1))
        indent = indent_match.group(0) if indent_match else "  "
        rendered = "tags:\n" + "".join(f"{indent}- {tag}\n" for tag in tags)
        return head + front[: block.start()] + rendered + front[block.end() :] + tail

    inline = _INLINE_TAGS_RE.search(front)
    if inline:
        rendered = "tags: [" + ", ".join(tags) + "]"
        return head + front[: inline.start()] + rendered + front[inline.end() :] + tail

    # No tags key at all: add one rather than skip the note — we already paid
    # for the tags by the time we get here, and the previous renderer appended
    # in this case too.
    closing = front.rfind("---")
    if closing == -1:
        return None
    rendered = "tags: [" + ", ".join(tags) + "]\n"
    return head + front[:closing] + rendered + front[closing:] + tail


class TranscriptRetagger:
    """Retag existing markdown transcripts using ClaudeTagger."""

    def __init__(
        self,
        root_dir: Path,
        force: bool = False,
        only: Optional[str] = None,
        dry_run: bool = False,
        stamp: str = "",
    ) -> None:
        """Initialize retagger state.

        Args:
            root_dir: vault directory to walk.
            force: regenerate even when the existing tags are already
                sanitized. Needed after a tagger-prompt change — otherwise
                every note is skipped as "already fine" and the corpus keeps
                its old tags.
            only: process only notes whose filename contains this substring.
            dry_run: report ``old tags -> new tags`` per note and write
                nothing. Costs the same API calls; changes no files.
            stamp: backup-folder name (defaults to the current timestamp).
        """
        self.root_dir = root_dir
        self.force = force
        self.only = only
        self.dry_run = dry_run
        self.backup_dir = (
            Path(root_dir)
            / config.SIDECAR_DIR_NAME
            / "retag-backup"
            / (stamp or datetime.now().strftime("%Y%m%d-%H%M%S"))
        )
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

        current_tags = parse_tags(content)
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

        updated_content = replace_tags(content, merged_tags)
        if updated_content is None:
            logger.warning("Skipping %s (no tags field to replace).", md_path.name)
            self.skipped += 1
            return

        # Grow the reusable-tag pool before the dry-run branch: a preview that
        # offered a different vocabulary than the real run would predict
        # different tags than the run it is previewing.
        self.existing_tags.extend(merged_tags[1:])

        if self.dry_run:
            logger.info(
                "DRY-RUN %s: %s -> %s",
                md_path.name,
                ", ".join(current_tags) or "—",
                ", ".join(merged_tags),
            )
            self.updated += 1
            return

        self._write_updated_file(md_path, content, updated_content)
        self.updated += 1

    def _split_frontmatter(self, content: str) -> MarkdownSections | None:
        """Split content into frontmatter lines and body."""
        lines = content.splitlines()
        if not lines or lines[0].strip() != "---":
            return None

        for idx in range(1, len(lines)):
            if lines[idx].strip() == "---":
                body = "\n".join(lines[idx + 1 :])
                return MarkdownSections(body=body)
        return None

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
        except APIBillingError:
            # Permanent (auth / credits / retired model): every remaining note
            # would fail the same way. Abort instead of walking the whole vault
            # logging one error per note and reporting "finished".
            raise
        except Exception as exc:  # noqa: BLE001
            logger.error("Tag generation failed: %s", exc, exc_info=True)
            return []

    def _write_updated_file(self, md_path: Path, original: str, updated: str) -> None:
        """Back the note up, then write the updated text."""
        try:
            self._backup(md_path, original)
        except OSError as err:
            logger.error("Skipping %s — could not back it up: %s", md_path, err)
            return
        try:
            md_path.write_text(updated, encoding="utf-8")
            logger.info("Updated tags for %s", md_path.name)
        except OSError as err:
            logger.error("Failed to write %s: %s", md_path, err)

    def _backup(self, md_path: Path, original: str) -> None:
        """Copy the note into a timestamped backup dir before rewriting it.

        write_text truncates first, so an interrupted run would otherwise lose
        a note outright, and a bad prompt change would be unrecoverable across
        the whole vault. Mirrors scripts/resummarize_vault.py.
        """
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        target = self.backup_dir / md_path.name
        if target.exists():
            # First write wins. The stamp has second resolution, so two runs
            # can share a folder — overwriting would replace the true original
            # with the previous run's output, which is the one thing a backup
            # must never do.
            return
        target.write_text(original, encoding="utf-8")


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
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "print 'old tags -> new tags' per note and write nothing "
            "(still calls the API, so it costs the same)"
        ),
    )
    args = parser.parse_args()

    config.ensure_directories()

    try:
        retagger = TranscriptRetagger(
            root_dir=config.TRANSCRIBE_DIR,
            force=args.force,
            only=args.only,
            dry_run=args.dry_run,
        )
    except RuntimeError as err:
        logger.error("Cannot run retagger: %s", err)
        return 1

    try:
        retagger.run()
    except APIBillingError as err:
        # Auth / credits / retired model: nothing left to try. Report it the
        # same way as a startup failure instead of dumping a traceback.
        logger.error(
            "Aborted after %s notes — Claude API unavailable: %s",
            retagger.updated,
            err,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
