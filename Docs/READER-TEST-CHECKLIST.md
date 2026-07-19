# Czytnik notatek — checklist testów manualnych (tester build)

Cel: zweryfikować czytnik in-app na realnym Macu z DMG. Automaty pokrywają
logikę (49 testów okna + fuzz + korpus 181 notatek); ta lista pokrywa to,
czego automat nie widzi: focus, płynność, odczucie nawigacji.

Build: DMG z iCloud `Timshel/` (sha na sidecarze `.sha256`). Po instalacji
sprawdź stamp w logu: `grep "Build:" ~/Library/Logs/timshel.log`.

## A. Wejścia do czytnika (5 min)

1. [ ] **Chip źródła:** otwórz Insights → klik w chip notatki pod tezą →
   notatka renderuje się w oknie (podsumowanie na górze, tytuł + data·czas).
2. [ ] **„Przejdź do transkrypcji ↓"** — skacze do sekcji Transkrypcja.
3. [ ] **Sekcja Notatki:** klik w notatkę z listy → czytnik; klik w INNĄ
   notatkę z listy → podmiana treści; **jedno** „← Wróć" wychodzi (nie
   przewija przez wszystkie klikane).
4. [ ] **„← Wróć" z chipa** wraca do TEGO SAMEGO insightu, na tej samej
   pozycji scrolla (zaznaczone kierunki nietknięte).

## B. Nawigacja wikilinkami (3 min)

5. [ ] Klik w zielony `[[wikilink]]` w treści → powiązana notatka w czytniku;
   „← Wróć" cofa po śladzie (A → B → Wróć → A).
6. [ ] Link `http(s)` w notatce → otwiera się w przeglądarce, czytnik zostaje.
7. [ ] Nieistniejący wikilink → nic się nie psuje (fallback do Obsidiana).

## C. Stabilność pozycji czytania (3 min) — sedno poprawek R2

8. [ ] Otwórz DŁUGĄ transkrypcję, przewiń do połowy → **zmień rozmiar okna**
   → pozycja czytania NIE ucieka do góry.
9. [ ] Czytaj notatkę w trakcie transkrypcji / gdy przyjdzie digest →
   widok nie mruga, pozycja zostaje.
10. [ ] Będąc w czytniku kliknij **insight na szynie** → od razu widać ten
    insight (nie trzeba „Wróć").

## D. Edycja i świeżość (2 min)

11. [ ] „Otwórz w Obsidianie ↗" → edytuj notatkę, zapisz → wróć do Timshel →
    klik w tę samą notatkę na liście → widać NOWĄ treść.
12. [ ] Skasuj w Obsidianie notatkę będącą w śladzie „Wróć" → „← Wróć"
    pomija ją bez błędu (i bez wyskoku do Obsidiana).

## E. Higiena (2 min)

13. [ ] Zamknij okno Konstelacji w trakcie czytania → otwórz ponownie →
    działa normalnie (bez pustej białej tafli).
14. [ ] ⌘K działa w trybie czytnika; zapytanie przełącza na wyniki (spinner
    się kończy, nigdy nie kręci w nieskończoność).
15. [ ] Zaznaczanie i kopiowanie tekstu z notatki działa.

**Raportowanie:** cokolwiek czerwone → screenshot + `Export feedback` z menu.
