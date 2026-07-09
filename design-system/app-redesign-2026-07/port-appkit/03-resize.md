# 03 · Reguły resize

Okno **resizable**, min **740×460**, domyślnie **~62% ekranu**. Poniżej: co jest stałe, co
płynie, co zawija, co ucina.

---

## Okno

| Parametr | Wartość | AppKit |
|---|---|---|
| `styleMask` | resizable + title-bar transparentny | `[.titled, .closable, .miniaturizable, .resizable, .fullSizeContentView]` |
| Rozmiar min | **740 × 460 pt** | `window.contentMinSize = NSSize(width: 740, height: 460)` |
| Rozmiar domyślny | **~62% `visibleFrame`**, wyśrodkowany | patrz snippet niżej |
| Tło | radial statyczny w `contentView` | rysowany raz (`00 §4`) |

```swift
if let vf = NSScreen.main?.visibleFrame {
    let w = max(740, vf.width  * 0.62)
    let h = max(460, vf.height * 0.62)
    window.setFrame(NSRect(x: vf.midX - w/2, y: vf.midY - h/2, width: w, height: h),
                    display: true)
}
window.contentMinSize = NSSize(width: 740, height: 460)
```

---

## Szyna (rail) — **stała 236 pt**

**Nie ma collapse ani min/max.** Szerokość **236 pt** jest niezmienna (`_RAIL_W`,
`flex:none` w prototypie). „Zwijanie" w projekcie dotyczy **sekcji drugiego trybu**
(nagłówek-przełącznik), **nie** szerokości szyny.

- **Nie `NSSplitView`** z suwakiem — użytkownik nie zmienia szerokości szyny.
- Layout: leading `NSView` `width == 236` (constraint równościowy), reader wypełnia resztę.
- `border-right` = **device-hairline** (`05`).

```swift
rail.widthAnchor.constraint(equalToConstant: 236).isActive = true
rail.leadingAnchor.constraint(equalTo: content.leadingAnchor).isActive = true
reader.leadingAnchor.constraint(equalTo: rail.trailingAnchor).isActive = true
reader.trailingAnchor.constraint(equalTo: content.trailingAnchor).isActive = true
```

---

## Czytnik (reader) — płynny, treść lewo-wyrównana z capem

**Rozstrzygnięcie:** treść czytnika jest **lewo-wyrównana** i **nie centruje się**. Każdy
blok ma własny `max-width` (cap); nadmiar szerokości okna staje się **pustym prawym
marginesem**, nie rozjeżdża tekstu i nie centruje kolumny.

| Blok | Cap (max-width) | Zachowanie |
|---|---|---|
| Teza `.thesis` | **30em = 720 pt** (30 × 24 pt) | zawija swobodnie, **nigdy nie ucina**; przy oknie < capu bierze pełną dostępną szerokość |
| Pytanie-tytuł `.r-q` | ~720 pt | jw. |
| Kierunki `.dirrow` | **640 pt** | zawija swobodnie, **nigdy nie ucina** |
| Chipy źródeł `.nchip` | — | **zawijają** do nowej linii (flow); pojedynczy chip nie zawija (ucina tail, jeśli bardzo długi) |
| Wyniki `.res` | jak reader | patrz tabela wrap/truncate |

**Padding czytnika:** `leading/trailing` **24 pt** przy szerokości min → **32 pt** przy ≥
domyślnej (62%); `top` 20–26 pt. Prosty próg (dwustopniowy) wystarcza — nie interpolować.

**Cap = pt, nie „em okna":** `30em` liczone od rozmiaru **tezy** (24 pt), więc `720 pt`
stałe. Nie przeliczać od rozmiaru okna.

### Sanity — przy oknie min (740×460)
`740 − 236 (szyna) − 48 (padding 24×2) = 456 pt` na treść. Teza (cap 720) i kierunki
(cap 640) > 456 → **biorą pełne 456 pt i zawijają**. Cap uaktywnia się dopiero, gdy okno
urośnie: teza rośnie do 720 pt, potem prawy margines pustnieje.

---

## Co zawija, co ucina

| Element | Zachowanie | AppKit |
|---|---|---|
| Wiersz szyny — tytuł `.tt` | **2 linie → tail** | `lineBreakMode = .byTruncatingTail`, `maximumNumberOfLines = 2` |
| Wiersz szyny — skrót `.dd` | **1 linia → tail** | `.byTruncatingTail`, `maxLines = 1` |
| Teza / pytanie-tytuł | **zawija swobodnie**, cap 720 pt, brak truncate | `.byWordWrapping`, `maxLines = 0` |
| Kierunek `.dirrow` | **zawija swobodnie**, cap 640 pt, brak truncate | `.byWordWrapping`, `maxLines = 0` |
| Chipy źródeł (zbiór) | **zawijają** (flow); każdy chip nowrap → tail | `NSStackView`/flow-layout + chip `.byTruncatingTail` |
| Wynik — tytuł `.ti` | **tail** | `.byTruncatingTail`, `maxLines = 1` |
| Wynik — „↗ otwórz" `.op` | **przypięte prawo, nigdy nie ucina** | trailing, `hugging` wysoki |
| Wynik — cytat `.qt` | **≤ 3 linie → tail** | `.byTruncatingTail`, `maxLines = 3` |

---

## Stopka triażu i pasek handoffu (dolne belki)

| Belka | Wys. | Szer. | Zachowanie na resize |
|---|---|---|---|
| Stopka triażu `.wfooter` (**tylko Przegląd**) | **46 pt** | pełna | Odrzuć (leading) · „1 z 3" (**środek absolutny**) · Zachowaj (trailing); środek zostaje centrowany niezależnie od szerokości przycisków |
| Pasek handoffu `.handoff` (≥1 kierunek) | **48 pt** | pełna | status + „✦ do chmury" (leading, **ucina tail** przy wąskim) · klaster **⋯ + split-CTA** (trailing, **nigdy nie ucina**) |

**Stackowanie (jedyne miejsce, gdzie dwie belki współistnieją):** w **Przeglądzie** z ≥1
zaznaczonym kierunkiem pasek handoffu siada **bezpośrednio nad** stopką triażu (48 nad 46).
W **Pytaniu** stopki triażu **nie ma** (`08`), więc handoff siada nad dolną krawędzią
czytnika. Obie belki pełnej szerokości, wysokości stałe; reader oddaje im wysokość
(kurczy się), a nie jest przez nie zasłaniany.

```
Przegląd + zaznaczony kierunek:   [ reader ... ]
                                  [ handoff 48 ]
                                  [ footer  46 ]
```

Środek stopki (constraint do `centerX` **okna**, nie do przestrzeni między przyciskami):
```swift
counter.centerXAnchor.constraint(equalTo: footer.centerXAnchor).isActive = true
```
