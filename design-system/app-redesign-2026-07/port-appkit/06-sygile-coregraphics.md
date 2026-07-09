# 06 · Geometria sygili → Core Graphics (`_SigilView.drawRect_`)

**`redesign-sigils.js` JEST źródłem prawdy kształtu.** Port do `_SigilView.drawRect_` (Core
Graphics) musi trafić te współrzędne **1:1**. HTML/SVG to spec kształtu, nie docelowy
renderer. Wszystko w przestrzeni **`viewBox 0 0 32 32`**; skaluj przez `scale = size/32`
(`ctx.scaleBy(x: s, y: s)`).

Kolor to `#D9542A` domyślnie; **per typ** barwi **tylko łuki/linie i glow węzła**. Rdzeń i
środek węzła oraz cały „bloom" (rozbłysk) są **stałe** niezależnie od typu.

---

## Węzeł (identyczny we wszystkich typach)

3 nałożone koła w punkcie `(x, y)`:

| Warstwa | Promień | Wypełnienie |
|---|---|---|
| glow | **7** | radial (patrz niżej), kolor = kolor typu |
| rdzeń | **2.5** | `#C24010` (**stały**) |
| środek | **1** | `#FAF3E2` (**stały**) |

**Radial glow węzła** (start w środku, `r = 7`):

| offset | kolor | alpha |
|---|---|---|
| 0.00 | kolor typu | 0.50 |
| 0.60 | kolor typu | 0.08 |
| 1.00 | kolor typu | 0.00 |

## Bloom / rozbłysk (złoty — stały we wszystkich typach)

Parametr `r0` (bazowy promień rozbłysku). 3 warstwy w `(x, y)`:

| Warstwa | Promień | Wypełnienie |
|---|---|---|
| glow | `r0 × 2.6` | radial złoty (niżej) |
| dysk | `r0` | `#F4DD8E` |
| iskra | `r0 × 0.4` | `#FFFBF0` |

**Radial glow bloomu** (start w środku, `r = r0 × 2.6`):

| offset | kolor | alpha |
|---|---|---|
| 0.00 | `#F4DD8E` | 0.90 |
| 0.55 | `#D6B033` | 0.30 |
| 1.00 | `#D6B033` | 0.00 |

---

## Typy — współrzędne, łuki, kolejność rysowania

### `contradiction` — napięcie / opozycja · kolor **`#D9542A`**
2 węzły, 2 rozchodzące się łuki wokół spornego punktu.

| Element | Geometria | Stroke |
|---|---|---|
| linia bazowa (kreskowana) | `(5,16) → (27,16)` | kolor α **.28**, w **1**, dash **[2, 4]** |
| łuk górny | quad `M 8,16  Q 16,7  24,16` | kolor α **.85**, w **1.5**, cap round |
| łuk dolny | quad `M 8,16  Q 16,25 24,16` | kolor α **.85**, w **1.5**, cap round |
| bloom | `(16, 16)`, `r0 = 2.4` | — |
| węzły | `(8, 16)`, `(24, 16)` | — |

**Kolejność (z-order):** linia bazowa → łuki → bloom → **węzły na wierzchu**.

### `shared` (thread) — spotkanie / wspólny wątek · kolor **`#D6B033`**
2 węzły zbiegają się ku rozbłyskowi u góry.

| Element | Geometria | Stroke |
|---|---|---|
| linia lewa | `(9,24) → (16,9)` | kolor α **.7**, w **1.4**, cap round |
| linia prawa | `(23,24) → (16,9)` | kolor α **.7**, w **1.4**, cap round |
| węzły | `(9, 24)`, `(23, 24)` | — |
| bloom | `(16, 9)`, `r0 = 3` | — |

**Kolejność:** linie → węzły → **bloom na wierzchu** (u góry, w punkcie zbiegu).

### `emergent` (triad) — pomysł z wielu źródeł · kolor **`#E3C16B`**
Centralny rozbłysk rozgałęzia się do 3 węzłów.

| Element | Geometria | Stroke |
|---|---|---|
| 3 linie | z `(16,16)` do `(8,9)`, `(25,12)`, `(15,26)` | kolor α **.55**, w **1.3**, cap round |
| węzły | `(8, 9)`, `(25, 12)`, `(15, 26)` | — |
| bloom | `(16, 16)`, `r0 = 3` | — |

**Kolejność:** linie → węzły → **bloom na wierzchu** (centrum).

---

## Rozmiary w użyciu

| Kontekst | Rozmiar |
|---|---|
| szyna (`.rrow .ic`) | **18–26 pt** |
| eyebrow czytnika | **24–30 pt** |
| stan pusty | **34–46 pt** |

> Sygnet aplikacji (`--logo-sygnet`, fala / pasek menu) to **osobny** motyw — **nie** sygil
> połączenia. Nie mylić (`07`).

---

## Szkic `drawRect_` (Core Graphics)

```swift
final class SigilView: NSView {
    enum Kind { case contradiction, shared, emergent }
    var kind: Kind = .contradiction
    override var wantsUpdateLayer: Bool { false }

    override func draw(_ dirty: NSRect) {
        guard let ctx = NSGraphicsContext.current?.cgContext else { return }
        let s = bounds.width / 32
        ctx.saveGState(); ctx.scaleBy(x: s, y: s)     // przestrzeń 32×32

        switch kind {
        case .contradiction:
            let c = TC.terraLit                        // #D9542A
            dashed(ctx, from: CGPoint(x: 5, y: 16), to: CGPoint(x: 27, y: 16),
                   color: c, alpha: 0.28, w: 1, dash: [2, 4])
            arc(ctx, m: CGPoint(x: 8, y: 16), q: CGPoint(x: 16, y: 7),  end: CGPoint(x: 24, y: 16), color: c, alpha: 0.85, w: 1.5)
            arc(ctx, m: CGPoint(x: 8, y: 16), q: CGPoint(x: 16, y: 25), end: CGPoint(x: 24, y: 16), color: c, alpha: 0.85, w: 1.5)
            bloom(ctx, at: CGPoint(x: 16, y: 16), r0: 2.4)
            node(ctx, at: CGPoint(x: 8, y: 16), glow: c); node(ctx, at: CGPoint(x: 24, y: 16), glow: c)
        case .shared:
            let c = TC.gold                            // #D6B033
            line(ctx, from: CGPoint(x: 9, y: 24),  to: CGPoint(x: 16, y: 9), color: c, alpha: 0.7, w: 1.4)
            line(ctx, from: CGPoint(x: 23, y: 24), to: CGPoint(x: 16, y: 9), color: c, alpha: 0.7, w: 1.4)
            node(ctx, at: CGPoint(x: 9, y: 24), glow: c); node(ctx, at: CGPoint(x: 23, y: 24), glow: c)
            bloom(ctx, at: CGPoint(x: 16, y: 9), r0: 3)
        case .emergent:
            let c = TC.hex(227,193,107)                // #E3C16B
            let nd = [CGPoint(x: 8, y: 9), CGPoint(x: 25, y: 12), CGPoint(x: 15, y: 26)]
            for p in nd { line(ctx, from: CGPoint(x: 16, y: 16), to: p, color: c, alpha: 0.55, w: 1.3) }
            for p in nd { node(ctx, at: p, glow: c) }
            bloom(ctx, at: CGPoint(x: 16, y: 16), r0: 3)
        }
        ctx.restoreGState()
    }
}
```

Pomocnicze: `line/arc/dashed` → `setLineCap(.round)`, `setLineDash(phase:0, lengths:[2,4])`
dla bazowej; łuk = `addQuadCurve(to:control:)`. `node` = radial glow (`drawRadialGradient`,
`startRadius 0`, `endRadius 7`, locations `[0, .6, 1]`, alpha `[.5, .08, 0]`) + koło `r2.5`
`#C24010` + koło `r1` `#FAF3E2`. `bloom` = radial złoty (`endRadius r0×2.6`, locations
`[0, .55, 1]`, kolory `#F4DD8E@.9 / #D6B033@.3 / #D6B033@0`) + `r0` `#F4DD8E` + `r0×0.4`
`#FFFBF0`. Gradient statyczny — liczony raz (`00`).
