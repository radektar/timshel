# Higiena sygnału w kanałach doboru kandydatów

Status: WDROŻONE (PR #93, 2026-07-28) · źródło: runda review na PR #92

## Zasada

**Metadana, którą apka sama zapisuje, nigdy nie jest sygnałem od użytkownika.**

Kanały doboru kandydatów odpowiadają na pytanie „które stare notatki mogą się
łączyć z oknem". Każdy sygnał, który jest prawdziwy dla *wszystkich* notatek z
konstrukcji — nagłówki sekcji, tag nadawany przez pipeline, marker transkrypcji
— nie niesie informacji o powiązaniu. Wpuszczony do rankingu psuje w dwóch
trybach naraz:

- jako **waga**: dodaje stałą do każdej notatki, więc nic nie różnicuje, ale
  przesuwa progi (np. „czy cokolwiek jest połączalne" nie może już wyjść na 0);
- jako **bramka**: warunek „dzielą X" staje się prawdziwy zawsze, czyli bramka
  przestaje istnieć.

Tryb bramkowy jest groźniejszy — nie widać go w wynikach, bo kanał dalej coś
zwraca. Zwraca tylko nie to, co obiecuje.

## Implementacja

Jedno źródło prawdy zamiast literału w kilku plikach:

- `src/tag_index.py::GENERATED_TAG` — tag, który pipeline nadaje każdej
  notatce (`transcriber.py` zasiewa nim listę, `markdown_generator.py` ma go
  jako fallback). Obaj piszący i wszyscy czytający używają stałej.
- `src/connections/candidate_assembly.py::signal_tags(note)` — tagi notatki
  minus tag apki. **Każdy kanał traktujący wspólny tag jako dowód wspólnego
  wątku czyta tagi przez tę funkcję.** Dziś: okno connectable, most tagowy,
  kotwice kanału Stanowisk.
- `_strip_headings()` — analogiczne cięcie szkieletu sekcji (strukturalne, nie
  po słowniku), stosowane tam, gdzie cut ubiquity jest poluzowany.

Pole `tags` samej notatki zostaje nietknięte: w notatce digestu i w promptcie
syntezy to uczciwe metadane, nie sygnał podobieństwa.

`note_graph.py` wyglądał na odporny — pasmo `TAG_DF_BAND = (2, 15)` wyklucza
tag o df=151 na vaultcie dogfood. Ale pasmo chroni tylko duże vaulty: przy
2–15 transkrypcjach (dokładnie vault testera po imporcie) df taga apki wpada
DO pasma i staje się krawędzią W_TAG=1.5 między każdą parą notatek, a bramka
$0 liczy takich sąsiadów „graph" jako silnych. Naprawione w rundzie review na
#93: `build_note_terms` też czyta tagi przez `signal_tags`. Wniosek: pasmo df
to dobra higiena statystyczna, ale NIE zastępuje zasady — sygnał, który apka
sama pisze, wycina się jawnie, na każdym rozmiarze korpusu.

## Pomiar (vault dogfood, 183 notatki, tag na 151, $0 offline)

Bramka kotwic kanału Stanowisk, okno 3 notatek:

| etap | przed | po |
|---|---|---|
| przechodzi bramkę kotwic | 148 / 180 | 21 / 180 |
| + warunek przeciwnej polaryzacji | 46 | 7 |
| kwalifikuje się WYŁĄCZNIE przez tag apki | 39 z 46 | — |

Most tagowy: 148/180 → 21/180 (okno 3), 143/175 → 33/175 (okno 8).

**Efekt end-to-end jest mniejszy niż te liczby** i to jest liczba, która się
liczy: gotowy zestaw kandydatów jest **bez zmian** dla okna 3 (17 notatek) i
**wymienia 2 z 22** dla okna 8 — obie zmiany przez kanał Stanowisk. Powody:
ogon mostu tagowego rzadko dochodził do capu notatek, a tier leksykalny już
wcześniej ważył prawdziwe kotwice wyżej (`len(shared)` 2 vs 1). Fix zdejmuje
szum, który wygrywał sloty tylko wtedy, gdy pula prawdziwych kotwic była
cienka — czyli na vaultach po imporcie, z małą liczbą encji i notatek w
formacie v2.

## Znalezione przy okazji, nie naprawione

**Tier strukturalny kanału Stanowisk nie działa przy normalnym oknie.**
`_structured_flip_neighbors` (parowanie po sparsowanych `## Stanowiska`, tier
opisany jako „near-exact") zwraca **0 z 4 slotów** dla okna 3 i 8 notatek; 3 z
4 dopiero przy oknie 15. W zwykłym digeście tygodniowym cały kanał sprzeczności
wypełnia więc tier leksykalny — ten słabszy, zgadujący polaryzację z prozy.
Do zdiagnozowania osobno: czy to kwestia progu, parsowania, czy tego, że okno
3 notatek po prostu rzadko niesie stanowisko kolidujące z archiwum.

## Powiązane

- `Docs/future/onboarding-followups.md` — lista PR-ów, z której to wypadło
- `Docs/future/distance-experiment-results.md` — po co w ogóle są kanały
  dystansowe
