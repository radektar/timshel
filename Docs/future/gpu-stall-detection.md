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

## Decyzja: okno statyczne zamiast kalibracji adaptacyjnej (2026-08-07)

Rundy 1–5 review wygenerowały ~16 znalezisk, z czego **8 dotyczyło kalibracji
tempa** — warstwy, która uczyła się szybkości maszyny ze strumienia wyjścia
(kolejność fd, bursty segmentów, monotoniczne maksimum, bankowanie kompilacji
jako tempa, w tym jedno znalezisko, gdzie nauczona wartość wyłączała detektor
całkowicie). Warstwy stabilne od początku: okna faz (karencja / kompilacja
Core ML), fallback `-ng` bez werdyktu, licznik zastojów.

Wniosek architektoniczny: kalibracja zgadywała wielkość znaną z góry. Decyzją
produktową (Radek: „Zróbmy statyczne na teraz. Potrzebuję sprawny mechanizm")
zastąpiona regułą statyczną z dwóch liczb znanych przed startem whispera:

- długość audio: WAV zawsze 16 kHz/mono/s16 (`_audio_duration_seconds`,
  moduł `wave`; błąd odczytu → 0 → podłoga),
- budżet czasu: `TRANSCRIPTION_TIMEOUT`.

Okno = `max(180 s, TIMEOUT / liczba_okien_30s)`. Najwolniejsza maszyna warta
czekania to ta, która zużywa cały budżet; jej czas na jedno okno dekodowania
to najdłuższa legalna cisza. Cichszy bieg jest zawieszony — albo za wolny, by
zmieścić się w budżecie, co kończy się tak samo. Fałszywy alarm na zdrowym
biegu jest niereprezentowalny, a nie „załatany".

| nagranie | okno |
|---|---|
| 3 h | 180 s (podłoga) |
| 4 min | 450 s |
| 60 s | 900 s (sufit) |

Sufit = karencja startowa (15 min): bez niego 30-sekundowy klip dostawał cały
budżet godziny, czyli dokładnie „stracisz godzinę", które ta funkcja usuwa —
a tolerowanie dłuższej ciszy w trakcie dekodowania niż na starcie byłoby
odwrotnością sensu. Podłoga 180 s jest związana z budżetem (5% z 3600 s = jeden
krok postępu) i pilnuje tego osobny test, żeby podniesienie
`TRANSCRIPTION_TIMEOUT` nie wywróciło niezmiennika po cichu.

Koszt: zawis przy krótkiej notce wykrywany w minuty, nie sekundy — świadomie
zaakceptowany (krótki plik = mały absolutny koszt czekania; po drugiej stronie
było 8 bugów i stan zbierany w pętli). Usunięte: `recent_gaps`, `pending_gap`,
`record_gap`, `_STALL_PACE_WINDOW`, `_STALL_PACE_MIN_GAP`, `last_progress_at`
i ~8 testów pilnujących przypadków, które przestały istnieć.

Historia rund 1–5 (w tym poprawki kalibracji, które ta decyzja unieważniła):
git log gałęzi `feat/gpu-stall-detection`, commity bb1ea15..db933fb.

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
