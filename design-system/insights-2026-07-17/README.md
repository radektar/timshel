# Handoff: Timshel — okno „Konstelacja" · decyzje z uwag 17.07 (U1–U10)

Paczka-delta do implementacji w **AppKit (Swift)**. Nakłada się na paczkę
`design_handoff_app_redesign_2026_07` i **zastępuje jej fragmenty** (lista w §3).
Powstała z review builda z 17.07 — dziesięć uwag, dziesięć decyzji.

> **Dla Claude Code — przeczytaj najpierw §11 „Anty-błędy".** Ten dokument jest
> rozwlekły celowo: każda decyzja ma metryki, stany, zachowanie, copy i kryteria
> odbioru. Jeżeli czegoś tu nie ma — NIE improwizuj, zapytaj.

---

## 1. O plikach w tej paczce

Pliki `.html` to **referencje projektowe wykonane w HTML** — pokazują docelowy
wygląd i zachowanie. **Nie są kodem produkcyjnym do skopiowania.** Zadanie:
odtworzyć te designy w natywnym macOS (AppKit: `NSView` / `NSButton` / Core
Graphics), używając wzorców istniejącego kodu.

- `insights-window-components-redesign.html` — **kanoniczny spec komponentów**
  okna (sekcje C1–C8 + 2 pełne kadry). To jest źródło do portu.
- `insights-window-uwagi-1707.html` — dokument decyzyjny (diagnoza → opcje →
  decyzja per uwaga). Czytaj, gdy chcesz zrozumieć *dlaczego*; rozstrzyga też
  spory interpretacyjne.
- `tokens.css` + `fonts/` — tokeny (źródło prawdy) i fonty do wiernego renderu
  HTML w przeglądarce. W apce fonty mapują się na **SF Pro / SF Pro Text / SF Mono**.

## 2. Fidelity: **Hi-fi**

Finalne kolory, typografia, spacing, stany, copy. Odtwórz 1:1. Redline'y
(tabelki na dole każdej sekcji spec) są wiążące. Ograniczenie odwzorowalności:
wszystko musi się składać z `layer` (background / border / cornerRadius /
shadow), tint template-image, prosty wash-overlay, zmiana koloru tekstu —
**bez animowanych gradientów i efektów web-only**.

## 3. Co ta paczka ZASTĘPUJE w poprzedniej (`design_handoff_app_redesign_2026_07`)

| Było (A–I) | Jest (ta paczka) | Gdzie |
|---|---|---|
| Filtr triażu „Nowe 3 ⌄" → `NSMenu` (ekran A3) | **WYCOFANE.** Segment z 3 stale widocznymi licznikami, wewnątrz rozwiniętej sekcji | §5 (U9), spec C1+C8 |
| ⌕ w title-barze jako wejście w Pytanie | **WYCOFANE.** Pasek narzędzi z polem nad czytnikiem | §7 (U6 rev. 3), spec C8 |
| Pasek handoffu 48 px nad stopką (ekran E2) | **WYCOFANE.** Pasek kierunków POD listą KIERUNKI w czytniku | §6 (U4 rev. 2), spec C4 |
| Nazwa sekcji „Podsunięte" | **„Serendypacje"** (EN: „Insights") | §4 (U1) |
| Zaznaczony kierunek: tint + ramka terakotowa | **Bez ramki** — checkbox + tint tła | §6 (U7), spec C3 |
| Znaczniki „z chmury / ✦ do chmury" na digestach i CTA | **WYCOFANE** na tej powierzchni — cicha metadana + nazwa narzędzia | §8 (U5) |

Reszta poprzedniej paczki (ask-bar ⌥Space jako `NSPanel`, pasek menu F,
wizard G, ustawienia H, feedback I, tryb Pytanie B, synteza D) — **obowiązuje bez zmian**.
Uwaga: rola „✦ do chmury" z tamtej paczki zostaje w Ustawieniach/Prywatności (H3);
w oknie Konstelacja język chmury znika (§8).

## 4. U1 — Szyna: akordeon sekcji-rówieśników

**Architektura:** szyna 236 px = 3 sekcje-rówieśnicy: **Serendypacje** (licznik
sumy, np. „3" / złote „3 nowe" gdy nowe > 0) · **Zapytałeś** (liczba pytań) ·
**Notatki** (liczba notatek, np. „128"). Jeden wzorzec nagłówka niesie wszystkie.

**To NIE jest dropdown ani `NSMenu`.** Nagłówek to przełącznik-disclosure: klik
rozwija sekcję **w miejscu** (chevron › obraca się o 90°) i zwija poprzednią.
Nic nie nakłada się na treść. Dokładnie jedna sekcja otwarta naraz; zwinięte
trzymają liczniki. Stan per okno.

**Nagłówek sekcji (metryki):** wiersz 30 px wys., padding 0 8 px, radius 8 px,
hover bg `rgba(255,255,255,.05)`. Etykieta 10.5 px / 600 / wersaliki /
tracking .1em, kolor `#8C8273` → otwarta `rgba(250,243,226,.82)`. Licznik mono
10.5 px tabular `#6F665A`; wariant „N nowe" w `#D6B033` tylko gdy nowe > 0.
Chevron „›" 11 px przy prawej, otwarta = rotacja 90°.

**Przepełnienie (10+ insightów):** rozwinięta sekcja = flex 1 + scroll
wewnętrzny; nagłówki pozostałych sekcji **zawsze widoczne**; segment triażu
trzyma się góry listy; licznik bez limitu („12 nowych"). Szyna nigdy nie
wypycha sekcji poza okno.

**Wiersze zawartości:** insight = sygil 26 px + tytuł 12.5/600 + snippet 12 px
(clamp 2 linie), radius 12, aktywny: bg `.07` + lewy pasek 2.5 px złoty
gradient. Zapytanie/notatka = ikona 18 px (kolumna 18 px, wyśrodkowana
z tekstem) + tekst 12.5 px clamp 2.

✅ Odbiór: klik każdego z 3 nagłówków rozwija/zwija w miejscu; żadnego `NSMenu`;
liczniki widoczne przy zwiniętych; 15 insightów nie łamie layoutu.

## 5. U9 — Triaż: Zachowane nie mogą znikać

Wewnątrz rozwiniętych „Serendypacji": **segment Nowe / Zachowane / Odrzucone
z zawsze widocznymi licznikami** (spec C1). Aktywny człon: fill
`rgba(217,84,42,.16)` + border `rgba(217,84,42,.55)` + etykieta; nieaktywne:
sama ikona + licznik. Dropdown-filtr nie istnieje.

**Stan pusty widoku (np. Nowe = 0):** jedno zdanie 12.5 px `#8C8273`
(„Nic nowego. Digest wróci, gdy korpus urośnie.") + **mostek**: wiersz-link
„Zachowane czekają — 2 ›" (ikona zakładki 14 px, tekst 12.5/500 `#8BE0B5`,
hover bg wash) → przełącza segment na Zachowane.

**Fokus na starcie:** okno otwiera się na pierwszym niepustym widoku w kolejności
Nowe → Zachowane → Odrzucone. Wybór użytkownika w ramach sesji wygrywa.

✅ Odbiór: przy Nowe = 0 użytkownik NIE widzi pustej szyny — widzi zdanie +
mostek, a przy starcie okna ląduje od razu na Zachowanych.

## 6. U2 / U3 / U7 / U4 — Kierunki i akcje

**U2 — nagłówek listy:** jeden wiersz: etykieta „KIERUNKI" 11 px / 600 /
wersaliki `#8C8273`, zaczyna się **dokładnie na lewej krawędzi checkboxów**
(padding-left = padding wiersza, 14 px). Obok glif „?" — okrąg 14 px, border
`rgba(255,255,255,.16)`, znak 9 px, `cursor:help`; tooltip po ~400 ms:
„Zaznaczone kierunki trafią do handoffu — «Kontynuuj w Claude»."
**Żadnego opisu w layoucie** (tekst „zaznacz, by przekazać" usunięty).

**U3 — checkbox, jedna stała:** 18×18 px, border 1.5 px
`rgba(255,255,255,.24)` (hover `.5`), radius **5 px**, margin-top 3 px
(optyczny środek 1. linii tekstu). Zaznaczony: fill `#C24010`, haczyk biały
11 px. Jedna stała w kodzie — zero wartości per wiersz.

**U7 — zaznaczenie = jeden sygnał:** zaznaczony wiersz kierunku ma checkbox
wypełniony + tło `rgba(217,84,42,.09)` + tekst `#FAF3E2`. **Border wiersza
transparentny we WSZYSTKICH stanach** — żadnej ramki. Radius wiersza 12 px.

**U4 rev. 2 — dwa poziomy obiektów (decyzja architektury):**
- **Pasek kierunków** — pojawia się bezpośrednio **pod listą KIERUNKI**
  (ta sama szerokość i lewa krawędź), gdy zaznaczono ≥1 checkbox; znika przy 0.
  Wejście: fade + przesunięcie 8 px, ~180 ms. Radius 12, border
  `rgba(217,84,42,.28)`, tło ciepły gradient `rgba(44,24,17,.5)→rgba(28,16,12,.75)`.
  Zawartość: licznik „2 kierunki wybrane" (12.5/500 `#F0E0C8`; PL: 1 kierunek
  wybrany · 2–4 kierunki wybrane · 5+ kierunków wybranych) · spacer · ikony
  wtórne 34 px (zadanie, kopiuj; radius 6) · **split-CTA „Kontynuuj w Claude ⌄"**
  (fill `#C24010`, biały tekst 13/500, wys. 34, radius 6, chip marki 18 px na
  białym; caret oddzielony kreską `rgba(255,255,255,.32)`, przełącza Claude/ChatGPT).
- **Stopka okna jest STAŁA** — zawsze: Odrzuć (ghost) · „1 z 3" · Zachowaj
  (jade tinted: bg `rgba(70,177,126,.16)`, border `rgba(91,196,149,.5)`, tekst
  `#8BE0B5`). Działa na całym insightcie. **Nigdy nie morfuje**, nigdy nie niesie CTA handoffu.
- **Handoff ⇒ auto-Zachowaj:** klik CTA przekazuje kierunki I zachowuje insight.
  Toast: „Przekazano · zachowano". Wiersz wędruje do widoku Zachowane. Odrzuć
  po handoffie cofa zachowanie (z potwierdzeniem). Przekazać-a-potem-odrzucić
  to sprzeczność — system jej nie oferuje.

Dwa mocne przyciski (CTA terakota + Zachowaj jade) mogą współistnieć, bo działają
na **różnych obiektach w różnych strefach**. Gatunki przycisków zdefiniowane raz:
filled-primary / tinted-secondary / ghost / icon-secondary — wszystkie wys. 34 px, radius 6 px.

✅ Odbiór: 0 zaznaczeń → paska kierunków nie ma, stopka stoi; 2 zaznaczenia →
pasek pod listą (nie w stopce!); klik CTA → toast „Przekazano · zachowano" i
insight w Zachowanych; checkboxy piksel w piksel identyczne.

## 7. U6 rev. 3 + U8 — Wejście w „zapytaj" i arkusz historii

**Pasek narzędzi nad czytnikiem:** stały pasek **36 px**, border-bottom
`rgba(255,255,255,.07)` — **zaczyna się na prawej krawędzi szyny i NIGDY jej
nie nachodzi** (szyna sięga do title-baru). W pasku, przy prawej, pole
„⌕ Zapytaj swój korpus…" + badge ⌘K: wys. 28 px, szer. do 260 px (elastyczna,
min-width 0, tekst z ellipsis), radius 6, border `rgba(255,255,255,.16)`,
bg `rgba(255,255,255,.04)`, ⌕ w `#D9542A`. Title-bar czysty (trafficlights +
tytuł). **W szynie zero pól tekstowych.**

**Arkusz historii (U8):** fokus pola (klik / ⌘K / ⌥Space) rozwija pod polem
arkusz 560 px (wyrównany do pola, przyklejony do dolnej krawędzi paska):
wiersz inputu z caretem + mikrofon; nagłówek „OSTATNIE PYTANIA" 10/600
wersaliki; 3–5 ostatnich pytań (13 px, ikona ⌕ 12 px, licznik „6 fragm." mono
10.5 przy prawej, hover wash); stopka skrótów „↵ zapytaj · ↑↓ historia ·
esc zamknij" (11 px, nowrap). **Scrim `rgba(10,9,14,.45)` tylko nad kolumną
czytnika** — szyna zostaje aktywna. Pozycja stała — arkusz nigdy nie ląduje
„na dziko" na treści.

**Po Enter:** arkusz znika, okno przechodzi w tryb Pytanie (pytanie = tytuł
czytnika), wpis dopisuje się do sekcji „Zapytałeś" w szynie. ↑↓ przewija
historię, ↵ ponawia zaznaczone.

✅ Odbiór: pasek nie nachodzi na szynę (lewa krawędź paska = prawa krawędź
szyny); ⌘K fokusuje pole i otwiera arkusz; arkusz zawsze w tym samym miejscu;
po wysłaniu pytanie widoczne w „Zapytałeś".

## 8. U5 — Koniec z językiem „chmury"

Słowo „chmura" **znika z okna Konstelacja**:
- Pochodzenie digestu = **cicha metadana** przy prawej krawędzi nagłówka
  czytnika: chip marki 15 px (template-image, tint `#B0A28D`) + tekst
  „digest · 17.07 · Claude" 12 px `#6F665A`. Digest lokalny: „digest · 17.07 ·
  lokalnie". Tooltip: „Ten digest powstał z użyciem Claude — wybrane notatki
  zostały wysłane do Anthropic."
- Akcja handoffu = **„Kontynuuj w Claude"** / „Kontynuuj w ChatGPT" (czasownik +
  narzędzie, chip marki). Nigdy „do chmury".
- **Wersalikowe badge'e pochodzenia są zakazane** („Z CHMURY", „✦ DO CHMURY" — out).

## 9. U10 — Pusty czytnik: jedna kolumna + „co dalej"

Stan pusty czytnika to **jeden wycentrowany blok** (obie osie obszaru
czytnika, nie okna; max-width 360 px, tekst center):
sygil 46 px (opacity .85) → 14 px → tytuł 18 px display 500 `#FAF3E2` →
7 px → jedno zdanie 13.5 px `#8C8273` max 34ch.
Copy (widok Nowe): „Wszystko przejrzane / Nowych połączeń nie ma. Wrócą, gdy
korpus urośnie o kolejne notatki."

**Wiersz „co dalej"** 20 px pod blokiem — maks. 2 ciche akcje, wys. 30 px,
radius 6, **nigdy filled**:
1. mostek kontekstowy: przy pustych Nowych „Zachowane · 2" (jade tinted);
   przy pustych Zachowanych „Nowe · N" lub brak; przy pustych Odrzuconych — brak;
2. „Zapytaj swój korpus ⌘K" (ghost z ramką) → otwiera arkusz z §7.

Przy pustym widoku **stopka triażu się nie renderuje**.

✅ Odbiór: sygil + tytuł + zdanie to jedna pionowa oś (nie trzy luźne elementy);
akcje są pod blokiem; żaden element nie jest filled-primary.

## 10. Tokeny okna (dark) — skrót

Pełne źródło: `tokens.css` + `:root` w plikach spec.
- Tło czytnika: `radial-gradient(130% 120% at 64% 0%, #1C1B24, #16141C 52%, #100E15)`;
  szyna `rgba(0,0,0,.16)`.
- Tekst: hi `#FAF3E2` · body `#C9BBA6` · soft `#B0A28D` · mute `#8C8273` · faint `#6F665A`.
- Bordery na ciemnym: `.10 / .16 / .24` bieli; wash hover `rgba(255,255,255,.05)`.
- Terakota (akcja): `#C24010` fill · `#D9542A` akcent/ikony · tint `rgba(217,84,42,.09)`.
- Jadeit (lokalne/zachowaj): fill `rgba(70,177,126,.16)` · border `rgba(91,196,149,.5)` · tekst `#8BE0B5`.
- Złoto (insight): `#D6B033` · glow `#F4DD8E` — liczniki nowych, sygile, aktywny insight.
- **Rodzina promieni: 6 px kontrolki · 5 px checkbox · 12 px wiersze · 14 px karta okna.**
  Żadnych innych wartości; żadnych pill poza kropkami statusu.
- Fonty: display → SF Pro (500), body/UI → SF Pro Text, liczniki/skróty → SF Mono
  (tabular-nums). Copy PL z pełnymi diakrytykami.
- Wymiary okna: szyna 236 px · pasek narzędzi 36 px · stopka 46 px · przyciski 34 px ·
  okno ~62% ekranu, min 740×460.

## 11. Anty-błędy — czego NIE robić (częste błędy implementacji)

1. **Sekcje szyny ≠ dropdown.** Żadnego `NSMenu`/popovera do zmiany sekcji lub
   widoku triażu. Disclosure w miejscu + segment z licznikami.
2. **Żadnego pola tekstowego w szynie.** Pole żyje wyłącznie w pasku nad czytnikiem.
3. **Pasek narzędzi nie nachodzi na szynę.** Zaczyna się na jej prawej krawędzi.
4. **CTA handoffu nie wolno umieścić w stopce okna.** Stopka = tylko
   Zachowaj/Odrzuć, zawsze te same, zawsze w tych samych miejscach.
5. **Zaznaczony kierunek bez ramki.** Tylko checkbox + tint. Jeśli widzisz
   obwódkę na zaznaczonym wierszu — to błąd.
6. **Jeden checkbox-constant.** 18/1.5/r5/mt3 — jeżeli dwa checkboxy różnią się
   o piksel, to błąd.
7. **Zero słowa „chmura" w oknie.** Metadana nazywa narzędzie („Claude",
   „lokalnie"), CTA nazywa czynność i narzędzie.
8. **Radius spoza rodziny 6/5/12/14 = błąd.** Żadnych 4, 7, 9, 10 px „na oko".
9. **Empty state nie jest pusty.** Zawsze: zdanie + (jeśli dotyczy) mostek +
   „Zapytaj ⌘K". Stopka ukryta.
10. **Liczniki zawsze widoczne** — zwinięte sekcje i nieaktywne widoki triażu
    pokazują liczby; „0" nigdy nie ukrywa treści innych widoków.
11. **Toast po handoffie brzmi „Przekazano · zachowano"** — bo handoff
    auto-zachowuje. Jeśli po przekazaniu insight został w Nowych — błąd logiki.
12. **`prefers-reduced-motion`** → wsuwanie paska kierunków i arkusza zastępuje cięcie.

## 12. Stan i dane (delta do §12 poprzedniej paczki)

- `sectionOpen: serendypacje | zapytales | notatki` (per okno; default: serendypacje).
- `triageView: nowe | zachowane | odrzucone` + reguła startu: pierwszy niepusty.
- `selectedDirections: Set<Direction>` → widoczność paska kierunków.
- `handoff(directions)` → side-effect `keep(insight)` + toast + przeniesienie do Zachowanych.
- `askHistory: [{query, fragmentCount, timestamp}]` — trwała, lokalna; zasila
  arkusz (3–5 ostatnich) i sekcję „Zapytałeś".

## 13. Pliki

- `insights-window-components-redesign.html` — **spec kanoniczny C1–C8** (buduj z tego)
- `insights-window-uwagi-1707.html` — decyzje U1–U10 z uzasadnieniami (czytaj przy wątpliwościach)
- `BEHAVIOR.md` — **opis działania funkcjonalności** (przepływy, zdarzenie → reakcja, maszyna stanów)
- `screenshots/` — pełnostronicowe PNG obu dokumentów (tylko podgląd; wiążące są HTML + redline)
- `tokens.css`, `fonts/` — tokeny + render HTML

**Kolejność:** §3 (co się zmienia) → spec C1–C8 → `BEHAVIOR.md` (logika) → przy wątpliwości: dokument uwag → §11 przed code review.
