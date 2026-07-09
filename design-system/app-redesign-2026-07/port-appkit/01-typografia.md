# 01 · Rampa typograficzna → SF Pro  **[BLOKER]**

Per styl tekstu okna „Konstelacja" (+ powierzchnie natywne). Kolumny gotowe do wklejenia
do `NSAttributedString`. Konwencje (px=pt, wagi, fonty) — patrz `00-README.md`.

---

## Rozstrzygnięcia (jawne)

**(a) Display czy Text.** Próg = **20 pt** i pokrywa się z auto-przełącznikiem
`NSFont.systemFont`. Powyżej/równo 20 pt → **SF Pro (Display)**; poniżej → **SF Pro Text**.
- **Display:** teza (24), pytanie-tytuł (21–24). To **jedyne** dwa style Display.
- **Text:** wszystko inne (≤ 15 pt).
- **Pułapka:** tytuł stanu pustego używa w webie *rodziny* display (Neue Montreal) przy
  `16 px`. W SF `16 pt` renderuje się optycznie jako **Text** — użyj `TS.font(16, .medium)`
  i zaakceptuj optyk Text (rola nagłówka zostaje, optyk nie). „Rodzina display w webie" ≠
  „optyk Display w SF".

**(b) px = pt @1x.** Redline w px czytamy jako pt 1:1 (`00 §1`). `24 px` → `24 pt`.

**(c) waga „500".** → **`.medium`** (nie `.semibold`). `.semibold`/`600` w projekcie nie
istnieje. `700` = `.bold`, `400` = `.regular` (`00 §2`).

**(d) tracking w pt.** `kern` w `NSAttributedString` jest w **punktach**:
`kern(pt) = tracking(em) × rozmiar(pt)`. SF ma własny optyczny tracking (per rozmiar) — te
wartości to **dodatkowy** `kern` nakładany, by dobić do zwięzłości prototypu. Dla eyebrowów
`kern` dodatni jest **obowiązkowy** (letterspacing wersalików).

| tracking (em) | rozmiar (pt) | **kern (pt)** | gdzie |
|---|---|---|---|
| −0.012 | 24 | **−0.29** | teza |
| −0.012 | 21 | **−0.25** | pytanie-tytuł |
| −0.012 | 16 | **−0.19** | tytuł stanu pustego |
| +0.10 | 10.5 | **+1.05** | eyebrow / nagłówek szyny / chip statusu / „Kierunki" |
| +0.10 | 11 | **+1.10** | eyebrow @11 |
| +0.04 | 11.5 | **+0.46** | data wyniku (mono) |
| 0 | — | 0 | reszta |

`lineHeightMultiple` = mnożnik CSS `line-height` wprost do `NSParagraphStyle`
(`1.3` → `1.3`). Dla stylów 1-linijkowych → `1.0`.

---

## Rampa — Display (SF Pro, ≥ 20 pt)

| Styl (selektor) | Próbka | Face | pt | Waga | kern (pt) | lineHeightMult | Token koloru |
|---|---|---|---|---|---|---|---|
| Teza `.thesis` | „Założenie o jakości przesunęło się…" | Display | **24** | `.medium` | −0.29 | 1.30 | `hi #FAF3E2`; `max 30em` |
| Pytanie-tytuł `.r-q` | „Co z dostawą okien i opóźnieniem dachu?" | Display | **21** (zakres 21–24) | `.medium` | −0.25 | 1.25 | `hi #FAF3E2` |
| Cytowanie `.thesis .cite` `[n]` | ¹ | Display | 14.4 (`.6em×24`) | `.medium` | 0 | — | `gold #D6B033`; baseline +≈6 pt (super) |

> Cytowanie `[n]`: nie używać `NSSuperscript` bez kontroli — ustaw `.baselineOffset ≈ +6`
> + font 14.4 pt. Kolor złoty (rola: synteza).

## Rampa — Szyna (rail, SF Pro Text)

| Styl | Próbka | Face | pt | Waga | kern | lhMult | Token |
|---|---|---|---|---|---|---|---|
| Nagłówek szyny `.rail-h` | PODSUNIĘTE | Text | 10.5 | `.medium` | +1.05 | 1.0 | `body .55` (lit `.82`); **wersaliki** |
| Nagłówek-przełącznik `.collapsed-h` | ZAPYTAŁEŚ | Text | 10.5 | `.medium` | +1.05 | 1.0 | `body .55`; **wersaliki** |
| Licznik szyny / filtr `.n` | „3" | **Mono** | 10.5 | `.regular` | 0 | — | nowe → `gold`; inaczej `body .5` |
| Wiersz — tytuł `.rrow .tt` | „Sprzeczność w czasie" | Text | 12.5 | **`.bold`** | 0 | 1.30 | `hi` (quiet: `.medium`, `body .78`) |
| Wiersz — skrót `.rrow .dd` | „Założenie o jakości przesunęło się w miesiąc." | Text | 11.5 | `.regular` | 0 | 1.40 | `body .55` |

## Rampa — Czytnik / karta (SF Pro Text)

| Styl | Próbka | Face | pt | Waga | kern | lhMult | Token |
|---|---|---|---|---|---|---|---|
| Eyebrow typu `.r-eyebrow` | SPRZECZNOŚĆ W CZASIE | Text | 10.5 | `.medium` | +1.05 | 1.0 | `gold #D6B033`; **wersaliki** |
| Znacznik „✦ do chmury" `.cloud-chip` | DIGEST 30.06 · Z CHMURY | Text | 10.5 | `.medium` | +1.05 | 1.0 | `cloud #E7B45C`; **wersaliki** |
| Znacznik „lokalnie" `.jade-chip` | LOKALNIE | Text | 10.5 | `.medium` | +1.05 | 1.0 | `jade-txt #8BE0B5`; **wersaliki** |
| Chip źródła `.nchip` | „Haetta — rozmowa z konstruktorem ↗" | Text | 11.5 | `.regular` | 0 | 1.0 | `body .8` |
| Eyebrow „Kierunki" | KIERUNKI | Text | 10.5 | `.medium` | +1.05 | 1.0 | `body .55`; **wersaliki** |
| Tekst kierunku `.dirrow` | „Co wymusiło zmianę założenia jakościowego…" | Text | 13 | `.regular` | 0 | 1.45 | `body .82` (on: `hi`) |

## Rampa — Wiersz wyniku (tryb Pytanie, SF Pro Text)

| Styl | Próbka | Face | pt | Waga | kern | lhMult | Token |
|---|---|---|---|---|---|---|---|
| Data `.res .dt` | „30.06" | **Mono** | 11.5 | `.regular` | +0.46 | 1.0 | `gold #D6B033` |
| Tytuł `.res .ti` | „okna-waskie-gardlo.md" | Text | 11.5 | **`.bold`** | 0 | 1.0 | `body .9` |
| „↗ otwórz" `.res .op` | „↗ otwórz" | Text | 11.5 | `.regular` | 0 | 1.0 | `body .45` → hover `terra-txt #E0633A` |
| Cytat `.res .qt` | „…okna jako wąskie gardło w dwóch notatkach…" | Text | 12.5 | `.regular` | 0 | 1.50 | `body .66` |
| `<mark>` w cytacie | „wąskie gardło" | Text | 12.5 | `.regular` | 0 | 1.50 | tekst `gold-glow #F4DD8E` · **tło** `rgba(214,176,51,.22)` (atrybut zakresu) |

> `<mark>` = **nie osobny font**, tylko atrybuty na zakresie w cytacie: `.foregroundColor`
> `#F4DD8E` + `.backgroundColor` `rgba(214,176,51,.22)`. Padding webowy `0 2px` → w AppKit
> pomijalny (albo `NSTextView` z `lineFragmentPadding`).

## Rampa — Chrome okna, stopka, przyciski (SF Pro Text)

| Styl | Próbka | Face | pt | Waga | kern | lhMult | Token |
|---|---|---|---|---|---|---|---|
| Tytuł okna `.win-title` | Timshel — **Konstelacja** | Text | 12.5 | `.regular` (nazwa `.bold`) | 0 | 1.0 | `body .75` (nazwa `hi`) |
| Etykieta przycisku `.btn` (ghost/syn) | „Odrzuć" / „Zsyntetyzuj" | Text | 12.5 | `.medium` | 0 | 1.0 | ghost `body .7`; syn `#F4DD8E` |
| Etykieta przycisku (jade/terra) | „Zachowaj" / „Zapisz do vaulta" | Text | 12.5 | **`.bold`** | 0 | 1.0 | jade `jade-txt`; terra biel `#FFFFFF` |
| Licznik stopki | „1 z 3" | **Mono** | 11 | `.regular` | 0 | 1.0 | `body .4` |
| Status handoffu `.handoff` | „2 kierunki wybrane" | Text | 12 | `.regular` | 0 | 1.0 | `body .6` |
| Tytuł stanu pustego | „Wszystko przejrzane" | Text (rola nagł.) | 16 | `.medium` | −0.19 | 1.2 | `hi` |
| Opis stanu pustego | „Nowe połączenia pojawią się z kolejnym digestem." | Text | 12 | `.regular` | 0 | 1.45 | `body .5` |

## Rampa — Overlay / ask-bar / menu / feedback (SF Pro Text)

| Styl | Próbka | Face | pt | Waga | kern | lhMult | Token |
|---|---|---|---|---|---|---|---|
| Pole ask-bara `.ask .q` | „Co z dostawą okien…" | Text | 15 | `.regular` | 0 | 1.0 | `hi #FAF3E2` |
| Placeholder ask-bara `.ph` | „Zapytaj swój korpus…" | Text | 15 | `.regular` | 0 | 1.0 | `body .4` |
| Pozycja menu `.mi` | „Utwórz zadanie" | Text | 13 | `.regular` | 0 | 1.0 | `hi` (hover: biel na terakocie) |
| Skrót menu `.mi .sc` | „⌘⇧K" | **Mono** | 11 | `.regular` | 0 | 1.0 | `body .4` (hover `rgba(255,255,255,.7)`) |
| Toast `.toastc` | „Zachowano" | Text | 12.5 | `.regular` | 0 | 1.0 | `hi` |
| Toast — Cofnij `.undo` | „Cofnij" | Text | 12.5 | **`.bold`** | 0 | 1.0 | `terra-txt #E0633A` |
| Ślad `.trace` | „Przekazano do Claude" | Text | 12 | `.regular` | 0 | 1.0 | `body .8` |
| Ślad — plik `.trace .f` | „okna-waskie-gardlo.md" | **Mono** | 11.5 | `.regular` | 0 | 1.0 | `jade-txt #8BE0B5` |
| Ślad — czas `.trace .t` | „14:32" | **Mono** | 11 | `.regular` | 0 | 1.0 | `body .4` |
| Notyfikacja — tytuł `.nt` | „3 nowe połączenia" | Text | 12.5 | **`.bold`** | 0 | 1.3 | `hi` |
| Notyfikacja — body `.nb` | „Digest z 42 notatek ostatnich dwóch dni." | Text | 12.5 | `.regular` | 0 | 1.4 | `body .65` |

## Rampa — Powierzchnie natywne (wizard / ustawienia, SF Pro Text na paper)

Kontrolki natywne → **niosą własną typografię systemową**; poniżej tylko dla parytetu.

| Styl | Próbka | Face | pt | Waga | Token |
|---|---|---|---|---|---|
| Przycisk natywny `.nbtn` | „Dalej" | Text | 13 | `.regular` (primary `.medium`) | `#1A1A1A` (primary biel) |
| Pole natywne `.nfield` | ścieżka vaulta | Text | 13 | `.regular` | `#1A1A1A` (placeholder `--ink-soft #6E6A64`) |
| Zakładka aktywna | „Prywatność" | Text | 13 | `.medium` | `terracotta` (tekst + tło `rgba(194,64,16,.1)`) |

---

## Fabryka atrybutów (do wklejenia)

```swift
extension NSAttributedString {
    /// Jeden styl rampy. `em` = tracking (patrz tabela kern), `mult` = lineHeightMultiple.
    static func ts(_ text: String, pt: CGFloat, weight: NSFont.Weight = .regular,
                   em: CGFloat = 0, mult: CGFloat = 1.0, color: NSColor,
                   upper: Bool = false, mono: Bool = false) -> NSAttributedString {
        let f = mono ? TS.mono(pt, weight) : TS.font(pt, weight)
        let p = NSMutableParagraphStyle(); p.lineHeightMultiple = mult
        let s = upper ? text.uppercased() : text
        return NSAttributedString(string: s, attributes: [
            .font: f, .foregroundColor: color, .paragraphStyle: p,
            .kern: em * pt                    // kern(pt) = em × pt
        ])
    }
}

// Teza:
let thesis = NSAttributedString.ts(text, pt: 24, weight: .medium,
                                   em: -0.012, mult: 1.30, color: TC.hi)
// Eyebrow typu (złoty, wersaliki):
let eyebrow = NSAttributedString.ts("Sprzeczność w czasie", pt: 10.5, weight: .medium,
                                    em: 0.10, color: TC.gold, upper: true)
// Data wyniku (mono, złota):
let date = NSAttributedString.ts("30.06", pt: 11.5, em: 0.04, color: TC.gold, mono: true)
```

`<mark>` na zakresie w cytacie:
```swift
let m = NSMutableAttributedString(attributedString: quote)   // .ts(..., pt:12.5, mult:1.5, color: body .66)
m.addAttributes([.foregroundColor: TC.goldGlow,
                 .backgroundColor: TC.hex(214,176,51, 0.22)], range: markRange)
```
