#!/usr/bin/env python3
"""Re-summarize existing transcript notes into the v2 format + vocabulary.

The connection engine reads SUMMARIES, and the pre-2026-07-06 corpus was
summarized without the v2 prompt: no "Stanowiska"/"Wątki otwarte" sections,
no personal-vocabulary canonicalisation ("TekTutoreski" lives in titles and
key points). This one-off migration regenerates ONLY the summary layer of
each note from its stored raw transcript, with the current prompt + glossary:

* frontmatter (title, tags, fingerprint, version…) — preserved byte-for-byte;
* ``## Transkrypcja`` and everything below — preserved byte-for-byte
  (the transcript is the source of truth and the evidence layer);
* basename/filename — NEVER touched (planted pairs, digests and the vault
  index all join on basenames).

Three modes, escalating trust:

  (default)   plan only — list the batch, no API calls, no writes
  --preview   generate via API, write rebuilt notes to
              .malinche/resummarize-preview/ — the VAULT IS NOT TOUCHED
  --apply     generate + back up originals to .malinche/resummarize-backup/
              + overwrite the summary layer in place

Run from a terminal with Full Disk Access (the vault lives in iCloud):

  ./venv312/bin/python scripts/resummarize_vault.py --only tttr --preview
  ./venv312/bin/python scripts/resummarize_vault.py --limit 10 --preview
  ./venv312/bin/python scripts/resummarize_vault.py --all --apply
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import config  # noqa: E402

# Default matches production: the eval baseline should measure what the app
# actually produces, and prod summaries run on Haiku.
DEFAULT_MODEL = "claude-haiku-4-5-20251001"

_TRANSCRIPT_HEADING_RE = re.compile(
    r"^##\s+(Transkrypcja|Transcript)\s*$", re.MULTILINE
)

# ClaudeSummarizer.generate() falls back to a canned template on transient API
# errors instead of raising. Overwriting a real summary with that template
# would be data loss — detect and skip. These markers exist ONLY in the
# fallback/canned texts of src/summarizer.py.
_FALLBACK_MARKERS = (
    "Brak podsumowania AI",
    "Przejrzeć transkrypcję ręcznie",
    "Nie udało się wygenerować podsumowania",
)

# Placeholder transcripts (silence/music) — nothing to summarize.
_EMPTY_TRANSCRIPT_MARKER = "(Brak rozpoznawalnej mowy w nagraniu)"
_MIN_TRANSCRIPT_CHARS = 80


def split_note(text: str) -> Optional[Tuple[str, str, str]]:
    """Split a note into (frontmatter_block, old_summary, transcript_block).

    ``frontmatter_block`` ends with the closing ``---`` line;
    ``transcript_block`` starts at the ``## Transkrypcja`` heading. Returns
    None when the note doesn't have the expected shape (no frontmatter or no
    transcript section) — such notes are skipped, never rewritten.
    """
    if not text.startswith("---"):
        return None
    fm_end = text.find("\n---", 3)
    if fm_end == -1:
        return None
    fm_close = text.find("\n", fm_end + 1)
    if fm_close == -1:
        return None
    frontmatter = text[: fm_close + 1]
    rest = text[fm_close + 1 :]

    match = _TRANSCRIPT_HEADING_RE.search(rest)
    if not match:
        return None
    old_summary = rest[: match.start()].strip("\n")
    transcript_block = rest[match.start() :]
    return frontmatter, old_summary, transcript_block


def rebuild_note(frontmatter: str, new_summary: str, transcript_block: str) -> str:
    """Reassemble the note in the MD_TEMPLATE layout (fm, blank, summary,
    blank, transcript)."""
    return f"{frontmatter}\n{new_summary.strip()}\n\n{transcript_block}"


def raw_transcript(transcript_block: str) -> str:
    """The transcript text below the heading line."""
    return transcript_block.split("\n", 1)[1] if "\n" in transcript_block else ""


def is_fallback_summary(summary_md: str) -> bool:
    return any(marker in summary_md for marker in _FALLBACK_MARKERS)


def discover_notes(root: Path) -> List[Path]:
    """Transcript notes only — top level of TRANSCRIBE_DIR, oldest first.

    Subfolders (Malinche Digests / Malinche Recall) are products of the
    pipeline, not transcripts; rglob would drag them in.
    """
    return sorted(p for p in root.glob("*.md"))


def eligible(path: Path) -> Tuple[bool, str]:
    """(ok, reason) — cheap structural checks before any API call."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return False, f"unreadable: {exc}"
    parts = split_note(text)
    if parts is None:
        return False, "no frontmatter/transcript section"
    transcript = raw_transcript(parts[2]).strip()
    if _EMPTY_TRANSCRIPT_MARKER in transcript:
        return False, "empty-transcript placeholder"
    if len(transcript) < _MIN_TRANSCRIPT_CHARS:
        return False, f"transcript too short ({len(transcript)} chars)"
    return True, ""


def _select(
    notes: List[Path], only: List[str], limit: Optional[int], take_all: bool
) -> List[Path]:
    if only:
        needles = [n.casefold() for n in only]
        notes = [p for p in notes if any(n in p.name.casefold() for n in needles)]
    if not take_all and limit is not None:
        notes = notes[:limit]
    return notes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--preview",
        action="store_true",
        help="generate and write to .malinche/resummarize-preview/ (vault untouched)",
    )
    mode.add_argument(
        "--apply",
        action="store_true",
        help="generate, back up originals, overwrite summaries in place",
    )
    parser.add_argument("--limit", type=int, default=10, help="batch size (default 10)")
    parser.add_argument(
        "--all", action="store_true", help="ignore --limit, take the whole corpus"
    )
    parser.add_argument(
        "--only",
        action="append",
        default=[],
        metavar="SUBSTR",
        help="filter by basename substring (repeatable)",
    )
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument(
        "--yes", action="store_true", help="skip the --apply confirmation prompt"
    )
    args = parser.parse_args()

    vault = Path(config.TRANSCRIBE_DIR)
    if not vault.exists():
        print(f"❌ TRANSCRIBE_DIR not found: {vault}")
        print("   (run from a terminal with Full Disk Access — iCloud/TCC)")
        return 1

    candidates = _select(discover_notes(vault), args.only, args.limit, args.all)
    batch: List[Path] = []
    for path in candidates:
        ok, reason = eligible(path)
        if ok:
            batch.append(path)
        else:
            print(f"  skip  {path.name}  ({reason})")
    if not batch:
        print("Nothing to do — no eligible notes in selection.")
        return 0

    print(f"\nBatch: {len(batch)} notes (model: {args.model})")
    for path in batch:
        print(f"  •  {path.name}")

    if not (args.preview or args.apply):
        print(
            "\nPlan only — no API calls made. "
            "Re-run with --preview (safe) or --apply (writes)."
        )
        return 0

    # Glossary + summarizer, built once for the whole batch.
    from src.summarizer import APIBillingError, ClaudeSummarizer  # noqa: E402
    from src.vocabulary import VocabularyIndex  # noqa: E402

    if not config.LLM_API_KEY:
        print("❌ No Claude API key configured (settings/ANTHROPIC_API_KEY).")
        return 1
    vocab = VocabularyIndex()
    vocab.build(force_refresh=True)
    known_terms = vocab.known_terms_block()
    print(f"\nGlossary: {len(known_terms.splitlines())} known terms")
    summarizer = ClaudeSummarizer(api_key=config.LLM_API_KEY, model=args.model)

    if args.apply and not args.yes:
        answer = input(f"\nOverwrite summaries of {len(batch)} notes? [y/N] ")
        if answer.strip().lower() not in ("y", "yes", "t", "tak"):
            print("Aborted.")
            return 0

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    preview_dir = vault / ".malinche" / "resummarize-preview"
    backup_dir = vault / ".malinche" / "resummarize-backup" / stamp

    done = failed = 0
    stances_notes = 0
    for path in batch:
        text = path.read_text(encoding="utf-8")
        frontmatter, _old, transcript_block = split_note(text)  # type: ignore[misc]
        transcript = raw_transcript(transcript_block)
        try:
            result = summarizer.generate(transcript, known_terms_block=known_terms)
        except APIBillingError as exc:
            print(f"\n❌ Permanent API error — aborting run: {exc}")
            return 1
        new_summary = result.get("summary", "")
        if not new_summary or is_fallback_summary(new_summary):
            print(f"  FAIL  {path.name}  (API fallback — original kept)")
            failed += 1
            continue

        rebuilt = rebuild_note(frontmatter, new_summary, transcript_block)
        has_stances = "## Stanowiska" in new_summary or "## Stances" in new_summary
        stances_notes += has_stances
        marker = "✅+st" if has_stances else "✅   "

        if args.preview:
            preview_dir.mkdir(parents=True, exist_ok=True)
            (preview_dir / path.name).write_text(rebuilt, encoding="utf-8")
        else:
            backup_dir.mkdir(parents=True, exist_ok=True)
            (backup_dir / path.name).write_text(text, encoding="utf-8")
            path.write_text(rebuilt, encoding="utf-8")
        done += 1
        print(f"  {marker} {path.name}  (new title suggestion: {result.get('title')})")

    where = preview_dir if args.preview else f"vault (backups: {backup_dir})"
    print(
        f"\nDone: {done} rewritten, {failed} failed/kept · "
        f"{stances_notes} notes gained a Stanowiska section\n→ {where}"
    )
    if args.preview:
        print("Inspect the previews, then re-run with --apply.")
    else:
        print("Next: make recall-eval  (baseline v3 on the same 52 pairs)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
