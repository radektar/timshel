# Distance experiment — claude-opus-4-8

Window: 15 newest notes · bridges injected: `['25-11-19 - Rozwoj dzialalnosci opartej na warsztatach i agroturystyce', '26-04-16 - Analiza modelu biznesowego - oblozenie i strategie cenowe', '26-04-20 - Projekt Haetta- Wymagania Miszki i wyzwania konceptu', '26-05-10 - Rybojady kalendarz']`


## Analiza

**Hipoteza:** zaskoczenie bierze się z DYSTANSU (jakie notatki w ogóle się porównują), nie z lepszego modelu. Test: 3 warianty na tym samym oknie, jeden model (Opus 4.8), zmienia się tylko retrieval i prompt. **A→B izoluje dystans, B→C izoluje prompt.**

| | znalezione | rozkład typów | mosty użyte | jakość |
|---|---|---|---|---|
| **A** baseline (podobieństwo + stary prompt) | 5 | 4× shared-thread, 1 emergent | 0 | niska — generyczne grupowanie tematyczne |
| **B** +dystans (mosty + stary prompt) | 6 | 4 shared, 1 emergent, 1 contradiction | 3 | średnia — głębia jest, ale tonie w szumie |
| **C** +dystans +ostry prompt | 4 | 2 contradiction, 2 emergent, **0 shared** | 3 z 4 | wysoka — konkret, transfer, zaskoczenie |

**Atrybucja (czysta):**
- **Dystans jest konieczny.** A→B: mosty dały kontradykcję i emergent, które *strukturalnie* nie mogły powstać w A — notatki (XI'25 agroturystyka, IV Haetta) nie były nawet kandydatami przy retrievalu po podobieństwie.
- **Prompt jest mnożnikiem.** B→C: ostry prompt wyzerował 4 shared-thready (guard na horoskop + „dwa zaskakujące zamiast sześciu oczywistych") i pogłębił rationale do 2–3 zdań nazywających konkretne napięcie/transfer.
- Wniosek: **dystans otwiera przestrzeń, prompt ją oczyszcza.** Oba wchodzą, nie „albo-albo".

**Przykład tego samego zjawiska na trzech poziomach:**
- A (horoskop): *„we wszystkich trzech notatkach powraca wzorzec: tanie demo AI → reakcja rynku"* — prawda, o niczym.
- C (transfer): *„AR nieopłacalny przez koszt jednostkowy + BOŚ buduje tani silnik AI + Misza ręczne rendery → tania generacja AI mogłaby zbić koszt, który zablokował model AR"*.

**Zastrzeżenia:**
1. **N=1** — jedno okno, jeden run, jakość C oceniona ręcznie. Ground truth to kept/dismiss (`signal.jsonl`). To eval kierunkowy, nie dowód statystyczny.
2. **Bug produkcyjny:** baseline prompt przy domyślnym `SYNTHESIS_MAX_TOKENS=2048` obcina się i zwraca **0 połączeń** (pierwszy run: A=B=0, oba `out=2048`). Ten plik to wersja `--max-tokens 4096`. Ostry prompt jest zwięzły i mieści się w 2048.

**Rekomendacja:** ostry prompt + mosty jako default, napraw `max_tokens` niezależnie, zmierz keep/dismiss przez 2–4 tyg zanim uznasz za wygrane.

---

## A  baseline (similarity + baseline prompt)

found 5 (emergent-idea=1, shared-thread=4)

- (shared-thread)  [[26-06-24 - Projekt BOS przygotowanie demo generowania assetow AI]], [[26-06-04 - Potencjal wizualizacji AR w e-commerce i uslugach projekt]], [[26-05-19 - Kontroler parametrow Claudea w stylu syntezatora]]
    We wszystkich trzech notatkach powraca ten sam wzorzec: budowanie szybkiego prototypu/demo opartego na AI i obserwowanie reakcji rynku przed dalszą inwestycją.
      – A: Czy chciałbyś spisać wspólną metodę 'taniego demo → walidacja rynku → rozwój', która łączy projekt BOŚ, wizualizacje AR i kontroler parametrów?
      – B: Co odróżnia te projekty pod względem ryzyka i kosztu wejścia — które z nich najszybciej da sygnał o zainteresowaniu?
      – C: Czy któreś z tych narzędzi (generowanie assetów, AR, kontroler) mogłyby zasilać się nawzajem w jednym portfolio produktowym?

- (shared-thread)  [[26-06-18 - 8Moons Projekt filmikow instruktazowych dla 8moons 2]], [[26-06-18 - 8Moons Projekt filmikow instruktazowych dla 8moons]], [[26-06-17 - Haetta - rozmowa z konstruktorem]]
    Powtarza się myśl, że dokumentacja procesu budowy i wywiady z konstruktorem mają budować markę i ekspertyzę, a nie tylko sprzedawać domy.
      – A: Czy widzisz filmiki instruktażowe jako naturalne przedłużenie prototypu domu z Haetty — dokumentowanie tego, czego uczycie się z ekspertem?
      – B: Co byłoby pierwszym materiałem, który chciałbyś nagrać podczas budowy prototypu?
      – C: Jak rozdzielić treści, które budują markę, od tych, które wprost wspierają sprzedaż?

- (shared-thread)  [[26-06-05 - Planowanie budowy domu - materialy okna dach]], [[26-06-03 - Przygotowania do Eight Moons - okna i fundamenty kluczowe]], [[26-06-18 - 8Moons Projekt filmikow instruktazowych dla 8moons 2]]
    Okna i koszty materiałów wracają jako powtarzające się wąskie gardło: brak odpowiedzi producentów okien, przekroczone budżety i poszukiwanie tańszych ekwiwalentów.
      – A: Czy warto stworzyć jedną listę krytycznych materiałów z terminami i statusem dostawców, skoro okna pojawiają się jako blokada w wielu notatkach?
      – B: Co realnie zmienia przekroczenie budżetu (okna 20 vs 10 tys.) dla decyzji o tańszych zamiennikach?
      – C: Kiedy najpóźniej musi zapaść decyzja o dostawcach, by nie opóźnić startu w sierpniu?

- (shared-thread)  [[26-06-18 - 8Moons Projekt filmikow instruktazowych dla 8moons 2]], [[26-04-23 - Haetta - Planowanie projektu Miszy tiny house i harmonogram pracy]], [[26-06-03 - Antresola okno i wyceny decyzje dotyczace projektu bud]]
    Powtarza się pytanie o rentowność pracy dla klienta Miszy i napięcie między dogadzaniem życzeniom klienta a opłacalnością i spójnością designu.
      – A: Czy chciałbyś określić próg, poniżej którego projekt dla Miszy przestaje być opłacalny przy danym zaangażowaniu zespołu?
      – B: Jak chronić spójność designu (jak przy odrzuceniu antresoli), gdy klient chce 'zrobić wszystko'?
      – C: Czy ten projekt jest bardziej inwestycją w naukę procesu niż w zysk — i czy to zmienia kalkulację?

- (emergent-idea)  [[26-06-03 - Harmonogram i organizacja 2-tygodniowego projektu budowla]], [[26-06-03 - Przygotowania do Eight Moons - okna i fundamenty kluczowe]], [[26-04-23 - Haetta - Planowanie projektu Miszy tiny house i harmonogram pracy]], [[26-06-18 - 8Moons Projekt filmikow instruktazowych dla 8moons 2]]
    Łącząc prefabrykację elewacji, dwutygodniowy intensywny tryb pracy, harmonogram dnia i optymalizację procesu tak, by wykonywali go inni, rysuje się powtarzalny, skalowalny model produkcji domów.
      – A: Czy te elementy układają się w jeden 'playbook' produkcji domu, który mógłby prowadzić zespół wykonawczy bez was?
      – B: Które kroki muszą być prefabrykowane wcześniej, by dwutygodniowy montaż na miejscu był naprawdę minimalny?
      – C: Co trzeba opisać po prototypie z Piotrkiem, by proces dało się powtórzyć i skalować?


## B  + distance (bridges + baseline prompt)

found 6 (contradiction-over-time=1, emergent-idea=1, shared-thread=4)

- (shared-thread)  [[26-04-20 - Projekt Haetta- Wymagania Miszki i wyzwania konceptu]]  ⟵ MOST, [[26-06-03 - Antresola okno i wyceny decyzje dotyczace projektu bud]], [[26-06-18 - 8Moons Projekt filmikow instruktazowych dla 8moons 2]]
    Projekt dla klienta Miszy powraca przez miesiące — od rozbieżności konceptu i pomysłu antresoli, przez jej odrzucenie, aż po pytanie o rentowność przy zaangażowaniu zespołu.
      – A: Czy chciałbyś zebrać w jednym miejscu wszystkie decyzje dotyczące projektu Miszy, żeby zobaczyć, jak ewoluowały wymagania i ograniczenia?
      – B: Co by się zmieniło, gdybyś teraz wprost rozliczył rentowność tego projektu wobec wcześniejszych założeń budżetowych (250 tys.)?
      – C: Czy warto rozważyć, które życzenia klienta najczęściej kolidują z waszą koncepcją designu?

- (shared-thread)  [[26-06-05 - Planowanie budowy domu - materialy okna dach]], [[26-06-18 - 8Moons Projekt filmikow instruktazowych dla 8moons 2]], [[26-06-03 - Przygotowania do Eight Moons - okna i fundamenty kluczowe]], [[26-06-17 - Haetta - rozmowa z konstruktorem]]
    Przekroczenia budżetu materiałów, poszukiwanie tańszych ekwiwalentów (Wełmex zamiast Steiko) oraz okna jako wąskie gardło wracają w wielu notatkach o budowie.
      – A: Czy mógłbyś stworzyć jedną listę krytycznych materiałów (okna, elewacja, płyty) z aktualnym statusem dostępności i ceną vs. założenia?
      – B: Jak pogodzić presję na obniżenie kosztów z trzema filarami jakości (materiały naturalne, design, smart home)?
      – C: Co stanowi największe ryzyko terminowe — dostawa płyt czy odpowiedź producentów okien?

- (shared-thread)  [[26-06-03 - Harmonogram i organizacja 2-tygodniowego projektu budowla]], [[26-06-03 - Przygotowania do Eight Moons - okna i fundamenty kluczowe]], [[26-06-05 - Planowanie budowy domu - materialy okna dach]], [[26-06-24 - bie ogarnac powiedzmy sami sniadania w kolakcie]]
    Pojawia się powtarzający się wątek organizacji dwutygodniowego intensywnego okresu budowy — harmonogram dnia, gotowanie/śniadania, gotowość materiałów przed startem.
      – A: Czy chciałbyś połączyć te elementy w jeden plan operacyjny dwóch tygodni (harmonogram dnia + catering + checklist materiałów)?
      – B: Która zależność jest naprawdę blokująca start — plany budowlane, materiały czy obsada zespołu?
      – C: Co musiałoby być gotowe na 15 lipca, żeby start w sierpniu był realny?

- (shared-thread)  [[26-06-04 - Potencjal wizualizacji AR w e-commerce i uslugach projekt]], [[26-06-24 - Projekt BOS przygotowanie demo generowania assetow AI]]
    Oba projekty wyrastają z tej samej technologii wizualizacji (ART/dywany) i dotyczą generowania oraz porównywania assetów wizualnych jako oferty komercyjnej.
      – A: Czy demo BOŚ mogłoby też posłużyć jako materiał pokazowy dla pomysłu rozszerzenia AR na meble/ogrody/usługi?
      – B: Co łączy te kierunki — wspólny silnik, wspólny rynek profesjonalistów, czy jedno i drugie?
      – C: Czy warto sformułować jedną strategię produktową dla rodziny rozwiązań wizualizacyjnych?

- (emergent-idea)  [[25-11-19 - Rozwoj dzialalnosci opartej na warsztatach i agroturystyce]]  ⟵ MOST, [[26-04-16 - Analiza modelu biznesowego - oblozenie i strategie cenowe]]  ⟵ MOST, [[26-06-18 - 8Moons Projekt filmikow instruktazowych dla 8moons 2]], [[26-06-18 - 8Moons Projekt filmikow instruktazowych dla 8moons]]
    Pomysły na agroturystykę, model subskrypcyjny domków, budowanie marki przez wywiady/filmy i meble autorskie układają się w jeden ekosystem biznesowy oparty na ekspertyzie, a nie tylko na sprzedaży pojedynczych domów.
      – A: Czy chciałbyś spisać te rozproszone pomysły jako jeden model: dom + treści edukacyjne + subskrypcja + agroturystyka?
      – B: Który element najlepiej buduje markę i ekspertyzę przy minimalnym budżecie — filmy, prototyp, czy katalog mebli?
      – C: Co by oznaczało potraktowanie treści (filmy instruktażowe) jako produktu, a nie tylko marketingu?

- (contradiction-over-time)  [[25-11-19 - Rozwoj dzialalnosci opartej na warsztatach i agroturystyce]]  ⟵ MOST, [[26-06-18 - 8Moons Projekt filmikow instruktazowych dla 8moons 2]]
    W listopadzie nacisk był na samodzielne wykonawstwo (każdy domek i mebel zrobiony przeze mnie), a w czerwcu pojawia się refleksja, że proces trzeba zoptymalizować tak, by pracę wykonywali inni specjaliści, a nie zespół założycielski.
      – A: Czy zmiana z 'robię sam' na 'zarządzam procesem' jest świadomą decyzją, czy reakcją na zmęczenie/koszty?
      – B: Gdzie nadal warto zachować osobiste rzemiosło jako wyróżnik, a gdzie delegować?
      – C: Co ta zmiana oznacza dla tożsamości marki opartej na autorstwie?


## C  + distance + sharp prompt

found 4 (contradiction-over-time=2, emergent-idea=2)

- (contradiction-over-time)  [[26-06-18 - 8Moons Projekt filmikow instruktazowych dla 8moons 2]], [[26-06-18 - 8Moons Projekt filmikow instruktazowych dla 8moons]]
    W jednej notatce z tego samego dnia mówisz, że materiały edukacyjne w Polsce są w większości 'dziadowskie', a tworzenie własnych filmików to atrakcyjny kierunek rozwoju przy minimalnym budżecie i gotowych narzędziach. W drugiej, równoległej notatce stawiasz pod znakiem zapytania sens angażowania zespołu założycielskiego w pracę, która nie jest bezpośrednio związana ze sprzedażą domów. To napięcie: ten sam temat 'budowania marki' raz wygląda na okazję bez kosztów, raz na rozproszenie zasobów.
      – A: Czy mógłbyś rozdzielić, które działania faktycznie sprzedają domy, a które budują markę 'na zapas'?
      – B: Co by się stało, gdyby filmiki instruktażowe robił ktoś spoza zespołu założycielskiego?
      – C: Jak zmierzyłbyś, czy 'ciekawy kierunek' realnie przyciąga klientów, a nie tylko widzów?

- (emergent-idea)  [[26-06-04 - Potencjal wizualizacji AR w e-commerce i uslugach projekt]], [[26-06-24 - Projekt BOS przygotowanie demo generowania assetow AI]], [[26-06-03 - Antresola okno i wyceny decyzje dotyczace projektu bud]]
    W notatce o AR wskazujesz, że wizualizacje są nieopłacalne masowo przez wysoki koszt jednostkowy, a sens mają tylko dla profesjonalistów. W BOŚ właśnie budujesz tani i szybki silnik generowania assetów AI, a w projekcie Miszy ręcznie szykujesz rendery wnętrza i konfigurację kamery. Połączone razem sugerują, że tania generacja AI mogłaby zbić koszt jednostkowy wizualizacji na tyle, by domknąć model AR dla masowego rynku — i jednocześnie odciążyć ręczne rendery przy projektach budowlanych.
      – A: Czy ten sam silnik z BOŚ mógłby generować rendery wnętrz domków, zamiast robić je ręcznie?
      – B: Gdyby koszt wizualizacji spadł dziesięciokrotnie, czy rynek konsumencki AR znów staje się opłacalny?
      – C: Co łączy 'tanio i szybko' z BOŚ z barierą kosztową, którą opisałeś przy AR?

- (contradiction-over-time)  [[26-04-20 - Projekt Haetta- Wymagania Miszki i wyzwania konceptu]]  ⟵ MOST, [[26-06-18 - 8Moons Projekt filmikow instruktazowych dla 8moons 2]]
    W kwietniu projekt Miszy jawi się jako szansa i 'testowanie konceptu' z budżetem 250 tys. zł i zaangażowanym klientem. W czerwcu, po przekroczeniu kosztów materiałów (okna i elewacja podwojone), wprost kwestionujesz rentowność — czy zarobek 30 tys. zł przy takim nakładzie pracy w ogóle ma sens. To zmiana stanowiska wobec tego samego klienta: od obiecującego testu do wątpliwego biznesu.
      – A: Czy mógłbyś prześledzić, w którym momencie koszty materiałów rozjechały się z założeniami?
      – B: Co odróżniałoby 'test konceptu wart strat' od projektu po prostu nierentownego?
      – C: Jakie warunki musiałby spełnić kolejny klient typu Misza, żebyś wszedł w projekt świadomie?

- (emergent-idea)  [[26-04-16 - Analiza modelu biznesowego - oblozenie i strategie cenowe]]  ⟵ MOST, [[26-06-18 - 8Moons Projekt filmikow instruktazowych dla 8moons 2]]
    W analizie modelu biznesowego wariant premium uzasadniasz tym, że 'świadomi klienci' ułatwiają zarządzanie obiektem. Niezależnie, przy filmikach instruktażowych rozważasz budowanie marki i ekspertyzy niepowiązanej wprost ze sprzedażą. Razem rodzi się idea, że treści edukacyjne nie są kosztem marketingowym, lecz narzędziem selekcji właśnie tych świadomych, premium klientów, którzy domykają model 50% obłożenia.
      – A: Czy materiały edukacyjne mogłyby celowo przyciągać klientów premium z wariantu drugiego?
      – B: Jak rozpoznać, czy widz filmików to przyszły świadomy klient, a nie przypadkowy odbiorca?
      – C: Czy treść mogłaby być częścią oferty subskrypcyjnej, a nie tylko promocją?
