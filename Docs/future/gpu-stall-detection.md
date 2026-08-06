# Zawieszony GPU: wykrywanie zastoju zamiast czekania na timeout

Status: **ZREALIZOWANE 2026-08-06** · założenia spisane po rundzie 3 review na
PR #104 · implementacja: `_is_stalled` / `_stall_limit` / `_run_whisper_streaming`
w `src/transcriber.py`

## Problem

PR #104 naprawił awarie Metala, które **zgłaszają się na stderr**: przy
inicjalizacji (`ggml_metal_init: error`, `MTLLibraryErrorDomain`) i w trakcie
biegu (martwy command buffer, pipeline, który się nie kompiluje). Każda z nich
kończy przebieg niezerowym kodem, więc `_should_retry_without_gpu` widzi awarię
i puszcza fallback z `-ng`.

Poza tą siatką został wariant, w którym **GPU nie mówi nic — po prostu milknie**:
whisper żył, nie drukował postępu, nie kończył się, pętla czekała do
`TRANSCRIPTION_TIMEOUT` (3600 s), a `_run_macwhisper` łapał `TimeoutExpired`,
ustawiał `AppStatus.ERROR` i zwracał `None`. Nagranie umierało po godzinie, bez
próby `-ng`, która najprawdopodobniej by je uratowała.

## Czego NIE robić

**Retry `-ng` po globalnym timeoucie.** Timeout nie odróżnia „zawisł" od „mieli
wolno": trzygodzinne nagranie na modelu `medium` potrafi legalnie przekroczyć
godzinę i dostałoby drugi pełny przebieg. To naprawianie podwojenia
podwojeniem — czyli dokładnie tego buga, który PR #104 zlikwidował.

## Co zostało zrobione

Sygnałem jest **brak jakiegokolwiek wyjścia**, nie całkowity czas.

1. **stdout wrócił do gry.** Dotąd szedł do `DEVNULL` (whisper zapisuje TXT sam
   przez `-otxt`), więc jedynym sygnałem życia był `progress = NN%` ze stderr —
   drukowany co 5% biegu, czyli przy limicie 3600 s nawet co ~180 s. Tymczasem
   whisper wypisuje na stdout **każdy zdekodowany segment**, jeden na ~30 s
   audio. Oba pipe'y są czytane tą samą nieblokującą pętlą `select`, treść
   stdout jest wyrzucana — liczy się sam fakt aktywności. Dzięki temu okno
   zastoju zeszło z zakładanych 10 min do **3 min**.
2. **Znacznik `last_activity`** aktualizowany przy każdym odczycie >0 bajtów z
   któregokolwiek kanału — świadomie NIE `last_heartbeat`, który przesuwa się
   tylko wtedy, gdy heartbeat faktycznie poszedł do logu (dławienie co 10
   punktów / 20 s). Wiązanie detekcji z logiem to ta sama klasa błędu co
   detektor z PR #104, który mylił log z faktem.
3. **Karencja 15 min do pierwszego wyjścia** (`_STALL_GRACE_SECONDS`): pierwsze
   uruchomienie Core ML na maszynie kompiluje enkoder w ciszy, whisper sam
   ostrzega „first run on a device may take a while". Po pierwszym segmencie
   albo pierwszej linii postępu obowiązuje już okno 3 min
   (`_STALL_SILENCE_SECONDS`).
4. **`select()` nigdy nie śpi dłużej niż do progu zastoju** — inaczej to
   interwał odpytywania, a nie próg, decydowałby o czasie reakcji. Wyszło przy
   mutacji: test karencji był zielony na zepsutym kodzie, bo detektor był
   głodzony przez `select` z limitem 1 s.
5. **Fallback tylko dla tego nagrania, BEZ zapisu werdyktu.** Zastój może mieć
   źródło poza Metalem (przeciążony CPU, spanie dysku, iCloud). Licznik z
   `_persist_gpu_disabled()` zostaje zarezerwowany dla awarii, które się
   zgłaszają. Gdy GPU już było wyłączone albo fallback też zawisł — błąd z
   komunikatem odróżniającym oba przypadki.
6. **`WhisperRun`** (podklasa `CompletedProcess`) niesie flagę `stalled` i
   zmierzoną ciszę `stalled_after`: „ubiliśmy to sami" to informacja, której
   żaden kod wyjścia nie wyraża, a komunikat ma cytować pomiar, nie próg.

## Poprawki po review (runda 1)

Review wskazało, że próg 3 min i karencja 15 min były mierzone wyłącznie na
ciepłym starcie `medium` na M2 — czyli nie na scenariuszach, dla których
istnieją. Stąd:

- **Okno zastoju skaluje się do tempa biegu**: `max(180 s, 4 × najdłuższa
  dotychczasowa przerwa)`. Stary próg zabijał krótkie nagranie na wolnej
  maszynie (`medium`, 2 wątki, bez GPU — okno 30 s audio potrafi tam zająć
  minuty), która i tak zmieściłaby się w godzinie. Tempo liczone jest już od
  **pierwszego** segmentu (mierzone od ostatniej linii startowej) — inaczej
  wolna maszyna ginęła zanim zdążyła się „przedstawić". To wyszło dopiero przy
  teście: pierwsza wersja adaptacji nie miała z czego się uczyć.
- **Kompilacja Core ML dostała własne okno** (`_STALL_COMPILE_SECONDS`, 30 min).
  `large` jest wybieralny w ustawieniach, a pierwsza kompilacja enkodera na
  starszym sprzęcie potrafi przekroczyć 15 min karencji. Faza jest wykrywana, bo
  whisper ją oznacza (`loading Core ML model` → `Core ML model loaded`), nie
  zgadywana.
- **Zgłoszona awaria Metala wygrywa z zastojem.** Marker mógł przyjść bez
  końcowego `\n` i dopiero potem proces milkł — wtedy `handle_line` go nie
  widział, a gałąź zastoju przejmowała bieg i werdykt nigdy nie był zapisany.
  Teraz zabicie na zastoju najpierw domyka częściową linię, a sprawdzenie
  markerów jest przed sprawdzeniem zastoju.
- **Komunikat mówi zmierzoną ciszę** — bieg ubity na karencji milczał 15 min,
  a błąd twierdził „3 min".
- **Fallback `-ng` nie rusza enkodera** (Core ML jest zawsze), więc komunikat
  i QUICKSTART kierują przy podwójnym zastoju także na model/zależności, nie
  wyłącznie na dysk i pamięć.

## Pomiary (M2 Pro, `medium` + Core ML, ciepły start)

| zdarzenie | czas od startu |
|---|---|
| `Core ML model loaded` | 1,8 s |
| `system_info` (koniec inicjalizacji) | 1,8 s |
| pierwszy segment na stdout | 6,9 s (+5,1 s) |
| drugi segment | 7,7 s (+0,7 s) |

Najgorsza legalna cisza = czas przeżucia jednego okna 30 s audio. Okno 3 min
toleruje maszynę ~6× wolniejszą niż realtime — taka i tak nie zmieściłaby się
w `TRANSCRIPTION_TIMEOUT`.

## Powiązane

- PR #104 — markery awarii, podwójna transkrypcja, werdykt trwały
- `src/transcriber.py`: `_STALL_SILENCE_SECONDS`, `_STALL_GRACE_SECONDS`,
  `_is_stalled`, `_run_whisper_streaming`, `WhisperRun`
- QUICKSTART.md — sekcja „Transcription hangs"
