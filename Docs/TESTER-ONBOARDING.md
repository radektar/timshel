# Timshel — onboarding testera

Dzięki, że testujesz Timshela. Konfiguracja zajmuje ~15 minut, potem ~10 minut
raz w tygodniu. Cel testu: **czy połączenia, które Timshel znajduje między
Twoimi notatkami, są warte działania?**

> Interfejs jest częściowo po angielsku (menu przy ikonce), częściowo po
> polsku (główne okno). Nazwy przycisków cytujemy dokładnie tak, jak je
> zobaczysz.

## Czym jest Timshel (i co testujemy)

Timshel zamienia zwykły dyktafon w rejestrator AI: transkrybuje nagrania do
notatek Markdown w Twoim vaultcie, a płatna warstwa **Insights** czyta
archiwum i wyciąga nieoczywiste połączenia oraz sprzeczności między
notatkami. Testujesz, czy ta warstwa Insights jest coś warta.

**Prywatność:** cotygodniowy plik z feedbackiem, który odsyłasz, zawiera
wyłącznie tekst digestów, tytuły notatek i Twój słownik osobisty — nic
więcej. Nagrania i treść notatek nigdy nie opuszczają Twojego Maca.

## Wymagania

- Mac z Apple Silicon (M1 lub nowszy). **Maki z Intelem nie są wspierane.**
- macOS 12 (Monterey) lub nowszy.
- ~2 GB wolnego dysku; jednorazowe pobranie ~700 MB przy pierwszym starcie.

## 1. Instalacja

Timshel dostajesz mailem lub linkiem (nie przez iCloud). Pobierz DMG na dysk,
zanim zaczniesz.

1. Otwórz DMG i przeciągnij **Timshel** do Applications (Aplikacje).
   Potem **wysuń** obraz DMG (ikona na pulpicie → **Eject**) i uruchamiaj już
   apkę z folderu Applications, nie z DMG.
2. Apka nie jest jeszcze notaryzowana przez Apple, więc **podwójny klik ją
   zablokuje** — to normalne, nie znaczy, że coś jest nie tak. Odblokuj ją
   **raz**, jednym z poniższych sposobów. Zacznij od A; jeśli nie zadziała,
   przejdź do B.

   **A. Prawy klik → Otwórz**
   - W folderze Applications kliknij **prawym przyciskiem** (albo Ctrl+klik)
     na **Timshel** → **Otwórz**.
   - W okienku, które wyskoczy, kliknij **Otwórz** jeszcze raz.
   - Jeśli okienko ma tylko przyciski „Przenieś do Kosza" / „Anuluj" i **nie ma**
     „Otwórz" — to macOS 15/26, przejdź do B.

   **B. Ustawienia systemowe (macOS 15 / macOS 26)**
   - Kliknij dwukrotnie **Timshel** — pojawi się blokada, kliknij **Gotowe**.
   - Wejdź w **Ustawienia systemowe → Prywatność i ochrona**.
   - Przewiń na sam dół — zobaczysz komunikat *„Timshel został zablokowany…"*
     i przycisk **Otwórz mimo to**. Kliknij go (może poprosić o Touch ID/hasło).
   - Wróć do apki i kliknij **Otwórz** w potwierdzeniu.

   Robisz to tylko przy pierwszym uruchomieniu. Potem apka odpala się normalnie.

   **Awaryjnie (jeśli A i B zawiodą):** otwórz **Terminal** i wklej dokładnie tę
   linię, potem Enter — usuwa flagę kwarantanny, którą macOS nadaje pobranym
   plikom:
   ```
   xattr -dr com.apple.quarantine /Applications/Timshel.app
   ```
   Następnie uruchom Timshel normalnie. Jeśli i to nie pomoże — napisz do Radka
   z tym, co dokładnie zobaczyłeś na ekranie.

## 2. Kreator pierwszego uruchomienia

Kreator przeprowadzi Cię przez wszystko:

1. Wybierz folder docelowy — **wskaż swój vault Obsidiana** (albo dowolny
   folder na notatki).
2. Potwierdź pobranie silnika (~700 MB — potrzebny internet, kilka minut).
3. **Full Disk Access (Pełny dostęp do dysku)** — kreator otworzy Ustawienia
   systemowe. Włącz przełącznik przy Timshelu i **zrestartuj apkę**. To
   konieczne: bez tego Timshel widzi pustą kartę SD i nigdy nic nie
   transkrybuje.
4. Wklej **klucz Claude API**, który dostałeś od Radka: menu przy ikonce →
   **Settings…** → zakładka **Transcription** → pole **Claude API key**.

## 3. Zasiej vault

Insights potrzebują materiału do łączenia. Pierwszego dnia:

- Menu przy ikonce → **Import transcripts…** → zaznacz swoje istniejące
  transkrypty (txt / md / vtt — np. eksporty notatek ze spotkań). Celuj w
  **30+ notatek**.

## 4. Codzienne używanie

Nagrywaj albo importuj tak, jak normalnie pracujesz. Digest (podsumowanie
połączeń) pojawia się mniej więcej co tydzień w folderze **Timshel Digests**
w Twoim vaultcie.

Poza tym w głównym oknie (menu → **Insights**) możesz:

- **Przeszukiwać swoje notatki** — pasek pytania na górze okna albo skrót
  **⌃⌥Spacja** z dowolnego miejsca. Wyszukiwanie jest w 100% lokalne.
  Działa dosłownie (po słowach, które padły w notatkach) — jeśli nic nie
  znajduje, spróbuj słów, których naprawdę użyłeś w nagraniu.
- **Czytać notatki bez wychodzenia z apki** — klik w źródło przy połączeniu
  albo w notatkę w sekcji **Notatki** otwiera ją w oknie; „Otwórz w
  Obsidianie ↗" zostaje pod ręką.

## 5. Cotygodniowe 10 minut

Raz w tygodniu (np. w piątek):

1. Jeśli w tym tygodniu nie pojawił się digest: menu → **Generate digest
   now**.
2. Menu → **Insights** → przejdź **każde** połączenie i oceń je szczerze:
   **Zachowaj** (warte działania), **Odrzuć** (szum), albo **Kontynuuj w
   Claude** (najmocniejszy sygnał „to jest użyteczne").
3. Menu → **Export feedback** → zip ląduje na Biurku i Finder go pokaże.
   **Wyślij ten zip mailem na radoslaw.taraszka@gmail.com.**

Rób tak przez co najmniej trzy tygodnie.

## Gdy coś nie działa

- **Nic się nie transkrybuje / karta SD niewykryta** → brak Full Disk
  Access; włącz i zrestartuj apkę.
- **Brak podsumowań AI / brak digestu** → brak klucza API albo wyczerpany
  limit (menu → **Settings…** → **Transcription**).
- **Wyszukiwarka mówi, że nic nie ma** → chwilę po instalacji indeks może
  się jeszcze budować (spróbuj za minutę); pamiętaj też, że szuka dosłownie
  — po słowach z notatek, nie po skojarzeniach.
- **Cokolwiek innego** → menu → **Open logs**, albo napisz do Radka.
