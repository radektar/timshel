#!/usr/bin/env python3
"""Digest the vault ARCHIVE on demand — explicit, paid, user-triggered.

The scheduler's seen-set deliberately protects existing vaults from being
auto-drained by paid runs (a fresh install marks everything but the newest
window as seen; migration marks everything dated before the last digest as
seen). This script is the explicit opt-in for the archive: forget the
seen-set (``--reset``) and consume it window-by-window (15 notes per forced
run) with as many runs as you ask for.

Cost: each run is one synthesis (+ verdict) call — roughly $0.45 with Opus.

Run:  venv312/bin/python scripts/digest_archive.py --reset --runs 3
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import config  # noqa: E402

DEFAULT_MODEL = "claude-opus-4-8"
EST_RUN_COST_USD = 0.45


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--reset",
        action="store_true",
        help="forget the seen-set first: the WHOLE archive becomes new material",
    )
    ap.add_argument(
        "--runs",
        type=int,
        default=1,
        help="max paid digest runs (each consumes up to 15 unseen notes)",
    )
    ap.add_argument("--model", default=DEFAULT_MODEL, help="synthesis + verdict model")
    ap.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    args = ap.parse_args()

    if not config.LLM_API_KEY:
        print("no API key in Malinche settings — aborting")
        return 1

    # In-process overrides only (die with the process) — same full prototype
    # pipeline as `make magic-digest`, so archive digests are comparable.
    config.PROTOTYPE_TESTER_MODE = True
    config.INSIGHT_METRICS_ENABLED = True
    config.VERDICT_ENABLED = True
    config.SYNTHESIS_ENTITY_COUNT = 4
    config.SYNTHESIS_DENSE_COUNT = 6
    config.SYNTHESIS_GRAPH_COUNT = 6
    config.SYNTHESIS_STANCE_COUNT = 4
    config.LLM_MODEL_SYNTHESIS = args.model
    config.LLM_MODEL_VERDICT = args.model

    from src.connections.candidate_assembly import (
        FIRST_RUN_WINDOW,
        load_corpus,
        note_key,
    )
    from src.connections.scheduler import (
        _ensure_seen_migrated,
        get_scheduler,
        run_digest_if_due,
    )

    vault = Path(config.TRANSCRIBE_DIR)
    scheduler = get_scheduler()
    if args.reset:
        scheduler.reset_seen()
        print("seen-set reset — the whole archive is new material again.")
        print("NOTE: if the Timshel app is running, RESTART it afterwards —")
        print("      it holds the old seen-set in memory and would write it back.")
    else:
        _ensure_seen_migrated(scheduler, vault)

    def unseen_count() -> int:
        seen = scheduler.seen_note_keys or set()
        return sum(1 for n in load_corpus(vault) if note_key(n) not in seen)

    todo = unseen_count()
    if todo == 0:
        print("nothing unseen — use --reset to re-digest the archive.")
        return 0
    runs_needed = -(-todo // FIRST_RUN_WINDOW)  # ceil
    runs = min(args.runs, runs_needed)
    print(f"unseen notes: {todo}  (~{runs_needed} runs to drain; doing {runs})")
    print(
        f"estimated cost: ~${runs * EST_RUN_COST_USD:.2f} "
        f"({runs} x synthesis+verdict, {args.model})"
    )
    if not args.yes and input("proceed? [y/N] ").strip().lower() != "y":
        print("aborted.")
        return 1

    left = todo
    for i in range(runs):
        print(f"\n--- run {i + 1}/{runs} ---")
        path = run_digest_if_due(transcriber=None, force=True)
        print(
            f"digest -> {path}"
            if path is not None
            else "no digest this run (zero connections survived — see logs)"
        )
        now_left = unseen_count()
        if now_left == left:
            # Degenerate candidate set (<2 notes): the window was not consumed
            # and repeating would just spin — stop instead of looping.
            print("window not consumed — stopping")
            break
        left = now_left
        print(f"unseen left: {left}")
        if left == 0:
            break
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
