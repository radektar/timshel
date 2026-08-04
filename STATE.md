# STATE — Malinche/Timshel

Data: 2026-08-04 · Faza: kod → test
Re-entry (wypełnia Radek przy powrocie): ___ min

## Wejście do insightów: tagi-encje + guard stanowisk (PR #99, 2026-08-04)

Punkt wyjścia: ocena mechaniki tagowania i podsumowania na realnej nocie
(„26-07-30 Koalicja Tech to the Rescue"). Diagnoza: digest dostaje z notatki
tylko **trzy sygnały** — tagi, sekcję `## Stanowiska` i pierwsze 2400 znaków
podsumowania — i wszystkie trzy były osłabione u źródła.

**Tagi.** Reguła promptu „maks. 2 słowa" strukturalnie zakazywała
wielowyrazowych nazw własnych, więc `tech-to-the-rescue` nie miał jak powstać;
tagger nie widział też glosariusza, mimo że glosariusz JEST listą encji vaulta.
Nowy prompt (encje > konkretne tematy > jeden szeroki tag, negatywne przykłady
z realnej wpadki, reuse uzasadniony pasmem df), `known_entities` z
`VocabularyIndex.canonical_terms_block()`, `existing_tags_ranked()` wg df,
dyrektywa językowa. Efekt po retagu 180 notatek: pasmo punktujące w digeście
84 → 94 tagi z df≥2, a jego skład przeszedł z papki procesowej na encje
(`impact-chat` 20×, `tech-to-the-rescue` 14×, `malinche` 9×, `8-moons` 6×).

**Stanowiska — pętla trucizny domknięta.** Każdy `[[Subject]]` jest zbierany
przez `vocabulary.py` jako term POTWIERDZONY, więc śmieciowy podmiot
uwiarygodniał sam siebie: audyt na 95 notatkach pokazał **128 ze 178** podmiotów
do wyczyszczenia (skala over-bracketowania Haiku jest większa niż „bywa"
z ryzyk poniżej). Nowy `src/stance_guard.py` — deterministyczny, $0 — zdejmuje
same nawiasy; linia stanowiska przeżywa, więc kanał sprzeczności nie traci nic.
Kluczowa decyzja: **wyjątek tylko dla termów CURATED** (`vocabulary.json`) —
wyjątek na cały glosariusz chroniłby dokładnie tę truciznę, którą guard usuwa.

**Podsumowanie → synteza.** `NoteRef.synthesis_md`: przy przekroczeniu budżetu
sekcje wg priorytetu zamiast ślepego cięcia; scoring dalej czyta `summary_md`
bajt w bajt. Do tego tytuł cięty na granicy słowa (tytuł = nazwa pliku) i
transkrypcja head+tail zamiast samego ogona.

**Runda review (3 recenzentów) złapała dwie rzeczy warte zapamiętania:**
1. `synthesis_md` wyciąga Stanowiska ze środka podsumowania, a `verdict`
   czytał head/tail — cytat trafiał w martwą strefę weryfikatora i **prawdziwe
   połączenie leciało jako „zmyślone"**. Odpalałoby się to dokładnie w buildzie
   H1 (`tester_mode` włącza `VERDICT_ENABLED`). `_fuller_text` dostaje teraz
   całą sekcję podsumowania + transkrypcję.
2. Skrypt retagu składał notatkę od nowa: przy każdym przebiegu dokładał pustą
   linię, gubił końcowy newline, a przy blokowych tagach zostawiał wiszące
   pozycje listy (**niepoprawny YAML**). Zdążyło to dotknąć 180 notatek —
   naprawione w miejscu z backupu (0 różnic poza linią tagów, 0 błędnych YAML-i
   z tej przyczyny). Skrypt zapisuje teraz przez podmianę w oryginale, robi
   backup przed każdym zapisem, ma `--dry-run` i przerywa przy błędzie
   rozliczeniowym.

**Poprawa vaulta (za zgodą, 2026-08-04).** Wyczyszczone stanowiska w istniejącym
korpusie: 77 notatek, 132 podmioty zdjęte z nawiasów, 266 zmienionych linii —
wszystkie w sekcjach Stanowisk, kanał sprzeczności bit w bit ten sam (75 notatek,
164 stanowiska, identyczne podmioty i polaryzacje). Naprawione 3 notatki
z niepoprawnym YAML-em (`title:` z zagnieżdżonymi cudzysłowami → apostrofy
YAML-owe). Vault: 185 notatek, 0 błędnych YAML-i.

**Drugie źródło trucizny — znalezione przy weryfikacji efektu.** Po czyszczeniu
w prompcie whispera dalej siedziała nazwa pliku notatki:
`VocabularyIndex._harvest_vault` skanował vault rekurencyjnie, więc zbierał
**wygenerowane digesty**, a digest składa się z linków `[[nazwa-pliku]]`.
Zmierzone: 73 takie wikilinki z „Timshel Digests", 2 z „Timshel Recall".
Ta sama reguła co przy `signal_tags` — metadana pisana przez apkę nie jest
sygnałem użytkownika. Harvest chodzi teraz po top-levelu (jak `load_corpus`).

**I to samo w drugim wejściu taggera.** `TagIndex.build_index` też skanował
rekurencyjnie: 704 → 486 tagów (216 istniało wyłącznie w kopiach z
`.timshel/resummarize-backup`), `df('transcription')` 311 → 153. Najgorsze:
**`malinche-digest` siedział w liście `ISTNIEJĄCE TAGI`** podawanej modelowi
z instrukcją „użyj DOKŁADNIE w tej formie", a `signal_tags` zdejmuje tylko
`GENERATED_TAG` — marker digestu na notatce użytkownika stałby się pełnym
sygnałem połączenia. Ranking wg df (dodany w tym PR) był układany przez kopie
zapasowe: 74 ze 150 slotów promptu miało zawyżone df.
`NON_SOURCE_TYPES` (digesty + stuby `redirect`) to teraz jedna wspólna stała
w `tag_index`, importowana przez słownik.

Słownik: 310 → 196 (po czyszczeniu stanowisk) → **75** (po obu naprawach);
termy w kształcie nazw plików 33 → **0**.

**Reguła do zapamiętania:** każdy indeks czytający vault musi chodzić po
top-levelu. Zweryfikowane: `load_corpus`, `recall/engine`, `VocabularyIndex`
i `TagIndex` — zgodne. `menu_app`/`ui/obsidian_link` używają `rglob` do
otwierania notatek, nie do budowania sygnału, więc zostają.

Backupy: `scratchpad/vault-backup-20260804-095539` (sprzed retagu),
`vault-backup-stance-20260804-113227` (sprzed czyszczenia stanowisk).

## Konektor Voice Memos — ingest v2 faza 1 (PR #97, MERGE 2026-07-30)

Decyzja zakresu: z meeting-ingest v2 wchodzi **najpierw wyłącznie Voice
Memos**; Zoom/Teams/drop-folder, docx, mówcy i destylacja → backlog ingesta
(`Docs/future/meeting-ingest-plan.md`, przepisany). Powód: największy zasięg
adopcyjny (wystarczy iPhone, nie dyktafon), zero nowej logiki treści (głosówka
jest solowa i pierwszoosobowa), zasila trwający H1.

**Spike potwierdził wykonalność empirycznie:** po jednorazowym setupie (iCloud
→ Voice Memos na iPhonie + otwarcie appki raz na Macu) systemowy `voicememod`
dosyła nagrania przy zamkniętym GUI — zmierzone ~1 min od nagrania; archiwum
(104 pliki od 2018) spływa od razu; 104/104 nazwy sparsowane poprawnie.

**Pułapka, wokół której zbudowany jest cały moduł: mtime kłamie** — to czas
syncu, nie nagrania (archiwum ma mtime z dnia pierwszego syncu, a
eviction+redownload nadaje świeży). Dlatego prawda idzie z nazwy pliku
(`YYYYMMDD HHMMSS-XXXXXXXX.m4a`): stąd `recorded_at` (wstrzykiwany aż do
frontmatteru i do `compute_fingerprint`, który inaczej spada do mtime) oraz
klucz dedupu. Prywatnej bazy `CloudRecordings.db` NIE czytamy.

Zakres PR: `src/voice_memos.py` (rdzeń pollowalny `scan()` + stan + skorupa
FSEvents + pętla importu), przelot `recorded_at`/`provenance` przez
`import_audio_file → transcribe_file → _postprocess_transcript` (defaulty
`None` ⇒ ścieżka /Volumes bez zmian, chronione testem regresyjnym), sekcja
ustawień + jednorazowa auto-propozycja + dialog backfillu. Domyślnie OFF,
backfill „od dziś", archiwum tylko jawnym opt-inem.

**Pętla review: 4 rundy do czystej (4 → 2 → 1 → 0 defektów).** R1: `scan()`
bez watermarku zwracał CAŁE archiwum (fail-open) + backfill raportował sukces,
nie robiąc nic, gdy tick trzymał lock. R2: ponowne włączenie po przerwie
zasysało całą przerwę — `enable()` rozdzielone na zgodę (przesuwa znacznik) i
samonaprawę (tylko uzupełnia). R3 (najpoważniejsze): backfill archiwum omijał
`settle_after_import`, więc 104 notatki wypychały licznik ponad pattern-trigger
i kupowały płatny digest Opusa nad nagraniami z 2018 — przycinanie po KAŻDYM
przebiegu, bo hold wygasa po 60 min. R4: zero defektów; reguła zgody wydzielona
z modala do `apply_voice_memos_settings()` (była nietestowalna) + usunięty
martwy `ENABLE_VOICE_MEMOS`.

**Weryfikacja E2E bez mocków:** prawdziwa głosówka przez pełny pipeline w
izolowanym `$HOME` → notatka z `recording_date` z nazwy pliku (nie z mtime,
który sync ustawił 2h później), `source_type: voice-memo`, fingerprint z
prawdziwego czasu. Testy 1327, mypy 100 plików.

**Onboarding (2026-07-30, PR #98):** kreator dostał osobny krok `VOICE_MEMOS`
— tester bez dyktafonu dowiaduje się, że wystarczy mu iPhone. **Krok stoi PO
PERMISSIONS, nie obok ekranu dysków** (runda review): czytanie kontenera innej
apki wymaga FDA, a krok uprawnień kończy się restartem apki — zapytany
wcześniej ekran mówiłby komuś ze 100 nagraniami, że nie widzi żadnego, i zrzucał
winę na jego iCloud. Świadomie osobny
ekran, nie toggle przy dyskach: tamten ekran wybiera tryb PRZYCISKAMI, a
akcesorium ścina body do 2 linii i **nie istnieje w fallbacku bez AppKit** —
źródło zniknęłoby po cichu. Ekran pokazuje realną liczbę widocznych nagrań
(`iterdir`, NIE `glob` — glob połyka PermissionError i myli odmowę dostępu z
pustym folderem, a te dwa przypadki wymagają przeciwnych porad); „Turn on" i
„Skip" oba ustawiają `voice_memos_proposal_shown`, więc 20-sekundowa
propozycja w menu nie nagabuje po kreatorze. WELCOME i FINISH nazywają
źródła. Zoom/Teams NIE są wspominane — nie istnieją, nie obiecujemy.

**Pętla review #98: 5 rund (2→2→2→1→0), żadne znalezisko w nowym kodzie —
wszystkie w założeniach o środowisku.** Największe: **re-run kreatora po
bumpie major.minor startował na FINISH**, bo `setup_stage="finish"` był
traktowany jak punkt wznowienia — czyli nowe kroki nie docierały do NIKOGO,
kto już ma apkę (wznawiamy tylko przebieg PRZERWANY, `setup_completed=False`).
Naprawa tego udostępniła ścieżkę „kreator na skonfigurowanej instalacji",
gdzie czekały trzy defekty niszczące dane: pole klucza API nie pokazywało
zapisanej wartości, a „Skip"/puste pole ustawiało `enable_ai_summaries=False`
(upgrade po cichu wyłączał Insights w trakcie H1!); ekran dysków kasował
`watched_volumes`; a prompt nazw dysków pre-wypełniał PRZYKŁAD „LS-P1", więc
zatwierdzenie podmieniało realną listę. Zasada wyprowadzona i utrwalona
testem: **na skonfigurowanej instalacji ekran musi pokazywać to, co jest
skonfigurowane, a „Skip" znaczy „zostaw", nie „wyłącz"** (capstone
`TestFullRerunOnAConfiguredInstall` przeprowadza pełen re-run i sprawdza, że
nic nie ginie). Testy: 1352.

**ZOSTAJE do weryfikacji na buildzie DMG (nie z terminala!):** TCC dla Group
Containers — dev-run dziedziczy uprawnienia terminala i może fałszywie
przechodzić; obsłużone statusem `NO_ACCESS` + hintem. To jedyne realne ryzyko,
którego review nie rozstrzygnie.

## Checklista wysyłki do testerów (2026-07-29) — kod GOTOWY, zostały manuale

Sesja 2026-07-29: #93 zmergowany, runda review na nim znalazła i naprawiła
czwarty kanał (#94, patrz sekcja niżej), R2 czysta. **Świeży tester DMG
`1bbee1af…` (stamp `9588589`) na iCloud `Timshel/`** — zastępuje `d2d3ecf1…`
(21.07, bez onboardingu #89–94). SMOKE PASS pod świeżym $HOME. URL-e release
w `checksums.py` zweryfikowane po rename repo (oba 200 przez redirect —
kod bez zmian). Zostały WYŁĄCZNIE manuale:
1. **Gatekeeper realnym kanałem** (mail/link → drugi Mac) — jedyny twardy
   warunek przed wysyłką; przy okazji kliknąć toast „Cofnij" na żywo.
2. Klucze Anthropic per-tester + spend limit (konsola).
3. Lista 3–5 testerów P1 z gęstym vaultem.

## Pomiar onboardingu: telemetria, upgrade, uczciwa flaga (PR #92, MERGE 2026-07-28)

Fala 2 follow-upów po review #90 — nie feature, tylko przyrząd pomiarowy pod
decyzję GO/kill H1. **D:** wiersze onboardingu wróciły pod
`INSIGHT_METRICS_ENABLED` (wcześniej pisały telemetrię do vaulta każdego
użytkownika, a `feedback_export` to pakuje) — instrument czytany z kohorty
testerów; zawsze-włączony verdict zostaje, ale z uzasadnieniem produktowym
(nieugruntowany pierwszy insight kosztuje więcej zaufania niż brak).
**E:** `run_onboarding_digest` zwraca `not-first-session`, gdy vault ma
historię — definicja to „run skonsumował okno" (`digest_runs`, monotoniczny
jak seen-set), NIE zegar i NIE seen-set (migracja zasiewa go na świeżej
instalacji); menu sprawdza to PRZED płatną ofertą.
**Pętla review: 5 rund, 4 ze znaleziskiem, w tym dwa na własnych fixach.**
R1: guard historii odpalał się w prawdziwej pierwszej sesji. R2: `digest_runs`
zerowany przez zapisy z innego procesu → `max()` w `_merge_disk_seen`.
R3: blocklista boilerplate'u była zgadywanką słownikową (nie łapała `punkty`/
`otwarte`/`lista` ani całego szkieletu EN, `keypoint` nie matchował nic,
`wątk`/`działan` martwe po zdjęciu diakrytyków) → cięcie **strukturalne**
linii nagłówków. R4: mimo to flaga nadal nie mogła zapalić się nigdy — apka
tagująe KAŻDĄ notatkę tagiem `transcription` (151/183 w vaultcie Radka),
punktującym z najwyższą wagą; jedno źródło prawdy `tag_index.GENERATED_TAG`.
R5: czysta dla tego PR-a. Na koniec dwa follow-upy zamknięte: tag apki
wykluczony przy KAŻDYM rozmiarze korpusu (zmierzone przed zmianą: okno na
realnym vaultcie to te same 15 notatek, zmienia się tylko kolejność) i
`reset_seen` nie cofa już zegara tygodniowego (`_adopt_disk_clock` wspólny
z `refresh_from_disk`). Suita **1249**, mypy/flake8/black czyste, CI zielone.
Wzór pod spodem wszystkich czterech znalezisk: **produkt mylił to, co sam
napisał, z tym, co powiedział użytkownik** (nagłówki, tag systemowy).

## Tag apki jako sygnał podobieństwa (PR #93, MERGE 2026-07-29)

Wypadło z rundy review na #92. Zasada: **metadana, którą apka sama zapisuje,
nigdy nie jest sygnałem od użytkownika.** `GENERATED_TAG` ("transcription")
niesie każda notatka z pipeline'u, więc każdy kanał czytający wspólny tag jako
dowód wspólnego wątku czytał własną księgowość. Jedno źródło prawdy:
`tag_index.GENERATED_TAG` + `candidate_assembly.signal_tags()`, używane przez
okno connectable, most tagowy i kotwice Stanowisk. Pole `tags` notatki
nietknięte (w digeście i promptcie to uczciwe metadane). Runda review po
merge'u dołożyła czwarty kanał (**PR #94, MERGE 2026-07-29**): `note_graph`
wyglądał na odporny (pasmo `TAG_DF_BAND=(2,15)` wyklucza df=151), ale na
vaultcie z 2–15 transkrypcjami — dokładnie tester po imporcie — tag apki
wpada DO pasma i bramka $0 liczyła sąsiadów „graph" po samym tagu jako
silnych; `build_note_terms` też czyta przez `signal_tags`. Suita **1253**,
R2 czysta.

Najgroźniejszy był tryb **bramkowy**, nie wagowy: kotwica kanału Stanowisk
odpowiada „o CZYM te notatki się nie zgadzają", a tag apki czyni ją prawdziwą
dla każdej pary. Okno 3: bramkę przechodziło 148/180 starszych notatek, po
teście polaryzacji zostawało 46, z czego **39 kwalifikowało się wyłącznie przez
tag apki**. **Ale efekt end-to-end jest mniejszy** (poprzednia wersja tego
wpisu go zawyżała): gotowy zestaw kandydatów bez zmian dla okna 3 (17 notatek),
wymiana 2 z 22 dla okna 8. Ogon mostu tagowego nie dochodził do capu, a tier
leksykalny już ważył prawdziwe kotwice wyżej. Fix działa tam, gdzie pula
prawdziwych kotwic jest cienka — czyli na vaultach po imporcie.

Sprawdzone przy okazji, ważne dla oceny ryzyka: **„bzdury przechodzące do
outputu" nie materializują się.** Kanały nie mówią Claude'owi, co parować —
dają płaską listę 25 notatek. Przed wynikiem stoją dwie zapory: prompt syntezy
(contradiction = zmiana stanowiska TEJ SAMEJ osoby + horoscope guard) i verdict
na pełnym tekście („różne tematy → drop"). Przegląd 5 digestów z vaulta: 16
połączeń, 4 sprzeczności, wszystkie w temacie, zero par niepowiązanych. N=5,
jeden vault, Opus — cienki punkt to decyzja o tańszym modelu tygodniowym,
bo horoscope guard jest promptem, nie gwarancją.

**Znalezione, NIE naprawione:** tier strukturalny Stanowisk zwraca 0 z 4 slotów
dla okna 3 i 8 (3 z 4 dopiero przy oknie 15) — w zwykłej tygodniówce cały kanał
sprzeczności wypełnia słabszy tier leksykalny. Do zdiagnozowania osobno.
Doc: `Docs/future/channel-signal-hygiene.md`.

## Onboarding: import notatek + pierwszy digest Sonnet 5 (PR #90, MERGE 2026-07-27)

Aktywacja zamiast czekania tygodnia: wizard (krok IMPORT_NOTES po ekranie
klucza) zbiera folder z notatkami (txt/md/vtt, zgoda przy liczbie plików);
po setupie first-session (menu_app) importuje z progressem (retry locka),
bramki $0, dialog oferty (~$0.15–0.25) i `run_onboarding_digest`: cały
korpus jako materiał (bez migracji seen), okno CONNECTABLE (gęstość
tagi/encje/rare-tokens, guard na wszechobecne tokeny), max 2 płatne okna
(retry), model `claude-sonnet-5` wstrzykiwany per-run (eval 2026-07-24:
nigdy pusty, Opus dał pusty digest na najnowszym oknie; tygodniowy Opus
NIETKNIĘTY), verdict zawsze (metryka aktywacji), na końcu mark-all-corpus
pending=0. Wspólny ogon `_synthesize_and_write` (tygodniówka bajt-w-bajt,
mark-callback przed metrykami). Hold `suspend_auto_digest` z jawną
własnością (dialog→wątek digestu); "Later" startuje tygodniowy zegar.
Telemetria: `onboarding`/`window_fallback` w metrics.jsonl, wyłącznie
przy INSIGHT_METRICS_ENABLED (kohorta testerów) — kryterium: ≥1 połączenie
po verdictcie w sesji 1.
**E2E live: 60 realnych notek → digest 2 połączenia (prawdziwa
kontradykcja biznesowa) za $0.23; 20 notek → pusto 2× (mały korpus =
znany przypadek).** Pętla review: R1(7: 2 HIGH hold-gap + readiness,
3 MED, 2 LOW) → R2(3 LOW) → fixy zweryfikowane trace+testy. Suita 1220.
Otwarte: decyzja o modelu TYGODNIOWYM czeka na ślepy odczyt okien 2–3
(`/tmp/sonnet5_eval_BLIND.md`, klucz u Claude'a); relay demo = osobny
projekt (decyzja produktowa); dopieszczony wizual onboardingu → strona
w app-redesign briefie. Plan: `Docs/future/onboarding-first-digest-plan.md`.

## Digest: okno po fingerprintach + gate $0 przed API (PR #89, MERGE 2026-07-23)

Diagnoza z testu na drugim Macu: (1) digest liczył "nowość" po dacie nagrania
z frontmattera — backfill starych nagrań był niewidoczny; (2) ręczny trigger
palił Opusa (~$0.43) nawet po 1 nagraniu bez powiązań; (3) digest odpalał się
w środku batcha. Wdrożone (7 commitów): seen-set `note_key()` w stanie
schedulera (+ persystowany pending, epoka, tombstones) z migracją jednorazową
z daty (świeża instalacja = lustro legacy pierwszego runu, bez auto-drainu
archiwum); cap okna 15; lokalny gate przed API (okno≥2 LUB ≥2 silnych
sąsiadów; bm25-only = szum nagłówków) + cooldown 1h + wiersz `gate-skip` $0
w metrics.jsonl; ręczny run w menu z preview w wątku tła + dialogiem;
force z pustym oknem regeneruje świeże okno; seam po transkrypcji od-widuje
fingerprint (delete-and-retranscribe działa; tombstones adoptowane z dysku —
lift się propaguje między procesami); `make digest-archive RUNS=N RESET=1`
= jawny, płatny digest archiwum (reset przez epokę, bez restartu apki).
**Pętla review: R1 adversarial(10) → R2 full 8-finderów(10) → R3(3 unsee)
→ R4(2 merge-protokół) → R5 CZYSTA (repro-skrypty + trace).** Suita 1192,
black/flake8/mypy czyste. Do przetestowania na realnym archiwum: `make
digest-archive RESET=1 RUNS=2` (próbka ~$0.90) → ocena jakości digestów.
Poza zakresem (świadomie): digest nie czeka na koniec batcha transkrypcji;
odmowa summarizera została tytułem notki ("I cannot produce notes...") —
osobne drobne PR-y. Kalibracja progu gate'a → telemetria gate-skip po 2–4
tyg. Kontekst: vault 11-Transcripts zbackfillowany (175/175 z fingerprintem,
duplikat "Domki dla rodzin" scalony).

## Downloader — wyścig + stale resume NAPRAWIONE (PR #85, merge 2026-07-21)

Test Gatekeepera na drugim Macu złapał na żywo: encoder-small nie instalował
się nigdy (3 próby + [Errno 2] na rename). Dwa root cause'y: (1) wizard
(background download) i daemon (auto-naprawa encodera) pobierały RÓWNOLEGLE
do jednego .tmp (append → przeplot → zły checksum, rename jednego wyrywał
plik drugiemu); (2) retry po błędzie checksumy wznawiał ze stale offsetem
(Range na świeży plik → sam ogon → pętla błędów). Fix: locki per-artefakt
+ locki instalacyjne (download+extract+unlink jako całość, encoder/bundled/
static), resume liczony per-próba, checksum na .tmp PRZED rename, append
tylko przy 206, repair cleanup pod lockiem. Pętla review: R1(5)→R2(2)→R3(1)
→R4 PUSTA. Suita **1163** + mypy; SMOKE PASS. Znane kosmetyczne: czekający
na locku nie emituje progresu przez czas cudzego pobierania.
**Tester DMG `d2d3ecf1…` (stamp `1b2fab6`) na iCloud `Timshel/`** — zastępuje
`902a9a24…`. Doraźnie na drugim Macu: `rm -f ~/Library/"Application
Support"/Timshel/downloads/*.tmp` + restart odblokowuje stary build.
Onboarding testera przetłumaczony na PL i zaktualizowany pod ten build
(PR #84); suchy przebieg rytuału (signal-report + feedback zip) PASS —
paczka zgodna z obietnicą prywatności (uwaga: manifest niesie hostname).

## Wyszukiwarka w bundlu — NAPRAWIONA (PR #82, merge 2026-07-21)

Tryb **lexical-only**: bez fastembed/sqlite-vec silnik degraduje do czystego
BM25 — osobny plik bazy per tryb (`vault_lexical.db` obok `vault_vectors.db`,
środowiska nie kasują sobie indeksów), indeks bez wektorów, retriever bez
kanału gęstego, confidence = **idf-ważony** overlap (pospolite słowo nie udaje
trafienia), osobny próg abstynencji 0.45 (dense zostaje na 0.60 ze STARĄ
surową frakcją — bez cichej rekalibracji). UI uczciwe: seam→okno sygnał trybu
(„tryb dosłowny" w meta, kopia abstynencji mówi o braku warstwy semantycznej).
Hardening z pętli: samonaprawa skorumpowanego store'a (plik nieczytelny przy
otwarciu ORAZ korupcja w locie — iCloud; cooldown 120s), single-flight
backfill z coalescingiem (restart po zapisie ustawień/zmianie vaulta),
generacyjny reset silnika + deferred reset (zero beachballa na main thread),
fallback dense→lexical przy na-wpół-zainstalowanych depsach, inwalidacja
cache silnika toru digestu. **Pętla review: R1(10)→R2(9)→R3(6)→R4(6)→R5(4)→
R6(1)→R7 PUSTA (konwergencja).** Suita **1159** + mypy; SMOKE PASS.
**Tester DMG `902a9a24…` (stamp `3586438`) na iCloud `Timshel/`** — zastępuje
`a691e6af…`; pierwszy build z działającym ⌘K.
Znane ograniczenie (świadome, nie blokuje H1): osobny PROCES daemona
trzymający store pisze w osierocony inode po healu w apce (cross-process
file-identity poza zakresem PR); heal-cooldown po nieudanym rebuildzie może
opóźnić ponowny heal o ≤120s.

## Decyzja i18n (2026-07-20): wersja EN na bramce pre-waitlist

Audyt na pytanie „czy mamy wersję angielską": **treść już dwujęzyczna**
(`summarizer.detect_language` + Whisper multilingual — EN nagranie = EN
notatka), **chrome UI = tylko PL, zero warstwy i18n** (`settings.language`
to język Whispera, nie locale), **Stanowiska dostrojone pod PL** (rdzenie
fleksyjne w `stance.py`). **Rewizja wieczorna (Radek): faza EN = DWA filary,
oba obowiązkowe** — (1) i18n chrome: lekki `t(key)` JSON pl/en, EN bazowy,
`ui_language` obok nietykanego `settings.language`, ~1–1.5 dnia; (2) **insights
po angielsku BLOKUJĄCO** (uogólnienie `stance.py` + weryfikacja łańcucha
Stanowiska→kontradykcje→digest na korpusie EN; estymata dopiero po zbudowaniu
zbioru testowego EN). Timing bez zmian: **bramka pre-waitlist, NIE na H1**;
wyjątek nie-PL tester = oba filary. Pełny zapis: Obsidian →
[[2026-07-20 - Faza EN - UI i warstwa insights po angielsku]] (zastępuje
[[2026-07-20 - Wersja angielska UI - kiedy i jak]]).

## Runda testów ręcznych (2026-07-20) — poprawki + spójność wizualna

Z testów na drugim Macu (DMG serii dzisiejszej): (A.2) link „Przejdź do
transkrypcji" nie działał — root cause: strona ładowana `loadHTMLString` bez
realnego URL-a, kotwice `#` zawodzą; fix: render do pliku +
`loadFileURL` (przy okazji uproszczona polityka nawigacji — znikła cała
heurystyka `about:blank`). Tytuł okna „Timshel — Konstelacja" → **„Timshel"**
(Konstelacja = wewnętrzna nazwa kodowa, wyciekła). **Review wizualny
(/visual-identity):** rail był zimnym, płaskim slabem (wash `black @ 0.16`
+ blask przesunięty pod czytnik) ze schodkiem na szwie, a linie miały 6
różnych alf — fix: usunięty wash (rail = ta sama ciągła powierzchnia),
**skala neutralna** (jeden `_HAIRLINE_A` + 3 fille jako tokeny) egzekwowana
na wszystkich cienkich liniach. PR #78/#79. Suita **1126** + mypy, SMOKE PASS.
**DMG `a691e6af…` (stamp `e29b8bb`) na iCloud `Timshel/`** — do testów A–E.
Checklist: `Docs/READER-TEST-CHECKLIST.md`.

~~ZNANY, NIENAPRAWIONY: wyszukiwarka (Zapytałeś/⌘K) nie działa w żadnym
bundlu~~ — **NAPRAWIONE 2026-07-21 (PR #82, tryb lexical-only)**; szczegóły
w sekcji u góry.

## Ostatnia zmiana: czytnik markdown w oknie — WDROŻONY

Branch `feat/markdown-reader` (plan: `Docs/future/markdown-reader-plan.md`,
zrealizowany 1:1). Klik w chip źródła na insightcie albo w notatkę w sekcji
Notatki renderuje notatkę W OKNIE (podsumowanie na górze, „Przejdź do
transkrypcji", tabele GFM, wikilinki jadeit → nawigacja in-app z breadcrumbem
„← Wróć", „Otwórz w Obsidianie ↗" zostaje). Read-only z założenia; ścieżki
edycji na później otwarte (research: edytor źródła / Milkdown w webview /
mdformat). Hardening: JS off, raw HTML escapowany, obrazki bez fetchu,
http(s) → przeglądarka, reszta deny. Nowe: `src/ui/note_renderer.py` (czysty,
testowalny), zależności `markdown-it-py` + `pyobjc-framework-WebKit` w bundlu
(probe zweryfikowany PRZED kodem), `make preview-window` (harness QA
wypromowany — 4 stany do PNG, przejrzane przed pokazaniem).
**Code-review R1 (8 kątów): 10 findingów naprawionych** (trwały webview,
epoka, teardown, breadcrumb, polityka `about:`/mailto/obsidian, wikilink vs
code-spany, 1 odczyt pliku, label NOTE_OPENER, zdeterminizowany test chipów).
**Pętla review (nowa reguła: fix → review → build, aż runda czysta):**
R2 na poprawkach R1 → 10 findingów (wieczny spinner recall, stale-content
przy re-open tej samej notatki, klik insightu martwy w trybie note, breadcrumb,
polityka, czas w nagłówku…) → naprawione. R3 na poprawkach R2 → 6 findingów
(windowWillClose nie zwalniał webview NAPRAWDĘ, deny-bias zabijałby initial
load, semantyka niedomkniętego frontmattera psuła dedupe transcribera
i ręczne dismissale, wipe zaznaczeń przy geście powrotu, frankenstein
timestamp) → naprawione. **R4 → PUSTA (konwergencja).** PR #76.
Baterie: fuzz PASS, korpus 181/181, suita **1126** + mypy; SMOKE PASS.
**Finalny tester DMG: `3a8fe462…` (stamp `6d960bf`) na iCloud `Timshel/`** —
zastępuje wszystkie wcześniejsze. Checklist testów manualnych:
`Docs/READER-TEST-CHECKLIST.md` (15 punktów, ~15 min).
Follow-upy odłożone (nie blokują): wyniki wyszukiwania/cytaty syntezy wciąż
otwierają się zewnętrznie (decyzja produktowa), cache resolvera wikilinków
(rglob per klik — OK dla małych vaultów H1), konsolidacja splittera recall
(wymaga przemyślenia reindeksu), wspólna gramatyka wikilinków z entities.py.

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
**przebudowany po 3 rundach polish portu U1–U10, 2026-07-18** (beta.17, build
stamp `dffe161`, sha256 `06d99e9c…`); kopia na iCloud Drive `Timshel/` (+ test-assets:
10 tekstów Helios/Nordfab/Vantage + 2 audio TTS PL/EN). Fonty handoffu NIE
wdrożone (→ SF Pro).
NIE ruszać w assetach: fonty Neue Haas/Montreal (mapują na SF Pro); port ekranów A–I
(osobna faza kodu po testach).

## Ostatnia decyzja + dlaczego

**Port pakietu Claude Design 17.07 (okno Konstelacja, U1–U10) — wdrożony
2026-07-18.** Handoff `design_handoff_insights_2026_07_17` (spec C1–C8 +
BEHAVIOR.md, w repo `design-system/insights-2026-07-17/`) przeniesiony 1:1 do
PyObjC: akordeon szyny (Serendypacje/Zapytałeś/Notatki), segment triażu z
licznikami, pasek kierunków pod listą ze split-CTA "Kontynuuj w Claude",
**handoff ⇒ auto-Zachowaj** (domyka niespójność z review architektury
triage/signal), stała stopka, toolbar ⌘K + arkusz historii pytań (nowy store
`.timshel/ask_history.json`), sekcja Notatki (= brakujący podgląd
transkrypcji z apki), koniec języka "chmury", stany puste z mostkami, undo
przez nowy target `reset` w signal.jsonl. Świadome odchylenie: input zostaje
w polu toolbara (arkusz nie dubluje wiersza inputu).


**Runda 2 weryfikacji testerskiej (2026-07-16/17, drugi Mac) — naprawiona i
domknięta.** Bugi znalezione TYLKO w bundlu, niewidoczne dla pytest: (1) crash
"apka gaśnie po instalacji" = NSWindow bez `setReleasedWhenClosed_(False)`
(DownloadWindow, potwierdzone NSZombie); (2) **folder z wizarda nie docierał do
daemona** — singleton Config budowany przy starcie apki, przed zapisem wizarda;
fix u źródła: `reload_config()` w `_start_daemon()` (jedyne przewężenie startu);
(3) wrapper `TimshelTranscriber` nie forwardował `status=` (10/10 failed);
(4) dedup po cichu skipował re-import a UI kłamało "Imported N". Plus: natywne
alerty (rumps.alert deprecated na macOS 26), pip-guard w bundlu, ignorowanie
wolumenu własnego instalatora, PIL w bundlu (ikony SF-style, nie emoji), jasne
tło DMG ze standardową strzałką, auto-język (multilingual small, research
potwierdzony), pełna ścieżka folderu w Settings/wizardzie.
**DevX przeciw kolejnym 10 iteracjom:** build stamp w Info.plist (log mówi,
który build naprawdę działa), `make smoke-bundle` (binarka z bundla pod świeżym
$HOME na dev Macu — PASS), CI na GitHub Actions (pytest+mypy na PR).

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

0. **PR #99 czeka na merge** — 1444 testy zielone, mypy czysty, sześć rund
   review, vault wyczyszczony i zweryfikowany. Znany dług odsłonięty przy
   okazji, świadomie NIE brany: `TagIndex` nie czyta tagów w stylu blokowym
   (`tags:` + lista, czyli to, co pisze edytor properties w Obsidianie), więc
   ~30 notatek nie wchodzi do puli reuse taggera. Gotowy, przetestowany parser
   obu stylów leży w `scripts/retag_existing_transcripts.py::parse_tags` —
   do przeniesienia do `tag_index` osobnym krokiem.
1. ~~review + merge PR #66~~ — ZROBIONE (merge `4beac40`).
2. **Protokół A — DOMKNIĘTY 2026-07-18** (drugi Mac, DMG `06d99e9c…`):
   instalacja ✓, wizard+folder ✓, download ✓, import tekstów ✓, audio PL/EN
   auto-detect ✓, digest+metrics (opus, tester_mode) ✓, triage+handoff ✓,
   Export feedback ✓ (paczka zweryfikowana operatorsko: manifest/signal/
   metrics/digesty OK, action-rate liczy się), quit/relaunch ✓.
   ODŁOŻONE świadomie: **Gatekeeper realnym kanałem** (mail/link, nie iCloud)
   — jedyny warunek przed wysyłką DMG do pierwszego testera. Drobiazg: toast
   „Cofnij" (event `reset`) jeszcze nie kliknięty na żywo.
3. **Manualne poza kodem:** klucze Anthropic per-tester + spend limit;
   ~~potwierdzić że `checksums.py` release URL-e rozwiązują się po rename repo~~
   — ZWERYFIKOWANE 2026-07-29 (oba URL-e 200 przez redirect, kod bez zmian);
   lista 3–5 testerów P1 z gęstym vaultem.
4. **Meeting-ingest v2 na bramce** (2026-07-09): plan `Docs/future/meeting-ingest-plan.md`
   (konektory Zoom/Teams/drop-folder, transcript-first, reguła Stanowisk zamiast
   diaryzacji; Meet OAuth po popycie). Strategia rozszerzeń: vault →
   `research/2026-07-09 - Strategia rozszerzeń - synteza`. Czeka na "ok" przed kodem.
5. Zebranie sygnału H1 (N=3–5): rytuał tygodniowy rate→export ×3 tyg → `signal-report`.
GO: ≥3 warte akcji **połączenia dowolnego typu**/tydz., w tym ≥1 nieoczywiste.
Kill: import daje szum zamiast wartych akcji połączeń → import = onboarding FREE, nie feeder PRO.
**Kontradykcja NIE jest wymagana** (decyzja 2026-07-29, zsynchronizowana ze
Strategią w vaultcie): oczekiwanie „≥1 nieoczywista kontradykcja/tydz." było
sztywne i sztuczne — sprzeczność pojawia się, kiedy materiał ją niesie, a nie
na zamówienie kalendarza. Udział sprzeczności w zachowanych połączeniach
zostaje **obserwacją** (wejście do diagnozy toru strukturalnego i do
pozycjonowania PRO), nie bramką.

## Otwarte ryzyka

- Stanowiska mogą nie dowieźć kontradykcji w H1 — od 2026-07-29 **nie jest to
  już kill-trigger** (patrz kryterium wyżej), tylko sygnał diagnostyczny:
  zero sprzeczności przez 3 tyg. uruchamia diagnozę toru strukturalnego
  (0/4 slotów) i rozmowę o pozycjonowaniu PRO, nie zamknięcie hipotezy.
- Haiku jest za hojny w Stanowiskach (procesy/koncepty jako encje) — **zmierzone
  2026-08-04: 128/178 podmiotów to nie encje**, więc nie „bywa". Od PR #99 tnie
  to deterministyczny `stance_guard` ($0, zdejmuje nawiasy, stanowisko zostaje);
  logi `stance-subject de-bracketed` są sygnałem dryfu. Structured-output (B2)
  dalej jest lekarstwem docelowym, ale nie jest już warunkiem czystego sygnału.
- Stary korpus wciąż niesie śmieciowe wikilinki w Stanowiskach (guard działa na
  nowych notatkach i przez `resummarize_vault.py`) — glosariusz i kanał encji
  będą je widzieć do czasu przebudowy korpusu.
- Słownik uczy się tylko z wikilinków/encji — aliasy przekrętów wymagają
  ręcznego wpisu w vocabulary.json do czasu B1.
- P3 wdrożone (PR #64) POZA aliasem (patrz Ostatnia decyzja). Dług mypy:
  25 modułów zgrandfather'owanych (`ignore_errors` w pyproject) — do burn-down
  moduł po module, start od config.config/transcriber/vocabulary.
- Pełny rebuild okna Insights na każdy klik — świadomie NIE ruszony w P3-B
  (to okno oceny H1; przebudowa dopiero po H1).

## Nie ruszać (świadomie odłożone)

- Edycja notatek w apce — czytnik jest read-only z założenia; decyzja
  produktowa („apka pisze do vaultu") osobno, po H1. Stack jej nie blokuje.

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
- **Wersja angielska UI (i18n)** — bramka pre-waitlist obok Developer ID; NIE na
  H1 (panel PL). Flip tylko gdy pierwszy tester jest nie-PL. Decyzja 2026-07-20.
- **DONE (PR #66):** alias-canonicalizacja w prod (judge/retry) · rename Malinche→Timshel.

## Kontekst dla nowej sesji

Branch: **`main`** — repo ma od 2026-07-29 **wyłącznie `main`** (skasowane 8
wchłoniętych/porzuconych branchy; praca landingu żyje w osobnym repo
`~/CODE/timshel-web`, tam jest rozwinięta dalej). Pracuj od czystego `main` ·
testy: **1253 pass** (`./venv312/bin/python -m pytest tests/ -m "not slow" --ignore=tests/integration`);
mypy zielony (`./venv312/bin/python -m mypy src/`, 99 plików).
Ostatnie pakiety: PR #89 (seen-window + gate $0) → #90 (onboarding first-digest)
→ #91/#92 (zgody + pomiar) → #93/#94 (higiena sygnału) → #95 (instrukcja testera)
→ #96 (kryterium H1 ujednolicone). Starsze: #62/#64/#65/#66/#67.
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
