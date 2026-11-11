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
YEAR_RE = re.compile(r"\b(19[5-9]\d|20\d{2})\b")
BAD_TITLE = re.compile(r"\.(pdf|docx?|tex|dvi|indd)$|^untitled|microsoft word|^doi:|^pii:", re.I)


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


def guess_title_and_author(lines: list[Line]) -> tuple[str, str]:
    """Find the longest block at the largest upright page-1 font size."""
    candidates = [line for line in lines if not line.rotated and len(line.text) > 3
                  and not ARXIV_RE.match(line.text)]
    if not candidates:
        return "", ""
    largest = max(line.size for line in candidates)
    selected = [index for index, line in enumerate(lines) if line in candidates
                and abs(line.size - largest) < 0.6]
    groups = [[selected[0]]]
    for index in selected[1:]:
        previous = groups[-1][-1]
        if index == previous + 1 and lines[index].top - lines[previous].bottom < 1.5 * largest:
            groups[-1].append(index)
        else:
            groups.append([index])
    best = max(groups, key=lambda group: sum(len(lines[index].text) for index in group))
    title = " ".join(lines[index].text for index in best)
    author = ""
    for line in lines[best[-1] + 1:best[-1] + 6]:
        if (not line.rotated and len(line.text.split()) >= 2
                and re.match(r"^[A-Z][A-Za-z.\-' ]+[A-Za-z]", line.text)
                and not YEAR_RE.search(line.text)):
            author = line.text
            break
    return (title if 16 <= len(title) <= 299 else "", author)


def read_pdf(path: str | Path) -> dict:
    """Return the extraction and conservative identification hints."""
    raw_data = extract_pdf(path)
    metadata = raw_data["metadata"]
    title = str(metadata.get("Title") or "").strip()
    big_title, author_line = guess_title_and_author(raw_data["lines"])
    md_blob = " ".join(str(value) for value in metadata.values() if value)
    text = raw_data["text"]
    xmp = raw_data["xmp"]
    creation = str(metadata.get("CreationDate") or "")
    created = creation[2:6] if creation.startswith("D:") else ""
    return {
        "text": text,
        "page1": raw_data["page1"],
        "md_title": title if len(title) >= 11 and not BAD_TITLE.search(title) else "",
        "md_author": str(metadata.get("Author") or "").strip(),
        "md_dois": find_dois(md_blob, xmp),
        "big_title": big_title,
        "author_line": author_line,
        "created": created,
        "paperish": bool(DOI_RE.search(md_blob + xmp + text) or ARXIV_RE.search(text)
                         or re.search(r"\b(abstract|keywords|introduction|references)\b", text, re.I)),
    }
