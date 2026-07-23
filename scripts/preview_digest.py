#!/usr/bin/env python3
"""Preview the REAL connection digest on the live corpus — Haiku vs Opus.

Faithfully replays the production path (`run_digest_if_due`): same candidate
assembly (including the seen-set window production uses; the date window is
legacy), same prompt, same schema — but runs synthesis once per model on the
*same* candidate set and renders a side-by-side comparison to a markdown file
instead of writing into the vault. This is the on-real-data validation step the
gold-case eval cannot give: it shows the actual quality of connections on your
own notes.

Two passes:
  1. PRODUCTION defaults — exactly what the feature ships today.
  2. WIDE window — more context budget, to see the depth headroom.

Run:  venv312/bin/python scripts/preview_digest.py
Reads the vault read-only; writes only the comparison file (path printed).
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import config  # noqa: E402
from src.connections.candidate_assembly import (  # noqa: E402
    CandidateSet,
    assemble_candidates,
)
from src.connections.dismissals import DismissalStore  # noqa: E402
from src.connections.synthesis import ConnectionSynthesizer  # noqa: E402
from src.summarizer import APIBillingError, detect_language  # noqa: E402

MODELS = ["claude-haiku-4-5-20251001", "claude-opus-4-8"]
LABEL = {"claude-haiku-4-5-20251001": "Haiku 4.5", "claude-opus-4-8": "Opus 4.8"}
PRICES = {  # USD per 1M tokens (input, output) — verified 2026-06-23
    "claude-opus-4-8": (5.0, 25.0),  # standard rate; $15/$75 was Opus 4.1
    "claude-haiku-4-5-20251001": (1.0, 5.0),
}

OUT = Path("/tmp/malinche_digest_compare.md")


def _cost(model: str, usage) -> float:
    if usage is None:
        return 0.0
    pin, pout = PRICES.get(model, (0.0, 0.0))
    it = getattr(usage, "input_tokens", 0) or 0
    ot = getattr(usage, "output_tokens", 0) or 0
    return (it * pin + ot * pout) / 1_000_000.0


def _tokens(usage) -> int:
    it = getattr(usage, "input_tokens", 0) or 0
    ot = getattr(usage, "output_tokens", 0) or 0
    return it + ot


def _apply(window: int, max_notes: int, prompt_chars: int, note_chars: int) -> None:
    config.MAX_SYNTHESIS_NOTES = max_notes
    config.MAX_SYNTHESIS_PROMPT_CHARS = prompt_chars
    config.MAX_SYNTHESIS_NOTE_CHARS = note_chars


def _render_candidates(cands: CandidateSet) -> str:
    lines = []
    for n in cands.notes:
        new = " **NEW**" if n.basename in cands.window_basenames else ""
        tags = ", ".join(n.tags) if n.tags else "—"
        lines.append(f"- `{n.date or '????-??-??'}` [[{n.basename}]] · {tags}{new}")
    return "\n".join(lines)


def _render_connections(result) -> str:
    if result is None:
        return "_(błąd wywołania — brak wyniku)_\n"
    if not result.connections:
        return "_Brak połączeń (model uznał, że nic się genuinnie nie łączy)._\n"
    out = []
    for i, c in enumerate(result.connections, 1):
        notes = ", ".join(f"[[{b}]]" for b in c.notes)
        out.append(f"**{i}. {c.type}** — {notes}")
        out.append(f"> {c.rationale}")
        for d in c.directions:
            out.append(f"  - {d}")
        out.append("")
    return "\n".join(out)


def run_pass(name: str, cfg: dict, key: str, language_hint: str) -> str:
    _apply(**cfg)
    vault = Path(config.TRANSCRIBE_DIR)
    dismissals = DismissalStore(vault).load()
    # Window like production: by the digest's seen-set when one exists (the
    # date window is legacy). Read-only — no migration here, so a
    # pre-migration state falls back to the equivalent newest-N window.
    from src.connections.scheduler import get_scheduler

    cands = assemble_candidates(
        vault,
        None,
        dismissals,
        first_run_window=cfg["window"],
        seen_keys=get_scheduler().seen_note_keys,
    )
    lang = detect_language(" ".join(n.summary_md for n in cands.notes)[:5000])
    n_new = len(cands.window_basenames)

    block = [
        f"## {name}",
        f"Kandydaci: **{len(cands.notes)}** notatek "
        f"({n_new} nowych w oknie) · język: `{lang}` · "
        f"okno={cfg['window']} max_notes={cfg['max_notes']} "
        f"budżet={cfg['prompt_chars']} znaków",
        "",
        "<details><summary>Notatki, które model widział</summary>",
        "",
        _render_candidates(cands),
        "",
        "</details>",
        "",
    ]

    for model in MODELS:
        synth = ConnectionSynthesizer(api_key=key, model=model)
        t0 = time.time()
        try:
            result = synth.synthesize(cands, language=lang)
        except APIBillingError as exc:
            block.append(f"### {LABEL[model]} — BŁĄD: {exc}\n")
            continue
        dt = time.time() - t0
        cost = _cost(model, synth.last_usage)
        toks = _tokens(synth.last_usage)
        nconn = len(result.connections) if result else 0
        block.append(
            f"### {LABEL[model]} — {nconn} połączeń · "
            f"~${cost:.4f} · {toks} tok · {dt:.1f}s"
        )
        block.append("")
        block.append(_render_connections(result))
        block.append("")
        print(f"  {name} / {LABEL[model]}: {nconn} conn, " f"${cost:.4f}, {dt:.1f}s")

    return "\n".join(block)


def main() -> int:
    key = config.LLM_API_KEY
    if not key:
        print("No Claude API key in Malinche settings — set one and retry.")
        return 1

    passes = [
        (
            "Pass 1 — ustawienia produkcyjne (to co działa dziś)",
            dict(window=15, max_notes=25, prompt_chars=30000, note_chars=1200),
        ),
        (
            "Pass 2 — szersze okno (potencjał z większym budżetem)",
            dict(window=20, max_notes=35, prompt_chars=70000, note_chars=1600),
        ),
    ]

    header = [
        "# Malinche — podgląd digestu na realnym korpusie",
        "",
        f"Korpus: **164 notatki** w `11-Transcripts`. "
        "Ten sam pipeline co produkcja (`run_digest_if_due`), "
        "synteza puszczona Haiku vs Opus na identycznym zestawie kandydatów. "
        "Vault czytany read-only; nic nie zapisano do notatek.",
        "",
        f"_Wygenerowano: {time.strftime('%Y-%m-%d %H:%M')}_",
        "",
        "---",
        "",
    ]

    print(f"Preview digest — {len(passes)} passes x {len(MODELS)} models\n")
    body = []
    for name, cfg in passes:
        body.append(run_pass(name, cfg, key, "pl"))
        body.append("\n---\n")

    OUT.write_text("\n".join(header + body), encoding="utf-8")
    print(f"\nWritten: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
