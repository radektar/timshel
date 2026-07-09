# 05 · Hairline'y — device-px vs logical pt

Prototyp używa borderów `0.5 / 1 / 1.5 / 2.5 px`. Nie wszystkie znaczą to samo w AppKit.

---

## Zasada

**Hairline = 1 fizyczny piksel urządzenia.** Na Retinie @2x → **0.5 pt**; @1x → **1 pt**:
`hairline = 1.0 / backingScaleFactor`.

Rozstrzygnięcie, co czym jest (wg **intencji**, nie samej wartości px):

- **Separator strukturalny** (ledwie widoczny podział między wierszami/sekcjami, `rgba`
  bieli `.06–.10`) → **prawdziwy device-hairline** (`1/scale`). W CSS to `1px`, bo
  przeglądarka nie renderuje pewnie `0.5px`; intencja to hairline.
- **Krawędź kontrolki** (obrys definiujący klikalny element: chip, przycisk, wiersz
  kierunku, ramka menu/ask/toast) → **logical 1 pt** (stała, ma być wyraźna, nie znikać
  na @1x).
- **Celowy wskaźnik** (pasek aktywnego wiersza 2.5, border checkboxa 1.5) → **logical pt**
  w podanej wartości.

---

## Tabela

| Border (element) | CSS | Klasa | Szer. AppKit | Uwaga |
|---|---|---|---|---|
| `border-right` szyny `rgba(255,255,255,.06)` | 1px | **device-hairline** | `1/scale` (0.5 pt @2x) | separator strukturalny |
| `border-bottom` title-bara `.07` | 1px | **device-hairline** | `1/scale` | — |
| `border-bottom` wiersza wyniku `.res` `.07` | 1px | **device-hairline** | `1/scale` | znika w hoverze (`border-bottom-color: transparent`) |
| `border-top` stopki `.08` / handoffu `.08` | 1px | **device-hairline** | `1/scale` | — |
| separator menu `.msep` `.10` | 1px | **device-hairline** | `1/scale` | — |
| border chipa źródła `.nchip` `.14` | 1px | **logical** | **1 pt** | krawędź kontrolki |
| border przycisku (ghost/syn/jade) | 1px | **logical** | **1 pt** | krawędź kontrolki |
| border wiersza kierunku `.dirrow` `.10 / .55` | 1px | **logical** | **1 pt** | krawędź kontrolki |
| ramka menu / ask-bar / toast / popover | 1px | **logical** | **1 pt** | ramka pływająca |
| divider split-CTA `rgba(255,255,255,.25)` | 1px | **logical** | **1 pt** | rozdziela główny / caret |
| **border checkboxa `.cbx`** | **1.5px** | **logical** | **1.5 pt** | + strzałki ✓ **1.8 pt**; align do 1. linii `+2 pt` |
| **pasek aktywnego wiersza `.rrow.active::before`** | **2.5px** | **logical** | **2.5 pt** | `r2`, inset top/bottom **8 pt**; **złoto `#D6B033`** (insight) / **terakota `#D9542A`** (zapytanie) |

---

## Realizacja

```swift
extension NSView {
    var hairline: CGFloat { 1.0 / (window?.backingScaleFactor ?? 2.0) }
}

// Reaguj na zmianę ekranu (przeciągnięcie okna Retina ⇄ @1x):
override func viewDidChangeBackingProperties() {
    super.viewDidChangeBackingProperties()
    layer?.contentsScale = window?.backingScaleFactor ?? 2
    updateSeparators()                         // przelicz szerokości hairline'ów
}
```

**Ostrość — dwie zasady:**

1. **Separatory rysuj jako 1-device-px prostokąt** (`CALayer`/box o wysokości `1/scale`),
   nie jako `borderWidth` na dużej warstwie — `borderWidth` sub-punktowy potrafi się
   rozmyć (anty-aliasing na krawędzi). Wyrównaj `frame` do siatki pikseli:
   `backingAlignedRect(_:options: .alignAllEdgesNearest)`.
2. **Logical bordery (1/1.5/2.5 pt)** → `layer.borderWidth` w punktach jest OK; ustaw
   `layer.contentsScale = backingScaleFactor`, by krawędź była ostra na Retinie.

```swift
// separator strukturalny (device-hairline):
let sep = CALayer()
sep.backgroundColor = TC.hex(255,255,255, 0.06).cgColor
sep.frame = backingAlignedRect(
    NSRect(x: bounds.maxX - hairline, y: 0, width: hairline, height: bounds.height),
    options: .alignAllEdgesNearest)

// pasek aktywnego wiersza (logical 2.5 pt, złoto = insight / terakota = zapytanie):
bar.frame = NSRect(x: 0, y: 8, width: 2.5, height: bounds.height - 16)
bar.cornerRadius = 2
bar.backgroundColor = (row.kind == .insight ? TC.gold : TC.terraLit).cgColor
```
