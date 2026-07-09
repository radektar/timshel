# 07 · Znaki marek LLM — spec osadzenia

**Potwierdzenie:** glif w prototypie (`redesign-sigils.js → mIco('claude')`, 5-ramienna
gwiazdka) jest **placeholderem**, **nie** kanonicznym znakiem. W paczce **nie ma**
`assets/brands/claude.svg` ani `openai.svg` — README §13 oznacza je „**do dostarczenia**".

**Nie odtwarzam znaków Claude (Anthropic) ani ChatGPT/OpenAI** — to znaki towarowe stron
trzecich. Kanoniczne, monochromatyczne pliki pobierz z oficjalnych brand-kitów:
**Anthropic** (znak Claude) i **OpenAI** (znak ChatGPT). Poniżej **kanoniczna specyfikacja
osadzenia** (template-image) + checklist, którą dostarczone pliki muszą spełnić, oraz kod
integracji. Tylko **Claude + ChatGPT** (Gemini odpada — brak prefill-URL).

---

## Czego wymagają dostarczone pliki (`assets/brands/claude.svg`, `openai.svg`)

| Wymóg | Wartość |
|---|---|
| Format | SVG, **path/kształt** (bez tekstu, bez `<image>`) |
| Kolor | **jednokolorowy** — `fill` monochromatyczny (docelowo tintowany), tło **przezroczyste** |
| viewBox | **kwadrat** (`0 0 16 16` oraz `0 0 20 20` lub jeden skalowalny `0 0 24 24`) |
| Padding | **zerowy poza optycznym** — glif wypełnia pole, wyśrodkowany optycznie |
| Waga glifu | dopasowana optycznie do etykiety `12.5 pt .medium` obok |

Import do AppKit jako **template-image**: kolor niesie `contentTintColor` nadrzędnego
przycisku, nie sam plik.

## Rozmiary i tint (z redline E5 + README §5)

| Kontekst | Rozmiar | Tint |
|---|---|---|
| Split-CTA „Kontynuuj w Claude ▾" (E) | **16 pt** (E5: „glif marki 16 px", gap 7) | **biały `#FFFFFF`** (na terakocie) |
| Menu / switcher (Claude/ChatGPT) | **16 pt** | kolor tekstu pozycji (`hi` / biel na highlight terakotowym) |
| Ewentualne większe CTA/hero | **~20 pt** (rezerwa) | wg tła |

> Rozbieżność do świadomego rozstrzygnięcia: README §5/#7 wymienia „16 px (UI) i ~20 px
> (CTA)", ale redline E5 pokazuje **16 px w split-CTA**. **Domyślnie 16 pt** także w CTA
> (za E5); 20 pt trzymaj w rezerwie na większe powierzchnie, jeśli powstaną.

## Integracja

```swift
func brandImage(_ name: String, pt: CGFloat) -> NSImage {
    let img = NSImage(named: name)!        // "claude" / "chatgpt" z assets/brands
    img.isTemplate = true                  // template-image → tint z contentTintColor
    img.size = NSSize(width: pt, height: pt)
    return img
}

// w split-CTA (główny przycisk terakotowy):
let iv = NSImageView(image: brandImage("claude", pt: 16))
iv.contentTintColor = .white               // biel na terakocie
// wyrównanie: środek glifu do cap-height etykiety, gap 7 pt do tekstu
```

**Checklist odbioru assetu** (zanim wejdzie do buildu):
- [ ] `isTemplate` daje czysty tint (plik ma jeden kanał alpha, brak wbudowanych kolorów)
- [ ] wyśrodkowany w kwadracie; brak asymetrycznego marginesu
- [ ] czytelny przy **16 pt** (menu) — nie gubi kształtu
- [ ] biel na terakocie ma kontrast; kolor tekstu w menu również
- [ ] zgodny z aktualnymi wytycznymi brand-kitu danego dostawcy

---

## Sygnet aplikacji — **to nie jest znak marki LLM**

`--logo-sygnet` (fala, 6 zaokrąglonych słupków = ikona z paska menu) to **znak Timshel**,
generowany z maski w `tokens.css` (brak bitmap). Nie mylić z markami LLM.

| Użycie | Render |
|---|---|
| Ikona apki | gradientowy sygnet (`--logo-mesh`) na **czarnym kaflu `#141414`** |
| Pasek menu (`NSStatusItem`) | **monochromatyczny** sygnet, template-image, tint systemowy; stan „indeksuję" → 55% opacity |
| Ikona w notyfikacji (`.notif .aicon`) | sygnet mesh na `#141414`, 34 pt, `r8` |

Sygnet ⇒ maska `--logo-sygnet` nałożona na wypełnienie (`--logo-mesh` + grain) — w AppKit
statyczny obraz/warstwa, nie animowany gradient (`00`).
