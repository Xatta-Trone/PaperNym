"""Read page text and embedded metadata with pypdfium2."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path

import pypdfium2 as pdfium
import pypdfium2.raw as raw


DOI_RE = re.compile(r'\b(10\.\d{4,9}/[^\s"<>\]\[{}|\\^`,;]+)', re.I)
ARXIV_RE = re.compile(r"arxiv[:.\s/]*(\d{4}\.\d{4,5})(?:v\d+)?", re.I)
ARXIV_FILE_RE = re.compile(r"^(\d{4}\.\d{4,5})(?:v\d+)?$", re.I)
XMP_RE = re.compile(rb"<x:xmpmeta\b.*?</x:xmpmeta>", re.S)
EXTRA_KEYS = ("doi", "DOI", "arXivID")


class PdfReadError(ValueError):
    """A PDF cannot be opened or read."""


@dataclass(frozen=True)
class Line:
    size: float
    text: str
    top: float
    bottom: float
    rotated: bool


def find_dois(*texts: str) -> list[str]:
    found = []
    seen = set()
    for text in texts:
        for match in DOI_RE.finditer(text or ""):
            doi = match.group(1).rstrip(".)('").lower()
            if doi not in seen:
                seen.add(doi)
                found.append(doi)
    return found


def read_xmp(path: str | Path) -> str:
    """Read uncompressed XMP packets from a PDF file."""
    path = Path(path)
    try:
        if path.stat().st_size > 300 * 1024 * 1024:
            return ""
        return "\n".join(packet.group().decode("utf-8", "ignore")
                         for packet in XMP_RE.finditer(path.read_bytes()))
    except OSError as exc:
        raise PdfReadError(f"cannot read PDF bytes: {exc}") from exc


def page_text(page) -> str:
    textpage = page.get_textpage()
    try:
        return (textpage.get_text_range().replace("\r\n", "\n").replace("\r", "\n")
                .replace("\x02", "").replace("\ufffe", ""))
    finally:
        textpage.close()


def page_lines(page) -> list[Line]:
    """Return page text lines with effective size, position, and rotation."""
    textpage = page.get_textpage()
    lines = []
    current = []
    height = page.get_height()

    def flush():
        if not current:
            return
        text = " ".join("".join(item[0] for item in current).split())
        if text:
            size = max(item[1] for item in current)
            if size < 2:
                box_heights = sorted(item[3] - item[2] for item in current)
                size = box_heights[len(box_heights) // 2] * 1.4
            upright = sum(abs(item[4]) < 0.05 or abs(item[4] - 2 * math.pi) < 0.05
                          for item in current) > len(current) / 2
            lines.append(Line(round(size, 1), text,
                              height - max(item[3] for item in current),
                              height - min(item[2] for item in current), not upright))
        current.clear()

    try:
        for index in range(textpage.count_chars()):
            codepoint = raw.FPDFText_GetUnicode(textpage.raw, index)
            if not codepoint:
                continue
            char = chr(codepoint)
            if char in "\r\n":
                flush()
                continue
            if char in "\x02\ufffe":
                continue
            _, bottom, _, top = textpage.get_charbox(index)
            current.append((char, raw.FPDFText_GetFontSize(textpage.raw, index), bottom,
                            top, raw.FPDFText_GetCharAngle(textpage.raw, index)))
        flush()
        return lines
    finally:
        textpage.close()


def extract_pdf(path: str | Path) -> dict:
    """Extract the first two pages plus PDF properties, extra keys, and XMP."""
    path = Path(path)
    try:
        doc = pdfium.PdfDocument(str(path))
    except (pdfium.PdfiumError, OSError) as exc:
        reason = "password-protected" if "assword" in str(exc) else f"cannot open PDF ({exc})"
        raise PdfReadError(reason) from exc
    try:
        metadata = dict(doc.get_metadata_dict() or {})
        for key in EXTRA_KEYS:
            try:
                value = doc.get_metadata_value(key)
            except Exception:
                value = ""
            if value:
                metadata[key] = value
        pages = []
        lines = []
        for index in range(min(2, len(doc))):
            page = doc[index]
            try:
                pages.append(page_text(page))
                if index == 0:
                    lines = page_lines(page)
            finally:
                page.close()
        return {"text": "\n".join(pages), "page1": pages[0] if pages else "",
                "lines": sorted(lines, key=lambda line: line.top),
                "metadata": metadata, "xmp": read_xmp(path)}
    except (pdfium.PdfiumError, OSError) as exc:
        raise PdfReadError(f"cannot read PDF ({exc})") from exc
    finally:
        doc.close()
