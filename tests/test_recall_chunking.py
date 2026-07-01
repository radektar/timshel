"""Unit tests for the recall chunker (pure, no model)."""

from __future__ import annotations

from src.connections.recall.chunking import Chunk, chunk_body, content_hash


def test_empty_body_yields_no_chunks():
    assert chunk_body("n", "") == []
    assert chunk_body("n", "   \n\n  ") == []


def test_short_body_is_one_chunk_with_exact_offsets():
    body = "To jest krótka notatka o oknach i dachu."
    chunks = chunk_body("note-1", body, target_chars=1200)
    assert len(chunks) == 1
    c = chunks[0]
    assert c.note_id == "note-1"
    assert c.seq == 0
    assert c.text == body.strip()
    # offsets index back into the original body
    assert body[c.char_start:c.char_end].strip() == c.text
    assert c.version_hash == content_hash(body)


def test_long_body_splits_with_overlap_and_increasing_seq():
    para = "Producenci okien nie odpowiadają, a bez nich dach stoi w miejscu. "
    body = "\n\n".join(para * 6 for _ in range(8))  # comfortably over target
    chunks = chunk_body("n", body, target_chars=400, overlap_chars=120)
    assert len(chunks) >= 3
    assert [c.seq for c in chunks] == list(range(len(chunks)))
    # consecutive chunks overlap: each starts before the previous ended
    for a, b in zip(chunks, chunks[1:]):
        assert b.char_start < a.char_end
    # every chunk's text is a real slice of the body
    for c in chunks:
        assert c.text and c.text in body


def test_parent_block_wraps_the_chunk():
    body = ("Alfa. " * 200) + "\n\n" + ("Beta okna dach. " * 200)
    chunks = chunk_body("n", body, target_chars=300, overlap_chars=80, parent_margin=600)
    mid = chunks[len(chunks) // 2]
    assert mid.text in mid.parent_text
    assert len(mid.parent_text) >= len(mid.text)


def test_chunk_is_frozen_dataclass():
    c = chunk_body("n", "abc def ghi")[0]
    assert isinstance(c, Chunk)
    try:
        c.seq = 5  # type: ignore[misc]
        assert False, "Chunk should be immutable"
    except Exception:
        pass


def test_snap_start_moves_off_midword():
    from src.connections.recall import chunking
    body = "abcdef ghijkl mnopqr"
    assert chunking._snap_start(body, 2) == 7   # mid 'abcdef' -> start of 'ghijkl'


def test_snap_start_is_noop_at_word_boundary():
    from src.connections.recall import chunking
    body = "abc def"
    assert chunking._snap_start(body, 0) == 0   # start of body
    assert chunking._snap_start(body, 4) == 4   # 'def' preceded by a space


def test_chunks_never_start_mid_word():
    from src.connections.recall import chunking
    body = " ".join(f"slowo{i}" for i in range(400))  # forces several overlapping chunks
    chunks = chunking.chunk_body("n", body, target_chars=200, overlap_chars=50)
    assert len(chunks) > 1
    for ch in chunks:
        assert ch.text.split()[0].startswith("slowo")  # never a fragment like "lowo12"
