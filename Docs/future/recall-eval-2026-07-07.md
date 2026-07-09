# Recall eval (H3) — planted pairs vs candidate assembly

pairs: 52 confirmed | window-collisions excluded: 4 | skipped (missing note/date): 0

## Recall per config

| config | recall | hits/denominator |
|---|---|---|
| full | 60% | 29/48 |
| no-stance | 58% | 28/48 |
| no-graph | 58% | 28/48 |
| no-dense | 54% | 26/48 |
| no-entity | 60% | 29/48 |
| no-bridge | 58% | 28/48 |
| full-band | 56% | 27/48 |
| similarity-only | 42% | 20/48 |

Blended recall (full config): 60% -> GREY ZONE (50-70%)

## Full config — split by pair type (the real verdict)

- contradiction-over-time: 46% (6/13)  [GO ≥65%: ❌]
- emergent-idea: 55% (6/11)  [GO ≥60%: ❌]
- shared-thread: 71% (17/24)

**H3 verdict: ITERATE — contradiction and emergent must clear their GO thresholds.**

## Lexically-disjoint slice (Jaccard ≤ 10%, 38 pairs — the hard, uncheatable ones)

- recall: 55% (21/38)
  - contradiction-over-time: 36% (4/11)
  - emergent-idea: 60% (6/10)
  - shared-thread: 65% (11/17)

## Full config — split by source (bootstrap-bias detector)

- llm-proposed: 60% (29/48)
- radek-manual: 0% (0/0)

## Channel attribution (full config, hits)

- bm25: 29 surfaced-note credits
- tag: 22 surfaced-note credits
- bridge: 15 surfaced-note credits
- dense: 10 surfaced-note credits
- entity: 2 surfaced-note credits
- stance: 1 surfaced-note credits
- graph: 1 surfaced-note credits

## Unique saves per distance channel

- stance: 1 pairs only reachable with it: ['pp-017']
- graph: 1 pairs only reachable with it: ['pp-036']
- dense: 3 pairs only reachable with it: ['pp-004', 'pp-031', 'pp-044']
- entity: 0 pairs only reachable with it: []
- bridge: 1 pairs only reachable with it: ['pp-037']

## Misses (full config) — diagnostics

- pp-001 [contradiction-over-time]: 25-08-19 - Wielowymiarowy koncept wartosci - czas pieniadze i energia (RANKED-BUT-CUT)
- pp-006 [contradiction-over-time]: 25-09-25 - Budowa organizacji AI Native Non-Profit (RANKED-BUT-CUT)
- pp-007 [shared-thread]: 26-02-03 - Poprawa synergii zespolu AE Studio (RANKED-BUT-CUT)
- pp-008 [contradiction-over-time]: 25-09-25 - Wytyczne bezpieczenstwa AI dla organizacji non-profit (RANKED-BUT-CUT)
- pp-013 [shared-thread]: 25-12-11 - Pomysl ktory juz mialem dawno temu czyli trasy rowerowe po (RANKED-BUT-CUT)
- pp-018 [shared-thread]: 26-01-08 - Artystyczna przestrzen w 100 dole - wizja i wyzwania (RANKED-BUT-CUT)
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
- pp-054 [emergent-idea]: 25-09-24 - Instrukcja obslugi i kalendarz rezerwacji rybojadow (RANKED-BUT-CUT)
- pp-055 [shared-thread]: 26-06-05 - Planowanie budowy domu - materialy okna dach (RANKED-BUT-CUT)
- pp-056 [shared-thread]: 26-01-27 - Aktualizacja projektu LAN graf agentowy (RANKED-BUT-CUT)

Miss anatomy: 19 notes ranked-but-cut (budget problem: raise MAX_SYNTHESIS_NOTES / rebalance channels) vs 0 never found (discovery problem: channels blind to them).
