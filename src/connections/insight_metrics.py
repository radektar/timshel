"""Per-digest cost + coverage instrument for the magic-insights prototype.

Every digest run appends one record to ``{vault}/.timshel/metrics.jsonl``:
which model ran, tokens in/out (incl. cache read/creation), the derived USD
cost, how many candidates were assembled, and how many genuine connections
came back. This is the evidence base for the prototype's kill-tests — H1
(quality, connections/run), H4 (cost, USD/digest) — and nothing here is
proof of value on its own; it is the raw ledger those metrics are computed
from.

Design mirrors :mod:`src.connections.validation_signal`:

* **Best-effort for the pipeline, loud in the log** — a write failure never
  reaches the daemon tick, but it *is* logged, so a broken vault path shows up
  in ``make logs`` instead of silently voiding the prototype's data.
* **Shared ``.timshel`` dir** — same directory the insights sidecar and the
  action signal resolve to, so the three instruments never drift apart.
* **Pure + side-effect-isolated** — the cost model is a pure function; the only
  side effect is the append, isolated to :func:`record_digest_metrics`.

Prices are per **million tokens**, standard tier, verified 2026-07-05 against
platform.claude.com/docs. Batch (-50%) and prompt caching (cache-read ~0.1x
input, 5-min cache-write ~1.25x input) are modelled explicitly so a cascade
experiment can read true cost, not list price. The US-only inference option
(1.1x) is NOT applied here — apply it downstream if the chosen zero-retention
provider forces a US region.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from src.config.config import config
from src.logger import logger

#: Schema version for the digest metrics record shape.
#: v2 adds the verdict pass: verdict_* fields, synthesis_cost_usd, and
#: cost_usd becomes the TOTAL (synthesis + verdict). v1 rows stay parseable.
METRICS_SCHEMA_VERSION = 2

#: Per-million-token (input, output) USD list price, standard tier.
#: Verified 2026-07-05; unknown models fall back to Opus (the safe over-estimate
#: for a budget guard — better to over-report cost than under-report it).
_PRICES_PER_MTOK: Dict[str, Tuple[float, float]] = {
    "claude-opus-4-8": (5.0, 25.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-haiku-4-5-20251001": (1.0, 5.0),
}
_FALLBACK_MODEL = "claude-opus-4-8"

#: Cache multipliers relative to the input price.
_CACHE_READ_MULT = 0.1
_CACHE_WRITE_MULT = 1.25


def _prices_for(model: str) -> Tuple[float, float]:
    """(input, output) per-MTok price for ``model``, Opus fallback if unknown."""
    if model not in _PRICES_PER_MTOK:
        logger.warning(
            "insight_metrics: unknown model %r — pricing as %s (over-estimate)",
            model,
            _FALLBACK_MODEL,
        )
    return _PRICES_PER_MTOK.get(model, _PRICES_PER_MTOK[_FALLBACK_MODEL])


def estimate_cost_usd(
    model: str,
    input_tokens: int,
    output_tokens: int,
    *,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
    batch: bool = False,
) -> float:
    """Pure cost model in USD for one call.

    ``input_tokens`` is the count billed at full input price (the Anthropic
    ``usage.input_tokens`` already excludes cache reads/writes). Cache reads and
    5-min cache writes are billed off the input price via the multipliers above.
    ``batch`` halves the whole call (Batch API, -50%).
    """
    in_price, out_price = _prices_for(model)
    cost = (
        input_tokens * in_price
        + output_tokens * out_price
        + cache_read_tokens * in_price * _CACHE_READ_MULT
        + cache_write_tokens * in_price * _CACHE_WRITE_MULT
    ) / 1_000_000
    if batch:
        cost *= 0.5
    return round(cost, 6)


def usage_tokens(usage: object) -> Dict[str, int]:
    """Extract token counts from an Anthropic ``usage`` object, defensively.

    Returns zeros for any field the SDK didn't populate (older responses omit
    the cache fields). ``usage`` may be ``None`` when no call was made.
    """

    def _get(name: str) -> int:
        try:
            return int(getattr(usage, name, 0) or 0)
        except (TypeError, ValueError):
            return 0

    return {
        "input_tokens": _get("input_tokens"),
        "output_tokens": _get("output_tokens"),
        "cache_read_tokens": _get("cache_read_input_tokens"),
        "cache_write_tokens": _get("cache_creation_input_tokens"),
    }


def metrics_log_path() -> Optional[Path]:
    """``{vault}/.timshel/metrics.jsonl`` — the append target, or None."""
    base = getattr(config, "TRANSCRIBE_DIR", None)
    if not base:
        return None
    return Path(base) / str(config.SIDECAR_DIR_NAME) / "metrics.jsonl"


def build_record(
    *,
    model: str,
    usage: object,
    candidates: int,
    connections: int,
    connection_types: Optional[List[str]] = None,
    digest: str = "",
    batch: bool = False,
    tester_mode: bool = False,
    verdict_model: str = "",
    verdict_usage: object = None,
    verdict_dropped: int = 0,
    now: Optional[datetime] = None,
) -> Dict[str, object]:
    """Assemble one metrics record (pure — no I/O).

    ``cost_usd`` is the run TOTAL; ``synthesis_cost_usd`` preserves the v1
    meaning. Verdict fields are zero/empty when the pass did not run.
    """
    tokens = usage_tokens(usage)
    synthesis_cost = estimate_cost_usd(
        model,
        tokens["input_tokens"],
        tokens["output_tokens"],
        cache_read_tokens=tokens["cache_read_tokens"],
        cache_write_tokens=tokens["cache_write_tokens"],
        batch=batch,
    )
    v_tokens = usage_tokens(verdict_usage)
    verdict_cost = (
        estimate_cost_usd(
            verdict_model,
            v_tokens["input_tokens"],
            v_tokens["output_tokens"],
            cache_read_tokens=v_tokens["cache_read_tokens"],
            cache_write_tokens=v_tokens["cache_write_tokens"],
            batch=batch,
        )
        if verdict_model
        else 0.0
    )
    stamp = (now or datetime.now()).isoformat(timespec="seconds")
    return {
        "v": METRICS_SCHEMA_VERSION,
        "ts": stamp,
        "digest": digest,
        "model": model,
        "batch": bool(batch),
        "tester_mode": bool(tester_mode),
        "candidates": int(candidates),
        "connections": int(connections),
        "connection_types": list(connection_types or []),
        "synthesis_cost_usd": synthesis_cost,
        "verdict_model": verdict_model,
        "verdict_input_tokens": v_tokens["input_tokens"],
        "verdict_output_tokens": v_tokens["output_tokens"],
        "verdict_cost_usd": verdict_cost,
        "verdict_dropped": int(verdict_dropped),
        "cost_usd": round(synthesis_cost + verdict_cost, 6),
        **tokens,
    }


def record_digest_metrics(
    *,
    model: str,
    usage: object,
    candidates: int,
    connections: int,
    connection_types: Optional[List[str]] = None,
    digest: str = "",
    batch: bool = False,
    tester_mode: bool = False,
    verdict_model: str = "",
    verdict_usage: object = None,
    verdict_dropped: int = 0,
    path: Optional[Path] = None,
    now: Optional[datetime] = None,
) -> bool:
    """Append one digest metrics record to ``metrics.jsonl``. Never raises.

    Gated by ``config.INSIGHT_METRICS_ENABLED``. Returns True on a successful
    append, False if disabled, misconfigured, or the write failed (all logged).
    """
    if not getattr(config, "INSIGHT_METRICS_ENABLED", True):
        return False
    try:
        out = Path(path) if path is not None else metrics_log_path()
        if out is None:
            logger.warning("digest metrics dropped: no log path (config?)")
            return False
        record = build_record(
            model=model,
            usage=usage,
            candidates=candidates,
            connections=connections,
            connection_types=connection_types,
            digest=digest,
            batch=batch,
            tester_mode=tester_mode,
            verdict_model=verdict_model,
            verdict_usage=verdict_usage,
            verdict_dropped=verdict_dropped,
            now=now,
        )
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        logger.info(
            "digest metrics: model=%s cost=$%.4f candidates=%d connections=%d",
            model,
            record["cost_usd"],
            candidates,
            connections,
        )
        return True
    except Exception as exc:  # noqa: BLE001 - instrument must never break the tick
        logger.warning("could not record digest metrics: %s", exc)
        return False


def record_gate_skip(
    *,
    window: int,
    neighbors: int,
    candidates: int,
    path: Optional[Path] = None,
    now: Optional[datetime] = None,
) -> bool:
    """Append a $0 record for a run the local gate skipped. Never raises.

    The false-negative instrument for the pre-API gate: each row says how much
    material the gate judged insufficient, so a threshold that is cutting real
    digests shows up in the ledger instead of disappearing silently. Rows carry
    ``kind: "gate-skip"`` — digest rows have no ``kind`` field, so existing
    readers (which use ``.get``) are unaffected.
    """
    if not getattr(config, "INSIGHT_METRICS_ENABLED", True):
        return False
    try:
        out = Path(path) if path is not None else metrics_log_path()
        if out is None:
            logger.warning("gate-skip metrics dropped: no log path (config?)")
            return False
        record = {
            "v": METRICS_SCHEMA_VERSION,
            "ts": (now or datetime.now()).isoformat(timespec="seconds"),
            "kind": "gate-skip",
            "window": int(window),
            "neighbors": int(neighbors),
            "candidates": int(candidates),
            "cost_usd": 0.0,
        }
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        return True
    except Exception as exc:  # noqa: BLE001 - instrument must never break the tick
        logger.warning("could not record gate-skip metrics: %s", exc)
        return False
