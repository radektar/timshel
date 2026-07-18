# Markdown reader in the Konstelacja window — research + plan (gated)

Status: **IMPLEMENTED 2026-07-18** (branch `feat/markdown-reader`) — plan
executed as written; editing paths stay open (source-editor / WYSIWYG-in-
webview / mdformat token serialization) per the follow-up research.
Vault pointer: `research/2026-07-18 - Czytnik markdown w oknie - research.md`.

## Goal

Read a note's **summary + transcript in-app**, entered from the digest:
click a source chip on a connection (or a row in the Notatki section) and
the reader renders the note — no jump to Obsidian. Closes the loop
"insight → check the source → judge the connection" inside one window.

## What the content actually is

- Notes are generated from `config.MD_TEMPLATE` (config.py:193): YAML
  frontmatter → `{summary}` (Haiku: headings, bullets, Stanowiska,
  `[[wikilinks]]`) → `## Transkrypcja` → paragraphs.
- BUT imported files (txt/md/vtt — Zoom/Teams exports) can carry arbitrary
  markdown incl. tables. Renderer must cover full GFM-like markdown, not
  just our template.
- Frontmatter is already stripped/parsed by `src/markdown_frontmatter.py`.
- basename→path resolution exists (`src/ui/obsidian_link.open_note`);
  connections carry note basenames (`insight_model.Connection.notes`).

## Package research (verified 2026-07-18)

| Option | Verdict |
|---|---|
| **`markdown-it-py` 4.x** ⭐ | Pure Python, actively maintained, CommonMark 0.31.2, `gfm-like` preset = tables+strikethrough in core (no plugin needed). Already in venv (via rich) — but must be added to `requirements.txt` + py2app `packages` to ship in bundle. |
| `mistune` 3 | ~3× faster but NOT CommonMark-compliant (nested inline edge cases). Speed irrelevant at our note sizes (<100 KB, <10 ms either way). Rejected. |
| `NSAttributedString(markdown:)` (macOS 12+) | No tables, presentation-intent styling is manual work comparable to a custom renderer, less control. Rejected. |

Display layer — two viable renderers, decision made:

| Renderer | Trade-off |
|---|---|
| **WKWebView + inline CSS** ⭐ | Full markdown coverage for free (tables/blockquotes from vtt/md imports), ~50 lines CSS from Konstelacja tokens. Cost: new dep `pyobjc-framework-WebKit` (verified: 12.2 universal2 wheel exists, 50 kB, matches installed pyobjc 12.2); slight "web island" feel — mitigated by CSS matching the window exactly. |
| Native NSTextView + token→NSAttributedString renderer | Perfect native consistency, no WebKit. Cost: ~2× implementation, tables/blockquote layout manual — exactly the content imports can carry. Rejected for v1. |

Security/hygiene (verified): JS off via
`WKWebpagePreferences.allowsContentJavaScript = False` on
`configuration.defaultWebpagePreferences`; `loadHTMLString_baseURL_(html, None)`
⇒ no relative resource loads; content is 100% local, inline CSS only.

## Plan (~1–1.5 days)

1. **Deps:** `markdown-it-py` + `pyobjc-framework-WebKit` → `requirements.txt`
   + `setup_app.py` packages/includes; smoke-bundle guards the bundle.
2. **Renderer module `src/ui/note_renderer.py`:** frontmatter off
   (`markdown_frontmatter`), `MarkdownIt("gfm-like")`, custom inline rule
   `[[wikilink]]` → `<a href="timshel-note://<name>">`, wrap in HTML with
   inline CSS from `theme.py` tokens (reader bg, `#FAF3E2`/`#C9BBA6`,
   radius family 6/5/12/14, `-apple-system` ⇒ SF Pro).
3. **Reader mode "notatka" in `dashboard_window.py`:** WKWebView (JS off)
   swapped into the reader area; header = note title + "← Wróć" +
   "Otwórz w Obsidianie ↗" (existing opener). Entry points:
   (a) Notatki row click, (b) **source chip click on a connection** —
   the digest entry this research is for. Chip keeps its current look;
   click resolves basename → path → render. Summary lands on top (template
   order), link "Przejdź do transkrypcji" jumps to `## Transkrypcja`.
4. **Navigation delegate:** intercept `timshel-note://` → render that note
   in-app (breadcrumb back); external `http(s)` → `NSWorkspace` open;
   everything else denied.
5. **Tests:** renderer unit tests (headings/lists/tables/wikilinks/frontmatter
   stripped/JS never enabled), chip-click resolution, back navigation.
   Visual QA via preview harness (promote `preview_window.py` →
   `make preview-window` — same round, it was parked for exactly this).
6. Suite + mypy + smoke-bundle + tester DMG.

## Consciously out of scope (v1)

- Editing, live reload, search-in-note.
- Rendering digest .md files themselves in-app (digest lives in the deck UI;
  the raw file keeps opening via opener).
- Mermaid/code highlight — plain `<pre>` styling only.
