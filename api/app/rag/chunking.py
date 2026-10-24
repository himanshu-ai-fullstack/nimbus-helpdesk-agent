"""Recursive text splitter: tries paragraph, then line, then sentence, then word
boundaries so chunks stay semantically whole, with a fixed character overlap."""

from dataclasses import dataclass

SEPARATORS = ["\n\n", "\n", ". ", " "]


@dataclass(frozen=True)
class Chunk:
    ordinal: int
    content: str


def _split(text: str, size: int, separators: list[str]) -> list[str]:
    if len(text) <= size:
        return [text]
    if not separators:
        return [text[i : i + size] for i in range(0, len(text), size)]

    sep, rest = separators[0], separators[1:]
    pieces = text.split(sep)
    if len(pieces) == 1:
        return _split(text, size, rest)

    out: list[str] = []
    buf = ""
    for piece in pieces:
        candidate = f"{buf}{sep}{piece}" if buf else piece
        if len(candidate) <= size:
            buf = candidate
            continue
        if buf:
            out.append(buf)
        if len(piece) > size:
            out.extend(_split(piece, size, rest))
            buf = ""
        else:
            buf = piece
    if buf:
        out.append(buf)
    return out


def chunk_text(text: str, size: int = 800, overlap: int = 120) -> list[Chunk]:
    if overlap >= size:
        raise ValueError("overlap must be smaller than size")
    text = text.strip()
    if not text:
        return []

    pieces = _split(text, size - overlap, SEPARATORS)
    chunks: list[Chunk] = []
    for i, piece in enumerate(pieces):
        if i > 0 and overlap:
            tail = pieces[i - 1][-overlap:]
            # Start the overlap at a word boundary so chunks don't begin mid-word.
            space = tail.find(" ")
            tail = tail[space + 1 :] if 0 <= space < len(tail) - 1 else tail
            piece = f"{tail} {piece}"
        chunks.append(Chunk(ordinal=i, content=piece.strip()))
    return chunks
