# 02 · Inwentarz komponentów — custom vs natywny  **[BLOKER]**

Dla każdego komponentu: **layer-backed `NSView` rysowany ręcznie** czy **natywna kontrolka
AppKit** (i która) + tint. Kontrolka natywna niesie **własny padding / baseline /
focus-ring** — kolumna „Gotcha" mówi, co z tym zrobić.

---

## Reguła rozstrzygająca

- **Natywne**, gdy element niesie standardową semantykę, którą drogo odtworzyć: edycję
  tekstu (IME, kursor, zaznaczenie), menu (nawigacja klawiaturą, dismiss, pozycjonowanie),
  role dostępności, notyfikacje systemowe, całą ramę wizard/ustawień.
- **Custom (layer-backed `NSView`)**, gdy liczy się **dokładny paint**, którego natywne
  bezle nie trafią: konkretne `rgba` tła/borderu, `radius 6`, pressed `translateY +1pt`,
  niestandardowy highlight (terakota, nie systemowy niebieski), wyrównanie do pierwszej
  linii.
- **Hybryda** (częsta i preferowana): **natywny szkielet** (semantyka, klawiatura) +
  **custom paint** w `updateLayer()` / view-based item. Tak robimy przyciski i menu.

---

## Powierzchnia okna „Konstelacja" (dark)

| Komponent | Custom / Natywny | Klasa AppKit | Tint / rysowanie | Gotcha (padding · baseline · focus-ring) |
|---|---|---|---|---|
| **Przycisk** jade/ghost/syn/terra `.btn` | **Hybryda** | `NSButton` subklasa, `isBordered=false`, `wantsLayer=true` | bg / border / etykieta w `updateLayer()`; `radius 6`; pressed `translateY +1pt` (patrz `04`) | natywny bezel niesie własny padding **i** focus-ring — wyłącz (`isBordered=false`), rysuj **własny ring 3 pt** (`05`); zostaw `keyEquivalent` + aktywację spacją |
| **Checkbox** `.cbx` | **Custom** | `NSButton` `.switch` subklasa (semantyka AX) | 16 pt kwadrat `r4`, border **1.5 pt**, `on` → fill `terra` + biały ✓ (rysowany path) | natywny checkbox = **zły kolor** (systemowy akcent) + centrowanie do środka wiersza; my wyrównujemy do **pierwszej linii** tekstu (`+2 pt`), więc rysujemy sami |
| **Filtr „Nowe 3 ⌄"** (A3) | **Hybryda** | trigger `NSView`/`NSButton` + **`NSMenu`** | trigger: etykieta + złoty licznik + caret, hover wash; `menu.popUp(positioning:at:in:)` | highlight `NSMenu` = **systemowy akcent (niebieski)**; terakota wymaga **view-based item** (patrz niżej) |
| **Menu / popover** `.menu` | **Natywne + custom item-view** | `NSMenu` | pozycje jako `NSView` (terakotowy highlight + mono skrót) | tło `NSMenu` = **systemowy materiał vibrancy**; exact `rgba(38,36,44,.97)` → albo zaakceptuj materiał (dark), albo host menu w `NSPanel`; skróty w mono jako druga kolumna item-view |
| **Status-menu** paska menu (F2, pasek postępu) | **Natywne + custom header** | `NSMenu` + pierwszy item = `NSView` | custom widok statusu u góry (sygnet + pasek postępu = `CALayer`) | maks. **7 pozycji**; pasek postępu rysowany sam, nie `NSProgressIndicator` (styl) |
| **Ask-bar** `.ask` (C) | **Custom panel + natywne pole** | `NSPanel(.nonactivating, .borderless)` + `NSTextField` (borderless) | panel `r10`, dark, **ring focus 3 pt** terakota; pole tintowane, placeholder attributed; mic = custom `NSView` | `NSTextField` niesie własny baseline/inset — wycentruj w polu **52 pt**; **ring rysuj na kontenerze**, nie natywny focus-ring pola (`focusRingType = .none`); mic żyje **tylko tu** |
| **Split-CTA „Kontynuuj w Claude ▾"** (E3) | **Custom** | 2× `NSButton` (główny + caret) w layer-backed kontenerze + **`NSMenu`** | terakota; divider **1 pt** `rgba(255,255,255,.25)`; `radius 6` tylko rogi zewnętrzne; marka = template-image tint biały | wzorzec split-button **nie jest natywny** na macOS; główny = akcja, caret = `NSMenu` (Claude/ChatGPT); wybór zapamiętany globalnie (`08`, H1) |
| **Chip źródła** `.nchip` | **Custom** | `NSButton` subklasa | 26 pt, `r6`, border `rgba(255,255,255,.14)`, kropka 5 pt terakota, „↗" | klik = otwórz w appce; hover border → `terra-lit` |
| **Wiersz wyniku** `.res` (B) | **Custom w liście natywnej** | `NSTableView` / `NSCollectionView` + custom `NSTableCellView` | cały wiersz = **jeden** target „otwórz źródło"; hover: padding `13×2`→`13×10` + wash; „otwarto ✓" 2 s | **wyłącz systemową selekcję** (`selectionHighlightStyle = .none`) — rysuj własny hover/press; data = mono run; `<mark>` = atrybut zakresu (`01`) |
| **Wiersz kierunku** `.dirrow` (E) | **Custom** | `NSView` + custom checkbox + `NSTextField` (wrap) | `r10`, padding `11×12`; `on` → tint `rgba(217,84,42,.09)` + border `.55` | **cały wiersz** klikalny (toggle, nie tylko checkbox); tekst **zawija**, nie truncate (`03`) |
| **Trwały ślad** `.trace` (D4/E4/I2) | **Custom** | `NSButton` subklasa | `r8`; wariant jadeit / złoto; plik = mono | klikalny; **trwały** — źródłem jest model, nie widok (przeżywa zamknięcie okna) |
| **Toast** `.toastc` (I) | **Custom** | `NSView` (child `contentView`) nad stopką | `r8`, bg `#24222C`, border 1 pt; Cofnij = `NSButton` subklasa | **NIE `NSPanel`** — żyje w oknie, **10 pt** nad stopką; timer 2 s, hover pauzuje, `Esc` zamyka; jeden naraz (nowy zastępuje) |
| **Title-bar** | **Natywne** | `NSWindow` (`titlebarAppearsTransparent=true`) + `NSTitlebarAccessoryViewController` | światła = **systemowe (NIE rysuj)**; tytuł wyśrodkowany = accessory/toolbar; **⌕ = prawy accessory** (custom `NSButton`) | tło okna (radial) to `contentView` **pod** transparentnym title-barem; okno dark → `appearance = NSAppearance(named:.darkAqua)` lub własne tło; wys. ~40 pt = standard title-bar |

## Powierzchnie natywne (wizard / ustawienia — light, `.nativewin`)

Rama **natywna z tokenami**. Spójność niesie **akcent + typografia + radius + głos**, nie
kolor tła. Native focus-ring / baseline **zostają** — to natywna powierzchnia, nie tłumimy.

| Komponent | 100% stock czy tint | Klasa | Uwaga |
|---|---|---|---|
| Okno prefs / wizard | stock | `NSWindow` (styl preferencji) | tło systemowe jasne ≈ `#F5F3EF`; titlebar `#ECEAE4` |
| Przycisk wtórny `.nbtn` | **stock** | `NSButton` (push) | native bezel, `radius 6` systemowy |
| Przycisk primary | **tint** | `NSButton` | `bezelColor = terracotta` (nie systemowy niebieski); „Dalej" / „Zacznij" |
| Pole `.nfield` | **stock** | `NSTextField` | native focus-ring OK (30 pt wys.) |
| Radio (opener: Obsidian/Pile/Finder) | **stock** | `NSButton` `.radio` (grupa) | — |
| Model / narzędzie / rytm | **stock** | `NSPopUpButton` | — |
| Zakładki Ogólne · Vault · Prywatność | **tint (jedyny custom w ramie)** | lekki custom pasek **lub** `NSSegmentedControl` tintowany | aktywna: tekst terakota + tło `rgba(194,64,16,.1)` (`08`, H) |
| Bloki Prywatności (jadeit / złoto) | tint | `NSBox` / `NSView` | „Zawsze lokalnie" jadeit · „✦ Do chmury" złoto |

## Powierzchnie systemowe

| Komponent | Natywne | Klasa | Uwaga |
|---|---|---|---|
| **Pasek menu** (F) | natywne | `NSStatusItem` + `NSMenu` | ikona = **monochromatyczny sygnet** template-image (tint systemowy); stany: spoczynek · nagrywam (kropka `#E0633A`) · indeksuję (sygnet 55%); **status indeksowania żyje tylko tu**; ikona **bez animacji** (F3) |
| **Notyfikacja systemowa** (I3) | natywne | `UNUserNotificationCenter` (`UNNotificationRequest`) | **nie** custom `NSView` — systemowa; ikona apki = sygnet mesh na `#141414`; klik → deep-link (`userInfo` → tryb/okno); dwa rodzaje: digest gotowy, indeks gotowy |
| Dialogi | natywne | `NSAlert` | tylko klasyczne dialogi; **błąd syntezy NIE `NSAlert`** — komunikat w miejscu karty (`08`, I4) |

---

## Dwie polityki przekrojowe

### Focus-ring (na powierzchni okna)
Na ciemnym oknie **tłumimy** natywny focus-ring (`view.focusRingType = .none`) i rysujemy
**własny ring 3 pt** w kolorze terakotowym — spójny z fokusem ask-bara
(`box-shadow 0 0 0 3px rgba(217,84,42,.18)` + border `rgba(217,84,42,.65)`). To jest jedyny
język fokusa w oknie. Na **powierzchniach natywnych** (wizard/ustawienia) — **odwrotnie**:
zostaw natywny focus-ring (spójność z systemem).

```swift
// custom ring na przycisku/polu w oknie (dark):
func drawFocusRing(in layer: CALayer) {
    let ring = CALayer()
    ring.frame = layer.bounds.insetBy(dx: -3, dy: -3)
    ring.cornerRadius = layer.cornerRadius + 3
    ring.borderWidth = 3
    ring.borderColor = TC.hex(217,84,42, 0.18).cgColor   // rgba(217,84,42,.18)
    layer.addSublayer(ring)
    layer.borderColor = TC.hex(217,84,42, 0.65).cgColor
}
```

### Highlight w `NSMenu` (gotcha)
Domyślny highlight `NSMenu` to **systemowy akcent (niebieski)**. Spec chce **terakoty**
(`#C24010`, biały tekst). Rozwiązanie: **view-based menu items** — każdemu `NSMenuItem`
ustaw `.view = <custom NSView>`, który sam maluje tło terakotowe w stanie `highlighted`
(obserwuj `enclosingMenuItem?.isHighlighted`). To samo daje mono kolumnę skrótu i glif
marki. Bez view-based items highlight zostanie systemowy — **nie do zaakceptowania** dla
menu switchera / filtra (naruszałoby rolę akcentu).

### „Layer-backed" = zawsze `wantsLayer = true`
Każdy custom komponent: `wantsLayer = true`, paint w `updateLayer()` (nie `draw(_:)` gdzie
się da — tańsze), `layer.contentsScale = window.backingScaleFactor` (ostrość, `05`).
