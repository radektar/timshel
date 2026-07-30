# Ingest v2 — konektory źródeł

Status: **faza 1 (Voice Memos) w implementacji** (2026-07-30) · reszta = backlog
Kontekst strategiczny: vault → `research/2026-07-09 - Strategia rozszerzeń - synteza`
oraz `research/2026-07-29 - Meeting-ingest - mapa narzędzi i dróg dostępu`
Baza: `Docs/future/ingest-plan.md` (ingest v1: txt/md/vtt — zmergowany, PR #65)

## Zmiana zakresu (2026-07-30)

Pierwotny plan (2026-07-09) obejmował Zoom + Teams + drop-folder naraz. Po
researchu narzędzi i spike'u Voice Memos zakres **fazy 1 zawężony do jednego
konektora: Apple Voice Memos**. Powody:

- **Największy zasięg adopcyjny** — nie wymaga dyktafonu ani firmowego Zooma,
  wystarczy iPhone. Nagrania przypływają same przez iCloud.
- **Zero nowej logiki treści** — głosówka jest solowa i pierwszoosobowa, tak jak
  materiał z dyktafonu. Nie potrzeba parsera docx, etykiet mówców, reguły
  Stanowisk ani destylacji długich transkryptów. To wszystko dotyczy dopiero
  spotkań wieloosobowych.
- **Zasila trwający test H1** zamiast czekać na jego koniec.

## Cel / hipoteza (faza 1)

„Skonfiguruj raz → dzieje się samo": głosówki nagrane na iPhonie stają się
notatkami w vaultcie bez żadnej akcji użytkownika.

- **Binarny sygnał:** tester włącza konektor i w ciągu tygodnia ma w vaultcie
  notatki z głosówek, których wcześniej by nie przepisał.
- **Kill:** głosówki telefoniczne okazują się materiałem gorszej jakości niż
  dyktafon (szum, przypadkowe nagrania) → konektor zostaje opcją, nie domyślną
  ścieżką.

## Spike — wyniki (2026-07-29/30, empirycznie)

| Pytanie | Odpowiedź |
|---|---|
| Ścieżka | `~/Library/Group Containers/group.com.apple.VoiceMemos.shared/Recordings/*.m4a` (stabilna Sonoma→Tahoe 26.x) |
| Uprawnienia | FDA, które apka i tak wymaga — zero nowych |
| Sync w tle | **Tak.** Po jednorazowym setupie (iCloud→Voice Memos na iPhonie + otwarcie appki raz na Macu) systemowy `voicememod` dosyła pliki przy zamkniętym GUI; zmierzone ~1 min od nagrania |
| Backfill | Całe archiwum spływa od razu (104 pliki od 2018 u autora) |
| Nazwa pliku | `YYYYMMDD HHMMSS-XXXXXXXX.m4a` — czas lokalny nagrania + stały id; 104/104 sparsowane poprawnie |
| `CloudRecordings.db` | **Nie czytamy** — zero zależności od prywatnego schematu Apple |

**Kluczowa pułapka: mtime kłamie.** To czas syncu, nie nagrania — całe archiwum
ma mtime z dnia pierwszego syncu, a eviction+redownload iCloud nadaje świeży.
Dlatego ani watermark „od dziś", ani dedup nie mogą się o niego opierać, a
`compute_fingerprint` (który przy tagless .m4a spada do mtime) dostaje jawny
`recording_datetime` z nazwy pliku.

## Architektura (zaimplementowana)

```
voicememod (iCloud) → Recordings/*.m4a
  → VoiceMemosWatcher (FSEvents, file_events=True)  [akcelerator]
  → VoiceMemosConnector.scan()                      [rdzeń pollowalny]
      parse nazwy → watermark → dedup (memo_id) → stability check
  → process_voice_memos()
      pre-filtr vault_index → Transcriber.import_audio_file(
          recorded_at=..., provenance={source_type: voice-memo})
  → istniejący pipeline: whisper → summarizer → notatka
```

Moduł: `src/voice_memos.py`. Stan: `voice_memos_state.json` (App Support),
zapis atomowy, `enabled_at` + `imported` + `failed{attempts,gave_up}`.
Wpięcie: `app_core.start()/_periodic_check()/stop()`. UI: sekcja „Voice Memos"
w ustawieniach + jednorazowa auto-propozycja + dialog backfillu.

Dwie linie dedupu: **memo_id** (stan konektora) oraz **vault_index po nazwie i
rozmiarze** (gdy stan zginie — bez tego pipeline nie pominąłby pliku, tylko
zrobiłby notatkę `.v2`).

## Backlog ingesta (świadomie odłożone)

Kolejność wg mapy narzędzi (`research/2026-07-29`):

1. **Zoom (local rec)** — watch-folder `~/Documents/Zoom/<data temat>/`; ten sam
   framework konektorów, dochodzi router transcript-first (jest `.vtt` → import
   tekstu, audio oznaczone jako „covered"; brak → whisper).
2. **Teams** — OneDrive `Recordings/` (mp4 auto; transkrypt `.vtt/.docx` ręcznym
   downloadem). Wymaga `_parse_docx` — **stdlib zipfile+ElementTree, NIE
   python-docx** (lxml do bundla dla samych akapitów to zła cena).
3. **Drop-folder** — uniwersalny odbiornik: Otter→Dropbox, eksporty MacWhisper,
   ręczne eksporty Meet/Krisp/Fathom. W UI zasługuje na instrukcje per-narzędzie.
4. **Reguła Stanowisk** (dla `source_type: meeting`) — mówcy zmapowani →
   Stanowiska tylko z wypowiedzi usera; brak mapowania → zero Stanowisk, tylko
   „Głosy ze spotkania". Bezwzględny warunek wpuszczenia materiału
   wieloosobowego: cudze zdanie nie może stać się stanowiskiem usera.
5. **Destylat spotkań** — do vaulta pełny transkrypt, do warstwy Insights tylko
   destylat. Chroni płaski model kosztów (bez tego okno digestu puchnie ~10×).
6. **Konektory API** — Fireflies pierwszy (GraphQL + webhooki na planie FREE),
   dopiero po sygnale popytu.

**Trwale odrzucone:** capture audio systemowego / boty na spotkaniach · Meet
przez Drive OAuth do czasu pomiaru popytu (sensitive scope → weryfikacja
Google/CASA) · reverse-engineering zaszyfrowanego cache Granoli.

## Ryzyka (faza 1)

- **TCC / Group Containers** — macOS może bramkować odczyt kontenera innej
  aplikacji. Obsłużone statusem `NO_ACCESS` + hintem w ustawieniach; wymaga
  weryfikacji **na buildzie DMG** (dev-run z terminala dziedziczy uprawnienia
  terminala i może fałszywie przechodzić).
- **Backfill archiwum** — 104 pliki to godziny whispera. Domyślnie „od dziś";
  archiwum wyłącznie jawnym opt-inem z liczbą plików, a lock i tak ustępuje
  nagraniom z dyktafonu.
- **Strefa czasowa** — nazwa pliku niesie czas lokalny bez TZ (naive), spójnie
  z resztą repo; nagrania z podróży dostaną czas „tamtejszy".
