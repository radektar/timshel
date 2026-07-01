"""CLI for the local recall engine.

    python -m src.connections.recall.cli ask "co ustaliłem w sprawie okien?"
    python -m src.connections.recall.cli backfill

``ask`` runs a fully-local, LLM-free hybrid search and prints cited passages;
``backfill`` embeds the existing vault once. Wired into the Makefile as
``make ask Q="…"`` / ``make backfill-embeddings``.
"""

from __future__ import annotations

import argparse
import sys
from typing import List, Optional


def _clip(text: str, n: int = 200) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= n else text[: n - 1] + "…"


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="malinche-recall", description="Local recall over your notes.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    ask = sub.add_parser("ask", help="Search your corpus (local, no LLM).")
    ask.add_argument("query")
    ask.add_argument("-k", type=int, default=8)
    sub.add_parser("backfill", help="Embed the existing vault once.")
    args = parser.parse_args(argv)

    from src.config.config import get_config
    from src.connections.recall.engine import RecallEngine

    engine = RecallEngine(get_config().TRANSCRIBE_DIR)
    try:
        if args.cmd == "ask":
            results = engine.search(args.query, k=args.k)
            if not results:
                print("Brak trafień w Twoich notatkach.")
                return 0
            for i, r in enumerate(results, 1):
                print(f"{i:2}. [{r.note_id}]  ·  {r.channels}")
                print(f'    „{_clip(r.quote)}"\n')
        elif args.cmd == "backfill":
            def _progress(i, total, path):
                print(f"  {i}/{total}  {path.name}", file=sys.stderr)

            n = engine.backfill(progress=_progress)
            print(f"Zaindeksowano {n} notatek — {engine.count()} chunków w indeksie.")
    finally:
        engine.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
