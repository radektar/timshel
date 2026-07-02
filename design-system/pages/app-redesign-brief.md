# Malinche — redesign całej aplikacji: wszystkie ekrany, wszystkie stany — brief do Claude Design

> Następca i **nadzbiór** `insights-window-components-brief.md` (komponentowy brief z 2026-06-25 —
> jeśli masz go w toku, złóż tamtą pracę do tego przebiegu, nie kończ jej osobno). Poprzednie briefy
> projektowały pojedyncze komponenty lub pojedyncze rozszerzenia okna. Ten brief zmienia poziom:
> **zaprojektuj całą aplikację — każdą powierzchnię, każdy stan — zanim wrócimy do implementacji.**
> Powód: wdrożenie po raz drugi wyprzedziło design (doszedł cały tryb Recall, Fazy 3–5) i dogfood
> na realnym vaultcie wypadł źle. Decyzja procesowa: stop implementacji UI → pełny design → review
> Radka na projektach → dopiero potem kod. Importuj `../tokens.css`. Zrzuty z dogfoodu:
> `audit-2026-07-02/`.

---

## 0. Werdykt z dogfoodu (2026-07-02) — przeczytaj najpierw

Funkcjonalnie pipeline działa (wyszukiwanie lokalne, synteza, zapis, otwieranie źródeł). UX oceniony
jako zły w całości: **za dużo rzeczy naraz, nie wiadomo jak używać aplikacji**, do tego błędy UI.
Konkrety, każdy z dowodem:

1. **Dwa produkty wciśnięte w jedno okno bez sygnalizacji trybu.** Okno Konstelacji renderuje
   insights (push) i recall (pull) w tym samym readerze, ale szyna po lewej dalej pokazuje nawigację
   insightów, a **stopka „Odrzuć / Zachowaj" (triage insightów) wisi pod wynikami wyszukiwania
   i pod kartą syntezy** — użytkownik zadał pytanie, a UI proponuje mu „Odrzuć". Kontekst przecieka
   między trybami. → `audit-2026-07-02/01-synthesis-card.png`, `02-recall-results.png`.
2. **Segment triażu rozjechany.** Etykiety „Zachowane 0" / „Odrzucone 0" wylewają się poza obrys
   chipa. To ten sam komponent, który był priorytetem C1 poprzedniego briefu — nadal niezaprojektowany.
   → `03-chip-odrzucone.png`, `04-chip-zachowane.png`.
3. **Zero sygnału indeksowania przy starcie.** Stan indeksowania jest zamodelowany
   (`IndexingState`, `src/connections/recall/indexing.py:23`), ale pokazywany w **jednym** miejscu:
   banner w readerze recall, wyłącznie gdy user już tam wszedł (`dashboard_window.py:1167`).
   Etykiety do chipa w menu (`IndexingState.label()`) **nigdy nie są wywoływane**. Użytkownik
   uruchamia apkę, w tle embedduje się cały vault — i nic o tym nie wie.
4. **„⤓ Zapisz do notatek" — nie wiadomo, co się stało.** Feedback to toast na 1,7 s
   (`dashboard_window.py:1636`); brak trwałego śladu i brak linku do zapisanej notatki — nie da się
   otworzyć tego, co się przed chwilą zapisało.
5. **Karta syntezy dubluje źródła.** Cytowane dowody w sekcji SYNTEZA + osobna lista ŹRÓDŁA z tymi
   samymi fragmentami niżej — dwie reprezentacje tego samego, jedna pod drugą. → `01-synthesis-card.png`.
6. **Surowy markdown w cytatach** („**przygotowania poprzedzające**" z literalnymi gwiazdkami)
   → `01-synthesis-card.png`.
7. **Akcenty bez systemu.** Terakota raz jako fill („Zapisz do notatek"), raz jako outline
   („Nowe", „Zapytaj o to"), złoto na „Zsyntetyzuj" — role kolorów (terakota=akcja, jadeit=lokalne,
   złoto=insight) nie są egzekwowane. → wszystkie zrzuty.
8. **Dwa języki wizualne w jednej aplikacji.** Ciemna, polska Konstelacja vs natywne, angielskie
   wszystko pozostałe (menu, Settings, wizard, log viewer, dialogi). Użytkownik przechodzi między
   nimi bez ostrzeżenia.

---

## 1. Zadanie

**Zasada nadrzędna — hierarchia zamiast kompletności.** Główna przyczyna dzisiejszego chaosu:
każdy widok pokazuje *wszystkie* przyciski i akcje naraz (ask-bar + triage + handoff + kierunki +
stopka w jednym kadrze). Projektuj odwrotnie: **jedna główna rzecz na ekran**, jedna wyraźna akcja
podstawowa, reszta ujawnia się progresywnie (hover, rozwinięcie, menu kontekstowe, wejście w tryb).
Stan domyślny każdego widoku ma być spokojny — użytkownik w 3 sekundy wie, co tu się robi i co
kliknąć. Jeśli jakaś akcja nie broni się w hierarchii, zaproponuj jej usunięcie zamiast upychania.
Miarą sukcesu jest to, ile dało się **schować lub wyciąć**, nie ile się zmieściło.

Zaprojektuj **kompletną aplikację** jako spójny system na `tokens.css`:

- **Najpierw architektura informacji (§2), potem ekrany (§3).** Bez rozstrzygnięcia IA projektowanie
  ekranów utrwali obecny chaos.
- **Każdy ekran we WSZYSTKICH stanach** (§3 wylicza je per ekran — to jest checklista pokrycia,
  nie inspiracja). Format jak w poprzednich briefach: siatki stanów obok siebie, spec, nie jedna
  ładna klatka.
- **Prototypy jako strony HTML** w `design-system/pages/` (konwencja `@dsCard`), importujące
  `../tokens.css`. Reużyj silnika sygili/konstelacji z poprzednich prototypów.
- Wynik przechodzi **review Radka przed jakąkolwiek implementacją**. Iterujemy na projektach.

## 2. Do rozstrzygnięcia najpierw: architektura informacji

Pytania, na które projekt musi odpowiedzieć wprost (z rekomendacją, nie menu opcji):

- **Push (insights) i pull (recall) — jedno okno czy dwa tryby z jawnym przełącznikiem?**
  Decyzja produktowa brzmiała: „pull i push mają czuć się jak jeden produkt" (ta sama gramatyka
  Konstelacji). Ale obecna implementacja pokazuje, że *jeden reader* bez jawnego trybu = przeciek
  kontekstu (stopka triażu pod wynikami). Zaproponuj model: co widzi szyna w trybie recall? co robi
  stopka? jak się wchodzi i wychodzi z trybu? gdzie żyje historia zapytań?
- **Podróż pierwszego uruchomienia.** Minuta 0: wizard → start indeksowania całego vaulta. Co widzi
  użytkownik w minucie 0, 2, 10? Gdzie żyje status indeksowania (chip w menu? banner? notyfikacja
  po zakończeniu?) i jak apka komunikuje „możesz już pytać, wyniki częściowe"?
- **System feedbacku.** Dziś: toasty 1,7 s + pełnoekranowe flashe + notyfikacje systemowe, bez
  reguły. Zaprojektuj jedną zasadę: co jest toastem, co trwałym śladem, co notyfikacją. Akcje
  z trwałym skutkiem (zapis notatki) muszą zostawiać klikalny ślad.
- **Jeden język wizualny.** Czy Settings/wizard/dialogi przechodzą na język Konstelacji, czy
  Konstelacja dostaje natywniejszą ramę? Rekomendacja + konsekwencje. Copy: całość PL czy całość EN
  — dziś miks.
- **Rola menu bar.** Menu to dziś 8 pozycji + dynamiczny status. Co jest naprawdę potrzebne
  w menu, a co powinno żyć w oknie?

## 3. Inwentarz ekranów i stanów (pokrycie = 100%)

Stan obecny, z kodu (`src/menu_app.py`, `src/ui/*`, `src/setup/*`). Projektujesz każdą pozycję;
możesz łączyć/usuwać powierzchnie, jeśli IA z §2 to uzasadnia — ale każdy stan musi mieć swój dom.

### A · Ikona w pasku menu + dropdown
- Ikona: 8 stanów statusu (idle / scanning / transcribing / downloading / migrating / recorder-idle /
  recorder-pending / error) + wariant ze **złotą kropką** (nieprzejrzane insighty).
- Menu: wiersz statusu (kilkanaście możliwych stringów — m.in. czekanie na rekorder, przetwarzanie
  pliku, pobieranie zależności, błędy), Insights (N), Import audio, Otwórz digest, Generuj digest,
  submenu Retranskrybuj (pusty / lista / w toku), Settings, Quit.
- **Nowe do zaprojektowania:** stan indeksowania recall w menu (Indeksuję d/t · Gotowe · Błąd ·
  Standby) — dziś niepodpięty.

### B · Okno Konstelacji — tryb INSIGHTS (push)
- Layout: header z licznikiem nawigacji · szyna 236 px (segment triażu, wiersze połączeń,
  Ostatnie transkrypty) · reader · ask-bar (zawsze widoczny) · stopka Odrzuć/Zachowaj.
- Stany readera: skeleton „Transkrybuję…" · pusty globalny („Cisza w korpusie") · pusty per widok
  (Nowe/Zachowane/Odrzucone) · karta połączenia (teza, chipy notatek, „Zapytaj o to", dowody
  zwinięte/rozwinięte, Kierunki multi-select) · pasek handoffu (pojawia się przy ≥1 zaznaczeniu;
  wariant ciasny) · flash Zachowane/Odrzucone · toast.
- Stany segmentu triażu: aktywny / nieaktywny / hover / licznik 0 — **z twardym limitem szerokości**
  (patrz zrzuty 03/04: dziś się nie mieści).

### C · Okno Konstelacji — tryb RECALL (pull)
- Stany: idle z zachętą + disclosure prywatności · szukam (lokalnie, bez AI) · wyniki (wiersze
  rank·data·tytuł·cytat·otwórz + meta „N fragmentów") · brak wyników z uczciwą abstynencją
  (+ przygaszony near-miss) · indeks niegotowy vs błąd wyszukiwania (dwa różne komunikaty) ·
  banner częściowego indeksu · eskalacja „Zsyntetyzuj te wyniki" (default / loading / nota
  prywatności) · **karta odpowiedzi** (teza · dowody z ↗ · Kierunki · Zapisz do notatek · „tylko
  wyniki"; wariant „brak pokrycia w notatkach") · synteza nieudana · **potwierdzenie zapisu
  z linkiem do notatki** (nowe) · historia/powrót (nowe, jeśli IA tak zdecyduje).
- Rozstrzygnij relację dowodów w karcie ↔ listy wyników pod nią (dziś dubel — zrzut 01).
- Hotkey ⌃⌥Space: stan „brak uprawnień Accessibility" wymaga swojego UX (dziś cichy no-op).

### D · Settings (4 sekcje: General / Transcription / Disks / Maintenance)
- Stany: listy dysków pusta/zapełniona, przycisk disabled, ostrzeżenie destrukcyjne, potwierdzenie
  zapisu, alert pobierania modelu. Dziś natywne, angielskie, wizualnie obce reszcie.

### E · Wizard pierwszego uruchomienia (7 kroków)
- WELCOME → SOURCE → BASIC (folder+język+model) → DOWNLOAD (okno postępu) → PERMISSIONS (FDA) →
  AI (oferta + klucz) → FINISH. Stany: kroki z akcesoriami i bez, 1–3 przyciski, progress dots,
  anulowanie („Configuration incomplete"). **Dołącz moment startu indeksowania** (z §2).

### F · Okno pobierania zależności
- Postęp determinate · komplet · błąd. (Również wariant „Repairing whisper-cli".)

### G · Log viewer
- Toolbar (poziom, szukaj, wyczyść) · lista na żywo · stan pusty/filtrowany.

### H · Dialogi systemowe
- Nieznany wolumen (Yes/No/Once) · potwierdzenia (retranscribe, reset pamięci + date picker, quit) ·
  About · aktywacja/status PRO. Decyzja z §2: natywne NSAlert czy język systemu.

### I · Notyfikacje macOS
- Digest gotowy (teza) · import start/koniec · retranskrypcja · postęp pobierania · błędy ·
  **koniec indeksowania (nowe?)**. Zaprojektuj zasadę: co zasługuje na notyfikację.

## 4. Ograniczenia

- **Natywny AppKit, bez web view.** Wszystko, co zaprojektujesz, będzie rysowane w AppKit —
  unikaj efektów niewykonalnych natywnie (blur-scrolle, złożone animacje layoutu). Sygile/kształty
  konstelacji są już rysowane natywnie — można na nich polegać.
- **`tokens.css` jest źródłem prawdy**: terakota = akcja, jadeit = „lokalne i prywatne",
  złoto = insight. Egzekwuj role, nie mieszaj.
- **Polskie diakrytyki** w każdym foncie i każdej wadze (ą ć ę ł ń ó ś ź ż).
- Prywatność to filar produktu: stany, w których tekst opuszcza Maca (synteza, digest, handoff),
  muszą być **wizualnie odróżnialne** od stanów w pełni lokalnych — to język jadeitu.
- Szerokości ekranów jak w obecnym oknie (~62% ekranu, szyna 236 px) są punktem wyjścia, nie
  dogmatem — jeśli IA wymaga innych proporcji, podaj liczby.

## 5. Deliverables

1. **Mapa IA** — jedna strona: powierzchnie, tryby, nawigacja, model feedbacku (odpowiedzi na §2,
   z rekomendacjami).
2. **Strony HTML per powierzchnia** (§3 A–I) z pełnymi siatkami stanów, na `tokens.css`,
   z markerami `@dsCard`.
3. **Changelog decyzji** — co się zmienia względem obecnej implementacji i dlaczego (to będzie
   spec dla implementacji po review).

Kolejność review: najpierw §5.1 (IA) — zatwierdzenie kierunku, potem ekrany. Nie projektuj
wszystkich ekranów przed akceptacją mapy IA.

## 6. Poza zakresem

- **Faza 6 (lekki reader/przeglądarka markdown)** — osobny brief (`notes-browser-brief.md`);
  zostaw w IA miejsce na wejście do niej, ale nie projektuj jej ekranów.
- Landing / strona — osobny tor.
- Zmiany w silniku (retrieval, synteza) — projektujesz powierzchnię, nie pipeline.
