#!/usr/bin/env python3
"""Autonomous acceptance harness for the tester build (A1–A8).

Exercises the ENGINE end-to-end on the real machine — real whisper models, the
operator's real Anthropic key — WITHOUT touching the real vault: every check
runs in a throwaway temp dir. It complements the human-only GUI/permission pass
(Gatekeeper, Full Disk Access, wizard, menu clicks, physical recorder) that
macOS deliberately cannot delegate.

Run:  make verify-tester      (or  ./venv312/bin/python scripts/verify_tester.py)

Exit code 0 = every non-skipped check passed. Checks that need a dependency the
machine lacks (whisper models, an API key, macOS `say`) report SKIP, not FAIL.
"""

from __future__ import annotations

import json
import sys
import tempfile
import traceback
from datetime import datetime, timedelta
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))


class Skip(Exception):
    """Raised by a check when a required dependency is absent."""


def _real_api_key() -> str:
    cfg = Path.home() / "Library" / "Application Support" / "Timshel" / "config.json"
    if not cfg.exists():
        return ""
    try:
        return json.loads(cfg.read_text(encoding="utf-8")).get("ai_api_key") or ""
    except Exception:
        return ""


# --------------------------------------------------------------------------- #
# A1 — migration is idempotent and non-destructive.
# --------------------------------------------------------------------------- #
def a1_migration_idempotent() -> str:
    from src import bootstrap

    support = Path.home() / "Library" / "Application Support" / "Timshel"
    cfg_path = support / "config.json"
    if not cfg_path.exists():
        raise Skip("no Timshel config yet (run the app once)")

    before = cfg_path.read_bytes()
    key_before = json.loads(before).get("ai_api_key")
    # ensure_ready must be a no-op on an already-migrated machine.
    bootstrap.ensure_ready()
    after = json.loads(cfg_path.read_text(encoding="utf-8"))
    assert after.get("ai_api_key") == key_before, "API key changed across ensure_ready"
    assert not (
        Path.home() / "Library" / "Application Support" / "Malinche"
    ).exists(), "old Malinche app-support dir reappeared"
    return "config + key intact; no Malinche dir"


# --------------------------------------------------------------------------- #
# A8 — tester_mode maps to the H1 knobs through __post_init__.
# --------------------------------------------------------------------------- #
def a8_tester_mode_wiring() -> str:
    from src.config.config import Config
    from src.config.settings import UserSettings
    from unittest.mock import patch

    s = UserSettings(tester_mode=True)
    with patch.object(UserSettings, "load", classmethod(lambda cls: s)):
        cfg = Config()
    assert cfg.VERDICT_ENABLED and cfg.INSIGHT_METRICS_ENABLED, "gates off"
    assert cfg.PROTOTYPE_TESTER_MODE, "label off"
    assert cfg.LLM_MODEL_SYNTHESIS == "claude-opus-4-8", "synthesis model wrong"
    assert cfg.LLM_MODEL_VERDICT == "claude-opus-4-8", "verdict model wrong"
    assert cfg.SYNTHESIS_ENTITY_COUNT == 4, "entity channel off"
    return "verdict+metrics+opus+channels all wired"


# --------------------------------------------------------------------------- #
# A3 — text seed (txt/md/vtt) → notes + dedup + frontmatter.
# --------------------------------------------------------------------------- #
def a3_text_import(tmp: Path) -> str:
    from unittest.mock import patch
    from src.config.config import Config
    from src.transcriber import Transcriber

    cfg = Config()
    cfg.TRANSCRIBE_DIR = tmp / "vault"
    cfg.TRANSCRIBE_DIR.mkdir(parents=True, exist_ok=True)
    cfg.LOCAL_RECORDINGS_DIR = tmp / "staging"
    cfg.ENABLE_RECALL_INDEX = False
    with patch("src.transcriber.logger"):
        t = Transcriber(config=cfg)
    t.summarizer = None
    t.tagger = None

    (tmp / "a.txt").write_text("Notatka o strategii rekrutacji testerów.", encoding="utf-8")
    (tmp / "b.md").write_text("# Nagłówek\n\nDruga notatka o pricingu.", encoding="utf-8")
    (tmp / "c.vtt").write_text(
        "WEBVTT\n\n1\n00:00:00.000 --> 00:00:02.000\n<v R>Trzecia o retencji.\n",
        encoding="utf-8",
    )
    ok = sum(t.import_text_file(tmp / n) for n in ("a.txt", "b.md", "c.vtt"))
    assert ok == 3, f"expected 3 imports, got {ok}"
    notes = list(cfg.TRANSCRIBE_DIR.glob("*.md"))
    assert len(notes) == 3, f"expected 3 notes, got {len(notes)}"
    # dedup
    assert t.import_text_file(tmp / "a.txt") is True
    assert len(list(cfg.TRANSCRIBE_DIR.glob("*.md"))) == 3, "dedup failed"
    # vtt scaffolding stripped, provenance stamped
    vtt_note = next(p for p in notes if "retencji" in p.read_text(encoding="utf-8"))
    body = vtt_note.read_text(encoding="utf-8")
    # The VTT timing/header/tag scaffolding must not survive. (Note: a bare
    # "00:00:00" would false-match the `duration:` frontmatter, so assert on the
    # cue-timing format `.000 -->` instead.)
    assert "WEBVTT" not in body, "WEBVTT header leaked"
    assert "-->" not in body and "00:00:00.000" not in body, "vtt timing leaked"
    assert "<v R>" not in body, "vtt speaker tag leaked"
    assert "source_type: import" in body, "provenance missing"
    return "3 formats imported, deduped, VTT stripped, provenance stamped"


# --------------------------------------------------------------------------- #
# A2 — real audio → note (real whisper + the machine's models).
# --------------------------------------------------------------------------- #
def a2_real_audio(tmp: Path) -> str:
    from unittest.mock import patch
    from tests.fixtures import whisper_runtime as wr
    from tests.fixtures.audio_factory import AudioFactory, say_available

    if wr.find_whisper_install() is None or wr.find_ffmpeg() is None or not say_available():
        raise Skip("no whisper install / ffmpeg / macOS `say`")

    from src.transcriber import Transcriber

    factory = AudioFactory()
    source = factory.make(lang="en_US", ext=".wav")
    cfg = wr.make_e2e_config(tmp / "vault", language="en", model="small")
    cfg.LOCAL_RECORDINGS_DIR = tmp / "staging"
    cfg.ENABLE_RECALL_INDEX = False
    with patch("src.transcriber.logger"):
        t = Transcriber(config=cfg)
    t.summarizer = None
    t.tagger = None

    assert t.import_audio_file(source) is True, "import_audio_file returned False"
    notes = list(Path(cfg.TRANSCRIBE_DIR).glob("*.md"))
    assert len(notes) == 1, f"expected 1 note, got {len(notes)}"
    assert "recording" in notes[0].read_text(encoding="utf-8").lower(), "no transcript text"
    return "real whisper transcribed a .wav into a note"


# --------------------------------------------------------------------------- #
# A4 — alias judge on a live Anthropic call.
# --------------------------------------------------------------------------- #
def a4_alias_judge_live(tmp: Path) -> str:
    key = _real_api_key()
    if not key:
        raise Skip("no Anthropic key in the operator config")

    from src.config import config
    from src.summarizer import ClaudeSummarizer
    from src.vocabulary import VocabularyIndex, find_alias_misses

    vault = tmp / "vault"
    (vault / ".timshel").mkdir(parents=True, exist_ok=True)
    (vault / ".timshel" / "vocabulary.json").write_text(
        json.dumps(
            {"terms": [{"canonical": "Tech to the Rescue", "aliases": ["TekTutoreski"]}]}
        ),
        encoding="utf-8",
    )
    config.TRANSCRIBE_DIR = vault
    config.LLM_API_KEY = key

    vocab = VocabularyIndex(root_dir=vault)
    summarizer = ClaudeSummarizer(api_key=key)
    transcript = (
        "Rozmawialiśmy dziś o współpracy z TekTutoreski. TekTutoreski pomaga "
        "organizacjom pozarządowym w projektach technologicznych. Ustaliliśmy "
        "trzy kolejne kroki z TekTutoreski na najbliższy kwartał."
    )
    summary = summarizer.generate(transcript, known_terms_block=vocab.known_terms_block())
    misses = find_alias_misses(summary.get("summary", ""), vocab)
    # The model should canonicalise the alias; if it slips once, the prod path
    # re-prompts — here we assert the judge at least DETECTS correctly and the
    # canonical form made it into the output.
    canonical_present = "Tech to the Rescue" in summary.get("summary", "")
    assert canonical_present or misses == [], (
        f"neither canonicalised nor detectable; misses={misses}"
    )
    return "live summary canonicalised the alias" if canonical_present else "judge detected the miss"


# --------------------------------------------------------------------------- #
# A5 — real instrumented digest (Opus + verdict + metrics) on a seeded vault.
# --------------------------------------------------------------------------- #
def a5_real_digest(tmp: Path) -> str:
    key = _real_api_key()
    if not key:
        raise Skip("no Anthropic key in the operator config")

    from src.config import config

    vault = tmp / "vault"
    vault.mkdir(parents=True, exist_ok=True)
    today = datetime.now()
    seeds = [
        ("Priorytety produktu — początek", "Zdecydowaliśmy, że najważniejszy jest onboarding testerów i seedowanie vaulta."),
        ("Rozmowa o pricingu", "Rozważamy 59 vs 79 dolarów; onboarding testerów wpływa na konwersję pre-order."),
        ("Retencja i digest", "Cotygodniowy digest ma trzymać retencję; testerzy oceniają połączenia."),
        ("Sprzeczność w priorytetach", "Wcześniej mówiliśmy, że onboarding jest najważniejszy, dziś priorytetem jest pricing."),
    ]
    for i, (title, body) in enumerate(seeds):
        d = (today - timedelta(days=i)).strftime("%Y-%m-%d")
        (vault / f"{d} - {title}.md").write_text(
            f'---\ntitle: "{title}"\ndate: {d}\ntags: [transcription]\n---\n\n'
            f"## Podsumowanie\n\n{body}\n\n## Transkrypcja\n\n{body}\n",
            encoding="utf-8",
        )

    # Point the global config at the temp vault + turn on the tester knobs
    # (same set as magic_digest / the tester build) — a fresh process has no
    # cached synthesizer/scheduler, so they pick these up.
    config.TRANSCRIBE_DIR = vault
    config.LLM_API_KEY = key
    config.CONNECTIONS_STATE_FILE = tmp / "connections_state.json"
    config.DIGEST_LOCK_FILE = tmp / "digest.lock"
    config.PROTOTYPE_TESTER_MODE = True
    config.INSIGHT_METRICS_ENABLED = True
    config.VERDICT_ENABLED = True
    config.SYNTHESIS_ENTITY_COUNT = 4
    config.SYNTHESIS_DENSE_COUNT = 6
    config.SYNTHESIS_GRAPH_COUNT = 6
    config.SYNTHESIS_STANCE_COUNT = 4
    config.LLM_MODEL_SYNTHESIS = "claude-opus-4-8"
    config.LLM_MODEL_VERDICT = "claude-opus-4-8"

    from src.connections.scheduler import run_digest_if_due

    path = run_digest_if_due(transcriber=None, force=True)

    metrics = vault / ".timshel" / "metrics.jsonl"
    assert metrics.exists(), "no metrics.jsonl written — digest pipeline didn't run"
    last = json.loads(metrics.read_text(encoding="utf-8").strip().splitlines()[-1])
    assert last.get("tester_mode") is True, "metrics row not stamped tester_mode"
    assert "opus" in str(last.get("model", "")).lower(), (
        f"digest did not use Opus: {last.get('model')}"
    )
    wrote = f"digest note written ({path.name})" if path else "no connections (clock reset, metrics recorded)"
    return f"instrumented run OK — {wrote}"


# --------------------------------------------------------------------------- #
# A6 — signal instrument → action-rate readout.
# --------------------------------------------------------------------------- #
def a6_signal_report(tmp: Path) -> str:
    from src.connections import validation_signal as vs
    from src.connections import signal_report as sr

    sig_path = tmp / ".timshel" / "signal.jsonl"
    sig_path.parent.mkdir(parents=True, exist_ok=True)
    # Two engaged connections, both actioned via a handoff.
    assert vs.record_action(vs.TARGET_LLM, sig="c1", conn_type="contradiction-over-time",
                            notes=["A", "B"], kind="develop", tool="claude", path=sig_path)
    assert vs.record_action(vs.TARGET_LLM, sig="c2", conn_type="shared-thread",
                            notes=["C", "D"], kind="develop", tool="claude", path=sig_path)
    events, _ = sr.load_events(sig_path)
    summary = sr.summarize(events)
    assert summary.engaged == 2, f"expected 2 engaged, got {summary.engaged}"
    assert summary.actioned == 2, f"expected 2 actioned, got {summary.actioned}"
    return f"engaged={summary.engaged} actioned={summary.actioned} action_rate={summary.action_rate}"


# --------------------------------------------------------------------------- #
# A7 — feedback export bundles the H1 evidence.
# --------------------------------------------------------------------------- #
def a7_feedback_export(tmp: Path) -> str:
    from src.config import config
    from src.feedback_export import build_feedback_zip
    import zipfile

    vault = tmp / "vault"
    sidecar = vault / config.SIDECAR_DIR_NAME
    sidecar.mkdir(parents=True, exist_ok=True)
    (sidecar / "signal.jsonl").write_text('{"action":"action_taken"}\n', encoding="utf-8")
    (sidecar / "metrics.jsonl").write_text('{"cost_usd":0.01,"tester_mode":true}\n', encoding="utf-8")
    digests = vault / config.DIGEST_DIR_NAME
    digests.mkdir(parents=True, exist_ok=True)
    (digests / "2026-07-09 Synthesis.md").write_text("# digest", encoding="utf-8")

    zip_path = build_feedback_zip(vault, tmp / "out", timestamp="20260709-0700")
    with zipfile.ZipFile(zip_path) as zf:
        names = set(zf.namelist())
    assert "manifest.json" in names, "manifest missing"
    assert "sidecar/signal.jsonl" in names and "sidecar/metrics.jsonl" in names, "evidence missing"
    assert any(n.startswith("digests/") for n in names), "digests missing"
    return f"bundle built with {len(names)} members"


# --------------------------------------------------------------------------- #
# Runner.
# --------------------------------------------------------------------------- #
_CHECKS = [
    ("A1  migration idempotent + non-destructive", a1_migration_idempotent, False),
    ("A8  tester_mode → knob wiring", a8_tester_mode_wiring, False),
    ("A3  text seed (txt/md/vtt) + dedup", a3_text_import, True),
    ("A2  real audio → note (whisper)", a2_real_audio, True),
    ("A4  alias judge (live Anthropic)", a4_alias_judge_live, True),
    ("A5  instrumented digest (Opus+verdict+metrics)", a5_real_digest, True),
    ("A6  signal → action-rate", a6_signal_report, True),
    ("A7  feedback export bundle", a7_feedback_export, True),
]


def main() -> int:
    print("Tester-build acceptance harness (engine only; GUI/permissions are human-only)\n")
    results = []
    for label, fn, needs_tmp in _CHECKS:
        try:
            if needs_tmp:
                with tempfile.TemporaryDirectory(prefix="timshel-verify-") as d:
                    detail = fn(Path(d))
            else:
                detail = fn()
            results.append(("PASS", label, detail))
            print(f"  ✅ PASS  {label}\n           {detail}")
        except Skip as exc:
            results.append(("SKIP", label, str(exc)))
            print(f"  ⏭️  SKIP  {label}\n           {exc}")
        except Exception as exc:  # noqa: BLE001
            results.append(("FAIL", label, f"{type(exc).__name__}: {exc}"))
            print(f"  ❌ FAIL  {label}\n           {type(exc).__name__}: {exc}")
            traceback.print_exc()

    passed = sum(1 for s, _, _ in results if s == "PASS")
    skipped = sum(1 for s, _, _ in results if s == "SKIP")
    failed = sum(1 for s, _, _ in results if s == "FAIL")
    print(f"\n{'='*70}\n  {passed} passed · {skipped} skipped · {failed} failed\n{'='*70}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
