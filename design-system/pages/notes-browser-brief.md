# Light notes browser/reader — trzeci tryb okna „Konstelacja" — brief do Claude Design

> Siostra `recall-window-extension-brief.md`. Ten sam projekt: **rozszerzenie istniejącego okna
> Konstelacja**, nie nowe okno. Dokłada **trzeci tryb** obok Insights (push) i Recall (pull):
> **Notatki** — przeglądaj, czytaj, rozumiej, drobno popraw. Cel: **Malinche stoi sama na gołym
> folderze, bez Obsidiana.** Importuj `../tokens.css`. Reuse okna, szyny, tokenów, gramatyki 1:1.

---

## 0. Kontekst / co nowego (przeczytaj najpierw)

**Korekta pozycjonowania:** Malinche przestaje *zakładać*, że user ma Obsidian/Pile. Musi dać
**minimum wartości na gołym folderze**: user bez żadnego PKM może przeglądać i rozumieć swoje
notatki w Malinche. To **NIE** jest zastąpienie Obsidiana — to **minimum**, świadomie małe.

Trzy tryby żyją w jednym oknie i jednej szynie:
- **Podsunięte** (insighty, push) — jest.
- **Zapytałeś** (recall, pull) — zaprojektowane w `recall-window-extension`.
- **Notatki** (browse+read, ten brief) — *nowe*.

**Guardrail (twardy):** to soczewka, która teraz też *czyta*, ale **nie zarządza jak Obsidian**.
Zero: wikilinków, backlinków, **grafu**, pluginów, szablonów, daily notes, canvas, zarządzania
folderami/hierarchią, split-view, zakładek, **WYSIWYG**, sync. Przeglądanie **po znaczeniu**
(tematy/tagi), nigdy po drzewie folderów — drzewo to dokładnie to, co Obsidian robi najlepiej.

---

## 1. Co ten design ma rozstrzygnąć

**Jak wygląda „czytnik notatki, który ROZUMIE"** — render markdown + **kontekst Malinche**
(streszczenie, powiązane insighty, tagi) — tak, żeby to był *czytnik Malinche* (nie Notatnik),
a jednocześnie *nie Obsidian*. I jak lista notatek siedzi w tej samej szynie co Zapytałeś/Podsunięte,
nie jako czwarta zakładka.

---

## 2. Co zaprojektować

### Blok 1 · Przeglądanie (browse)
Wejście **„Notatki"** w szynie → lista **wszystkich** notatek: tytuł + data, sort po dacie,
filtr/szukaj (po tytule i treści — recall już to ma) → klik = otwórz w czytniku. **v1 = lista +
szukaj.** Pokaż też *kierunek docelowy*: grupowanie **po tematach** (klastry znaczeniowe/tagi) jako
opcję nagłówka — ale lekko, to nie graf.

### Blok 2 · Czytnik notatki (read + understand) — rdzeń
Otwarta notatka w głównym obszarze okna:
- **Render markdown** (nagłówki, listy, pogrubienia, cytaty) — czytelnie, nie raw.
- **Frontmatter ładnie** (data · tagi · źródło · długość) — nie surowy YAML.
- Sekcje: **streszczenie (card)** wyróżnione + **transkrypcja**.
- **Panel kontekstu Malinche** (to odróżnia od Notatnika): **powiązane insighty/połączenia** dla tej
  notatki (mini-karty) + **tagi** (klikalne → filtr). „Rozumieć" = widzisz, co Malinche wyciągnęła.
- **Cytat z recall/insightu ląduje TU** — z zaznaczonym, dosłownym fragmentem. „Otwórz w Obsidianie"
  zostaje jako **opcja** obok (nie jedyna droga).
- Kopiuj tekst / fragment.

### Blok 3 · Edycja — **v1.1 (zaprojektuj, oznacz jako późniejsze)**
Toggle **render ↔ edit** → **prosty edytor markdown** (textarea/mono, *nie* WYSIWYG). Zapis na dysk.
Lekka edycja tagów/tytułu. Stan „edytujesz" + „zapisano". **Caveat konfliktu:** banner „plik zmieniony
na zewnątrz — przeładuj" (zapis+reload, bez merge). Wyraźnie druga faza — czytnik jest v1.

### Blok 4 · Stany brzegowe
- **Pusty** (świeży vault, brak notatek) — spokojny, z podpowiedzią „nagraj / wskaż folder".
- **Notatka bez streszczenia** (AI off) — pokaż samą transkrypcję, bez pustego card.

---

## 3. Anatomia (ascii)

```
┌ Malinche — Konstelacja ─────────────── [ ⌕ szukaj notatek… ] ─────────────────┐
│ ┌ KORPUS ───────┐ ┌ CZYTNIK ─────────────────────────┐ ┌ KONTEKST ──────────┐ │
│ │ Notatki (128) │ │ Przygotowania do Eight Moons —    │ │ Powiązane insighty │ │
│ │  ● okna/fund. │ │ okna i fundamenty                 │ │ ◆ Okna — wspólny   │ │
│ │  · budowa dom │ │ 14.06 · dyktafon · 12 min         │ │   wątek            │ │
│ │  · TekTutor.  │ │ #8moons #budowa #okna             │ │ ◆ Sprzeczność w    │ │
│ │ ─────────────  │ │ ── Streszczenie ──                │ │   czasie (jakość)  │ │
│ │ Zapytałeś (4) │ │ • dostępność okien niepewna…      │ │ Tagi               │ │
│ │ Podsunięte(3) │ │ ── Transkrypcja ──                 │ │ #8moons #budowa    │ │
│ │               │ │ „…producenci okien nie odp…"      │ │ [ ✎ edytuj (v1.1) ]│ │
│ └───────────────┘ └───────────────────────────────────┘ └────────────────────┘ │
└────────────────────────────────────────────────────────────────────────────────┘
```
Kontekst Malinche może być z boku (jak wyżej) albo pod treścią — do interpretacji. Sedno: notatka
+ to, co Malinche o niej wie, w jednym widoku.

## 4. Reuse — nie reinwentuj
Okno, szyna, tokeny, ciemna powierzchnia — jak Insights/Recall. Mini-karty w panelu kontekstu
reużywają gramatyki karty-insightu (sygil + typ + skrót). Szukaj = ten sam ask/search-field.

## 5. Tokeny, typografia, kolor (kanon v2)
- Ciemna powierzchnia (`--obsidian`).
- **Treść notatki:** `--font-body` (Neue Haas), czytelny rozmiar/leading — to ma się *dobrze czytać*.
- **Tytuł notatki + streszczenie:** `--font-display` (Neue Montreal), streszczenie lekko wyróżnione.
- **Kontekst Malinche:** akcenty jak insighty (gold/terakota) ale **mini** — sygnał „to derived",
  nie dominuje treści.
- Frontmatter: eyebrow/mono, stonowany.

## 6. Stany i interakcje (na makietach)
1. **Lista (browse)** — wszystkie notatki, szukaj, sort.
2. **Czytnik (read)** — notatka wyrenderowana + frontmatter + streszczenie + transkrypcja.
3. **Czytnik + kontekst** — panel powiązanych insightów/tagów; cytat zaznaczony (wejście z recall).
4. **Edycja (v1.1)** — toggle render↔edit, zapis, stan zapisano.
5. **Pusty** · **notatka bez streszczenia** · **konflikt edycji zewnętrznej**.

## 7. Realne dane (NIE lorem)
Notatka: **„Przygotowania do Eight Moons — okna i fundamenty"** · 14.06 · dyktafon · 12 min ·
tagi `#8moons #budowa #okna`.
Streszczenie: „Dostępność okien przed sierpniem niepewna — blokuje fundamenty. Brak potwierdzeń
producentów." Transkrypcja (fragment): „…producenci okien nie odpowiadają, a bez nich dach i tak
stoi w miejscu…". Kontekst Malinche: powiązany insight **„Okna — wspólny wątek"** (+ druga notatka
09.06) i **„Sprzeczność w czasie — jakość materiałów"**; tagi klikalne.

## 8. Locked vs open
**Locked:** samowystarczalność bez zastępowania; **NIE Obsidian** (zero wikilinków/backlinków/grafu/
pluginów/folderów/split-view/WYSIWYG/sync); trzeci tryb w **tym samym oknie**; ciemna powierzchnia;
tokeny/kanon v2; **render markdown czytelny**; **kontekst Malinche na notatce** (odróżnia od Notatnika);
cytaty otwierają się **in-app** (handoff = opcja); przeglądanie **po znaczeniu**, nie po drzewie folderów;
**edycja = v1.1**; realne dane; ton (`Docs/TONE-OF-VOICE.md`, bez emoji, krótkie polskie etykiety);
reduced-motion.

**Open (do interpretacji Claude Design):** układ czytnika (kontekst Malinche z boku vs pod treścią);
jak „Notatki" dzieli szynę z Zapytałeś/Podsunięte (trzy sekcje w jednym scrollu vs przełącznik trybu);
lista vs od razu grupowanie po tematach; traktowanie frontmattera (zwinięty vs pokazany); wygląd
toggle render↔edit; stan konfliktu zewnętrznej edycji; pusty stan.

## 9. Ograniczenia / kontekst / referencje
- **Cel = natywny AppKit.** Rozszerza `dashboard_window.py` (to samo okno co Insights/Recall). HTML = spec.
- **Guardrail: minimum, nie Obsidian.** Każda funkcja spoza „przeglądaj / czytaj / rozumiej / drobno
  popraw" jest poza zakresem. Reading/zarządzanie „na serio" = appka usera (opcjonalny handoff).
- **Edycja = druga faza** — zaprojektuj stan edycji, ale rdzeń to czytnik.
- macOS ciemny; dostępność (kontrast, polskie diakrytyki); `prefers-reduced-motion`.
- Reuse: `recall-window-extension.html` (okno, szyna, tokeny), `insights-ui-brief.md` (gramatyka karty),
  `tokens.css`. Plan techniczny: `Docs/future/recall-markdown-native-plan.md` (Faza 6).

## 10. Deliverable
Samodzielny prototyp HTML/CSS importujący `../tokens.css`, klatki:
- **lista notatek** (browse + szukaj),
- **czytnik** (render markdown + frontmatter + streszczenie + transkrypcja),
- **czytnik + kontekst Malinche** (powiązane insighty + tagi; cytat zaznaczony),
- **edycja (v1.1)** (toggle render↔edit + zapisano),
- **stany brzegowe** (pusty · bez streszczenia · konflikt).

Trzeci tryb **obok** Insights/Recall w tym samym oknie — ma dowieść, że Malinche **stoi sama na gołym
folderze**, nie stając się Obsidianem.
