# Higiena sygnału: co apka pisze o sobie, nie jest sygnałem użytkownika

Status: WDROŻONE — kanały doboru (PR #93/#94, 2026-07-28), wejścia generacji
(PR #99, 2026-08-04) · źródło: rundy review na PR #92 i #99

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

## Rozszerzenie: wejścia generacji (PR #99, 2026-08-04)

PR #93/#94 zastosował zasadę do **kanałów doboru kandydatów**. Okazało się, że
łamią ją także **wejścia generacji** — to, z czego powstaje notatka, zanim
jakikolwiek kanał ją zobaczy. Trzy niezależne ścieżki, ta sama pętla:

**1. Stanowiska karmiły słownik.** Każdy `[[Subject]]` z sekcji `## Stanowiska`
jest zbierany przez `vocabulary.py` jako term POTWIERDZONY (`wikilinked=True`
omija próg powtarzalności) i przez `entities.py` jako klucz encji. Haiku
bracketuje procesy i koncepty, więc śmieć uwiarygodniał sam siebie i szedł
dalej do promptu whispera oraz bloku KNOWN TERMS. **Zmierzone: 128 ze 178
podmiotów w 95 notatkach to nie były encje.** Lekarstwo: `src/stance_guard.py`
— deterministyczny, $0, zdejmuje same nawiasy; linia stanowiska przeżywa
(parser czyta podmiot bez nawiasów), więc kanał sprzeczności nie traci nic.
Kluczowa decyzja: **wyjątek tylko dla termów CURATED** (`vocabulary.json`).
Wyjątek na cały glosariusz chroniłby dokładnie tę truciznę, którą guard usuwa —
bo glosariusz uczy się z wikilinków.

**2. Digesty karmiły słownik nazwami plików.** `VocabularyIndex._harvest_vault`
skanował vault rekurencyjnie, a digest z definicji składa się z linków
`[[nazwa-pliku]]`. **Zmierzone: 73 takie wikilinki z „Timshel Digests", 2
z „Timshel Recall".** W prompcie dekodowania whispera siedziała pełna ścieżka
`02-Work-TTTR/Google Grant/26-06-03 - Workshop - ...`.

**3. Kopie zapasowe układały ranking tagów.** `TagIndex.build_index` też
skanował rekurencyjnie, więc liczył kopie notatek z
`.timshel/resummarize-backup`. **Zmierzone: 704 vs 486 tagów** (216 istniało
wyłącznie w kopiach), `df('transcription')` 311 zamiast 153. Najgroźniejsze:
**`malinche-digest` trafił do listy `ISTNIEJĄCE TAGI`** podawanej modelowi
z instrukcją „użyj DOKŁADNIE w tej formie" — a `signal_tags` zdejmuje tylko
`GENERATED_TAG`, więc marker digestu na notatce użytkownika stałby się pełnym
sygnałem połączenia. Ranking wg df (dodany w tym samym PR, żeby cap 150
slotów trzymał tagi zdolne łączyć notatki) był układany przez backupy: 74 ze
150 slotów miało co najmniej dwukrotnie zawyżone df.

### Reguła operacyjna

**Każdy indeks czytający vault chodzi po top-levelu.** Podfoldery to output
apki: digesty, notatki recall, kopie przedmigracyjne. Zweryfikowane jako
zgodne: `load_corpus`, `recall/engine`, `VocabularyIndex`, `TagIndex`.
`menu_app` i `ui/obsidian_link` używają `rglob` do *otwierania* notatek, nie do
budowania sygnału — zostają.

Wspólna stała zamiast literałów: `tag_index.py::NON_SOURCE_TYPES` (digesty
plus ręczne stuby `redirect`), czytana przez indeks tagów i słownik. Typ
frontmattera parsujemy przez `parse_frontmatter`, nie regexem na oknie znaków,
żeby `type: "timshel-digest"` w cudzysłowie wykluczał się tak samo jak
w `load_corpus`.

### Efekt łączny (vault dogfood, 185 notatek)

| | przed | po |
|---|---|---|
| termy w słowniku | 310 | **75** |
| w kształcie nazw plików | 33 | **0** |
| różnych tagów w indeksie | 704 | **486** |
| `df('transcription')` | 311 | **153** |

Słownik steruje promptem dekodowania whispera i blokiem KNOWN TERMS, więc to
nie jest higiena samego digestu — dotyczy jakości każdej kolejnej transkrypcji.

## Znalezione przy okazji, nie naprawione

**Tier strukturalny kanału Stanowisk nie działa przy normalnym oknie.**
`_structured_flip_neighbors` (parowanie po sparsowanych `## Stanowiska`, tier
opisany jako „near-exact") zwraca **0 z 4 slotów** dla okna 3 i 8 notatek; 3 z
4 dopiero przy oknie 15. W zwykłym digeście tygodniowym cały kanał sprzeczności
wypełnia więc tier leksykalny — ten słabszy, zgadujący polaryzację z prozy.
Do zdiagnozowania osobno: czy to kwestia progu, parsowania, czy tego, że okno
3 notatek po prostu rzadko niesie stanowisko kolidujące z archiwum.

**`TagIndex` nie czyta tagów w stylu blokowym** (2026-08-04). Edytor properties
Obsidiana zapisuje `tags:` jako listę wciętych pozycji zamiast `[a, b]` —
i takie notatki wyglądają na nieotagowane. Na vaultcie dogfood: **30 ze 185
notatek (16%)**, 81 niewidocznych tagów, z tego dwa w paśmie `df >= 2`, które
liczy scoring (`bezpieczenstwo-danych`, `projekt-dla-miszy`). Luka jest
pre-istniejąca, ale podcina ranking wg df i będzie rosnąć, bo to kształt, który
Obsidian zapisuje sam. Parser obu stylów jest napisany i przetestowany:
`scripts/retag_existing_transcripts.py::parse_tags` — przeniesienie go do
`tag_index` zmienia pasma df dla całego korpusu, więc osobny krok.

**`ARCHITECTURE.md` opisuje nieistniejący backend.** Diagram (sekcja „Tagger" /
„Summarizer") pokazuje `malinche-backend` z endpointami `POST /api/v1/tags`
i bramkowaniem licencją; w kodzie tagger i summarizer wołają Anthropic
bezpośrednio (BYOK), a bramkowanie tierem zostało usunięte. Nie ruszone w #99 —
przepisanie diagramu to osobna robota.

## Powiązane

- `Docs/future/onboarding-followups.md` — lista PR-ów, z której to wypadło
- `Docs/future/distance-experiment-results.md` — po co w ogóle są kanały
  dystansowe
