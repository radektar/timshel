# Zawieszony GPU: wykrywanie zastoju zamiast czekania na timeout

Status: BACKLOG — założenia spisane 2026-08-06 · źródło: runda 3 review na PR #104

## Problem

PR #104 naprawił awarie Metala, które **zgłaszają się na stderr**: przy
inicjalizacji (`ggml_metal_init: error`, `MTLLibraryErrorDomain`) i w trakcie
biegu (martwy command buffer, pipeline, który się nie kompiluje). Każda z nich
kończy przebieg niezerowym kodem, więc `_should_retry_without_gpu` widzi awarię
i puszcza fallback z `-ng`.

Poza tą siatką zostaje wariant, w którym **GPU nie mówi nic — po prostu
milknie**. Wtedy:

1. whisper żyje, nie drukuje postępu, nie kończy się,
2. pętla w `_run_whisper_streaming` czeka aż do `TRANSCRIPTION_TIMEOUT`
   (`config.py`: **3600 s**),
3. `_run_macwhisper` łapie `TimeoutExpired` (`transcriber.py`, gałąź przy końcu
   `try`), ustawia `AppStatus.ERROR` i zwraca `None`.

Efekt dla użytkownika: nagranie umiera **po godzinie czekania**, bez próby
`-ng`, która najprawdopodobniej by je uratowała, i bez śladu w liczniku awarii
GPU. Komentarz przy `_METAL_FAIL_MARKERS` mówi o tym wprost, żeby nie obiecywać
pokrycia, którego nie ma.

## Czego NIE robić

**Retry `-ng` po globalnym timeoucie.** Timeout nie odróżnia „zawisł" od „mieli
wolno": trzygodzinne nagranie na modelu `medium` potrafi legalnie przekroczyć
godzinę i dostałoby drugi pełny przebieg. To naprawianie podwojenia
podwojeniem — czyli dokładnie tego buga, który PR #104 zlikwidował.

## Założenia rozwiązania

Sygnałem jest **brak postępu**, nie całkowity czas. Instalacja już to
produkuje: whisper dostaje flagę `-pp` i drukuje `progress = NN%` na stderr, a
`_run_whisper_streaming` to parsuje (`_PROGRESS_RE`) — dziś wyłącznie do
logowania heartbeatu.

1. **Osobny znacznik `last_progress_at`**, aktualizowany przy KAŻDYM trafieniu
   `_PROGRESS_RE` — nie da się użyć istniejącego `last_heartbeat`, bo ten jest
   przesuwany tylko wtedy, gdy heartbeat faktycznie poszedł do logu (dławienie
   co 10 punktów / 20 s).
2. **Karencja do pierwszego postępu (~15 min).** Pierwsze uruchomienie Core ML
   kompiluje model i whisper sam ostrzega `first run on a device may take a
   while`; ładowanie modelu `medium` też nie drukuje postępu. Zastój liczymy
   dopiero po pierwszej linii postępu albo po wyczerpaniu karencji.
3. **Okno zastoju ~10 min** bez nowego postępu przy żywym procesie → kill,
   traktowany jak awaria GPU tego przebiegu.
4. **Fallback tylko dla tego nagrania, BEZ zapisu werdyktu.** Zastój może mieć
   źródło poza Metalem (przeciążony CPU, spanie dysku, iCloud). Przebieg `-ng`
   jest testem rozstrzygającym: jeśli też zawiśnie, to nie GPU — a wtedy
   trwałe wyłączenie GPU byłoby fałszywym oskarżeniem. Licznik z
   `_persist_gpu_disabled()` zostaje zarezerwowany dla awarii, które się
   zgłaszają.
5. **Gdy GPU już było wyłączone** — zastój kończy przebieg błędem, jak dziś.

## Ryzyka do sprawdzenia przy implementacji

- Progi 15/10 min są zgadywane. Zmierzyć realny czas ładowania `medium`
  + kompilacji Core ML na zimnym starcie, zanim się je zaklepie — za krótka
  karencja ubija zdrowy przebieg przed pierwszym procentem.
- Dławienie logowania nie może wpływać na detekcję (patrz punkt 1) — to jest
  ta sama klasa błędu co detektor z PR #104, który mylił log z faktem.
- Test musi symulować proces żywy i milczący (bez EOF), czyli wariant
  `_FakePipeProc(hold_open=True)` — ten istnieje już w
  `tests/test_transcriber.py` przy teście timeoutu.

## Powiązane

- PR #104 — markery awarii, podwójna transkrypcja, werdykt trwały
- `src/transcriber.py`: `_METAL_FAIL_MARKERS`, `_run_whisper_streaming`,
  `_should_retry_without_gpu`, `_persist_gpu_disabled`
