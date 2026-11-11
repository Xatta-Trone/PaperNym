import pytest

from papernym.core import pdfread
from papernym.core.pdfread import PdfReadError, extract_pdf, find_dois, read_pdf, read_xmp

from .pdf_factory import make_pdf


def test_two_pages_layout_properties_extra_keys_and_xmp(tmp_path):
    path = make_pdf(tmp_path / "paper.pdf", [
        [("A research title", 20, 70, 700, False), ("Rotated stamp", 9, 30, 400, True)],
        [("Second page text", 10, 70, 700, False)],
        [("Third page must not be read", 10, 70, 700, False)],
    ], {"Title": "Metadata title", "Author": "Alice Smith", "DOI": "10.1234/EXTRA"},
        "<x:xmpmeta>10.5678/xmp</x:xmpmeta>")
    data = extract_pdf(path)
    assert "A research title" in data["page1"]
    assert "Second page text" in data["text"]
    assert "Third page" not in data["text"]
    assert data["metadata"]["Title"] == "Metadata title"
    assert data["metadata"]["DOI"] == "10.1234/EXTRA"
    assert "10.5678/xmp" in data["xmp"]
    title = next(line for line in data["lines"] if "A research" in line.text)
    stamp = next(line for line in data["lines"] if "Rotated" in line.text)
    assert title.size == 20
    assert title.top < title.bottom
    assert not title.rotated
    assert stamp.rotated


def test_doi_cleanup_and_xmp_read(tmp_path):
    path = make_pdf(tmp_path / "x.pdf", [[]], xmp="<x:xmpmeta>doi:10.1000/ABC.</x:xmpmeta>")
    assert find_dois("10.1000/ABC.", "10.1000/abc") == ["10.1000/abc"]
    assert "10.1000/ABC" in read_xmp(path)


def test_title_block_author_and_paperish(tmp_path):
    path = make_pdf(tmp_path / "paper.pdf", [[
        ("Journal of Big Studies", 22, 70, 750, False),
        ("A detailed study of", 22, 70, 690, False),
        ("road crash severity", 22, 70, 666, False),
        ("Alice Smith and Bob Jones", 12, 70, 635, False),
        ("Abstract This paper studies crashes", 9, 70, 600, False),
        ("arXiv:1706.03762", 45, 30, 400, True),
    ]], {"Title": "microsoft word", "Author": "Alice Smith", "CreationDate": "D:20241101120000",
         "doi": "10.1234/META"})
    data = read_pdf(path)
    assert data["big_title"] == "A detailed study of road crash severity"
    assert data["author_line"] == "Alice Smith and Bob Jones"
    assert data["md_title"] == ""
    assert data["md_dois"] == ["10.1234/meta"]
    assert data["created"] == "2024"
    assert data["paperish"]


def test_xmp_only_doi_and_blank_pdf(tmp_path):
    xmp_path = make_pdf(tmp_path / "xmp.pdf", [[("Some paper title text", 18, 70, 700, False)]],
                        xmp="<x:xmpmeta>10.4444/XMP</x:xmpmeta>")
    assert read_pdf(xmp_path)["md_dois"] == ["10.4444/xmp"]
    blank = make_pdf(tmp_path / "blank.pdf", [[]])
    info = read_pdf(blank)
    assert info["text"] == ""
    assert info["big_title"] == ""
    assert not info["paperish"]


def test_corrupt_pdf_raises_clear_error(tmp_path):
    path = tmp_path / "broken.pdf"
    path.write_bytes(b"not a PDF")
    with pytest.raises(PdfReadError, match="cannot open PDF"):
        read_pdf(path)


def test_password_failure_is_classified(tmp_path, monkeypatch):
    def encrypted(_path):
        raise pdfread.pdfium.PdfiumError("Password required")

    monkeypatch.setattr(pdfread.pdfium, "PdfDocument", encrypted)
    with pytest.raises(PdfReadError, match="password-protected"):
        read_pdf(tmp_path / "encrypted.pdf")
