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


def test_pending_persists_across_restart(tmp_path):
    state_file = tmp_path / "cs.json"
    s = DigestScheduler(state_file)
    now = datetime(2026, 7, 23, 12, 0, 0)
    s.mark_ran(now, seen_keys={"sha256:a"}, pending=4)
    # A restart must not strand the backfill backlog: is_due() keys off the
    # counter, so it has to survive the process.
    reloaded = DigestScheduler(state_file)
    assert reloaded.new_notes == 4
    assert reloaded.is_due(now + timedelta(days=8)) is True


def test_mark_ran_merges_disk_seen_from_other_process(tmp_path):
    # Two processes (resident app + magic_digest CLI) share the state file;
    # a blind overwrite would un-see the other's consumed window.
    state_file = tmp_path / "cs.json"
    now = datetime(2026, 7, 23, 12, 0, 0)
    s1 = DigestScheduler(state_file)
    s2 = DigestScheduler(state_file)  # loaded before s1 writes
    s1.mark_ran(now, seen_keys={"sha256:a"})
    s2.mark_ran(now, seen_keys={"sha256:b"})
    assert DigestScheduler(state_file).seen_note_keys >= {"sha256:a", "sha256:b"}


def test_reset_seen_forgets_without_disk_merge(tmp_path):
    # The archive re-digest seam: reset must NOT union the old on-disk set
    # back (that is exactly what it exists to forget).
    state_file = tmp_path / "cs.json"
    now = datetime(2026, 7, 23, 12, 0, 0)
    s = DigestScheduler(state_file)
    s.mark_ran(now, seen_keys={"sha256:a", "sha256:b"})
    s.reset_seen()
    assert DigestScheduler(state_file).seen_note_keys == set()
    # Post-reset consumption tracks only what was actually re-digested.
    s.mark_ran(now, seen_keys={"sha256:c"})
    assert DigestScheduler(state_file).seen_note_keys == {"sha256:c"}


def test_reset_epoch_propagates_to_stale_process(tmp_path):
    # The resurrection bug: a resident app holding the old set in memory must
    # ADOPT a reset (higher epoch on disk), not union its stale keys back.
    state_file = tmp_path / "cs.json"
    now = datetime(2026, 7, 23, 12, 0, 0)
    s1 = DigestScheduler(state_file)
    s1.mark_ran(now, seen_keys={"sha256:a", "sha256:b"})
    app = DigestScheduler(state_file)  # "resident app": holds {a, b} in memory
    s1.reset_seen()  # CLI --reset bumps the epoch

    app.mark_ran(now, seen_keys={"sha256:c"})  # app's next paid run
    on_disk = DigestScheduler(state_file).seen_note_keys
    assert on_disk == {"sha256:c"}  # reset survived; consumed window kept


def test_refresh_from_disk_adopts_other_process_progress(tmp_path):
    # Read-path sync: without it a resident app re-pays for windows a CLI
    # already consumed.
    state_file = tmp_path / "cs.json"
    now = datetime(2026, 7, 23, 12, 0, 0)
    app = DigestScheduler(state_file)  # loaded before the CLI ran
    cli = DigestScheduler(state_file)
    cli.mark_ran(now, seen_keys={"sha256:w"})

    app.refresh_from_disk()
    assert "sha256:w" in (app.seen_note_keys or set())
    assert app.last_digest_at == now.isoformat(timespec="seconds")


def test_corrupt_seen_keys_never_break_mark_ran(tmp_path):
    # A hand-mangled state value must degrade to "merge skipped", not raise
    # out of the bookkeeping of a PAID run.
    import json as _json

    state_file = tmp_path / "cs.json"
    state_file.write_text(_json.dumps({"seen_note_keys": 123}), encoding="utf-8")
    s = DigestScheduler(state_file)  # load tolerates it
    s.mark_ran(datetime(2026, 7, 23, 12, 0, 0), seen_keys={"sha256:a"})  # no raise
    assert DigestScheduler(state_file).seen_note_keys == {"sha256:a"}


def test_enqueue_with_md_path_unsees_fingerprint(tmp_path, monkeypatch):
    # Delete-and-retranscribe: a freshly written note whose fingerprint was
    # consumed before must become digest material again.
    import json as _json

    state_file = tmp_path / "cs.json"
    state_file.write_text(
        _json.dumps({"seen_note_keys": ["sha256:x", "sha256:y"]}), encoding="utf-8"
    )
    monkeypatch.setattr(config, "CONNECTIONS_STATE_FILE", state_file)
    md = tmp_path / "note.md"
    md.write_text("---\ntitle: n\nfingerprint: sha256:x\n---\n\nbody", encoding="utf-8")
    reset_scheduler_for_tests()
    try:
        enqueue_connection_analysis(None, md_path=md)
        s = get_scheduler()
        assert s.new_notes == 1
        assert s.seen_note_keys == {"sha256:y"}
        assert DigestScheduler(state_file).seen_note_keys == {"sha256:y"}
    finally:
        reset_scheduler_for_tests()


def test_fresh_install_migration_does_not_drain_archive(tmp_path):
    # First-ever migration on a populated vault mirrors the legacy first run:
    # newest FIRST_RUN_WINDOW stay unseen, the rest is marked seen — no
    # auto-drain of the whole archive through paid weekly runs.
    from src.connections.candidate_assembly import FIRST_RUN_WINDOW
    from src.connections.scheduler import _ensure_seen_migrated

    vault = tmp_path / "vault"
    vault.mkdir()
    total = FIRST_RUN_WINDOW + 5
    for i in range(total):
        _write_vault_note(vault, f"n{i:02d}", f"2026-06-{i + 1:02d}")
    s = DigestScheduler(tmp_path / "cs.json")

    seen = _ensure_seen_migrated(s, vault)
    assert len(seen) == 5
    assert f"sha256:n{total - 1:02d}" not in seen  # newest stays unseen
    assert "sha256:n00" in seen  # oldest is out of scope, as on main


def test_migration_marks_undated_notes_seen(tmp_path):
    # The legacy date window could never select an undated note; migration
    # must not turn it into paid window material.
    from src.connections.scheduler import _ensure_seen_migrated

    vault = tmp_path / "vault"
    vault.mkdir()
    _write_vault_note(vault, "dated", "2026-07-01")
    (vault / "undated.md").write_text(
        '---\ntitle: "undated"\nfingerprint: sha256:undated\n---\n\nbody',
        encoding="utf-8",
    )
    s = DigestScheduler(tmp_path / "cs.json")
    s.last_digest_at = "2026-07-10T00:00:00"
    assert _ensure_seen_migrated(s, vault) == {"sha256:dated", "sha256:undated"}


def test_forced_run_with_nothing_unseen_regenerates_recent_window(
    tmp_path, monkeypatch
):
    """Force must regenerate over already-seen material, not silently no-op."""
    import json as _json

    import src.connections.scheduler as sched
    import src.connections.synthesis as synth_mod

    vault = tmp_path / "vault"
    vault.mkdir()
    for i in range(3):
        _write_vault_note(vault, f"n{i}", f"2026-07-0{i + 1}", tags="t")
    state_file = tmp_path / "cs.json"
    state_file.write_text(
        _json.dumps(
            {
                "last_digest_at": "2026-07-10T00:00:00",
                "seen_note_keys": [f"sha256:n{i}" for i in range(3)],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "TRANSCRIBE_DIR", vault)
    monkeypatch.setattr(config, "DIGEST_LOCK_FILE", tmp_path / "digest.lock")
    monkeypatch.setattr(config, "CONNECTIONS_STATE_FILE", state_file)
    reset_scheduler_for_tests()
    try:
        calls = []

        class _Synth:
            model = "claude-opus-4-8"
            last_usage = None

            def synthesize(self, candidates, dismissed=None, language=None):
                calls.append(len(candidates.notes))
                return None  # recoverable: run ends without state changes

        monkeypatch.setattr(synth_mod, "get_synthesizer", lambda: _Synth())
        assert sched.run_digest_if_due(transcriber=None, force=True) is None
        assert calls == [3]  # fallback window reached the paid path
    finally:
        reset_scheduler_for_tests()


def test_gate_skip_sig_stamped_only_after_successful_write(tmp_path, monkeypatch):
    """A failed/disabled telemetry write must stay retryable, not silence the
    window for the process lifetime."""
    import json as _json

    import src.connections.scheduler as sched
    import src.connections.synthesis as synth_mod

    vault = tmp_path / "vault"
    vault.mkdir()
    _write_vault_note(vault, "solo", "2026-07-22", tags="unikat", summary="osobny")
    for i in range(5):
        _write_vault_note(vault, f"old{i}", "2026-06-01", tags="ogrod")
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
    monkeypatch.setattr(config, "INSIGHT_METRICS_ENABLED", False)  # write fails
    reset_scheduler_for_tests()
    try:

        class _Synth:
            model = "claude-opus-4-8"
            last_usage = None

            def synthesize(self, *a, **kw):
                raise AssertionError("gate must skip before synthesis")

        monkeypatch.setattr(synth_mod, "get_synthesizer", lambda: _Synth())
        s = get_scheduler()
        s.register_new_notes(1)

        assert sched.run_digest_if_due(transcriber=None, force=False) is None
        assert s._gate_skip_sig is None  # NOT stamped — write did not happen

        monkeypatch.setattr(config, "INSIGHT_METRICS_ENABLED", True)
        s._gate_skip_at = None  # cooldown expiry
        assert sched.run_digest_if_due(transcriber=None, force=False) is None
        assert s._gate_skip_sig is not None  # stamped with the successful row
        rows = (
            (vault / ".timshel" / "metrics.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        )
        assert len(rows) == 1
    finally:
        reset_scheduler_for_tests()


def test_stale_counter_cleared_when_nothing_unseen(tmp_path, monkeypatch):
    """new_notes > 0 with zero unseen notes must self-heal, not loop forever."""
    import json as _json

    import src.connections.scheduler as sched
    import src.connections.synthesis as synth_mod

    vault = tmp_path / "vault"
    vault.mkdir()
    for i in range(3):
        _write_vault_note(vault, f"old{i}", "2026-06-01")
    state_file = tmp_path / "cs.json"
    state_file.write_text(
        _json.dumps(
            {
                "last_digest_at": "2026-07-10T00:00:00",
                "seen_note_keys": [f"sha256:old{i}" for i in range(3)],
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

        class _Synth:
            model = "claude-opus-4-8"
            last_usage = None

            def synthesize(self, *a, **kw):
                raise AssertionError("must not synthesize with an empty window")

        monkeypatch.setattr(synth_mod, "get_synthesizer", lambda: _Synth())
        s = get_scheduler()
        s.register_new_notes(1)  # phantom: the material is already seen

        assert sched.run_digest_if_due(transcriber=None, force=False) is None
        assert s.new_notes == 0  # counter cleared, no hourly re-scan loop
        assert not (vault / ".timshel" / "metrics.jsonl").exists()  # no spam
    finally:
        reset_scheduler_for_tests()


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
    _write_vault_note(
        vault, "solo", "2026-07-22", tags="unikat", summary="zupelnie osobny watek"
    )
    for i in range(5):
        _write_vault_note(
            vault,
            f"old{i}",
            "2026-06-01",
            tags="ogrod",
            summary="rosliny nawozy podlewanie",
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

        # Cooldown expiry re-skips the SAME window: no second telemetry row
        # (one record per distinct skipped window, not one per hour).
        s._gate_skip_at = None
        assert sched.run_digest_if_due(transcriber=None, force=False) is None
        rows_after = (
            (vault / ".timshel" / "metrics.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        )
        assert len(rows_after) == len(rows)
    finally:
        reset_scheduler_for_tests()
