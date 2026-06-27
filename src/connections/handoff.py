"""Hand a packaged insight off to an external tool (ADR-004).

A gesture = package the insight's context (the spark + the dated evidence + the
directions the user selected) and throw it over the wall to the user's own tool.
Malinche does not host the conversation or store the action — it packages and
hands off. **Zero OAuth in v1**: every target is reached with macOS ``open`` /
``osascript`` / ``pbcopy``, so Malinche itself makes no network call.

Split, as everywhere in this codebase: the **builders are pure and testable**
(seeded prompt, per-tool URL, ``.ics`` body, AppleScript); the side-effecting
dispatch is a thin wrapper over one ``_run`` seam the tests monkeypatch.
"""

from __future__ import annotations

import hashlib
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable, List, Optional, Sequence, Tuple
from urllib.parse import quote

from src.logger import logger

# Targets (mirror validation_signal.TARGET_*).
LLM = "llm"
TASK = "task"
CALENDAR = "calendar"
CLIPBOARD = "clipboard"

#: Connected LLM tools: id → (display name, base URL, supports ?q= prefill).
LLM_TOOLS = {
    "claude": ("Claude", "https://claude.ai/new", True),
    "chatgpt": ("ChatGPT", "https://chatgpt.com/", True),
    "gemini": ("Gemini", "https://gemini.google.com/app", False),  # no public prefill
}

#: claude.ai / chatgpt truncate very long ?q= values — past this many encoded
#: chars we fall back to clipboard-seed + opening the bare tool (ADR-004).
URL_MAX = 6000


def tool_name(tool: str) -> str:
    """Display name for a connected-LLM id (falls back to a title-cased id)."""
    entry = LLM_TOOLS.get(tool)
    return entry[0] if entry else (tool or "").title() or "LLM"


# --------------------------------------------------------------------------- #
# Pure builders
# --------------------------------------------------------------------------- #
EvidenceTuple = Tuple[str, str, str]  # (date, note, quote)


def seeded_prompt(
    label: str,
    rationale: str,
    evidence: Sequence[EvidenceTuple],
    directions: Sequence[str],
) -> str:
    """The markdown payload seeded into the handoff (LLM / clipboard).

    Non-prescriptive by construction: it states the insight, grounds it in the
    quotes, lists the chosen directions and asks for *thinking*, not answers —
    the POSITIONING lock holds across the wall.
    """
    lines: List[str] = ["Mam wgląd z moich notatek głosowych.", ""]
    head = f"{label}: " if label else ""
    lines.append(f"{head}„{rationale.strip()}”")
    if evidence:
        lines.append("")
        lines.append("Oparte na:")
        for date, note, quote_ in evidence:
            stamp = f"{date} · " if date else ""
            lines.append(f"- {stamp}{note}: „{quote_}”")
    chosen = [d for d in directions if d and d.strip()]
    if chosen:
        lines.append("")
        lines.append("Chcę rozwinąć:")
        for i, d in enumerate(chosen, start=1):
            lines.append(f"{i}. {d.strip()}")
    lines.append("")
    lines.append("Pomóż mi to przemyśleć — bez gotowych odpowiedzi, raczej dobre pytania.")
    return "\n".join(lines)


def llm_url(tool: str, prompt: str) -> Optional[str]:
    """Deep-link that opens ``prompt`` in the connected LLM, or ``None``.

    ``None`` means "no prefill available" — either the tool has no public
    prompt-prefill URL (Gemini) or the encoded payload exceeds :data:`URL_MAX`.
    The caller then falls back to clipboard-seed + opening the bare tool.
    """
    entry = LLM_TOOLS.get(tool)
    if entry is None:
        return None
    _, base, supports_prefill = entry
    if not supports_prefill:
        return None
    encoded = quote(prompt, safe="")
    if len(encoded) > URL_MAX:
        return None
    return f"{base}?q={encoded}"


def llm_base_url(tool: str) -> str:
    """Bare tool URL (used when prefill isn't available — open + paste)."""
    entry = LLM_TOOLS.get(tool)
    return entry[1] if entry else LLM_TOOLS["claude"][1]


def _ics_escape(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\n", "\\n")
    )


def ics_text(summary: str, description: str, *, now: Optional[datetime] = None) -> str:
    """A VEVENT the user adds via Calendar.app (default: tomorrow 09:00, 30 min).

    The time is a sensible default the add-dialog lets the user change — we don't
    presume to know when; we just stop the insight from evaporating.
    """
    now = now or datetime.now()
    start = (now + timedelta(days=1)).replace(
        hour=9, minute=0, second=0, microsecond=0
    )
    stamp = now.strftime("%Y%m%dT%H%M%S")
    dtstart = start.strftime("%Y%m%dT%H%M%S")
    return "\r\n".join(
        [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "PRODID:-//Malinche//Insights//PL",
            "CALSCALE:GREGORIAN",
            "BEGIN:VEVENT",
            f"UID:{stamp}-{hashlib.sha1(summary.encode('utf-8')).hexdigest()[:8]}@malinche",
            f"DTSTAMP:{stamp}",
            f"DTSTART:{dtstart}",
            "DURATION:PT30M",
            f"SUMMARY:{_ics_escape(summary)}",
            f"DESCRIPTION:{_ics_escape(description)}",
            "END:VEVENT",
            "END:VCALENDAR",
            "",
        ]
    )


def _osa_string(text: str) -> str:
    """An AppleScript string *expression* for ``text``.

    AppleScript has no ``\\n`` escape and cannot span a quoted literal across
    physical lines, so embedded newlines (the seeded prompt is always multi-line)
    are spliced in via the ``linefeed`` constant — otherwise the script fails to
    compile and the Reminders handoff silently never works.
    """
    esc = text.replace("\\", "\\\\").replace('"', '\\"')
    esc = esc.replace("\r\n", "\n").replace("\r", "\n")
    return '"' + esc.replace("\n", '" & linefeed & "') + '"'


def reminders_script(title: str, body: str) -> str:
    """AppleScript that creates a reminder in Reminders.app (local, no OAuth)."""
    return (
        'tell application "Reminders"\n'
        f"  make new reminder with properties {{name:{_osa_string(title)}, "
        f"body:{_osa_string(body)}}}\n"
        "end tell"
    )


# --------------------------------------------------------------------------- #
# Side-effecting dispatch (thin; the one _run seam tests monkeypatch)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class HandoffResult:
    ok: bool
    mode: str  # "open" | "clipboard" | "applescript" | "error"
    toast: str


def _run(args: Sequence[str], *, input_text: Optional[str] = None) -> bool:
    """Run a local command, returning success. Never raises."""
    try:
        subprocess.run(
            list(args),
            input=(input_text.encode("utf-8") if input_text is not None else None),
            check=True,
            capture_output=True,
        )
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("handoff command failed (%s): %s", args[:1], exc)
        return False


def _open_url(url: str) -> bool:
    return _run(["open", url])


def _copy(text: str) -> bool:
    return _run(["pbcopy"], input_text=text)


def _open_ics(text: str) -> bool:
    try:
        fd = tempfile.NamedTemporaryFile(
            "w", suffix=".ics", delete=False, encoding="utf-8"
        )
        with fd:
            fd.write(text)
        return _run(["open", fd.name])
    except Exception as exc:  # noqa: BLE001
        logger.warning("could not stage .ics: %s", exc)
        return False


def _osascript(script: str) -> bool:
    return _run(["osascript", "-e", script])


def dispatch(
    target: str,
    *,
    label: str = "",
    rationale: str = "",
    evidence: Iterable[EvidenceTuple] = (),
    directions: Sequence[str] = (),
    tool: str = "claude",
    now: Optional[datetime] = None,
) -> HandoffResult:
    """Package the insight and hand it to ``target``. Never raises.

    Returns a :class:`HandoffResult` whose ``toast`` the window surfaces. The
    caller is responsible for logging the ``action_taken`` event separately
    (validation_signal.record_action) — handoff does the doing, not the logging.
    """
    evidence = list(evidence)
    prompt = seeded_prompt(label, rationale, evidence, directions)
    n = len([d for d in directions if d and d.strip()])

    if target == LLM:
        url = llm_url(tool, prompt)
        name = tool_name(tool)
        if url:
            ok = _open_url(url)
            return HandoffResult(ok, "open", f"Wysłano do {name}" if ok else "Nie udało się")
        # no prefill (Gemini / too long): copy the prompt, open the bare tool
        ok = _copy(prompt) and _open_url(llm_base_url(tool))
        return HandoffResult(
            ok, "clipboard",
            f"Prompt skopiowany — wklej w {name}" if ok else "Nie udało się",
        )

    if target == CALENDAR:
        summary = (directions[0].strip() if directions and directions[0].strip()
                   else (label or "Insight"))
        ok = _open_ics(ics_text(summary, prompt, now=now))
        return HandoffResult(ok, "open", "Otwórz w Kalendarzu" if ok else "Nie udało się")

    if target == TASK:
        title = (directions[0].strip() if directions and directions[0].strip()
                 else (label or "Insight"))
        ok = _osascript(reminders_script(title, prompt))
        return HandoffResult(ok, "applescript",
                             "Utworzono zadanie" if ok else "Nie udało się")

    if target == CLIPBOARD:
        ok = _copy(prompt)
        plural = "kierunek" if n == 1 else "kierunki"
        return HandoffResult(ok, "clipboard", f"Skopiowano {n} {plural}")

    return HandoffResult(False, "error", "Nieznany cel")
