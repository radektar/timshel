# Ingest — wgrywanie gotowych transkryptów (v1: txt + vtt)

Status: w implementacji (2026-07-08) · branch `feat/ingest-transcripts`

## Cel / hipoteza
Gasić cold-start małej grupy H1: tester wrzuca własne notatki/eksporty → pierwszy
digest ma materiał. Przy okazji bypass Meet/Zoom przez ich eksport `.vtt`, bez
integracji API. **Import to on-ramp, nie nagłówek.**

- **Binarny sygnał:** zimny tester importuje stare notatki → pierwszy digest ma
  ≥3 insighty warte akcji w tygodniu 1 (vs zagłodzony bez importu).
- **Kill:** import (zwł. wieloosobowy) daje szum zamiast wartych akcji *połączeń
  dowolnego typu* → import to pomoc onboardingowa FREE, nie feeder PRO.

## Kluczowy ruch architektoniczny — split, nie drugi pipeline
`_postprocess_transcript(audio_file, txt_path, fingerprint, version)` robi dziś
(a) zbiera tekst+metadane z audio, (b) **finalizuje**: summarizer(KNOWN TERMS) →
markdown → temp cleanup. Wydzielam (b):

```
_finalize_note(text, metadata: dict, fingerprint, *, version,
               previous_version=None, output_filename=None) -> md_path
```

- Ścieżka audio: `_postprocess_transcript` czyta txt + `extract_audio_metadata`,
  potem woła `_finalize_note`. Zachowanie niezmienione — chroni istniejący zestaw.
- Ścieżka importu: adapter buduje `(text, metadata, fingerprint)` i woła to samo.

Altitude-correct: jeden mechanizm „tekst → notatka", dwa źródła.

## Komponenty (nowe)
1. `src/ingest/__init__.py` — `import_text_file(source) -> bool` (mirror
   `import_audio_file`: te same locki workflow+process z Fix 7).
2. `src/ingest/adapters.py` — `parse(source) -> ImportedDoc`; dispatch po
   rozszerzeniu: `.txt/.md` → treść, tytuł=stem, recorded_at=mtime; `.vtt` →
   strip cue-timestampów/indeksów; nieznane → `ValueError`.
3. `ImportedDoc` (dataclass): `text, title, recorded_at, source_label,
   extra_frontmatter`.
4. `src/ingest/fingerprint.py` — `text_fingerprint(text, source_name)` =
   `sha256:<hash treści+nazwy>`.

## Prowenansja
Frontmatter importowanej notatki: `source_type: import`, `origin: txt|vtt`.
Daje pomiar import-vs-audio + etykietę „źródło zewnętrzne vs Twoja notatka"
w kontradykcji zamiast fałszywego „flip-flop".

## Wejście
- `make import-text SRC=<ścieżka|katalog>` → iteruje pliki, woła `import_text_file`.
- Menu-bar „Import notes…" — później (ten sam wątek tła + alert busy co audio).

## Zakres — granice
- **v1:** txt, md, vtt (pokrywa cold-start + Meet/Zoom/Teams/Otter → wszystkie robią vtt).
- **NIE v1:** PDF (skany/OCR/layout — fast-follow), nazwane json platform,
  diaryzacja mówców.

## Testy
- `test_ingest_adapters.py` — vtt cue-stripping + recorded_at; txt; nieznane → ValueError.
- `test_ingest_fingerprint.py` — determinizm; różna treść → różny fp; dedup.
- `test_import_text_file.py` — pełny przebieg: notatka z `source_type: import`,
  wpis w vault_index, brak duplikatu przy 2×, honoruje workflow-lock (busy).
- Regression: istniejące testy transcribera zielone bez modyfikacji (audio przez
  `_finalize_note`).

## Kryteria akceptacji
- Import txt/vtt tworzy notatkę strukturalnie identyczną z audio-origin (poza
  prowenansją), przez summarizer v2 (Stanowiska gdy materiał je niesie).
- Ścieżka audio bez zmian zachowania — cały zestaw zielony.
- Importowana notatka wchodzi do recall i candidate_assembly.
- Ponowny import tego samego pliku = brak duplikatu (fingerprint).

## Ryzyka
- `_finalize_note` dotyka ścieżki H1-produkcyjnej — bezpiecznik: testy audio +
  osobny regression test.
- vtt wieloosobowy → Stanowiska mogą przypisać cudze zdanie jako userowe; łagodzi
  prowenansja, pełne lekarstwo = diaryzacja (odłożona).
- Import masowy podbija `new_notes` w scheduler → digest odpala wcześnie
  (pożądane dla cold-startu, świadome).
