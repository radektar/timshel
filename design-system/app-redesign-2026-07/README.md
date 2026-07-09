# Handoff: Timshel — aplikacja macOS „Konstelacja" (redesign 2026-07)

Paczka spec do implementacji **aktualnego** UI aplikacji. Powstała, bo w buildzie
(beta.17) wdrożony jest stary układ — ten dokument + załączone ekrany opisują wersję,
która ma go zastąpić.

---

## 1. Przegląd

Timshel to natywna aplikacja macOS. Jej sercem jest jedno okno — **„Konstelacja"** —
plus kilka powierzchni systemowych (pasek menu, ask-bar, wizard, ustawienia).
Aplikacja indeksuje lokalny vault notatek Markdown i robi dwie rzeczy:

- **Push (Przegląd / „Podsunięte")** — cyklicznie generuje *digest*: połączenia
  między notatkami (sprzeczności, wspólne wątki, emergentne pomysły) i podsuwa je
  do triażu (Zachowaj / Odrzuć).
- **Pull (Pytanie / „Zapytałeś")** — użytkownik pyta swój korpus; aplikacja zwraca
  cytowane fragmenty (lokalnie, bez LLM), z opcją świadomej eskalacji do chmury
  („Zsyntetyzuj").

Zasada nadrzędna redesignu: **jedno okno, dwa jawne, wzajemnie wykluczające się
tryby; chrome (nagłówek, stopka, akcje) należy do trybu, nigdy do obu naraz.**
Każdy widok ma jedną główną akcję.

Ta paczka to **krok 3** procesu: mapa IA (kierunek) → ekrany A–I (pełne siatki
stanów) → **changelog decyzji** (lista różnic do portu). Wszystkie trzy są w środku.

---

## 2. O plikach w tej paczce

Pliki `.html` to **referencje projektowe wykonane w HTML** — prototypy pokazujące
docelowy wygląd, metryki i zachowanie. **To nie jest kod produkcyjny do skopiowania.**

Zadanie: **odtworzyć te designy w docelowym środowisku aplikacji — natywnym
macOS (AppKit / Swift)** — używając jego wzorców (`NSView`, `NSButton`, `NSMenu`,
`NSPanel`, Core Graphics), nie przenosić HTML wprost. Każdy ekran-spec ma na dole
tabelę **redline** (piksele + tokeny) i sekcję „Zależności" wskazującą powiązane ekrany.

Fonty w `fonts/` służą wyłącznie do wiernego renderu HTML w przeglądarce. **W apce
mapują się na SF Pro / SF Pro Text** (patrz §5).

---

## 3. Fidelity: **Hi-fi**

Finalne kolory, typografia, spacing, stany i interakcje. Odtwórz 1:1 w AppKit,
używając istniejących kontrolek i wzorców kodu. Redline'y na każdym ekranie są
wiążące. Prototypy pokazują pełne siatki stanów: `default · hover · pressed ·
zaznaczony · empty · flash`.

**Ograniczenie odwzorowalności (wiążące):** każdy element musi się składać z tego,
co AppKit robi tanio — `layer` (background / border / cornerRadius / shadow), tint
template-image, prosty wash-overlay, zmiana koloru tekstu. **Bez animowanych
gradientów, bez efektów web-only.** Prototypy już tego pilnują; trzymaj się tego w porcie.

---

## 4. Architektura informacji (co jest powierzchnią, co trybem)

Pełny opis: **`app-ia-map.html`**. Skrót:

| Warstwa | Powierzchnia | Uwaga |
|---|---|---|
| Korzeń (zawsze) | **Pasek menu** (`NSStatusItem`) | Jedyny trwały punkt. Status indeksowania żyje **tylko tutaj** (ekran F). |
| Przelotne | **Ask-bar** (overlay ⌥Space), notyfikacje systemowe | Ask-bar to `NSPanel`, nie chrome okna (ekran C). |
| Główne okno | **Konstelacja** — jedno okno, dwa tryby: **Przegląd** ⇄ **Pytanie** | Jedyna powierzchnia customowa (ciemna). Ekrany A, B, D, E. |
| Natywne | **Wizard** (G), **Ustawienia** (H), dialogi (`NSAlert`) | Natywny AppKit z tokenami — **nie** przechodzą na ciemny język Konstelacji (§5 mapy IA). |

**Przełączanie trybów:** nagłówki sekcji szyny SĄ przełącznikiem. Aktywna sekcja
rozwinięta; druga zwinięta do nagłówka z licznikiem. Klik zwiniętego nagłówka →
tryb się zmienia, cały chrome się wymienia. `Esc` w Pytaniu → powrót do Przeglądu.
Zero osobnych zakładek. (ekran B5)

**Wejścia do trybu Pytanie:** ⌥Space (globalnie) · ⌕ w title-barze · „Zapytaj o to"
z karty insightu (prefill zawężony do źródeł).

**Wymiary okna (z implementacji — zostają bez zmian):** szyna **236 px** (`_RAIL_W`),
stopka triażu **46 px**, pasek handoffu **48 px**, przyciski **~30–32 px** wys.,
title-bar **40 px**, okno **~62% ekranu**, min **740×460**, resizable.

---

## 5. Stack docelowy i zasady portu

- **Framework:** AppKit (Swift). `NSWindow` / `NSView` / `NSButton` / `NSMenu` /
  `NSPanel` / `NSTextField` / `NSTextView`.
- **Fonty:** Neue Montreal → **SF Pro** (display/nagłówki), Neue Haas Grotesk →
  **SF Pro Text** (body/UI), mono → **SF Mono**. Wagi: 400 / 500 / 700.
- **Sygile:** rysowane w **Core Graphics** — `_SigilView.drawRect_`, 3 typy
  (`contradiction` / `shared`(thread) / `emergent`(triad)). Silnik referencyjny:
  `redesign-sigils.js` (`window.mSigil(type, color, size)`), typy i geometria w §8.
- **Marki LLM:** lokalne SVG jako **template-image**, tintowane
  (`assets/brands/claude.svg`, `openai.svg` — do dostarczenia; w prototypach glif
  Claude jest placeholderem, patrz `redesign-sigils.js → mIco('claude')`). Tint
  biały na terakotowym CTA, `--c-body` w menu. Tylko **Claude + ChatGPT** (Gemini
  odpada — brak prefill-URL).
- **Sygnet aplikacji:** `--logo-sygnet` (maska, 6 zaokrąglonych słupków = fala).
  Ikona apki = gradientowy sygnet (`--logo-mesh`) na czarnym kaflu `#141414`;
  w pasku menu = monochromatyczny sygnet (tint systemowy).
- **Copy: całość PL, pełne diakrytyki** (ą ć ę ł ń ó ś ź ż) w każdym foncie i wadze.
  Miks PL/EN jest gorszy niż każda z opcji osobno. Skróty klawiszowe: ⌥Space,
  ⌘⇧K, ⌘, ⌘Q.
- **Dostępność:** kontrast na ciemnym; `prefers-reduced-motion` → animacje wsuwania
  (150–180 ms) zastępuje cięcie.

---

## 6. Design tokens

Źródło prawdy: **`tokens.css`** (w tej paczce). Wybór do portu:

### Kolory — baza (paper / natywne powierzchnie)
| Token | Hex | Rola |
|---|---|---|
| `--paper` | `#FFFFFF` | tło stron/natywne |
| `--panel` | `#F3F1EB` | panel ciepłoszary |
| `--panel-2` | `#ECEAE3` | sunken / chip |
| `--ink` | `#1A1A1A` | tekst główny |
| `--ink-soft` | `#6E6A64` | tekst wtórny |
| `--obsidian` | `#141414` | kafel ikony apki |

### Powierzchnia okna (dark — Konstelacja)
- Tło: `radial-gradient(130% 120% at 64% 0%, #1C1B24, #16141C 50%, #100E15)`
- Tekst: `#FAF3E2` (hi) · `#C9BBA6` (body) · `rgba(250,243,226,.55)` (mute)
- Szyna: `rgba(0,0,0,.16)`; obramowania na ciemnym: `rgba(255,255,255,.06–.16)`

### Trzy akcenty (role egzekwowane twardo — patrz §7)
| Akcent | Na ciemnym / natywnym | Paper (marketing) |
|---|---|---|
| **Terakota** (akcja) | `#C24010` base · `#D9542A` hover/lit · `#9A3009` pressed | `#AC4B16` (Poppy) |
| **Jadeit** (lokalne) | `#46B17E` · tekst `#8BE0B5` · `#1E7A52` na jasnym | — |
| **Złoto** (insight / do chmury) | `#D6B033` · glow `#F4DD8E` · chmura `#E7B45C` | — |

> Uwaga: w oknie i na powierzchniach natywnych terakota to rodzina **#C24010 /
> #D9542A / #9A3009**, nie `--terracotta #AC4B16` z bazy paper. Złoto i jadeit żyją
> **tylko w oknie** i w bloku Prywatności — nigdy jako kolor UI na powierzchniach paper.

### Typografia
`--font-display` Neue Montreal → SF Pro · `--font-body` Neue Haas Grotesk → SF Pro Text ·
mono → SF Mono. Skala w oknie: teza `24 px`/1.3 display 500; pytanie-tytuł `21–24 px`;
etykiety/eyebrow `10.5–11 px` uppercase `.1em`; body wierszy `12.5–13 px`; mono `11–12 px`.

### Radius (native macOS feel — ostre, nie pill)
`--radius-button 6px` (przyciski, inputy, segmenty, split, chipy metadanych) ·
checkbox `4–5px` · wiersze/karty `8–12px` · popover/menu `8px` · notyfikacja `14px` ·
`--radius-pill 999px` (kropki statusu). **Kontrolki ostre 6 px — to feel macOS.**

### Elewacja
`--shadow-float: 0 28px 70px -28px rgba(20,20,20,.28)` (okno) ·
`--shadow-accent` (przyciski terakota) · menu `0 16px 44px -12px rgba(0,0,0,.65)`.

### Spacing
Baza 4 px (`--space-1..24`).

---

## 7. Role akcentów — reguła rozstrzygająca

Z `redesign-changelog.html §6`. **Egzekwowana twardo — test na każdym elemencie:**

- **Element jest akcją użytkownika → terakota.** CTA, split-button, checkbox
  zaznaczony, aktywny wpis w Pytaniu (pull), fokus ask-bara, „↗ otwórz" w hoverze,
  „Zapisz do vaulta".
- **Element mówi „to zostaje u Ciebie / lokalnie" → jadeit.** „Zachowaj", znacznik
  „lokalnie", banner indeksu, ślad zapisu, blok „Zawsze lokalnie".
- **Element dotyczy insightu / syntezy / tekstu wychodzącego do chmury → złoto.**
  Sygile, pasek aktywnego insightu (w Przeglądzie), eyebrow typu, daty wyników,
  „✦ do chmury", ślad handoffu, licznik nowych.
- **Nie pasuje do żadnej roli → neutralny.**

Konsekwencja w szynie: aktywny wiersz **insightu** (push) ma pasek **złoty**;
aktywny wpis **zapytania** (pull) ma pasek **terakotowy** (Twoja akcja).

---

## 8. Wspólne komponenty okna (dark) — metryki do portu

Wszystkie style w **`redesign-spec.css`** (importowany po `tokens.css`).
Poniżej najważniejsze — dokładne redline'y per stan są na dole każdego ekranu A–I.

**Title-bar** — wys. `40 px`, światła `11 px` gap `7 px`, tytuł 12.5 px wyśrodkowany;
po prawej **tylko ⌕** `rgba(250,243,226,.55)`, hover pełna biel → otwiera ask-bar (C).

**Szyna (rail)** — `236 px`, tło `rgba(0,0,0,.16)`, border-right `rgba(255,255,255,.06)`,
padding `12/10`.

**Wiersz szyny (`.rrow`)** — padding `9×8`, radius `8`, sygil `18 px` + tytuł `12.5px/700`
`#FAF3E2` + skrót `11.5px` `rgba(.55)` (clamp 1–2 linie).
`hover` bg `rgba(255,255,255,.04)` · `active` bg `.07` + pasek pionowy `2.5 px` po lewej
(**złoty `#D6B033` dla insightu**, `.au`; **terakotowy `#D9542A` dla zapytania**) ·
`dim` (zachowany/odrzucony) opacity `.55`.

**Nagłówek-przełącznik (`.collapsed-h`)** — zwinięta druga sekcja; uppercase `10.5px .1em`
`rgba(.55)`, hover bg `.05` pełna biel. Klik = zmiana trybu.

**Filtr triażu (`.rail-filter`, ekran A3)** — następca segmentu Nowe/Zachowane/Odrzucone.
Jeden element w nagłówku szyny („Nowe **3** ⌄", licznik nowych złoty) → `NSMenu` z 3
pozycjami. Model 3 widoków bez zmian; Odrzuć odwracalny.

**Czytnik (`.reader`)** — padding `20–26 / 24–32`.
- eyebrow typu: sygil `26–30 px` + etykieta `10.5px/.1em` **złota**; po prawej znacznik
  „digest … · z chmury" / „lokalnie".
- **teza (`.thesis`)**: `--font-display` 500, `24 px`/1.3, tracking `-.012em`, max `30em`,
  `#FAF3E2`; cytowania `[n]` złote `.6em` super (synteza).
- **pytanie-tytuł (`.r-q`)**: display 500, `21–24 px`/1.25 (tryb Pytanie — pytanie jest
  tytułem, nie polem).
- **chip źródła (`.nchip`)**: h `26`, radius `6`, border `rgba(255,255,255,.14)`, kropka
  `5px` `#D9542A`; hover border `rgba(224,99,58,.6)`; „↗" otwiera w appce.

**Wiersz wyniku (`.res`, Pytanie)** — cały wiersz = jedna akcja „otwórz źródło".
Padding `13×2` (hover `13×10`), radius `6`, border-bottom `rgba(255,255,255,.07)`.
Data mono **złota** `#D6B033`; tytuł `700` `rgba(.9)`; „↗ otwórz" `rgba(.45)` →
hover **terakota** `#E0633A`; cytat `12.5px`/1.5 `rgba(.66)`; `<mark>` bg
`rgba(214,176,51,.22)` tekst `#F4DD8E`. `po otwarciu`: „otwarto ✓" `#8BE0B5`, 2 s, wraca.

**Kierunek (`.dirrow` + `.cbx`, ekran E)** — wiersz padding `11×12`, radius `10`, gap `11`,
border `rgba(255,255,255,.1)`. Checkbox **16 px**, radius `4`, border `1.5px`
`rgba(250,243,226,.4)`, **wyrównany do pierwszej linii** tekstu (margin-top `2 px`, nie
do środka wiersza). `on`: fill **terakota `#C24010`** + biały ✓; wiersz tint
`rgba(217,84,42,.09)` + border `.55`, tekst pełną bielą.

**Przyciski (`.btn`)** — wys. `31 px`, radius `6`, `12.5px/500`:
- `btn-jade` (**Zachowaj**): bg `rgba(70,177,126,.16)` border `.45` tekst `#8BE0B5` 700;
  hover `.24/.65`; pressed `.32`; **flash 180 ms** ring `rgba(70,177,126,.22)` bg `.3`.
- `btn-ghost` (**Odrzuć / wtórne**): border `rgba(255,255,255,.16)` `rgba(.7)`; hover
  border `.3` biel; pressed bg `.06`.
- `btn-syn` (**Zsyntetyzuj**): border `rgba(214,176,51,.5)` tekst `#F4DD8E` bg
  `rgba(214,176,51,.08)` — rola insight/synteza.
- `btn-terra` (**Zapisz do vaulta / CTA handoffu**): bg `#C24010` biel 700; hover
  `#D9542A` + `--shadow-accent`; pressed `#9A3009`.

**Stopka triażu (`.wfooter`, tylko Przegląd)** — wys. `46 px`, border-top
`rgba(255,255,255,.08)`, bg `rgba(0,0,0,.18)`. Odrzuć (ghost) · „1 z 3" (mono `rgba(.4)`,
środek) · Zachowaj (jadeit). **Nie istnieje w trybie Pytanie.**

**Pasek handoffu (`.handoff`, ekran E)** — wys. `48 px`, bg `rgba(0,0,0,.22)`. **Pojawia
się dopiero przy ≥1 zaznaczonym kierunku** (wsuwa 150 ms). Po lewej „N kierunków
wybrane" + znacznik „✦ do chmury"; po prawej menu **⋯** (akcje wtórne: zadanie ·
kalendarz · schowek) + **split-CTA** „Kontynuuj w Claude ▾" (caret przełącza Claude/
ChatGPT). Liczebność PL: 1 kierunek · 2–4 kierunki · 5+ kierunków.

**Toast (`.toastc`, ekran I)** — h `36`, radius `8`, bg `#24222C` border `rgba(255,255,255,.12)`;
2 s, wyśrodkowany nad stopką (`10 px` odstępu), hover pauzuje zegar, Esc zamyka.
„Cofnij" `#E0633A`. Wariant `jade` (Zachowano) z kropką `#46B17E`.

**Trwały ślad (`.trace`, ekrany D4/E4/I2)** — padding `8×12`, radius `8`, klikalny,
przeżywa zamknięcie okna. **Jadeit** (zapis lokalny): bg `rgba(70,177,126,.08)` border `.3`,
plik mono `#8BE0B5`. **Złoto** (handoff do chmury): bg `rgba(231,180,92,.07)` border `.3`,
„✦ Przekazano do… ↗ otwórz wątek".

**Menu / popover (`.menu`)** — `NSMenu`; szer. `180–252`, bg `rgba(38,36,44,.97)` border
`rgba(255,255,255,.12)` radius `8`; pozycja padding `6×9` radius `5`, hover bg **terakota**
`#C24010` biel; skrót mono `rgba(.4)`.

**Ask-bar (`.ask`, ekran C)** — `NSPanel` nonactivating, szer. `560`, pole `52 px` radius `10`,
bg `rgba(32,30,40,.98)` border `rgba(255,255,255,.16)` + cień float. `focus`: ring `3 px`
`rgba(217,84,42,.18)` + border `rgba(217,84,42,.65)`, caret `#E0633A`. Mic `36 px` radius `7`;
`live` border/tekst terakota-lit, bg `rgba(217,84,42,.12)`. Podpowiedzi (chip `28 px`,
max 2) tylko w stanie pustym — ostatnie tematy korpusu.

**Natywna rama (`.nativewin`, wizard/ustawienia)** — bg `#F5F3EF` tekst `#1A1A1A`; titlebar
`#ECEAE4`. `nbtn` `28 px` radius `6`, primary bg `#C24010` biel. `nfield` `30 px`. Zakładki:
aktywna bg `rgba(194,64,16,.1)` tekst terakota.

**Pasek menu (`.osbar`) + notyfikacja (`.notif`)** — patrz ekrany F oraz I. Notyfikacja:
szer. `344`, radius `14`, ikona `34 px` (`#141414` + sygnet mesh).

---

## 9. Sygile (kształt = typ połączenia)

Silnik referencyjny: **`redesign-sigils.js`** → `window.mSigil(type, color, size)`.
`viewBox 0 0 32 32`. Węzeł = 3 nałożone koła (poświata radialna → `#C24010` r2.5 →
`#FAF3E2` r1). „Rozbłysk" (bloom) = złoty. Do portu w **Core Graphics
(`_SigilView.drawRect_`)** — HTML tu jest **spec kształtu**, nie docelowym rendererem.

| Typ | Kolor | Kształt | Odczyt |
|---|---|---|---|
| `contradiction` | `#D9542A` | 2 węzły, **2 rozchodzące się łuki** wokół spornego punktu | napięcie / opozycja |
| `shared` (thread) | `#D6B033` | 2 węzły **zbiegają się** ku rozbłyskowi u góry | spotkanie / wspólny wątek |
| `emergent` (triad) | `#E3C16B` | centralny rozbłysk **rozgałęzia się** do 3 węzłów | pomysł z wielu źródeł |

Rozmiary w użyciu: szyna `18–26 px` · eyebrow czytnika `24–30 px` · stan pusty `34–46 px`.
Sygnet aplikacji (`--logo-sygnet`) to **osobny** motyw (fala/menu-bar), nie sygil połączenia.

Ikony liniowe (`mIco`): `szukaj · mic · zadanie · kalendarz · kopiuj · caret · wiecej · claude`
— `16 px`, stroke `currentColor 1.3`.

---

## 10. Ekrany A–I (spec do portu)

Każdy plik = jeden ekran ze wszystkimi stanami + redline + „Zależności".
Buduj z nich; poniżej cel, layout, kluczowe stany i **dokładne copy** (odtwórz z diakrytykami).

### A — `redesign-a-przeglad.html` · Tryb Przegląd (push, domyślny)
Stan spoczynkowy okna. Jedna główna rzecz: karta aktywnego połączenia. Jedna główna
akcja: **Zachowaj**.
- **A1** pełny kadr: szyna „Podsunięte" (filtr „Nowe 3 ⌄", 3 wiersze insightów, na dole
  zwinięte „Zapytałeś 2 ›") + czytnik (eyebrow typu złoty · teza · chipy źródeł · „⌄ Dowód"
  · Kierunki) + stopka Odrzuć / „1 z 3" / Zachowaj.
- **A2** wiersz szyny — 4 stany. **A3** filtr triażu (default/hover/otwarty NSMenu/widok
  „Odrzucone"). **A4** stopka Zachowaj (jadeit) / Odrzuć (ghost) — pełna siatka + flash.
  **A5** 3 stany puste (sygil + tytuł + jedno zdanie, bez przycisków). **A6** redline.
- Copy stanów pustych: „Wszystko przejrzane / Nowe połączenia pojawią się z kolejnym
  digestem." · „Nic zachowanego / Zachowaj odkłada połączenie tutaj, na później." ·
  „Nic odrzuconego / Odrzucone trafiają tu — Zachowaj je odzyskuje."

### B — `redesign-b-pytanie.html` · Tryb Pytanie (pull)
Pytanie jest **tytułem czytnika**, nie polem. Wyniki = cytowane fragmenty **bez LLM**,
znacznik „lokalnie". Jedyny przycisk: **„Zsyntetyzuj te wyniki"** (znacznik „do chmury").
**Stopka triażu nie istnieje w tym trybie.**
- **B1** pełny kadr (4 trafienia). **B2** wiersz wyniku — 4 stany (default/hover/pressed/
  „otwarto ✓"). **B3** nagłówek („ponów · edytuj" w hoverze) + historia w szynie (trwała,
  lokalna, „wyczyść historię"). **B4** abstynencja (0 trafień → uczciwy komunikat +
  najbliższe trafienie + „Poszerz zakres" / „Przekaż do Claude" — **jedyne** miejsce, gdzie
  te dwa istnieją) oraz częściowy indeks (linia „Przeszukuję 240 z 1800 notatek"). **B5**
  przełączanie trybów. **B6** redline.

### C — `redesign-c-askbar.html` · Ask-bar (overlay)
`NSPanel` bez title-baru, wyśrodkowany w ⅓ wysokości, przyciemnienie tła `rgba(0,0,0,.25)`.
Jedyne miejsce wpisywania; mikrofon żyje **wyłącznie tu**. Enter → ląduje w oknie (tryb
Pytanie). Esc → znika bez śladu.
- **C1** 4 stany: pusty z podpowiedziami · pisanie (fokus) · głos (nasłuch, mic „live") ·
  prefill „Zapytaj o to" (chip zakresu usuwalny). **C2** lądowanie (overlay oddaje, okno
  renderuje — bez spinnera, embeddingi lokalne). **C3** redline. Placeholder: „Zapytaj swój
  korpus…"; głos: „Słucham…".

### D — `redesign-d-synteza.html` · Synteza (eskalacja do chmury)
Jedyne miejsce przepływu pull, gdzie tekst opuszcza Maca. **Zgoda = przycisk, nie dialog**,
ale przycisk mówi wprost, co wychodzi.
- **D1** moment zgody (hover odsłania „4 dopasowane fragmenty opuszczą Maca — nic poza
  nimi"; „w toku" → status „✦ Syntetyzuję z 4 fragmentów…" + Zatrzymaj). **D2** streaming
  (karta wsuwa się nad wyniki, cytowania [n] w trakcie). **D3** karta gotowa (teza z [n] →
  dowód ponumerowany → chipy „Pociągnij dalej" → akcje: **Zapisz do vaulta** terakota /
  Kontynuuj w Claude / kopiuj). **D4** zapis → **trwały ślad** podwójny (pod kartą + w
  historii); błąd sieci **w miejscu karty**, nie `NSAlert`. **D5** redline.

### E — `redesign-e-handoff.html` · Kierunki + pasek handoffu
Progresywne odsłanianie: **0 zaznaczonych = paska nie ma.** Zaznaczenie kierunku = intencja
→ pasek z jednym CTA.
- **E1** wiersz kierunku + checkbox (default/hover/zaznaczony). **E2** odsłanianie paska
  (0 → 1 → 2, wsuwa 150 ms). **E3** split-CTA z marką + switcher (Claude/ChatGPT) + menu **⋯**
  (akcje wtórne — dawny klaster 3 ikon). **E4** trwały ślad złoty „✦ Przekazano do Claude
  ↗ otwórz wątek · 14:32". **E5** redline. Marki = template-image, tint biały.

### F — `redesign-f-pasek-menu.html` · Pasek menu + indeksowanie
Korzeń aplikacji (`NSStatusItem` + `NSMenu`). **Status indeksowania żyje tylko tu.**
- **F1** stany ikony (spoczynek · nagrywam +kropka `#E0633A` · indeksuję — sygnet
  przygaszony do 55% · menu otwarte). **F2** menu w 3 wariantach (spoczynek / indeksuję
  z paskiem postępu / digest gotowy „✦ 3 nowe połączenia"). Custom widok statusu u góry
  `NSMenu`, maks. 7 pozycji. Skróty: Otwórz Konstelację ⌘⇧K · Zapytaj ⌥Space · Ustawienia
  ⌘, · Zakończ ⌘Q. **F3** zasady (status ma jeden dom; digest ręczny „Nowy digest ✦" tylko
  tu; ikona nie teatralizuje — bez animacji).

### G — `redesign-g-pierwszy-bieg.html` · Pierwsze uruchomienie
Wizard **2 kroki** (natywny, tokeny), potem apka znika do paska menu; indeksowanie w tle
**nic nie blokuje** — pytać można od minuty 0.
- **G1** wizard: krok 1 vault („Gdzie leżą Twoje notatki?" + `.nfield` + „Dalej") · krok 2
  opener (radio Obsidian/Pile/Finder + „Zacznij") · finał „Indeksuję w tle · 1 800 notatek ·
  ~5 min · pytać: ⌥Space". **G2** minuta 0/2/10 (pasek menu → linia zakresu w wynikach →
  **jedna** notyfikacja „Vault zaindeksowany"). **G3** Przegląd przed pierwszym digestem
  („Pierwszy digest przygotuję po indeksowaniu" — jedyny pusty stan z podpowiedzią gestu).

### H — `redesign-h-ustawienia.html` · Ustawienia (natywne, z tokenami)
Standardowe okno preferencji. Spójność niesie akcent/typografia/promienie/głos, **nie kolor
tła**. 3 zakładki: **Ogólne · Vault · Prywatność**.
- **H1** Ogólne (opener, skrót zapytania, start przy logowaniu, domyślne narzędzie handoffu).
  **H2** Vault (folder, indeks „1 800 notatek", „Przebuduj indeks", indeksowanie przyrostowe).
  **H3** Prywatność = **umowa produktu**: blok jadeitowy „Zawsze lokalnie" (nagrania,
  transkrypcje, indeks, wyszukiwanie, historia) + blok złoty „✦ Do chmury — tylko na Twój
  gest" (digest, synteza, handoff), potem model / klucz API / rytm digestu. **H4** zasady
  portu (rama natywna, tokeny na kontrolkach, 3 zakładki, prywatność jako stały element).

### I — `redesign-i-feedback.html` · System feedbacku
Jedna zasada: **kto zainicjował × jak trwały skutek.**
- **I1** toast (2 s, Cofnij, dół okna). **I2** trwały ślad (jadeit = wróciło do Ciebie /
  złoto = wyszło do chmury). **I3** notyfikacja systemowa (rzadka, klikalna — 2 rodzaje:
  digest gotowy, indeks gotowy). **I4** **mapa wszystkich zdarzeń** — tabela rozstrzygająca
  (każde zdarzenie ma dokładnie jeden kanał). Anty-zasady: nigdy dwa kanały dla jednego
  zdarzenia; nigdy notyfikacja jako echo akcji użytkownika; nigdy toast dla skutku trwałego.

---

## 11. Changelog beta.17 → redesign — lista różnic do portu

**`redesign-changelog.html`** to najważniejszy plik dla „co dokładnie zmienić względem
tego, co jest w buildzie". 6 sekcji (okno i tryby · triage i stopka · Recall · handoff ·
powierzchnie systemowe · role akcentów), każdy wiersz z odesłaniem do ekranu-specu (A1–I4).
Skrót najważniejszych cięć:

- Stały ask-bar (56 px) w oknie → **wycięty** (overlay ⌥Space / ⌕; pytanie = tytuł). `C1·B3`
- Segment triażu (3 przyciski) → **filtr w nagłówku szyny** („Nowe 3 ⌄" → NSMenu). `A3`
- Stopka Zachowaj/Odrzuć zawsze widoczna → **tylko w Przeglądzie** (błąd znika z
  architektury, nie przez `if`). `A4·B1`
- 3 równorzędne akcje pod wynikami → **jedna** („Zsyntetyzuj", „do chmury"); „poszerz/
  przekaż" tylko w abstynencji. `B1·B4`
- Handoff: klaster 3 ikon zawsze → **menu ⋯** + jeden split-CTA, pojawia się przy ≥1
  kierunku. `E2·E3`
- Brak oznaczeń lokalne/chmura → **jadeit „lokalnie" / złoto „✦ do chmury"** wszędzie na
  granicy. `B1·H3`
- „✦ Nowy insight" i licznik pozycji z title-baru → do menu paska menu / do stopki. `F2·A1`

**Wymiary (szyna 236 · stopka 46 · handoff 48 · przyciski 30–32 · okno ~62%) — bez zmian.**

---

## 12. Stan i dane (do logiki)

- **Tryb okna:** `Przegląd | Pytanie` — wzajemnie wykluczające; determinuje cały chrome.
- **Widok triażu (Przegląd):** `Nowe | Zachowane | Odrzucone` — Odrzuć **odwracalny**;
  liczniki (przykład danych: Nowe 3 · Zachowane 1 · Odrzucone 2).
- **Insight (digest):** `{ type: contradiction|shared|emergent, thesis, notes[],
  evidence:[{date, note, quote}], directions[] }`. `evidence` i pełniejsze `directions`
  muszą być **emitowane przez syntezę** (grounded-only) — bez nich „grunt" renderuje się
  pusto (uwaga „Track B" z prototypów kart).
- **Zaznaczenie kierunków:** multi-select; steruje widocznością paska handoffu.
- **Aktywne narzędzie handoffu:** `Claude | ChatGPT` (globalne, zapamiętane; też w
  Ustawieniach H1).
- **Historia zapytań:** trwała między sesjami, w pełni lokalna, kasowalna; wpis może nieść
  ślad zapisanej syntezy.
- **Indeksowanie:** postęp `X z Y` + szacunek; dom = pasek menu; okno pokazuje 1 linię zakresu.
- **Granica lokalne/chmura:** wszystko lokalne poza 3 gestami (digest, synteza, handoff) —
  te oznaczone „✦ do chmury".

Mapa zdarzeń → kanał feedbacku: pełna tabela w `redesign-i-feedback.html §I4`.

---

## 13. Assets

- **Fonty** (`fonts/`, 6 plików) — tylko do renderu HTML. W apce → **SF Pro / SF Pro Text /
  SF Mono** (systemowe).
- **Marki LLM** — `assets/brands/claude.svg`, `openai.svg` **do dostarczenia** (template-
  image, tint). W prototypach glif Claude jest placeholderem (`redesign-sigils.js`).
- **Sygile i sygnet** — generowane w kodzie (Core Graphics + maska `--logo-sygnet` z
  `tokens.css`); brak plików bitmap.
- **Brak zdjęć/ilustracji** — powierzchnia jest typograficzna.
- **`screenshots/`** — pełnostronicowe podglądy każdego ekranu-specu (PNG), gdyby ktoś
  przeglądał paczkę bez otwierania HTML. Nie są źródłem — źródłem jest HTML + redline.

---

## 14. Pliki w tej paczce

**Buduj z tych (aktualny spec):**
- `redesign-a-przeglad.html` … `redesign-i-feedback.html` — ekrany A–I (pełne siatki stanów)
- `redesign-changelog.html` — **lista różnic beta.17 → redesign (zacznij tutaj)**
- `redesign-spec.css` — wspólny system komponentów okna (metryki, kolory, stany)
- `redesign-sigils.js` — silnik sygili + ikon (spec kształtu → Core Graphics)
- `tokens.css` — źródło prawdy tokenów (kolory, typografia, radius, spacing, sygnet)
- `app-ia-map.html` — architektura informacji (kontekst kierunkowy)
- `app-ia-before-after.html` — ten sam moment w beta.17 vs. nowa architektura (ilustracja)
- `fonts/` — 6 plików (render HTML)
- `screenshots/` — 12 pełnostronicowych PNG: `A-przeglad` … `I-feedback`, `changelog`,
  `ia-map`, `before-after` (tylko podgląd; wiążące są HTML + redline'y)

**Kolejność czytania:** `app-ia-map` (dlaczego) → `redesign-changelog` (co zmienić) →
ekrany `A–I` (jak, z redline'ami).

**Poza zakresem tego portu (świadomie pominięte):**
- Wcześniejsze iteracje okna Insights (`insights-dashboard-redesign`,
  `insights-window-components-redesign`, `insights-card-redesign`) oraz
  `recall-window-extension` — **zastąpione** przez ekrany A–I (patrz stopka changelogu).
- **Reader notatek (trzeci tryb okna) — Faza 6**, poza zakresem; zarezerwowane miejsce w
  architekturze (mapa IA §7). Nic w tym porcie od niego nie zależy.
- Materiały wideo / style frame'y (`teaser-v2-*`) — nie są ekranami apki.

---

## 15. Niezmienniki (nie zgub ich w porcie)

1. **Jedno okno, dwa wykluczające się tryby; chrome należy do trybu.** Stopka triażu istnieje
   tylko w Przeglądzie — to gwarancja architektury, nie warunek w kodzie.
2. **Jedna główna akcja na widok** (Przegląd → Zachowaj · Pytanie → otwórz źródło, z jedyną
   eskalacją Zsyntetyzuj · Synteza → Zapisz do vaulta).
3. **Granica lokalne/chmura zawsze jawna** — jadeit „lokalnie", złoto „✦ do chmury"; 3 gesty
   wychodzą do chmury i tylko one.
4. **Role akcentów egzekwowane twardo** (§7).
5. **Jedna powierzchnia customowa** (Konstelacja + ask-bar); wizard/ustawienia/dialogi natywne.
6. **Copy całość PL z diakrytykami.** Wymiary okna i rodzina promieni 6 px — bez zmian.
