# Insight surface — design brief for Claude Design

Malinche znajduje połączenia między notatkami (sprzeczności w czasie, wspólne wątki, emergentne pomysły), ale dziś **dostarcza je jako plik .md w folderze + płaskie powiadomienie**. Moment „Malinche coś zauważyła" jest niewidoczny — zero magii. Landing obiecuje *złoty rozbłysk insightu* (zob. `hero-graph-redesign-brief.md`); aplikacja go nie dotrzymuje.

Ten brief prosi o **wizualny prototyp powierzchni in-app**, na której pojawienie się insightu *czuć*. Aplikacja jest natywna (macOS menu-bar, PyObjC/AppKit) — **prototyp HTML/CSS to specyfikacja wyglądu do decyzji; implementacja będzie natywna (Core Graphics + NSPopover).** Importuj `design-system/tokens.css`.

---

## 1. Moment, który to reprezentuje (nie zgubić)

To samo, co hero landingu, ale **wewnątrz apki, na notatkach użytkownika**: *Szum → Połączenie → złoty rozbłysk insightu.* Hero ma już kompletny render tego (`drawComm` = terakotowy węzeł z poświatą, łuki quadratic-bezier, `bloom` = złoty rozbłysk — zob. `hero-graph-redesign-brief.md` §6). **Karta insightu = ta sama grafika, zmniejszona do 2-3 węzłów** (notatek danego połączenia). Ton: „cichy punchline" z `Docs/TONE-OF-VOICE.md` — bez krzyku, bez emoji, jedno tapnięcie i mały piękny reveal.

---

## 2. Co zaprojektować (dwa kierunki obok siebie + wsparcie)

Decyzja zapadnie na obrazie — więc **wyrenderuj oba główne kierunki jako osobne ramki**, plus dwa drobne elementy wsparcia.

- **A (główny, rekomendowany v1) — „Karta insightu" (popover).** NSPopover spod ikony menu-bar. Mała konstelacja + jedno połączenie naraz, nawigacja `‹ 1/N ›`. Reużywa istniejący panel — niskie ryzyko.
- **B (do porównania) — „Żywa konstelacja" (okno).** Większe okno-czytnik: żywy graf notatek (estetyka hero), nowe połączenie zapala węzły → łuk → złoty rozbłysk; pod spodem detale. Maksymalna magia, większy build. Wyrenderuj **jedną reprezentatywną klatkę** (stan „po rozbłysku").
- **Sygnał w menu-bar:** ikona z dyskretnym **złotym punktem/poświatą** (`--status-insight`), gdy czeka niezobaczony insight. Pokaż stan spoczynku vs. „czeka insight".
- **Powiadomienie (teaser):** zamiast „New digest ready" — niesie samą tezę. Makieta natywnego powiadomienia macOS z treścią rationale.

---

## 3. Anatomia karty insightu (kierunek A)

Szerokość ~340 px (jak istniejący panel). Regiony od góry:

```
┌─ INSIGHT CARD ───────────────────────────┐
│  ‹eyebrow›  ✦ Nowy insight        ‹1/3›   │  ← złoty znacznik + label + licznik
│                                           │
│            [ MINI-KONSTELACJA ]           │  ← sekcja 4 (hero: węzły+łuk+rozbłysk)
│                                           │
│  ‹typ›  Sprzeczność w czasie              │  ← etykieta typu (złoto/terakota)
│                                           │
│  „Chłodzenie powietrzem miało wystarczyć  │  ← RATIONALE: Fraunces serif, pull-quote
│   — miesiąc później piszesz, że trzeba    │
│   wody."                                  │
│                                           │
│  ◇ Cooling v1     ◇ Cooling v2            │  ← źródła = chipy (klik → otwórz w Obsidian)
│  ───────────────────────────────────────  │
│  Kierunki                                 │  ← 2-4 niedyrektywne, ciche
│  · Co wymusiło zmianę zdania?             │
│  · Inne decyzje tego projektu w czasie?   │
│                                           │
│  [ Zachowaj ]                 [ Odrzuć ]  │  ← sygnał walidacji (keep = pozytyw)
└───────────────────────────────────────────┘
```

Hierarchia: **konstelacja + rationale to bohaterowie**; typ, źródła, kierunki, akcje są podporządkowane. Rationale ma czytać się jak *myśl*, nie jak wiersz logu.

---

## 4. Mini-konstelacja (rdzeń „magii") — reuse hero

Język wizualny z `hero-graph-redesign-brief.md` §6, zmniejszony:

- **Węzły = notatki połączenia** (2-4). Terakotowy rdzeń `#C24010` + radialna poświata (gradient `rgba(217,84,42,.55) → rgba(194,64,16,0)`), jasny rdzeń `#FAF3E2`.
- **Łuki = połączenie.** Quadratic-bezier, `rgba(217,84,42,.92)`, `shadowColor rgba(194,64,16,.6)` blur. Między węzłami.
- **Złoty rozbłysk = insight.** Nad/między węzłami: gradient `rgba(244,221,142,.92) → rgba(214,176,51,0)`, pierścienie, biały rdzeń `#FFFBF0`. To pointa kadru.
- Tło sekcji: ciemna scena (jak hero: radial `#20202B → #110F16`).
- **W prototypie:** statyczne **inline SVG** (kółka z radial-gradient, ścieżka łuku, koło rozbłysku). **W implementacji:** Core Graphics w `NSView.drawRect_`.
- **Mapowanie:** 2 notatki → 2 węzły + 1 łuk + rozbłysk powyżej; 3 → trójkąt + łuki + rozbłysk w środku. Liczba węzłów = liczba notatek połączenia.
- Opcjonalnie (open): delikatna animacja wejścia (łuk się rysuje → rozbłysk rozkwita, ~600 ms) — respektuj `prefers-reduced-motion` (od razu stan końcowy).

---

## 5. Typografia, kolor, tokeny (z `tokens.css`)

- **Rationale (pull-quote):** `--font-serif` Fraunces, `--leading-snug` 1.34, kolor `--content-contrast` (`#FAF3E2`) na ciemnym. Jedyne miejsce serifu — niesie „myśl".
- **Etykiety/UI/kierunki:** `--font-sans` Inter. Eyebrow uppercase `--tracking-eyebrow`.
- **Akcenty:** insight/rozbłysk = `--status-insight` (`--gold #D6B033`, glow `#F4DD8E`). Połączenia/węzły = `--terracotta`/`--terracotta-lit`. „Zachowaj" = subtelny `--jade`. „Odrzuć" = ghost/neutral.
- **Powierzchnia:** karta **ciemna** (`--surface-hero #110F16` / `--obsidian`) — konstelacja i rozbłysk *świecą tylko na ciemnym tle*. Świadomy wyjątek: reszta apki bywa jasna/systemowa, ale insight to „okno w konstelację".
- **Promienie/cień:** karta `--radius-4xl` (28px) lub `--radius-3xl`; chipy `--radius-pill`; `--shadow-float`. Border na ciemnym: `--border-on-dark`.
- **Motyw:** opcjonalny `--motif-greca` jako cienki dolny fryz (jak hero) — sygnaturowy, nie obowiązkowy.

---

## 6. Stany i interakcje (pokaż na makietach)

1. **Spoczynek vs. czeka insight** — ikona menu-bar (złoty punkt) w obu stanach.
2. **Otwarcie** — popover (A) / okno (B) z pierwszym połączeniem.
3. **Wiele połączeń** — `‹ 1/N ›`; kadr z N=3.
4. **Trzy typy** — po jednym kadrze dla `contradiction-over-time`, `shared-thread`, `emergent-idea` (różny układ węzłów, ta sama gramatyka).
5. **Zachowaj** — mikro-feedback (złoty błysk + „zachowane"); połączenie znika z kolejki.
6. **Odrzuć** — znika; cicho.
7. **Pusto/po przejrzeniu** — stan „brak nowych połączeń" (spokojny, nie pusty-smutny).

---

## 7. Realna treść do makiet (dane Radka — NIE lorem ipsum)

Model danych jednego połączenia: `type` (1 z 3) · `notes[]` (≥2, basenamy) · `rationale` (1 zdanie) · `directions[]` (2-4, jako pytania/zaproszenia). Użyj tych trzech realnych (z prawdziwego digestu na korpusie 8moons):

**1. contradiction-over-time** — notatki: `Haetta — rozmowa z konstruktorem` (17.06), `8Moons — filmiki 2` (18.06).
rationale: „17.06 projekt stoi na naturalnych materiałach i jakości dla świadomego klienta; 18.06 — budżet przekroczony 2×, rozważasz obniżenie jakości materiałów."
directions: „Co wymusiło zmianę założenia jakościowego?" · „Czy filary projektu trzeba zrewidować, czy bronić mimo budżetu?"

**2. shared-thread** — notatki: `Planowanie budowy domu — materiały okna dach` (05.06), `Przygotowania do Eight Moons — okna i fundamenty` (03.06).
rationale: „Okna wracają w obu notatkach jako krytyczne wąskie gardło — brak odpowiedzi producentów i niepewna dostępność przed sierpniem."
directions: „Poszukać alternatywnych producentów już teraz?" · „Jak wyglądałby plan B na okna?"

**3. emergent-idea** — notatki: `Strategia TekTutoreski` (01.06), `8Moons — filmiki 2` (18.06), `Harmonogram 2-tyg. projektu` (03.06).
rationale: „W różnych projektach wraca ten sam dylemat: skalować przez automatyzację/oddanie pracy, czy utrzymać ręczny udział kosztem skali."
directions: „Czy to jedna ‚zasada skalowania', którą stosujesz wszędzie?" · „Gdzie hands-on buduje jakość, a gdzie tylko blokuje skalę?"

---

## 8. Co zablokowane vs. otwarte

**Locked:** moment i jego znaczenie (szum→połączenie→rozbłysk); pokazywane dane (typ, rationale, źródła, kierunki); Zachowaj/Odrzuć; tokeny marki; brak emoji; ton; reduced-motion fallback; rationale w Fraunces.

**Open (do interpretacji Claude Design):** dokładny układ karty; styl konstelacji (kropki vs glify, grubości, krzywe); traktowanie rozbłysku; jasna vs ciemna (rekomendacja: ciemna); chrome chipów/przycisków; ewentualna animacja wejścia; jak różnią się 3 typy wizualnie; layout okna (B).

---

## 9. Ograniczenia i kontekst

- **Cel = natywny AppKit.** Prototyp HTML to specyfikacja wyglądu, nie kod do wdrożenia. Trzymaj się tego, co odwzorowalne w Core Graphics/NSPopover.
- **Kontekst menu-bar:** popover (A) kotwiczony pod ikoną w prawym-górnym rogu; szerokość ~320-360 px. Okno (B) ~520-620 px.
- **macOS, light/dark systemowy** — karta insightu rekomendowana jako ciemna niezależnie (uzasadnienie §5).
- **Dostępność:** kontrast tekstu na ciemnym; `prefers-reduced-motion`; Polish diacritics (Fraunces i Inter wspierają).
- **Ton/copy:** `Docs/TONE-OF-VOICE.md` — bez „drugi mózg", bez hype, bez emoji; etykiety krótkie, polskie.

---

## 10. Deliverable

Samodzielny prototyp HTML/CSS importujący `tokens.css`, z ramkami: **A** (karta — 3 typy + stan keep + N=3 + pusty), **B** (okno — 1 klatka po rozbłysku), **sygnał menu-bar** (2 stany), **powiadomienie** (1). Konstelacje jako inline SVG w gramatyce hero.

Po prototypie: wybór A vs B + rejestru → osobny plan portu do AppKit (`src/ui/`: nowy `insight_panel.py` na wzór `status_panel.py`; konstelacja w `NSView.drawRect_`; dane z połączeń — wymaga dołożenia pełnych `rationale`/`directions` do tego, co trafia do UI, dziś leci sama nazwa pliku).
