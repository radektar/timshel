#!/usr/bin/env python3
"""Sonnet 5 vs Opus 4.8 digest eval — real corpus, blind, measured cost.

Replays THREE consecutive archive windows (the production seen-set mechanism,
simulated in-process — the real scheduler state is never touched) and runs
both models on the IDENTICAL candidate set per window: synthesis + verdict
(verifier = same model), full prototype channels, costs computed from the
API's actual usage (Sonnet 5's tokenizer yields ~30% more tokens, so list
price alone lies).

Outputs:
  * blind report — connections labelled Model A/B per window, shuffled, for
    the human blind read (the deciding instrument),
  * answer key + measured cost/drop-rate table (open AFTER judging).

Run:  venv312/bin/python scripts/eval_sonnet5.py [--windows 3]
Costs real API money (~$2-3 total). Reads the vault read-only.
"""

from __future__ import annotations

import argparse
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import config  # noqa: E402

MODELS = ["claude-sonnet-5", "claude-opus-4-8"]
LABEL = {"claude-sonnet-5": "Sonnet 5", "claude-opus-4-8": "Opus 4.8"}
# Standard rates (2026-07-24). Sonnet 5 intro promo $2/$10 until 2026-08-31 —
# we report the permanent rate; the promo column is derived in the report.
PRICES = {"claude-sonnet-5": (3.0, 15.0), "claude-opus-4-8": (5.0, 25.0)}

OUT_DIR = Path("/tmp")
BLIND = OUT_DIR / "sonnet5_eval_BLIND.md"
KEY = OUT_DIR / "sonnet5_eval_ANSWER_KEY.md"


def _usage_cost(model: str, usage) -> tuple[int, int, float]:
    it = int(getattr(usage, "input_tokens", 0) or 0)
    ot = int(getattr(usage, "output_tokens", 0) or 0)
    pin, pout = PRICES[model]
    return it, ot, (it * pin + ot * pout) / 1_000_000.0


def _render_conns(conns) -> list[str]:
    out = []
    for i, c in enumerate(conns, 1):
        notes = ", ".join(f"[[{b}]]" for b in c.notes)
        out.append(f"**{i}. {c.type}** — {notes}")
        out.append(f"> {c.rationale}")
        for e in getattr(c, "evidence", []) or []:
            out.append(f"  - _{e.note} ({e.date})_: „{e.quote}”")
        for d in c.directions:
            out.append(f"  - {d}")
        out.append("")
    if not conns:
        out.append("_Brak połączeń, które przeżyły weryfikację._\n")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--windows", type=int, default=3)
    args = ap.parse_args()

    if not config.LLM_API_KEY:
        print("no API key — aborting")
        return 1

    from src.config.tester_mode import apply_tester_overrides

    # Full prototype channels; the per-call model is set explicitly below.
    apply_tester_overrides(MODELS[0])
    config.INSIGHT_METRICS_ENABLED = False  # eval must not pollute the ledger

    from src.connections.candidate_assembly import assemble_candidates
    from src.connections.dismissals import DismissalStore
    from src.connections.synthesis import ConnectionSynthesizer
    from src.connections.verdict import ConnectionVerifier, apply_verdicts
    from src.summarizer import detect_language

    vault = Path(config.TRANSCRIBE_DIR)
    dismissals = DismissalStore(vault).load()
    seen: set[str] = set()
    rng = random.Random(20260724)

    blind: list[str] = ["# Sonnet 5 vs Opus — ŚLEPY ODCZYT", ""]
    blind.append(
        "Per okno: te same notatki, dwa modele jako **Model A / Model B** "
        "(przypisanie losowe per okno). Oceń per połączenie: które lepsze "
        "(A/B/remis) i czy w ogóle prawdziwe. Klucz otwórz PO ocenie.\n"
    )
    key_lines: list[str] = ["# ANSWER KEY + koszty (otwierać po ślepym odczycie)", ""]
    totals: dict[str, dict] = {
        m: {"cost": 0.0, "proposed": 0, "kept": 0, "in": 0, "out": 0} for m in MODELS
    }

    for w in range(1, args.windows + 1):
        candidates = assemble_candidates(
            vault,
            None,
            dismissals,
            inject_bridges=config.SYNTHESIS_BRIDGE_COUNT,
            inject_entities=config.SYNTHESIS_ENTITY_COUNT,
            inject_dense=config.SYNTHESIS_DENSE_COUNT,
            inject_graph=config.SYNTHESIS_GRAPH_COUNT,
            inject_stance=config.SYNTHESIS_STANCE_COUNT,
            seen_keys=seen,
        )
        if len(candidates.notes) < 2:
            print(f"window {w}: <2 candidates, stopping")
            break
        language = detect_language(
            " ".join(n.summary_md for n in candidates.notes)[:5000]
        )
        window_dates = sorted(
            n.date for n in candidates.notes if n.basename in candidates.window_basenames
        )
        print(
            f"window {w}: {len(candidates.notes)} candidates "
            f"({len(candidates.window_basenames)} new, {window_dates[0]}"
            f"..{window_dates[-1]})"
        )

        results = {}
        for model in MODELS:
            synth = ConnectionSynthesizer(api_key=config.LLM_API_KEY, model=model)
            t0 = time.time()
            result = synth.synthesize(candidates, [], language)
            s_in, s_out, s_cost = _usage_cost(model, synth.last_usage)
            conns = [
                c
                for c in (result.connections if result else [])
                if len(c.notes) >= 2
                and all(b in {n.basename for n in candidates.notes} for b in c.notes)
            ]
            proposed = len(conns)
            verifier = ConnectionVerifier(api_key=config.LLM_API_KEY, model=model)
            v_in = v_out = 0
            v_cost = 0.0
            if conns:
                verdicts = verifier.verify(
                    conns, {n.basename: n for n in candidates.notes}, language
                )
                if verdicts is not None:
                    conns = apply_verdicts(conns, verdicts)
                v_in, v_out, v_cost = _usage_cost(model, verifier.last_usage)
            dt = time.time() - t0
            results[model] = dict(
                conns=conns, proposed=proposed, cost=s_cost + v_cost, dt=dt
            )
            t = totals[model]
            t["cost"] += s_cost + v_cost
            t["proposed"] += proposed
            t["kept"] += len(conns)
            t["in"] += s_in + v_in
            t["out"] += s_out + v_out
            print(
                f"  {LABEL[model]}: {proposed} proposed -> {len(conns)} kept, "
                f"${s_cost + v_cost:.4f}, {dt:.0f}s"
            )

        order = MODELS[:]
        rng.shuffle(order)
        blind.append(f"\n## Okno {w}  ({window_dates[0]} … {window_dates[-1]})\n")
        for tag, model in zip(("A", "B"), order):
            blind.append(f"### Model {tag}\n")
            blind.extend(_render_conns(results[model]["conns"]))
        key_lines.append(
            f"Okno {w}: A = {LABEL[order[0]]}, B = {LABEL[order[1]]} · "
            + " · ".join(
                f"{LABEL[m]}: {results[m]['proposed']}→{len(results[m]['conns'])} "
                f"(${results[m]['cost']:.4f}, {results[m]['dt']:.0f}s)"
                for m in MODELS
            )
        )
        seen |= candidates.window_keys

    key_lines.append("\n## Suma (koszt z realnego usage, stawki standardowe)\n")
    for m in MODELS:
        t = totals[m]
        drop = (t["proposed"] - t["kept"]) / t["proposed"] if t["proposed"] else 0.0
        promo = ""
        if m == "claude-sonnet-5":
            promo_cost = (t["in"] * 2.0 + t["out"] * 10.0) / 1_000_000.0
            promo = f" (promo do 31.08: ${promo_cost:.4f})"
        key_lines.append(
            f"- **{LABEL[m]}**: ${t['cost']:.4f} za {args.windows} okna{promo} · "
            f"tokeny {t['in']}/{t['out']} · propozycje {t['proposed']} → "
            f"przeżyło {t['kept']} (drop {drop:.0%})"
        )

    BLIND.write_text("\n".join(blind), encoding="utf-8")
    KEY.write_text("\n".join(key_lines), encoding="utf-8")
    print(f"\nblind report -> {BLIND}\nanswer key   -> {KEY}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
