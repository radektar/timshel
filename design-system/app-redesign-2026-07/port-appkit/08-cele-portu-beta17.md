# 08 · Cele portu + rozbieżności względem beta.17

Ten dokument to **kryteria akceptacji**: co build **beta.17** robi inaczej i co port ma
odtworzyć. Zacznij tu — potem `01`+`02` (fundament), `03`–`05` (zachowanie), `06`+`07`
(assety).

---

## Potwierdzenia (wprost o co pytano)

**1 · Pasek aktywnego wiersza — złoto vs terakota.**
Aktywny wiersz **insightu** (push, Przegląd) = **złoto `#D6B033`** (klasa `.rrow.active.au`).
Aktywny wpis **zapytania** (pull, Pytanie) = **terakota `#D9542A`** (`.rrow.active`).
Reguła: insight → złoto, akcja użytkownika → terakota. **beta.17 ma terakotę wszędzie** →
zmień pasek insightu na **złoty**. Szer. **2.5 pt**, `r2`, inset top/bottom 8 pt (`05`).

**2 · Title-bar po prawej — tylko ⌕.**
Prawy accessory title-bara = **wyłącznie ⌕** (`rgba(250,243,226,.55)`, hover pełna biel →
otwiera ask-bar, ekran C). **Bez pagera / licznika pozycji** (zszedł do stopki „1 z 3") i
**bez „✦ Nowy insight"** (zszedł do menu paska menu).

**3 · Stopka triażu — tylko w Przeglądzie.**
Stopka `Odrzuć · „1 z 3" (środek, mono `.4`) · Zachowaj` (46 pt) istnieje **wyłącznie w
trybie Przegląd**. W trybie Pytanie **jej nie ma** — to gwarancja architektury (chrome
należy do trybu), **nie** `if` w kodzie. „1 z 3" tylko w Przeglądzie.

**4 · Wycięte z okna (potwierdzone):**
- **Stały ask-bar (56 px)** → **wycięty**; wpisywanie tylko w overlay (⌥Space / ⌕), pytanie
  jest **tytułem** czytnika (C1 · B3).
- **„OSTATNIE TRANSKRYPTY" w szynie** → **usunięte**; historia „Zapytałeś" **zwinięta** do
  nagłówka-przełącznika, transkrypty nie żyją w szynie (B3).
- **3-przyciskowy segment triażu** → **filtr w nagłówku szyny** („Nowe 3 ⌄" → `NSMenu`),
  model 3 widoków bez zmian, Odrzuć odwracalny (A3).

---

## Changelog beta.17 → redesign (lista różnic do portu)

| Było (beta.17) | Jest (redesign) | Ekran |
|---|---|---|
| Stały ask-bar 56 px w oknie | Overlay ⌥Space / ⌕; pytanie = tytuł | C1 · B3 |
| Segment triażu (3 przyciski) | Filtr w nagłówku szyny „Nowe 3 ⌄" → `NSMenu` | A3 |
| Stopka Zachowaj/Odrzuć zawsze widoczna | **Tylko w Przeglądzie** (znika z architektury, nie przez `if`) | A4 · B1 |
| 3 równorzędne akcje pod wynikami | **Jedna** („Zsyntetyzuj", „do chmury"); „poszerz/przekaż" tylko w abstynencji (0 trafień) | B1 · B4 |
| Handoff: klaster 3 ikon zawsze | **Menu ⋯** + jeden split-CTA; pojawia się przy ≥1 kierunku | E2 · E3 |
| Brak oznaczeń lokalne/chmura | **Jadeit „lokalnie" / złoto „✦ do chmury"** na każdej granicy | B1 · H3 |
| „✦ Nowy insight" + licznik w title-barze | Do menu paska menu / do stopki („1 z 3") | F2 · A1 |
| Pasek aktywnego insightu terakotowy | **Złoto `#D6B033`** (insight); terakota tylko dla zapytania | A2 · §7 |

**Wymiary bez zmian:** szyna **236** · stopka **46** · handoff **48** · przyciski **30–32**
· title-bar **40** · okno **~62%** · min **740×460** · rodzina promieni **6 pt**.

---

## Mapa zdarzeń → kanał feedbacku (spec rozstrzygający, I4)

Każde zdarzenie ma **dokładnie jeden** kanał. Nowe zdarzenie w kodzie musi znaleźć wiersz
w tej tabeli, zanim dostanie UI.

| Zdarzenie | Inicjator | Kanał | Treść / cel kliku |
|---|---|---|---|
| Zachowaj / Odrzuć | użytkownik | **toast** | „Zachowano · Cofnij" — odwracalne w miejscu |
| Kopiowanie (kierunki, cytat) | użytkownik | **toast** | „Skopiowano…" — bez Cofnij |
| Zapis syntezy do vaulta | użytkownik | **ślad** (jadeit) | „Zapisano: plik.md ↗" — podwójny: karta + historia |
| Handoff do Claude/ChatGPT | użytkownik | **ślad** (złoto ✦) | „Przekazano do… ↗ otwórz wątek" — na karcie |
| Otwarcie źródła (soczewka) | użytkownik | **mikro-wash** | „otwarto ✓" 2 s na wierszu (B2) — poniżej progu toastu |
| Digest gotowy | aplikacja | **notyfikacja** | „3 nowe połączenia" → okno, Przegląd |
| Indeksowanie zakończone | aplikacja | **notyfikacja** | „Vault zaindeksowany" → ask-bar; tylko 1. bieg / przebudowa |
| Postęp indeksowania | aplikacja | **status** (pasek menu) | menu F2 + linia zakresu w wynikach (B4); zero toastów/notyfikacji |
| Błąd syntezy / sieci | aplikacja | **w miejscu** | komunikat w miejscu karty + „Spróbuj ponownie" (D4); **nigdy `NSAlert`** |
| Nagrywanie start/stop | użytkownik | **status** (ikona) | kropka przy sygnecie (F1); bez toastu |

**Anty-zasady:** nigdy dwa kanały dla jednego zdarzenia · nigdy notyfikacja jako echo akcji,
którą użytkownik właśnie widział · nigdy toast dla skutku trwałego (zostawia ślad).

---

## Niezmienniki (README §15 — nie zgubić w porcie)

1. **Jedno okno, dwa wykluczające się tryby; chrome należy do trybu.** Stopka triażu tylko
   w Przeglądzie — gwarancja architektury, nie warunek w kodzie.
2. **Jedna główna akcja na widok:** Przegląd → Zachowaj · Pytanie → otwórz źródło (jedyna
   eskalacja: Zsyntetyzuj) · Synteza → Zapisz do vaulta.
3. **Granica lokalne/chmura zawsze jawna** — jadeit „lokalnie", złoto „✦ do chmury"; do
   chmury wychodzą **3 gesty** (digest, synteza, handoff) i **tylko one**.
4. **Role akcentów egzekwowane twardo** (`00 §4`): akcja→terakota, lokalne→jadeit,
   insight/chmura→złoto.
5. **Jedna powierzchnia customowa** (Konstelacja + ask-bar); wizard/ustawienia/dialogi
   **natywne** (`02`).
6. **Copy całość PL z diakrytykami.** Wymiary okna i rodzina promieni **6 pt** — bez zmian.

---

## Świadomie poza zakresem tego portu

- Wcześniejsze iteracje okna (`insights-dashboard-redesign`,
  `insights-window-components-redesign`, `insights-card-redesign`, `recall-window-extension`)
  — **zastąpione** ekranami A–I.
- **Reader notatek (trzeci tryb okna) — Faza 6.** Zarezerwowane miejsce w architekturze;
  nic w tym porcie od niego nie zależy.
- Materiały wideo / style frame'y (`teaser-v2-*`) — **nie** są ekranami apki (glob
  `pages/app/teaser-v2-*`); konsumuje je osobny loop wideo.
