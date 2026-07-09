# Port AppKit — spec render 1:1 (warstwa 3b)

**Timshel / „Konstelacja" — redesign 2026-07 → natywny macOS (AppKit, PyObjC).**

Ta paczka **nie przeprojektowuje** niczego. Handoff (`README.md` + ekrany A–I +
`redesign-spec.css` + `tokens.css`) jest kompletny w warstwie **layoutu / tokenów /
stanów**. Poniższe dokumenty **formalizują to, co HTML pod-specyfikuje** dla renderu
1:1 w AppKit — w formie, którą implementer wkleja do kodu (Swift / PyObjC).

Źródłem prawdy pozostają `tokens.css` (kolory/typografia/radius) i `redesign-spec.css`
(metryki komponentów). Gdzie te dokumenty podają liczbę, którą HTML zostawiał domyślną
(kern w pt, easing, dystans wsuwania, klasa hairline'a, mapowanie wag), **wygrywa ten
dokument** — to jego zadanie.

---

## Ograniczenie odwzorowalności (wiążące — nie gubić w porcie)

Każdy element składa się **wyłącznie** z tego, co AppKit robi tanio:

- `layer` — `backgroundColor` / `borderColor`+`borderWidth` / `cornerRadius` / `shadow`
- `template-image` tintowany (`contentTintColor`)
- prosty **wash-overlay** (półprzezroczysta warstwa nad tłem)
- zmiana koloru tekstu / atrybutu zakresu

**Bez animowanych gradientów, bez efektów web-only.** Radialny gradient tła okna i glow
sygili są **statyczne** (rysowane raz). Ruch = `opacity` + `transform.translation.y`
(patrz `04`).

---

## Konwencje wspólne (obowiązują we wszystkich dokumentach)

### 1. Piksel redline = punkt @1x (1:1)
Prototypy renderowane w CSS px (jednostka device-independent). **W AppKit `px` z redline
czytamy jako `pt` 1:1** — teza `24 px` → `24 pt`, szyna `236 px` → `236 pt`. Retina @2x
skaluje automatycznie (1 pt = 2 device px); nie przeliczamy ręcznie poza hairline'ami
(patrz `05`).

### 2. Wagi: 400 / 500 / 700 → `.regular` / `.medium` / `.bold`
Design używa **tylko trzech** wag. Rozstrzygnięcie: **`500` = `NSFont.Weight.medium`**
(nie `.semibold`). `600 / .semibold` **nie występuje** w projekcie — nie wprowadzać go
„dla wagi". `700` = `.bold`, `400` = `.regular`.

### 3. Fonty → systemowe SF
| Web | AppKit | API |
|---|---|---|
| Neue Montreal (display) | **SF Pro** (optyk Display) | `NSFont.systemFont(ofSize:weight:)` — auto Display **≥ 20 pt** |
| Neue Haas Grotesk (body/UI) | **SF Pro Text** (optyk Text) | `NSFont.systemFont(ofSize:weight:)` — auto Text **< 20 pt** |
| mono | **SF Mono** | `NSFont.monospacedSystemFont(ofSize:weight:)` |

`NSFont.systemFont` **sam** przełącza optyk Display/Text na progu **20 pt** — a to jest
dokładnie nasz próg. Kolumna „Face" w `01` dokumentuje wynik tego przełącznika, nie ręczny
override. Diakrytyki PL (ą ć ę ł ń ó ś ź ż) — pełne we wszystkich wagach SF.

### 4. Kolory powierzchni okna (dark — „Konstelacja")
> W oknie i na powierzchniach natywnych terakota to rodzina **#C24010 / #D9542A / #9A3009**,
> **nie** `--terracotta #AC4B16` z bazy paper. Złoto i jadeit żyją **tylko** w oknie
> (i w bloku Prywatności) — nigdy jako kolor UI na paper.

| Token | Hex | sRGB (0–1) | Rola |
|---|---|---|---|
| `hi` | `#FAF3E2` | 0.980 0.953 0.886 | tekst główny na ciemnym |
| `body` | `rgba(#FAF3E2,.55)` | biały α .55 (lub .66/.78/.82/.9) | tekst wtórny |
| `terra` | `#C24010` | 0.760 0.251 0.063 | **akcja** — base |
| `terra-lit` | `#D9542A` | 0.851 0.329 0.165 | akcja hover / pasek zapytania |
| `terra-deep` | `#9A3009` | 0.604 0.188 0.035 | akcja pressed |
| `terra-txt` | `#E0633A` | 0.878 0.388 0.227 | akcja na tekście (↗, Cofnij) |
| `gold` | `#D6B033` | 0.839 0.690 0.200 | **insight** — pasek insightu, daty, eyebrow |
| `gold-glow` | `#F4DD8E` | 0.957 0.867 0.557 | glow / `<mark>` tekst |
| `cloud` | `#E7B45C` | 0.906 0.706 0.361 | „✦ do chmury" |
| `jade` | `#46B17E` | 0.275 0.694 0.494 | **lokalne** — kropki, fill Zachowaj |
| `jade-txt` | `#8BE0B5` | 0.545 0.878 0.710 | jadeit na tekście |
| tło okna | `radial(130% 120% at 64% 0%, #1C1B24, #16141C 50%, #100E15)` | — | statyczny, rysowany raz |

**Reguła akcentów (egzekwowana twardo, `README.md §7`):** akcja użytkownika → **terakota**;
„zostaje lokalnie" → **jadeit**; insight / tekst do chmury → **złoto**. Konsekwencja: pasek
aktywnego wiersza **insightu** = złoto; aktywnego **zapytania** = terakota (patrz `08`).

### 5. Helper Swift (bazowy — pozostałe dokumenty go zakładają)
```swift
import AppKit

enum TS {  // Timshel Scale — px(redline) == pt
    /// systemFont sam wybiera optyk Display(≥20pt)/Text(<20pt) — nasz próg 20pt.
    static func font(_ pt: CGFloat, _ w: NSFont.Weight = .regular) -> NSFont {
        NSFont.systemFont(ofSize: pt, weight: w)          // 400→.regular 500→.medium 700→.bold
    }
    static func mono(_ pt: CGFloat, _ w: NSFont.Weight = .regular) -> NSFont {
        NSFont.monospacedSystemFont(ofSize: pt, weight: w) // SF Mono
    }
    /// kern (pt) = tracking(em) × rozmiar(pt)
    static func kern(_ em: CGFloat, _ pt: CGFloat) -> CGFloat { em * pt }
}

enum TC {  // Timshel Color — powierzchnia okna (dark)
    static func hex(_ r: Int, _ g: Int, _ b: Int, _ a: CGFloat = 1) -> NSColor {
        NSColor(srgbRed: CGFloat(r)/255, green: CGFloat(g)/255, blue: CGFloat(b)/255, alpha: a)
    }
    static let hi        = hex(250,243,226)          // #FAF3E2
    static func body(_ a: CGFloat) -> NSColor { hex(250,243,226, a) }  // biały-ciepły α
    static let terra     = hex(194, 64, 16)          // #C24010
    static let terraLit  = hex(217, 84, 42)          // #D9542A
    static let terraDeep = hex(154, 48,  9)          // #9A3009
    static let terraTxt  = hex(224, 99, 58)          // #E0633A
    static let gold      = hex(214,176, 51)          // #D6B033
    static let goldGlow  = hex(244,221,142)          // #F4DD8E
    static let cloud     = hex(231,180, 92)          // #E7B45C
    static let jade      = hex( 70,177,126)          // #46B17E
    static let jadeTxt   = hex(139,224,181)          // #8BE0B5
}
```

---

## Dokumenty (kolejność = priorytet)

| # | Dokument | Priorytet | Co rozstrzyga |
|---|---|---|---|
| **01** | `01-typografia.md` | **BLOKER** | rampa per styl → SF Pro/Text, pt, waga, kern(pt), lineHeightMultiple, token |
| **02** | `02-komponenty.md` | **BLOKER** | custom (layer-backed) vs natywny (która klasa) + tint + gotcha padding/baseline/focus-ring |
| 03 | `03-resize.md` | wysokie | okno / szyna / reader fluid / co zawija, co ucina / stopka + handoff |
| 04 | `04-ruch-caanimation.md` | wysokie | per animacja: from→to, czas, easing (punkty), `prefers-reduced-motion` |
| 05 | `05-hairline.md` | wysokie | 0.5/1/1.5/2.5 px → device-hairline vs logical pt |
| 06 | `06-sygile-coregraphics.md` | nice | geometria węzłów/łuków/glow per typ do `_SigilView.drawRect_` |
| 07 | `07-marki-llm.md` | nice | znaki Claude/ChatGPT — spec osadzenia (template-image); assety do dostarczenia |
| 08 | `08-cele-portu-beta17.md` | — | potwierdzenie celów + rozbieżności względem buildu beta.17 |

**Kolejność czytania w porcie:** `08` (co się zmienia względem tego, co w kodzie) → `01`+`02`
(fundament renderu) → `03`–`05` (zachowanie) → `06`+`07` (assety).

*Podgląd wszystkich dokumentów w jednym miejscu: `index.html` (czytnik w stylu handoffu).*
