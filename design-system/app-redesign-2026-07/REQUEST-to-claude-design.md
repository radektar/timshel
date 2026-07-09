# Request do Claude Design — domknięcie handoffu do pixel-perfect portu (AppKit/PyObjC)

**Od:** implementacja (Timshel, natywny macOS — AppKit przez PyObjC)
**Do:** Claude Design
**Dot.:** `design_handoff_app_redesign_2026_07`
**Data:** 2026-07-09

Handoff jest bardzo mocny — redline'y per ekran, tokeny, pełne siatki stanów,
plus wiążące „ograniczenie odwzorowalności" (layer/tint/wash). Zaczynamy port
**na tym, co jest**; poniższe punkty to rzeczy, których **HTML nie oddaje 1:1
w AppKit**. Nie blokują startu — ale bez nich port będzie „blisko", nie „pixel-
perfect". Uszeregowane: 🔴 bloker jakości · 🟡 wysokie · 🟢 nice-to-have.

Format prośby: gdzie się da, poproszę o **tabelę do wypełnienia**, nie o prozę.

---

## 🔴 1. Natywna rampa typograficzna (pojedynczy najważniejszy artefakt)

Handoff podaje rozmiary CSS (teza 24 px, body 12.5–13, eyebrow 10.5–11, mono
11–12) i mapę Neue Montreal→SF Pro, Neue Haas→SF Pro Text. Do natywnego renderu
potrzebuję **tabeli per styl tekstu** z kolumnami:

| Styl (selektor) | Próbka | SF Pro **Text czy Display** | Rozmiar **pt** | NSFontWeight | Tracking **pt** (lub em) | lineHeightMultiple | Token koloru |
|---|---|---|---|---|---|---|---|

Kluczowe niejednoznaczności do rozstrzygnięcia:
- **Text vs Display** — Apple przełącza optyczny wariant SF Pro na **20 pt**.
  Które style są Display, które Text? Szczególnie teza `24 px`, pytanie-tytuł
  `21–24 px` (straddle progu), eyebrow `10.5–11`.
- **px = pt?** — potwierdźcie, że redline'owe `px` to punkty @1x (a nie device px).
- **Waga `500`** — to `.medium` czy `.semibold` w SF Pro? (400/700 są jasne;
  „display 500" na tezie wymaga potwierdzenia.)
- **Tracking** — `-.012em` (teza), `.1em` (eyebrow/etykiety uppercase) → proszę
  o wartość w **pt per rozmiar** (albo zostawcie w em, przeliczę), bo NSKern
  bierze punkty, nie em.
- **lineHeight** — CSS `1.3` (teza), `1.25` (pytanie-tytuł), `1.5` (cytaty/wyniki)
  → jako `NSParagraphStyle.lineHeightMultiple`.

**Style do pokrycia (min.):** teza `.thesis` · pytanie-tytuł `.r-q` · eyebrow
typu · wiersz szyny `.rrow` (tytuł + skrót) · nagłówek-przełącznik `.collapsed-h`
· chip źródła `.nchip` · etykieta przycisku `.btn` · data wyniku (mono) · tytuł
wyniku · cytat wyniku · `<mark>` · licznik stopki (mono) · pozycja menu + skrót
(mono) · pole ask-bara + placeholder · toast · ślad `.trace` · kierunek `.dirrow`.

---

## 🔴 2. Inwentarz komponentów: custom-drawn vs natywne

Pixel-perfect stoi na tej granicy — **natywna kontrolka niesie własny padding,
focus-ring, baseline i hit-area**, których nie nadpiszę. Dla każdego komponentu:
**layer-backed NSView rysowany ręcznie**, czy **natywny AppKit z tintem/konfiguracją**?

| Komponent | Custom NSView / Natywny (jaki) | Uwaga |
|---|---|---|
| Przyciski `.btn-jade/ghost/syn/terra` | ? | custom czy stylowany NSButton? |
| Checkbox `.cbx` (16 px) | ? | custom czy NSButton typu checkbox? |
| Filtr „Nowe 3 ⌄" | NSMenu? | trigger = custom view? |
| Menu/popover `.menu` | prawdziwe NSMenu czy custom NSPanel? | hover-terakota + padding 6×9 sugerują custom |
| Ask-bar `.ask` | NSPanel (potwierdzone) — pole = NSTextField/NSTextView? | |
| Split-CTA „Kontynuuj w Claude ▾" | custom czy NSButton+NSMenu / NSSegmented? | |
| Chip źródła · wiersz wyniku · wiersz kierunku · ślad · toast | custom NSView? | zakładam custom — potwierdźcie |
| Title-bar | custom (titlebarAppearsTransparent + accessory)? | |
| Wizard/Ustawienia `.nativewin` | natywny NSWindow — które kontrolki 100% stock (NSButton/NSTextField/NSTabView) vs tint? | „spójność niesie akcent, nie tło" |

---

## 🟡 3. Reguły resize / reflow

Redline'y są dla jednej szerokości; okno jest resizable (min **740×460**, domyślnie
**~62% ekranu**). Proszę o:
- **Szyna 236 pt** — stała na każdym rozmiarze, czy ma min/collapse?
- **Reader (fluid)** — teza „max 30 em": przy jakim pt rozwiązuje się 30 em i czy
  **cała kolumna readera ma max-width (wyśrodkowana)**, czy rośnie z oknem? Padding
  readera przy min vs szeroko?
- Co **zawija**, a co **ucina** przy min szerokości: chipy, tekst kierunku, wiersze
  wyników, tytuł.
- Zachowanie **stopki triażu** i **paska handoffu** przy resize.
- Różnica default (~62%) vs zmaksymalizowane okno.

---

## 🟡 4. Specyfikacja ruchu (do CAAnimation)

Handoff podaje czasy (wsuwanie 150–180 ms, flash 180 ms, toast 2 s). Do natywnej
animacji potrzebuję per animacja:
- **Easing** — punkty cubic-bezier lub nazwana krzywa (ease-out?).
- **Która właściwość** — `opacity`, `transform.translateY` (o ile pt), czy oba;
  wartości from/to.
- Dotyczy: odsłonięcie paska handoffu (0→1 kierunek) · wsuwanie karty syntezy (D2)
  · flash-ring `btn-jade` (180 ms) · wejście/wyjście toastu · wymiana chrome przy
  zmianie trybu (B5).
- `prefers-reduced-motion` → handoff mówi „cięcie zamiast wsuwania" — potwierdźcie,
  że cięcie = natychmiastowa zmiana opacity (0 ms).

---

## 🟡 5. Hairline'y i sub-pixelowe obramowania

CSS używa `0.5 / 1 / 1.5 / 2.5px`. Na Retinie „1px CSS" = 1 device px = **0.5 pt** —
łatwo pomylić wagę całego UI. Per obramowanie:
- Które to **prawdziwe 1-device-px hairline'y** (renderuję 0.5 pt), a które
  **logiczne pt** (1 pt, 1.5 pt)?
- Pionowy pasek aktywnego wiersza `2.5px` — 2.5 pt logiczne czy device?
- Border checkboxa `1.5px` — logiczne pt?

---

## 🟢 6. Geometria sygili do Core Graphics

`redesign-sigils.js` daje SVG (viewBox 0 0 32 32; węzeł = 3 nałożone koła; poświata
radialna). Do `_SigilView.drawRect_` natywny spec skróciłby iterację:
- Dokładne **współrzędne węzłów** per typ (contradiction/shared/emergent).
- **Gradient radialny** poświaty i złotego rozbłysku: środek, promień, stopy
  (pozycje + kolory).
- Grubości/opacity łuków i linii (część jest w JS — potwierdźcie, że to źródło prawdy).
Port z JS zrobimy — to tylko redukcja zgadywania.

---

## 🟢 7. Znaki marek (brands)

Handoff: `assets/brands/claude.svg` + `openai.svg` „do dostarczenia", jako tintowane
template-image. **Oba już mamy w repo** — potwierdźcie, że odpowiadają docelowym
glifom (szczególnie **Claude** — w prototypie był placeholder `mIco('claude')`), albo
dostarczcie kanoniczne jednokolorowe SVG w docelowych rozmiarach (16 px w UI, ~20 px
na CTA).

---

## Potwierdzenia (nie braki — cele portu; obecny build beta.17 się rozjeżdża)

- Pasek aktywnego **insightu** = **złoto `#D6B033`** (handoff §7). *(build używa terakoty)*
- Title-bar po prawej = **tylko ⌕**. *(build pokazuje pager „N z N")*
- Stopka triażu ze środkowym licznikiem „1 z 3", tylko w trybie Przegląd.
- Wycięte: stały ask-bar w oknie, „OSTATNIE TRANSKRYPTY" w szynie, segment triażu 3-przyciskowy.

---

## Priorytet dla Was

Gdyby był czas tylko na jedno — **#1 (type-ramp) + #2 (inwentarz komponentów)**.
To dwie rzeczy, których nie da się wyprowadzić z CSS bez zgadywania i które
najmocniej decydują o „pixel-perfect vs blisko". Resztę (redline'y, tokeny, stany)
handoff już pokrywa i zaczynamy port na tym.
