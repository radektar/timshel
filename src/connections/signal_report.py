"""Read-side readout for the ``action_taken`` signal log (ADR-004).

:mod:`validation_signal` is the write path — one event per move the user makes
on a surfaced connection. This is the read path: it computes the KPI the whole
action-engine bet rides on — **action-rate** — over those events.

KPI definition (and its honest denominator):

* An **engaged connection** is any connection (unique canonical ``sig``) the user
  *triaged* — it has at least one event in the log. Connections that were merely
  displayed and never touched leave no trace, so they are **not** in the
  denominator; this measures conversion *given engagement*, not given exposure.
* A connection is **actioned** if it produced at least one non-``none`` move —
  ``kind`` in :data:`ACTIONED_KINDS` (develop / do / decide). The quiet
  ``Zachowaj`` (save) and ``Odrzuć`` (none) are engagement without action.
* ``action_rate = actioned / engaged``.

Everything here is pure over a list of event dicts, except the thin
:func:`load_events` loader and the ``__main__`` CLI (``make signal-report``). The
loader tolerates blank lines, malformed JSON, and legacy ``v1`` records — only
schema-v2 ``action_taken`` events feed the metrics; the rest are counted as
``skipped`` so a polluted log is visible, not silently miscounted.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

#: ``kind`` values that count as a real action (a non-``none`` move).
ACTIONED_KINDS = {"develop", "do", "decide"}


def load_events(path: Path) -> Tuple[List[dict], int]:
    """Read newline-delimited JSON, returning ``(events, skipped)``.

    ``events`` are the well-formed schema-v2 ``action_taken`` records; ``skipped``
    counts every other non-blank line (legacy v1, malformed JSON, other shapes).
    Never raises on a missing file — that is just ``([], 0)``.
    """
    events: List[dict] = []
    skipped = 0
    if not path.exists():
        return events, skipped
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except (ValueError, TypeError):
            skipped += 1
            continue
        if (
            isinstance(rec, dict)
            and rec.get("action") == "action_taken"
            and rec.get("v") == 2
        ):
            events.append(rec)
        else:
            skipped += 1
    return events, skipped


@dataclass
class Summary:
    """The computed action-rate readout over a window of events."""

    events: int = 0
    engaged: int = 0  # unique connections (non-empty sig) with >=1 event
    actioned: int = 0  # of those, ones with >=1 non-none move
    by_kind: Dict[str, int] = field(default_factory=dict)  # event counts
    by_target: Dict[str, int] = field(default_factory=dict)  # event counts
    by_tool: Dict[str, int] = field(default_factory=dict)  # handoff tool counts
    # conn_type -> (actioned_connections, engaged_connections)
    by_conn_type: Dict[str, Tuple[int, int]] = field(default_factory=dict)
    missing_sig: int = 0  # events we cannot join to a connection
    first_ts: Optional[str] = None
    last_ts: Optional[str] = None

    @property
    def action_rate(self) -> float:
        """Share of engaged connections that produced at least one action."""
        return self.actioned / self.engaged if self.engaged else 0.0


def summarize(events: List[dict]) -> Summary:
    """Fold a list of ``action_taken`` events into a :class:`Summary`.

    Connection-level metrics (engaged / actioned / per-type) are computed over
    unique non-empty ``sig`` values; events with an empty ``sig`` cannot be
    joined to a connection, so they are tallied in ``missing_sig`` and excluded
    from the rate (they still count in the event-level breakdowns).
    """
    s = Summary(events=len(events))
    if not events:
        return s

    # per-sig: did this connection ever get a real action, and its raw type
    actioned_by_sig: Dict[str, bool] = {}
    type_by_sig: Dict[str, str] = {}

    for rec in events:
        kind = str(rec.get("kind") or "none")
        target = str(rec.get("target") or "")
        tool = str(rec.get("tool") or "")
        sig = str(rec.get("sig") or "")
        ctype = str(rec.get("conn_type") or "")
        ts = rec.get("ts")

        s.by_kind[kind] = s.by_kind.get(kind, 0) + 1
        if target:
            s.by_target[target] = s.by_target.get(target, 0) + 1
        if tool and kind in ACTIONED_KINDS:
            s.by_tool[tool] = s.by_tool.get(tool, 0) + 1

        if isinstance(ts, str) and ts:
            if s.first_ts is None or ts < s.first_ts:
                s.first_ts = ts
            if s.last_ts is None or ts > s.last_ts:
                s.last_ts = ts

        if not sig:
            s.missing_sig += 1
            continue

        is_action = kind in ACTIONED_KINDS
        actioned_by_sig[sig] = actioned_by_sig.get(sig, False) or is_action
        # first non-empty type wins as the connection's label
        if sig not in type_by_sig and ctype:
            type_by_sig[sig] = ctype

    s.engaged = len(actioned_by_sig)
    s.actioned = sum(1 for v in actioned_by_sig.values() if v)

    per_type: Dict[str, List[int]] = {}
    for sig, did in actioned_by_sig.items():
        ctype = type_by_sig.get(sig, "?")
        bucket = per_type.setdefault(ctype, [0, 0])
        bucket[1] += 1
        if did:
            bucket[0] += 1
    s.by_conn_type = {k: (v[0], v[1]) for k, v in per_type.items()}

    return s


def _bar(rate: float, width: int = 20) -> str:
    filled = int(round(rate * width))
    return "█" * filled + "·" * (width - filled)


def render(summary: Summary) -> str:
    """A scannable, terminal-friendly readout of the summary."""
    s = summary
    lines: List[str] = []
    lines.append("Timshel — action-rate readout (ADR-004)")
    lines.append("=" * 44)

    if s.events == 0:
        lines.append("")
        lines.append("Brak danych jeszcze — żaden insight nie był triażowany.")
        lines.append("(Otwórz Insights, zrób handoff/Zachowaj/Odrzuć — wróci tu sygnał.)")
        return "\n".join(lines)

    span = ""
    if s.first_ts and s.last_ts:
        span = f"  ·  {s.first_ts[:10]} → {s.last_ts[:10]}"
    lines.append(f"events: {s.events}{span}")
    lines.append("")

    rate = s.action_rate
    lines.append(f"ACTION-RATE   {rate:5.0%}  {_bar(rate)}")
    lines.append(f"  engaged connections : {s.engaged}")
    lines.append(f"  → actioned          : {s.actioned}  (≥1 develop/do/decide)")
    lines.append(f"  → no action         : {s.engaged - s.actioned}  (tylko save/none)")

    if s.by_kind:
        lines.append("")
        lines.append("by kind (events):")
        for k in ("develop", "do", "decide", "none"):
            if k in s.by_kind:
                lines.append(f"  {k:<8} {s.by_kind[k]}")

    if s.by_target:
        lines.append("")
        lines.append("by target (events):")
        for t, n in sorted(s.by_target.items(), key=lambda kv: -kv[1]):
            lines.append(f"  {t:<10} {n}")

    if s.by_tool:
        lines.append("")
        lines.append("by LLM tool (actions):")
        for t, n in sorted(s.by_tool.items(), key=lambda kv: -kv[1]):
            lines.append(f"  {t:<10} {n}")

    if s.by_conn_type:
        lines.append("")
        lines.append("action-rate by connection type:")
        for ct, (act, eng) in sorted(s.by_conn_type.items(), key=lambda kv: -kv[1][1]):
            r = act / eng if eng else 0.0
            lines.append(f"  {ct:<26} {act}/{eng}  {r:4.0%}")

    if s.missing_sig:
        lines.append("")
        lines.append(f"⚠ {s.missing_sig} event(s) bez sig — nie wliczone do rate (data quality).")

    # one-line read for the N=1 gate
    lines.append("")
    if s.actioned > 0:
        lines.append(f"→ {s.actioned}/{s.engaged} insightów zrodziło akcję. Brama żyje — patrz na trend.")
    else:
        lines.append("→ 🔴 zero handoffów mimo zaangażowania — kill-signal: wróć do jakości tezy/syntezy.")

    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entry: read the log (or a path passed as the first arg) and print."""
    import argparse

    parser = argparse.ArgumentParser(
        prog="signal-report",
        description="Compute action-rate over the Insights signal log (ADR-004).",
    )
    parser.add_argument(
        "path",
        nargs="?",
        help="path to signal.jsonl (default: the vault's .timshel/signal.jsonl)",
    )
    parser.add_argument(
        "--json", action="store_true", help="emit the raw summary as JSON"
    )
    args = parser.parse_args(argv)

    if args.path:
        log_path: Optional[Path] = Path(args.path)
    else:
        from src.connections.validation_signal import signal_log_path

        log_path = signal_log_path()

    if log_path is None:
        print("Brak ścieżki do logu (config niedostępny). Podaj ją argumentem.")
        return 1

    events, skipped = load_events(log_path)
    summary = summarize(events)

    if args.json:
        payload = {
            "events": summary.events,
            "engaged": summary.engaged,
            "actioned": summary.actioned,
            "action_rate": summary.action_rate,
            "by_kind": summary.by_kind,
            "by_target": summary.by_target,
            "by_tool": summary.by_tool,
            "by_conn_type": {k: list(v) for k, v in summary.by_conn_type.items()},
            "missing_sig": summary.missing_sig,
            "skipped_lines": skipped,
            "first_ts": summary.first_ts,
            "last_ts": summary.last_ts,
            "path": str(log_path),
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    print(render(summary))
    print(f"\nźródło: {log_path}")
    if skipped:
        print(f"(pominięto {skipped} linii: legacy v1 / malformed)")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
