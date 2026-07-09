# STATE — Malinche/Timshel

Data: 2026-07-09 · Faza: design
Re-entry (wypełnia Radek przy powrocie): ___ min

## Kolejna faza: redesign UI (design → kod)

Handoff Claude Design `Timshel.zip` (`design_handoff_app_redesign_2026_07`) = hi-fi
spec redesignu CAŁEJ apki: jedno okno „Konstelacja" + 2 tryby (Przegląd/Pytanie),
ask-bar overlay, wizard, ustawienia, feedback. 9 ekranów A–I + spec.css + tokens.css
+ sigile (Core Graphics) + changelog beta.17→redesign. Cel: **port natywny AppKit
(u nas PyObjC `src/ui/`), NIE kopiowanie HTML.** Fonty → systemowe SF Pro. 3 akcenty
egzekwowane twardo: terakota #C24010 (akcja) · jadeit #46B17E (lokalne) · złoto #D6B033
(insight/chmura). Ikona idzie w NOWY kierunek: mesh sygnet (fala 6 słupków) na kaflu
#141414 (obecna = kremowy waveform — do wymiany).
Sekwencja: **(1) paczka assetów ✅ → (3) PORT OKNA ✅ UKOŃCZONY (2026-07-09) → (2) dalsze testy [NASTĘPNE].**
Port dowieziony wg kryteriów akceptacji 08-cele: rampa SF Pro (typography.py, korekty
Claude Design) · ekran A (teza/eyebrow/chipy-kropka/filtr „Nowe ⌄" NSMenu/stopka „1 z N")
· B (pytanie=tytuł, wiersze wyników, przełącznik B5, BEZ stopki) · C (ask-overlay ⌃⌥Space
+ ⌕ accessory) · E (pasek handoffu: ⋯-menu, „✦ do chmury", split-CTA, slide-in 150ms) ·
D (btn-syn/btn-terra) · F (sygnet w pasku menu) · sigile CG 1:1 (§06) · motion §04
(reduce-motion) · hairline'y §05 · H3 sekcja Prywatność (jadeit/złoto).
Odchylenia ŚWIADOME (nie hack): wizard G 2-krokowy koliduje z obowiązkowym downloadem
silnika (zostaje 7-krokowy); ustawienia trzymają EN + obecne IA (pełny PL-pass i 3
zakładki = follow-up); historia zapytań w szynie = nowy storage (follow-up).
Po drodze: review jakościowy (visual-identity+maker) — root cause lineHeightMultiple
naprawiony w rampie; „Zapytaj o to" wycięte z karty (nie ma go w A1).
Assety: handoff wpięty `design-system/app-redesign-2026-07/`; tokeny w `src/ui/theme.py`
(rodziny akcentów + MESH_STOPS + SIGIL_BARS); nowa ikona (mesh sygnet na #141414,
`assets/gen_icon.py`) — Radek zatwierdził kierunek; znak menu-bar mono
(`assets/menu_bar/sigil.png` +@2x, wpięcie do menu_app = faza 3). Tester DMG
przebudowany z nową ikoną. Fonty handoffu NIE wdrożone (→ SF Pro).
NIE ruszać w assetach: fonty Neue Haas/Montreal (mapują na SF Pro); port ekranów A–I
(osobna faza kodu po testach).

## Ostatnia decyzja + dlaczego

**Tester Build ZMERGOWANY (PR #66 → `feat/magic-insights-prototype`, merge
`4beac40`).** 7 faz + 2 tury multi-agent code review (7 realnych bugów
znalezionych i naprawionych, w tym KRYTYCZNY: `tester_mode` nigdy się nie
włączał) + szerokie testy ładujące realne pliki (txt/md/vtt E2E + matryca audio
z realnym whisperem). 1038 szybkich testów + mypy zielone; audio e2e zielone.
- **Rename Malinche→Timshel** pełny (bundle `com.timshel.app`, UI, klasy,
  `~/Library/Application Support/Timshel`, sidecar `.timshel`, `Timshel Digests`,
  log, logger, env, build/DMG). Migracja przy 1. starcie (`bootstrap.py`, krok 0):
  app-support całościowo (bez re-downloadu) albo non-destructive merge; sidecary
  vaulta; usunięcie starego LaunchAgent; idempotentne. **Zweryfikowane na żywych
  danych Radka** (config+klucz+modele+vault przeniesione nienaruszone). Back-compat
  za guard testem `tests/test_rename_guard.py`.
- **tester_mode** trwały (UserSettings→`__post_init__`, przeżywa `reload_config`) →
  knoby H1 (verdict, metrics, kanały, Opus) dla daemona i menu. Baking:
  plist `TimshelTesterBuild` + adopcja przy 1. starcie; `make build-app-tester`/
  `release-tester`. Build zweryfikowany: `dist/Timshel.app`, plist flag=true.
- **Sędzia aliasów w prod** (transcriber): judge → 1 correction retry; model
  poprawia, nie podmiana kodu; ocalały miss logowany. Wspólne helpery
  (vocabulary/summarizer) = parytet z resummarize.
- **Import transcripts…** (menu, multi-select txt/md/vtt → seed) + **Export
  feedback** (menu → zip signal/metrics+digesty na Desktop).
- Docs: `TESTER-ONBOARDING.md`, `H1-TEST-PROTOCOL.md`, `TESTER-BUILD-VERIFY.md`.

## Następny krok

1. ~~review + merge PR #66~~ — ZROBIONE (merge `4beac40`).
2. **Weryfikacja buildu na czystym środowisku** wg
   `Docs/TESTER-BUILD-VERIFY.md` (Gatekeeper right-click→Open, wizard, FDA+restart,
   700 MB download, import, digest, export) — to jedyne kroki niemożliwe do
   zautomatyzowania tu.
3. **Manualne poza kodem:** klucze Anthropic per-tester + spend limit; potwierdzić
   że `checksums.py` release URL-e (`radektar/malinche`) rozwiązują się przez
   redirect po rename repo; lista 3–5 testerów P1 z gęstym vaultem.
4. **Meeting-ingest v2 na bramce** (2026-07-09): plan `Docs/future/meeting-ingest-plan.md`
   (konektory Zoom/Teams/drop-folder, transcript-first, reguła Stanowisk zamiast
   diaryzacji; Meet OAuth po popycie). Strategia rozszerzeń: vault →
   `research/2026-07-09 - Strategia rozszerzeń - synteza`. Czeka na "ok" przed kodem.
5. Zebranie sygnału H1 (N=3–5): rytuał tygodniowy rate→export ×3 tyg → `signal-report`.
GO: ≥3 warte akcji **połączenia dowolnego typu**/tydz., w tym ≥1 nieoczywiste.
Kill: import daje szum zamiast wartych akcji połączeń → import = onboarding FREE, nie feeder PRO.

## Otwarte ryzyka

- Stanowiska mogą nie dowieźć kontradykcji w H1 (kill-trigger zdefiniowany).
- Haiku bywa za hojny w Stanowiskach (procesy/koncepty jako encje) — szum,
  nie bloker; docelowe lekarstwo to structured-output (B2).
- Słownik uczy się tylko z wikilinków/encji — aliasy przekrętów wymagają
  ręcznego wpisu w vocabulary.json do czasu B1.
- P3 wdrożone (PR #64) POZA aliasem (patrz Ostatnia decyzja). Dług mypy:
  25 modułów zgrandfather'owanych (`ignore_errors` w pyproject) — do burn-down
  moduł po module, start od config.config/transcriber/vocabulary.
- Pełny rebuild okna Insights na każdy klik — świadomie NIE ruszony w P3-B
  (to okno oceny H1; przebudowa dopiero po H1).

## Nie ruszać (świadomie odłożone)

- Wspólny executor ciężkiej pracy + budżet wątków — po sygnale z H1.
- Pełny rebuild okna Insights — po H1 (okno oceny).
- Ciała forced-tool (synthesis/verdict/recall) → wspólny helper — dług, nie teraz.
- Strojenie H3 / podnoszenie MAX_SYNTHESIS_NOTES — dopiero z sygnałem z H1.
- B1 entity pre-pass z auto-nauką aliasów (tryb ustalony: auto + log).
- B2 structured-output summarizera (forced tool) — jeśli Haiku dryfuje w prod.
- mDeBERTa/NLI dla kanału sprzeczności.
- Kanonizacja pola `title:` w frontmatterze starych notatek.
- **Notaryzacja / Developer ID** — tester DMG zostaje ad-hoc (right-click→Open);
  Developer ID dopiero przed waitlistą, nie przed małą grupą.
- **DONE (PR #66):** alias-canonicalizacja w prod (judge/retry) · rename Malinche→Timshel.

## Kontekst dla nowej sesji

Branch: **`main`** (PR #67 zmergowany 2026-07-09 — tester build + port UI scalone
do `main`, branch roboczy usunięty; pracuj od czystego `main`) ·
testy: **1038 pass** (`./venv312/bin/python -m pytest tests/ -m "not slow" --ignore=tests/integration`);
mypy zielony (`./venv312/bin/python -m mypy src/`, 93 pliki).
Pakiety: PR #62 (P1+P2) + PR #64 (P3) + PR #65 (ingest) + PR #66 (tester build) +
**PR #67 (merge do main + port UI)**, sesja "[Timshel - APP]" 2026-07-08/09.
UWAGA: nazwy zmienione — app-support `Timshel`, sidecar `.timshel`, log `timshel.log`,
env `TIMSHEL_TRANSCRIBE_DIR`, klasy `TimshelTranscriber/TimshelMenuApp`.
Nowe pliki: `src/feedback_export.py`; testy `test_rename_guard`, `test_tester_mode`,
`test_alias_judge`, `test_import_transcripts_menu`, `test_feedback_export`.
Ingest: `src/ingest/` (parsing) + `Transcriber.import_text_file` + `_finalize_note`
(wspólny tail audio/import) + `make import-text SRC=<path>`. Plan:
`Docs/future/ingest-plan.md`. Fast-follow: PDF, JSON platform, diaryzacja mówców.
Stan szczegółowy: Obsidian → [[Timshel — Project State (2026-07-07) — korpus v3, słownik, start H1]].
Vault-touching komendy (recall-eval, magic-digest, resummarize) wymagają
Full Disk Access; ta sesja Claude miała dostęp przez działający terminal Radka.
