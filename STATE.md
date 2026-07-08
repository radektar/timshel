# STATE — Malinche/Timshel

Data: 2026-07-08 · Faza: test
Re-entry (wypełnia Radek przy powrocie): ___ min

## Ostatnia decyzja + dlaczego

Głęboki code review (8 kątów + weryfikacja adwersaryjna) → wdrożone i zmergowane:
- **P1+P2** (PR #62): integralność danych + punktowa współbieżność. Bez
  przebudowy na executor (odłożona) — nie destabilizować H1.
- **P3** (PR #64): TYLKO zmiany behawioralnie neutralne — bramka mypy realnie
  działa (3.12 + baseline 25 modułów), UI-perf (cache triage/tokenize, guard
  ikony/submenu, tail log viewera), wspólny `build_anthropic_client` (5→1),
  poprawka reguły import-ów w CLAUDE.md.

**Odłożone świadomie z P3 (wymaga decyzji Radka):** alias-canonicalizacja w
produkcji. Deterministyczna podmiana cofałaby decyzję „model owns
canonicalization"; judge/retry w prod dokłada 2. wywołanie Haiku na ścieżce
FREE. Każda wersja zmienia output podsumowań = instrument H1 i sąsiaduje z
odłożonym B1. → post-H1, w jednym pakiecie z B1/B2.

## Następny krok

Przygotowanie małej grupy H1 (GTM krok 1, „3–5 testerów P1"):
1. **Wpiąć sędziego aliasów do produkcji** (decyzja podjęta) — parytet prod =
   migracja PRZED buildem testera. To sędzia (find_alias_hits → correction →
   retry), NIE deterministyczna podmiana; koszt = 2. wywołanie Haiku tylko na
   missie, na kluczu usera. Uwaga GTM: dla zimnych testerów z pustym słownikiem
   odpala rzadko — realny lewar to dobór testerów z gęstym vaultem, nie sędzia.
2. **Import transkryptów** — DOWIEZIONY (PR #65): `make import-text SRC=<path>`;
   gasi cold-start (seed vaulta) + bypass Meet/Zoom przez .vtt. Użyj do
   zaseedowania testerów z materiałem pierwszoosobowym.
3. Radek: ocena digestu `2026-07-07` → `make magic-digest` ×3 tyg → `make signal-report`.
GO: ≥3 warte akcji **połączenia dowolnego typu**/tydz. (skorygowane: nie tylko
kontradykcje — cross-source linki też liczą), w tym ≥1 nieoczywiste.
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
- Alias-canonicalizacja w produkcji (deterministyczna LUB judge/retry) — zmienia
  instrument H1; do pakietu post-H1 z B1/B2.
- Pełny rebuild okna Insights — po H1 (okno oceny).
- Ciała forced-tool (synthesis/verdict/recall) → wspólny helper — dług, nie teraz.
- Strojenie H3 / podnoszenie MAX_SYNTHESIS_NOTES — dopiero z sygnałem z H1.
- B1 entity pre-pass z auto-nauką aliasów (tryb ustalony: auto + log).
- B2 structured-output summarizera (forced tool) — jeśli Haiku dryfuje w prod.
- mDeBERTa/NLI dla kanału sprzeczności.
- Kanonizacja pola `title:` w frontmatterze starych notatek.
- Rename-pass Malinche→Timshel w kodzie/UI (osobny pakiet wg strategii v2.0).

## Kontekst dla nowej sesji

Branch: `feat/magic-insights-prototype` · testy: 1002 pass
(`./venv312/bin/python -m pytest tests/ -m "not slow" --ignore=tests/integration`);
mypy zielony (`./venv312/bin/python -m mypy src/`, 92 pliki).
Pakiety: PR #62 (P1+P2) + PR #64 (P3) + PR #65 (ingest txt/md/vtt),
sesja "[Timshel - APP]" 2026-07-08.
Ingest: `src/ingest/` (parsing) + `Transcriber.import_text_file` + `_finalize_note`
(wspólny tail audio/import) + `make import-text SRC=<path>`. Plan:
`Docs/future/ingest-plan.md`. Fast-follow: PDF, JSON platform, diaryzacja mówców.
Stan szczegółowy: Obsidian → [[Timshel — Project State (2026-07-07) — korpus v3, słownik, start H1]].
Vault-touching komendy (recall-eval, magic-digest, resummarize) wymagają
Full Disk Access; ta sesja Claude miała dostęp przez działający terminal Radka.
