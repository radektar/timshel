# Onboarding — lista follow-up PR-ów (po review PR #90)

Status: PROPOSED · 2026-07-28 · źródło: pełna runda /code-review na zmergowanym
PR #90 (8 finderów → 38 kandydatów → 10 findingów CONFIRMED + drobne).

Szczęśliwa ścieżka onboardingu działa (E2E na żywo: 60 notek → 2 połączenia,
$0.23). Poniżej ścieżki nieszczęśliwe, pogrupowane w PR-y.

---

## Przed testerem zewnętrznym (blokujące)

### PR A — "płacisz tylko wtedy, gdy się zgodzisz"
Findingi 1, 3, 4 (+ crash-relaunch). Jeden mechanizm, cztery objawy.
- **Settle stanu na starcie first-session:** zaraz po imporcie (zanim
  cokolwiek może paść) ustaw zegar tygodniowy i sclampuj licznik nowych
  notek — wtedy KAŻDA ścieżka wyjścia (błąd, crash, "Later", brak klucza,
  gate-fail) zostawia tani, spójny stan.
- **Hold cross-process:** flaga wstrzymania na dysku z TTL zamiast bool-a w
  pamięci jednego procesu (daemon LaunchAgent / relaunch po crashu jej dziś
  nie widzą).
- **"Later" nie eskaluje:** licznik clampowany poniżej progu pattern-trigger
  (dziś import ≥6 notek → płatny run po 2 dniach zamiast po tygodniu).
- Testy: każda ścieżka wyjścia → brak `is_due()` na następnym ticku; daemon
  w osobnym procesie respektuje hold; crash mid-flow nie płaci.

### PR B — import nie może zjeść własnego vaulta
Finding 2 (+ dryf 4 kopii walka po plikach).
- Blokada: folder == `TRANSCRIBE_DIR` (lub go zawiera / jest w nim) →
  jasny komunikat zamiast importu; wykluczenie `DIGEST_DIR_NAME`, `.timshel`,
  katalogów ukrytych (`.obsidian`).
- Jeden wspólny `iter_importable(folder)` w `src/ingest` — dziś wizard liczy
  z capem 50k, first-session importuje bez capu (może opłacić więcej plików,
  niż user potwierdził), `import_text.py` ma trzecią wersję.
- Testy: vault jako źródło odrzucony; liczba z wizarda == liczba importu.

### PR C — uczciwe komunikaty w momencie aktywacji
Findingi 8 (+ 1-część UX).
- `run_onboarding_digest` zwraca STATUS (written / empty / error / locked),
  nie samo `path`.
- Menu rozróżnia: pusto → dzisiejszy łagodny komunikat; błąd/lock → "nie
  udało się przeanalizować, spróbuj ponownie" + ponowienie; billing → jak
  dziś. Koniec z werdyktem "twoje notatki nie mają połączeń", gdy nic nie
  policzono.

---

## Przed decyzją o rollout (dane muszą być prawdziwe)

### PR D — integralność pomiaru i zgody
Findingi 7, 9 (+ `window_fallback` przewleczony przez 4 warstwy).
- Cofnięcie bypassu `INSIGHT_METRICS_ENABLED` dla wierszy onboardingu —
  pomiar aktywacji zbieramy na kohorcie testerów, nie u wszystkich (dziś
  `feedback_export` pakuje metryki także userom bez tester_mode).
- Guard `df < n_corpus` poluzowany dla małych korpusów (n ≤ 3): dziś import
  2 idealnie powiązanych notek zawsze raportuje `window_fallback=True`,
  czyli miara "brak materiału" kłamie tam, gdzie materiał jest najlepszy.
- `window_fallback` czytany z `candidates`, nie przekazywany osobno.

### PR E — upgrade to nie świeża instalacja
Finding 5.
- Wizard re-runuje się przy bumpie major.minor → onboarding na istniejącym
  vaultcie dziś ignoruje seen-set (re-płaci za zdigestowane notki) i kasuje
  oczekujący backlog (`mark_ran(corpus_keys, pending=0)`).
- Fix: tryb onboardingu tylko gdy `last_digest_at is None` i seen-set pusty;
  inaczej import + normalna ścieżka tygodniowa (albo jawna oferta "przemiel
  archiwum" = istniejące `digest-archive`).

---

## Higiena (przy okazji)

### PR F — `UserSettings.mutate` w oknach UI
Finding 6: `settings_window.py:902` i `dashboard_window.py:~4077` robią
load→save na stalej instancji i mogą wskrzesić skonsumowaną
`pending_import_dir` → powtórny import i drugi płatny digest.

### PR G — model onboardingu przez config
Finding 10: `LLM_MODEL_ONBOARDING` jako etap w `model_router` (stała jako
default). Dziś deprecjacja `claude-sonnet-5` = onboarding każdej świeżej
instalacji pada do czasu nowego DMG; A/B testera niemożliwy.

### PR H — dług z evalu i uproszczenia
- `eval_sonnet5.py`: użyj `insight_metrics.estimate_cost_usd` zamiast 4.
  kopii cennika (ślepej na tokeny cache), dodaj target `make eval-sonnet5`,
  black.
- Uproszczenia z review: `start_weekly_clock` przez `refresh_from_disk`,
  martwa gałąź `or consumed`, `_import_batch` zwraca resztę zamiast
  arytmetyki indeksów, wspólny predykat "AI skonfigurowane", wspólny "head"
  scaffolding onboarding/weekly.

---

## Kolejność i koszt

A → B → C przed wysyłką do testera zewnętrznego (to jedyne, które dotykają
pieniędzy usera i zaufania). D → E przed zbieraniem danych do decyzji
rollout. F, G, H kiedykolwiek — każdy ~pół godziny.

Każdy PR: pętla review-before-merge jak przy #89/#90 (rundy do czystej).
