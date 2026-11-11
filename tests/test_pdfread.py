from papernym.core.pdfread import extract_pdf, find_dois, read_xmp

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
