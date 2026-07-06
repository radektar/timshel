# Recall eval (H3) — planted pairs vs candidate assembly

pairs: 52 confirmed | window-collisions excluded: 4 | skipped (missing note/date): 0

## Recall per config

| config | recall | hits/denominator |
|---|---|---|
| full | 65% | 31/48 |
| no-stance | 65% | 31/48 |
| no-graph | 65% | 31/48 |
| no-dense | 54% | 26/48 |
| no-entity | 65% | 31/48 |
| no-bridge | 62% | 30/48 |
| full-band | 58% | 28/48 |
| similarity-only | 48% | 23/48 |

Blended recall (full config): 65% -> GREY ZONE (50-70%)

## Full config — split by pair type (the real verdict)

- contradiction-over-time: 54% (7/13)  [GO ≥65%: ❌]
- emergent-idea: 55% (6/11)  [GO ≥60%: ❌]
- shared-thread: 75% (18/24)

**H3 verdict: ITERATE — contradiction and emergent must clear their GO thresholds.**

## Lexically-disjoint slice (Jaccard ≤ 10%, 41 pairs — the hard, uncheatable ones)

- recall: 59% (24/41)
  - contradiction-over-time: 45% (5/11)
  - emergent-idea: 55% (6/11)
  - shared-thread: 68% (13/19)

## Full config — split by source (bootstrap-bias detector)

- llm-proposed: 65% (31/48)
- radek-manual: 0% (0/0)

## Channel attribution (full config, hits)

- bm25: 31 surfaced-note credits
- tag: 25 surfaced-note credits
- bridge: 16 surfaced-note credits
- dense: 11 surfaced-note credits
- graph: 3 surfaced-note credits
- entity: 1 surfaced-note credits

## Unique saves per distance channel

- stance: 0 pairs only reachable with it: []
- graph: 1 pairs only reachable with it: ['pp-006']
- dense: 5 pairs only reachable with it: ['pp-004', 'pp-005', 'pp-007', 'pp-012', 'pp-017']
- entity: 0 pairs only reachable with it: []
- bridge: 1 pairs only reachable with it: ['pp-017']

## Misses (full config) — diagnostics

- pp-001 [contradiction-over-time]: 25-08-19 - Wielowymiarowy koncept wartosci - czas pieniadze i energia (RANKED-BUT-CUT)
- pp-008 [contradiction-over-time]: 25-09-25 - Wytyczne bezpieczenstwa AI dla organizacji non-profit (RANKED-BUT-CUT)
- pp-013 [shared-thread]: 25-12-11 - Pomysl ktory juz mialem dawno temu czyli trasy rowerowe po (RANKED-BUT-CUT)
- pp-019 [emergent-idea]: 26-01-20 - Smart Sauna Innovative Concept for the Lunar Works Project (RANKED-BUT-CUT)
- pp-026 [contradiction-over-time]: 25-12-08 - Przygotowanie filmu na bazie zdjec i kostium na impreze (RANKED-BUT-CUT)
- pp-027 [contradiction-over-time]: 25-09-25 - Notatki z filmow AI - Jak unikac nieoczekiwanych rezultat (RANKED-BUT-CUT)
- pp-028 [emergent-idea]: 26-02-15 - Przygotowania do remontu domu i budowy obory (RANKED-BUT-CUT)
- pp-029 [contradiction-over-time]: 25-11-25 - Uniwersalna aplikacja do transkrypcji nagran audio (RANKED-BUT-CUT)
- pp-034 [emergent-idea]: 26-03-16 - Infrastruktura Agenta Dla NGO i Donorow (RANKED-BUT-CUT)
- pp-038 [contradiction-over-time]: 26-05-15 - 8 Moons - Projekt Hata Zadania na nastepny tydzien (RANKED-BUT-CUT)
- pp-039 [shared-thread]: 26-06-18 - 8Moons Projekt filmikow instruktazowych dla 8moons (RANKED-BUT-CUT)
- pp-040 [emergent-idea]: 26-06-04 - Potencjal wizualizacji AR w e-commerce i uslugach projekt (RANKED-BUT-CUT)
- pp-049 [shared-thread]: 26-04-08 - Wakacje jako abonament - koncepcja mobilnych domkow w atr (RANKED-BUT-CUT)
- pp-052 [shared-thread]: 26-02-10 - Wdrazanie wnioskow z analizy dzialan Aleksa (RANKED-BUT-CUT)
- pp-054 [emergent-idea]: 25-09-24 - Instrukcja obslugi i kalendarz rezerwacji rybojadow (RANKED-BUT-CUT)
- pp-055 [shared-thread]: 26-06-05 - Planowanie budowy domu - materialy okna dach (RANKED-BUT-CUT)
- pp-056 [shared-thread]: 26-01-27 - Aktualizacja projektu LAN graf agentowy (RANKED-BUT-CUT)

Miss anatomy: 17 notes ranked-but-cut (budget problem: raise MAX_SYNTHESIS_NOTES / rebalance channels) vs 0 never found (discovery problem: channels blind to them).
