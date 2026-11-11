#!/usr/bin/env python3
"""
compare_sources.py - for every PDF, show what EACH metadata source returns. Renames nothing.

Keep it next to paper_renamer.py, then:
    python compare_sources.py                 # all folders set up in the renamer
    python compare_sources.py "F:/some folder"  # or a specific folder

The same report is saved as api_report.txt in the current folder.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import paper_renamer as pr

cfg = pr.load_config()
lines = []


def out(s=""):
    print(s)
    lines.append(s)


INFO = {}


def ask(fn, arg, is_list=False, want_title=None):
    """Return (meta or None, note)."""
    if fn.__name__.startswith("openalex") and not cfg.get("openalex_key"):
        return None, "skipped (no key)"
    if fn.__name__.startswith("s2"):
        time.sleep(1.2)                        # keyless Semantic Scholar is easily rate limited
    for attempt in range(2):
        try:
            r = fn(arg, cfg)
            break
        except pr.NetError as e:
            if "429" in str(e) and attempt == 0:
                time.sleep(5)
                continue
            return None, f"ERROR {e}"
    if is_list:
        r = next((m for m in r or [] if pr.title_hit_ok(m, want_title, INFO)), None)
    return (r, "") if r else (None, "not found")


def show(label, meta, note, ref):
    if not meta:
        out(f"    {label:26} {note}")
        return ref
    author = (meta["authors"] or ["Unknown"])[0]
    yo = meta.get("year_online")
    flag = ""
    if ref and (meta["year"] != ref["year"] or pr.norm(author) != pr.norm((ref["authors"] or ["Unknown"])[0])):
        flag = "   <-- differs"
    yrs = f"{meta['year'] or 'nd'}" + (f" (online {yo})" if yo and yo != meta["year"] else "")
    out(f"    {label:26} {yrs} | {author} | {meta['title'][:60]}{flag}")
    return ref or meta


def report(path: Path):
    out("=" * 100)
    out(path.name)
    try:
        info = pr.read_pdf(path)
    except Exception as e:
        out(f"    cannot read PDF: {e}")
        return
    INFO.clear(); INFO.update(info)
    md = [d.lower() for d in info["md_dois"]]
    dois = (info["md_dois"] + [d for d in pr.find_dois(info["text"]) if d.lower() not in md])[:6]
    am = pr.ARXIV_RE.search(info["text"]) or pr.ARXIV_FILE_RE.match(path.stem)
    title = info["big_title"] or info["md_title"]
    out(f"  Found in PDF  DOI: {dois[0] if dois else '-'}" + (f" (+{len(dois) - 1} more)" if len(dois) > 1 else "")
        + f"   arXiv: {am.group(1) if am else '-'}")
    out(f"                title on page 1: {title[:80] or '-'}")
    out(f"                PDF properties author: {info['md_author'] or '-'}   |   author line on page 1: {info['author_line'] or '-'}")
    ref = None

    # pick the DOI that really belongs to this paper (not one from the reference list)
    doi = None
    for d in dois:
        m, _ = ask(pr.crossref_doi, d)
        if m is None:
            m, _ = ask(pr.doiorg_doi, d)
        if m and (pr.title_in_text(m["title"], info["text"]) or len(info["text"]) < 200):
            doi = d
            break
    if dois and not doi:
        out("  No DOI in the PDF matched this paper's own title.")
    if doi:
        out(f"  By DOI {doi}")
        for label, fn in (("Crossref", pr.crossref_doi), ("doi.org", pr.doiorg_doi),
                          ("OpenAlex", pr.openalex_doi), ("Semantic Scholar", pr.s2_doi)):
            ref = show(label, *ask(fn, doi), ref)
    if am:
        out(f"  By arXiv ID {am.group(1)}")
        for label, fn in (("arXiv", pr.arxiv_id), ("Semantic Scholar", pr.s2_arxiv)):
            ref = show(label, *ask(fn, am.group(1)), ref)
    if title:
        out("  By title search")
        for label, fn in (("Crossref", pr.crossref_title), ("OpenAlex", pr.openalex_title),
                          ("Semantic Scholar", pr.s2_title)):
            ref = show(label, *ask(fn, title, True, title), ref)
    off = pr.identify_offline(info)
    out("  From the PDF alone (offline fallback)")
    show("PDF-only guess", off, "no usable title", None)


folders = [Path(a) for a in sys.argv[1:]] or [Path(f["path"]) for f in cfg["folders"]]
if not folders:
    sys.exit('No folder given and none set up. Usage: python compare_sources.py "FOLDER"')
pdfs = sorted(p for f in folders for p in f.rglob("*") if p.suffix.lower() == ".pdf")
out(f"{len(pdfs)} PDF(s). Each line: citation year (online year if different) | first author | title.  '<-- differs' = year or author differs from the first source.")
for p in pdfs:
    report(p)
Path("api_report.txt").write_text("\n".join(lines), encoding="utf-8")
print("\nSaved to api_report.txt")
