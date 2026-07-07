# STATE — Malinche/Timshel

Data: 2026-07-07 · Faza: test
Re-entry (wypełnia Radek przy powrocie): ___ min

## Ostatnia decyzja + dlaczego

H3 (recall preselekcji) przestaje być metryką decyzyjną — wąskie gardło to
budżet 25 notatek (wszystkie missy RANKED-BUT-CUT, 0 never-found), a metryka
jest ślepa na wartość migracji v3 (kanonizacja, Stanowiska). Zastępuje ją H1
(desire-test na realnych digestach). Kanonizacja nazw przez MODEL, nie kod —
system ma się uczyć nowych wariantów; kod tylko sędziuje (alias-miss + retry).
Podsumowania produkcyjne na Haiku (cost model wymaga; Opus 50× drożej).

## Następny krok

Radek: ocena digestu `2026-07-07 Synthesis.md` w oknie Insights →
`make magic-digest` co tydzień ×3 → `make signal-report`.
GO: ≥3 insighty warte akcji/tydz., w tym ≥1 nieoczywista kontradykcja.
Kill: kontradykcje puste mimo parsera Stanowisk → stance-signal = ślepa uliczka.

## Otwarte ryzyka

- Stanowiska mogą nie dowieźć kontradykcji w H1 (kill-trigger zdefiniowany).
- Haiku bywa za hojny w Stanowiskach (procesy/koncepty jako encje) — szum,
  nie bloker; docelowe lekarstwo to structured-output (B2).
- Słownik uczy się tylko z wikilinków/encji — aliasy przekrętów wymagają
  ręcznego wpisu w vocabulary.json do czasu B1.

## Nie ruszać (świadomie odłożone)

- Strojenie H3 / podnoszenie MAX_SYNTHESIS_NOTES — dopiero z sygnałem z H1.
- B1 entity pre-pass z auto-nauką aliasów (tryb ustalony: auto + log).
- B2 structured-output summarizera (forced tool) — jeśli Haiku dryfuje w prod.
- mDeBERTa/NLI dla kanału sprzeczności.
- Kanonizacja pola `title:` w frontmatterze starych notatek.
- Rename-pass Malinche→Timshel w kodzie/UI (osobny pakiet wg strategii v2.0).

## Kontekst dla nowej sesji

Branch: `feat/magic-insights-prototype` · testy: 956 pass
(`./venv312/bin/python -m pytest tests/ -m "not e2e" --ignore=tests/integration`).
Stan szczegółowy: Obsidian → [[Timshel — Project State (2026-07-07) — korpus v3, słownik, start H1]].
Vault-touching komendy (recall-eval, magic-digest, resummarize) wymagają
Full Disk Access; ta sesja Claude miała dostęp przez działający terminal Radka.
