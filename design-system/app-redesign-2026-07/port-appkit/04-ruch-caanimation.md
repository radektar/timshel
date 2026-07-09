# 04 · Ruch → CAAnimation

Prototypy są statyczne; poniższe `from→to`, czasy i easingi **formalizują** ruch, który
handoff opisuje słownie (README §5: „wsuwanie 150–180 ms"; §8: „flash 180 ms", „toast 2 s").

**Właściwości ruchu: tylko `opacity` + `transform.translation.y`** (ograniczenie
odwzorowalności — `00`). Żadnych animowanych gradientów, blurów, ścieżek.

---

## Krzywe (CAMediaTimingFunction)

| Nazwa | Punkty | Użycie |
|---|---|---|
| **standard** | `0.4, 0, 0.2, 1` | odsłonięcia, karta syntezy, wymiana chrome (krzywa `--transition` z tokens.css) |
| **decelerate** (ease-out) | `0.0, 0, 0.2, 1` | wejście toastu, flash-ring |
| **accelerate** (ease-in) | `0.4, 0, 1.0, 1` | wyjście toastu, ukrycie paska |

```swift
enum Ease {
    static let standard   = CAMediaTimingFunction(controlPoints: 0.4, 0, 0.2, 1)
    static let decelerate = CAMediaTimingFunction(controlPoints: 0,   0, 0.2, 1)
    static let accelerate = CAMediaTimingFunction(controlPoints: 0.4, 0, 1,   1)
}
```

> **Znak `translation.y`:** poniżej „+Y = w dół ekranu". Warstwy na `NSView` mają często
> `isGeometryFlipped` — ustal raz kierunek i trzymaj się go (jeśli oś odwrócona, zamień
> znak). „Wsuwa z dołu" = start z **dodatnim** offsetem, dojazd do 0.

---

## Tabela animacji

| Animacja | Trigger | Właściwość (from → to) | Czas | Easing | `reduce-motion` |
|---|---|---|---|---|---|
| **Odsłonięcie paska handoffu** | ≥1 kierunek zaznaczony | `opacity 0→1` **+** `ty +10→0` | **150 ms** | standard | `opacity` natychmiast, **bez** translate |
| **Ukrycie paska handoffu** | 0 kierunków | `opacity 1→0` **+** `ty 0→+10` | 120 ms | accelerate | znika natychmiast |
| **Wsuwanie karty syntezy** (D2) | „Zsyntetyzuj" → streaming | `opacity 0→1` **+** `ty +16→0` | **180 ms** | standard | natychmiast; wyniki poniżej reflow bez animacji |
| **Flash-ring `btn-jade`** | klik „Zachowaj" | ring `borderWidth 4pt` `rgba(70,177,126,.22)` `opacity 1→0` **+** bg `.16→.30→.16` | **180 ms** | decelerate | **bez ringu** — „Zachowano ✓" + kolor natychmiast, toast się pojawia |
| **Toast — wejście** | skutek lokalny/odwracalny | `opacity 0→1` **+** `ty +8→0` | 150 ms | decelerate | `opacity` natychmiast |
| **Toast — wyjście** | 2 s / `Esc` / nowy toast | `opacity 1→0` **+** `ty 0→+4` | 150 ms | accelerate | znika natychmiast |
| **Wymiana chrome (tryb)** | klik zwiniętego nagłówka / `Esc` | crossfade: wychodzące `opacity 1→0` (120 ms) → wchodzące `opacity 0→1` **+** `ty +4→0` (150 ms) | 120 + 150 ms | standard | **natychmiastowa podmiana** (bez fade i translate) |
| **„otwarto ✓" na wierszu wyniku** (B2) | klik wiersza | podmiana tekstu/koloru (bez ruchu), auto-powrót po **2 s** | — | — | identycznie (to nie-ruch) |
| **Ikona paska menu** (nagrywam / indeksuję) | zmiana stanu | podmiana koloru/opacity (**bez animacji** — F3: „ikona nie teatralizuje") | — | — | identycznie |

**Toast:** widoczny **2 s**; **hover pauzuje** zegar; jeden naraz (nowy zastępuje stary);
wyśrodkowany **10 pt** nad stopką (`03`).

---

## `prefers-reduced-motion` — potwierdzenie

**Tak — „cięcie" = natychmiastowa `opacity`, bez translate.** Przy włączonym
Reduce Motion **każda** animacja wsuwania staje się natychmiastowym pojawieniem stanu
końcowego (`duration = 0`), a **offset `ty` jest pomijany** (element od razu na docelowej
pozycji). Flash-ring → sama podmiana etykiety/koloru (bez rozbłysku). Źródło stanu:
`NSWorkspace.shared.accessibilityDisplayShouldReduceMotion`.

---

## Szablon (do wklejenia)

```swift
func slideIn(_ layer: CALayer, dy: CGFloat, dur: CFTimeInterval,
             timing: CAMediaTimingFunction) {
    if NSWorkspace.shared.accessibilityDisplayShouldReduceMotion {
        layer.opacity = 1                       // cięcie — stan końcowy, bez ruchu
        return
    }
    let o = CABasicAnimation(keyPath: "opacity")
    o.fromValue = 0; o.toValue = 1
    let t = CABasicAnimation(keyPath: "transform.translation.y")
    t.fromValue = dy; t.toValue = 0
    let g = CAAnimationGroup()
    g.animations = [o, t]; g.duration = dur; g.timingFunction = timing
    g.fillMode = .backwards
    layer.add(g, forKey: "slideIn")
    layer.opacity = 1                            // model = stan końcowy
}

// Pasek handoffu:  slideIn(bar.layer!,  dy: 10, dur: 0.15, timing: Ease.standard)
// Karta syntezy:   slideIn(card.layer!, dy: 16, dur: 0.18, timing: Ease.standard)
// Toast (wejście): slideIn(toast.layer!, dy: 8,  dur: 0.15, timing: Ease.decelerate)
```

Flash-ring:
```swift
func flashRing(_ btn: CALayer) {
    if NSWorkspace.shared.accessibilityDisplayShouldReduceMotion { return }  // sam swap etykiety
    let ring = CALayer()
    ring.frame = btn.bounds
    ring.cornerRadius = btn.cornerRadius
    ring.borderWidth = 4
    ring.borderColor = TC.hex(70,177,126, 0.22).cgColor
    btn.addSublayer(ring)
    let fade = CABasicAnimation(keyPath: "opacity")
    fade.fromValue = 1; fade.toValue = 0
    fade.duration = 0.18; fade.timingFunction = Ease.decelerate
    fade.isRemovedOnCompletion = false; fade.fillMode = .forwards
    CATransaction.setCompletionBlock { ring.removeFromSuperlayer() }
    CATransaction.begin(); ring.add(fade, forKey: nil); CATransaction.commit()
}
```
