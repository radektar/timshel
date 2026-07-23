"""Unit tests for the digest scheduler (no API)."""

from datetime import datetime, timedelta
from pathlib import Path

from src.config import config
from src.connections.scheduler import (
    DigestScheduler,
    enqueue_connection_analysis,
    get_scheduler,
    reset_scheduler_for_tests,
)


def test_is_due_truth_table(tmp_path):
    s = DigestScheduler(tmp_path / "cs.json")
    now = datetime(2026, 6, 23, 12, 0, 0)

    assert s.is_due(now) is False  # no new material
    s.register_new_notes(1)
    assert s.is_due(now) is True  # first run with material
    s.mark_ran(now)
    assert s.is_due(now) is False  # just ran, counter reset

    s.register_new_notes(1)
    s.last_digest_at = (now - timedelta(days=8)).isoformat(timespec="seconds")
    assert s.is_due(now) is True  # weekly cadence elapsed

    s.mark_ran(now)
    s.register_new_notes(6)
    s.last_digest_at = (now - timedelta(days=3)).isoformat(timespec="seconds")
    assert s.is_due(now) is True  # pattern-trigger (>=6 new, >=2 days)

    s.mark_ran(now)
    s.register_new_notes(2)
    s.last_digest_at = (now - timedelta(days=1)).isoformat(timespec="seconds")
    assert s.is_due(now) is False  # below pattern + below weekly + min-gap


def test_mark_ran_persists_and_resets(tmp_path):
    state_file = tmp_path / "cs.json"
    sched = DigestScheduler(state_file)
    sched.register_new_notes(3)
    now = datetime(2026, 6, 23, 12, 0, 0)
    sched.mark_ran(now, Path("/x/digest.md"))
    assert sched.new_notes == 0

    reloaded = DigestScheduler(state_file)
    assert reloaded.last_digest_at == now.isoformat(timespec="seconds")
    assert reloaded.last_digest_path == "/x/digest.md"


def test_enqueue_increments_singleton(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CONNECTIONS_STATE_FILE", tmp_path / "cs.json")
    reset_scheduler_for_tests()
    try:
        enqueue_connection_analysis(None)
        enqueue_connection_analysis(None)
        assert get_scheduler().new_notes == 2
    finally:
        reset_scheduler_for_tests()


def test_seen_keys_persist_and_accumulate(tmp_path):
    state_file = tmp_path / "cs.json"
    s = DigestScheduler(state_file)
    assert s.seen_note_keys is None  # pre-migration marker
    now = datetime(2026, 7, 23, 12, 0, 0)
    s.mark_ran(now, seen_keys={"sha256:a", "sha256:b"}, pending=3)
    assert s.new_notes == 3  # backfill leftover keeps the cadence firing
    # A big backlog is clamped below the pattern trigger: it must drain on the
    # weekly cadence, never escalate to the every-2-days one by itself.
    s.mark_ran(now, seen_keys=set(), pending=100)
    assert s.new_notes == config.CONNECTIONS_PATTERN_TRIGGER_MIN - 1
    s.mark_ran(now, seen_keys={"sha256:c"})
    assert s.new_notes == 0

    reloaded = DigestScheduler(state_file)
    assert reloaded.seen_note_keys == {"sha256:a", "sha256:b", "sha256:c"}


def test_init_seen_persists_empty_set_as_migrated(tmp_path):
    state_file = tmp_path / "cs.json"
    s = DigestScheduler(state_file)
    s.init_seen(set())
    reloaded = DigestScheduler(state_file)
    assert reloaded.seen_note_keys == set()  # empty, but no longer None


def test_gate_cooldown_and_reset_on_new_note(tmp_path):
    s = DigestScheduler(tmp_path / "cs.json")
    now = datetime(2026, 7, 23, 12, 0, 0)
    assert s.gate_cooldown_active(now) is False
    s.note_gate_skip(now)
    assert s.gate_cooldown_active(now + timedelta(minutes=30)) is True
    assert s.gate_cooldown_active(now + timedelta(minutes=61)) is False
    s.note_gate_skip(now)
    s.register_new_notes(1)  # fresh material re-opens the gate
    assert s.gate_cooldown_active(now + timedelta(minutes=1)) is False


def test_digest_potential_truth_table():
    from src.connections.candidate_assembly import CandidateSet, NoteRef
    from src.connections.scheduler import digest_potential

    def _cs(window_n, strong_n, bm25_only_n=0):
        def _note(name):
            return NoteRef(
                md_path=Path(f"/x/{name}.md"),
                basename=name,
                title=name,
                date="2026-07-01",
                tags=[],
                norm_tags=set(),
                summary_md="text",
                fingerprint=f"sha256:{name}",
            )

        window = [_note(f"w{i}") for i in range(window_n)]
        strong = [_note(f"s{i}") for i in range(strong_n)]
        weak = [_note(f"b{i}") for i in range(bm25_only_n)]
        channel_map = {n.basename: {"window"} for n in window}
        channel_map |= {n.basename: {"tag", "bm25"} for n in strong}
        channel_map |= {n.basename: {"bm25"} for n in weak}
        return CandidateSet(
            window + strong + weak,
            {n.basename for n in window},
            channel_map=channel_map,
        )

    assert digest_potential(_cs(0, 5)).ok is False  # nothing new at all
    assert digest_potential(_cs(1, 0)).ok is False  # lone unconnected note
    assert digest_potential(_cs(1, 1)).ok is False  # below neighbour floor
    assert digest_potential(_cs(1, 2)).ok is True  # one note, enough archive
    assert digest_potential(_cs(2, 0)).ok is True  # window connects itself
    # bm25-only neighbours are noise (shared section headers), not evidence.
    assert digest_potential(_cs(1, 0, bm25_only_n=9)).ok is False
    assert digest_potential(_cs(1, 0, bm25_only_n=9)).neighbors == 0


def _write_vault_note(vault, name, date, tags="", summary="tekst"):
    (vault / f"{name}.md").write_text(
        f'---\ntitle: "{name}"\ndate: {date}\ntags: [{tags}]\n'
        f"fingerprint: sha256:{name}\n---\n\n"
        f"## Podsumowanie\n{summary}\n\n## Transkrypcja\nfoo\n",
        encoding="utf-8",
    )


def test_seen_migration_seeds_from_dates(tmp_path, monkeypatch):
    from src.connections.scheduler import _ensure_seen_migrated

    vault = tmp_path / "vault"
    vault.mkdir()
    _write_vault_note(vault, "old", "2026-07-01")
    _write_vault_note(vault, "fresh", "2026-07-20")
    s = DigestScheduler(tmp_path / "cs.json")
    s.last_digest_at = "2026-07-10T00:00:00"

    seen = _ensure_seen_migrated(s, vault)
    assert seen == {"sha256:old"}
    # Idempotent: a second call must not re-scan or reset.
    s.seen_note_keys.add("sha256:extra")
    assert "sha256:extra" in _ensure_seen_migrated(s, vault)


def test_gate_skips_unforced_low_potential_run(tmp_path, monkeypatch):
    """A lone unconnected note must not trigger a paid synthesis call."""
    import json as _json

    import src.connections.scheduler as sched
    import src.connections.synthesis as synth_mod

    vault = tmp_path / "vault"
    vault.mkdir()
    # One unseen note with vocabulary/tags unrelated to the seen archive.
    _write_vault_note(vault, "solo", "2026-07-22", tags="unikat", summary="zupelnie osobny watek")
    for i in range(5):
        _write_vault_note(
            vault, f"old{i}", "2026-06-01", tags="ogrod", summary="rosliny nawozy podlewanie"
        )
    state_file = tmp_path / "cs.json"
    state_file.write_text(
        _json.dumps(
            {
                "last_digest_at": "2026-07-10T00:00:00",
                "seen_note_keys": [f"sha256:old{i}" for i in range(5)],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "TRANSCRIBE_DIR", vault)
    monkeypatch.setattr(config, "DIGEST_LOCK_FILE", tmp_path / "digest.lock")
    monkeypatch.setattr(config, "CONNECTIONS_STATE_FILE", state_file)
    monkeypatch.setattr(config, "INSIGHT_METRICS_ENABLED", True)
    reset_scheduler_for_tests()
    try:

        class _MustNotSynthesize:
            model = "claude-opus-4-8"
            last_usage = None

            def synthesize(self, *a, **kw):
                raise AssertionError("gate failed: paid synthesis was called")

        monkeypatch.setattr(synth_mod, "get_synthesizer", lambda: _MustNotSynthesize())
        s = get_scheduler()
        s.register_new_notes(1)

        assert sched.run_digest_if_due(transcriber=None, force=False) is None
        assert s.gate_cooldown_active(datetime.now()) is True
        assert s.last_digest_at == "2026-07-10T00:00:00"  # clock NOT advanced
        assert "sha256:solo" not in s.seen_note_keys  # material stays pending

        rows = [
            _json.loads(line)
            for line in (vault / ".timshel" / "metrics.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        ]
        assert rows[-1]["kind"] == "gate-skip"
        assert rows[-1]["cost_usd"] == 0.0
        assert rows[-1]["window"] == 1
    finally:
        reset_scheduler_for_tests()
