#!/usr/bin/env python3
"""Distance-injection experiment: do cross-topic bridges + a sharpened prompt
produce more *surprising* connections than the similarity baseline?

Runs three conditions over the SAME window of the real vault, one fixed model,
so the only things that vary are retrieval (distance) and the prompt:

    A  baseline      similarity assembly      + baseline prompt
    B  + distance    bridge assembly          + baseline prompt   (A→B isolates distance)
    C  + prompt      bridge assembly          + sharp prompt      (B→C isolates the prompt)

Prints every connection found per condition (type, notes, rationale, directions)
and marks which candidate notes were injected as bridges. Writes a markdown
record next to the script's sibling Docs/future/ for side-by-side comparison.

Usage:
    ./venv312/bin/python scripts/compare_distance_experiment.py [--model MODEL] [--bridges N] [--window N]
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import config  # noqa: E402
from src.connections.candidate_assembly import assemble_candidates  # noqa: E402
from src.connections.dismissals import DismissalStore  # noqa: E402
from src.connections.synthesis import (  # noqa: E402
    _SYSTEM_PROMPT,
    _SYSTEM_PROMPT_SHARP,
    ConnectionSynthesizer,
)

# Opus 4.8 — the deep model; the experiment asks what distance unlocks at the
# quality ceiling, holding the model fixed across all three conditions.
DEFAULT_MODEL = "claude-opus-4-8"


def _fmt_conn(c, bridges: set) -> str:
    notes = ", ".join(
        f"[[{n}]]{'  ⟵ MOST' if n in bridges else ''}" for n in c.notes
    )
    lines = [
        f"  • ({c.type})  {notes}",
        f"    {c.rationale}",
    ]
    for d in c.directions:
        lines.append(f"      – {d}")
    return "\n".join(lines)


def _run(label, synth, candidates, prompt, lang):
    result = synth.synthesize(candidates, dismissed=[], language=lang,
                              system_prompt=prompt)
    conns = result.connections if result else []
    usage = getattr(synth, "last_usage", None)
    return conns, usage


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--bridges", type=int, default=4)
    ap.add_argument("--window", type=int, default=15)
    ap.add_argument("--max-tokens", type=int, default=None,
                    help="override config.SYNTHESIS_MAX_TOKENS (baseline prompt "
                         "is verbose and truncates at the default 2048)")
    args = ap.parse_args()

    if args.max_tokens:
        config.SYNTHESIS_MAX_TOKENS = args.max_tokens

    vault = Path(config.TRANSCRIBE_DIR)
    dismissals = DismissalStore(vault).load()
    lang = "pl"

    # Same window for every condition (first-run mode → N most recent notes).
    base = assemble_candidates(vault, None, dismissals,
                               first_run_window=args.window, inject_bridges=0)
    brdg = assemble_candidates(vault, None, dismissals,
                               first_run_window=args.window,
                               inject_bridges=args.bridges)

    print(f"\nMODEL: {args.model}   WINDOW: {args.window}   BRIDGES: {args.bridges}")
    print(f"baseline candidates: {len(base.notes)}   "
          f"bridge candidates: {len(brdg.notes)}   "
          f"bridges injected: {sorted(brdg.bridge_basenames)}\n")

    # Prefer an explicit ANTHROPIC_API_KEY for the run (lets you test a valid key
    # without touching the app's config.json), else fall back to the app config.
    api_key = os.environ.get("ANTHROPIC_API_KEY") or config.LLM_API_KEY
    synth = ConnectionSynthesizer(api_key=api_key, model=args.model)

    conditions = [
        ("A  baseline (similarity + baseline prompt)", base, _SYSTEM_PROMPT, set()),
        ("B  + distance (bridges + baseline prompt)", brdg, _SYSTEM_PROMPT,
         brdg.bridge_basenames),
        ("C  + distance + sharp prompt", brdg, _SYSTEM_PROMPT_SHARP,
         brdg.bridge_basenames),
    ]

    out_lines = [f"# Distance experiment — {args.model}", ""]
    out_lines.append(f"Window: {args.window} newest notes · bridges injected: "
                     f"`{sorted(brdg.bridge_basenames)}`\n")

    for label, cand, prompt, bridges in conditions:
        print("=" * 78)
        print(label)
        print("=" * 78)
        out_lines += ["", f"## {label}", ""]
        conns, usage = _run(label, synth, cand, prompt, lang)
        by_type: dict = {}
        for c in conns:
            by_type[c.type] = by_type.get(c.type, 0) + 1
        summary = ", ".join(f"{k}={v}" for k, v in sorted(by_type.items())) or "none"
        tok = ""
        if usage is not None:
            tok = f"  [in={getattr(usage, 'input_tokens', '?')} " \
                  f"out={getattr(usage, 'output_tokens', '?')}]"
        print(f"found {len(conns)}  ({summary}){tok}\n")
        out_lines.append(f"found {len(conns)} ({summary})\n")
        for c in conns:
            block = _fmt_conn(c, bridges)
            print(block + "\n")
            out_lines.append(block.replace("  •", "-") + "\n")

    # Raw, machine-written dump (regenerated each run). The curated
    # distance-experiment-results.md (analysis + a frozen snapshot) is kept by
    # hand and must NOT be clobbered by a rerun.
    out_path = (Path(__file__).resolve().parents[1]
                / "Docs" / "future" / "distance-experiment-raw.md")
    out_path.write_text("\n".join(out_lines), encoding="utf-8")
    print(f"\n📄 results written → {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
