# Działanie funkcjonalności — okno „Konstelacja" (opis behawioralny)

Uzupełnienie README: **jak aplikacja się zachowuje**, krok po kroku, zdarzenie →
reakcja. Dla implementacji logiki (nie wyglądu — wygląd w spec C1–C8).

## 1. Model mentalny

Aplikacja indeksuje lokalny vault notatek i robi dwie rzeczy:
- **Push (Serendypacje):** cyklicznie generowany digest podsuwa połączenia między
  notatkami (sprzeczność / wspólny wątek / emergentny pomysł). Użytkownik je
  triażuje: Zachowaj / Odrzuć.
- **Pull (Zapytałeś):** użytkownik pyta własny korpus; dostaje cytowane fragmenty
  lokalnie; może eskalować (synteza, handoff do Claude/ChatGPT).

Okno = szyna (nawigacja) + pasek narzędzi z polem pytania + czytnik + stała stopka triażu.

## 2. Szyna — cykl życia

1. **Start okna:** otwarta sekcja „Serendypacje"; widok triażu = pierwszy
   niepusty z (Nowe → Zachowane → Odrzucone). Wybór sekcji/widoku z bieżącej
   sesji wygrywa nad regułą.
2. **Klik nagłówka innej sekcji:** poprzednia zwija się do nagłówka z licznikiem,
   kliknięta rozwija się w miejscu (animacja wysokości ~180 ms; reduced-motion → cięcie).
   Czytnik pokazuje ostatnio aktywny element nowej sekcji (lub jej stan pusty).
3. **Klik członu segmentu triażu:** przełącza listę Nowe/Zachowane/Odrzucone bez
   zmiany sekcji. Liczniki wszystkich trzech członów zawsze widoczne i aktualne.
4. **Klik wiersza:** ładuje element do czytnika; wiersz dostaje lewy pasek
   (złoty dla insightu, terakotowy dla zapytania).
5. **Pusty widok triażu:** lista = jedno zdanie + mostek-link do najcenniejszego
   niepustego widoku (klik = pkt 3).

## 3. Triaż insightu (poziom: cały insight)

- **Zachowaj** (stopka, jade): insight → widok Zachowane; toast jade „Zachowano ·
  Cofnij" (2 s); czytnik ładuje następny z kolejki Nowych; liczniki się aktualizują.
- **Odrzuć** (stopka, ghost): insight → widok Odrzucone (odwracalne — w widoku
  Odrzucone przycisk „Zachowaj" go odzyskuje); toast z „Cofnij".
- Licznik „1 z 3" w stopce = pozycja w bieżącym widoku.
- Stopka renderuje się tylko, gdy czytnik pokazuje insight (nie w trybie Pytanie,
  nie na stanie pustym).

## 4. Kierunki i handoff (poziom: zaznaczone kierunki)

1. Insight ma 2–4 kierunki (pytania pogłębiające). Checkbox = multi-select.
2. **0 zaznaczonych:** pod listą nie ma żadnego paska.
3. **≥1 zaznaczony:** pod listą wsuwa się pasek kierunków (fade + 8 px, ~180 ms):
   licznik + ikony wtórne (utwórz zadanie / kopiuj) + split-CTA „Kontynuuj w Claude ⌄".
4. **Caret ⌄:** menu wyboru narzędzia (Claude / ChatGPT); wybór globalny,
   zapamiętany, ten sam co w Ustawieniach.
5. **Klik CTA:** buduje prompt (teza + zaznaczone kierunki + cytowane źródła),
   otwiera narzędzie (prefill URL), **auto-zachowuje insight** → toast
   „Przekazano · zachowano", wiersz ląduje w Zachowanych, checkboxy się czyszczą,
   pasek znika. Odrzuć po handoffie = cofnięcie zachowania z potwierdzeniem.
6. **Ikony wtórne:** zadanie → Przypomnienia/Rzeczy (bez auto-zachowania? NIE —
   też zachowuje, każde „wyjście" kierunków zachowuje insight); kopiuj → schowek
   (markdown), toast „Skopiowano".

## 5. Pytanie (pull) — pełny przepływ

1. **Wejścia:** klik pola w pasku narzędzi · ⌘K (w oknie) · ⌥Space (globalnie,
   przez ask-bar `NSPanel` z poprzedniej paczki) · „Zapytaj o to" z insightu (prefill).
2. **Fokus pola:** pod polem rozwija się arkusz (560 px): input + „OSTATNIE
   PYTANIA" (3–5, z licznikami fragmentów). Scrim przyciemnia tylko czytnik;
   szyna klikalna (klik w szynę = zamknięcie arkusza).
3. **Klawisze:** pisanie filtruje nic (to nie search-as-you-type — zapytanie
   wykonuje się na ↵); ↑↓ chodzi po historii (wpis wskakuje do inputu);
   ↵ wykonuje; Esc zamyka bez śladu.
4. **Po ↵:** arkusz znika; okno przechodzi w tryb Pytanie: pytanie = tytuł
   czytnika (display 21–24 px), pod nim wyniki-cytaty (lokalnie, bez LLM);
   wpis dopisuje się na górę sekcji „Zapytałeś" (licznik +1).
5. **Wynik = jedna akcja:** klik wiersza otwiera notatkę źródłową w openerze
   (Obsidian/Pile/Finder); potwierdzenie inline „otwarto ✓" 2 s.
6. **Esc w trybie Pytanie:** powrót do Przeglądu (ostatni insight).
7. **Historia:** trwała między sesjami, w pełni lokalna; „wyczyść historię"
   w sekcji Zapytałeś.

## 6. Digest i pochodzenie

- Digest generowany cyklicznie (rytm w Ustawieniach) lub ręcznie z paska menu.
- Nowe insighty → licznik sekcji „N nowe" (złoto) + notyfikacja systemowa
  (jedna, klikalna) — okno samo się nie otwiera.
- Każdy insight niesie metadaną pochodzenia w nagłówku czytnika:
  „digest · 17.07 · Claude" (chip marki) lub „digest · 17.07 · lokalnie".
  Tooltip wyjaśnia, co opuściło Maca. Zero słowa „chmura".

## 7. Notatki (sekcja)

Przeglądanie korpusu: lista ostatnio zmienionych notatek (ikona + tytuł);
klik = otwarcie w openerze. Licznik = rozmiar indeksu („128"). Sekcja jest
nawigacją, nie edytorem — Timshel nie edytuje notatek.

## 8. Maszyna stanów (skrót)

```
window:
  section: serendypacje | zapytales | notatki   (persist: sesja)
  mode:    przeglad | pytanie                    (pytanie ⇒ stopka ukryta)
insight:
  triage:  nowy → zachowany | odrzucony          (odwracalne)
  handoff(dirs ≥1) ⇒ triage=zachowany + toast + clear(dirs)
ask:
  idle → focused(sheet) → submitted(mode=pytanie, history+1) | dismissed(esc)
digest:
  scheduled|manual → indexing → ready(counter+notif)
```

## 9. Feedback — kanały (delta)

| Zdarzenie | Kanał |
|---|---|
| Zachowaj / Odrzuć | toast 2 s + „Cofnij" |
| Handoff | toast „Przekazano · zachowano" + trwały ślad złoty pod kartą |
| Kopiuj | toast „Skopiowano" |
| Digest gotowy | licznik złoty + notyfikacja systemowa |
| Zapytanie wykonane | brak toastu — wynik JEST feedbackiem |
| Otwarcie źródła | inline „otwarto ✓" 2 s |

Zasady: jedno zdarzenie = jeden kanał; nigdy notyfikacja jako echo akcji użytkownika.
