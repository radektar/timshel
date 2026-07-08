# STATE — Malinche/Timshel

Data: 2026-07-08 · Faza: test
Re-entry (wypełnia Radek przy powrocie): ___ min

## Ostatnia decyzja + dlaczego

Głęboki code review (8 kątów + weryfikacja adwersaryjna) → pakiet naprawczy
P1+P2 wdrożony i zmergowany (PR #62): integralność danych (readline-wedge,
adopcja TXT po sidecarze, kolizje nazw notatek, klamry, dialog wolumenu) +
punktowa współbieżność (locki w imporcie, kill whispera przy quit, lock na
singletonie recall, cap wątków ONNX, handoff poza main thread). Zakres ustalony
świadomie: BEZ przebudowy na wspólny executor — żeby nie destabilizować
instrumentu H1 w trakcie pomiaru. H1 pozostaje jedyną metryką decyzyjną.

## Następny krok

1. Radek: smoke manualny pakietu (import podczas auto-transkrypcji → alert
   busy; quit w trakcie → `pgrep -f whisper-cli` pusty).
2. Radek: ocena digestu `2026-07-07 Synthesis.md` w oknie Insights →
   `make magic-digest` co tydzień ×3 → `make signal-report`.
GO: ≥3 insighty warte akcji/tydz., w tym ≥1 nieoczywista kontradykcja.
Kill: kontradykcje puste mimo parsera Stanowisk → stance-signal = ślepa uliczka.

## Otwarte ryzyka

- Stanowiska mogą nie dowieźć kontradykcji w H1 (kill-trigger zdefiniowany).
- Haiku bywa za hojny w Stanowiskach (procesy/koncepty jako encje) — szum,
  nie bloker; docelowe lekarstwo to structured-output (B2).
- Słownik uczy się tylko z wikilinków/encji — aliasy przekrętów wymagają
  ręcznego wpisu w vocabulary.json do czasu B1.
- Review zostawił pakiet P3 nietknięty (świadomie): bramka mypy martwa
  (python_version=3.8 odrzucane przez mypy), reguła importów w CLAUDE.md
  sprzeczna z kodem, UI-perf (ikona co 2 s, pełny rebuild okna, signal.jsonl
  w całości przy otwarciu), scaffold Anthropic ×5, alias-judge niepodpięty
  w produkcji. Lista w planie: `~/.claude/plans/toasty-sprouting-brooks.md`.

## Nie ruszać (świadomie odłożone)

- Wspólny executor ciężkiej pracy + budżet wątków — po sygnale z H1.
- P3 (mypy/CLAUDE.md, UI-perf, LLM-helper) — po H1, osobny pakiet.
- Strojenie H3 / podnoszenie MAX_SYNTHESIS_NOTES — dopiero z sygnałem z H1.
- B1 entity pre-pass z auto-nauką aliasów (tryb ustalony: auto + log).
- B2 structured-output summarizera (forced tool) — jeśli Haiku dryfuje w prod.
- mDeBERTa/NLI dla kanału sprzeczności.
- Kanonizacja pola `title:` w frontmatterze starych notatek.
- Rename-pass Malinche→Timshel w kodzie/UI (osobny pakiet wg strategii v2.0).

## Kontekst dla nowej sesji

Branch: `feat/magic-insights-prototype` · testy: 977 pass
(`./venv312/bin/python -m pytest tests/ -m "not slow" --ignore=tests/integration`).
Pakiet naprawczy: PR #62 (9 commitów `0ee2dce…801741b`), pełny raport review
w sesji "[Timshel - APP]" 2026-07-08.
Stan szczegółowy: Obsidian → [[Timshel — Project State (2026-07-07) — korpus v3, słownik, start H1]].
Vault-touching komendy (recall-eval, magic-digest, resummarize) wymagają
Full Disk Access; ta sesja Claude miała dostęp przez działający terminal Radka.
