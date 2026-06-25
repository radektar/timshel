# Insights UI — brief do Claude Design (oba kierunki, decyzja popover vs okno)

> Następca `insight-card-brief.md`. Tamten dał pierwszy prototyp (`insight-surface.html`):
> kartę-popover (A) w pełni + okno (B) jako jedna klatka. **Decyzja A vs B jeszcze nie zapadła** —
> ten brief prosi o **oba kierunki dociągnięte do równej, porównywalnej, decyzyjnej jakości**,
> osadzone w finalnym modelu nawigacji. Importuj `../tokens.css`. Reużyj silnika konstelacji
> z `insight-surface.html` (gotowy inline-SVG generator: węzły + łuki + złoty rozbłysk).

---

## 0. Co się zmieniło od poprzedniego briefu (przeczytaj najpierw)

Przesądziliśmy **model nawigacji** — Malinche idzie ścieżką Dockera:

- **Pilot = systemowe menu (`NSMenu`).** Klik w ikonę menu-bar otwiera **natywne menu macOS**
  (jak Docker Desktop / Cursor), nie naszą powierzchnię. Tego **NIE projektujemy** jako custom —
  rysujemy je tylko wiernie jako natywne, żeby pokazać *wejście* do Insights. System rysuje je sam.
- **Dom = powierzchnia „Insights"** — tu żyje cały brand i magia. Wchodzi się w nią **z pozycji menu**
  (`✦ Nowy insight (N)` / `Otwórz Malinche`) albo **klikiem w powiadomienie** — nie klikiem w ikonę.

Wcześniej karta-insightu była celem kliku w ikonę. Teraz jest **osobną powierzchnią uruchamianą z menu**.

**Jedyne pytanie, które ten design ma rozstrzygnąć:** czym ma być „Insights" — **popover** czy **okno**.

---

## 1. Decyzja do rozstrzygnięcia na obrazie: popover vs okno

To nie różnica techniczna, tylko **zachowania**. Designy mają tę różnicę *uczynić widoczną*, żeby
decyzja zapadła na kadrach, nie w teorii.

| | **A · Popover** (karta pod ikoną) | **B · Okno** (Dashboard) |
|---|---|---|
| Charakter | „zerknąć i zniknąć" | „usiąść, czytać, wracać" |
| Znika gdy | klikniesz obok → **zamyka się** | zostaje aż je zamkniesz |
| Rozmiar | stały, mały (~340 px) | resizable, duże |
| Wiele naraz / drugi monitor | nie | tak |
| Build natywny | niski (mamy `NSPopover`) | większy (`NSWindow` + chrome) |

**Argument rozstrzygający, który designy muszą obsłużyć:** chipy notatek linkują do Obsidiana
(„Otwórz w Obsidian"). To znaczy, że użytkownik **wychodzi z apki w trakcie czytania** — popover
wtedy **znika**, okno **zostaje**. Pokaż tę konsekwencję wprost (np. mała klatka „klikasz notatkę →
popover gaśnie" vs „okno trwa obok edytora").

---

## 2. Co zaprojektować (porównywalnie)

Trzy bloki + sygnał. **A i B mają być równej rangi** — to porównanie, nie „główny + dodatek".

### Blok S · Systemowe menu (support, natywne — nie custom)
Jedna klatka wiernego **natywnego `NSMenu`** w stylu Docker/Cursor (zob. referencje w sekcji 9),
pokazująca *wejście* do Insights. Regiony od góry:
- **status-header** (wyłączona pozycja): kolorowa kropka + tekst — `● Malinche — Spoczynek`
  (jadeit) / `● Malinche — Transkrybuję…` (terakota). Dokładnie jak „● Docker Desktop is running".
- `✦ Nowy insight (3)` — pozycja-wejście; licznik = liczba niezobaczonych połączeń.
- `Otwórz Malinche` — otwiera powierzchnię Insights (A lub B — to testujemy).
- separator · `Importuj audio…` · `Najnowszy digest…` · `Ustawienia… ⌘,` · separator · `Zakończ ⌘Q`.
Renderuj jako natywne (ciemne/jasne systemowe), z lekkimi ikonami SF po lewej (jak Docker).
**Nie** stylizuj go naszymi tokenami — to celowo systemowy chrome.

### Blok A · Insights jako **popover**
Pełny zestaw (jak w `insight-surface.html`, ale dociągnięty i samodzielny):
- 3 typy połączeń: `contradiction-over-time`, `shared-thread`, `emergent-idea` — różny układ węzłów,
  ta sama gramatyka.
- nawigacja `‹ 1/N ›` (kadr z N=3).
- stan **Zachowaj** (mikro-rozbłysk + „zachowane") i **Odrzuć** (cicho znika).
- stan **pusty / po przejrzeniu** (spokojny, nie smutny).
- **klatka konsekwencji:** klik w chip notatki → popover gaśnie (uzasadnia ograniczenie powierzchni).

### Blok B · Insights jako **okno (Dashboard)**
To jest **dom**. Struktura z Dockera jako wskazówka (samodzielne okno, lekka lewa szyna/aktywność,
obszar treści) — **ale zawężone do Insights, nie klon Dockera.** Malinche jest cicha. Zaprojektuj:
- **chrome okna** (natywny title-bar macOS lub własny ciemny — rekomendacja: ciemny, bo konstelacja
  świeci tylko na ciemnym), tytuł „Malinche — Konstelacja", licznik `połączenie 3 z 7`.
- **lewa szyna / lista połączeń** — N połączeń jako lista (typ + 1-linijkowy skrót rationale),
  zaznaczone aktywne. To czego popover nie ma: *przeglądasz korpus*, nie jedno naraz.
- **czytnik** (główny obszar): żywa konstelacja (estetyka hero, większa) → pod spodem typ, rationale
  (pull-quote), chipy notatek, kierunki, Zachowaj/Odrzuć.
- opcjonalnie **pasek aktywności / ostatnie transkrypty** (reużywa `PanelModel` z kodu) — drugi powód,
  dla którego okno ma sens (jest dom, nie tylko jeden insight).
- stany: po rozbłysku (żywy kadr), pusty, wiele połączeń.
- **klatka konsekwencji:** okno trwa obok otwartego Obsidiana (kontra do A).

### Blok sygnał (support)
- **ikona menu-bar**: spoczynek vs „czeka insight" (dyskretny **złoty punkt + poświata**, `--status-insight`).
- **powiadomienie**: niesie **samą tezę** (rationale), nie „New digest ready". Klik → otwiera Insights.

---

## 3. Anatomia (regiony)

**Popover (A)** — szer. ~340 px, ciemny:
```
✦ Nowy insight                         ‹1/3›
        [ MINI-KONSTELACJA ]
● Sprzeczność w czasie
„17.06 projekt stoi na naturalnych materiałach…
 18.06 — budżet przekroczony 2×, obniżasz jakość."
◇ Haetta — rozmowa…   ◇ 8Moons — filmiki 2
──────────────────────────────────────────
Kierunki
· Co wymusiło zmianę założenia jakościowego?
· Bronić filarów mimo budżetu?
[ Zachowaj ]                      [ Odrzuć ]
```

**Okno (B)** — szer. ~700–900 px, ciemny:
```
┌ Malinche — Konstelacja ───────────────── połączenie 3 z 7 ┐
│ ┌ POŁĄCZENIA ─┐ ┌ CZYTNIK ───────────────────────────────┐│
│ │● Sprzeczność │ │          [ ŻYWA KONSTELACJA ]          ││
│ │  emergentny  │ │ ● Emergentny pomysł                    ││
│ │  wspólny wątek│ │ „W różnych projektach wraca ten sam… "  ││
│ │  …            │ │ ◇ Strategia… ◇ 8Moons… ◇ Harmonogram…  ││
│ │              │ │ Kierunki · … · …                       ││
│ │ (aktywność)  │ │ [ Zachowaj ]              [ Odrzuć ]    ││
│ └──────────────┘ └────────────────────────────────────────┘│
└────────────────────────────────────────────────────────────┘
```
Hierarchia w obu: **konstelacja + rationale to bohaterowie**; typ, źródła, kierunki, akcje podporządkowane.
Rationale ma czytać się jak *myśl*, nie jak wiersz logu.

---

## 4. Konstelacja — reuse, nie reinvent

Silnik jest gotowy w `insight-surface.html` (inline-SVG: `constellation(layout, opts)` — węzły z radialną
poświatą, łuki quadratic-bezier, złoty rozbłysk; 3 layouty: `contradiction` / `thread` / `triad`;
animacja wejścia respektująca `prefers-reduced-motion`). **Użyj go 1:1**, tylko skaluj:
mini w popoverze (~300×150), duża w oknie (~520×230). Gramatyka wizualna: `hero-graph-redesign-brief.md` §6.
Węzły = notatki (`--terracotta`), łuki = połączenie, rozbłysk = insight (`#D6B033`/`#F4DD8E`).
W natywnym porcie → Core Graphics w `NSView.drawRect_`; prototyp to spec.

---

## 5. Tokeny, typografia, kolor (z `tokens.css` — kanon v2)

- **Powierzchnia Insights: ciemna** (`--obsidian` / `#110F16`) — świadomy wyjątek; konstelacja i rozbłysk
  *świecą tylko na ciemnym*. Reszta apki bywa jasna/systemowa; Insights to „okno w konstelację".
- **Rationale (pull-quote):** `--font-display` (**Neue Montreal** — kanon v2 zastąpił Fraunces),
  `--leading-snug`, kolor `--content-contrast` na ciemnym. To jedyne miejsce „głosu".
- **Etykiety/UI/kierunki:** `--font-body` (Neue Haas Grotesk). Eyebrow uppercase `--tracking-eyebrow`.
- **Akcenty:** insight/rozbłysk = `--status-insight` (gold `#D6B033`, glow `#F4DD8E`);
  połączenia/węzły = `--terracotta`/`--terracotta-lit`; „Zachowaj" = jadeit `--status-local`;
  „Odrzuć" = ghost/neutralny.
- **Promienie/cień:** popover `--radius-3xl`; chipy `--radius-pill`; `--shadow-float`;
  border na ciemnym `--border-on-dark`. Okno: natywne radii macOS lub `--radius-2xl`.
- **Motyw:** opcjonalny `--motif-greca` jako cienki dolny fryz — sygnaturowy, nie obowiązkowy.
- **Uwaga implementacyjna (nie wpływa na prototyp):** natywna apka zostaje na **fontach systemowych (SF)** —
  display→SF Pro, body→SF Pro Text. Prototyp używa fontów brandowych jako spec wyglądu; port mapuje na SF.

---

## 6. Stany i interakcje (pokaż na makietach)

1. **Spoczynek vs czeka insight** — ikona menu-bar + status-header w menu (oba stany).
2. **Wejście** — z pozycji menu / z powiadomienia → powierzchnia z pierwszym połączeniem.
3. **Wiele połączeń** — A: `‹ 1/N ›`; B: lista po lewej. Kadr N=3 / N=7.
4. **Trzy typy** — po kadrze dla każdego (różny układ węzłów, ta sama gramatyka).
5. **Zachowaj** — mikro-rozbłysk + „zachowane"; połączenie znika z kolejki.
6. **Odrzuć** — znika; cicho.
7. **Pusto/po przejrzeniu** — „brak nowych połączeń" (spokojny).
8. **Konsekwencja powierzchni** — A: klik notatki → popover gaśnie · B: okno trwa obok Obsidiana.

---

## 7. Realna treść do makiet (dane Radka — NIE lorem ipsum)

Model jednego połączenia: `type` (1 z 3) · `notes[]` (≥2, basenamy) · `rationale` (1 zdanie) ·
`directions[]` (2–4, jako pytania/zaproszenia). Użyj tych trzech realnych (digest na korpusie 8moons):

**1. contradiction-over-time** — notatki: `Haetta — rozmowa z konstruktorem` (17.06),
`8Moons — filmiki 2` (18.06).
rationale: „17.06 projekt stoi na naturalnych materiałach i jakości dla świadomego klienta; 18.06 —
budżet przekroczony 2×, rozważasz obniżenie jakości materiałów."
directions: „Co wymusiło zmianę założenia jakościowego?" · „Czy filary projektu trzeba zrewidować, czy bronić mimo budżetu?"

**2. shared-thread** — notatki: `Planowanie budowy domu — materiały okna dach` (05.06),
`Przygotowania do Eight Moons — okna i fundamenty` (03.06).
rationale: „Okna wracają w obu notatkach jako krytyczne wąskie gardło — brak odpowiedzi producentów
i niepewna dostępność przed sierpniem."
directions: „Poszukać alternatywnych producentów już teraz?" · „Jak wyglądałby plan B na okna?"

**3. emergent-idea** — notatki: `Strategia TekTutoreski` (01.06), `8Moons — filmiki 2` (18.06),
`Harmonogram 2-tyg. projektu` (03.06).
rationale: „W różnych projektach wraca ten sam dylemat: skalować przez automatyzację/oddanie pracy,
czy utrzymać ręczny udział kosztem skali."
directions: „Czy to jedna ‚zasada skalowania', którą stosujesz wszędzie?" · „Gdzie hands-on buduje jakość, a gdzie tylko blokuje skalę?"

---

## 8. Locked vs open

**Locked:** model nawigacji (menu systemowe = pilot, Insights = dom uruchamiany z menu/powiadomienia);
moment szum→połączenie→rozbłysk; pokazywane dane (typ, rationale, źródła, kierunki); Zachowaj/Odrzuć;
tokeny i kanon v2 (Neue Montreal, nie Fraunces); brak emoji; ton (`Docs/TONE-OF-VOICE.md`); ciemna
powierzchnia Insights; reduced-motion fallback; konstelacja w gramatyce hero.

**Open (do interpretacji Claude Design):** czy zwycięża A czy B (to projektujemy, żeby zdecydować);
dokładny layout okna B (lewa szyna vs zakładki; czy aktywność jest w oknie); chrome okna (natywny vs
ciemny custom); styl listy połączeń; traktowanie rozbłysku; chrome chipów/przycisków; animacje;
jak różnią się 3 typy wizualnie; ikonografia w menu systemowym.

---

## 9. Ograniczenia, kontekst, referencje

- **Cel = natywny AppKit.** Prototyp HTML to spec wyglądu, nie kod do wdrożenia. Trzymaj się tego, co
  odwzorowalne w Core Graphics / `NSPopover` / `NSWindow` / natywnym `NSMenu`.
- **Menu = natywne, nie projektujemy go.** Rysujemy tylko wierny mock dla pełni przepływu wejścia.
- **Wymiary:** popover (A) kotwiczony pod ikoną, ~320–360 px. Okno (B) ~700–900 px, resizable.
- **macOS, light/dark systemowy** dla menu; Insights rekomendowane jako ciemne niezależnie (uzasadnienie §5).
- **Dostępność:** kontrast na ciemnym; `prefers-reduced-motion`; polskie diakrytyki.
- **Ton/copy:** `Docs/TONE-OF-VOICE.md` — bez „drugi mózg", bez hype, bez emoji; etykiety krótkie, polskie;
  cicha puenta, nie pitch.
- **Referencje modelu nawigacji:** Docker Desktop (menu-bar `NSMenu` + osobne okno Dashboard) i Cursor
  (minimalne systemowe menu) — Radek dostarczył zrzuty. Bierzemy **strukturę przepływu** (pilot + dom),
  nie ich paletę.
- **Reuse z repo:** silnik konstelacji i wariant v1 → `pages/insight-surface.html`; gramatyka hero →
  `pages/hero-graph-redesign-brief.md`; tokeny → `tokens.css`; poprzedni brief → `pages/insight-card-brief.md`.

---

## 10. Deliverable

Samodzielny prototyp HTML/CSS importujący `../tokens.css`, z ramkami:

- **S** · systemowe menu (1 klatka, natywny styl, z wejściami do Insights).
- **A** · popover — 3 typy + Zachowaj + N=3 + pusty + klatka „popover gaśnie".
- **B** · okno/Dashboard — layout z listą połączeń + czytnik, kadr po rozbłysku + pusty + klatka „okno trwa obok Obsidiana".
- **sygnał** · ikona menu-bar (2 stany) + powiadomienie (1).

Konstelacje jako inline SVG w gramatyce hero (reuse silnika). A i B obok siebie, równej jakości — to porównanie.

Po prototypie: decyzja **A vs B** → osobny plan portu do AppKit (`src/ui/`: `insight_panel.py` na wzór
`status_panel.py` dla A, lub nowy `dashboard_window.py` dla B; konstelacja w `NSView.drawRect_`; pipeline
danych — pełne `rationale`/`directions`/`notes` do UI, dziś leci sama nazwa pliku).
