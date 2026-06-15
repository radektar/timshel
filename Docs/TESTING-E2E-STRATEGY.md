# ADR-001: Scenario / end-to-end testing strategy

**Status:** Proposed
**Date:** 2026-06-15
**Deciders:** Radek (owner)

> Companion executable artifacts: `tests/fixtures/audio_factory.py` (sample
> corpus generator) and `tests/test_audio_factory.py` (its self-test). The
> markers and Make targets named here are the contract the rest of the test
> layers build on.

## Context

The Malinche pipeline is a chain of process boundaries:

```
recorder → ffmpeg → whisper.cpp → transcript → Claude (summary/tags/title) → Markdown in vault
```

Every one of those boundaries is **mocked** in the current suite (380 unit
tests). That is appropriate for unit tests, but it means we have *zero*
coverage of the thing the product actually does: turn real audio into a real
Markdown note. The consequence is a recurring class of regression that ships
through a green build because the failure lives on a boundary a unit test never
exercises:

- **alpha.15** — a retired Claude model returned HTTP 404 on every file.
- **alpha.16** — an unreadable audio file caused an infinite retry loop.
- **alpha.18** — an AI-generated title containing `{}` broke `str.format()`.
- **beta.7** — subprocess encoding mangled Polish characters.

All four are boundary defects. Before v2.0.0 GA we need a layer that actually
pushes audio through whisper and a transcript through Claude.

### Current state (baseline)

- 47 test files, all unit-level.
- **No audio fixtures exist** in the repo.
- `test_summarizer.py` mocks `src.summarizer.Anthropic` — Claude is never
  really called; we test response parsing, not summary quality or the live API
  contract.
- `test_transcriber.py` mocks `_run_whisper_transcription` / `subprocess` —
  whisper never really runs.
- 7 formats declared (`mp3, wav, m4a, wma, flac, aac, ogg`); none tested with a
  real file.
- `tests/integration/` holds shell + interactive `print()` scripts (download,
  staging, corrupted-file) — not pytest, not audio, not in CI.
- No UI tests for the menu bar (rumps / PyObjC).

## Decision

Adopt a **4-layer test pyramid** with explicit pytest markers and separate CI
gates, plus a **versioned audio sample corpus** generated deterministically
(recipes + cache, not large binaries committed to git).

```
         ┌────────────────────────────────────────────┐
   L4    │  UI smoke (menu bar, headless + manual)     │  rarely, release + nightly
         ├────────────────────────────────────────────┤
   L3    │  E2E real (whisper + Claude live)           │  @e2e, nightly + pre-release
         ├────────────────────────────────────────────┤
   L2    │  Pipeline (real whisper, mock Claude)       │  @integration, every PR (mac)
         ├────────────────────────────────────────────┤
   L1    │  Unit (current ~380) — boundaries mocked    │  every commit, <30s
         └────────────────────────────────────────────┘
```

## Options considered

### A — where multilingual audio comes from

| Option | Determinism | Cost | Realism | License |
|---|---|---|---|---|
| **A1. TTS-generated (`say` + ffmpeg)** | high | zero | medium (clean speech) | clean |
| A2. Public-domain corpus (Common Voice, LibriVox) | high | download | high | CC0 / CC-BY |
| A3. Self-recorded on a real device | low | high | highest | own |

**Decision: A1 as the base + A2 as a "realism pack".** macOS `say -v` produces
PL/EN/ES/DE/FR voices for free and deterministically (known text → known
expected transcript → measurable WER). Common Voice adds accented / noisy
samples to nightly. Self-recordings do not scale and cannot be versioned.

### B — verifying summaries with a real Claude key

| Option | What it checks | Stability | API cost |
|---|---|---|---|
| B1. Structural assertions (fields present, length, language, no `{}`) | contract, not quality | high | low |
| **B2. B1 + LLM-as-judge (a second Claude scores relevance 1–5)** | semantic quality | medium (threshold) | medium |
| B3. Golden file (exact string) | nothing useful | zero (LLM is non-deterministic) | low |

**Decision: B1 mandatory on every E2E + B2 as a quality gate in nightly.**
Exact-golden (B3) is out — the model is non-deterministic. The judge scores
against a threshold (`score ≥ 4`), not equality. The key comes from the
environment (`ANTHROPIC_API_KEY`); the test **skips** when the key is missing —
never a hard fail on a machine without the secret.

### C — audio format matrix

A parametrized test that renders **the same speech in each of the 7 formats**
(ffmpeg transcodes from a master WAV) plus edge cases:

```
formats:   wav, mp3, m4a, wma, flac, aac, ogg     (full AUDIO_EXTENSIONS)
edge:      0-byte file, corrupted header, 2h length (timeout),
           sample-rate ≠ 16kHz (whisper needs resample), stereo vs mono,
           silence, filename with Polish chars and {braces}
```

This directly covers the alpha.16 / alpha.18 / beta.7 regressions.

### D — menu bar UI tests

| Option | Coverage | Feasibility |
|---|---|---|
| **D1. Logic split from rumps (partly there: `test_ui_constants`, `test_ui_dialogs`)** | icon state/transitions, menu text | high, headless |
| D2. PyObjC introspection (instantiate `rumps.App` headless) | object creation | brittle (NSWindow main thread) |
| D3. Full UI automation (XCUITest / cliclick) | real clicking | expensive, flaky |

**Decision: D1 + a light D2 smoke in nightly.** Enforce the pattern: all logic
(which icon state, which alert text, whether the PRO/BYOK gate is active) lives
in pure functions testable without NSWindow; rumps is only the thin render
layer. Full UI automation is not worth it before GA.

## Trade-off analysis

The main trade-off is **CI**: L2/L3 need a macOS Apple Silicon host with
whisper + Core ML, and GitHub-hosted macOS runners are expensive and GPU-less.
So the gates are split:

- **L1** (current) — every commit, GitHub-hosted runner, <30s, no secrets.
- **L2** (real whisper, mock Claude) — every PR, **self-hosted mac** or local
  `make test-pipeline`. Deterministic (WER threshold), no API cost.
- **L3** (real whisper + real Claude) — **nightly + pre-release tag**, needs the
  API secret, budget ~$0.01/run (Haiku, short samples).
- **L4** (UI) — manual at release + a light smoke in nightly.

This keeps the developer feedback loop fast (L1) and defers the
costly / non-deterministic work to nightly.

## Consequences

**Easier:** catching boundary regressions before the user does; measurable
transcription quality (WER) and summary quality (judge score) as a trend;
confidence when bumping the Claude model.

**Harder:** maintaining a self-hosted mac runner (or accepting that L2/L3 run
only locally); the judge adds API cost and variance and needs threshold
calibration; the audio corpus must be versioned (recipe + cache under the OS
temp dir, not git).

**To revisit:** when `malinche_pro` (MCP) lands, an L3 layer for
`search_transcripts` / embeddings is added — same pyramid, new layer.

## Findings

Bugs the layers surfaced as they were built — the point of the exercise.

### F1 — m4a / wma / aac silently fail at the whisper boundary — FIXED (2026-06-15)

`AUDIO_EXTENSIONS` advertised 7 formats, but L2 (`test_real_whisper_transcribes_each_format`)
showed whisper-cli read only **wav, mp3, flac, ogg** natively; **m4a, wma, aac**
failed with `failed to read audio data as wav`. Root cause: the pipeline fed the
raw recording straight to whisper-cli (`-f <file>`) and never transcoded to
16 kHz WAV — `FFMPEG_PATH` was checked for availability but never used. m4a/aac
are exactly what iPhone Voice Memos and many recorders produce, so those
recordings failed with no clear user-facing error.

- **Fix:** `Transcriber._convert_to_wav` normalises every input to 16 kHz mono
  PCM WAV via ffmpeg before whisper (`_run_macwhisper`), then deletes the temp
  WAV. This also fixes non-16 kHz / stereo sources. A conversion failure
  (corrupted/unreadable input) is treated as a permanent transcription failure.
- **Verified:** all 7 formats now pass `test_real_whisper_transcribes_each_format`
  (the xfail guards were removed — the self-correcting design did its job), and
  `test_corrupted_audio_fails_without_crash` still passes via the conversion
  failure path.

## Action items

1. [x] `tests/fixtures/audio_factory.py` — generator: master WAV via `say -v`,
   ffmpeg transcode to all 7 formats, cache + checksum, pytest fixtures
   (`sample_pl`, `sample_en`, `samples_all_formats`, `corrupted_audio`,
   `silence_audio`).
2. [x] Markers: add `e2e` and `ui` to `pyproject.toml`; `requires_whisper`,
   `requires_claude` as skip-if-missing.
3. [x] **L2** `tests/e2e/test_pipeline_real_whisper.py` — real whisper on each
   format, assert WER < threshold + language detected + Markdown valid.
4. [x] **L3** `tests/e2e/test_summary_quality.py` — real Claude (skip without
   `ANTHROPIC_API_KEY` *and* on billing/quota/auth errors, so a dev box with no
   credits stays green): B1 structural + B2 judge ≥ 4/5; `{}` escape test
   (alpha.18 regression, runs without a key). **Note:** the live B1/B2 quality
   assertions are unverified until the account has API credits — the structure,
   skip path, and `{}` guard are verified; the thresholds activate on first
   funded run.
5. [~] **L3** multilang: PL covered (Polish-summary judge); EN structural.
   ES/DE/FR still to add.
6. [x] Edge cases: 0-byte, corrupted header, silence, sample-rate ≠ 16k,
   filename with `{}` and PL chars.
7. [ ] **L4** split menu bar logic into pure functions (extend
   `test_ui_dialogs`); fix `test_menu_bar_icons.py` (add Pillow to
   `requirements-dev.txt`).
8. [x] `Makefile`: `make test` (L1, default), `make test-pipeline` (L2),
   `make test-e2e` (L3, needs key), `make test-ui` (L4).
9. [ ] CI: split workflow — L1 on GitHub-hosted; L2/L3 on self-hosted mac
   (nightly) or documented as a local pre-release gate.
10. [ ] Fix the known version mismatch (`setup_app.py` beta.10 vs UI beta.8) —
    a pre-release gate.
