"""Turn uploaded files and fetched pages into titled pages of plain text."""

import io
import re
from dataclasses import dataclass
from pathlib import PurePath

from bs4 import BeautifulSoup
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from ..rag.store import Page

SUPPORTED = {".md", ".markdown", ".txt", ".pdf", ".html", ".htm"}


class UnsupportedDocument(ValueError):
    pass


@dataclass
class Parsed:
    title: str
    pages: list[Page]
    kind: str


def _title_from_name(filename: str) -> str:
    stem = PurePath(filename).stem
    return re.sub(r"[-_]+", " ", stem).strip().capitalize() or "Untitled"


def _decode(data: bytes) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as e:
        raise UnsupportedDocument("text files must be UTF-8") from e


def parse_text(data: bytes, filename: str) -> Parsed:
    text = _decode(data).replace("\r\n", "\n").strip()
    first = text.splitlines()[0] if text else ""
    title = first.lstrip("# ").strip() if first.startswith("#") else _title_from_name(filename)
    return Parsed(title=title[:200], pages=[Page(text)], kind="upload")


def parse_pdf(data: bytes, filename: str) -> Parsed:
    try:
        reader = PdfReader(io.BytesIO(data))
        pages = [
            Page(text=(page.extract_text() or "").strip(), number=i + 1)
            for i, page in enumerate(reader.pages)
        ]
        meta_title = (reader.metadata.title if reader.metadata else None) or ""
    except PdfReadError as e:
        raise UnsupportedDocument(f"couldn't read this PDF: {e}") from e
    pages = [p for p in pages if p.text]
    if not pages:
        # Scanned PDFs have no text layer; OCR is out of scope here.
        raise UnsupportedDocument("this PDF has no extractable text (is it a scan?)")
    title = meta_title.strip() or _title_from_name(filename)
    return Parsed(title=title[:200], pages=pages, kind="upload")


def parse_html(data: bytes, source: str) -> Parsed:
    soup = BeautifulSoup(data, "html.parser")
    for tag in soup(["script", "style", "noscript", "nav", "header", "footer", "aside", "form"]):
        tag.decompose()
    title = ""
    if soup.title and soup.title.string:
        title = soup.title.string.strip()
    elif soup.h1:
        title = soup.h1.get_text(" ", strip=True)
    main = soup.find("main") or soup.find("article") or soup.body or soup
    text = main.get_text("\n", strip=True)
    text = re.sub(r"\n{3,}", "\n\n", text)
    if not text:
        raise UnsupportedDocument("no readable text on this page")
    return Parsed(title=(title or source)[:200], pages=[Page(text)], kind="web")


def parse_upload(filename: str, data: bytes) -> Parsed:
    suffix = PurePath(filename).suffix.lower()
    if suffix not in SUPPORTED:
        raise UnsupportedDocument(
            f"unsupported file type {suffix or '(none)'}; use " + ", ".join(sorted(SUPPORTED))
        )
    if suffix == ".pdf":
        return parse_pdf(data, filename)
    if suffix in (".html", ".htm"):
        return parse_html(data, filename)
    return parse_text(data, filename)
