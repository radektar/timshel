#!/usr/bin/env python3
"""Recall harness for hypothesis H3 — can preselection REACH the planted pairs?

For every confirmed planted pair (scripts/bootstrap_planted_pairs.py) this
replays candidate assembly as it would have run the day the pair's NEWER note
arrived (time-travel via ``as_of``: notes after that day do not exist yet;
``last_digest_at`` = the day before, so the newer note is the window). A pair
is a HIT when ALL of its older notes surface in the candidate set — synthesis
cannot link what assembly never showed it.

Runs the whole pair set under four channel configs (all local, $0):
full (bridges+entities, production), no-entity, no-bridge, similarity-only —
so the report shows what each distance channel actually buys ("unique saves").

H3 verdict line (on the FULL config): recall >=70% pass, <50% kill.

Pairs whose notes share the newer note's date are classified WINDOW-COLLISION
and excluded from the denominator: date granularity puts both notes in the
window, so the pair says nothing about preselection.

Optional --synthesize N runs the real synthesizer over up to N hit pairs
(~$0.25/pair on Opus) and reports the surfaced->linked conversion SEPARATELY —
H3 itself is preselection-only.

Run:  ./venv312/bin/python scripts/recall_eval.py
      ./venv312/bin/python scripts/recall_eval.py --synthesize 10
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import date as _date
from pathlib import Path
from typing import Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import config  # noqa: E402
from src.connections.candidate_assembly import assemble_candidates  # noqa: E402
from src.connections.dismissals import DismissalStore  # noqa: E402

H3_PASS = 0.70
H3_KILL = 0.50

# (name, bridges, entities, dense)
CONFIGS = [
    ("full", 4, 4, 6),
    ("no-dense", 4, 4, 0),
    ("no-entity", 4, 0, 6),
    ("no-bridge", 0, 4, 6),
    ("similarity-only", 0, 0, 0),
]


@dataclass
class PairResult:
    pair_id: str
    pair_type: str
    source: str
    status: str  # hit | miss | window-collision | skipped
    older_channels: Dict[str, List[str]] = field(default_factory=dict)
    missing: List[str] = field(default_factory=list)
    # subset of `missing` that a channel DID rank but the note-count cap /
    # char budget cut — a budget problem, not a discovery problem.
    missing_but_ranked: List[str] = field(default_factory=list)
    linked_by_llm: Optional[bool] = None


def note_dates(pair: dict, corpus_dates: Dict[str, str]) -> Optional[Dict[str, str]]:
    """basename -> date for the pair's notes; None when a date is unknown."""
    out: Dict[str, str] = {}
    for b in pair.get("notes", []):
        d = corpus_dates.get(b, "")
        if not d:
            return None
        out[b] = d
    return out


def simulate_pair(
    pair: dict,
    vault: Path,
    dismissals: DismissalStore,
    bridges: int,
    entities: int,
    corpus_dates: Dict[str, str],
    dense: int = 0,
) -> PairResult:
    base = PairResult(
        pair_id=pair.get("id", "?"),
        pair_type=pair.get("type", "?"),
        source=pair.get("source", "?"),
        status="skipped",
    )
    dates = note_dates(pair, corpus_dates)
    if not dates:
        return base  # note vanished from corpus or has no date
    newer = max(dates, key=lambda b: dates[b])
    older = [b for b in pair["notes"] if b != newer]
    if any(dates[b] == dates[newer] for b in older):
        base.status = "window-collision"
        return base

    # last_digest_at = the newer note's OWN date, not the day before. The window
    # is `note.date >= cutoff`, so the newer note (== cutoff) is the sole window
    # member, while an older note dated one day earlier is now < cutoff and must
    # be reached by a real preselection channel — not handed a free "window" hit.
    cands = assemble_candidates(
        vault,
        f"{dates[newer]}T00:00:00",
        dismissals,
        inject_bridges=bridges,
        inject_entities=entities,
        inject_dense=dense,
        as_of=dates[newer],
    )
    surfaced = {n.basename for n in cands.notes}
    base.missing = [b for b in older if b not in surfaced]
    base.missing_but_ranked = [b for b in base.missing if b in cands.precap_basenames]
    base.older_channels = {
        b: sorted(cands.channel_map.get(b, set())) for b in older if b in surfaced
    }
    base.status = "hit" if not base.missing else "miss"
    return base


def run_config(
    pairs: List[dict],
    vault: Path,
    dismissals: DismissalStore,
    bridges: int,
    entities: int,
    corpus_dates: Dict[str, str],
    dense: int = 0,
) -> List[PairResult]:
    return [
        simulate_pair(p, vault, dismissals, bridges, entities, corpus_dates, dense)
        for p in pairs
    ]


def recall_of(results: List[PairResult]) -> tuple:
    """(recall, hits, denominator) excluding collisions/skips."""
    counted = [r for r in results if r.status in ("hit", "miss")]
    hits = sum(1 for r in counted if r.status == "hit")
    return (hits / len(counted) if counted else 0.0, hits, len(counted))


def _split_recall(results: List[PairResult], key) -> Dict[str, tuple]:
    groups: Dict[str, List[PairResult]] = {}
    for r in results:
        groups.setdefault(key(r), []).append(r)
    return {k: recall_of(v) for k, v in sorted(groups.items())}


def render_report(
    by_config: Dict[str, List[PairResult]],
    n_pairs: int,
    synth_results: Optional[Dict[str, bool]] = None,
) -> str:
    lines: List[str] = []
    add = lines.append
    add("# Recall eval (H3) — planted pairs vs candidate assembly\n")
    full = by_config["full"]
    collisions = sum(1 for r in full if r.status == "window-collision")
    skipped = sum(1 for r in full if r.status == "skipped")
    add(
        f"pairs: {n_pairs} confirmed | window-collisions excluded: {collisions} "
        f"| skipped (missing note/date): {skipped}\n"
    )

    add("## Recall per config\n")
    add("| config | recall | hits/denominator |")
    add("|---|---|---|")
    for name, results in by_config.items():
        rec, hits, denom = recall_of(results)
        add(f"| {name} | {rec:.0%} | {hits}/{denom} |")

    rec, hits, denom = recall_of(full)
    verdict = (
        "PASS (>=70%)"
        if rec >= H3_PASS
        else (
            "KILL (<50%) — fix preselection before anything else"
            if rec < H3_KILL
            else "GREY ZONE (50-70%) — iterate preselection"
        )
    )
    add(f"\n**H3 verdict (full config): {rec:.0%} -> {verdict}**\n")

    add("## Full config — split by pair type\n")
    for k, (r, h, d) in _split_recall(full, lambda x: x.pair_type).items():
        add(f"- {k}: {r:.0%} ({h}/{d})")
    add("\n## Full config — split by source (bootstrap-bias detector)\n")
    for k, (r, h, d) in _split_recall(full, lambda x: x.source).items():
        add(f"- {k}: {r:.0%} ({h}/{d})")

    add("\n## Channel attribution (full config, hits)\n")
    channel_counts: Dict[str, int] = {}
    for r in full:
        if r.status != "hit":
            continue
        for chans in r.older_channels.values():
            for c in chans:
                channel_counts[c] = channel_counts.get(c, 0) + 1
    for c, n in sorted(channel_counts.items(), key=lambda kv: -kv[1]):
        add(f"- {c}: {n} surfaced-note credits")

    add("\n## Unique saves per distance channel\n")
    full_hits = {r.pair_id for r in full if r.status == "hit"}
    for name, label in (
        ("no-dense", "dense"),
        ("no-entity", "entity"),
        ("no-bridge", "bridge"),
    ):
        if name not in by_config:
            continue
        off_hits = {r.pair_id for r in by_config[name] if r.status == "hit"}
        saves = sorted(full_hits - off_hits)
        add(f"- {label}: {len(saves)} pairs only reachable with it: {saves}")

    add("\n## Misses (full config) — diagnostics\n")
    cut = found_never = 0
    for r in full:
        if r.status == "miss":
            ranked_cut = set(r.missing_but_ranked)
            cut += len(ranked_cut)
            found_never += len([b for b in r.missing if b not in ranked_cut])
            detail = ", ".join(
                f"{b} (RANKED-BUT-CUT)" if b in ranked_cut else f"{b} (never found)"
                for b in r.missing
            )
            add(f"- {r.pair_id} [{r.pair_type}]: {detail}")
    add(
        f"\nMiss anatomy: {cut} notes ranked-but-cut (budget problem: raise "
        f"MAX_SYNTHESIS_NOTES / rebalance channels) vs {found_never} never found "
        f"(discovery problem: channels blind to them)."
    )

    if synth_results is not None:
        linked = sum(1 for v in synth_results.values() if v)
        add(
            f"\n## Surfaced -> linked (separate from H3): "
            f"{linked}/{len(synth_results)} sampled hit pairs linked by synthesis\n"
        )
        for pid, ok in sorted(synth_results.items()):
            add(f"- {pid}: {'linked' if ok else 'NOT linked'}")
    return "\n".join(lines)


def synthesize_sample(
    hit_pairs: List[dict],
    vault: Path,
    dismissals: DismissalStore,
    corpus_dates: Dict[str, str],
    limit: int,
    model: Optional[str],
) -> Dict[str, bool]:
    from src.connections.synthesis import ConnectionSynthesizer
    from src.summarizer import detect_language

    api_key = config.LLM_API_KEY
    if not api_key:
        print("no API key — skipping --synthesize")
        return {}
    out: Dict[str, bool] = {}
    for pair in hit_pairs[:limit]:
        dates = note_dates(pair, corpus_dates)
        if not dates:
            continue  # defensive: a hit pair should always have dates
        newer = max(dates, key=lambda b: dates[b])
        older = [b for b in pair["notes"] if b != newer]
        cands = assemble_candidates(
            vault,
            f"{dates[newer]}T00:00:00",
            dismissals,
            inject_bridges=4,
            inject_entities=4,
            inject_dense=6,
            as_of=dates[newer],
        )
        language = detect_language(" ".join(n.summary_md for n in cands.notes)[:5000])
        synth = ConnectionSynthesizer(api_key=api_key, model=model or "claude-opus-4-8")
        result = synth.synthesize(cands, [], language)
        linked = False
        if result is not None:
            for c in result.connections:
                if newer in c.notes and any(o in c.notes for o in older):
                    linked = True
                    break
        out[pair.get("id", "?")] = linked
        print(f"  {pair.get('id')}: {'linked' if linked else 'not linked'}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pairs", type=Path, default=None, help="planted_pairs.json path")
    ap.add_argument("--synthesize", type=int, default=0, metavar="N")
    ap.add_argument("--model", default=None)
    ap.add_argument("--out", type=Path, default=None, help="markdown report path")
    args = ap.parse_args()

    vault = Path(config.TRANSCRIBE_DIR)
    pairs_file = args.pairs or (vault / ".malinche" / "planted_pairs.json")
    try:
        data = json.loads(pairs_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"cannot read {pairs_file}: {exc}")
        return 1
    confirmed = [p for p in data.get("pairs", []) if p.get("confirmed") is True]
    if not confirmed:
        print("no confirmed pairs — run bootstrap_planted_pairs.py confirm first")
        return 1

    from src.connections.candidate_assembly import load_corpus

    corpus = load_corpus(vault)
    if len(corpus) < 10:
        print(
            f"corpus suspiciously small ({len(corpus)} notes) — likely a "
            "TCC-blocked process; run from a terminal with Full Disk Access."
        )
        return 1
    corpus_dates = {n.basename: n.date for n in corpus}
    dismissals = DismissalStore(vault).load()

    by_config: Dict[str, List[PairResult]] = {}
    for name, bridges, entities, dense in CONFIGS:
        print(
            f"config {name} (bridges={bridges}, entities={entities}, "
            f"dense={dense}) ..."
        )
        by_config[name] = run_config(
            confirmed, vault, dismissals, bridges, entities, corpus_dates, dense
        )

    synth_results = None
    if args.synthesize > 0:
        hit_ids = {r.pair_id for r in by_config["full"] if r.status == "hit"}
        hit_pairs = [p for p in confirmed if p.get("id") in hit_ids]
        print(f"synthesize sample over {min(args.synthesize, len(hit_pairs))} pairs")
        synth_results = synthesize_sample(
            hit_pairs, vault, dismissals, corpus_dates, args.synthesize, args.model
        )

    report = render_report(by_config, len(confirmed), synth_results)
    print("\n" + report)
    out_path = args.out or (
        Path(__file__).resolve().parents[1]
        / "Docs"
        / "future"
        / f"recall-eval-{_date.today().isoformat()}.md"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report + "\n", encoding="utf-8")
    print(f"\nreport -> {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
