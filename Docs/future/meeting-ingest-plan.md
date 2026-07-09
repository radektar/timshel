# Meeting-ingest v2 — konektory źródeł (Zoom / Teams / drop-folder)

Status: plan na bramce (2026-07-09) · czeka na "ok" przed kodem
Kontekst strategiczny: vault → `research/2026-07-09 - Strategia rozszerzeń - synteza`
Baza: `Docs/future/ingest-plan.md` (ingest v1: txt/md/vtt — zmergowany, PR #65)

## Cel / hipoteza

„Skonfiguruj raz → dzieje się samo": transkrypty i nagrania spotkań (Zoom,
Teams; Meet przez drop-folder) trafiają do vaulta bez ręcznego importu.
Import eksportów, NIE capture audio systemowego (odrzucone — synteza).
Zasila korpus testerów H1, zanim H1 się skończy.

- **Binarny sygnał (gate z syntezy):** testerzy H1 realnie dostają notatki
  ze spotkań i ≥1 insight/tydz. pochodzi z nich.
- **Kill:** szum wieloosobowy → import zostaje onboardingiem FREE,
  konektory nie idą do marquee jako headline.

## Decyzje wejściowe (Radek, 2026-07-09)

1. **Transcript-first:** gotowy transkrypt (vtt/docx) > nasze audio→whisper.
   Wartość Timshela = krok PO transkrypcie (summarizer: tagi, Stanowiska).
   Audio przez whisper tylko gdy transkryptu brak.
2. **Meet:** v1 = drop-folder + instrukcja (Drive Desktop syncuje tylko
   wskaźniki `.gdoc` — brak taniej drogi auto). Konektor Drive OAuth =
   osobna decyzja po pomiarze popytu (sensitive scope → weryfikacja Google).
3. **Zero diaryzacji audio.** Zamiast tego reguła Stanowisk (niżej, §6).

## Architektura — konektor = (lokalizacja, matcher, prowenansja)

Rozszerzenie istniejącego `src/ingest/`, nie drugi pipeline. Nowy watcher
folderów obok `FileMonitor` (ten zostaje przy /Volumes — inna semantyka:
mount vs pliki w drzewie).

```
konektor (Zoom/Teams/drop) → folder watcher (FSEvents, file_events)
  → stability check (plik przestał rosnąć)
  → router per katalog spotkania:
      jest transkrypt (.vtt/.docx) → ingest adapters → _finalize_note
      tylko audio/wideo (.m4a/.mp4) → ffmpeg extract → istniejący pipeline whisper
  → dedup: text_fingerprint / audio fingerprint + vault_index
```

## Komponenty

1. **`src/ingest/connectors.py`** — dataclass `Connector(id, label,
   default_paths, suffixes, provenance)` + auto-detekcja:
   - `zoom`: `~/Documents/Zoom` (per-spotkanie podfolder: .m4a/.mp4/.vtt gdy
     user włączy lokalną transkrypcję w Zoom — jednorazowy hint w UI),
   - `teams`: wykryty root OneDrive + `Recordings/` (nagrania .mp4 lądują
     same; transkrypty .vtt/.docx user dokłada downloadem — ten sam folder),
   - `drop`: dowolny folder wskazany przez usera (Meet-exporty, Otter, inne).
2. **`src/folder_monitor.py`** — FSEvents (`file_events=True`) na listę
   folderów konektorów; debounce + stability check (size bez zmian ≥N s —
   OneDrive/Zoom dopisują pliki stopniowo); rescan przy starcie appki
   (spotkania z czasu, gdy appka nie działała).
3. **Router transcript-first** — grupowanie po katalogu spotkania (Zoom:
   jeden folder = m4a+mp4+vtt): transkrypt obecny → import tekstu, audio
   pomijane (fingerprint audio zapisany jako "covered", żeby późniejszy
   rescan nie transkrybował drugi raz); brak transkryptu → `.m4a` (lub
   ffmpeg-extract z `.mp4`) → `import_audio_file`.
4. **Adaptery:**
   - `_parse_vtt`: zachować mówców — `<v Nazwa>` (Teams) mapować na prefiks
     `Nazwa: ` PRZED strip tagów (dziś `_VTT_TAG` je wycina); Zoom pisze
     `Nazwa: tekst` w treści cue — przechodzi już teraz.
   - `_parse_docx` (nowe, Teams-transkrypt): python-docx, akapity
     `Nazwa: tekst`; bez stylowania.
   - `ImportedDoc.extra_frontmatter`: `source_type: meeting`,
     `origin: zoom|teams|drop`, `speakers: [..]` (unikalne etykiety,
     jeśli wykryte).
5. **Ustawienia + UI** — `UserSettings`: `meeting_connectors` (per konektor:
   enabled, path, override) + **`user_display_names`** (lista „jak nazywasz
   się na spotkaniach" — potrzebne, by Stanowiska wiedziały, który mówca
   to user). Menu: Ustawienia → „Meeting apps": 3 karty, toggle,
   wykryta ścieżka, pole nazwy; hint Zoom local-transcription.
6. **Reguła Stanowisk (summarizer)** — dla `source_type: meeting`:
   - etykiety mówców SĄ + user zmapowany (`user_display_names`) →
     Stanowiska tylko z wypowiedzi usera; reszta → sekcja „Głosy ze
     spotkania" (per osoba),
   - etykiet BRAK (audio-fallback, dyktafon na stole) → ZERO Stanowisk
     usera, tylko „Głosy ze spotkania" bez atrybucji.
   Zamyka ryzyko fałszywych kontradykcji („to nie było Twoje stanowisko").

## Zakres — granice

- **v1 (ten plan):** framework konektorów, Zoom, Teams-recordings,
  drop-folder, `_parse_docx`, mówcy w vtt, reguła Stanowisk, UI ustawień.
- **NIE v1:** Meet OAuth (po popycie) · diaryzacja audio (wraca tylko
  jeśli audio-fallback okaże się częsty u testerów) · capture systemowy
  (odrzucone trwale) · auto-download transkryptów Teams przez Graph API.

## Testy

- `test_connectors.py` — auto-detekcja ścieżek (tmp fixtures), enable/disable.
- `test_folder_monitor.py` — nowy plik → event; stability check; rescan
  przy starcie; ignorowanie plików tymczasowych.
- `test_router.py` — vtt obecny → tekst, audio pominięte + covered;
  sam m4a → pipeline audio; mp4-only → extract; dedup 2× rescan.
- `test_ingest_adapters.py` (rozszerzenie) — `<v Nazwa>` → `Nazwa: `;
  docx parsing; speakers w frontmatter.
- Reguła Stanowisk — unit na promptcie/outputcie summarizera dla obu gałęzi.
- Regression: ścieżka audio z /Volumes bez zmian (cały zestaw zielony).

## Kryteria akceptacji

- Zoom: nagranie spotkania z włączoną lokalną transkrypcją → notatka
  w vaultcie bez żadnej akcji usera (poza jednorazową konfiguracją).
- Teams: mp4 w OneDrive `Recordings/` → notatka (przez whisper); dołożony
  vtt/docx → notatka z mówcami, audio nie liczone drugi raz.
- Notatka meeting-origin wchodzi do recall i candidate_assembly;
  kontradykcje odróżniają „głos ze spotkania" od stanowiska usera.
- Ponowny import / rescan = zero duplikatów.

## Ryzyka

- **OneDrive Files On-Demand:** mp4 może być placeholderem (cloud-only) —
  odczyt wymusza download; wykrywać i nie blokować watchera (osobny wątek,
  te same locki workflow co audio).
- Duże mp4 (godzinne spotkania) → ffmpeg extract przed whisperem; czas
  transkrypcji = to, co produkt sprzedaje, ale UI musi pokazywać busy.
- Mapowanie usera po nazwie jest kruche (przezwiska, „iPhone Radka") —
  lista `user_display_names` edytowalna; miss → konserwatywnie: brak
  Stanowisk (nigdy fałszywa atrybucja).
- Import masowy przy pierwszym włączeniu konektora → digest odpala
  wcześnie (pożądane dla cold-startu; świadome, jak w ingest v1).
- `_finalize_note` / summarizer to ścieżka H1-produkcyjna — reguła
  Stanowisk za flagą prowenansji, notatki audio-origin bez zmian.
