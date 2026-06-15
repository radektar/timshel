# Malinche Backlog

> Active work and planned features. For shipped items see [CHANGELOG.md](CHANGELOG.md).
>
> **Related:**
> - [Docs/PUBLIC-DISTRIBUTION-PLAN.md](Docs/PUBLIC-DISTRIBUTION-PLAN.md) — distribution strategy
> - [Docs/BETA-1-PLAN.md](Docs/BETA-1-PLAN.md) — beta program

---

## Business model: Freemium (MCP-first)

The application code is open source (MIT). AI features run locally via BYOK. The paid PRO tier sells **MCP integration** — a hosted transcript database your LLM can search natively — not hosted AI summaries.

```
┌──────────────────────┬───────────────────────────┬─────────────────────────────────┐
│  FREE (MIT)          │  + BYOK (your key)        │  + PRO subscription (v2.1.0)    │
├──────────────────────┼───────────────────────────┼─────────────────────────────────┤
│  ✅ Auto-detection   │  ✅ Everything in FREE +  │  ✅ Everything in FREE/BYOK +   │
│  ✅ Local transcribe │  ⭐ AI summaries          │  ⭐ Cloud transcript DB         │
│  ✅ Markdown export  │  ⭐ AI smart tags         │  ⭐ Local MCP server            │
│  ✅ Basic tags       │  ⭐ AI naming             │  ⭐ Semantic search             │
│  ❌ AI / cloud / MCP │  ⭐ Versioning/Retranscr. │  ⭐ Auto-config MCP clients     │
│                      │  (needs ANTHROPIC_API_KEY)│  ⭐ Cross-device sync           │
└──────────────────────┴───────────────────────────┴─────────────────────────────────┘
```

> **Key subtlety:** AI summaries/tags/naming are **MIT + BYOK**, not PRO. PRO does not replace BYOK — the fullest experience is **PRO + BYOK** (local AI via your Anthropic key + hosted, MCP-searchable transcript DB via the subscription).

**Pricing: TBD before v2.1.0 (Phase 3 backend).** Considered options: subscription $5–$12/mo Individual; optional $25/mo Organization; or $79 lifetime. Decision to be made before the backend build.

---

## v2.0.0 FREE — remaining work

- [x] **Audio pre-conversion to WAV before whisper** (bug F1, found + fixed 2026-06-15)
  - `AUDIO_EXTENSIONS` advertised `m4a, wma, aac` but whisper-cli could not
    decode them (only wav/mp3/flac/ogg natively); m4a/aac (iPhone Voice Memos,
    many recorders) silently failed.
  - Fixed: `Transcriber._convert_to_wav` normalises every input to 16 kHz mono
    WAV via ffmpeg before whisper. Guarded by
    `tests/e2e/test_pipeline_real_whisper.py`. See `Docs/TESTING-E2E-STRATEGY.md` §F1.
- [ ] **Code signing & notarization** (requires $99 Apple Developer Program)
- [ ] **py2app bundle size optimization** (currently 43 MB, target <20 MB excluding models)
  - Audit largest dependencies (`du -sh dist/Malinche.app/Contents/Resources/*`)
  - Tighten py2app `excludes` for unused PyObjC frameworks
  - Consider switching to `pyinstaller` if savings are material

## v2.1.0 PRO — MCP integration (flagship)

The PRO pipeline: `transcript → cloud DB + embeddings → local MCP server → your LLM`. Implemented in a private `malinche_pro` package, lazy-loaded by the open-source app.

- [ ] **Local MCP server** (5 tools: `search_transcripts`, `get_transcript`, `list_recent`, `list_by_date_range`, `find_quotes`) — works in Claude Desktop, Cursor, Continue, Claude Code, Zed
- [ ] **Cloud transcript DB** — Supabase (managed Postgres + pgvector), per-user row-level security
- [ ] **Embeddings** — hosted server-side via Voyage `voyage-3-lite` (or OpenAI `text-embedding-3-small`)
- [ ] **PRO backend** — Cloudflare Workers (`/v1/license/validate`, `/v1/embeddings`) + LemonSqueezy webhook → license issuance; license validation in `src/config/license.py`
- [ ] **Auto-config wizard** — detects and writes MCP config for Claude Desktop / Cursor / Continue / Claude Code on activation
- [ ] **Cross-device sync** — same transcript DB visible from any device with an active license
- [ ] **Marketing site** at `malinche.app` with checkout flow

> AI summaries/tags/naming are **not** in this list — they stay in MIT via BYOK. PRO does not host a Claude proxy; the backend only stores transcripts and computes embeddings.

## v2.2.0+ candidates (PRO, post-MVP)

- [ ] **Speaker diarization** — local, MLX-based; identify speakers across recordings
- [ ] **iOS sync** — Mac/iOS via Supabase (affects PRO Organization positioning)

> **Out of product scope:** shared speaker DB, domain lexicon, and knowledge-base extraction belong to a separate personal-AI layer built on top of Malinche PRO's MCP server, not to the Malinche product itself. See `Docs/future/knowledge-base-engine.md` for the design notes (kept for reference only).

---

## Open questions (need decisions)

- [ ] **PRO pricing** — model and amount: subscription $5–$12/mo Individual vs $79 lifetime
- [ ] Include **PRO Organization** at launch, or Individual only?
- [ ] **Trial / freemium-extended** — e.g. 100 free MCP transcripts?
- [ ] **Apple Developer Program** registration ($99/year) — timing (blocker for v2.0.0 GA, not beta)
- [ ] **Architectures** — Apple Silicon only, or also Intel?
- [ ] **iOS sync** timeline — affects PRO Organization positioning

---

## Improvements / nice-to-have

### Configurable Core ML mode

- New setting `WHISPER_COREML_MODE` with values `auto | off | force`
  - `auto` — try Core ML, fall back to CPU on failure (current behavior)
  - `off` — always CPU
  - `force` — Core ML only, error on failure (debug)
- Heuristic detection: if N out of last M whisper runs failed with Core ML errors, auto-disable for the session

### Native menu bar wrapper

The current Python-based menu bar app (rumps + PyObjC) works but ships 43 MB of Python runtime. A Swift launcher could:
- Set `PATH`/`PYTHONPATH` and start the Python daemon as a child process
- Reduce the standalone bundle size if the daemon stays separate

This is a follow-up after py2app size optimization fails to hit the <20 MB target.

### Documentation

- [ ] Translate `Docs/archive/` and `Docs/testing-archive/` (low priority — historical)
- [ ] Translate `CHANGELOG.md` historical entries (low priority — frozen text)

---

## Recent shipped work

For the full release log see [CHANGELOG.md](CHANGELOG.md). Highlights since v1.x:

- v2.0.0-beta.8: UI redesign (English UI, settings tabs, log viewer, aztec accent palette)
- v2.0.0-beta.6: Multi-device deduplication and versioned retranscription
- v2.0.0-beta.4: First-run wizard polish, py2app bundle, DMG release
- v2.0.0-beta.1 → beta.3: Universal recorder support, dependency download, settings UI
