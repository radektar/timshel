#!/usr/bin/env python3
"""Planted-pairs ground truth for the magic-insights prototype (H3).

The recall harness (scripts/recall_eval.py) needs a set of KNOWN-true
connection/contradiction pairs in the real vault to measure whether candidate
assembly can reach them. This tool builds that set with minimal human time:

  propose   one Opus call mines the whole corpus for 40-60 candidate pairs
            (over-generated on purpose — a human filters);
  confirm   interactive TAK/NIE loop over unconfirmed pairs (seconds per pair,
            thanks to verbatim evidence quotes);
  add       hand-entered pairs the LLM did NOT propose (bias guard: if these
            recall much worse than llm-proposed ones, the bootstrap was biased
            toward what the pipeline can already see);
  stats     counts by source/type/confirmed.

The fixture lives at ``{vault}/.timshel/planted_pairs.json`` — NEXT TO the
vault, never in the repo: it contains private note basenames and verbatim
quotes. The dismissed-connections list is deduped POST-HOC and never shown to
the propose prompt (telling the miner what was dismissed would steer it and
contaminate the ground truth).

Run:  ./venv312/bin/python scripts/bootstrap_planted_pairs.py propose
      ./venv312/bin/python scripts/bootstrap_planted_pairs.py confirm
      ./venv312/bin/python scripts/bootstrap_planted_pairs.py add
      ./venv312/bin/python scripts/bootstrap_planted_pairs.py stats
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pydantic import BaseModel, Field, ValidationError  # noqa: E402

from src.config import config  # noqa: E402
from src.connections.candidate_assembly import NoteRef, load_corpus  # noqa: E402
from src.connections.dismissals import DismissalStore  # noqa: E402
from src.connections.insight_metrics import estimate_cost_usd  # noqa: E402
from src.connections.signature import connection_signature  # noqa: E402

PAIRS_SCHEMA_VERSION = 1
_TOOL_NAME = "emit_planted_pairs"
DEFAULT_MODEL = "claude-opus-4-8"

_VALID_TYPES = ("contradiction-over-time", "emergent-idea", "shared-thread")


# --------------------------------------------------------------------------- #
# Schema (prototype tooling — deliberately local, not product code)
# --------------------------------------------------------------------------- #
class PairEvidence(BaseModel):
    note: str
    date: str = ""
    quote: str


class PlantedPair(BaseModel):
    notes: List[str] = Field(min_length=2)
    type: str
    why: str
    evidence: List[PairEvidence] = Field(default_factory=list)


class PlantedPairList(BaseModel):
    pairs: List[PlantedPair] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Fixture I/O
# --------------------------------------------------------------------------- #
def pairs_path() -> Path:
    return Path(config.TRANSCRIBE_DIR) / config.SIDECAR_DIR_NAME / "planted_pairs.json"


def load_pairs(path: Path) -> Dict[str, Any]:
    """Tolerant load; always returns a dict with v/created/pairs keys."""
    data: Dict[str, Any] = {}
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        print(f"! could not read {path} ({exc}); starting empty")
    if not isinstance(data, dict):
        data = {}
    data.setdefault("v", PAIRS_SCHEMA_VERSION)
    data.setdefault("created", datetime.now().isoformat(timespec="seconds"))
    data.setdefault("pairs", [])
    return data


def save_pairs(path: Path, data: Dict[str, Any]) -> None:
    """Atomic write (tmp + replace), mirroring DismissalStore._save."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def existing_sigs(data: Dict[str, Any]) -> Set[str]:
    return {p.get("sig", "") for p in data.get("pairs", []) if p.get("sig")}


def _next_id(data: Dict[str, Any]) -> str:
    return f"pp-{len(data.get('pairs', [])) + 1:03d}"


# --------------------------------------------------------------------------- #
# propose
# --------------------------------------------------------------------------- #
_PROPOSE_SYSTEM = (
    "You read a person's own voice notes (transcribed) and MINE CANDIDATE PAIRS "
    "for a ground-truth set. A human will review every proposal, so OVER-GENERATE: "
    "include plausible-but-uncertain pairs; propose 30-45 in total. Keep every "
    "field TIGHT — quotes at most ~15 words, 'why' one short sentence — so the "
    "full list fits in the response.\n\n"
    "Pair types (prioritise the first two; at most 1 in 4 may be shared-thread):\n"
    "- contradiction-over-time: the person's stance CHANGED between an earlier "
    "and a later note (use the dates). Highest value — hunt for these first, "
    "especially where the wording differs but the underlying stance flipped.\n"
    "- emergent-idea: two or more notes that do NOT obviously belong together "
    "combine into a claim the person never stated.\n"
    "- shared-thread: the same specific theme recurs. Lowest value.\n\n"
    "Hard rules:\n"
    "- Ground every pair in the supplied summaries. NEVER invent a link.\n"
    "- Reference notes by their exact [[basename]] id (as given).\n"
    "- 'why' is exactly one grounded sentence naming the specific tension or "
    "combination — not the shared topic. Write it in the LANGUAGE OF THE NOTES "
    "(Polish if the notes are Polish). The SUBJECT is the person, never the "
    "dates: 'w sierpniu zakładałeś X, w grudniu przesuwasz to za Y' — NOT "
    "'August proposes X, December pushes Y' (dates are timestamps, not "
    "narrators).\n"
    "- 'evidence': for EACH note in the pair, one item with its exact basename "
    "as 'note', its 'date' as given, and a SHORT VERBATIM fragment of that "
    "note's summary as 'quote'. The human decides TAK/NIE from these quotes "
    "alone, so pick the exact line that carries the link. Never paraphrase.\n"
    f"Return your answer ONLY through the {_TOOL_NAME} tool."
)


# Per-note text budget in the mining prompt. The first run sent full summaries
# (193k input tokens) — slow prefill, fragile stream, $1+ per attempt. ~700
# chars still carries the stance/entities a pair check needs, and quotes are
# verified later against fuller text anyway (confirm shows them; verdict/H3
# re-read the notes).
_PROPOSE_NOTE_CHARS = 700


def _corpus_prompt(corpus: List[NoteRef]) -> str:
    lines = ["NOTES (whole corpus, oldest to newest):"]
    for note in sorted(corpus, key=lambda n: n.date):
        tags = ", ".join(note.tags) if note.tags else "—"
        lines.append(f"\n[[{note.basename}]] | {note.date} | tags: {tags}")
        lines.append(note.summary_md.strip()[:_PROPOSE_NOTE_CHARS])
    return "\n".join(lines)


def _parse_proposals(payload: object) -> PlantedPairList:
    """Lenient parse mirroring synthesis._parse_payload."""
    if not isinstance(payload, dict):
        return PlantedPairList()
    try:
        return PlantedPairList.model_validate(payload)
    except ValidationError:
        good: List[PlantedPair] = []
        for raw in payload.get("pairs", []) or []:
            try:
                good.append(PlantedPair.model_validate(raw))
            except ValidationError:
                continue
        return PlantedPairList(pairs=good)


def filter_proposals(
    proposals: List[PlantedPair],
    corpus_basenames: Set[str],
    known_sigs: Set[str],
    dismissed_sigs: Set[str],
) -> tuple:
    """(kept, n_hallucinated, n_duplicate). Pure — unit-tested."""
    kept: List[PlantedPair] = []
    hallucinated = duplicates = 0
    seen: Set[str] = set()
    for p in proposals:
        if p.type not in _VALID_TYPES:
            p.type = "emergent-idea"
        missing = [b for b in p.notes if b not in corpus_basenames]
        if missing:
            hallucinated += 1
            print(f"  ! dropped (hallucinated note): {missing}")
            continue
        sig = connection_signature(p.notes, p.type)
        if sig in known_sigs or sig in dismissed_sigs or sig in seen:
            duplicates += 1
            continue
        seen.add(sig)
        kept.append(p)
    return kept, hallucinated, duplicates


def propose_pairs(
    corpus: List[NoteRef],
    api_key: str,
    known_sigs: Set[str],
    dismissed_sigs: Set[str],
    model: str = DEFAULT_MODEL,
) -> List[Dict[str, Any]]:
    """One Opus call over the whole corpus -> validated, deduped pair dicts."""
    import anthropic
    import httpx

    # Generous read timeout (long prefill on a big corpus sends no bytes for a
    # while). max_retries=1 so the SDK's connection-establishment retries don't
    # compound with our own outer stream-retry loop below.
    client = anthropic.Anthropic(
        api_key=api_key,
        timeout=httpx.Timeout(connect=30.0, read=900.0, write=60.0, pool=30.0),
        max_retries=1,
    )
    tool = {
        "name": _TOOL_NAME,
        "description": "Return the candidate planted pairs you mined.",
        "input_schema": PlantedPairList.model_json_schema(),
    }
    prompt = _corpus_prompt(corpus)
    print(f"mining pairs with {model} over {len(corpus)} notes ...")
    # 32k output headroom: 40+ pairs with verbatim quotes truncated at 16k
    # (a truncated forced-tool call yields unparseable JSON = 0 pairs, money
    # burned). Streaming keeps long generations alive; dots = progress.
    # Catch ANY transport failure, not just timeouts: a peer/proxy closing the
    # connection mid-stream surfaces as httpx.RemoteProtocolError (an HTTPError,
    # NOT a TimeoutException) and the SDK does not wrap errors raised while
    # iterating the SSE body — so a narrow except would let it escape and crash
    # propose after the input was already billed. Backoff between attempts, and
    # each attempt re-sends the full prompt, so cap at 3 to bound spend.
    import time

    retryable = (httpx.HTTPError, anthropic.APIError)
    message = None
    for attempt in range(1, 4):
        try:
            with client.messages.stream(
                model=model,
                max_tokens=32768,
                system=_PROPOSE_SYSTEM,
                tools=[tool],
                tool_choice={"type": "tool", "name": _TOOL_NAME},
                messages=[{"role": "user", "content": prompt}],
            ) as stream:
                n_events = 0
                for _event in stream:
                    n_events += 1
                    if n_events % 250 == 0:
                        print(".", end="", flush=True)
                message = stream.get_final_message()
            print()
            break
        except retryable as exc:
            print(f"\n  ! attempt {attempt}/3 failed mid-stream: {exc}")
            if attempt == 3:
                print("  giving up — check the network and re-run propose")
                return []
            time.sleep(2 * attempt)  # brief backoff before re-sending
    if message is None:
        return []
    usage = getattr(message, "usage", None)
    if usage:
        cost = estimate_cost_usd(model, usage.input_tokens, usage.output_tokens)
        print(
            f"  tokens: in={usage.input_tokens} out={usage.output_tokens} "
            f"(~${cost:.2f})"
        )
    truncated = getattr(message, "stop_reason", None) == "max_tokens"
    if truncated:
        print(
            "  ! response TRUNCATED at max_tokens — the tool JSON may be "
            "partial; salvaging what parses."
        )
    proposals = PlantedPairList()
    for block in message.content:
        if (
            getattr(block, "type", None) == "tool_use"
            and getattr(block, "name", None) == _TOOL_NAME
        ):
            proposals = _parse_proposals(block.input)
    if truncated and not proposals.pairs:
        print(
            "  ! nothing salvageable from the truncated call. Re-run propose; "
            "if it truncates again, lower the pair target in _PROPOSE_SYSTEM."
        )
    corpus_basenames = {n.basename for n in corpus}
    kept, halluc, dups = filter_proposals(
        proposals.pairs, corpus_basenames, known_sigs, dismissed_sigs
    )
    print(
        f"  proposed={len(proposals.pairs)} kept={len(kept)} "
        f"hallucinated={halluc} duplicate/dismissed={dups}"
    )
    return [
        {
            "notes": p.notes,
            "type": p.type,
            "why": p.why,
            "evidence": [e.model_dump() for e in p.evidence],
            "source": "llm-proposed",
            "confirmed": None,
            "sig": connection_signature(p.notes, p.type),
        }
        for p in kept
    ]


# --------------------------------------------------------------------------- #
# confirm / add / stats
# --------------------------------------------------------------------------- #
def _render_pair(pair: Dict[str, Any]) -> str:
    lines = [f"[{pair.get('type')}]  {'  +  '.join(pair.get('notes', []))}"]
    lines.append(f"  why: {pair.get('why', '')}")
    for ev in pair.get("evidence", []):
        lines.append(
            f"  [[{ev.get('note')}]] {ev.get('date', '')}: „{ev.get('quote')}\""
        )
    return "\n".join(lines)


def confirm_loop(path: Path, data: Dict[str, Any]) -> None:
    """t/n/s/q over unconfirmed pairs; saves after EVERY answer (crash-safe)."""
    pending = [p for p in data["pairs"] if p.get("confirmed") is None]
    if not pending:
        print("nothing to confirm — all pairs decided")
        return
    print(f"{len(pending)} pairs to confirm.  t=TAK  n=NIE  s=skip  q=quit\n")
    for i, pair in enumerate(pending, 1):
        print(f"--- {i}/{len(pending)} ({pair.get('id')}) ---")
        print(_render_pair(pair))
        while True:
            ans = input("TAK/nie/skip/quit [t/n/s/q]: ").strip().lower()
            if ans in ("t", "n", "s", "q"):
                break
        if ans == "q":
            print("stopped; progress saved")
            return
        if ans == "s":
            continue
        pair["confirmed"] = ans == "t"
        save_pairs(path, data)
    print("done; progress saved")


def normalize_basename(raw: str) -> str:
    """Accept whatever the user pastes and reduce it to a bare basename.

    Handles: a plain basename, a `[[wikilink]]`, a vault-relative or absolute
    path (with or without .md), and an `obsidian://open?...&file=...` deep link
    (URL-encoded, possibly with shell-escaped `\\?`/`\\&`).
    """
    from urllib.parse import unquote

    s = raw.strip().replace("\\", "")
    if s.startswith("obsidian://"):
        # take the file= param (last one wins), URL-decode it
        for part in s.split("&"):
            if part.startswith("file="):
                s = unquote(part[len("file=") :])
    s = s.strip().strip("[]").strip()
    if s.lower().endswith(".md"):
        s = s[: -len(".md")]
    # vault path -> last segment
    s = s.rsplit("/", 1)[-1]
    return s.strip()


def add_manual_pair(
    path: Path, data: Dict[str, Any], corpus_basenames: Set[str]
) -> None:
    """Interactive manual entry — the bias guard against the LLM bootstrap."""
    print(
        "Manual pair (bias guard). Paste a note name, [[wikilink]], path or "
        "obsidian:// link.\nNOTE: pairs must be TRANSCRIPT notes "
        "(11-Transcripts) — that is the prototype corpus."
    )
    notes: List[str] = []
    while True:
        raw = input(f"note {len(notes) + 1} (empty = done): ").strip()
        if not raw:
            break
        b = normalize_basename(raw)
        if b not in corpus_basenames:
            print(f"  ! '{b}' not in the transcript corpus")
            close = [c for c in corpus_basenames if b.lower() in c.lower()]
            for c in sorted(close)[:5]:
                print(f"    did you mean: {c}")
            continue
        print(f"  ok: {b}")
        notes.append(b)
    if len(notes) < 2:
        print("need at least 2 notes; aborted")
        return
    ptype = input(f"type {list(_VALID_TYPES)} [contradiction-over-time]: ").strip()
    if ptype not in _VALID_TYPES:
        ptype = "contradiction-over-time"
    why = input("why (one sentence): ").strip()
    sig = connection_signature(notes, ptype)
    if sig in existing_sigs(data):
        print("already in the fixture; skipped")
        return
    data["pairs"].append(
        {
            "id": _next_id(data),
            "notes": notes,
            "type": ptype,
            "why": why,
            "evidence": [],
            "source": "radek-manual",
            "confirmed": True,
            "sig": sig,
        }
    )
    save_pairs(path, data)
    print(f"added {data['pairs'][-1]['id']}")


def print_stats(data: Dict[str, Any]) -> None:
    pairs = data.get("pairs", [])
    by = lambda key: {  # noqa: E731
        v: sum(1 for p in pairs if p.get(key) == v)
        for v in sorted({p.get(key) for p in pairs}, key=str)
    }
    print(f"pairs: {len(pairs)}")
    print(f"  confirmed: {by('confirmed')}")
    print(f"  source:    {by('source')}")
    print(f"  type:      {by('type')}")


# --------------------------------------------------------------------------- #
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("propose", help="mine candidate pairs (1 Opus call)")
    p.add_argument("--model", default=DEFAULT_MODEL)
    sub.add_parser("confirm", help="interactive TAK/NIE loop")
    sub.add_parser("add", help="hand-add a pair the LLM did not propose")
    sub.add_parser("stats", help="fixture counts")
    args = ap.parse_args()

    vault = Path(config.TRANSCRIBE_DIR)
    path = pairs_path()
    data = load_pairs(path)

    if args.cmd == "stats":
        print_stats(data)
        return 0
    if args.cmd == "confirm":
        confirm_loop(path, data)
        print_stats(data)
        return 0

    corpus = load_corpus(vault)
    # TCC guard: from a sandboxed/unauthorised process the iCloud vault globs
    # as EMPTY (not an error). Mining "nothing" would waste a call and write a
    # useless fixture — refuse loudly instead (same lesson as the second-brain
    # index wipe). Run this from a terminal with Full Disk Access.
    if len(corpus) < 10:
        print(
            f"corpus suspiciously small ({len(corpus)} notes) at {vault}\n"
            "likely an iCloud/TCC-blocked process — run from YOUR terminal "
            "(Full Disk Access), not a sandboxed shell."
        )
        return 1
    if args.cmd == "add":
        add_manual_pair(path, data, {n.basename for n in corpus})
        return 0

    # propose
    api_key = os.environ.get("ANTHROPIC_API_KEY") or config.LLM_API_KEY
    if not api_key:
        print("no API key (settings or ANTHROPIC_API_KEY)")
        return 1
    dismissals = DismissalStore(vault).load()
    dismissed_sigs = set(
        dismissals._data.get("dismissed_signatures", {}).keys()  # noqa: SLF001
    )
    new_pairs = propose_pairs(
        corpus, api_key, existing_sigs(data), dismissed_sigs, model=args.model
    )
    if not new_pairs:
        print("no new pairs from this call — nothing saved (see messages above)")
        return 1
    for pair in new_pairs:
        pair["id"] = _next_id(data)
        data["pairs"].append(pair)
    save_pairs(path, data)
    print(f"saved -> {path}")
    print_stats(data)
    print("\nnext: ./venv312/bin/python scripts/bootstrap_planted_pairs.py confirm")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
