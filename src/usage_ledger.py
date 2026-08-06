"""Monthly usage ledger: AI hours consumed and deep scans run.

What this is for
----------------
The paid tier is sold in **hours of recording that got an AI summary** (local
transcription stays free and unlimited, and the weekly digest is a flat cost
that does not touch this counter). To say "12h 40m of 30h" honestly, something
has to add up note durations across a calendar month — nothing in the app did.
The same file also counts manual "deep scans", which are the one paid action a
user can trigger at will.

Deliberately soft
-----------------
Nothing here blocks anything. Going over the budget is a *calibration signal*
for the 30h tier, not an incident; the hard ceiling during the beta is the
per-tester Anthropic workspace cap. Enforcement moves server-side when the
subscription proxy exists.

Concurrency
-----------
The daemon is a THREAD inside the menu app, not a separate process, so the two
writers (a note finalizing, a deep scan being counted) share a PID: a
per-process temp file would not keep them apart. Read→modify→write is therefore
serialized by a module-level lock and published with an atomic ``os.replace``
from a uniquely-named temp file, which is unlinked even when the write fails.
A separate process (the ``magic_digest`` CLI) can still lose one increment by
racing the app — accepted on purpose: counters, unlike the scheduler's
seen-set, cannot be merged idempotently without an oplog, and a soft budget
does not justify one. What must never happen is a corrupt file, because that
loses the WHOLE month. Every function swallows its own errors: a broken ledger
must never stop a note from being written.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from src.config import config
from src.logger import logger

LEDGER_SCHEMA = 1

# Serializes read→modify→write within this process. The daemon runs as a thread
# beside the menu app, so both writers are in here.
_LOCK = threading.Lock()


@dataclass
class MonthlyUsage:
    """Usage within one calendar month (``month`` is ``YYYY-MM``)."""

    month: str
    ai_seconds: int = 0
    deep_scans: int = 0
    notified_80: bool = False

    @property
    def ai_hours(self) -> float:
        return self.ai_seconds / 3600.0

    def budget_fraction(self, budget_hours: Optional[int] = None) -> float:
        """Share of the monthly hour budget used (0.0 when no budget set)."""
        hours = (
            budget_hours
            if budget_hours is not None
            else int(getattr(config, "AI_HOURS_BUDGET", 0) or 0)
        )
        if hours <= 0:
            return 0.0
        return self.ai_hours / float(hours)


def ledger_path() -> Optional[Path]:
    """App-support ``usage_ledger.json``, or None when config has no path."""
    path = getattr(config, "USAGE_LEDGER_FILE", None)
    return Path(path) if path else None


def current_month(now: Optional[datetime] = None) -> str:
    return (now or datetime.now()).strftime("%Y-%m")


def _empty(now: Optional[datetime] = None) -> MonthlyUsage:
    return MonthlyUsage(month=current_month(now))


def read_usage(now: Optional[datetime] = None) -> MonthlyUsage:
    """Read the ledger, resetting lazily when the calendar month rolled over.

    The reset is on READ, not on a timer: no process is guaranteed to be alive
    at midnight on the 1st, so a scheduled reset would simply not fire.
    """
    month = current_month(now)
    path = ledger_path()
    if path is None:
        return _empty(now)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return _empty(now)
    except (OSError, ValueError) as exc:
        # A corrupt ledger costs at most one month of counting; refusing to
        # transcribe over it would cost the note.
        logger.warning("usage ledger unreadable (%s) — starting a fresh month", exc)
        return _empty(now)
    if not isinstance(raw, dict) or raw.get("month") != month:
        return _empty(now)
    try:
        return MonthlyUsage(
            month=month,
            ai_seconds=int(raw.get("ai_seconds", 0) or 0),
            deep_scans=int(raw.get("deep_scans", 0) or 0),
            notified_80=bool(raw.get("notified_80", False)),
        )
    except (TypeError, ValueError):
        logger.warning("usage ledger has bad field types — starting a fresh month")
        return _empty(now)


def _write(usage: MonthlyUsage) -> None:
    path = ledger_path()
    if path is None:
        return
    payload = {
        "v": LEDGER_SCHEMA,
        "month": usage.month,
        "ai_seconds": int(usage.ai_seconds),
        "deep_scans": int(usage.deep_scans),
        "notified_80": bool(usage.notified_80),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    # A unique temp file per write, removed even on failure: a shared name lets
    # two writers interleave into one file and os.replace then publishes
    # mangled JSON — which costs the whole month, not one increment.
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def add_ai_seconds(
    seconds: Optional[int], now: Optional[datetime] = None
) -> MonthlyUsage:
    """Add recording seconds that were summarized by the AI. Never raises.

    ``None`` (text imports have no audio) and non-positive values are ignored
    so a note without a duration cannot corrupt the counter.
    """
    if seconds is None:
        return read_usage(now)
    try:
        delta = int(seconds)
    except (TypeError, ValueError):
        return read_usage(now)
    if delta <= 0:
        return read_usage(now)
    with _LOCK:
        usage = read_usage(now)
        usage.ai_seconds += delta
        try:
            _write(usage)
        except OSError as exc:
            logger.warning("usage ledger write failed: %s", exc)
        return usage


def increment_deep_scan(now: Optional[datetime] = None) -> MonthlyUsage:
    """Count one manual deep scan. Never raises."""
    with _LOCK:
        usage = read_usage(now)
        usage.deep_scans += 1
        try:
            _write(usage)
        except OSError as exc:
            logger.warning("usage ledger write failed: %s", exc)
        return usage


def mark_notified_80(now: Optional[datetime] = None) -> MonthlyUsage:
    """Latch the 80%-of-budget notice so it fires once per month. Never raises."""
    with _LOCK:
        usage = read_usage(now)
        if usage.notified_80:
            return usage
        usage.notified_80 = True
        try:
            _write(usage)
        except OSError as exc:
            logger.warning("usage ledger write failed: %s", exc)
        return usage


def format_hours(seconds: int) -> str:
    """``4520`` → ``"1h 15m"``; under a minute reads ``"0m"``."""
    try:
        total = max(0, int(seconds))
    except (TypeError, ValueError):
        total = 0
    hours, remainder = divmod(total, 3600)
    minutes = remainder // 60
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"
