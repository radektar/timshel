# Insights — okno: komponenty + stany — brief do Claude Design

> Następca `insights-ui-brief.md`. Tamten rozstrzygnął **A vs B** (wygrało okno/Dashboard) i ono jest
> wdrożone natywnie (`src/ui/dashboard_window.py`). Ten brief NIE projektuje powierzchni od zera — prosi
> o **redesign konkretnych komponentów okna i wszystkich ich stanów**, bo wdrożenie wyprzedziło design:
> doszły elementy, których Claude Design nigdy nie widział (segment triażu), a istniejące (checkboxy,
> pasek handoffu) wyglądają jak placeholdery, nie komponenty z systemu. Importuj `../tokens.css`.
> Reużyj silnika konstelacji/sygili z poprzednich prototypów.

---

## 0. Co jest teraz i dlaczego to brief (przeczytaj najpierw)

Okno działa, ale wizualnie się rozjeżdża. Konkretne zarzuty z dogfoodu (zrzut w ręku Radka):

1. **Segment triażu „Nowe / Zachowane / Odrzucone"** — najgorszy. Wygląda jak trzy surowe przyciski
   („Button Nowe") z licznikiem wciśniętym nad etykietę, obramowania nie trzymają linii. To **nowy
   komponent, którego nigdy nie zaprojektowano** — kod go dostawił, bo doszedł model 3-stanowy.
2. **Checkboxy kierunków** — puste kwadraty bez wagi, etykieta osadzona surowo. Stan zaznaczony istnieje
   w kodzie (terakotowy box + ✓), ale cały wiersz nie czyta się jak interaktywny komponent.
3. **Pasek handoffu / CTA „Kontynuuj w Claude"** — brand-mark słabo dopracowany, hierarchia z akcjami
   wtórnymi (ikony zadanie/kalendarz/schowek) niejasna, switcher (caret) to goły znak.
4. **Footer Zachowaj/Odrzuć** — Zachowaj jest teraz jadeitowy (dobrze), ale całość potrzebuje
   spójnych stanów (hover/pressed) i właściwej wagi.
5. **Stany hover/pressed** — dodaliśmy je w kodzie, ale „nie są zgodne z językiem wizualnym".

**Zadanie:** zaprojektuj te komponenty jako spójny zestaw z `tokens.css`, **z pełną siatką stanów**,
osadzone w realnym layoucie okna. To ma wyglądać jak rodzina z jednego systemu, nie jak sześć różnych
przycisków.

---

## 1. Model triażu — kontekst, bez którego segment nie ma sensu

Okno jest teraz **kolejką triażu** z trzema widokami. To napędza segment i większość stanów:

- **Nowe** — połączenia do przejrzenia (domyślny widok).
- **Zachowane** — to, co user zachował, żeby wrócić.
- **Odrzucone** — odrzucone, ale **odwracalne** (można odzyskać → wraca do Zachowanych).

`Zachowaj` przenosi aktywne połączenie do *Zachowane* i przeskakuje do następnego *Nowego*. `Odrzuć`
przenosi do *Odrzucone*. Segment przełącza widok szyny i czytnika. Każdy widok ma własny stan pusty.

To znaczy, że segment **nie jest dekoracją** — to główna nawigacja okna. Musi czytać się jak segmented
control rangi systemowej (myśl: macOS segmented / Linear filter), nie jak trzy przyciski obok siebie.

---

## 2. Co zaprojektować — komponenty i ich stany

Dla każdego: **default · hover · pressed/active · (disabled/empty gdzie dotyczy)**. Pokaż wszystkie stany
obok siebie, jako siatkę — to ma być spec, nie jedna ładna klatka.

### C1 · Segment triażu (Nowe / Zachowane / Odrzucone) — PRIORYTET
- Trzy segmenty w jednym pasku, każdy z **liczbą** (licznik połączeń w danym widoku) i **etykietą**.
- Stany: **aktywny** (bieżący widok), **nieaktywny**, **hover na nieaktywnym**, **pusty widok**
  (licznik 0 — segment nadal klikalny, ale wyciszony).
- Rozstrzygnij hierarchię licznik↔etykieta (teraz licznik nad etykietą wygląda źle — może liczba jako
  subtelny badge przy etykiecie? może liczba dominująca, etykieta drobna pod? — to projektujesz).
- Aktywny segment: rekomendacja — terakotowy akcent (`--terracotta-lit` na ciemnym), nie pełny fill,
  raczej tinted-fill + akcentowy border + jaśniejszy tekst. Nieaktywny: ghost. Ale to Twoja decyzja.
- **Twarde ograniczenie szerokości:** szyna ma ~236 px (patrz §5). Trzy segmenty z etykietami
  „Zachowane"/„Odrzucone" + liczniki muszą się zmieścić **czytelnie** w ~212 px użytecznych. Jeśli się
  nie mieszczą poziomo — zaproponuj layout (skrót etykiet? liczba jako badge? dwa rzędy? szersza szyna?).
  Podaj realną szerokość, którą trzeba dać szynie, jeśli pełne etykiety są nie do ściśnięcia.

### C2 · Wiersz połączenia w szynie (rail row)
- Zawiera: mały **sygil** (kształt = typ połączenia), etykietę typu, 1-linijkowy skrót rationale.
- Stany: **default · hover** (delikatny wash) **· aktywny** (złoty pasek po lewej + jaśniejszy tekst +
  subtelne tło) **· zachowany/wyciszony** (przygaszony, gdy w widoku „Zachowane" lub jako znacznik).
- Dziś hover maluje neutralny biały wash i działa — ale dociągnij wagę aktywnego (design chce
  `rgba(255,255,255,.07)` tła pod aktywnym + złoty pasek). Pokaż wszystkie cztery stany.

### C3 · Kierunek = checkbox + wiersz (direction row)
- Wielolinijkowa etykieta-pytanie + checkbox po lewej. Multi-select (można zaznaczyć kilka → przekazać).
- Stany checkboxa: **niezaznaczony** (border) **· zaznaczony** (terakotowy fill + ✓) **· hover**.
- Stany wiersza: **default · hover · zaznaczony** (terakotowy tint tła + border).
- **Problem do rozwiązania:** wyrównanie checkboxa do **pierwszej linii** wielolinijkowego tekstu
  (nie do środka całego wiersza), oraz waga pustego checkboxa (teraz „znika"). Podaj dokładne metryki.

### C4 · Pasek handoffu (handoff bar) + CTA z marką
- Region dolny nad footerem, pojawia się gdy ≥1 kierunek zaznaczony. Zawiera:
  - status „N kierunków wybrane",
  - **primary CTA** „Kontynuuj w {Claude|ChatGPT}" z **marką providera** (lokalne SVG: Claude / OpenAI),
  - **switcher** (caret) do zmiany narzędzia,
  - **akcje wtórne** jako ikony: zadanie · kalendarz · schowek.
- Stany CTA: **default · hover** (rozjaśnienie + subtelny lift) **· pressed**. Stany ikon wtórnych:
  **default · hover**. Switcher: **default · hover** + jak sygnalizuje aktualne/następne narzędzie.
- **Do rozstrzygnięcia:** jak marka siedzi na CTA (rozmiar glifu, odstęp, tint = biały na terakocie),
  i jak odróżnić wizualnie primary (jeden, mocny) od wtórnych (cichy klaster ikon) bez tłoku.
  Tylko Claude i ChatGPT (Gemini usunięty — brak prefill-URL). Marki = template-image tintowane.

### C5 · Footer — Zachowaj / Odrzuć
- **Zachowaj** = jadeitowy afirmatyw (`--status-local`/jade), **Odrzuć** = ghost (hover rozjaśnia tekst).
- Stany obu: **default · hover · pressed**. Plus mikro-feedback po kliknięciu (jest „flash" w kodzie —
  rozbłysk jadeitowy na Zachowaj, wygaszenie na Odrzuć; zaprojektuj jego docelowy wygląd).
- **Kontekst widoku:** w widoku „Odrzucone" przycisk Zachowaj = *odzyskaj*. Rozważ, czy etykiety/wygląd
  zmieniają się per widok, czy zostają stałe (rekomendacja: stałe, znaczenie z kontekstu).

### C6 · Stany puste ×3 (per widok)
- **Nowe puste:** „Wszystko przejrzane" — spokojny, nie smutny (sygil + tytuł + 1 zdanie).
- **Zachowane puste:** „Nic zachowanego" — zaproszenie, nie pustka.
- **Odrzucone puste:** „Nic odrzuconego" — z podpowiedzią, że stąd się odzyskuje.
- Ton: `Docs/TONE-OF-VOICE.md` — cicho, bez hype, bez emoji.

### C7 · Layout i chrome okna (kompozycja całości)
- Okno otwiera się teraz **proporcjonalnie do ekranu** (~62%, clamp), więc na 27" jest duże. Zaprojektuj
  kompozycję dla **dużego okna**, nie tylko minimalnego: jak oddychają szyna / czytnik / pasek / footer,
  gdzie ląduje powietrze, czy czytnik ma max-measure dla rationale.
- Chrome: ciemny title-bar „Malinche — Konstelacja", licznik pozycji w bieżącym widoku, „✦ Nowy insight".

---

## 3. Tokeny, typografia, kolor (z `tokens.css`)

- **Powierzchnia: ciemna** — `--hero-dark #110F16` baza, radial jak w `insights-ui.html`
  (`radial-gradient(130% 120% at 64% 0%, #1C1B24, #16141C 50%, #100E15)`). Szyna: `rgba(0,0,0,.16)`.
- **Akcenty:** połączenia/aktywne/CTA = terakota (`--terracotta #C24010`, na ciemnym `--terracotta-lit
  #D9542A`); insight/rozbłysk/aktywny-pasek = `--gold #D6B033` (glow `#F4DD8E`); Zachowaj = jadeit
  `--jade #057857` (na ciemnym jaśniejszy tint, np. fill `rgba(70,177,126,.16)`, tekst `#8BE0B5`).
- **Tekst:** rationale (pull-quote) = display, `--leading-snug`, `--content-contrast` (`#FAF3E2`);
  etykiety/kierunki/UI = body; eyebrow uppercase `--tracking-eyebrow`. Wyciszony = `#B0A28D` / `--ink-soft`.
- **Promienie:** przyciski/segmenty/chipy `--radius-pill` lub `--radius-lg` (10px) — **ustal jedną
  rodzinę i trzymaj ją wszędzie** (teraz jest niespójnie 9–12 px). Karty/wiersze `--radius-xl` (14px).
- **Border na ciemnym:** `--border-on-dark` (`rgba(244,233,207,.28)`) lub neutralny biały `.10–.22`.
- **Cień/lift:** hover na CTA = `--shadow-accent` lub subtelny `--shadow-card`; lift max ~1–2px.
- **Przejścia:** `--transition` (0.2s). Tylko kolor/opacity/cień — bez efektów web-only.

---

## 4. Realne dane do makiet (NIE lorem ipsum)

Trzy realne połączenia (digest na korpusie 8moons). Użyj ich, plus liczników triażu **Nowe 3 ·
Zachowane 1 · Odrzucone 2**, żeby segment był pokazany z prawdziwymi liczbami.

**1. contradiction-over-time** — notatki: `Haetta — rozmowa z konstruktorem` (17.06),
`8Moons — filmiki 2` (18.06).
rationale: „Założenie o jakości przesunęło się w miesiąc — z fundamentu projektu w pozycję do negocjacji
pod presją budżetu."
directions: „Co wymusiło zmianę założenia jakościowego — jednorazowy kompromis, czy trwała zmiana
kierunku, którą warto nazwać wprost?" · „Filary projektu — bronić mimo budżetu, czy zrewidować i szukać
oszczędności gdzie indziej?"

**2. shared-thread** — notatki: `Planowanie budowy domu — materiały okna dach`,
`Przygotowania do Eight Moons — okna i fundamenty`.
rationale: „Okna wracają w obu notatkach jako to samo wąskie gardło — brak potwierdzeń od producentów
napina sierpniowy termin z dwóch stron naraz."
directions: „Poszukać alternatywnych producentów już teraz?" · „Jak wyglądałby plan B na okna?"

**3. emergent-idea** — notatki: `Strategia TekTutoreski`, `8Moons — filmiki 2`, `Harmonogram 2-tyg.`.
rationale: „Ten sam dylemat skali wraca w różnych projektach: skalować przez automatyzację, czy utrzymać
ręczny udział kosztem skali."
directions: „Czy to jedna ‚zasada skalowania', którą stosujesz wszędzie?" · „Gdzie hands-on buduje
jakość, a gdzie tylko blokuje skalę?"

---

## 5. Ograniczenia implementacyjne (to jest port AppKit — projektuj pod to)

- **Cel = natywny AppKit (PyObjC).** Prototyp HTML to **spec wyglądu z redlinami**, nie kod do wdrożenia.
  Wszystko musi być odwzorowalne w `NSView`/`NSButton`/Core Graphics. Bez gradientów animowanych, bez
  efektów, których nie da się złożyć z: layer background/border/cornerRadius/shadow, tint template-image,
  prosty wash-overlay, zmiana koloru tekstu.
- **Wymiary realne (z kodu):** szyna `_RAIL_W = 236 px`; padding czytnika `24 px`; wiersz `~58 px`;
  footer `46 px`; pasek handoffu `48 px`; przyciski `~30–32 px` wys. Okno otwiera się ~62% ekranu
  (min 740×460). **Trzymaj się tych metryk lub podaj wprost, które trzeba zmienić** (np. szersza szyna
  pod segment) — wtedy zmienię stałe.
- **Fonty:** natywnie SF Pro / SF Pro Text. Prototyp może użyć Inter/Fraunces jako spec; port mapuje na SF.
- **Sygile:** rysowane w Core Graphics (`_SigilView.drawRect_`), 3 typy (`contradiction`/`thread`/`triad`).
  Reużyj gramatyki z poprzednich prototypów. Prototyp = spec kształtu.
- **Marki LLM:** lokalne SVG (`assets/brands/claude.svg`, `openai.svg`), ładowane jako template-image
  i tintowane. Projektuj rozmiar/odstęp glifu, nie sam glif.
- **Dostępność:** kontrast na ciemnym; polskie diakrytyki (ą ć ę ł ń ó ś ź ż); `prefers-reduced-motion`.
- **Ton/copy:** `Docs/TONE-OF-VOICE.md` — krótkie polskie etykiety, cicha puenta, bez emoji, bez hype.

---

## 6. Locked vs open

**Locked:** model triażu (3 widoki, Odrzuć odwracalny); ciemna powierzchnia; tokeny z `tokens.css`;
dane z §4; Zachowaj = jadeit, połączenia/CTA = terakota, insight/aktywny = złoto; tylko Claude+ChatGPT;
cel = natywny AppKit z realnymi metrykami z §5; brak emoji; ton.

**Open (do interpretacji Claude Design):** wygląd i hierarchia segmentu (licznik↔etykieta, fill vs ghost,
czy mieści się w 236 px czy potrzebuje szerszej szyny); chrome i waga checkboxa + dokładne wyrównanie do
pierwszej linii; jak marka siedzi na CTA i jak odróżnić primary od klastra ikon; jedna rodzina promieni;
docelowy wygląd mikro-flashy Zachowaj/Odrzuć; kompozycja dużego okna (powietrze, max-measure rationale);
copy stanów pustych.

---

## 7. Deliverable

Samodzielny prototyp HTML/CSS importujący `../tokens.css`, w konwencji poprzednich (`pages/*.html`), z:

- **Siatka stanów per komponent** (C1–C5): każdy komponent pokazany we wszystkich stanach obok siebie,
  podpisany, z **redline'ami** (px + token) — to jest spec do portu.
- **Stany puste ×3** (C6).
- **Min. 2 pełne kadry okna** (C7): widok „Nowe" z aktywnym połączeniem + zaznaczonymi kierunkami +
  paskiem handoffu; oraz widok „Zachowane" lub „Odrzucone" (pokazuje segment w innym stanie + recall).
  Oba w **dużym oknie** (nie minimalnym), żeby widać kompozycję i powietrze.
- Sygile jako inline SVG (reuse silnika), marki LLM jako proste glify/placeholdery z notką „tint template".

Po prototypie: implementuję **pixel-perfect** w `src/ui/dashboard_window.py` (komponenty już istnieją —
to redesign ich wyglądu i stanów, nie przepisywanie logiki). Redline → stałe i kolory 1:1.
