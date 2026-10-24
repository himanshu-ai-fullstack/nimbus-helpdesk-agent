from itertools import pairwise

import pytest

from app.rag.chunking import chunk_text


def test_empty_text_gives_no_chunks():
    assert chunk_text("   ") == []


def test_short_text_is_one_chunk():
    [c] = chunk_text("hello world")
    assert c.ordinal == 0 and c.content == "hello world"


def test_chunks_respect_size_and_overlap():
    text = "\n\n".join(f"Paragraph {i}. " + "word " * 60 for i in range(10))
    chunks = chunk_text(text, size=400, overlap=50)
    assert len(chunks) > 1
    assert all(len(c.content) <= 400 for c in chunks)
    assert [c.ordinal for c in chunks] == list(range(len(chunks)))
    # each chunk after the first starts with the tail of the previous one
    for prev, cur in pairwise(chunks):
        assert cur.content.split()[0] in prev.content


def test_long_word_is_hard_split():
    chunks = chunk_text("x" * 1000, size=300, overlap=0)
    assert all(len(c.content) <= 300 for c in chunks)
    assert "".join(c.content for c in chunks) == "x" * 1000


def test_overlap_must_be_smaller_than_size():
    with pytest.raises(ValueError):
        chunk_text("abc", size=10, overlap=10)
