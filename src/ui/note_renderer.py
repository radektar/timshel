"""Markdown → HTML renderer for the in-app note reader (Konstelacja).

Pure module — no AppKit imports — so the whole rendering path is testable in
the plain pytest suite. The WKWebView host lives in ``dashboard_window``; this
module only produces a fully self-contained HTML page (inline CSS from
``theme.HEX`` tokens, no external resources, no JavaScript).

Privacy stance (matches the product promise "nothing leaves the machine"):

- raw HTML in notes is escaped, never rendered (``html=False``);
- images are rendered as plain links, so the webview never fetches a remote
  URL just because a note embeds one;
- bare-URL autolinking is off (no ``linkify-it-py`` dependency); explicit
  ``[text](url)`` links still work and are handed to the browser by the
  navigation delegate, not loaded in-app.

``[[wikilinks]]`` become ``timshel-note://<name>`` anchors the navigation
delegate resolves back to vault notes.
"""

from __future__ import annotations

import html as _html
import re
import unicodedata
from pathlib import Path
from typing import Optional
from urllib.parse import quote, unquote

from markdown_it import MarkdownIt

from src.markdown_frontmatter import split_frontmatter
from src.ui import theme

#: Scheme the reader uses for note-to-note links; the WKWebView navigation
#: delegate intercepts it and renders the target note in-app.
WIKILINK_SCHEME = "timshel-note"

#: Anchor id the "Przejdź do transkrypcji" jump link targets (the note
#: template's ``## Transkrypcja`` heading slugifies to this).
TRANSCRIPT_ANCHOR = "transkrypcja"


def strip_frontmatter(text: str) -> str:
    """Body of a note without its leading ``---`` frontmatter block."""
    return split_frontmatter(text)[1]


def heading_slug(text: str) -> str:
    """Stable ascii id for a heading ("## Transkrypcja" → "transkrypcja")."""
    norm = unicodedata.normalize("NFKD", text)
    ascii_txt = norm.encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"[^a-z0-9]+", "-", ascii_txt).strip("-")


def wikilink_target(url: str) -> Optional[str]:
    """Note basename from a ``timshel-note://`` URL (None for other URLs)."""
    prefix = f"{WIKILINK_SCHEME}://"
    if not url.startswith(prefix):
        return None
    return unquote(url[len(prefix) :]).strip() or None


def _wikilink_rule(state, silent: bool) -> bool:
    """Inline rule: ``[[Target]]`` / ``[[Target|Label]]`` → in-app anchor."""
    src = state.src
    pos = state.pos
    if src[pos : pos + 2] != "[[":
        return False
    end = src.find("]]", pos + 2)
    if end == -1:
        return False
    inner = src[pos + 2 : end]
    # A backtick inside means the ']]' likely sits in a code span — bail out
    # so the backticks rule can parse it instead of us eating across it.
    if not inner.strip() or "\n" in inner or "`" in inner:
        return False
    target, _, label = inner.partition("|")
    target = target.strip()
    label = label.strip() or target
    if not target:
        return False
    if not silent:
        token = state.push("link_open", "a", 1)
        token.attrSet("href", f"{WIKILINK_SCHEME}://{quote(target)}")
        token.attrSet("class", "wikilink")
        text_token = state.push("text", "", 0)
        text_token.content = label
        state.push("link_close", "a", -1)
    state.pos = end + 2
    return True


def _render_image_as_link(self, tokens, idx, options, env) -> str:
    """Images become links — the reader must never fetch remote resources."""
    token = tokens[idx]
    src = token.attrGet("src") or ""
    alt = token.content or src
    return (
        f'<a href="{_html.escape(src, quote=True)}" class="image-link">'
        f"{_html.escape(alt)}</a>"
    )


def _anchor_headings(md: MarkdownIt) -> None:
    """Give every heading an id so in-document jump links work without JS."""

    def rule(state) -> None:
        tokens = state.tokens
        for i, token in enumerate(tokens):
            if token.type != "heading_open" or i + 1 >= len(tokens):
                continue
            slug = heading_slug(tokens[i + 1].content)
            if slug:
                token.attrSet("id", slug)

    md.core.ruler.push("heading_anchors", rule)


def build_parser() -> MarkdownIt:
    """gfm-like parser hardened for local, non-interactive rendering."""
    md = MarkdownIt("gfm-like", options_update={"html": False, "linkify": False})
    md.inline.ruler.before("link", "wikilink", _wikilink_rule)
    md.add_render_rule("image", _render_image_as_link)
    _anchor_headings(md)
    return md


_parser: Optional[MarkdownIt] = None


def render_body(md_text: str) -> str:
    """Markdown body → HTML fragment."""
    global _parser
    if _parser is None:
        _parser = build_parser()
    return str(_parser.render(md_text))


# --------------------------------------------------------------------------- #
# Page assembly
# --------------------------------------------------------------------------- #

_CSS = """
:root { color-scheme: dark; }
* { margin: 0; padding: 0; box-sizing: border-box; }
html { background: #100E15; }
body {
  font: 15px/1.55 -apple-system, BlinkMacSystemFont, sans-serif;
  color: %(body)s;
  padding: 20px 24px 48px;
  -webkit-font-smoothing: antialiased;
  word-wrap: break-word;
}
article { max-width: 640px; margin: 0 auto; }
header.note-head { margin-bottom: 18px; }
h1.note-title {
  color: %(hi)s; font-size: 19px; line-height: 1.3;
  font-weight: 600; letter-spacing: 0.01em;
}
p.note-meta { color: %(body)s; opacity: 0.62; font-size: 12.5px; margin-top: 5px; }
p.note-jump { margin-top: 10px; font-size: 13px; }
p.note-jump a { color: %(terra_txt)s; text-decoration: none; }
h1, h2, h3, h4 { color: %(hi)s; font-weight: 600; margin: 22px 0 8px; }
h1 { font-size: 17px; } h2 { font-size: 16px; } h3 { font-size: 15px; }
h4 { font-size: 14px; }
p, ul, ol, table, blockquote, pre { margin-bottom: 10px; }
ul, ol { padding-left: 22px; }
li { margin-bottom: 3px; }
a { color: %(gold_cloud)s; text-decoration: none; border-bottom: 1px solid rgba(231,180,92,0.35); }
a.wikilink { color: %(jade_text)s; border-bottom: 1px solid rgba(139,224,181,0.35); }
a.image-link { opacity: 0.8; }
strong { color: %(hi)s; font-weight: 600; }
em { font-style: italic; }
code {
  font: 12.5px ui-monospace, "SF Mono", Menlo, monospace;
  background: rgba(255,255,255,0.07); border-radius: 4px; padding: 1px 5px;
}
pre {
  background: rgba(255,255,255,0.05); border-radius: 6px;
  padding: 10px 12px; overflow-x: auto;
}
pre code { background: none; padding: 0; }
blockquote {
  border-left: 2px solid rgba(194,64,16,0.55);
  padding: 2px 0 2px 12px; opacity: 0.9;
}
hr { border: none; border-top: 1px solid rgba(255,255,255,0.09); margin: 18px 0; }
table { border-collapse: collapse; width: 100%%; font-size: 13.5px; }
th, td {
  border: 1px solid rgba(255,255,255,0.12);
  padding: 5px 9px; text-align: left; vertical-align: top;
}
th { color: %(hi)s; background: rgba(255,255,255,0.04); }
::selection { background: rgba(194,64,16,0.35); }
""" % {
    "hi": theme.HEX["window_hi"],
    "body": theme.HEX["window_body"],
    "terra_txt": theme.HEX["terra_txt"],
    "jade_text": theme.HEX["jade_text"],
    "gold_cloud": theme.HEX["gold_cloud"],
}

_PAGE = """<!doctype html>
<html lang="pl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>{css}</style></head>
<body><article>
<header class="note-head">
<h1 class="note-title">{title}</h1>
{meta}{jump}
</header>
{body}
</article></body></html>
"""


def _meta_line(fm: dict) -> str:
    parts = []
    # Day: same priority as the digest layer (candidate_assembly), date first.
    # Time-of-day lives only in recording_date (date is day-only in the note
    # template) — keep showing it so same-day recordings stay distinguishable.
    date = (fm.get("date") or fm.get("recording_date") or "").strip()
    rec = (fm.get("recording_date") or "").strip()
    day = date[:10]
    if day and day.lower() not in ("none", "null"):
        time_part = rec[11:16] if len(rec) >= 16 and rec[10] in "T " else ""
        parts.append(f"{day} · {time_part}" if time_part else day)
    duration = (fm.get("duration") or "").strip()
    if duration and duration not in ("00:00:00", "None"):
        parts.append(duration)
    lang = (fm.get("language") or "").strip()
    if lang and lang.lower() not in ("none", "auto"):
        parts.append(lang.upper())
    if not parts:
        return ""
    return f'<p class="note-meta">{_html.escape(" · ".join(parts))}</p>\n'


def note_page_html(path: Path) -> str:
    """Full self-contained HTML page for one note on disk.

    Raises ``OSError`` on unreadable paths — the caller (window) decides how
    to degrade (it falls back to the external opener).
    """
    text = path.read_text(encoding="utf-8")
    # One read AND one split — header and body can never disagree about
    # where the frontmatter ends.
    fm, body = split_frontmatter(text)
    title = (fm.get("title") or "").strip() or path.stem
    body_html = render_body(body)
    jump = ""
    if f'id="{TRANSCRIPT_ANCHOR}"' in body_html:
        jump = (
            f'<p class="note-jump"><a href="#{TRANSCRIPT_ANCHOR}">'
            "Przejdź do transkrypcji ↓</a></p>\n"
        )
    return _PAGE.format(
        css=_CSS,
        title=_html.escape(title),
        meta=_meta_line(fm),
        jump=jump,
        body=body_html,
    )
