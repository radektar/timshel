# H1 Test Protocol (operator)

The hypothesis: **the Insights layer surfaces connections worth acting on.**
This is the operator half — how the small group runs and how to read the
results. Tester-facing steps live in `TESTER-ONBOARDING.md`.

## Panel

- 3–5 testers, Apple Silicon, macOS 12+.
- Hand-picked for a **dense, first-person vault** — the real lever for whether
  insights fire (a cold vault produces nothing regardless of the engine).
- Day 1: install + wizard + paste a per-tester Claude key + seed ≥30 notes via
  **Import transcripts…**.

## Cadence

Normal daily use for **2–3 weeks**. The scheduler fires a digest every 7 days,
pulled forward to a 2-day floor once ≥6 new notes accumulate. The weekly ritual
(below) guarantees ≥1 rated digest per tester per week regardless.

## Weekly ritual (per tester, ~10 min)

1. If no digest this week → **Generate digest now**.
2. **Insights** → rate every connection: Zachowaj / Odrzuć / handoff.
3. **Export feedback** → email the Desktop zip back.

Minimum three cycles per tester.

## Reading the results (per tester per week)

Unzip the feedback bundle, then:

```
./venv312/bin/python -m src.connections.signal_report --json <unzipped>/sidecar/signal.jsonl
```

- `signal.jsonl` → keep / dismiss / handoff rates (the action instrument).
- `metrics.jsonl` → cost + coverage per digest (watch Opus spend).
- Read the kept connections against the digest `.md` to judge quality.

Plus a 3-question reply email:
1. Which kept connection was **non-obvious** to you?
2. Did you **actually do** anything because of one?
3. What was the most annoying **noise**?

## GO / kill (per STATE.md)

- **GO:** ≥3 action-worthy connections *of any type* per tester-week, including
  ≥1 self-reported non-obvious.
- **Kill:** imports produce noise instead of action-worthy connections → import
  stays a FREE onboarding feature, not a PRO feeder.

Track per-tester weekly in a simple sheet; decide after week 3.

## Operator setup notes

- **Anthropic console:** one named key per tester in a "Timshel testers"
  workspace, each with a spend limit (Opus synthesis+verdict per digest is the
  cost driver — set the limit before handing keys out).
- **Build:** `make release-tester` → `dist/Timshel-<ver>-ARM64-UNSIGNED.dmg`
  (+ sha256). The tester DMG bakes `TimshelTesterBuild` so instrumentation is on
  from first launch (no manual config).
- **Verify before sending:** run the full checklist in `TESTER-BUILD-VERIFY.md`
  on a clean environment (Gatekeeper, wizard, FDA, import, digest, export).
