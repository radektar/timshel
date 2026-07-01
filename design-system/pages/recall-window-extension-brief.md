# Recall — rozszerzenie okna „Konstelacja" o „zapytaj swój korpus" — brief do Claude Design

> Następca `insights-ui-brief.md`. **Okno „Konstelacja" (Blok B) jest już zaprojektowane
> i zportowane do kodu** (`dashboard_window.py`, beta.17). Ten brief **NIE projektuje okna
> od nowa** — **rozszerza** je o warstwę PULL (recall): zapytaj korpus i dostań uziemione
> wyniki. Importuj `../tokens.css`. Reużyj okna, lewej szyny, czytnika, konstelacji i gramatyki
> 1:1 — to ma być ta sama powierzchnia, nie druga.

---

## 0. Co nowego / kontekst (przeczytaj najpierw)

Malinche dostaje **PULL (recall)** obok istniejącego **PUSH (digest/insighty)**. Trzy decyzje
są **zamknięte** i wiążą design:

1. **Search = embeddingi, BEZ LLM.** Wynik wyszukiwania to **uszeregowane, cytowane fragmenty**
   z notatek — *nie* wygenerowana proza. Zero halucynacji, 100% lokalnie, nic nie wychodzi z Maca.
   LLM pojawia się **tylko** przy insightach (digest) i przy **świadomej eskalacji** „Zsyntetyzuj
   te wyniki".
2. **Malinche to SOCZEWKA, nie czytnik/menedżer notatek.** Cytaty i chipy **otwierają się na
   zewnątrz** — w skonfigurowanej appce użytkownika (Obsidian / Pile / Finder; opener jest już
   konfigurowalny). **Żadnego czytania ani zarządzania plikami w appce.** To granica produktu.
3. **Jedno okno, dwa gesty.** Recall (zapytałeś) i insight (podsunięte) **dzielą tę samą
   powierzchnię i gramatykę** — różni je nagłówek, nie osobna zakładka „AI chat".

---

## 1. Co ten design ma rozstrzygnąć

**Jak warstwa PULL (zapytaj) współistnieje z PUSH (podsunięte) w JEDNYM oknie tak, by czuły się
jednym produktem** — a nie doklejonym czatem. To jest sedno; reszta to wykończenie.

Zasada przewodnia (Mem): **insight = „klepnięcie w ramię", recall = „głębokie nurkowanie".** Ten
sam dom, ścieżka między nimi w jeden klik.

---

## 2. Co zaprojektować

### Blok 1 · Ask-bar (wejście)
Globalny **hotkey z dowolnego miejsca** → spotlight-owy ask-bar → **ląduje w oknie Konstelacja**
(panel do *wpisania* myśli; okno do *wyrenderowania* uziemionej odpowiedzi). Pole tekstowe +
opcja **zapytania głosem** (masz transkrypcję — naturalny fit dla „myślę na głos"). Stany:
pusty (z 1–2 podpowiedziami), pisanie, wysłane.

### Blok 2 · Wyniki wyszukiwania — BEZ LLM
Uszeregowana lista **trafień-fragmentów**. Każdy wiersz = **tytuł notatki + data + dosłowny
cytat (snippet) + timestamp** (jeśli dostępny). Klik → **otwiera źródło w skonfigurowanej
appce** (nie renderujemy w środku). Wizualnie **odróżnione od kart-insightów** — to *dowody*,
nie *teza* — ale w tej samej powierzchni i tokenach. **Stan abstynencji**: „Nic w Twoich
notatkach o X — najbliższe trafienie: […]" + wyjścia (poszerz / przekaż do Claude/ChatGPT).

### Blok 3 · Blend push ↔ pull
Insighty (nagłówek **„Podsunięte"**) i wyniki (nagłówek **„Zapytałeś"**) dzielą okno i lewą
szynę. Na każdej karcie-insightu: **„Zapytaj o to"** → pre-fill ask-bara zawężony do źródeł tego
insightu. Wizualnie nie da się powiedzieć „to się samo pojawiło" od „o to zapytałem" — różni
tylko nagłówek i ranga.

### Blok 4 · Eskalacja „Zsyntetyzuj te wyniki" (jedyny LLM w tym przepływie)
Świadoma akcja zamienia zestaw wyników w **kartę Konstelacji** (teza → cytowany dowód →
kierunki) — **ta sama gramatyka co insight**, wizualnie oznaczona jako *synteza*. Streaming
odpowiedzi z cytatami przy zdaniach. **Tu — i tylko tu — dopasowane fragmenty świadomie idą do
chmury.** Zapis odpowiedzi do vaulta jako notatka z żywymi linkami.

### Blok 5 · Indeksowanie / onboarding
Pierwszy bieg **embedduje istniejący vault w tle**: progress + **uczciwy szacunek czasu**
(„~5 min dla 1000 notatek"), **nie blokuje** — można pytać od razu, z bannerem „przeszukuję
240 z 1800". Status żyje **dyskretnie w menu** (Spoczynek / Indeksuję / Gotowe). Kolejne
nagrania indeksowane przyrostowo, bez nagabywania. Zero ręcznego tagowania/porządkowania.

---

## 3. Anatomia (okno + ask-bar; ascii)

```
┌ Malinche — Konstelacja ─────────────────────── [ ⌕ zapytaj swój korpus… 🎙 ] ┐
│ ┌ KORPUS ───────┐ ┌ CZYTNIK / WYNIKI ───────────────────────────────────────┐│
│ │ Zapytałeś (4) │ │  Zapytałeś: „co z dostawą okien i opóźnieniem dachu?"     ││
│ │  ● okna/dach  │ │  ──────────────────────────────────────────────────────  ││
│ │ Podsunięte(3) │ │  14.06 · Przygotowania do Eight Moons — okna i fundamenty ││
│ │  ◆ sprzecz.   │ │   „…dostępność okien przed sierpniem niepewna — blokuje   ││
│ │  ◆ wspólny    │ │    fundamenty…"                                    ↗ otwórz││
│ │  ◆ emergent   │ │  09.06 · Planowanie budowy domu — materiały okna dach     ││
│ │               │ │   „…producenci okien nie odpowiadają…"             ↗ otwórz││
│ │ (aktywność)   │ │  [ ✦ Zsyntetyzuj te wyniki ]        [ poszerz ] [ → Claude]││
│ └───────────────┘ └───────────────────────────────────────────────────────────┘│
└──────────────────────────────────────────────────────────────────────────────┘
```
Wynik (PULL) = lista cytowanych fragmentów, dowodowa, neutralna. Eskalacja → karta (teza/
dowód/kierunki), jak insight. Hierarchia: cytat czytelny, data wyróżniona, „↗ otwórz" zawsze.

---

## 4. Reuse — nie reinwentuj

Okno, lewa szyna, czytnik, **konstelacja (silnik inline-SVG)**, tokeny, gramatyka hero, stany
Zachowaj/Odrzuć — **wszystko już jest** (`dashboard-screens.html` + `dashboard_window.py`).
**Nowe** elementy tego briefu: ask-bar, wiersze-wyników (cytat+data+↗), nagłówki „Zapytałeś/
Podsunięte", przycisk eskalacji, banner/status indeksowania, abstynencja. Osadź je w istniejącej
gramatyce, nie obok.

## 5. Tokeny, typografia, kolor (kanon v2 z `tokens.css`)

- **Powierzchnia ciemna** (`--obsidian`), jak Insights.
- **Teza przy syntezie:** `--font-display` (Neue Montreal), pull-quote — jedyny „głos".
- **Wyniki/cytaty/UI:** `--font-body` (Neue Haas Grotesk); **data** w eyebrow (`--tracking-eyebrow`).
- **Akcenty:** insight/rozbłysk/synteza = `--status-insight` (gold); połączenia/węzły = `--terracotta`;
  **wyniki-dowód = neutralny** (świadomie chłodniejsze niż insight — to nie teza); Zachowaj = jadeit.
- **„↗ otwórz"** = dyskretny, ale zawsze obecny (to obietnica soczewki: wychodzisz do swojej appki).
- Cytat-wynik **mniejszy/spokojniejszy** niż teza-insight (hierarchia: dowód < teza).

## 6. Stany i interakcje (pokaż na makietach)

1. **Ask-bar** — pusty (z podpowiedziami) · pisanie · wysłane.
2. **Wyniki** — N trafień (kadr N=4), cytaty z datą, „↗ otwórz".
3. **Abstynencja** — 0/słabe trafienia → uczciwy komunikat + poszerz / przekaż.
4. **Synteza** — klik „Zsyntetyzuj" → streaming → karta Konstelacji (teza/dowód/kierunki).
5. **Blend** — insight („Podsunięte") i wynik („Zapytałeś") w jednym oknie; „Zapytaj o to" na karcie.
6. **Indeksowanie** — pierwszy bieg (progress + szacunek) · partial („240/1800") · status w menu.
7. **Konsekwencja soczewki** — klik cytatu → **otwiera w appce użytkownika**, okno trwa obok.

## 7. Realna treść (dane Radka — NIE lorem)

Korpus 8moons. Zapytanie + trafienia:

- **„Co z dostawą okien i opóźnieniem dachu?"** →
  `Przygotowania do Eight Moons — okna i fundamenty` (14.06): „…dostępność okien przed sierpniem
  niepewna — to blokuje fundamenty…" · `Planowanie budowy domu — materiały okna dach` (09.06):
  „…producenci okien nie odpowiadają, a bez nich dach i tak stoi w miejscu…".
- **Eskalacja → synteza** (karta): teza „Okna to wspólne wąskie gardło — brak potwierdzeń napina
  sierpniowy termin z dwóch stron"; kierunki: „Plan B na okna?", „Co zwalnia, jeśli się obsuną?".
- Drugie zapytanie do kadru: **„Co ustaliłem w sprawie jakości materiałów?"** → fragmenty z
  17.06/18.06 (Haetta / 8Moons filmiki 2) + opcja syntezy.

## 8. Locked vs open

**Locked:** search = embeddingi, **bez LLM** (wynik = cytowane fragmenty, nie proza); **soczewka**
(cytaty otwierają się na zewnątrz, zero zarządzania plikami); **jedno okno** push+pull; ciemna
powierzchnia; tokeny/kanon v2 (Neue Montreal, bez Fraunces); konstelacja-reuse; ton
(`Docs/TONE-OF-VOICE.md` — bez „drugiego mózgu", bez hype, bez emoji, krótkie polskie etykiety);
realne dane; reduced-motion; LLM tylko przy syntezie/eskalacji.

**Open (do interpretacji Claude Design):** umiejscowienie i zachowanie ask-bara (stały pasek u
góry okna vs overlay, który *ląduje* w oknie); **jak wiersze-wyników różnią się wizualnie od
kart-insightów, a wciąż czują się jednym produktem** (to jest serce briefu); przejścia trybu
search ↔ insight ↔ synteza; wizual abstynencji; traktowanie statusu/progress indeksowania; chipy
follow-up po syntezie; głos-do-zapytania (mikrofon w ask-barze); czy „Zapytałeś" i „Podsunięte"
to dwie sekcje szyny, zakładki, czy jeden strumień z etykietami.

## 9. Ograniczenia / kontekst / referencje

- **Cel = natywny AppKit.** Prototyp HTML to spec wyglądu; trzymaj się odwzorowalnego w
  `NSWindow`/Core Graphics. Rozszerza istniejące `dashboard_window.py` (Blok B), nie tworzy okna.
- **Guardrail soczewki:** to **nie** menedżer/czytnik plików. Recall = przeglądaj + przekaż dalej.
  Reading/zarządzanie = appka usera (Obsidian/Pile) — tam nie wchodzimy.
- **macOS ciemny**, dostępność (kontrast na ciemnym, polskie diakrytyki), `prefers-reduced-motion`.
- **Reuse z repo:** okno + ekrany → `dashboard-screens.html`; silnik konstelacji + gramatyka →
  `insights-ui-brief.md` §4 / `hero-graph-redesign-brief.md` §6; tokeny → `tokens.css`.
- **Powiązany plan (źródło prawdy techniczne):** `Docs/future/recall-markdown-native-plan.md`.

## 10. Deliverable

Samodzielny prototyp HTML/CSS importujący `../tokens.css`, ramki:

- **ask-bar** — pusty (z podpowiedziami) + pisanie.
- **wyniki** — N=4 cytowane fragmenty (tytuł+data+cytat+„↗ otwórz") + **abstynencja**.
- **synteza** — streaming → karta Konstelacji (teza/dowód/kierunki) z chipami follow-up.
- **blend** — insight („Podsunięte") i wynik („Zapytałeś") w jednym oknie + „Zapytaj o to".
- **indeksowanie** — pierwszy bieg (progress+szacunek) + partial + status w menu.
- **klatka konsekwencji** — klik cytatu → otwiera w appce usera, okno trwa obok.

Recall jako **rozszerzenie istniejącego okna**, obok siebie z trybem insightów — to ma dowieść,
że pull i push to jeden produkt.
