#!/usr/bin/env python3
"""Blind cascade test — pick the production model mix with H4 numbers (plan D).

Three conditions over the SAME window and the SAME assembled base candidate
set, so only the model cascade varies:

  A  Opus 4.8 synthesis                          (quality ceiling)
  B  Haiku triage -> Opus 4.8 synthesis          (does cheap pruning hurt?)
  C  Haiku triage -> Sonnet synthesis -> Opus verdict   (the strategy's bet)

Triage here is a minimal IN-SCRIPT Haiku pass (forced tool: keep the ~N
non-window notes most likely to yield surprising, grounded connections) — a
production triage stage is deliberately deferred until this test proves the
cascade is worth it.

BLINDING (the piece compare_distance_experiment never had): results are
shuffled with a seeded RNG and rendered as "Digest I/II/III" into a rating
file with ZERO model/cost/latency traces. The answer key goes to a separate
JSON — do not open it before the ratings are done. Then:

  --reveal RATINGS.md KEY.json   parses the 'ocena:' lines, joins with the
  key, prints mean score per condition, score-per-dollar and the H4 line
  (condition cost x 30/CONNECTIONS_DIGEST_INTERVAL_DAYS vs the $2.60 bar).

Rating scale (fill next to each connection):
  2 = would act on it | 1 = interesting | 0 = noise | -1 = fabricated

Estimated spend per full run: ~$1.20-1.80.

Run:  ./venv312/bin/python scripts/blind_cascade_test.py [--window 15] [--seed 7]
      ./venv312/bin/python scripts/blind_cascade_test.py --reveal R.md K.json
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
import time
from datetime import date as _date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pydantic import BaseModel, Field  # noqa: E402

from src.config import config  # noqa: E402
from src.connections.candidate_assembly import (  # noqa: E402
    CandidateSet,
    assemble_candidates,
)
from src.connections.dismissals import DismissalStore  # noqa: E402
from src.connections.insight_metrics import (  # noqa: E402
    estimate_cost_usd,
    usage_tokens,
)
from src.connections.synthesis import (  # noqa: E402
    Connection,
    ConnectionSynthesizer,
)
from src.connections.verdict import ConnectionVerifier, apply_verdicts  # noqa: E402
from src.summarizer import detect_language  # noqa: E402

OPUS = "claude-opus-4-8"
SONNET = "claude-sonnet-4-6"
HAIKU = "claude-haiku-4-5-20251001"

H4_BAR_USD_MONTHLY = 2.60
ROMAN = ["I", "II", "III"]

_TRIAGE_TOOL = "emit_triage"


class TriageKeep(BaseModel):
    keep: List[str] = Field(default_factory=list)


_TRIAGE_SYSTEM = (
    "You pre-select notes for a connection-mining pass over a person's own "
    "voice notes. From the CANDIDATE notes (the non-NEW ones), keep the ones "
    "most likely to form a SURPRISING but grounded connection or contradiction "
    "with the NEW notes — shared entities, changed stances, transferable ideas. "
    "Prefer diverse, specific candidates over near-duplicates of the NEW notes. "
    f"Return ONLY the exact [[basename]] ids to keep via the {_TRIAGE_TOOL} tool."
)


def _client(api_key: str):
    import anthropic

    return anthropic.Anthropic(api_key=api_key)


def triage_filter(
    api_key: str, cands: CandidateSet, keep_n: int, model: str = HAIKU
) -> Tuple[CandidateSet, Any]:
    """One Haiku call: keep window + ~keep_n most promising non-window notes."""
    non_window = [n for n in cands.notes if n.basename not in cands.window_basenames]
    if len(non_window) <= keep_n:
        return cands, None

    lines = [f"Keep at most {keep_n} candidate notes.", "", "NEW notes:"]
    for n in cands.notes:
        if n.basename in cands.window_basenames:
            lines.append(f"[[{n.basename}]] | {n.date}")
            lines.append(n.summary_md.strip()[:400])
    lines.append("\nCANDIDATE notes (choose from these):")
    for n in non_window:
        lines.append(f"\n[[{n.basename}]] | {n.date}")
        lines.append(n.summary_md.strip()[:400])

    message = _client(api_key).messages.create(
        model=model,
        max_tokens=2048,
        timeout=60.0,
        system=_TRIAGE_SYSTEM,
        tools=[
            {
                "name": _TRIAGE_TOOL,
                "description": "Basenames of candidate notes to keep.",
                "input_schema": TriageKeep.model_json_schema(),
            }
        ],
        tool_choice={"type": "tool", "name": _TRIAGE_TOOL},
        messages=[{"role": "user", "content": "\n".join(lines)}],
    )
    keep: List[str] = []
    for block in message.content:
        if getattr(block, "type", None) == "tool_use":
            try:
                keep = TriageKeep.model_validate(block.input).keep
            except Exception:  # noqa: BLE001
                keep = []
    keep_set = {k.strip().strip("[]") for k in keep}
    kept_notes = [
        n
        for n in cands.notes
        if n.basename in cands.window_basenames or n.basename in keep_set
    ]
    filtered = CandidateSet(
        kept_notes,
        set(cands.window_basenames),
        set(cands.bridge_basenames),
        channel_map=dict(cands.channel_map),
    )
    return filtered, getattr(message, "usage", None)


CONDITIONS = [
    {"key": "A", "triage": False, "synthesis": OPUS, "verdict": None},
    {"key": "B", "triage": True, "synthesis": OPUS, "verdict": None},
    {"key": "C", "triage": True, "synthesis": SONNET, "verdict": OPUS},
]


def run_condition(
    spec: Dict[str, Any],
    base: CandidateSet,
    api_key: str,
    keep_n: int,
    language: Optional[str],
) -> Dict[str, Any]:
    t0 = time.time()
    cost = 0.0
    tokens_in = tokens_out = 0

    def _add_usage(model: str, usage: Any) -> None:
        nonlocal cost, tokens_in, tokens_out
        t = usage_tokens(usage)
        cost += estimate_cost_usd(
            model,
            t["input_tokens"],
            t["output_tokens"],
            cache_read_tokens=t["cache_read_tokens"],
            cache_write_tokens=t["cache_write_tokens"],
        )
        tokens_in += t["input_tokens"]
        tokens_out += t["output_tokens"]

    cands = base
    if spec["triage"]:
        cands, usage = triage_filter(api_key, base, keep_n)
        if usage is not None:
            _add_usage(HAIKU, usage)

    synth = ConnectionSynthesizer(api_key=api_key, model=spec["synthesis"])
    result = synth.synthesize(cands, [], language)
    _add_usage(spec["synthesis"], synth.last_usage)
    connections: List[Connection] = list(result.connections) if result else []
    known = {n.basename for n in cands.notes}
    connections = [
        c for c in connections if len(c.notes) >= 2 and all(b in known for b in c.notes)
    ]

    dropped = 0
    if spec["verdict"] and connections:
        verifier = ConnectionVerifier(api_key=api_key, model=spec["verdict"])
        verdicts = verifier.verify(
            connections, {n.basename: n for n in cands.notes}, language
        )
        _add_usage(spec["verdict"], verifier.last_usage)
        kept = apply_verdicts(connections, verdicts)
        dropped = len(connections) - len(kept)
        connections = kept

    return {
        "key": spec["key"],
        "mix": {
            "triage": HAIKU if spec["triage"] else None,
            "synthesis": spec["synthesis"],
            "verdict": spec["verdict"],
        },
        "connections": connections,
        "n_candidates": len(cands.notes),
        "verdict_dropped": dropped,
        "cost_usd": round(cost, 4),
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "latency_s": round(time.time() - t0, 1),
    }


def render_rating_file(shuffled: List[Dict[str, Any]]) -> str:
    lines = [
        "# Ślepa ocena digestów — kaskada modeli",
        "",
        "Oceń każde połączenie w linii `ocena:` — skala:",
        "`2` działałbym na tym · `1` ciekawe · `0` szum · `-1` zmyślone.",
        "NIE otwieraj pliku klucza przed skończeniem ocen.",
        "",
    ]
    for i, res in enumerate(shuffled):
        lines.append(f"## Digest {ROMAN[i]}")
        if not res["connections"]:
            lines.append("\n(pusty — brak połączeń)\n")
            continue
        for j, c in enumerate(res["connections"], 1):
            lines.append(f"\n### {ROMAN[i]}.{j} [{c.type}]")
            lines.append("notatki: " + ", ".join(f"[[{b}]]" for b in c.notes))
            lines.append(f"\n{c.rationale}\n")
            for ev in c.evidence:
                lines.append(f"- [[{ev.note}]] {ev.date}: „{ev.quote}”")
            if c.directions:
                lines.append("")
                for d in c.directions:
                    lines.append(f"- {d}")
            lines.append("\nocena: ")
        lines.append("")
    return "\n".join(lines)


def reveal(ratings_path: Path, key_path: Path) -> int:
    key = json.loads(key_path.read_text(encoding="utf-8"))
    text = ratings_path.read_text(encoding="utf-8")

    scores: Dict[str, List[int]] = {}
    current = None
    for line in text.splitlines():
        m = re.match(r"^## Digest (I{1,3})\s*$", line.strip())
        if m:
            current = m.group(1)
            scores.setdefault(current, [])
            continue
        m = re.match(r"^ocena:\s*(-?\d+)", line.strip())
        if m and current:
            scores[current].append(int(m.group(1)))

    interval = getattr(config, "CONNECTIONS_DIGEST_INTERVAL_DAYS", 7) or 7
    print("=== REVEAL ===")
    for label, cond_key in key["label_to_condition"].items():
        cond = next(c for c in key["conditions"] if c["key"] == cond_key)
        s = scores.get(label, [])
        mean = sum(s) / len(s) if s else float("nan")
        per_dollar = (mean / cond["cost_usd"]) if s and cond["cost_usd"] else 0.0
        monthly = cond["cost_usd"] * (30 / interval)
        print(
            f"Digest {label} = {cond_key} "
            f"(triage={cond['mix']['triage'] or '—'}, synth={cond['mix']['synthesis']}, "
            f"verdict={cond['mix']['verdict'] or '—'})"
        )
        print(
            f"  ratings: {s}  mean={mean:.2f}  score/$={per_dollar:.2f}  "
            f"cost/run=${cond['cost_usd']:.4f}  monthly-eq=${monthly:.2f}"
        )
        if cond_key == "C":
            verdict = "PASS" if monthly <= H4_BAR_USD_MONTHLY else "OVER BAR"
            print(
                f"  H4: condition C monthly-equivalent ${monthly:.2f} "
                f"vs ${H4_BAR_USD_MONTHLY:.2f} bar -> {verdict}"
            )
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--window", type=int, default=15)
    ap.add_argument("--keep", type=int, default=12, help="triage keep count")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--reveal", nargs=2, metavar=("RATINGS", "KEY"))
    args = ap.parse_args()

    if args.reveal:
        return reveal(Path(args.reveal[0]), Path(args.reveal[1]))

    api_key = os.environ.get("ANTHROPIC_API_KEY") or config.LLM_API_KEY
    if not api_key:
        print("no API key (settings or ANTHROPIC_API_KEY)")
        return 1

    vault = Path(config.TRANSCRIBE_DIR)
    dismissals = DismissalStore(vault).load()
    base = assemble_candidates(
        vault,
        None,
        dismissals,
        first_run_window=args.window,
        inject_bridges=config.SYNTHESIS_BRIDGE_COUNT,
        # Entity channel is off in the production default (unvalidated); the
        # blind test evaluates the full prototype pipeline, so turn it on here.
        inject_entities=4,
    )
    if len(base.notes) < 4:
        print(
            f"only {len(base.notes)} candidates — vault unreadable (TCC?) or too "
            "small; run from a terminal with Full Disk Access."
        )
        return 1
    language = detect_language(" ".join(n.summary_md for n in base.notes)[:5000])
    print(
        f"base candidate set: {len(base.notes)} notes "
        f"({len(base.window_basenames)} window) | language={language}"
    )

    results = []
    for spec in CONDITIONS:
        print(f"condition {spec['key']} ...")
        results.append(run_condition(spec, base, api_key, args.keep, language))
        r = results[-1]
        print(
            f"  {len(r['connections'])} connections | ${r['cost_usd']:.4f} | "
            f"{r['latency_s']}s | dropped={r['verdict_dropped']}"
        )

    rng = random.Random(args.seed)
    shuffled = list(results)
    rng.shuffle(shuffled)

    out_dir = Path(__file__).resolve().parents[1] / "Docs" / "future"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = _date.today().isoformat()
    ratings_path = out_dir / f"blind-cascade-ratings-{stamp}.md"
    key_path = out_dir / f"blind-cascade-key-{stamp}.json"

    ratings_path.write_text(render_rating_file(shuffled) + "\n", encoding="utf-8")
    key = {
        "seed": args.seed,
        "date": stamp,
        "label_to_condition": {ROMAN[i]: r["key"] for i, r in enumerate(shuffled)},
        "conditions": [
            {k: v for k, v in r.items() if k != "connections"} for r in results
        ],
    }
    key_path.write_text(
        json.dumps(key, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print(f"\nrating file -> {ratings_path}")
    print(f"answer key  -> {key_path}   (DO NOT open before rating)")
    print(
        "\nafter rating run:\n"
        f"  ./venv312/bin/python scripts/blind_cascade_test.py --reveal "
        f"{ratings_path} {key_path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
