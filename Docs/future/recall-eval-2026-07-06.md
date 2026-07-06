# Recall eval (H3) — planted pairs vs candidate assembly

pairs: 52 confirmed | window-collisions excluded: 4 | skipped (missing note/date): 0

## Recall per config

| config | recall | hits/denominator |
|---|---|---|
| full | 54% | 26/48 |
| no-entity | 54% | 26/48 |
| no-bridge | 48% | 23/48 |
| similarity-only | 48% | 23/48 |

**H3 verdict (full config): 54% -> GREY ZONE (50-70%) — iterate preselection**

## Full config — split by pair type

- contradiction-over-time: 46% (6/13)
- emergent-idea: 45% (5/11)
- shared-thread: 62% (15/24)

## Full config — split by source (bootstrap-bias detector)

- llm-proposed: 54% (26/48)
- radek-manual: 0% (0/0)

## Channel attribution (full config, hits)

- bm25: 26 surfaced-note credits
- tag: 20 surfaced-note credits
- bridge: 16 surfaced-note credits
- entity: 1 surfaced-note credits

## Unique saves per distance channel

- entity: 0 pairs only reachable with it: []
- bridge: 3 pairs only reachable with it: ['pp-031', 'pp-033', 'pp-050']

## Misses (full config) — diagnostics

- pp-004 [shared-thread] missing: ['25-11-25 - Koncepcja drzwi wejsciowych do sauny']
- pp-005 [contradiction-over-time] missing: ['25-09-25 - Notatki z filmow AI - Jak unikac nieoczekiwanych rezultat']
- pp-006 [contradiction-over-time] missing: ['25-09-25 - Budowa organizacji AI Native Non-Profit']
- pp-007 [shared-thread] missing: ['26-02-03 - Poprawa synergii zespolu AE Studio']
- pp-008 [contradiction-over-time] missing: ['25-09-25 - Wytyczne bezpieczenstwa AI dla organizacji non-profit']
- pp-012 [shared-thread] missing: ['25-09-02 - Trzecis wrzesnia notatka poprowerow musze sie zastanowic o']
- pp-013 [shared-thread] missing: ['25-12-11 - Pomysl ktory juz mialem dawno temu czyli trasy rowerowe po']
- pp-016 [shared-thread] missing: ['25-11-18 - Wizja i plan dzialania dla projektu przestrzeni wielofunk']
- pp-017 [shared-thread] missing: ['26-01-16 - Analiza procesu budowy stodoly i mozliwosci dofinansowania']
- pp-019 [emergent-idea] missing: ['26-01-20 - Smart Sauna Innovative Concept for the Lunar Works Project']
- pp-026 [contradiction-over-time] missing: ['25-12-08 - Przygotowanie filmu na bazie zdjec i kostium na impreze']
- pp-027 [contradiction-over-time] missing: ['25-09-25 - Notatki z filmow AI - Jak unikac nieoczekiwanych rezultat']
- pp-028 [emergent-idea] missing: ['26-02-15 - Przygotowania do remontu domu i budowy obory']
- pp-029 [contradiction-over-time] missing: ['25-11-25 - Uniwersalna aplikacja do transkrypcji nagran audio']
- pp-034 [emergent-idea] missing: ['26-03-16 - Infrastruktura Agenta Dla NGO i Donorow']
- pp-038 [contradiction-over-time] missing: ['26-05-15 - 8 Moons - Projekt Hata Zadania na nastepny tydzien']
- pp-039 [shared-thread] missing: ['26-06-18 - 8Moons Projekt filmikow instruktazowych dla 8moons']
- pp-040 [emergent-idea] missing: ['26-06-04 - Potencjal wizualizacji AR w e-commerce i uslugach projekt']
- pp-044 [emergent-idea] missing: ['26-02-10 - Wdrazanie wnioskow z analizy dzialan Aleksa']
- pp-049 [shared-thread] missing: ['26-04-08 - Wakacje jako abonament - koncepcja mobilnych domkow w atr']
- pp-052 [shared-thread] missing: ['26-02-10 - Wdrazanie wnioskow z analizy dzialan Aleksa']
- pp-054 [emergent-idea] missing: ['25-09-24 - Instrukcja obslugi i kalendarz rezerwacji rybojadow']
