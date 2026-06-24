#!/usr/bin/env python3
"""Compare synthesis models on the gold cases — the model-decision tool.

Runs every gold case (tests/fixtures/synthesis_cases.py) through the REAL
``ConnectionSynthesizer`` for each candidate model and reports a table of
{gold-pass, tokens, $, latency}. This is how we pick ``LLM_MODEL_SYNTHESIS``
(Opus 4.8 vs Sonnet 4.6 vs Haiku) empirically rather than by opinion.

The deterministic gold checks carry the hard signal (no LLM-judge bias). Token
counts are exact; the $ column uses the approximate prices below — edit them to
current pricing before trusting the dollar figure.

Run:  make eval-synthesis     (uses the BYOK key from your Malinche settings)
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import config  # noqa: E402
from src.connections.synthesis import (  # noqa: E402
    ConnectionList,
    ConnectionSynthesizer,
)
from src.summarizer import APIBillingError, detect_language  # noqa: E402
from tests.fixtures.synthesis_cases import GOLD_CASES  # noqa: E402

MODELS = [
    "claude-opus-4-8",
    "claude-sonnet-4-6",
    "claude-haiku-4-5-20251001",
]

# List prices, USD per 1M tokens (input, output).
# Verified against Anthropic's official pricing page on 2026-06-23.
# NOTE: Opus 4.8 is $5/$25 (NOT the $15/$75 of the deprecated Opus 4.1);
# the 1M context window is billed at standard rates (no long-context premium).
PRICES = {
    "claude-opus-4-8": (5.0, 25.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-haiku-4-5-20251001": (1.0, 5.0),
}


def _tokens(usage) -> int:
    it = getattr(usage, "input_tokens", 0) or 0
    ot = getattr(usage, "output_tokens", 0) or 0
    return it + ot


def _cost(model: str, usage) -> float:
    if usage is None:
        return 0.0
    pin, pout = PRICES.get(model, (0.0, 0.0))
    it = getattr(usage, "input_tokens", 0) or 0
    ot = getattr(usage, "output_tokens", 0) or 0
    return (it * pin + ot * pout) / 1_000_000.0


def main() -> int:
    key = config.LLM_API_KEY
    if not key:
        print("No Claude API key in Malinche settings — set one and retry.")
        return 1

    n = len(GOLD_CASES)
    print(f"Synthesis model eval — {n} gold cases x {len(MODELS)} models\n")
    results = {}
    for model in MODELS:
        synth = ConnectionSynthesizer(api_key=key, model=model)
        rows, passed, tokens, cost, latency = [], 0, 0, 0.0, 0.0
        for case in GOLD_CASES:
            cands = case.candidates()
            lang = detect_language(" ".join(x.summary_md for x in cands.notes)[:4000])
            t0 = time.time()
            try:
                out = synth.synthesize(cands, language=lang) or ConnectionList()
            except APIBillingError as exc:
                print(f"  permanent API error on {model}: {exc}")
                return 2
            dt = time.time() - t0
            ok, _detail = case.check(out)
            passed += 1 if ok else 0
            tokens += _tokens(synth.last_usage)
            cost += _cost(model, synth.last_usage)
            latency += dt
            rows.append(ok)
        results[model] = dict(
            rows=rows, passed=passed, tokens=tokens, cost=cost, latency=latency
        )

    # Per-case matrix
    header = "case".ljust(28) + "".join(m.split("-")[1][:7].rjust(9) for m in MODELS)
    print(header)
    for i, case in enumerate(GOLD_CASES):
        line = case.name.ljust(28)
        for m in MODELS:
            line += ("PASS" if results[m]["rows"][i] else "fail").rjust(9)
        print(line)

    # Summary
    print(
        "\n"
        + "model".ljust(30)
        + "gold".rjust(7)
        + "tokens".rjust(9)
        + "$/run".rjust(10)
        + "avg_s".rjust(8)
    )
    for m in MODELS:
        r = results[m]
        print(
            m.ljust(30)
            + f"{r['passed']}/{n}".rjust(7)
            + str(r["tokens"]).rjust(9)
            + f"{r['cost']:.4f}".rjust(10)
            + f"{r['latency'] / n:.1f}".rjust(8)
        )
    print("\n(prices approximate — verify before trusting $; token counts exact)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
