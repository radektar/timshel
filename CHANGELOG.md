# Changelog

All notable changes to Malinche will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed
- **Insights window — pixel-perfect port of the Claude Design component redesign.**
  Implements `design-system/pages/insights-window-components-redesign.html` 1:1:
  one **radius family** (controls 6px, checkbox 5px, rows/cards 12px); the triage
  **segment is now a hybrid** segmented control (active segment carries icon +
  label + count and fills the free width; inactive collapse to icon + count) that
  fits the 236px rail; the **direction checkbox** is weightier and aligned to the
  first text line; the **rail row** gets a 26px sigil, a `.07` active fill + gold
  stripe, and a bookmark glyph on kept items; the **handoff CTA** becomes a split
  pill (white brand chip with the provider glyph + a joined switcher caret) over a
  quiet icon cluster for the secondary actions; the **footer** keeps the jade
  Zachowaj (now with a bookmark glyph) against a ghost Odrzuć; palette aligned to
  the on-dark design tokens (`--terra #D9542A`, `--terra-deep #C24010`).

### Added
- **Triage navigation — Nowe / Zachowane / Odrzucone.** The rail now has a
  segmented control (count over label) to switch among the three triage views,
  so Zachowaj and Odrzuć finally lead somewhere: kept connections have a home to
  return to, and dismissed ones can be **recovered** (Odrzuć is now reversible —
  it retags rather than deletes). `InsightDeck` becomes a three-state model
  (`new` / `kept` / `dismissed`) with a current-view filter; keep/dismiss retag
  the active connection and advance within the view. State **persists across
  sessions**, reconstructed from the signal log via
  `validation_signal.triage_state_by_sig` (latest Zachowaj/Odrzuć per canonical
  `sig`) — no new store, so Odrzuć stays a signal, not a suppressor. Each view
  has its own empty state. (This model is a deliberate extension; it is not in
  the current Claude Design reference, which only specs per-insight triage.)

### Changed
- **Insights buttons now read as interactive — hover, pressed, cursor.** Per the
  Claude Design system (which specs `cursor:pointer`, a hover brighten + lift,
  and a pressed state), the action bar and footer were inert borderless buttons
  with none of it; the only hover infra (`hover.py`) also painted the system
  selection **blue**, off-brand. Introduced one `_PillButton` with a pointing-hand
  cursor, a hover fill (brightened from the base), a darker pressed fill, an
  optional label-brighten for ghost buttons, and a soft shadow for the lift —
  routed across the CTA, switcher, secondary icons and Zachowaj / Odrzuć. The
  rail / direction-row hover (`_HoverButton`) now paints a brand-neutral wash via
  a non-destructive overlay (so call-site tints survive) and shows the pointing
  cursor. **Zachowaj** is now a jade pill (the local/private affirmative) instead
  of the same grey as Odrzuć.

- **Insights handoff bar — buttons no longer misalign or clip.** The action row
  was positioned with hardcoded width guesses that diverged from the real button
  widths, so the last button ("Kopiuj") could fall off the right edge. It is now
  one measured, right-anchored layout that degrades gracefully under width
  pressure (drops the provider name, then the selection-count label) so the
  actions never clip. The secondary actions (task / calendar / clipboard) become
  compact **icon-only** buttons (SF Symbols + tooltips), and the primary CTA now
  carries the connected provider's **brand mark** — Claude / OpenAI (ChatGPT) —
  vendored locally under `assets/brands/` (offline; never fetched at runtime) and
  tinted as a template image. Window min-width raised to keep the full bar
  comfortable. The direction **checkbox** is now vertically centred on the first
  text line instead of sitting low on multi-line rows.

### Removed
- **Gemini dropped as a handoff LLM.** It exposes no public prompt-prefill URL,
  so its handoff silently degraded to copy-and-paste while looking identical to
  the one-click Claude / ChatGPT flow. The connected-LLM switcher now cycles only
  the prefill-capable tools (Claude ↔ ChatGPT); a stale `gemini` in saved config
  falls back to Claude. The clipboard fallback still covers over-long payloads.

### Added
- **The action-rate KPI is now measurable — `make signal-report`.** The
  action-engine writes `action_taken` events; this is the read side that closes
  the loop. It folds `signal.jsonl` into **action-rate** — the share of *engaged*
  connections (any triaged, unique canonical `sig`) that produced at least one
  non-`none` move — plus breakdowns by kind, target, LLM tool, and connection
  type, the time span, and a one-line gate read (alive vs. kill-signal). Pure
  `summarize()` over event dicts with a tolerant loader (legacy v1 / malformed
  lines are skipped, not miscounted); `--json` for piping. See
  `src/connections/signal_report.py` and `Docs/future/ADR-004-insight-action-integration.md`.
- **Insights become actions — the window is now an action engine, not an
  archive.** Each connection lays out as *spark → ground → act*: the high-level
  rationale up top, the dated, quoted **evidence** per note revealed inline on
  demand (so an insight survives without fresh memory), and the directions
  promoted to **multi-select** with one shared handoff bar. Selected directions
  are packaged (insight + evidence + chosen directions) and handed to your
  **connected LLM** (Claude / ChatGPT / Gemini, switchable), the **calendar**
  (`.ics` → Calendar.app), a **task** (Reminders.app), or the **clipboard** —
  all zero-OAuth, via macOS `open`/`osascript`. The constellation is demoted to
  a small static per-type **sigil**; the reader scrolls with a pinned
  Odrzuć · Zachowaj footer that is never cropped. A new `action_taken` signal
  (`signal.jsonl` v2) records what you *did* with an insight — action-rate
  replaces keep-rate as the validation KPI. Synthesis now emits the evidence
  layer and fuller, still-non-prescriptive directions. See
  `Docs/future/ADR-004-insight-action-integration.md`.
- **Insights window is a lens over the vault — notes and transcripts open in
  Obsidian.** Source-note chips and the "Ostatnie transkrypty" rail are now
  clickable and hand off to Obsidian via `obsidian://open?path=` (no vault-name
  guessing); a new `src/ui/obsidian_link.py` builds the deep links and resolves a
  bare note basename anywhere in the vault. Malinche surfaces the connection and
  launches the reader rather than rebuilding one.
- **Insights "Konstelacja" window + validation signal.** A native AppKit window
  (`src/ui/dashboard_window.py`) renders the digest's connections as a
  constellation (terracotta nodes, golden bloom) with Zachowaj/Odrzuć; each
  triage appends one line to `{vault}/.malinche/signal.jsonl` (`validation_signal`)
  so kept-vs-dismissed by connection type can be measured over time.
- **Distance-injection synthesis.** `candidate_assembly` injects
  `SYNTHESIS_BRIDGE_COUNT` cross-topic "bridge" notes (far in topic, joined by a
  shared rare token) so the synthesis sees combinations pure similarity retrieval
  cannot surface — the source of surprising, cross-time/cross-domain connections.

### Changed
- **Menu-bar menu cleaned up to Docker-level.** Trailing "…" now follows the
  macOS HIG — it stays only on commands that need more input in a dialog
  ("Import audio…", "Settings…") and is dropped from items that act immediately
  or open a submenu ("Insights", "Open logs", "Open latest digest", "Generate
  digest now", "Retranscribe file"). Each action carries an **SF Symbol icon**
  (template images that adapt to light/dark + selection), the header shows a
  **status dot keyed by state**, and the Insights item shows the unseen-insight
  **count** (`Insights (N)`).
- **"Ostatnie transkrypty" now shows real data.** The Insights rail listed three
  hardcoded placeholder rows from the design phase; it now reads the real most-
  recent transcripts from `vault_index.recent_entries`, injected via a callback
  from `menu_app` (the only owner of `transcriber`/`vault_index`).
- **Odrzuć now gives feedback.** Dismiss showed nothing — the connection just
  vanished, so the user couldn't tell what their click signalled. It now mirrors
  Zachowaj with a brief flash ("Odrzucone · nie wróci") before advancing, so the
  validation signal is made on an understood action; the keep/dismiss bloom tint
  is parameterised so a dismiss no longer flashes celebratory gold.
- **Sharper synthesis prompt is now the default.** A horoscope guard (reject
  connections true of any random notes), a real shared-thread vs emergent-idea
  split, and a 2-3 sentence rationale that names the specific tension/transfer.
  In an A/B/C run it eliminated generic shared-thread noise and deepened every
  rationale. `SYNTHESIS_MAX_TOKENS` raised 2048 → 4096 (the old verbose prompt
  truncated mid tool-call at 2048 and returned zero connections).

### Removed
- **Retired status-panel popover surface.** `src/ui/status_panel.py` and
  `src/ui/status_panel_model.py` (plus their tests) backed the old left-click
  `NSPopover`, replaced by the native menu + Insights window. They were dead at
  runtime (`_status_panel` was hardwired `None`, `build_status_panel` never
  called) but read as live. Removed them and the dead `_build_panel_model` /
  panel branch in `_update_icon`, along with unused dashboard helpers
  (`_row_buttons` accumulator, the ignored `_label(weight=)` parameter) and the
  now-orphaned `license_manager` / `FeatureTier` imports.

### Fixed
- **Dependency download/repair updated the menu bar off the main thread.** The
  `done`/`error` callbacks correctly hopped to the main thread via
  `_run_on_main_thread`, but the `progress` callbacks set `status_item.title`
  and updated the progress window directly from the worker thread — an AppKit
  mutation off-main that can corrupt UI or crash. Both progress callbacks now
  hop to the main thread too.
- **Insights window showed placeholder connections even after a real digest.**
  The window is built once at launch (when no digest exists yet, so it renders
  the `sample_deck()` placeholder), and opening it only called `showWindow()` —
  `updateDeck_` was never invoked, so a digest landing mid-session never reached
  the open window (the badge count updated, the content didn't). `_open_insights`
  now refreshes from `latest_deck()` before showing.
- **"Ostatnie transkrypty" rail was permanently empty — wrong delegation level.**
  `menu_app` read `self.transcriber.vault_index`, but `self.transcriber` is the
  `MalincheTranscriber` wrapper and `vault_index` lives on its inner `Transcriber`
  — so the access raised `AttributeError`, was swallowed, and returned empty
  *before* reaching the new on-disk fallback (which was therefore dead). Added a
  `vault_index` property to `MalincheTranscriber` that forwards to the inner
  transcriber, and made the error path fall through to the disk scan.
- **A truncated synthesis call silently reset the weekly digest trigger.** With
  forced tool-use, a response hitting `max_tokens` still carries a `tool_use`
  block with partial JSON; parsing it leniently yielded "0 connections",
  indistinguishable from a genuinely empty run — so the scheduler marked the run
  done and zeroed the accumulated trigger. `synthesize` now checks
  `stop_reason == "max_tokens"` and returns `None` (recoverable; retried next
  tick) instead.
- **Crash (EXC_BAD_ACCESS) when reopening the Insights window.** The dashboard
  `NSWindow` defaulted to `releasedWhenClosed = YES`, so closing it deallocated
  the window while Python kept the reference; the second open then touched freed
  memory and crashed. Fixed with `setReleasedWhenClosed_(False)` — the same fix
  already applied to Settings. Also renamed the dashboard's `_FlippedView` ObjC
  subclass to `_DashFlippedView`: it collided with the identically-named class in
  `status_panel`, an ObjC global-name clash that would raise if both modules
  loaded in one process (and broke the test suite's collection).
- **"Ostatnie transkrypty" was empty when the vault index had no entries.** The
  rail read only `vault_index`, which is empty on a fresh install (or when
  transcripts were written by an older build that didn't maintain it). It now
  falls back to scanning the vault on disk for the most-recent `*.md`
  (excluding the digest folder and `.malinche`) so it reflects what's actually
  there. Clicking a source-note chip also resolves more precisely — note ids are
  now matched case-/whitespace-insensitively before falling back to Obsidian
  search.
- **Olympus DSS/DS2 dictaphone recordings were ignored.** `.dss` / `.ds2` (Digital Speech Standard, the native format of Olympus DS-series voice recorders — Malinche's own heritage) were not in the accepted-formats set, so those files were skipped on ingest. They are now accepted and transcoded to 16 kHz WAV by the existing ffmpeg step (ffmpeg can decode DSS/DS2). They are decode-only — the test audio factory can't render them — so the format-sync guard treats them as accept-only.
- **FAT/exFAT recorder cards re-prompted on relabel and could be confused with same-size cards.** These cards usually have no `VolumeUUID`, so identity fell straight back to a `name:size:fs` composite that changed when the card was renamed. `get_volume_uuid` now prefers any stable disk-bound id — `VolumeUUID` → `DiskUUID` (GPT partition GUID) → `MediaUUID` — before that composite, so a card exposing a partition/media UUID keeps a stable identity across relabels and readers. The name-based fallback remains only for cards that expose none of these.
- **"Once" approval transcribed nothing.** Choosing "Once" (transcribe this disk now, don't remember it) authorized the disk at the gate but recorded the approval only on the `FileMonitor` instance, while recorder discovery (`find_recorders` → `should_process_volume`) reads only the persisted whitelist — so the disk passed the prompt and was then dropped, transcribing zero files (this also affected the FSEvents path, not just polling). "Once" is now a process-wide, mount-session approval (`src/volume_session.py`) consulted by *both* the gate and discovery, so the disk is actually transcribed. It is deliberately not persisted: when the disk is ejected the periodic scan forgets it (`prune_to`), so a remount re-prompts — matching the "trust just for this session" intent and the privacy promise.
- **An unknown disk could go undetected when FSEvents missed its mount.** Detecting a new recorder/SD card relied entirely on a single FSEvents mount event resolving correctly; the 30 s periodic checker only re-scanned *already-trusted* disks, so a coalesced or parent-reported (`/Volumes` rather than the mountpoint) mount event left an unknown disk invisible until remount. The periodic checker now also calls `FileMonitor.scan_unknown_volumes`, which surfaces any unknown, non-system volume through the same Tak/Nie/Raz prompt — turning the poll into a real fallback. Existing trusted/blocked decisions and "Once" approvals are honoured, so a disk is never re-prompted.
- **AI summaries ignored the recording's language and invented content.** The summarizer prompt was written entirely in Polish and ended with "use Polish only", so an English recording came back as Polish notes; its fixed-count template ("5-7 sentences", "3-5 tasks") also padded short transcripts with hallucinated action items that were never said. The prompt is now in English (the model localises section headings to the transcript's language) with explicit grounding rules, plus deterministic in-code language detection (`summarizer.detect_language`, pl/en) that injects a named directive — Haiku's language prior was strong enough that the in-prompt rule alone was only ~60% reliable. Live L3 quality on the sample went from 4/5 faithfulness + Polish output to faithfulness/grounding/language all 5/5, guarded by new L3 tests.
- **The app showed a generic Python icon in the Dock.** The menu-bar app is accessory-only, but nothing set its activation policy, so launching it added a Dock tile. `main()` now sets `NSApplicationActivationPolicyAccessory` (mirrored by `LSUIElement` in the py2app bundle), so it lives only in the menu bar.
- **App version was inconsistent across the codebase** (`src/__init__`, `src/ui/constants` and `setup_app.py` had drifted to different `beta.x` strings). `src.__version__` is now the single source of truth — `constants` derives from it and the bundle literal is kept in lock-step by `tests/test_versions_sync`.
- **Crash (SIGSEGV) when closing the Settings window.** The native settings `NSWindow` was released by both AppKit (on close) and Python; the deferred close animation (`-[_NSWindowTransformAnimation dealloc]`) then dereferenced freed memory (`EXC_BAD_ACCESS`). Fixed with `setReleasedWhenClosed_(False)`, dismissing via `orderOut_` instead of the animated `close()`, and retaining the window/delegate past the runloop turn that tears them down.
- **m4a / wma / aac recordings silently failed to transcribe.** whisper-cli only decodes 16 kHz WAV (plus mp3/flac/ogg in this build); the pipeline fed it the raw file and never converted, so common recorder formats — notably m4a/aac from iPhone Voice Memos — failed with `failed to read audio data as wav` and no clear error. `Transcriber._convert_to_wav` now normalises every input to 16 kHz mono WAV via ffmpeg before whisper (also fixing non-16 kHz / stereo sources). Surfaced and guarded by the new L2 scenario tests — see `Docs/TESTING-E2E-STRATEGY.md` §F1.

### Added
- **Connection synthesis — the "Zestawianie" digest (local-first, BYO-Claude).** Malinche now reads the whole transcript corpus together and, on a calm weekly cadence (pulled forward when enough new material lands), writes a digest note into the vault (`Malinche Digests/`) surfacing *emergent connections* across recordings — shared threads, **contradictions in your stance over time**, and latent ideas — each with `[[wikilinks]]` back to the sources and 2–4 non-prescriptive directions. This is the differentiating value above transcription/recall (Whisper/MacWhisper/NotebookLM are commodity): a system that *composes something of its own* from notes that otherwise lie dead. 100% local — candidates are assembled with **no embeddings** (recency window + shared-tag bridges + a small in-process BM25 over summaries, bounded to a token budget; `bm25s` is the documented drop-in at scale), and a single forced-tool-use Claude pass returns a strict, Pydantic-validated result (note ids are normalized so any model's `[[..]]` framing maps cleanly to the known notes / dismiss signatures / wikilinks). Model-agnostic per stage (`LLM_MODEL_SYNTHESIS`, default Haiku) with a model-comparison harness (`make eval-synthesis`) that scores Opus 4.8 vs Sonnet 4.6 vs Haiku on six discriminating gold cases. Dismiss anything that misses by adding its number to the digest's `dismissed:` frontmatter list — the next run respects it (Obsidian-native, no UI needed). Gated behind PRO or a BYOK key; reuses the existing summarizer/tagger client + session circuit breaker so a billing trip degrades through the same menu-bar alert. Menu: "Generate digest now…" / "Open latest digest…". New `src/connections/` package + `src/llm/model_router.py`; hooks at the post-index seam in `transcriber.py` and the periodic tick in `app_core.py`. See `Docs/POSITIONING.md` (the value ladder).
- **New app icon — a terracotta waveform on a cream squircle.** The old skeuomorphic "M" monogram (heavy terracotta→black gradient, fret corners, jade dots — illegible and off-brand at 32 px) is replaced by a mark that extends the menu-bar `waveform` SF Symbol into the bundle icon: eleven flat-topped bars in a lively, dipping rhythm that reads as both an equalizer and a stepped *talud-tablero* pyramid, so the Aztec reference lives in the form rather than as glued-on ornament. Generated programmatically (vector-precise, reproducible) by `assets/gen_icon.py` (`make icon`); the greca step-fret now lives only on packaging surfaces (DMG background). The retired monogram generator (`scripts/gen_aztec_icon.py`), its `malinche.iconset/`, and the placeholder `assets/create_icon.sh` were removed. See `Docs/VISUAL-IDENTITY.md`.
- **Native macOS UI redesign (L4).** A real design system (`src/ui/style.py`: 8pt spacing grid, type scale, restrained palette — system colours + one terracotta accent, jade for "ready", system red for errors) drives every surface. Menu-bar status icons are now rendered from **SF Symbols** (guaranteed on macOS 12+) instead of shipped PNGs that could go missing and fall back to emoji. The menu-bar item opens an **`NSPopover` status panel** (vibrant material, status + current file + recent transcripts, hover states) on left-click and keeps the native menu on right-click. See `Docs/UI-REDESIGN-L4-PLAN.md`.
- **Settings redesigned as a sidebar + grouped cards** (General / Transcription / Disks / Maintenance) on a vibrant window, replacing the flat hand-placed dialog.
- **Styled first-run onboarding.** The setup wizard's screens render in a vibrant `NSWindow` (app icon, headline, progress dots, accent action) instead of plain `rumps.alert`s — Welcome and Finish plus the middle steps (recording sources, output/language/model with an embedded folder picker and popups, AI key entry). Falls back to alerts when AppKit is unavailable.
- **Manual "Import audio…" — a fallback when auto-detection misses a file.** A new menu-bar action opens a file picker (filtered to the supported audio formats); the chosen file is copied into the local staging area (collision-safe — the original is never touched) and run through the full single-file pipeline (`Transcriber.stage_audio_file` / `import_audio_file`). Lets you transcribe anything the recorder/SD watcher didn't pick up, without waiting for a remount.
- **End-to-end / scenario test layers (L1–L3)** under `tests/e2e/` and `tests/fixtures/`: a deterministic audio sample factory (macOS `say` + ffmpeg, all 7 formats + edge cases), real-whisper pipeline tests (per-format, multilingual, WER-scored), and real-Claude summary-quality tests (structural + LLM-as-judge), with `make test-pipeline` / `make test-e2e` / `make test-ui` targets. See `Docs/TESTING-E2E-STRATEGY.md`. L3 is now live-validated against the real API, with added guards for output-language fidelity and non-fabrication.

### Changed
- **The app no longer appears in the Dock** — it is menu-bar only (see the accessory-policy fix above).
- **Licensing defaults to PRO during the beta.** With no licensing backend yet, every install is granted the full PRO feature set; `LicenseManager._verify_license` returns PRO unless a still-valid local cache says otherwise. At GA this flips back to FREE with real verification. (The misleading "always FREE" docstring and a dead code branch were removed.)
- **Retired the shipped `assets/menu_bar/*.png` status icons** — icons are rendered at runtime from SF Symbols, so the static PNG set (and its Pillow-based test) was dead weight and has been removed.
- **Removed redundant system notifications for automatic transcription.** The menu-bar status item already shows recorder connection, progress and completion, so the "Recorder wykryty" and "Transkrypcja zakończona" `osascript` notifications were pure noise — dropped. User-initiated feedback (retranscribe start/complete/fail, memory reset) and error notifications are kept.
- GitHub repository renamed from `radektar/transrec` to `radektar/malinche`. Old URLs auto-redirect; explicit references in `src/setup/checksums.py` and `.github/workflows/build-whisper.yml` updated to the new path.
- Migration flag `transrec_migrated` renamed to `legacy_migrated` in `src/config/settings.py`. `UserSettings.load()` reads the old key name as a backward-compat alias and rewrites it on next save, so existing alpha users are unaffected.
- Active English documentation rewrite: `README.md`, `QUICKSTART.md`, `BACKLOG.md`, and `Docs/*.md` (architecture, development, API, plans, guides) translated from Polish to English. Historical archives in `Docs/archive/`, `Docs/testing-archive/`, `Docs/test-reports/`, and pre-Unreleased entries below remain in Polish.

### Notes
- Per-version notes from v2.0.0-alpha.x onward remain in Polish for historical fidelity. New release entries from this point forward will be written in English.

## [2.0.0-alpha.18] - 2026-04-24

### Fixed
- **Brak markdown + plik `.txt` w vault**: `create_markdown_document()` używał `str.format()` do wypełnienia szablonu, co powodowało `KeyError`/`ValueError` gdy AI-generowany tytuł, podsumowanie lub transkrypt zawierał literalne nawiasy klamrowe `{` lub `}` (np. `{projekt}`, `{action}`). Wyjątek był łapany przez outer `except Exception` w `_postprocess_transcript`, który zwracał `None` i nie usuwał pliku `.txt` ani nie aktualizował `vault_index`. Naprawione przez escape `{` → `{{` i `}` → `}}` we wszystkich polach user-content przed wywołaniem `.format()`.

## [2.0.0-alpha.17] - 2026-04-24

### Fixed
- **Staged pliki porzucone bez recordera**: `process_recorder()` skanuje teraz `LOCAL_RECORDINGS_DIR` jako fallback gdy żaden recorder nie jest podłączony. Pliki wcześniej skopiowane do staging, które nie zostały transkrybowane (np. po restarcie lub błędzie), są przetwarzane automatycznie bez potrzeby ponownego podłączania dyktafonu.

### Added
- **Automatyczne czyszczenie martwych wpisów w vault_index**: wpisy wskazujące na nieistniejące pliki markdown są teraz wykrywalne — usunięto 27 porzuconych wpisów (260420–260423) z `index.json` po tym jak użytkownik ręcznie usunął pliki markdown.

## [2.0.0-alpha.16] - 2026-04-24

### Fixed
- **Nieskończona pętla retry dla uszkodzonych plików audio**: gdy whisper-cli nie może odczytać pliku (`failed to read audio data`), fingerprint trafia do `_session_failed_fingerprints` i plik jest pomijany przez `find_pending_audio_files()` do końca sesji. Efekt: uszkodzony `test_depth3.mp3` (i każdy inny plik który whisper nie może przetworzyć) jest próbowany dokładnie raz, nie co 20 sekund.

## [2.0.0-alpha.15] - 2026-04-24

### Fixed
- **Model `claude-3-haiku-20240307` wycofany przez Anthropic (HTTP 404)**: zmiana domyślnego modelu na `claude-haiku-4-5-20251001` w `src/config/config.py`. Efekt: API calls trafiają do istniejącego modelu zamiast generować 404 na każdym pliku.
- **Circuit breaker obejmuje teraz 404 "model not found"**: `_is_permanent_api_error()` wykrywa zarówno 400 `credit_balance` jak i 404 `not_found_error` (wycofany model). Pierwszy taki błąd wyłącza AI na czas sesji i pokazuje stosowny alert w menu bar.

## [2.0.0-alpha.14] - 2026-04-24

### Fixed
- **Bootstrap idempotencja**: `ensure_ready()` ma teraz fast-path i pomija pełny skan migracji, gdy `settings.transrec_migrated == True`. Efekt: brak logów `[bootstrap] migrated N items` przy każdym starcie, brak przypadkowych kolizji typu `recordings.transrec.bak.legacy.bak…` gdy dwa procesy wystartują równolegle.
- **Circuit breaker dla wyczerpanych kredytów Claude API (`credit_balance is too low`)**: nowy `APIBillingError` w `src/summarizer.py`, wykrywany w summarizerze i taggerze. Po pierwszym takim błędzie `Transcriber` ustawia `_ai_disabled_reason = "billing"` i nie wywołuje już AI dla kolejnych plików — Whisper działa normalnie, markdown dostaje fallback summary. Zamiast spamu HTTP 400 w logu, użytkownik widzi jednorazowy alert w menu bar z instrukcją doładowania konta na `console.anthropic.com`.

## [2.0.0-alpha.13] - 2026-04-24

### Fixed
- **Crash w `done_callback`/`error_callback` przy pobieraniu zależności** (`NSInternalInconsistencyException - NSWindow should only be instantiated on the main thread!`). Wywołania `rumps.alert` i mutacje `status_item`/ikon z wątku `DependencyDownload` są teraz kolejkowane przez `PyObjCTools.AppHelper.callAfter` na main run loop. Skutek: po pobraniu CoreML encodera aplikacja nie ginie w połowie cyklu, a transkrypcja kontynuuje w kolejnej iteracji `process_recorder`.

## [2.0.0-alpha.12] - 2026-04-24

### Fixed
- **CoreML encoder automatycznie pobierany przy starcie**: `whisper-cli` skompilowany z `WHISPER_COREML=ON` crashował z kodem 3 (`failed to load Core ML model`), gdy brakował `ggml-{model}-encoder.mlmodelc/`. Nowy `DependencyDownloader.download_model_encoder()` pobiera encoder z HuggingFace i rozpakowuje go w tle przy starcie (`CoreMLEncoderDownload` thread w `_check_whisper()`). Checksums SHA-256 zweryfikowane z LFS pointer files.
- **`missing_for_selected_model()` uwzględnia encoder**: setup wizard i `DependencyManager.status()` poprawnie raportują brakujący encoder jako wymaganą zależność.

## [2.0.0-alpha.11] - 2026-04-24

### Fixed
- **Automatyczna kolejka transkrypcji oparta o fingerprint**: `process_recorder()` przetwarza teraz pliki `pending` (brakujące w `vault_index`) zamiast wyłącznie `mtime > last_sync`, więc starsze nieprzetranskrybowane nagrania są pobierane automatycznie.
- **Stabilność statusu w menu bar**: przy zajętym locku aplikacja nie wymusza już przejścia do `IDLE`, co eliminuje „skakanie” statusu podczas równoległych triggerów monitora.
- **Bundlowanie DMG**: pakiet `anthropic` nie jest już wykluczany z py2app — aplikacja z `.app` może wywołać Claude API (wcześniej log: `anthropic package not installed`, brak podsumowań i tagów mimo klucza).
- **Runtime safeguard dla AI deps**: przy starcie `bootstrap` wykonuje best-effort `ensure_importable("anthropic")`, instalując brakujący pakiet do `~/Library/Application Support/Malinche/runtime/python-deps` bez psucia systemowego Pythona.
- **Status recordera oparty o fingerprint index**: rozdzielono stany na `recorder_idle` i `recorder_pending`; UI i notyfikacje bazują na brakujących fingerprintach w `vault_index`, a nie tylko na `mtime > last_sync`.
- **BYOK**: przy własnym `ANTHROPIC_API_KEY` (Claude) podsumowania i inteligentne tagi działają bez tieru PRO / `license_cache.json`.

## [2.0.0-alpha.8] - 2026-04-24

### Changed
- **Pobieranie zależności działa asynchronicznie w tle** przez nowy `src/setup/dependency_manager.py` (single source of truth). UI nie zawiesza się podczas setupu ani zmiany modelu w Settings.
- **Kolejność kroków wizarda zmieniona na** `WELCOME -> SOURCE_CONFIG -> BASIC_CONFIG -> DOWNLOAD -> PERMISSIONS -> AI_CONFIG -> FINISH`, dzięki czemu model jest wybierany zanim użytkownik zobaczy ekran pobierania.
- **Natywne okno postępu pobierania** (`src/ui/download_window.py`) z `NSProgressIndicator` zastąpiło pętlę `rumps.alert` z przyciskiem "Sprawdź status".

### Added
- **`UserSettings.setup_stage`** — wizard zapisuje aktualny krok i wznawia od niego po przerwaniu / restarcie aplikacji.
- **Automatyczne kolejkowanie pobierania po zmianie modelu** w Settings (`src/ui/settings_window.py`): brakujący model pobiera się w tle od razu po zapisaniu.
- **`DependencyDownloader.missing_for_selected_model()` i `required_size_for_selected_model()`** — API do model-aware prezentacji wymagań w UI.
- **Status `AppStatus.DOWNLOADING`** + ikona w menu bar z aktualizacją tytułu podczas pobierania.
- **Testy regresji**: `tests/test_dependency_manager.py`, `tests/test_download_window_integration.py`, `tests/test_menu_app_download.py` oraz rozszerzone `tests/test_wizard.py` (reorder kroków, resume `setup_stage`, async download).
- **Manual checklist** `tests/MANUAL_TEST_CHECKLIST_ALPHA8.md` do weryfikacji buildu.
- **Test `test_app_version_format` zaktualizowany do pełnego SemVer 2.0.0** (akceptuje prerelease `-alpha.N` i build metadata `+build`).

## [2.0.0-alpha.7] - 2026-04-23

### Fixed
- **Dodano pełne wsparcie pobierania modeli Whisper używanych w aplikacji** (`tiny`, `base`, `small`, `medium`, `large`) przez rozszerzenie metadanych URL/checksum/size oraz mapowanie `large` na kanoniczny artefakt `large-v3`.
- **Usunięto root cause błędu `Nieznany model: medium`**: downloader buduje teraz ścieżki modelu po nazwie kanonicznej i poprawnie obsługuje konfiguracje zmigrowane z `whisper_model: "medium"`.
- **Naprawiono fałszywe błędy miejsca na dysku podczas setupu**: `download_all()` liczy wymagany rozmiar tylko dla brakujących komponentów zamiast sumy wszystkich możliwych modeli.

### Added
- **Obsługa prefiksowanych checksumów `sha1:` i `sha256:`** w weryfikacji pobranych artefaktów modeli.
- **Nowe testy guardrail dla modeli** (`tests/test_checksums.py`) oraz rozszerzone testy downloadera dla `medium`, aliasu `large -> large-v3`, checksumu SHA-1 i kalkulacji miejsca (`tests/test_downloader.py`).

## [2.0.0-alpha.6] - 2026-04-23

### Fixed
- **Wdrożono pojedynczy bootstrap `ensure_ready()` jako źródło prawdy dla migracji legacy** i podpięto go do obu entry-pointów (`src/main.py`, `src/menu_app.py`), dzięki czemu migracja uruchamia się deterministycznie również w aplikacji menu bar.
- **Usunięto runtime fallbacki do `Transrec` i `.olympus_transcriber*` poza bootstrapem**: `Config` używa teraz wyłącznie ścieżek `Malinche` dla `state.json`, locka, recordings i loga.
- **Naprawiono root cause pobierania złego modelu**: `DependencyDownloader.download_all()` pobiera teraz model wybrany przez użytkownika (`self._selected_model()`), a `download_model()` wymaga jawnego argumentu modelu.

### Added
- **Nowe testy strażnicze architektury migracji**:
  - `tests/test_bootstrap.py` (migracja e2e + idempotencja),
  - `tests/test_entry_points_bootstrap.py` (kolejność bootstrap przed config/logger),
  - `tests/test_no_legacy_names.py` (blokada legacy nazw poza `src/bootstrap.py`).
- **Rozszerzone testy downloadera i uproszczone testy migracji/config** pod nowy model z jednym boundary legacy.

## [2.0.0-alpha.5] - 2026-04-23

### Fixed
- **Ujednolicono ścieżki runtime zależności do `~/Library/Application Support/Malinche`** w `Config` (model i ffmpeg), z read-only fallbackiem do legacy `Transrec` tylko dla kompatybilności.
- **Naprawiono przyczynę błędu ładowania modelu po migracji**: `perform_migration_if_needed()` wykonuje teraz jednorazową migrację zasobów `Transrec/bin` i `Transrec/models` także wtedy, gdy `Malinche/config.json` już istnieje.
- **`check_all()` w downloaderze weryfikuje model wybrany przez użytkownika**, a nie zawsze `ggml-small.bin`, więc brak np. `ggml-medium.bin` poprawnie wymusza pobranie zależności.
- **`SetupWizard.needs_setup()` porównuje tylko linię kompatybilności `major.minor`**, co eliminuje niepotrzebne retriggerowanie wizarda przy bumpach alpha/patch.
- **Wersja UI została zsynchronizowana z buildem** (`src/ui/constants.py` -> `2.0.0-alpha.5`), więc About i logika wersji nie rozjeżdżają się z `setup_app.py`.

### Added
- **Flaga migracji `transrec_migrated`** w `UserSettings` do idempotentnego przenoszenia legacy assetów.
- **Nowe testy regresji** dla:
  - ścieżek `Malinche` i fallbacku `Transrec` (`tests/test_config.py`),
  - migracji assetów legacy (`tests/test_migration.py`),
  - walidacji wybranego modelu w downloaderze (`tests/test_downloader.py`),
  - braku retriggera wizarda przy bumpie alfy (`tests/test_wizard.py`),
  - spójności wersji setup/UI (`tests/test_versions_sync.py`).

## [2.0.0-alpha.4] - 2026-04-23

### Fixed
- **Naprawiono źródłową przyczynę błędu `dyld: Library not loaded` dla `whisper-cli`.** Pipeline [`.github/workflows/build-whisper.yml`](.github/workflows/build-whisper.yml) buduje teraz dwa warianty (`static` i `bundled`), waliduje `otool -L`/`LC_RPATH` pod kątem ścieżek CI (`/Users/runner/...`) i publikuje artefakty porównawcze; release `deps-v1.1.0` jest tworzony przez osobny job `release-winner` z wyborem wariantu.
- **Downloader wykrywa uszkodzoną instalację runtime, a nie tylko obecność pliku.** `DependencyDownloader` dodaje `verify_whisper_runtime()` (`whisper-cli --help`), sprawdzanie kompletności dylibów dla wariantu bundled, migrację starej niekompletnej instalacji i bezpieczne rozpakowanie archiwum.

### Added
- **Nowy błąd domenowy `DependencyRuntimeError`** do sygnalizowania sytuacji „binarka pobrana, ale nieuruchamialna”.
- **Nowe testy regresji downloadera** dla smoke-testu runtime, scenariusza `dyld` i rozpakowania wariantu bundled (`tests/test_downloader.py`).

## [2.0.0-alpha.3] - 2026-04-22

### Fixed
- **Recorder już zamontowany przed startem Malinche jest teraz natychmiast wykrywany.** `FileMonitor.start()` dodaje jednorazowy `_initial_scan()`, który po założeniu obserwatora FSEvents sprawdza aktualną zawartość `/Volumes` i wywołuje `callback()`, jeśli któryś z wolumenów spełnia `should_process_volume()`. Do tej pory FSEvents reagował wyłącznie na zdarzenia mount/zmiana, więc po restarcie daemona z już podłączonym LS-P1 Malinche siedziała bezczynnie aż do wyjęcia i ponownego włożenia urządzenia.
- **Zaślepka po pythonowym circular imporcie.** `src/config/license.py` importował `src.logger` na poziomie modułu, co tworzyło cykl `logger → config → license → logger` i wywalało testy uruchamiane w izolacji (np. `pytest tests/test_file_monitor.py`). Import przeniesiono do środka metod (`activate_license`, `deactivate_license`), zachowując identyczne zachowanie publiczne.
- **`ProcessLock` wykrywa i usuwa lock pozostawiony przez ubity proces.** Plik locka zawiera teraz `<pid>\n<timestamp>` (zamiast samego timestampa). Przy `FileExistsError` sprawdzamy `os.kill(pid, 0)` — jeśli proces nie żyje, lock jest natychmiast kasowany i akwizycja ponawiana. Legacy format (sam timestamp) nadal obsługiwany jako fallback.

### Added
- **Autouse izolacja HOME w testach.** Nowy `tests/conftest.py` przekierowuje `$HOME` na tymczasowy katalog sesji ZANIM którykolwiek moduł testowy zaimportuje `src.logger`/`src.config`. Efekt: żaden `pytest` nie zmienia już `~/.olympus_transcriber_state.json`, `~/.olympus_transcriber/transcriber.lock` ani `~/Library/Logs/olympus_transcriber.log` zainstalowanej Malinche.
- **Session-level guard `_assert_real_home_untouched`** robi snapshot mtime chronionych plików na starcie sesji testowej i fail-uje run, jeśli którykolwiek zostanie zmieniony. Regresja, która przywróciłaby pisanie do realnego HOME, zostanie złapana w CI/lokalnie.
- **Nowe testy regresji:**
  - `tests/test_file_monitor.py::TestFileMonitorInitialScan` — 5 przypadków: volumen istnieje, brak volumenów, wiele volumenów (callback wołany dokładnie raz), debounce timer, wyjątki w callbacku nie zatrzymują monitora.
  - `tests/test_transcriber.py::test_process_lock_removes_dead_pid_lock` — martwy PID w locku jest natychmiast usuwany.
  - `tests/test_transcriber.py::test_process_lock_keeps_lock_for_live_foreign_pid` — żywy PID `1` (`launchd`) blokuje akwizycję.

### Changed
- `FileMonitor.start()` inicjalizuje `_last_trigger_time` po initial scan, żeby mount-driven FSEvent-y następujące tuż po starcie były debounce'owane (nie duplikowały work).
- `ProcessLock.acquire()` zapisuje PID bieżącego procesu w locku; istniejący test `test_process_lock_removes_stale_file` zaktualizowany, żeby weryfikować nowy format.
- `tests/test_file_monitor.py` — trzy testy, które wcześniej patrzyły na prawdziwy `/Volumes`, teraz jawnie patchują `find_matching_volumes` na pustą listę, żeby initial scan nie fałszował ich intencji.
- `tests/test_transcriber.py::test_run_macwhisper_retries_on_metal_error` — forsuje `transcriber.whisper_available = True` zamiast polegać na prawdziwym binarium w user HOME (teraz wyizolowanym przez conftest).

---

## [2.0.0-alpha.2] - 2026-04-22

### Fixed
- **Wykrywanie recordera w trybie `auto` respektuje `watch_mode`** — naprawiono regresję, w której Malinche pokazywała `Oczekiwanie na recorder...` mimo że macOS wykrył i zamontował dyktafon.
  - `Transcriber.find_recorder()` poprzednio iterował wyłącznie po hardkodowanej liście `RECORDER_NAMES` (`LS-P1`, `OLYMPUS`, `RECORDER`), podczas gdy `FileMonitor` w trybie `auto` akceptował dowolny niesystemowy wolumen z plikami audio. Przy dyktafonie o innej nazwie (`IC RECORDER`, `SD_CARD`, `ZOOM`, itp.) `process_recorder()` ustawiał status `IDLE` i UI dalej wyświetlał komunikat oczekiwania.
  - Wykrywanie scentralizowano w nowym module `src/volume_utils.py`, z którego korzystają zarówno `FileMonitor` jak i `Transcriber`. Obie klasy honorują teraz ten sam `watch_mode` (`auto` / `specific` / `manual`).
  - `Transcriber.find_recorders()` (nowa metoda) zwraca **wszystkie** pasujące wolumeny, a `process_recorder()` iteruje po nich i agreguje nowe pliki. `find_recorder()` zachowano jako cienki wrapper dla kompatybilności wstecznej.
  - Usunięto mylący fallback `RECORDER_NAMES = ["LS-P1", "OLYMPUS", "RECORDER"]` w trybie `auto` — lista jest teraz wypełniana tylko w trybie `specific` (na podstawie `watched_volumes`).

### Added
- **Nowy moduł `src/volume_utils.py`** — wspólne helpery `has_audio_files()`, `should_process_volume()`, `find_matching_volumes()` z testowalnym parametrem `volumes_root`.
- **Testy regresji** w `tests/test_volume_utils.py` i `tests/test_transcriber.py`:
  - Auto mode wykrywa wolumeny o dowolnych nazwach zawierające audio.
  - Auto mode pomija wolumeny systemowe oraz puste.
  - Specific mode respektuje `watched_volumes`.
  - Manual mode nigdy nie wykrywa automatycznie.
  - Wyniki `find_matching_volumes()` są posortowane alfabetycznie (deterministyczność).

### Changed
- `FileMonitor._should_process_volume()` oraz `FileMonitor._has_audio_files()` zredukowane do cienkich wrapperów nad `volume_utils` — eliminuje duplikację logiki skanowania.
- `process_recorder()` obsługuje wiele jednocześnie podłączonych wolumenów: notyfikacja "Podłączono" wymienia wszystkie wykryte urządzenia.

---

## [2.0.0-alpha.1] - 2026-02-08

### Added
- **Rebranding: Malinche** - całkowita zmiana nazwy aplikacji z "Transrec" / "Olympus Transcriber" na "Malinche".
  - Nowa ikona i nazwa w pasku menu.
  - Zmiana ścieżki konfiguracji na `~/Library/Application Support/Malinche`.
  - Automatyczna migracja ustawień i modeli z poprzedniej wersji (Transrec).
  - Nowy model brandingowy oparty na postaci historycznej Malinche (tłumaczka i doradczyni).
- **Faza 6: Profesjonalny DMG (wersja testowa)**
  - Skrypty `scripts/create_dmg.sh` oraz `scripts/build_release.sh` dla zautomatyzowanego pakowania.
  - Profesjonalny instalator DMG z linkiem do Applications (bez podpisu Apple Developer).
  - Instrukcja dla testerów `tests/TESTER_INSTRUCTIONS.md` dotycząca omijania blokady Gatekeeper.
  - Nowe targety w `Makefile`: `build-app`, `build-dmg`, `release`.

### Fixed
- **Aktualizacja testów do nowej nazwy Malinche**
  - Poprawiono `test_bundle_identifier`, `test_show_about_dialog` oraz domyślne ustawienia tagowania w testach konfiguracji.


---

## [1.15.2] - 2026-02-08

### Changed
- **Refaktoryzacja systemu konfiguracji** - deterministyczne zachowanie i lepsza testowalność
  - Przeniesiono `src/config.py` → `src/config/config.py` dla lepszej organizacji modułów
  - Usunięto side effects z `Config.__post_init__` - migracja nie jest już wywoływana automatycznie
  - Centralizacja migracji w `src/main.py` - wywołanie przed inicjalizacją innych modułów
  - Usunięto fallback do zmiennych środowiskowych w runtime - ENV jest czytane tylko podczas migracji
  - Dodano lazy-loading proxy dla globalnego `config` singleton
- **Dependency Injection do Transcriber** - lepsza testowalność i izolacja
  - Dodano parametr `config: Optional[Config] = None` do konstruktora `Transcriber`
  - Wszystkie użycia globalnego `config` zastąpione przez `self.config`
  - `app_core.py` przekazuje config do `Transcriber` podczas inicjalizacji
  - Testy używają wstrzykniętego configu zamiast patchować globalny singleton
- **Naprawa logiki głębokości skanowania (max_depth)**
  - Poprawiono liczenie głębokości w `find_audio_files()` - teraz liczy katalogi zamiast części ścieżki
  - Zaktualizowano `_has_audio_files()` w `file_monitor.py` dla spójności
  - Dodano poprawne logowanie wartości głębokości w debug messages

### Added
- **Test jednostkowy dla max_depth** - `test_find_audio_files_respects_max_depth()` w `tests/test_transcriber.py`
  - Weryfikuje wykrywanie plików na różnych głębokościach
  - Potwierdza że pliki > max_depth (3) są ignorowane

### Testing
- ✅ **Testy manualne Faza 1 - zakończone** (2026-02-08)
  - SCENARIUSZ 1: Watch mode "auto" - PASSED
  - SCENARIUSZ 2: Watch mode "specific" - PASSED
  - SCENARIUSZ 3: Watch mode "manual" - PASSED
  - SCENARIUSZ 5: Ignorowanie system volumes - PASSED
  - SCENARIUSZ 6: Migracja ze starej konfiguracji - PASSED
  - SCENARIUSZ 7: Głębokość skanowania (max_depth) - PASSED
  - SCENARIUSZ 4: Wykrywanie różnych formatów audio - POMINIĘTY (częściowo przetestowany .MP3)
  - Raport: `tests/test_results_phase1_2026-02-08.md`

### Technical Details
- **Stabilizacja konfiguracji:** `Config` jest teraz deterministyczny - nie wykonuje migracji podczas inicjalizacji, co eliminuje problemy z globalnym stanem w testach
- **Lepsza testowalność:** `Transcriber` może używać własnego configu w testach, co eliminuje konieczność skomplikowanego patchowania globalnego stanu
- **Separation of concerns:** Migracja jest teraz wyraźnie oddzielona od runtime - wykonywana tylko raz podczas startu aplikacji
- **Backward compatibility:** Wszystkie istniejące testy przechodzą (224/224 pass), kod produkcyjny działa bez zmian
- **Max depth scanning:** Pliki na głębokości > 3 katalogów są teraz poprawnie ignorowane, co poprawia wydajność skanowania

---

## [Unreleased]

### In Progress
- **🚀 Dystrybucja Publiczna (v2.0.0 FREE)** - Szczegółowy plan w [`Docs/PUBLIC-DISTRIBUTION-PLAN.md`](Docs/PUBLIC-DISTRIBUTION-PLAN.md)
  - ✅ **Faza 1:** Uniwersalne źródła nagrań (testy integracyjne zakończone ✅, testy manualne zakończone ✅ - 6/7 scenariuszy)
  - ✅ **Faza 2:** System pobierania whisper.cpp/modeli on-demand (COMPLETED)
  - ✅ **Faza 3:** First-run wizard z konfiguracją (COMPLETED ✅ - testy manualne zakończone)
  - ✅ **Faza 4:** Pakowanie z py2app (COMPLETED ✅ - wszystkie testy przechodzą)
  - [ ] **Faza 5:** Code signing & notaryzacja ($99 Apple Developer)
  - [ ] **Faza 6:** Profesjonalny DMG & GitHub Release
  - ✅ **Faza 7:** GUI Settings & polish (COMPLETED ✅ - wszystkie testy przechodzą, 9/9 manualnych)
    - ✅ Okno ustawień aplikacji (zmiana folderu, języka, modelu po instalacji)
  - ✅ **Faza 8:** Infrastruktura Freemium (COMPLETED ✅)
    - ✅ System feature flags (FREE/PRO/PRO_ORG)
    - ✅ License Manager z offline cache
    - ✅ PRO gate dla AI podsumowań i tagów
    - ✅ UI aktywacji PRO w menu paska stanu
  - ✅ **Faza 9:** Pełny redesign UI (menu bar icons, nowa ikona appki, DMG background, branding dialogów)
  - ✅ **Multi-device dedup v2:** fingerprint audio + `.malinche/index.json` + migracja legacy `.md`
    - FREE: skip transkrypcji gdy fingerprint istnieje
    - PRO: wersjonowanie re-transkrypcji (`.v2.md`, `.v3.md`) z `previous_version`

### Planned Features
- **🔒 PRO Features (v2.1.0)** - AI summaries, auto-tagging, cloud sync
- **🚀 Knowledge Base Engine (v2.2.0+)** - Speaker diarization, domain lexicon, knowledge base extraction (architectural analysis: [Docs/future/knowledge-base-engine.md](Docs/future/knowledge-base-engine.md))
- See `BACKLOG.md` for other upcoming features and improvements

---

## [1.15.1] - 2025-12-29

### Added (Faza 7 - kontynuacja)
- **Okno ustawień aplikacji** (`src/ui/settings_window.py`)
  - Menu item "Ustawienia..." w menu bar app
  - Możliwość zmiany folderu docelowego po instalacji (bez potrzeby usuwania config.json)
  - Możliwość zmiany języka transkrypcji (dropdown NSPopUpButton)
  - Możliwość zmiany modelu Whisper (dropdown NSPopUpButton)
  - Pętla pozwalająca zmienić wiele ustawień w jednej sesji
  - Automatyczny zapis zmian do `config.json`

### Changed (Faza 7 - kontynuacja)
- **src/menu_app.py** - dodano menu item "Ustawienia..."
  - Nowa metoda `_show_settings()` wywołująca okno ustawień
  - Pozycja menu przed "O aplikacji..."

### Technical Details
- Okno ustawień używa AppKit (NSAlert + NSPopUpButton) dla dropdownów
- Fallback na tekstowy input gdy AppKit niedostępne
- Reuse funkcji `choose_folder_dialog()` z modułu UI
- Integracja z `UserSettings.save()` dla zapisu zmian

---

## [1.15.0] - 2025-12-29

### Added (Faza 7)
- **Moduł UI** (`src/ui/`)
  - `src/ui/constants.py` - centralne miejsce na stałe UI (łatwe do wymiany przy redesignie)
  - `src/ui/dialogs.py` - reusable funkcje dialogów (date picker, folder picker, about)
- **Date picker dla "Resetuj pamięć"**
  - Dialog z opcjami: 7 dni / 30 dni / Inna data
  - Input daty w formacie YYYY-MM-DD z walidacją
  - Zastępuje prosty dialog z tylko opcją "7 dni"
- **Graficzny wybór folderu w wizardzie**
  - NSOpenPanel dla natywnego dialogu wyboru folderu
  - Fallback na tekstowy input gdy AppKit niedostępne
- **Dialog "O aplikacji"**
  - Nowy MenuItem w menu aplikacji
  - Wyświetla wersję, linki do strony i GitHub, informacje o licencji
- **Dropdown wyboru języka w wizardzie**
  - NSPopUpButton z pełnymi nazwami języków zamiast tekstowego inputu
  - Lepsze UX - nie wymaga znajomości kodów ISO
- **Opcja "Anuluj" w każdym kroku wizarda**
  - Możliwość zamknięcia wizarda z każdego kroku (oprócz download)
  - Lepsze UX - użytkownik nie musi przechodzić przez wszystkie kroki
- **Testy automatyczne** (`tests/test_ui_constants.py`, `tests/test_ui_dialogs.py`)
  - 18 testów jednostkowych (100% pass rate)
  - Coverage modułu UI: 94% (powyżej wymaganego 80%)
- **Dokumentacja testów manualnych** (`tests/MANUAL_TESTING_PHASE_7.md`)
  - 9 scenariuszy testowych (M7.1-M7.9)
  - Checklist i procedury testowe

### Changed (Faza 7)
- **src/menu_app.py** - użycie nowego modułu UI
  - Metoda `_reset_memory()` używa `choose_date_dialog()`
  - Dodana metoda `_show_about()` z dialogiem O aplikacji
  - Naprawiono notyfikacje - zmiana z `rumps.notification()` na `send_notification()` (osascript)
- **src/setup/wizard.py** - użycie folder pickera i poprawki UX
  - Metoda `_show_output_config()` używa `choose_folder_dialog()`
  - Dialog z opcjami: Wybierz folder / Użyj domyślnego / Wstecz
  - Metoda `_show_language()` używa NSPopUpButton zamiast tekstowego inputu
  - Dodano opcję "Anuluj" w każdym kroku wizarda (PERMISSIONS, SOURCE_CONFIG, OUTPUT_CONFIG, LANGUAGE, AI_CONFIG)
- **src/ui/dialogs.py** - poprawki obsługi przycisków
  - Naprawiono obsługę przycisku "other" w `choose_date_dialog()` - `response=-1` zamiast `2`
  - Poprawiono kolejność parametrów w `send_notification()` (title, message, subtitle)

### Fixed (Faza 7)
- **Notyfikacje nie pojawiały się** - zmiana z `rumps.notification()` na `send_notification()` (osascript)
- **Date picker "30 dni" nie działał** - naprawiono obsługę przycisku "other" (`response=-1` zamiast `2`)
- **Brak możliwości zamknięcia wizarda** - dodano opcję "Anuluj" w każdym kroku
- **Tekstowy input języka** - zastąpiono dropdownem z pełnymi nazwami języków

### Testing (Faza 7)
- ✅ **Testy automatyczne:** 18/18 przechodzą (100% pass rate)
  - Testy stałych UI (9 testów)
  - Testy dialogów (9 testów)
  - Coverage: 94% dla modułu `src/ui/`
- ✅ **Testy manualne:** 9/9 wykonane (100% completion)
  - ✅ M7.1: Date picker - 7 dni (PASS)
  - ✅ M7.2: Date picker - 30 dni (PASS - po poprawce response=-1)
  - ✅ M7.3: Date picker - custom data (PASS)
  - ✅ M7.4: Date picker - błędna data (PASS)
  - ✅ M7.5: Folder picker - NSOpenPanel (PASS)
  - ✅ M7.6: Folder picker - wybór (PASS)
  - ✅ M7.7: Folder picker - anuluj (PASS)
  - ✅ M7.8: About dialog (PASS)
  - ✅ M7.9: About dialog - zamknięcie (PASS)

### Technical Details
- Nowy moduł: `src/ui/` przygotowany na przyszły redesign UI
- Stałe UI w `constants.py` - łatwe do wymiany przy Fazie 9
- Funkcje dialogów w `dialogs.py` - reusable i testowalne
- Dropdown języka używa NSAlert z NSPopUpButton jako accessory view
- Opcja "Anuluj" w wizardzie zwraca "cancel" i kończy konfigurację

---

## [1.14.0] - 2025-12-29

### Added (Faza 4)
- **Pakowanie z py2app** (`setup_app.py`, `scripts/build_app.sh`)
  - Konfiguracja py2app dla macOS bundle (Apple Silicon arm64)
  - Bundle `.app` gotowy do dystrybucji (~45MB)
  - Skrypt automatycznego budowania z weryfikacją
  - Obsługa segfault podczas buildu (znany problem py2app 0.28.9 + Python 3.12.12)
  - Bundle działa poprawnie mimo segfaulta podczas ostatniego kroku weryfikacji
- **Naprawa blokowania UI podczas pobierania zależności**
  - Pobieranie działa w osobnym wątku (nie blokuje UI)
  - Okno dialogowe z aktualnym statusem pobierania
  - Możliwość odświeżania statusu przez użytkownika
  - Notyfikacje o postępie i zakończeniu
- **Dokumentacja testów manualnych** (`tests/MANUAL_TESTING_PHASE_4.md`)
  - Kompletny przewodnik testowania bundle
  - 7 scenariuszy testowych (M4.1-M4.7)
  - Checklist i troubleshooting
  - Instrukcje dla testu na czystym macOS (M4.6)

### Changed (Faza 4)
- **setup_app.py** - Optymalizacja buildu
  - `optimize: 1` (zmniejszone z 2 aby uniknąć segfaulta)
  - `strip: False` (zapobiega segfaultowi podczas sprawdzania importów)
- **scripts/build_app.sh** - Obsługa segfaulta
  - Tymczasowe wyłączenie `set -e` podczas buildu
  - Weryfikacja istnienia bundle mimo segfaulta
  - Ostrzeżenie zamiast błędu gdy bundle istnieje
- **src/setup/wizard.py** - Naprawa logiki pobierania
  - Pobieranie w osobnym wątku z oknem dialogowym
  - Synchronizacja zakończenia pobierania z UI
  - Poprawiona obsługa błędów podczas pobierania
- **BACKLOG.md** - Zaktualizowane zadania Fazy 7
  - Dodano poprawki UX do wykonania
  - Oznaczono naprawione problemy

### Testing (Faza 4)
- ✅ **Testy automatyczne:** 14/14 przechodzą (100% pass rate)
  - Testy konfiguracji setup_app.py
  - Testy skryptu budowania
  - Testy struktury bundle
- ✅ **Testy manualne:** 7/7 wykonane (100% completion)
  - ✅ M4.1: Build test - bundle zbudowany, struktura OK, Info.plist OK
  - ✅ M4.2: Launch test - aplikacja uruchamia się bez błędów
  - ✅ M4.3: Menu functionality - wszystkie opcje działają
  - ✅ M4.4: Wizard w bundle - wszystkie kroki działają
  - ✅ M4.5: Dependency download - pobieranie działa, UI nie blokuje
  - ✅ M4.6: Clean system test - aplikacja działa na czystym macOS bez Python
  - ✅ M4.7: Size verification - 43-45MB (akceptowalne dla v2.0.0)
- ✅ **Znalezione problemy (nie blokujące):**
  - Build segfault podczas sprawdzania importów (obsłużony w skrypcie)
  - Rozmiar bundle większy niż docelowy (43MB vs 20MB - akceptowalne)
  - UX: Reset pamięci wymaga date pickera (do poprawy w Fazie 7)
  - UX: Wizard - brak możliwości anulowania w większości kroków (do poprawy w Fazie 7)

### Technical Details
- Bundle lokalizacja: `dist/Malinche.app`
- Rozmiar: 43-45MB (cel: <20MB, ale akceptowalne dla pierwszej wersji)
- Architektura: arm64 (Apple Silicon only)
- Wersja: 2.0.0
- Bundle działa na czystym macOS bez wymagania instalacji Python
- Wszystkie funkcje działają poprawnie w bundle

---

## [1.13.0] - 2025-12-29

### Added (Faza 3)
- **First-Run Wizard** (`src/setup/wizard.py`)
  - 8-krokowy wizard konfiguracji przy pierwszym uruchomieniu
  - Automatyczne pobieranie zależności z progress bar (integracja z Fazą 2)
  - Instrukcja Full Disk Access z linkiem do System Preferences
  - Konfiguracja źródeł nagrań (auto/specific volumes)
  - Wybór folderu docelowego na transkrypcje
  - Wybór języka transkrypcji (pl, en, auto)
  - Opcjonalna konfiguracja AI podsumowań (klucz API Claude)
  - Nawigacja wstecz między krokami
  - Anulowanie wizarda na dowolnym kroku
- **System ustawień użytkownika** (`src/config/`)
  - Klasa `UserSettings` z persystencją do JSON
  - Domyślne wartości w `defaults.py` (języki, modele, ścieżki)
  - Lokalizacja: `~/Library/Application Support/Malinche/config.json`
  - Obsługa load/save z automatycznym tworzeniem katalogów
- **Moduł uprawnień** (`src/setup/permissions.py`)
  - Sprawdzanie Full Disk Access przez próbę dostępu do chronionych katalogów
  - Automatyczne otwieranie System Preferences -> Privacy -> Full Disk Access
  - Sprawdzanie dostępu do konkretnych volumów

### Changed (Faza 3)
- **menu_app.py** - Integracja z wizardem przy starcie
  - Sprawdzanie `SetupWizard.needs_setup()` przed uruchomieniem daemona
  - Uruchamianie wizarda przy pierwszym starcie (z opóźnieniem dla GUI)
  - Przeniesienie logiki pobierania zależności do wizarda (krok 2)
  - Daemon uruchamia się dopiero po zakończeniu wizarda
  - Obsługa anulowania wizarda z komunikatem dla użytkownika

### Testing (Faza 3)
- ✅ Testy jednostkowe: test_user_settings.py (6 testów, 100% pass)
- ✅ Testy jednostkowe: test_permissions.py (6 testów, 100% pass)
- ✅ Testy jednostkowe: test_wizard.py (8 testów, 100% pass)
- ✅ Testy manualne: MANUAL_TESTING_PHASE_3.md (10/16 kluczowych testów przeszło pomyślnie)
  - Weryfikacja przepływu wizarda, integracji z menu_app, zapisywania konfiguracji
  - Znalezione problemy UX zapisane w BACKLOG.md (nie blokują produkcji)

### Technical Details
- Wizard pojawia się tylko gdy `setup_completed == false` w config.json
- Po zakończeniu wizarda: `setup_completed = true` i wszystkie ustawienia zapisane
- Wizard obsługuje skip kroków (pobieranie jeśli już pobrane, FDA jeśli już nadane)
- Integracja z istniejącym `DependencyDownloader` z Fazy 2
- Wszystkie dialogi używają `rumps.alert()` i `rumps.Window()` dla natywnego macOS UX

---

## [1.12.0] - 2025-12-26

### Added (Faza 2)
- **Moduł pobierania zależności** (`src/setup/downloader.py`)
  - Klasa `DependencyDownloader` z automatycznym pobieraniem whisper.cpp i ffmpeg
  - Weryfikacja checksum SHA256 dla bezpieczeństwa
  - Retry logic z exponential backoff (max 3 próby)
  - Resume download dla przerwanych pobierań (Range header)
  - Progress callback dla UI
  - Obsługa błędów: brak internetu, brak miejsca, timeout, serwer niedostępny
- **Custom exceptions** (`src/setup/errors.py`)
  - `DownloadError`, `ChecksumError`, `NetworkError`, `DiskSpaceError`
- **Konfiguracja checksums** (`src/setup/checksums.py`)
  - Słowniki: `VERSIONS`, `CHECKSUMS`, `URLS`, `SIZES`
- **Testy jednostkowe** (`tests/test_downloader.py`)
  - 20 testów pokrywających wszystkie scenariusze (100% pass)
  - Testy P0: sprawdzanie, checksum, network, disk space
  - Testy P1: pobieranie, retry, progress callback
  - Testy P2: resume download, cleanup temp files
- **Testy integracyjne** (`tests/test_downloader_integration.py`)
  - Podstawowa struktura (do rozbudowy po utworzeniu GitHub Release)

### Changed (Faza 2)
- **src/config.py** - Nowa lokalizacja zależności
  - `WHISPER_CPP_PATH` domyślnie: `~/Library/Application Support/Malinche/bin/whisper-cli`
  - `WHISPER_CPP_MODELS_DIR` domyślnie: `~/Library/Application Support/Malinche/models/`
  - Dodano `FFMPEG_PATH` dla bundlowanego ffmpeg
  - Backward compatibility z `~/whisper.cpp/` dla developerów
- **src/transcriber.py** - Zmiana `_check_whisper()`
  - Zamiast błędu - warning i zwrócenie False (UI pokazuje ekran pobierania)
  - Sprawdzanie nowej lokalizacji przed fallback do starej
- **src/menu_app.py** - Integracja z downloaderem
  - Metoda `_check_dependencies()` sprawdza zależności przy starcie (z opóźnieniem dla GUI)
  - Metoda `_download_dependencies()` pobiera z progress callback
  - Komunikaty błędów dla użytkownika (NetworkError, DiskSpaceError, DownloadError)
  - Usunięto debug.log zapisy (11 miejsc)
  - Zoptymalizowano progress callback (100x mniej wywołań)
- **src/setup/downloader.py** - Weryfikacja checksum i auto-repair
  - `check_all()` weryfikuje checksum dla wszystkich plików
  - `download_whisper()`, `download_ffmpeg()`, `download_model()` auto-repair przy błędnym checksum
  - Zoptymalizowano progress callback (tylko przy zmianie procentu, nie co 8KB)
- **HTTP client** - Zmiana z urllib na httpx
  - Lepsze wsparcie dla przekierowań GitHub
  - Bardziej nowoczesne API
  - Automatyczne follow_redirects

### Testing (Faza 2)
- ✅ Wszystkie testy jednostkowe przechodzą (20/20, 100% pass rate)
- ✅ Wszystkie testy integracyjne przechodzą (5/5, 100% pass rate)
- ✅ GitHub Release deps-v1.0.0 utworzony i przetestowany
- ✅ Pobieranie whisper-cli, ffmpeg i modelu small działa poprawnie
- ✅ Weryfikacja checksums działa
- ✅ Repo zmienione na publiczne dla FREE release
- ✅ **Testy manualne Fazy 2 zakończone** (2025-12-26)
  - ✅ TEST M1: Pierwsze uruchomienie - wszystkie zależności pobrane
  - ✅ TEST M2: Brak internetu - komunikat błędu działa poprawnie
  - ✅ TEST M3: Resume download - wznawianie pobierania działa
  - ✅ TEST M5: Uszkodzony plik - wykrycie i auto-repair działa
  - ⏳ TEST M4: Brak miejsca na dysku (opcjonalny, pominięty)
  - ⏳ TEST M6: Wolne połączenie (opcjonalny, pominięty)

### Technical Details
- Lokalizacja zależności: `~/Library/Application Support/Malinche/`
  - `bin/whisper-cli` (~10MB)
  - `bin/ffmpeg` (~15MB)
  - `models/ggml-small.bin` (~466MB)
- Timeouty: CHUNK_TIMEOUT=30s, TOTAL_TIMEOUT=1800s (30min)
- Max retries: 3 próby z exponential backoff
- Minimalne miejsce na dysku: 500MB

---

---

## [1.11.0] - 2025-12-17

### Added
- **Cursor Rules dla projektu** (`.cursor/rules/`)
  - `git-workflow.mdc` - Git Flow strategy, branch naming, commit format
  - `freemium-architecture.mdc` - FREE/PRO feature separation, feature flags
  - `project-overview.mdc` - kontekst projektu dla AI
  - `documentation-structure.mdc` - organizacja dokumentacji z cross-references
  - Zaktualizowany `python-rules.mdc` z zasadami v2.0.0

- **System cross-references między dokumentami**
  - Każdy dokument zawiera header z wersją i powiązanymi dokumentami
  - Mapa powiązań w `documentation-structure.mdc`
  - Zasady aktualizacji powiązanych dokumentów przy zmianach

- **Archiwum dokumentacji** (`Docs/archive/`, `archive/`)
  - Stara dokumentacja przeniesiona do archiwum
  - README w każdym archiwum z opisem zawartości

### Changed
- **README.md** - zaktualizowany dla v2.0.0
  - Generic recorder support (nie tylko Olympus LS-P1)
  - FREE/PRO feature table
  - Cross-references do dokumentacji
  - Roadmap v2.0.0 FREE i v2.1.0 PRO

- **Docs/ARCHITECTURE.md** - nowa architektura v2.0.0
  - Menu bar app jako główny interfejs
  - Universal volume detection
  - Feature flags dla freemium
  - PRO features architecture (license_manager, backend API)
  - Diagram z nową strukturą komponentów

- **Docs/API.md** - rozszerzona dokumentacja API
  - Nowe moduły: `markdown_generator`, `state_manager`, `menu_app`, `app_core`
  - PRO moduły: `summarizer`, `tagger`, `license_manager`
  - Zaktualizowane typy i przykłady użycia

- **Docs/FULL_DISK_ACCESS_SETUP.md** - generic volume support
  - Usunięte referencje do konkretnego recordera
  - First-Run Wizard mention
  - Zaktualizowane ścieżki

- **Docs/DEVELOPMENT.md** - zaktualizowany przewodnik
  - Poprawione ścieżki projektu
  - Git Flow workflow
  - Cross-references do innych dokumentów

- **Docs/TESTING-GUIDE.md** - dodane cross-references

### Removed
- `Docs/requirements.md` - redundantny (jest `requirements.txt`)
- `Docs/requirements-dev.md` - redundantny (jest `requirements-dev.txt`)

### Archived
- `Docs/INSTALLATION-GUIDE` → `Docs/archive/`
- `Docs/olympus-setup-cursor.md` → `Docs/archive/`
- `Docs/CURSOR-WORKFLOW.md` → `Docs/archive/`
- `MIGRATION_SUMMARY.md` → `archive/`
- `PROJECT-SUMMARY.md` → `archive/`
- `OBSIDIAN-SETUP.md` → `archive/`

### Documentation
- Wszystkie dokumenty zaktualizowane dla v2.0.0
- Spójna struktura cross-references
- Cursor rules z zasadami Git Flow i freemium

---

## [1.10.0] - 2025-12-12

### Added
- **Retranskrypcja plików** - nowa opcja w menu aplikacji pozwalająca na ponowne przetworzenie nagrania, które zostało nieprawidłowo transkrybowane
  - Submenu "Retranskrybuj plik..." z listą ostatnich 10 plików ze staging directory (`~/.olympus_transcriber/recordings/`)
  - Automatyczne usuwanie istniejącej transkrypcji (MD/TXT) przed ponownym przetworzeniem
  - Bezpieczne działanie dzięki ProcessLock - nie koliduje z automatyczną transkrypcją
  - Automatyczne odświeżanie listy plików co 10 sekund
  - Powiadomienia o statusie retranskrypcji (sukces/błąd)

## [1.9.1] - 2025-11-29

### Changed
- **Reduced false recorder detection triggers**: FSEvents monitor now filters out macOS system directories (`.Spotlight-V100`, `.fseventsd`, `.Trashes`) to prevent unnecessary workflow invocations when Spotlight indexes the recorder volume
- **Optimized notification behavior**: System notifications are now sent only when new audio files are found, eliminating spam when recorder is connected but has no new recordings

### Fixed
- Fixed repeated "Recorder detected" notifications triggered by macOS Spotlight indexing activity on the recorder volume
- Reduced log noise from system directory changes that don't represent actual recorder activity

## [1.9.0] - 2025-11-28

### Added
- **macOS Application Bundle (`Malinche.app`)** - Native `.app` wrapper for daemon execution
  - Resolves TCC (Transparency, Consent, and Control) issues with external drive access
  - Enables Full Disk Access configuration for daemon processes
  - Located at `~/Applications/Malinche.app`
- **Full Disk Access setup guide** (`Docs/FULL_DISK_ACCESS_SETUP.md`)
  - Step-by-step instructions for configuring macOS privacy settings
  - Troubleshooting guide for external drive access issues
  - Alternative manual Terminal launch instructions
- **Test script** (`scripts/test_app_wrapper.sh`) - Verifies app configuration and access
- **Project backlog** (`BACKLOG.md`) - Planned features and improvements roadmap:
  - Menu bar app with GUI controls for daemon management
  - Native launcher to replace Automator wrapper
  - Configurable Core ML / CPU mode with automatic fallback
  - Enhanced Core ML stability detection
- macOS native notifications for key events (recorder detected, files found, transcription complete)
- Helper script `scripts/restart_daemon.sh` for easy daemon management
- Improved LaunchAgent configuration (uses `python -m src.main` for better module resolution)
- `start_menu_app.command` + Login Item instructions for automatic tray app startup
- Enhanced error handling in `find_audio_files()`:
  - Specific handling for `OSError` (recorder unmounted during scan)
  - Specific handling for `PermissionError` (Full Disk Access issues)
  - Added `exc_info=True` to all error logs for better debugging
  - Scan completion logging with file count

### Changed
- **Architecture**: Daemon now runs as macOS application bundle instead of direct Python process
  - LaunchAgent updated to use `Malinche.app/Contents/MacOS/Malinche`
  - Login Items configuration now uses `.app` bundle
  - Resolves root cause: macOS TCC blocking `rglob()` access to `/Volumes` for launchd processes
- **Logging**: Reduced verbose debug logging in `find_audio_files()` method
  - Removed per-file debug spam, kept essential scan summary logs
- **Documentation**: Enhanced setup and deployment instructions
  - `QUICKSTART.md`: Added Full Disk Access as mandatory step 6, reorganized daemon setup with `.app` bundle option
  - `INSTALLATION-GUIDE`: Added Full Disk Access as Part 7, `.app` deployment as Part 8, LaunchAgent as Part 9
  - Clear distinction between `.app` bundle (recommended) vs LaunchAgent deployment methods
- Daemon now sends system notifications visible in Notification Center
- Makefile `reload-daemon` command now uses restart script

### Fixed
- **Critical**: Fixed daemon unable to detect files on external recorder (`/Volumes/LS-P1`)
  - Root cause: macOS TCC blocking access to external volumes for processes without Full Disk Access
  - Solution: Application bundle `.app` can be granted Full Disk Access, enabling file detection
- LaunchAgent module import issues by using `python -m` execution
- Improved error messages when recorder becomes unavailable during file scanning
- Better diagnostic information for Full Disk Access permission issues

## [1.8.2] - 2025-11-26

### Changed
- Improved code quality compliance with PEP 8 standards:
  - Added trailing newlines to all source files (`.py`, `.toml`, `.flake8`, `.sh`)
  - Ensures consistency with Black formatter and flake8 linter requirements
- CHANGELOG documentation standardized to English for better accessibility
  - Translated Polish sections (1.6.1, 1.7.0, 1.7.1) to English
  - Maintains consistent language throughout project documentation

### Technical Details
- All Python source files now end with proper newline character
- Configuration files (`.flake8`, `pyproject.toml`) comply with tool requirements
- Shell scripts follow Unix/POSIX standards for text files

## [1.8.1] - 2025-11-25

### Fixed
- Stabilized whisper.cpp fallback from Metal/Core ML to CPU mode by explicitly disabling backends (`WHISPER_COREML=0`, `GGML_METAL_DISABLE=1`), eliminating recurring transcription errors on older devices.
- Stale lock files (`transcriber.lock`) are now detected and automatically cleaned to prevent permanent `process_recorder()` blocking after previous process crashes.

### Testing
- Added unit tests securing CPU fallback configuration and stale lock file handling in `Transcriber`.

## [1.8.0] - 2025-11-25

### Added
- **Automatic LLM-based transcription tagging**:
  - Claude API generates up to 6 Obsidian tags for each new recording
  - Tags based on transcription, summary, and existing tag dictionary
  - Intelligent deduplication and tag normalization (Polish characters → ASCII)
  - Tags added to YAML frontmatter in format `tags: [tag1, tag2, ...]`
- **Tag indexing across entire vault** (`src/tag_index.py`):
  - `TagIndex` scans all `.md` files in `TRANSCRIBE_DIR`
  - Normalizes tags (removes Polish characters, spaces → hyphens)
  - Maintains `normalized → original` mapping to preserve consistency
  - Methods: `build_index()`, `existing_tags()`, `normalize_tag()`, `sanitize_tag_value()`
- **Tagger module** (`src/tagger.py`):
  - Abstract `BaseTagger` class for different LLM providers
  - `ClaudeTagger` implementation with Anthropic API support
  - Prompt construction with existing_tags support (up to 150 tags in prompt)
  - 10s timeout, graceful fallback on API error
  - `get_tagger()` function for easy instance creation
- **Retagging script for existing transcriptions** (`scripts/retag_existing_transcripts.py`):
  - Bulk tag addition to `.md` files without tags or with only `[transcription]`
  - YAML frontmatter parsing, transcript and summary extraction
  - Dry-run mode (preview changes without saving)
  - Detailed logging of changes and errors
  - Uses `TagIndex` and `ClaudeTagger`
- **Tagging configuration** in `src/config.py`:
  - `ENABLE_LLM_TAGGING` (bool, default: True)
  - `MAX_TAGS_PER_NOTE` (int, default: 6)
  - `MAX_EXISTING_TAGS_IN_PROMPT` (int, default: 150)
  - `MAX_TAGGER_SUMMARY_CHARS` (int, default: 3000)
  - `MAX_TAGGER_TRANSCRIPT_CHARS` (int, default: 1500)
- **Extended documentation** in `QUICKSTART.md`:
  - "LLM Tagging" section with configuration instructions
  - Retagging script usage
  - Tagging troubleshooting

### Changed
- **Transcriber workflow** (`src/transcriber.py`):
  - After summary generation, automatic tagging follows (if enabled)
  - `TagIndex` built at transcriber startup
  - Tags passed to `markdown_generator.create_markdown()`
  - Log: "🏷️  Generated N tags: [tag1, tag2, ...]"
- **MarkdownGenerator** (`src/markdown_generator.py`):
  - Method `create_markdown()` accepts optional parameter `tags: Optional[List[str]]`
  - Default `tags=["transcription"]` if not provided
  - Template changed: `tags: [{tags}]` instead of `tags: [transcription]`
  - Tags rendered as `tag1, tag2, tag3` in YAML frontmatter
- **Enhanced Metal/Core ML error detection** (`src/transcriber.py`):
  - New method `_should_retry_without_coreml()` for precise detection
  - Detects messages: `ggml_metal`, `MTLLibrar`, `Core ML`, `tensor API disabled`
  - Automatic retry with `use_coreml=False` flag when Metal error detected
  - Better separation of retry logic vs. fatal error

### Fixed
- **Tag deduplication**: TagIndex prevents duplicates with Polish characters (e.g., `organizacja` vs `organizacja`)
- **Graceful fallback**: If `ENABLE_SUMMARIZATION=False`, automatically disables `ENABLE_LLM_TAGGING`
- **Empty tag handling**: `sanitize_tag_value()` returns empty string instead of error for invalid tags

### Dependencies
- Existing dependency `anthropic>=0.8.0` reused for tagging (no new packages)

### Technical Details
- **Tagger abstraction**: `BaseTagger` enables easy integration of other providers (OpenAI, Ollama)
- **Tag normalization**: Polish characters (`ą`, `ć`, `ę`, ...) → ASCII (`a`, `c`, `e`, ...)
- **Tag sanitization**: Spaces → hyphens, removal of disallowed characters, lowercase
- **Thread-safe tag indexing**: Index built once at startup, used multiple times
- **Graceful degradation**: Missing API key → tagging disabled, log warning, workflow continues
- **Prompt engineering**:
  - Short fragments (3000 chars summary, 1500 chars transcript)
  - Existing tags in comma-separated list
  - JSON output `{"tags": ["tag1", "tag2", ...]}`
- **Retry logic**: API error → return empty list, doesn't interrupt transcription

### Testing
- New tests in `tests/test_tagger.py`:
  - `test_tagger_normalize_tag()` - Polish character normalization
  - `test_tagger_sanitize_tag()` - sanitization to Obsidian format
  - `test_tagger_generate_tags_mock()` - Claude API mocking
  - `test_tagger_api_error_graceful()` - API error handling
- New tests in `tests/test_tag_index.py`:
  - `test_tag_index_build()` - markdown file indexing
  - `test_tag_index_existing_tags()` - tag extraction from vault
- Extended tests in `tests/test_transcriber.py`:
  - `test_transcriber_with_tagging()` - tagging integration in workflow
  - `test_should_retry_without_coreml()` - Metal error detection
- Extended tests in `tests/test_markdown_generator.py`:
  - `test_create_markdown_with_tags()` - custom tags in YAML frontmatter

### Known Limitations
- Tagging requires `ENABLE_SUMMARIZATION=True` and valid Anthropic API key
- Script `retag_existing_transcripts.py` doesn't support files outside `TRANSCRIBE_DIR`
- Maximum 150 existing tags in prompt (context length limitation)
- 10s API timeout may be too short for very long transcriptions

## [1.7.1] - 2025-11-25

### Added
- File-based process lock to ensure only one transcriber instance runs at a time
- Troubleshooting documentation describing Metal error handling and manual lock file removal

### Fixed
- whisper.cpp fallback now detects `ggml_metal`/`MTLLibrar` messages and automatically switches to CPU,
  eliminating series of `Return code -6` errors
- Protected workflow against re-copying/re-processing when second instance starts in parallel

## [1.7.0] - 2025-11-25

### Added
- **Multi-computer support**: Configuration of `OLYMPUS_TRANSCRIBE_DIR` via environment variable
  - Allows application installation on multiple computers with different usernames
  - All instances can point to the same synchronized Obsidian vault directory
  - Prevents transcription duplication between computers
- **Transcription directory validation at startup**:
  - Logging of `TRANSCRIBE_DIR` source (from environment variable or default path)
  - Automatic directory creation if it doesn't exist
  - Warning if directory doesn't appear to be synchronized (iCloud/Obsidian)
  - Detailed error messages with configuration instructions
- Documentation for multi-computer configuration in `DEVELOPMENT.md` and `INSTALLATION-GUIDE`

### Changed
- `TRANSCRIBE_DIR` in `config.py`:
  - First checks environment variable `OLYMPUS_TRANSCRIBE_DIR`
  - If not set, uses default path based on `Path.home()` instead of hardcoded `/Users/radoslawtaraszka/...`
  - Path always resolved to absolute (`.resolve()`)
- Enhanced logging at application startup (`app_core.py`):
  - Displays source of `TRANSCRIBE_DIR` configuration
  - Shows whether directory exists and whether it was created
  - Warns about potential synchronization issues

### Fixed
- Issue with installation on multiple computers with different usernames
- Hardcoded user path in configuration

### Technical Details
- Mechanism checking `source: <audio_file>` in YAML frontmatter prevents duplicates between computers
- All instances must point to the same vault directory for full duplicate protection
- Backward compatibility: if `OLYMPUS_TRANSCRIBE_DIR` is not set, uses standard location

### Documentation
- Added section "Multi-Computer Setup: TRANSCRIBE_DIR Configuration" in `DEVELOPMENT.md`
- Extended "Configuration" section in `INSTALLATION-GUIDE` with multi-computer instructions
- Configuration examples via `.env` and `~/.zshrc`

## [1.6.1] - 2025-11-25

### Added
- Enhanced Claude prompt and fallback summary, now including **Key Points** section with priority emojis, *Quotes* block with thematic headings, and richer markdown formatting.
- New tests in `tests/test_summarizer.py` that verify the presence of new sections, emojis, and quotes in LLM responses.

### Changed
- Markdown filenames now use readable format `YY-MM-DD - Title.md`, preserve spaces and remove only forbidden characters for easier browsing in Finder/Obsidian.
- `_sanitize_filename()` preserves spaces and removes only disallowed characters, improving title readability.

### Fixed
- Made `Anthropic` client available at module level in `src/summarizer`, allowing tests to patch it without `AttributeError`.

## [1.6.0] - 2025-11-25

### Added
- **Local staging workflow** for robust transcription processing
  - Audio files are now copied to local staging directory before transcription
  - Staging directory: `~/.olympus_transcriber/recordings/` (configurable via `LOCAL_RECORDINGS_DIR`)
  - Transcription works on local copies, making process resilient to recorder unmounting
  - Original files on recorder remain untouched (never deleted or moved)
- **Improved batch failure handling**
  - `last_sync` timestamp is only updated when ALL files in batch succeed
  - Failed files remain in queue for retry on next sync
  - Prevents losing unprocessed files when batch has partial failures
- **Staging reuse optimization**
  - Existing staged copies are reused if size and mtime match
  - Reduces unnecessary file copying on repeated processing
- **Comprehensive staging tests**
  - Unit tests for staging functionality (`test_stage_audio_file_*`)
  - Integration tests for staging workflow (`test_process_recorder_staging_integration`)
  - Batch failure handling tests (`test_process_recorder_batch_*`)
- **End-to-end test scripts**
  - `test_staging_e2e.sh` - Full E2E test with recorder
  - `test_staging_e2e_wait.sh` - E2E test that waits for recorder connection

### Changed
- **Transcription workflow** now uses staging:
  1. Files are discovered on recorder
  2. Each file is copied to local staging directory (`_stage_audio_file()`)
  3. Transcription runs on staged copy (not original recorder file)
  4. Original files on recorder remain untouched
- **Batch processing logic**:
  - Tracks successes and failures separately (`processed_success`, `processed_failed`)
  - State file (`last_sync`) only updated if `processed_failed == 0`
  - Failed files will be retried on next recorder connection
- **Configuration**:
  - Added `LOCAL_RECORDINGS_DIR` configuration option (default: `~/.olympus_transcriber/recordings/`)
  - Staging directory is automatically created by `ensure_directories()`

### Fixed
- **Recorder unmounting during transcription**: System now handles unstable recorder mounting
  - Files are staged locally before processing
  - Transcription continues even if recorder unmounts mid-process
  - No more "input file not found" errors from unstable mounts
- **Lost files on batch failure**: Files that fail in a batch are no longer lost
  - `last_sync` not updated if any file fails
  - Failed files remain in queue for next sync attempt

### Technical Details
- Staging uses `shutil.copy2()` to preserve file metadata and mtime
- Staging directory structure mirrors recorder structure (same filenames)
- Error handling for staging failures (FileNotFoundError, OSError)
- Logging includes staging activity (DEBUG level: "📋 Staging file", "✓ Staged")

### Documentation
- Updated `ARCHITECTURE.md` with staging workflow description
- Updated `API.md` with `_stage_audio_file()` method documentation
- Updated `TESTING-GUIDE.md` with staging test instructions
- Updated `DEVELOPMENT.md` with staging workflow section and debugging tips

### Testing
- All staging-related unit tests pass (6/6)
- All transcriber tests pass (21/21)
- E2E tests confirm staging works correctly with real recorder
- Verified files remain on recorder after processing

## [1.5.2] - 2025-11-24

### Fixed
- **Notification spam**: Fixed repeated "Recorder wykryty" notifications on periodic checks
  - Notifications now only sent on first recorder detection
  - Periodic checks no longer trigger false "new connection" notifications
- **Unnecessary delays**: Removed 5-second post-mount rescan delay
  - System no longer waits and retries when no new files are found
  - Faster processing workflow

### Changed
- Added `recorder_was_notified` flag to track notification state
- `recorder_monitoring` flag now remains `True` while recorder is connected
- Improved state management for periodic check vs. mount event distinction

### Removed
- `POST_MOUNT_RESYNC_DELAY` configuration option (no longer needed)
- 5-second wait and retry logic after mount

## [1.5.1] - 2025-11-24

### Added
- macOS native notifications for recorder detection and transcription events
- `scripts/restart_daemon.sh` - convenient daemon restart script

### Changed
- LaunchAgent now uses `python -m src.main` instead of direct script execution
- Improved daemon reliability with proper module path resolution

### Fixed
- Fixed `ModuleNotFoundError: No module named 'src'` in LaunchAgent mode

## [1.5.0] - 2025-11-20

### Added
- macOS menu bar application (tray app) for GUI-based operation
- Thread-safe application state management (`AppState`, `AppStatus`)
- Python API for state management (`state_manager.py`)
  - `reset_state()` - Reset transcription memory to specific date
  - `get_last_sync_time()` - Read last sync timestamp
  - `save_sync_time()` - Save current sync timestamp
- Real-time status display in menu bar (idle, scanning, transcribing, error)
- Menu actions:
  - Open logs in default editor
  - Reset memory from GUI
  - Graceful shutdown
- Status updates every 2 seconds in tray app
- Automatic state updates during transcription workflow

### Changed
- Refactored `OlympusTranscriber` class from `main.py` to `app_core.py`
- `Transcriber` now supports state update callbacks
- State management functions moved to dedicated `state_manager.py` module
- `main.py` now imports and uses `app_core.OlympusTranscriber`

### Dependencies
- Added `rumps>=0.4.0` for macOS menu bar interface

### Technical Details
- Menu app runs `OlympusTranscriber` in background thread
- State updates are thread-safe using locks
- State manager creates automatic backups before reset
- Menu app provides notifications for user actions

## [1.4.1] - 2025-11-20

### Added
- Helper script to reset transcription memory state:
  - `scripts/reset_recorder_memory.sh`
  - Backs up existing `~/.olympus_transcriber_state.json`
  - Allows setting `last_sync` to a custom date (default: 2025-11-18)
- Helper script to run transcriber with fresh memory:
  - `scripts/run_with_fresh_memory.sh`
  - Resets state and starts `python -m src.main` in one command
- Documentation for memory reset workflow in `README.md`

### Changed
- Recommended development workflow to use helper scripts when
  reprocessing historical recordings

## [1.4.0] - 2025-11-20

### Added
- Markdown document generation with YAML frontmatter for transcriptions
- AI-powered summarization using Claude API (Anthropic)
- Automatic title generation from transcript summaries
- Audio metadata extraction (recording date, duration) using mutagen
- Post-processing pipeline: TXT → Summary → Markdown
- Configurable LLM provider system (Claude, with extensibility for Ollama/OpenAI)
- Safe filename generation with Polish character normalization
- Option to delete temporary TXT files after MD creation (`DELETE_TEMP_TXT`)

### Changed
- Transcription output format changed from `.txt` to `.md` (markdown)
- File naming: now uses `YYYY-MM-DD_Title.md` format based on summary
- Post-processing step added after whisper.cpp transcription

### Configuration
- New config options:
  - `ENABLE_SUMMARIZATION`: Enable/disable AI summarization (default: True)
  - `LLM_PROVIDER`: LLM provider name (default: "claude")
  - `LLM_MODEL`: Model name (default: "claude-3-haiku-20240307")
  - `LLM_API_KEY`: API key (loaded from `ANTHROPIC_API_KEY` env var)
  - `SUMMARY_MAX_WORDS`: Maximum words in summary (default: 200)
  - `TITLE_MAX_LENGTH`: Maximum title length (default: 60)
  - `DELETE_TEMP_TXT`: Delete temporary TXT files (default: True)
  - `MD_TEMPLATE`: Markdown template with YAML frontmatter

### Dependencies
- Added `anthropic>=0.8.0` for Claude API integration
- Added `mutagen>=1.47.0` for audio metadata extraction

### Technical Details
- Summarizer uses abstract base class for easy provider switching
- Graceful fallback when API unavailable (uses filename-based title)
- Timeout protection for API calls (30 seconds)
- Error handling ensures transcription continues even if post-processing fails

### Known Limitations
- Requires Anthropic API key for summarization (set `ANTHROPIC_API_KEY` env var)
- Summarization disabled if API key not found (falls back to basic title)
- Ollama provider not yet implemented (placeholder for future)

## [1.3.0] - 2025-11-20

### Added
- whisper.cpp integration with Core ML support for Apple Silicon
- Automated installation script for whisper.cpp (scripts/install_whisper_cpp.sh)
- Core ML model detection and automatic GPU acceleration on M1/M2/M3 Macs
- CPU fallback when Core ML fails
- Configuration parameters for whisper.cpp paths (WHISPER_CPP_PATH, WHISPER_CPP_MODELS_DIR)

### Changed
- Replaced openai-whisper Python library with whisper.cpp native binary
- Changed default model from "medium" to "small" for 3-4x speed improvement
- Changed default device from auto-detect to "cpu" (whisper.cpp handles Core ML internally)
- Simplified transcription logic - removed MPS-specific error handling
- Updated setup.sh to check for whisper.cpp installation

### Removed
- openai-whisper Python dependency
- PyTorch dependency (no longer needed)
- MPS backend auto-detection logic
- MPS error checking method

### Performance
- 3-4x faster transcription with "small" model vs "medium"
- Up to 10x faster with Core ML acceleration on Apple Silicon
- Reduced memory footprint (no PyTorch runtime)

## [1.2.1] - 2025-11-19

### Fixed
- Automatic fallback to CPU when MPS device fails due to PyTorch sparse tensor incompatibility
- Transcription failures on Apple Silicon caused by MPS backend limitations

### Changed
- Enhanced error detection to identify MPS compatibility issues
- Improved logging to indicate when CPU fallback is used

## [1.2.0] - 2025-11-19

### Added
- GPU acceleration support for Apple Silicon (MPS) and NVIDIA (CUDA)
- Automatic GPU detection and configuration
- macOS metadata file filtering (._* and .DS_Store files)
- GPU availability logging during startup

### Changed
- Increased transcription timeout from 30 to 60 minutes for long recordings
- Enhanced file filtering to skip system files before transcription

### Fixed
- Prevented transcription attempts on macOS resource fork files (._* files)
- Eliminated ffmpeg errors from invalid metadata files

## [1.1.0] - 2025-11-19

### Added
- OpenAI Whisper CLI integration for command-line transcription
- Support for Polish and English language transcription
- Large model support for highest accuracy
- Local, free transcription (no API key required)
- Configurable Whisper model size (tiny, base, small, medium, large)
- Configurable language setting (Polish default, English, or auto-detect)

### Fixed
- FSEvents callback signature causing TypeError in file monitoring
- Transcription hanging due to MacWhisper GUI dependency

### Changed
- Replaced MacWhisper GUI with Whisper CLI
- Updated configuration to use Whisper-specific settings (WHISPER_MODEL, WHISPER_LANGUAGE)
- Updated transcriber to use `shutil.which()` for Whisper detection

### Removed
- MacWhisper dependency and MACWHISPER_PATHS configuration

## [1.0.0] - 2025-11-19

### Added
- Initial release of Malinche
- Automatic detection of Olympus LS-P1 recorder connection
- FSEvents-based monitoring for instant recorder detection
- Periodic fallback checker (30-second interval)
- MacWhisper integration for audio transcription
- Support for multiple audio formats (MP3, WAV, M4A, WMA)
- State management to track last sync time
- Prevents re-transcription of already processed files
- Comprehensive logging system
  - Application log: `~/Library/Logs/olympus_transcriber.log`
  - LaunchAgent stdout: `/tmp/olympus-transcriber-out.log`
  - LaunchAgent stderr: `/tmp/olympus-transcriber-err.log`
- LaunchAgent for automatic startup
- Graceful shutdown on SIGINT/SIGTERM
- 30-minute timeout protection for transcriptions
- Debouncing to prevent multiple rapid triggers
- Thread-safe transcription tracking
- Comprehensive test suite
  - Unit tests for all modules
  - Mock-based testing for external dependencies
  - Fixtures for common test scenarios
- Development tooling
  - Black code formatter configuration
  - Flake8 linter configuration
  - MyPy type checker configuration
  - isort import sorter configuration
  - VS Code/Cursor debug configuration
  - Cursor AI coding rules
- Complete documentation
  - README with quick start guide
  - ARCHITECTURE.md with system design
  - DEVELOPMENT.md with development guide
  - INSTALLATION-GUIDE with step-by-step setup
  - CURSOR-WORKFLOW.md for Cursor IDE users
- Automated setup script (`setup.sh`)
  - Creates necessary directories
  - Generates LaunchAgent plist
  - Loads daemon automatically
  - Validates environment

### Configuration
- Configurable recorder names (LS-P1, OLYMPUS, RECORDER)
- Configurable transcription directory (default: `~/Documents/Transcriptions`)
- Configurable MacWhisper paths
- Configurable timeouts and intervals
- Configurable audio file extensions

### Technical Details
- Python 3.8+ compatible
- macOS-native FSEvents API integration
- Async-ready architecture (threading-based)
- Zero-polling design for efficiency
- Graceful error handling
- Type hints throughout codebase
- PEP 8 compliant code style

### Security
- No credentials stored
- Local-only processing
- User-level LaunchAgent (not root)
- No network communication required

### Known Limitations
- macOS only (uses FSEvents)
- Requires MacWhisper installation
- Single recorder at a time
- Sequential transcription processing

---

## [Unreleased - Future]

### Planned Features
- Obsidian integration for automatic note creation
- N8N webhook notifications
- Web UI for management and monitoring
- SQLite database for transcription history
- Multiple recorder support
- Parallel transcription processing
- Cloud storage integration
- Custom transcription models
- Audio preprocessing options
- Batch transcription management

### Planned Improvements
- Async/await refactoring
- Progress reporting for long transcriptions
- Email notifications on completion
- Automatic error recovery
- Rate limiting for system resources
- Compression of old transcriptions
- Automatic backup to cloud
- Enhanced logging with rotation
- Performance metrics collection
- Health check endpoint

---

## Version History

- **1.14.0** (2025-12-29) - Faza 4: Pakowanie z py2app, bundle .app gotowy do dystrybucji
- **1.13.0** (2025-12-29) - Faza 3: First-run wizard z konfiguracją
- **1.12.0** (2025-12-26) - Faza 2: System pobierania whisper.cpp/modeli on-demand
- **1.11.0** (2025-12-17) - Documentation v2.0.0, Cursor rules, Git Flow strategy
- **1.10.0** (2025-12-12) - File retranscription feature with menu app integration
- **1.9.1** (2025-11-29) - Reduced false recorder detection triggers, optimized notification behavior
- **1.9.0** (2025-11-28) - macOS application bundle, Full Disk Access setup, enhanced error handling, project backlog
- **1.8.2** (2025-11-26) - Code quality improvements, PEP 8 compliance, CHANGELOG standardization
- **1.8.1** (2025-11-25) - Stabilized whisper.cpp CPU fallback, stale lock file detection
- **1.8.0** (2025-11-25) - LLM-based automatic tagging, tag indexing, retag script
- **1.7.1** (2025-11-25) - Process lock + extended Metal → CPU fallback
- **1.7.0** (2025-11-25) - Multi-computer support with OLYMPUS_TRANSCRIBE_DIR configuration
- **1.6.1** (2025-11-25) - Enhanced markdown formatting and Claude prompts
- **1.6.0** (2025-11-25) - Local staging workflow for robust transcription, improved batch failure handling
- **1.5.2** (2025-11-24) - Fixed notification spam and removed unnecessary delays
- **1.5.1** (2025-11-24) - Native notifications and daemon improvements
- **1.5.0** (2025-11-20) - macOS menu bar app with real-time status and GUI controls
- **1.4.1** (2025-11-20) - Helper scripts for memory reset workflow
- **1.4.0** (2025-11-20) - Markdown output with Claude AI summarization
- **1.3.0** (2025-11-20) - whisper.cpp integration with Core ML support
- **1.2.1** (2025-11-19) - MPS compatibility fix with automatic CPU fallback
- **1.2.0** (2025-11-19) - GPU acceleration, macOS metadata filtering, 60-min timeout
- **1.1.0** (2025-11-19) - Whisper CLI integration, FSEvents bug fix
- **1.0.0** (2025-11-19) - Initial release

## Upgrade Guide

### From Development to 1.0.0

If you were using a development version:

1. Backup your state file:

   ```bash
   cp ~/.olympus_transcriber_state.json ~/.olympus_transcriber_state.json.backup
   ```

2. Unload old LaunchAgent:

   ```bash
   launchctl unload ~/Library/LaunchAgents/com.user.olympus-transcriber.plist
   ```

3. Pull latest code:

   ```bash
   cd ~/CODE/Olympus_transcription
   git pull origin main
   ```

4. Update dependencies:

   ```bash
   source venv/bin/activate
   pip install --upgrade pip
   pip install -r requirements.txt
   ```

5. Run setup script:

   ```bash
   chmod +x setup.sh
   ./setup.sh
   ```

6. Verify installation:

   ```bash
   launchctl list | grep olympus-transcriber
   tail -f ~/Library/Logs/olympus_transcriber.log
   ```

## Support

For issues, questions, or contributions:
- Check documentation in `Docs/` directory
- Review logs for errors
- Open an issue on GitHub
- Read `DEVELOPMENT.md` for development setup

## License

MIT License - See LICENSE file for details

## Credits

Developed by Radoslaw Taraszka

Uses:
- whisper.cpp for transcription
- Claude API (Anthropic) for AI summarization
- FSEvents for file system monitoring
- Python standard library
