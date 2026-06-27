"""Append-only ``action_taken`` instrument for the Insights window (ADR-004).

Every move the user makes on a surfaced connection — handing its selected
directions to the connected LLM / a task / the calendar / the clipboard, or the
quiet Zachowaj / Odrzuć — is one event in ``{vault}/.malinche/signal.jsonl``.
The KPI is **action-rate**: the share of surfaced connections that produce at
least one non-``none`` action. Storing an insight was never proof of value; only
*doing something because of it* is — so this records the doing.

Design:

* **Pure + AppKit-free + side-effect-isolated** — the recorder lives here, not in
  the pure ``InsightDeck`` and not buried in the AppKit controller. The controller
  just calls :func:`record_action`.
* **Best-effort for the UI, loud in the log** — a write failure never reaches the
  click handler, but it is *logged* (``logger.warning``), so a broken vault path
  surfaces in ``make logs`` instead of silently voiding weeks of data.
* **Shared ``.malinche`` dir** — the path is derived from the same place
  ``insight_pipeline`` resolves its sidecar, so the two can never drift apart.
* **Canonical signature** — every event carries the one
  :func:`~src.connections.signature.connection_signature` so it joins back to the
  connection it measures.

(The legacy ``v1`` kept/dismissed recorder was retired with the action-engine
redesign; old ``v1`` lines in an existing log stay readable — they just have a
different shape, which the ``jq`` analysis tolerates.)
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Iterable, List, Optional

from src.connections.signature import connection_signature
from src.logger import logger

#: Schema version for the action_taken record shape.
ACTION_SCHEMA_VERSION = 2

# action_taken targets (where the insight was handed off) and the kind of move
# each implies. "none" = dismissed; "save" = the quiet Zachowaj archive.
TARGET_LLM = "llm"
TARGET_TASK = "task"
TARGET_CALENDAR = "calendar"
TARGET_CLIPBOARD = "clipboard"
TARGET_SAVE = "save"
TARGET_NONE = "none"

#: target → kind (develop | do | decide | none). The instrument's core axis.
_KIND_FOR_TARGET = {
    TARGET_LLM: "develop",
    TARGET_CLIPBOARD: "develop",
    TARGET_TASK: "do",
    TARGET_CALENDAR: "decide",
    TARGET_SAVE: "none",
    TARGET_NONE: "none",
}


def kind_for_target(target: str) -> str:
    """The move-kind a handoff target implies (develop/do/decide/none)."""
    return _KIND_FOR_TARGET.get(target, "none")


def signal_log_path() -> Optional[Path]:
    """Path to ``signal.jsonl``, or ``None`` if config is unavailable.

    Derived from the insights sidecar's directory so the validation log and the
    digest sidecar always share the one ``.malinche`` folder.
    """
    try:
        from src.ui.insight_pipeline import latest_insights_file

        sidecar = latest_insights_file()
        if sidecar is None:
            return None
        return Path(sidecar).parent / "signal.jsonl"
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("could not resolve signal log path: %s", exc)
        return None


def record_action(
    target: str,
    *,
    sig: str = "",
    conn_type: str = "",
    notes: Optional[Iterable[str]] = None,
    directions: Optional[Iterable[int]] = None,
    tool: str = "",
    kind: str = "",
    label: str = "",
    path: Optional[Path] = None,
    now: Optional[datetime] = None,
) -> bool:
    """Append one ``action_taken`` event to the signal log (schema v2).

    ``target`` is one of the ``TARGET_*`` constants; ``kind`` is derived from it
    unless given. ``sig`` is the canonical connection signature (carried from the
    deck so it never drifts); if absent it is recomputed from ``notes`` +
    ``conn_type`` — but ``conn_type`` must be the *raw synthesis type*, never the
    UI display constant, or the recomputed sig won't match the digest's.
    ``directions`` are the indices of the selected directions the handoff acted
    on (selection is multi). Never raises — failures are logged and swallowed.
    """
    try:
        out = Path(path) if path is not None else signal_log_path()
        if out is None:
            logger.warning("action signal dropped: no log path (config?)")
            return False

        if not sig and notes:
            sig = connection_signature(notes, conn_type)

        dir_list: List[int] = [int(i) for i in (directions or [])]
        stamp = (now or datetime.now()).isoformat(timespec="seconds")
        record = {
            "v": ACTION_SCHEMA_VERSION,
            "ts": stamp,
            "action": "action_taken",
            "kind": kind or kind_for_target(target),
            "target": str(target),
            "conn_type": str(conn_type),
            "sig": sig,
            "directions": dir_list,
            "n_dir": len(dir_list),
            "tool": str(tool or ""),
            "label": str(label or ""),
        }

        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        return True
    except Exception as exc:
        logger.warning("could not record action signal: %s", exc)
        return False
