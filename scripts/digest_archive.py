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

    # In-process overrides only (die with the process) — the same shared
    # prototype pipeline as `make magic-digest`, so archive digests are
    # comparable in the metrics ledger.
    from src.config.tester_mode import apply_tester_overrides

    apply_tester_overrides(args.model)

    from src.connections.candidate_assembly import (
        FIRST_RUN_WINDOW,
        load_corpus,
        note_key,
    )
    from src.connections.dismissals import DismissalStore
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
        print("(A running Timshel app picks the reset up on its next digest —")
        print(" the state file carries an epoch, no restart needed.)")
    else:
        _ensure_seen_migrated(scheduler, vault)

    # Count exactly what a run can consume: same muted-note filter as
    # candidate assembly, so the quoted backlog and cost are honest.
    dismissals = DismissalStore(vault).load()
    corpus = [n for n in load_corpus(vault) if not dismissals.note_muted(n.basename)]

    def unseen_count() -> int:
        seen = scheduler.seen_note_keys or set()
        return sum(1 for n in corpus if note_key(n) not in seen)

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
