#!/usr/bin/env python3
"""Tester-mode digest — the magic-insights prototype dogfood command.

Force-runs the REAL digest pipeline on the vault with the prototype knobs on:
Opus 4.8 synthesis + verdict verification + per-run metrics. This is NOT a
preview: it writes a real digest into ``Timshel Digests/``, records dismissal
metadata, and ADVANCES the digest clock (the next scheduled digest windows
from now). That is the point — the H1 measurement runs on real digests rated
through the Insights window. The side-effect-free comparison tool remains
``scripts/preview_digest.py``.

Config overrides are plain in-process assignments on the config proxy (the
established pattern of preview_digest/compare_distance_experiment) — they die
with the process and never touch the user's saved settings.

Run:  make magic-digest
      ./venv312/bin/python scripts/magic_digest.py [--model M] [--no-verdict]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import config  # noqa: E402

DEFAULT_MODEL = "claude-opus-4-8"


def _print_last_metrics(vault: Path) -> None:
    metrics_file = vault / config.SIDECAR_DIR_NAME / "metrics.jsonl"
    try:
        last = metrics_file.read_text(encoding="utf-8").splitlines()[-1]
        rec = json.loads(last)
    except (OSError, IndexError, json.JSONDecodeError):
        print("(no metrics record found)")
        return
    print("\n--- metrics (last run) ---")
    print(f"  model:            {rec.get('model')}")
    print(
        f"  synthesis tokens: in={rec.get('input_tokens')} "
        f"out={rec.get('output_tokens')}  ${rec.get('synthesis_cost_usd', 0):.4f}"
    )
    if rec.get("verdict_model"):
        print(
            f"  verdict tokens:   in={rec.get('verdict_input_tokens')} "
            f"out={rec.get('verdict_output_tokens')}  "
            f"${rec.get('verdict_cost_usd', 0):.4f}  "
            f"dropped={rec.get('verdict_dropped')}"
        )
    print(f"  TOTAL cost:       ${rec.get('cost_usd', 0):.4f}")
    print(
        f"  candidates: {rec.get('candidates')}  "
        f"connections: {rec.get('connections')} {rec.get('connection_types')}"
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model", default=DEFAULT_MODEL, help="synthesis + verdict model")
    ap.add_argument("--no-verdict", action="store_true", help="skip the verdict pass")
    args = ap.parse_args()

    print("=" * 62)
    print("MAGIC-INSIGHTS TESTER DIGEST — real run, real side effects:")
    print("  * writes a digest into 'Timshel Digests/'")
    print("  * advances the weekly digest clock (mark_ran)")
    print("  * appends a cost record to .timshel/metrics.jsonl")
    print(f"  model: {args.model}  verdict: {'OFF' if args.no_verdict else 'ON'}")
    print("=" * 62)

    if not config.LLM_API_KEY:
        print("no API key in Malinche settings — aborting")
        return 1

    vault = Path(config.TRANSCRIBE_DIR)
    # In-process overrides only (die with the process) — the one shared
    # definition of the full prototype pipeline, so digest_archive.py rows
    # stay comparable with these.
    from src.config.tester_mode import apply_tester_overrides

    apply_tester_overrides(args.model)
    config.VERDICT_ENABLED = not args.no_verdict

    from src.connections.scheduler import run_digest_if_due

    path = run_digest_if_due(transcriber=None, force=True)

    if path is not None:
        print(f"\ndigest written -> {path}")
        print("rate it in the Insights window — the H1 action instrument")
        print("(make signal-report) picks your actions up from there.")
    else:
        print(
            "\nno digest written. Possible reasons (see logs / metrics below):\n"
            "  - fewer than 2 candidate notes\n"
            "  - synthesis found no genuine connections (clock reset — OK)\n"
            "  - verdict dropped everything (clock reset, metrics recorded)\n"
            "  - another digest run holds the lock (daemon running?)\n"
            "  - recoverable API error (will retry next tick)"
        )
    _print_last_metrics(vault)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
