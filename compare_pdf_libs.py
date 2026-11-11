#!/usr/bin/env python3
"""
compare_pdf_libs.py - compare free PDF libraries on the three things PaperNym needs:
    1. the DOI / arXiv ID   2. a title guess from page-1 font sizes   3. embedded author/title

Libraries:  pdfminer.six (MIT)   pypdf (BSD-3)   pypdfium2 (Apache-2.0 / BSD-3)
Baseline:   PyMuPDF (AGPL) - used only as the reference if it is installed.

Install:    pip install pdfminer.six pypdf pypdfium2
Run:        python compare_pdf_libs.py "F:/New folder (4)"
Output:     per-file table, a summary, and pdf_lib_report.txt in the current folder.
Reads only; nothing is renamed or changed.
"""
import math
import re
import sys
import time
import unicodedata
from pathlib import Path

DOI_RE = re.compile(r"\b(10\.\d{4,9}/[^\s\"<>\]\[{}|\\^`,;]+)", re.I)
ARXIV_RE = re.compile(r"arxiv[:.\s/]*(\d{4}\.\d{4,5})(?:v\d+)?", re.I)
PAGES = 2


# ------------------------------------------------------------------ shared logic
def norm(s):
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", s)).strip()


def first_doi(*texts):
    for t in texts:
        m = DOI_RE.search(t or "")
        if m:
            return m.group(1).rstrip(".)('").lower()
    return ""


def xmp_from_file(path):
    """XMP metadata is normally stored uncompressed, so it can be read straight from the file."""
    data = Path(path).read_bytes()
    out = []
    for m in re.finditer(rb"<x:xmpmeta.*?</x:xmpmeta>", data, re.S):
        out.append(m.group(0).decode("utf-8", "ignore"))
    return "\n".join(out)


def title_guess(lines):
    """lines: [(font_size, text, top, bottom, upright)] for page 1, top measured from the page top."""
    lines = [(round(s, 1), " ".join(t.split()), y0, y1) for s, t, y0, y1, up in lines if up and t.strip()]
    lines.sort(key=lambda x: x[2])
    cand = [l for l in lines if len(l[1]) > 3 and not ARXIV_RE.match(l[1])]
    if not cand:
        return ""
    top = max(l[0] for l in cand)
    idx = [i for i, l in enumerate(lines) if abs(l[0] - top) < 0.6 and not ARXIV_RE.match(l[1])]
    groups = [[idx[0]]]
    for i in idx[1:]:
        prev = groups[-1][-1]
        if i == prev + 1 and lines[i][2] - lines[prev][3] < 1.5 * top:
            groups[-1].append(i)
        else:
            groups.append([i])
    best = max(groups, key=lambda g: sum(len(lines[i][1]) for i in g))
    title = " ".join(lines[i][1] for i in best)
    return title if 15 < len(title) < 300 else ""


def summarise(text, md_blob, md_title, md_author, lines, xmp=""):
    return {"doi_meta": first_doi(md_blob, xmp), "doi_text": first_doi(text),
            "doi": first_doi(md_blob, xmp, text),
            "arxiv": (ARXIV_RE.search(text or "") or [None, ""])[1],
            "title": title_guess(lines), "md_title": (md_title or "").strip(),
            "md_author": (md_author or "").strip(), "chars": len(text or "")}


# ------------------------------------------------------------------ backends
def with_pymupdf(path):
    import pymupdf
    doc = pymupdf.open(path)
    try:
        md = doc.metadata or {}
        text = "\n".join(doc[i].get_text() for i in range(min(PAGES, len(doc))))
        lines = []
        if len(doc):
            for b in doc[0].get_text("dict")["blocks"]:
                for ln in b.get("lines", []):
                    t = " ".join(s["text"] for s in ln["spans"])
                    if t.strip():
                        lines.append((max(s["size"] for s in ln["spans"]), t, ln["bbox"][1], ln["bbox"][3],
                                      abs(ln.get("dir", (1, 0))[0] - 1) < 0.01))
        return summarise(text, " ".join(str(v) for v in md.values() if v), md.get("title"), md.get("author"),
                         lines, doc.get_xml_metadata() or "")
    finally:
        doc.close()


def with_pdfminer(path):
    from pdfminer.high_level import extract_pages
    from pdfminer.layout import LAParams, LTChar, LTTextContainer, LTTextLine
    from pdfminer.pdfdocument import PDFDocument
    from pdfminer.pdfparser import PDFParser
    from pdfminer.pdftypes import resolve1
    from pdfminer.utils import decode_text

    def dec(v):
        v = resolve1(v)
        return decode_text(v) if isinstance(v, bytes) else str(v or "")

    with open(path, "rb") as f:
        info = {}
        for d in PDFDocument(PDFParser(f)).info:
            for k, v in d.items():
                try:
                    info[k] = dec(v)
                except Exception:
                    pass
    text, lines = [], []
    # detect_vertical is required: without it the rotated arXiv side stamp is read one letter per line
    for pno, page in enumerate(extract_pages(str(path), maxpages=PAGES, laparams=LAParams(detect_vertical=True))):
        for el in page:
            if not isinstance(el, LTTextContainer):
                continue
            text.append(el.get_text())
            if pno:
                continue
            for ln in el:
                if not isinstance(ln, LTTextLine):
                    continue
                chars = [c for c in ln if isinstance(c, LTChar)]
                if chars:
                    lines.append((max(c.size for c in chars), ln.get_text(), page.height - ln.y1, page.height - ln.y0,
                                  sum(c.upright for c in chars) > len(chars) / 2))
    return summarise("".join(text), " ".join(info.values()), info.get("Title"), info.get("Author"), lines,
                     xmp_from_file(path))


def with_pypdf(path):
    from pypdf import PdfReader
    reader = PdfReader(str(path))
    if reader.is_encrypted:
        reader.decrypt("")
    md = reader.metadata or {}
    blob = " ".join(str(v) for v in md.values() if v)
    text, chunks = [], []
    for pno in range(min(PAGES, len(reader.pages))):
        page = reader.pages[pno]
        height = float(page.mediabox.height)

        def visit(t, cm, tm, font, size, pno=pno, height=height):
            if pno or not t.strip():
                return
            b = tm[0] * cm[1] + tm[1] * cm[3]
            c = tm[2] * cm[0] + tm[3] * cm[2]
            d = tm[2] * cm[1] + tm[3] * cm[3]
            y = tm[4] * cm[1] + tm[5] * cm[3] + cm[5]
            eff = (size or 0) * math.hypot(c, d)
            chunks.append((eff, t, height - y - eff, height - y, abs(b) < 0.01))

        text.append(page.extract_text(visitor_text=visit) or "")
    lines = []                                             # merge chunks that sit on the same baseline
    for eff, t, y0, y1, up in sorted(chunks, key=lambda x: x[3]):
        if lines and abs(lines[-1][3] - y1) < 2 and lines[-1][4] == up:
            p = lines[-1]
            lines[-1] = (max(p[0], eff), p[1] + t, min(p[2], y0), p[3], up)
        else:
            lines.append((eff, t, y0, y1, up))
    try:
        xmp = xmp_from_file(path)
    except Exception:
        xmp = ""
    return summarise("\n".join(text), blob, md.get("/Title"), md.get("/Author"), lines, xmp)


def with_pypdfium2(path):
    import pypdfium2 as pdfium
    import pypdfium2.raw as raw
    pdf = pdfium.PdfDocument(str(path))
    try:
        md = pdf.get_metadata_dict()                       # standard keys only
        for key in ("doi", "DOI", "arXivID"):              # publishers also use non-standard keys
            try:
                v = pdf.get_metadata_value(key)
            except Exception:
                v = ""
            if v:
                md[key] = v
        text, lines = [], []
        for pno in range(min(PAGES, len(pdf))):
            page = pdf[pno]
            tp = page.get_textpage()
            text.append(tp.get_text_range())
            if pno == 0:
                height = page.get_height()
                cur = []                                   # (char, size, bottom, top, angle)

                def flush():
                    if not cur:
                        return
                    s = "".join(c[0] for c in cur)
                    size = max(c[1] for c in cur)
                    boxh = sorted(c[3] - c[2] for c in cur)[len(cur) // 2]
                    if size < 2:                           # font size hidden in the text matrix: use glyph height
                        size = boxh * 1.4
                    up = sum(abs(c[4]) < 0.05 or abs(c[4] - 2 * math.pi) < 0.05 for c in cur) > len(cur) / 2
                    lines.append((size, s, height - max(c[3] for c in cur), height - min(c[2] for c in cur), up))
                    cur.clear()

                for i in range(tp.count_chars()):
                    ch = chr(raw.FPDFText_GetUnicode(tp.raw, i))
                    if ch in "\r\n":
                        flush()
                        continue
                    l, b, r, t = tp.get_charbox(i)
                    cur.append((ch, raw.FPDFText_GetFontSize(tp.raw, i), b, t, raw.FPDFText_GetCharAngle(tp.raw, i)))
                flush()
            tp.close()
            page.close()
        return summarise("\n".join(text), " ".join(str(v) for v in md.values() if v), md.get("Title"),
                         md.get("Author"), lines, xmp_from_file(path))
    finally:
        pdf.close()


BACKENDS = [("PyMuPDF (baseline)", with_pymupdf), ("pdfminer.six", with_pdfminer),
            ("pypdf", with_pypdf), ("pypdfium2", with_pypdfium2)]


# ------------------------------------------------------------------ run
def main():
    if len(sys.argv) < 2:
        sys.exit('Usage: python compare_pdf_libs.py "FOLDER"')
    pdfs = sorted(p for a in sys.argv[1:] for p in Path(a).rglob("*") if p.suffix.lower() == ".pdf")
    out = []

    try:
        sys.stdout.reconfigure(errors="replace")          # odd characters must not crash the report
    except Exception:
        pass

    def say(s=""):
        s = s.encode("utf-8", "replace").decode("utf-8")
        print(s)
        out.append(s)

    usable = []
    for name, fn in BACKENDS:
        try:
            __import__({"PyMuPDF (baseline)": "pymupdf", "pdfminer.six": "pdfminer", "pypdf": "pypdf",
                        "pypdfium2": "pypdfium2"}[name])
            usable.append((name, fn))
        except ImportError:
            say(f"(not installed, skipped: {name})")
    has_base = usable and usable[0][0].startswith("PyMuPDF")
    stats = {n: {"doi": 0, "doi_ok": 0, "title": 0, "title_ok": 0, "author": 0, "errors": 0, "secs": 0.0} for n, _ in usable}

    say(f"{len(pdfs)} PDF(s).  '=' same as baseline, 'x' differs, '-' nothing found")
    for p in pdfs:
        say("=" * 110)
        say(p.name)
        base = None
        for name, fn in usable:
            t0 = time.time()
            try:
                r = fn(p)
            except Exception as e:
                stats[name]["errors"] += 1
                say(f"  {name:20} ERROR {type(e).__name__}: {str(e)[:70]}")
                continue
            secs = time.time() - t0
            st = stats[name]
            st["secs"] += secs
            if has_base and base is None and name.startswith("PyMuPDF"):
                base = r
            ident = r["doi"] or (("arxiv:" + r["arxiv"]) if r["arxiv"] else "")
            st["doi"] += bool(ident)
            st["title"] += bool(r["title"])
            st["author"] += bool(r["md_author"])
            dm = tm = " "
            if base is not None and r is not base:
                bident = base["doi"] or (("arxiv:" + base["arxiv"]) if base["arxiv"] else "")
                dm = "-" if not ident else ("=" if ident == bident else "x")
                tm = "-" if not r["title"] else ("=" if norm(r["title"]) == norm(base["title"]) else "x")
                st["doi_ok"] += dm == "="
                st["title_ok"] += tm == "="
            src = "meta" if r["doi_meta"] else ("text" if r["doi_text"] else ("text" if r["arxiv"] else ""))
            say(f"  {name:20} {secs:5.2f}s  id {dm} {ident or '-':34} ({src or '-':4})  author: {r['md_author'][:22] or '-'}")
            say(f"  {'':20}         title {tm} {r['title'][:78] or '-'}")

    say("=" * 110)
    say("SUMMARY" + (f"  (agreement is measured against PyMuPDF on {len(pdfs)} files)" if has_base else ""))
    say(f"  {'library':20} {'ID found':>9} {'ID = base':>10} {'title found':>12} {'title = base':>13} {'author':>7} {'errors':>7} {'time':>8}")
    for name, _ in usable:
        s = stats[name]
        b = name.startswith("PyMuPDF") or not has_base
        say(f"  {name:20} {s['doi']:>9} {'' if b else s['doi_ok']:>10} {s['title']:>12} {'' if b else s['title_ok']:>13} "
            f"{s['author']:>7} {s['errors']:>7} {s['secs']:>7.1f}s")
    Path("pdf_lib_report.txt").write_text("\n".join(out), encoding="utf-8")
    print("\nSaved to pdf_lib_report.txt")


if __name__ == "__main__":
    main()
