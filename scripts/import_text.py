#!/usr/bin/env python3
"""Import already-transcribed text (txt/md/vtt) into the vault.

Usage:
    ./venv312/bin/python scripts/import_text.py <file-or-directory> [more...]

Seeds a vault from existing notes / meeting-transcript exports so the first
Insights digest has material (cold-start fix), and bypasses the lack of
Meet/Zoom integrations (drop their .vtt export in). Runs the same
summarize→render→index pipeline as audio; imported notes carry
``source_type: import`` in frontmatter.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import config  # noqa: E402
from src.ingest import SUPPORTED_SUFFIXES  # noqa: E402
from src.transcriber import Transcriber  # noqa: E402


def _iter_sources(args):
    for arg in args:
        p = Path(arg).expanduser()
        if p.is_dir():
            for f in sorted(p.rglob("*")):
                if f.is_file() and f.suffix.lower() in SUPPORTED_SUFFIXES:
                    yield f
        elif p.is_file():
            yield p
        else:
            print(f"⚠️  skip (not found): {p}")


def main(argv) -> int:
    if not argv:
        print(__doc__)
        return 2

    sources = list(_iter_sources(argv))
    if not sources:
        print("No importable files found (supported: "
              f"{', '.join(sorted(SUPPORTED_SUFFIXES))}).")
        return 1

    transcriber = Transcriber(config=config)
    ok = 0
    failed = 0
    for src in sources:
        try:
            if transcriber.import_text_file(src):
                ok += 1
                print(f"✓ {src.name}")
            else:
                failed += 1
                print(f"✗ {src.name} (post-processing failed)")
        except (ValueError, FileNotFoundError) as exc:
            failed += 1
            print(f"✗ {src.name}: {exc}")

    print(f"\nImported {ok}/{len(sources)} file(s); {failed} failed.")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
