#!/usr/bin/env python3
"""
paper_renamer.py - watch folders and rename paper PDFs from their metadata.
Works on Windows, macOS and Linux.   Install:  pip install pypdfium2 requests watchdog

SETUP (once)
    python paper_renamer.py add-folder "D:/Papers"              # includes subfolders
    python paper_renamer.py add-folder "D:/Inbox" --no-subfolders
    python paper_renamer.py set-key openalex YOUR_KEY           # free key: openalex.org/settings/api
    python paper_renamer.py set-email you@university.edu        # optional, polite-pool for Crossref
    python paper_renamer.py formats                             # list naming presets
    python paper_renamer.py set-title-length 0                  # 0 = keep the whole title if it fits (default); or a number
    python paper_renamer.py set-year citation                   # citation = journal volume year (default); online = first-online year
    python paper_renamer.py set-format year_author_title        # a preset name ...
    python paper_renamer.py set-format "{author}-{year}-{shorttitle}" --word-sep _   # ... or your own

RUN
    python paper_renamer.py watch              # rename new PDFs, then keep watching (Ctrl+C to stop)
    python paper_renamer.py scan               # rename new PDFs once and exit
    python paper_renamer.py scan --dry-run     # preview only, change nothing
    python paper_renamer.py reformat --dry-run # preview applying the current format to earlier renames
    python paper_renamer.py reformat           # apply it (files you renamed by hand are left alone)
    python paper_renamer.py undo               # revert the last run (or: undo --last 5)
    python paper_renamer.py show               # show settings, folders, file locations

Tokens for custom formats: {year} {author} {authors} {title} {shorttitle} {journal}

Lookup order:  DOI -> Crossref, doi.org, OpenAlex, Semantic Scholar
               arXiv ID -> arXiv, Semantic Scholar
               title -> Crossref, OpenAlex, Semantic Scholar
               no source reachable -> name built from the PDF itself, marked _CHECK, retried later
               sources say 'not found' -> file is left untouched
"""
import argparse
import csv
import datetime as dt
import difflib
import hashlib
import json
import math
import os
import queue
import re
import sys
import threading
import time
import unicodedata
import xml.etree.ElementTree as ET
from pathlib import Path

import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_raw
import requests

APP = "PaperRenamer"
PRESETS = {
    "year_author_title":       ("{year}_{author}_{title}", "_"),
    "author_year_title":       ("{author}_{year}_{title}", "_"),
    "year_author_shorttitle":  ("{year}_{author}_{shorttitle}", "_"),
    "year_author_journal_title": ("{year}_{author}_{journal}_{title}", "_"),
    "author_year_title_spaces": ("{author} ({year}) {title}", " "),
    "authors_year_title_zotero": ("{authors} - {year} - {title}", " "),
}
TOKENS = {"year", "author", "authors", "title", "shorttitle", "journal"}
DEFAULTS = {"folders": [], "format": PRESETS["year_author_title"][0], "word_sep": "_",
            "title_limit": 0, "year": "citation", "openalex_key": "", "s2_key": "", "email": ""}
MAX_ATTEMPTS = 5          # retries for files that are _CHECK / unidentified
RETRY_MINUTES = 30
THIS_YEAR = dt.date.today().year


# ------------------------------------------------------------ config / state
def app_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    d = Path(os.environ.get("PAPER_RENAMER_HOME", base / APP))
    d.mkdir(parents=True, exist_ok=True)
    return d


def _load(name, default):
    p = app_dir() / name
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            pass
    return default


def _save(name, data):
    p = app_dir() / name
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, p)


def load_config():
    cfg = dict(DEFAULTS)
    cfg.update(_load("config.json", {}))
    cfg["openalex_key"] = os.environ.get("OPENALEX_API_KEY", cfg["openalex_key"])
    return cfg


def save_config(cfg):
    _save("config.json", cfg)


HISTORY_HEAD = ["time", "old_path", "new_path", "source", "status", "batch"]


def log_rename(old: Path, new: Path, source, status, batch=""):
    p = app_dir() / "history.csv"
    if not p.exists():
        with open(p, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(HISTORY_HEAD)
    with open(p, "a", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow([dt.datetime.now().isoformat(timespec="seconds"), str(old), str(new), source, status, batch])


# ------------------------------------------------------------ filename build
def ascii_clean(s):
    return unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode()


def norm(s):
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", ascii_clean(s).lower())).strip()


def clean_field(s, sep):
    s = re.sub(r"<[^>]+>", "", str(s))                    # JATS / HTML tags in titles
    s = re.sub(r"[^A-Za-z0-9\- ]", " ", ascii_clean(s).replace("'", ""))
    return sep.join(s.split())


def cut_words(s, limit, sep):
    out = []
    for w in s.split(sep):
        if len(sep.join(out + [w])) > limit:
            break
        out.append(w)
    return sep.join(out) or s[:limit]


def last_name(full):
    full = re.sub(r"[\d*]+", "", str(full)).strip()
    if "," in full:
        return full.split(",")[0].strip()
    parts = [p for p in full.split() if p.rstrip(".").lower() not in ("jr", "sr", "ii", "iii", "phd")]
    return parts[-1] if parts else ""


NAME_MAX = 255            # longest file name allowed on Windows, macOS and Linux
WIN_PATH_MAX = 259        # longest full path (folder + name) on Windows without the long-path option
DUP_RESERVE = 6           # room kept free for a possible "_dup12" ending


def name_budget(folder: Path, windows=None):
    """Longest file name (including .pdf) that is safe in this folder."""
    windows = (os.name == "nt") if windows is None else windows
    limit = NAME_MAX
    if windows:
        limit = min(limit, WIN_PATH_MAX - len(os.path.abspath(str(folder))) - 1)
    return max(limit, 30)


def build_name(meta, cfg, folder: Path, suffix="", windows=None):
    """Title space = name limit - everything else in the name (year, author, separators, suffix, .pdf)."""
    sep = cfg["word_sep"]
    authors = [a for a in meta.get("authors", []) if a] or ["Unknown"]
    if len(authors) == 1:
        many = authors[0]
    elif len(authors) == 2:
        many = f"{authors[0]} and {authors[1]}"
    else:
        many = f"{authors[0]} et al"
    year = (meta.get("year_online") if cfg.get("year", "citation") == "online" else None) or meta.get("year")
    vals = {"year": str(year or "nd"),
            "author": clean_field(authors[0], sep).replace(sep, "") if sep == "_" else clean_field(authors[0], sep),
            "authors": clean_field(many, sep),
            "journal": clean_field(meta.get("journal") or "", sep)}
    full_title = clean_field(meta["title"], sep)

    def render(title, short):
        stem = re.sub(r"\{(\w+)\}", lambda m: dict(vals, title=title, shorttitle=short).get(m.group(1), ""), cfg["format"])
        stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", stem)       # illegal on Windows
        stem = re.sub(r"([_\- ])\1+", r"\1", stem)
        return re.sub(r"\(\s*\)", "", stem).strip(" ._-")

    total = name_budget(folder, windows) - len(suffix) - len(".pdf") - DUP_RESERVE
    slots = len(re.findall(r"\{(?:title|shorttitle)\}", cfg["format"])) or 1
    fixed = len(render("T", "T")) - slots                         # year, author, separators...
    room = max((total - fixed) // slots, 10)                      # ...and what is left for the title
    cap = cfg.get("title_limit") or 0                             # 0 = use all the room there is
    if cap:
        room = min(room, cap)
    title = cut_words(full_title, room, sep)
    short = cut_words(sep.join(full_title.split(sep)[:6]), room, sep)
    stem = render(title, short)[:max(total, 20)].rstrip(" ._-")   # final guard (very long author/journal)
    return f"{stem}{suffix}.pdf"


def unique_path(folder: Path, name: str, me: Path, taken=()) -> Path:
    stem = name[:-4]
    p, n = folder / name, 2
    while (p.exists() and not same_file(p, me)) or os.path.normcase(os.path.abspath(p)) in taken:
        p = folder / f"{stem}_dup{n}.pdf"
        n += 1
    return p


def same_file(a: Path, b: Path):
    try:
        return a.exists() and b.exists() and os.path.samefile(a, b)
    except OSError:
        return False


# ------------------------------------------------------------ PDF reading
DOI_RE = re.compile(r"\b(10\.\d{4,9}/[^\s\"<>\]\[{}|\\^`,;]+)", re.I)
ARXIV_RE = re.compile(r"arxiv[:.\s/]*(\d{4}\.\d{4,5})(?:v\d+)?", re.I)
ARXIV_FILE_RE = re.compile(r"^(\d{4}\.\d{4,5})(?:v\d+)?$")
YEAR_RE = re.compile(r"\b(19[5-9]\d|20\d{2})\b")
BAD_TITLE = re.compile(r"\.(pdf|docx?|tex|dvi|indd)$|^untitled|microsoft word|^doi:|^pii:|^s\d{15}", re.I)


def find_dois(*texts):
    out = []
    for text in texts:
        for m in DOI_RE.finditer(text or ""):
            d = m.group(1).rstrip(".)('")
            if d.lower() not in [x.lower() for x in out]:
                out.append(d)
    return out


XMP_RE = re.compile(rb"<x:xmpmeta.*?</x:xmpmeta>", re.S)
EXTRA_KEYS = ("doi", "DOI", "arXivID")      # non-standard Info keys some publishers and arXiv use


def read_xmp(path: Path):
    """pdfium has no XMP call; XMP is stored uncompressed, so take it straight from the file."""
    try:
        if path.stat().st_size > 300 * 1024 * 1024:
            return ""
        return "\n".join(m.group(0).decode("utf-8", "ignore") for m in XMP_RE.finditer(path.read_bytes()))
    except OSError:
        return ""


def page_lines(page):
    """Upright text lines of a page as (font size, text, top, bottom), top measured from the page top."""
    tp = page.get_textpage()
    try:
        height, lines, cur = page.get_height(), [], []      # cur: (char, size, bottom, top, angle)

        def flush():
            if cur:
                text = " ".join("".join(c[0] for c in cur).split())
                size = max(c[1] for c in cur)
                if size < 2:                                 # size hidden in the text matrix: use glyph height
                    size = sorted(c[3] - c[2] for c in cur)[len(cur) // 2] * 1.4
                upright = sum(abs(c[4]) < 0.05 or abs(c[4] - 2 * math.pi) < 0.05 for c in cur) > len(cur) / 2
                if text and upright:                         # drops the rotated arXiv side stamp
                    lines.append((round(size, 1), text, height - max(c[3] for c in cur), height - min(c[2] for c in cur)))
                cur.clear()

        for i in range(tp.count_chars()):
            ch = chr(pdfium_raw.FPDFText_GetUnicode(tp.raw, i))
            if ch in "\r\n":
                flush()
                continue
            if ch in "\x02\ufffe":                          # pdfium's marker for a word broken at a line end
                continue
            left, bottom, right, top = tp.get_charbox(i)
            cur.append((ch, pdfium_raw.FPDFText_GetFontSize(tp.raw, i), bottom, top,
                        pdfium_raw.FPDFText_GetCharAngle(tp.raw, i)))
        flush()
        return lines
    finally:
        tp.close()


def page_text(page):
    tp = page.get_textpage()
    try:
        return tp.get_text_range().replace("\r\n", "\n").replace("\r", "\n").replace("\x02", "").replace("\ufffe", "")
    finally:
        tp.close()


def read_pdf(path: Path):
    try:
        doc = pdfium.PdfDocument(str(path))
    except pdfium.PdfiumError as e:
        raise ValueError("password-protected" if "assword" in str(e) else f"cannot open PDF ({e})")
    try:
        md = dict(doc.get_metadata_dict() or {})
        for key in EXTRA_KEYS:
            try:
                v = doc.get_metadata_value(key)
            except Exception:
                v = ""
            if v:
                md[key] = v
        xmp = read_xmp(path)
        pages, spans = [], []
        for i in range(min(2, len(doc))):
            page = doc[i]
            try:
                pages.append(page_text(page))
                if i == 0:
                    spans = page_lines(page)
            finally:
                page.close()
        spans.sort(key=lambda x: x[2])
        big, after = "", ""
        cand = [s for s in spans if len(s[1]) > 3 and not ARXIV_RE.match(s[1])]
        if cand:
            top = max(s[0] for s in cand)
            idx = [i for i, s in enumerate(spans) if abs(s[0] - top) < 0.6 and not ARXIV_RE.match(s[1])]
            groups = [[idx[0]]]                       # journal name and title can share a font size:
            for i in idx[1:]:                         # split into blocks, keep the longest one
                prev = groups[-1][-1]
                if i == prev + 1 and spans[i][2] - spans[prev][3] < 1.5 * top:
                    groups[-1].append(i)
                else:
                    groups.append([i])
            best = max(groups, key=lambda g: sum(len(spans[i][1]) for i in g))
            big = " ".join(spans[i][1] for i in best)
            for s in spans[best[-1] + 1: best[-1] + 6]:          # likely author line
                if re.match(r"^[A-Z][A-Za-z.\-' ]+[A-Za-z]", s[1]) and not YEAR_RE.search(s[1]) and len(s[1].split()) >= 2:
                    after = s[1]
                    break
        mt = (md.get("Title") or "").strip()
        return {"text": "\n".join(pages), "page1": pages[0] if pages else "",
                "big_title": big if 15 < len(big) < 300 else "",
                "md_title": mt if len(mt) > 10 and not BAD_TITLE.search(mt) else "",
                "md_author": (md.get("Author") or "").strip(), "author_line": after,
                "md_dois": find_dois(" ".join(str(v) for v in md.values() if v), xmp),
                "paperish": bool(DOI_RE.search(xmp + "\n".join(pages)) or ARXIV_RE.search("\n".join(pages))
                                 or re.search(r"\b(abstract|keywords|introduction|references)\b", "\n".join(pages), re.I)),
                "created": (md.get("CreationDate") or "")[2:6]}
    finally:
        doc.close()


# ------------------------------------------------------------ web sources
class NetError(Exception):
    pass


_session = requests.Session()
_warned = set()


def http_get(url, params=None, headers=None, kind="json"):
    """Return parsed body, None for 'not found', raise NetError when the service is unusable."""
    err = None
    for attempt in range(2):
        try:
            r = _session.get(url, params=params, headers=headers, timeout=12)
        except requests.RequestException as e:
            err = str(e)[:80]
            time.sleep(1)
            continue
        if r.status_code == 200:
            try:
                return r.json() if kind == "json" else r.text
            except ValueError:
                return None
        if r.status_code in (400, 404, 410):
            return None
        err = f"HTTP {r.status_code}"
        if r.status_code in (401, 403):
            break
        time.sleep(2)
    raise NetError(err)


def ua(cfg):
    mail = f" (mailto:{cfg['email']})" if cfg.get("email") else ""
    return {"User-Agent": f"{APP}/2.0{mail}"}


def _first(x):
    return (x[0] if x else "") if isinstance(x, list) else (x or "")


def from_csl(m, source):                       # Crossref and doi.org share this shape
    if not isinstance(m, dict):
        return None
    years = {}
    for k in ("issued", "published-print", "published-online", "published", "created"):
        dp = (m.get(k) or {}).get("date-parts") or [[None]]
        if dp and dp[0] and dp[0][0]:
            years[k] = int(dp[0][0])
    # citation year = the journal volume's year; online year = the earliest date on record
    # ("created" is when the DOI was registered, which for in-press articles is the online year)
    year = next((years[k] for k in ("issued", "published-print", "published-online", "published", "created") if k in years), None)
    online = min(years.values()) if years else None
    authors = [a.get("family") or last_name(a.get("name") or a.get("literal") or "") for a in m.get("author") or []]
    journal = _first(m.get("short-container-title")) or _first(m.get("container-title-short")) or _first(m.get("container-title"))
    return make_meta(_first(m.get("title")), year, authors, journal, source, online)


def make_meta(title, year, authors, journal, source, year_online=None):
    title = " ".join(str(title or "").split())
    authors = [a for a in authors if a]
    if not title or not year:
        return None
    return {"title": title, "year": int(year), "year_online": int(year_online or year), "authors": authors,
            "journal": journal or "", "source": source}


def crossref_doi(doi, cfg):
    p = {"mailto": cfg["email"]} if cfg.get("email") else None
    j = http_get(f"https://api.crossref.org/works/{doi}", p, ua(cfg))
    return from_csl(j.get("message"), "crossref") if j else None


def doiorg_doi(doi, cfg):
    h = dict(ua(cfg), Accept="application/vnd.citationstyles.csl+json")
    return from_csl(http_get(f"https://doi.org/{doi}", None, h), "doi.org")


def _openalex(w):
    if not isinstance(w, dict):
        return None
    authors = [last_name((a.get("author") or {}).get("display_name") or a.get("raw_author_name") or "")
               for a in w.get("authorships") or []]
    src = ((w.get("primary_location") or {}).get("source") or {}).get("display_name")
    return make_meta(w.get("title") or w.get("display_name"), w.get("publication_year"), authors, src, "openalex")


def openalex_doi(doi, cfg):
    if not cfg.get("openalex_key"):
        return None
    return _openalex(http_get(f"https://api.openalex.org/works/doi:{doi}", {"api_key": cfg["openalex_key"]}, ua(cfg)))


def _s2(w):
    if not isinstance(w, dict):
        return None
    pub = str(w.get("publicationDate") or "")[:4]
    online = min(int(pub), int(w["year"])) if pub.isdigit() and w.get("year") else None
    return make_meta(w.get("title"), w.get("year"), [last_name(a.get("name", "")) for a in w.get("authors") or []],
                     w.get("venue"), "semanticscholar", online)


def _s2_get(path, cfg, extra=None):
    h = ua(cfg)
    if cfg.get("s2_key"):
        h["x-api-key"] = cfg["s2_key"]
    p = {"fields": "title,year,authors,venue,publicationDate"}
    p.update(extra or {})
    return http_get(f"https://api.semanticscholar.org/graph/v1/paper/{path}", p, h)


def s2_doi(doi, cfg):
    return _s2(_s2_get(f"DOI:{doi}", cfg))


def s2_arxiv(aid, cfg):
    return _s2(_s2_get(f"ARXIV:{aid}", cfg))


def arxiv_id(aid, cfg):
    x = http_get("https://export.arxiv.org/api/query", {"id_list": aid}, ua(cfg), kind="text")
    if not x:
        return None
    ns = {"a": "http://www.w3.org/2005/Atom"}
    try:
        e = ET.fromstring(x).find("a:entry", ns)
        if e is None or e.find("a:title", ns) is None or e.find("a:published", ns) is None:
            return None
        authors = [last_name(n.text) for n in e.findall("a:author/a:name", ns)]
        return make_meta(e.find("a:title", ns).text, e.find("a:published", ns).text[:4], authors, "arXiv", "arxiv")
    except ET.ParseError:
        return None


def crossref_title(t, cfg):
    p = {"query.bibliographic": t, "rows": 3}
    if cfg.get("email"):
        p["mailto"] = cfg["email"]
    j = http_get("https://api.crossref.org/works", p, ua(cfg))
    return [from_csl(i, "crossref") for i in (j or {}).get("message", {}).get("items", [])]


def openalex_title(t, cfg):
    if not cfg.get("openalex_key"):
        return []
    j = http_get("https://api.openalex.org/works", {"search": t, "per_page": 3, "api_key": cfg["openalex_key"]}, ua(cfg))
    return [_openalex(i) for i in (j or {}).get("results", [])]


def s2_title(t, cfg):
    j = _s2_get("search/match", cfg, {"query": t})
    return [_s2(i) for i in (j or {}).get("data", [])]


DOI_SOURCES = [crossref_doi, doiorg_doi, openalex_doi, s2_doi]
ARXIV_SOURCES = [arxiv_id, s2_arxiv]
TITLE_SOURCES = [crossref_title, openalex_title, s2_title]


def call(fn, arg, cfg, stats):
    if fn.__name__.startswith("openalex") and not cfg.get("openalex_key"):
        return None                                   # not configured: neither reached nor failed
    try:
        r = fn(arg, cfg)
        stats["reached"] += 1
        return r
    except NetError as e:
        stats["failed"] += 1
        key = (fn.__name__.split("_")[0], str(e))
        if key not in _warned:
            _warned.add(key)
            print(f"[warn]  {key[0]} unavailable ({e}); using the next source")
        return None


# ------------------------------------------------------------ identification
def title_in_text(title, text):
    words = [w for w in norm(title).split() if len(w) > 3]
    if not words:
        return True
    t = norm(text)
    return sum(w in t for w in words) / len(words) >= 0.6


def titles_match(a, b):
    a, b = norm(a), norm(b)
    if not a or not b:
        return False
    if difflib.SequenceMatcher(None, a, b).ratio() >= 0.85:
        return True
    short, long_ = sorted((a, b), key=len)
    return len(short) >= 25 and long_.startswith(short)


def name_on_page(name, text):
    name = ascii_clean(name).strip()
    return bool(name) and re.search(r"(?<![A-Za-z])" + re.escape(name) + r"(?![a-z])", ascii_clean(text)) is not None


def title_hit_ok(meta, query, info):
    """A title-search result counts only if the title matches AND its first author is printed on page 1."""
    return bool(meta and meta.get("authors") and titles_match(meta["title"], query)
                and name_on_page(meta["authors"][0], info["page1"]))


def identify_online(path, info, cfg, stats):
    has_text = len(info["text"]) > 200
    md = [d.lower() for d in info["md_dois"]]
    for doi in (info["md_dois"] + [d for d in find_dois(info["text"]) if d.lower() not in md])[:6]:
        for fn in DOI_SOURCES:
            m = call(fn, doi, cfg, stats)
            if m:
                if title_in_text(m["title"], info["text"]) or (not has_text and doi.lower() in md):
                    return m
                break                       # DOI belongs to another paper (e.g. a reference)
    am = ARXIV_RE.search(info["text"]) or ARXIV_FILE_RE.match(path.stem)
    if am:
        for fn in ARXIV_SOURCES:
            m = call(fn, am.group(1), cfg, stats)
            if m and (not has_text or title_in_text(m["title"], info["text"])):
                return m
    for t in dict.fromkeys(x for x in (info["big_title"], info["md_title"]) if x):
        for fn in TITLE_SOURCES:
            for m in call(fn, t, cfg, stats) or []:
                if title_hit_ok(m, t, info):
                    return m
    return None


def identify_offline(info):
    title = info["md_title"] or info["big_title"]
    if not title:
        return None
    year = None
    for pat in (r"(?:©|\(c\)|copyright)", r"(?:available online|published)", r"accepted"):
        m = re.search(pat + r"[^\n]{0,40}?\b(19[5-9]\d|20\d{2})\b", info["page1"], re.I)
        if m:
            year = int(m.group(1))
            break
    if year is None:
        ys = [int(y) for y in YEAR_RE.findall(info["page1"]) if int(y) <= THIS_YEAR + 1]
        if ys:
            year = max(set(ys), key=ys.count)
        elif info["created"].isdigit():
            year = int(info["created"])

    def names(raw):
        """Split an author string into people; return [] unless every part reads like a person's name."""
        if not raw or ":" in raw:
            return []
        raw = re.sub(r"[\d*\u2020\u2021\u00a7\u00b6\u2217\u204e]+", " ", raw)                # footnote marks
        raw = re.sub(r"(?<=\s)[a-z](?:\s*,\s*[a-z])*(?=\s*(?:,|;|\u00b7|$|\band\b))", " ", raw)  # "Jia Hu a,b"
        parts = [p.strip() for p in re.split(r"\s*(?:;|,|&|\u00b7|\u2022|\band\b)\s*", raw) if p.strip()]
        if len(parts) >= 2 and len(parts[0].split()) == 1:               # "Islam, Md Monzurul"
            parts = [parts[1] + " " + parts[0]] + parts[2:]
        parts = [p for p in parts if p.rstrip(".").lower() not in ("prof", "dr", "phd", "jr", "sr")]
        ok = re.compile(r"^(?:[A-Z][\w.'\-]*|de|del|van|von|der|den|da|di|la|le|bin|al|el)$")
        for p in parts:
            toks = p.split()
            if not 2 <= len(toks) <= 5 or not all(ok.match(ascii_clean(t) or "x") for t in toks):
                return []
        return parts

    md, line = names(info["md_author"]), names(info["author_line"])
    md_first, line_first = (last_name(md[0]) if md else ""), (last_name(line[0]) if line else "")
    # Be conservative: a wrong author is worse than "Unknown". Use a name only when the PDF properties
    # and the printed author line agree, or when the single available one is clearly credible.
    if md_first and line_first:
        first = md_first if norm(md_first) == norm(line_first) else ""
    elif md_first:
        first = md_first if name_on_page(md_first, info["page1"]) else ""
    elif len(line) >= 2:
        first = line_first
    else:
        first = ""
    return {"title": title, "year": year, "authors": [first] if first else [],
            "journal": "", "source": "pdf-only"}


# ------------------------------------------------------------ engine
def pkey(path):
    return os.path.normcase(os.path.abspath(str(path)))


def inside(child, parent):
    c, p = pkey(child), pkey(parent)
    return c == p or c.startswith(p.rstrip("\\/") + os.sep)


def acquire_lock():
    """Only one renamer may change files at a time. The OS frees the lock when the process ends."""
    f = open(app_dir() / "lock", "a+")
    try:
        if os.name == "nt":
            import msvcrt
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        sys.exit("Paper Renamer is already running (for example a 'watch' window). Stop it first.")
    return f


def load_state():
    raw = _load("state.json", {})
    if "files" in raw:
        return raw["files"]
    files = {}                                         # migrate the first state format (keyed by fingerprint)
    for fp, r in raw.items():
        if isinstance(r, dict) and "path" in r:
            named = r.get("status") in ("ok", "check")
            files[pkey(r["path"])] = {"path": r["path"], "fp": fp, "sig": None, "status": r.get("status", "unknown"),
                                      "meta": r.get("meta"), "attempts": r.get("attempts", 0),
                                      "given": Path(r["path"]).name if named else None}
    return files


def read_history():
    p = app_dir() / "history.csv"
    if not p.exists():
        return []
    with open(p, encoding="utf-8", newline="") as f:
        return [(r + [""] * 6)[:6] for r in list(csv.reader(f))[1:] if r]


def write_history(rows):
    with open(app_dir() / "history.csv", "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows([HISTORY_HEAD] + rows)


class Engine:
    def __init__(self, cfg, log=print, dry=False):
        self.cfg, self.log, self.dry = cfg, log, dry
        self.files = load_state()                      # path key -> record
        self.lock = threading.Lock()
        self.renamed = 0
        self.planned = set()                           # names promised during a preview
        self.new_batch()

    # ---- small helpers
    def new_batch(self):
        self.batch = dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f")

    def _save(self):
        if not self.dry:
            _save("state.json", {"version": 2, "files": self.files})

    @staticmethod
    def fingerprint(path: Path):
        h = hashlib.sha1(str(path.stat().st_size).encode())
        with open(path, "rb") as f:
            h.update(f.read(262144))
        return h.hexdigest()

    @staticmethod
    def sig(path: Path):
        st = path.stat()
        return [st.st_size, int(st.st_mtime)]

    @staticmethod
    def stable(path: Path, timeout=120):
        last, t0 = -1, time.time()
        while time.time() - t0 < timeout:
            try:
                size = path.stat().st_size
            except OSError:
                return False
            if size == last and size > 0:
                return True
            last = size
            time.sleep(1.5)
        return False

    @staticmethod
    def manual(rec):
        """True when the user gave this file a name of their own."""
        return bool(rec.get("given")) and Path(rec["path"]).name != rec["given"]

    def _store(self, path, fp, status, meta, rec=None, given=None, bump=0):
        if rec and pkey(rec["path"]) != pkey(path):
            self.files.pop(pkey(rec["path"]), None)
        try:
            sig = self.sig(path)
        except OSError:
            sig = None
        new = {"path": str(path), "fp": fp, "sig": sig, "status": status, "meta": meta,
               "attempts": (rec or {}).get("attempts", 0) + bump,
               "given": given if given is not None else (rec or {}).get("given")}
        self.files[pkey(path)] = new
        self._save()
        return new

    def _lookup(self, path, fp=None):
        """Find the record for a file: by path, else by content if the user moved or renamed it."""
        rec = self.files.get(pkey(path))
        if rec:
            return rec, None
        fp = fp or self.fingerprint(path)
        twins = [r for r in self.files.values() if r["fp"] == fp]
        for r in twins:
            if not Path(r["path"]).exists():           # same file, moved or renamed by the user
                self.files.pop(pkey(r["path"]), None)
                r["path"] = str(path)
                self.files[pkey(path)] = r
                self._save()
                return r, None
        return None, next((r for r in twins if r["status"] == "ok" and r.get("meta")), None)

    def _rename(self, path, meta, status, source):
        """Rename (or preview). Returns the final path, or None when the file is locked."""
        suffix = "_CHECK" if status == "check" else ""
        new = unique_path(path.parent, build_name(meta, self.cfg, path.parent, suffix), path, self.planned)
        if new == path:
            return path
        tag = {"ok": "[ok]   ", "check": "[check]"}[status]
        if self.dry:
            self.planned.add(pkey(new))
            self.log(f"[preview] {path.name}  ->  {new.name}   ({source})")
            self.renamed += 1
            return path
        try:
            path.rename(new)
        except OSError as e:                           # e.g. open in a PDF viewer on Windows
            self.log(f"[busy]  {path.name}: {e.strerror or e}; will retry")
            return None
        log_rename(path, new, source, status, self.batch)
        self.renamed += 1
        self.log(f"{tag} {path.name}  ->  {new.name}   ({source})")
        return new

    # ---- main per-file logic
    def process(self, path: Path, retry=False):
        path = Path(path)
        if path.suffix.lower() != ".pdf" or path.name.startswith((".", "~$")) or not path.is_file():
            return
        with self.lock:
            try:
                self._process(path, retry)
            except Exception as e:
                self.log(f"[skip]  {path.name}: {e}")

    def _process(self, path, retry):
        rec = self.files.get(pkey(path))
        if rec and rec["status"] == "ok":              # done earlier: leave it alone
            try:
                sig = self.sig(path)
                if rec.get("sig") != sig:              # annotated / re-saved: refresh its fingerprint
                    rec["sig"], rec["fp"] = sig, self.fingerprint(path)
                    self._save()
            except OSError:
                pass
            return
        if not self.stable(path):
            return
        fp = self.fingerprint(path)
        if rec and rec["fp"] != fp:                    # a different file now has this (unfinished) name
            self.files.pop(pkey(path), None)
            rec = None
        meta, status, twin = None, "ok", None
        if rec is None:
            rec, twin = self._lookup(path, fp)
            if rec and rec["status"] == "ok":
                return
        if rec:
            if self.manual(rec) or not retry or rec.get("attempts", 0) >= MAX_ATTEMPTS:
                return
            if rec["status"] == "pending" and rec.get("meta"):
                meta, status = rec["meta"], rec.get("want", "ok")
        elif twin:                                     # a second copy of a paper we already know
            meta = twin["meta"]
        if meta is None:
            info = read_pdf(path)
            stats = {"reached": 0, "failed": 0}
            meta = identify_online(path, info, self.cfg, stats)
            if meta is None:
                offline = stats["failed"] and not stats["reached"] and info["paperish"]
                meta = identify_offline(info) if offline else None
                status = "check"
                bump = 1 if stats["reached"] else 0    # only count real "not found" answers
                if meta is None or (rec and rec["status"] == "check"):
                    if not rec:
                        why = "no web source reachable" if stats["failed"] and not stats["reached"] else "not identified"
                        self.log(f"[?]     {path.name}: {why}, left as is")
                        self._store(path, fp, "unknown", None, bump=bump)
                    elif bump:
                        rec["attempts"] = rec.get("attempts", 0) + 1
                        self._save()
                    return
        new = self._rename(path, meta, status, meta["source"])
        if self.dry:
            return
        if new is None:
            r = self._store(path, fp, "pending", meta, rec)
            r["want"] = status
            self._save()
            return
        self._store(new, fp, status, meta, rec, given=new.name, bump=0 if status == "ok" else 1)

    # ---- folder operations
    def pdfs(self, folders=None):
        for f in folders if folders is not None else self.cfg["folders"]:
            root = Path(f["path"])
            if not root.is_dir():
                self.log(f"[warn]  folder not available: {root}")
                continue
            it = root.rglob("*") if f.get("recursive", True) else root.glob("*")
            for p in sorted(it):
                if p.suffix.lower() == ".pdf" and p.is_file():
                    yield p

    def prune(self):
        """Forget files that were deleted (only where the watched folder itself is reachable)."""
        roots = [f["path"] for f in self.cfg["folders"] if Path(f["path"]).is_dir()]
        gone = [k for k, r in self.files.items()
                if any(inside(r["path"], root) for root in roots) and not Path(r["path"]).exists()]
        for k in gone:
            del self.files[k]
        if gone:
            self._save()

    def scan(self, folders=None):
        if not self.cfg["folders"]:
            self.log('No folders set up yet. First run:  python paper_renamer.py add-folder "PATH"')
            return
        self.new_batch()
        files = list(self.pdfs(folders))
        before = self.renamed
        for p in files:
            self.process(p, retry=True)
        if not self.dry:
            self.prune()
        word = "would be renamed" if self.dry else "renamed"
        self.log(f"Scan done: {len(files)} PDF(s) found, {self.renamed - before} {word}.")

    def reformat(self, include_manual=False):
        """Apply the current name format to files renamed earlier. Uses saved metadata, no web calls."""
        self.new_batch()
        kept = 0
        with self.lock:
            for p in list(self.pdfs()):
                try:
                    rec, _ = self._lookup(p)
                except OSError:
                    continue
                if not rec or not rec.get("meta") or rec["status"] not in ("ok", "check"):
                    continue
                if self.manual(rec) and not include_manual:
                    kept += 1
                    continue
                if "year_online" not in rec["meta"] and rec["status"] == "ok":
                    try:                               # saved before the online year existed: look it up once
                        fresh = identify_online(p, read_pdf(p), self.cfg, {"reached": 0, "failed": 0})
                    except Exception:
                        fresh = None
                    if fresh:
                        rec["meta"] = fresh
                        self._save()
                new = self._rename(p, rec["meta"], rec["status"], "reformat")
                if new and not self.dry:
                    self._store(new, rec["fp"], rec["status"], rec["meta"], rec, given=new.name)
        word = "would be renamed" if self.dry else "renamed"
        self.log(f"Reformat done: {self.renamed} {word}." +
                 (f" {kept} hand-renamed file(s) left alone (use --include-manual to rename them too)." if kept else ""))

    def undo(self, last=None):
        rows = read_history()
        if not rows:
            return self.log("Nothing to undo.")
        if last:
            take = rows[-last:]
        else:
            b = rows[-1][5]
            take = [r for r in rows if r[5] == b] if b else rows[-1:]
        for r in reversed(take):
            old, new = Path(r[1]), Path(r[2])
            if new.exists() and not old.exists():
                new.rename(old)
                rec = self.files.pop(pkey(new), None)
                if rec:
                    rec["path"] = str(old)
                    if r[3] == "reformat":             # back to the previous tool-given name
                        rec["given"] = old.name
                    self.files[pkey(old)] = rec        # otherwise it now counts as hand-named: left alone
                self.log(f"[undo]  {new.name}  ->  {old.name}")
            else:
                self.log(f"[skip]  cannot undo {new.name} (moved, renamed or original name taken)")
        write_history(rows[:len(rows) - len(take)] if last else [r for r in rows if r not in take])
        self._save()

    # ---- watching
    def watch(self, poll=False):
        from watchdog.events import FileSystemEventHandler
        from watchdog.observers import Observer
        from watchdog.observers.polling import PollingObserver
        if not self.cfg["folders"]:
            self.log('No folders set up yet. First run:  python paper_renamer.py add-folder "PATH"')
            return
        q = queue.Queue()

        class H(FileSystemEventHandler):
            def on_created(self, ev):
                if not ev.is_directory:
                    q.put(ev.src_path)

            def on_moved(self, ev):                    # browsers: x.crdownload -> x.pdf
                if not ev.is_directory:
                    q.put(ev.dest_path)

        obs = PollingObserver() if poll else Observer()
        obs.start()
        watches = {}                                   # path key -> (folder, watch handle)

        def reconcile():
            """Attach folders that are available, drop ones that vanished or were removed from settings."""
            want = {pkey(f["path"]): f for f in self.cfg["folders"]}
            for k in list(watches):
                f, handle = watches[k]
                if k not in want or want[k] != f or not Path(f["path"]).is_dir():
                    try:
                        obs.unschedule(handle)
                    except Exception:
                        pass
                    del watches[k]
                    if k in want and not Path(f["path"]).is_dir():
                        self.log(f"[warn]  {f['path']} is not available; will resume when it returns")
            fresh = []
            for k, f in want.items():
                if k not in watches and Path(f["path"]).is_dir():
                    try:
                        watches[k] = (f, obs.schedule(H(), f["path"], recursive=f.get("recursive", True)))
                    except Exception as e:
                        self.log(f"[warn]  cannot watch {f['path']}: {e}")
                        continue
                    self.log(f"Watching {f['path']}" + ("  (+subfolders)" if f.get("recursive", True) else ""))
                    fresh.append(f)
            return fresh

        def cfg_stamp():
            try:
                return (app_dir() / "config.json").stat().st_mtime
            except OSError:
                return 0

        fresh = reconcile()
        if fresh:
            self.scan(fresh)
        self.log("Ready. Ctrl+C to stop.")
        stamp, next_check, next_retry = cfg_stamp(), time.time() + 10, time.time() + RETRY_MINUTES * 60
        try:
            while True:
                try:
                    p = q.get(timeout=1)
                    self.new_batch()
                    self.process(Path(p))
                except queue.Empty:
                    pass
                now = time.time()
                if now > next_check:
                    next_check = now + 10
                    if cfg_stamp() != stamp:           # settings changed (CLI or, later, the UI)
                        stamp, self.cfg = cfg_stamp(), load_config()
                        self.log("Settings changed, reloaded.")
                    fresh = reconcile()
                    if fresh:
                        self.scan(fresh)
                if now > next_retry:
                    next_retry = now + RETRY_MINUTES * 60
                    self.new_batch()
                    for rec in list(self.files.values()):
                        if rec["status"] != "ok" and Path(rec["path"]).exists():
                            self.process(Path(rec["path"]), retry=True)
        except KeyboardInterrupt:
            pass
        obs.stop()
        obs.join()


# ------------------------------------------------------------ CLI
def add_folder(cfg, path, recursive):
    if not Path(path).is_dir():
        sys.exit(f"Not a folder: {path}")
    for f in cfg["folders"]:
        if pkey(f["path"]) == pkey(path):
            f["recursive"] = recursive
            return print(f"Updated {path}")
        if f.get("recursive", True) and inside(path, f["path"]):
            return print(f"Already covered: {path} is inside the watched folder {f['path']}")
    if recursive:
        covered = [f for f in cfg["folders"] if inside(f["path"], path)]
        for f in covered:
            print(f"Merged {f['path']} into the new folder")
        cfg["folders"] = [f for f in cfg["folders"] if f not in covered]
    cfg["folders"].append({"path": path, "recursive": recursive})
    print(f"Added {path}")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Rename paper PDFs from their metadata.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add-folder"); a.add_argument("path"); a.add_argument("--no-subfolders", action="store_true")
    a = sub.add_parser("remove-folder"); a.add_argument("path")
    a = sub.add_parser("set-key"); a.add_argument("service", choices=["openalex", "semanticscholar"]); a.add_argument("key")
    a = sub.add_parser("set-email"); a.add_argument("email")
    a = sub.add_parser("set-format"); a.add_argument("format"); a.add_argument("--word-sep", choices=["_", " ", "-"])
    a = sub.add_parser("set-title-length"); a.add_argument("n", type=int, help="max title characters; 0 = as long as fits")
    a = sub.add_parser("set-year"); a.add_argument("mode", choices=["online", "citation"])
    sub.add_parser("formats"); sub.add_parser("show")
    a = sub.add_parser("scan"); a.add_argument("--dry-run", action="store_true", help="preview only, change nothing")
    a = sub.add_parser("reformat"); a.add_argument("--dry-run", action="store_true")
    a.add_argument("--include-manual", action="store_true", help="also rename files you renamed by hand")
    a = sub.add_parser("watch"); a.add_argument("--poll", action="store_true", help="for network drives")
    a = sub.add_parser("undo"); a.add_argument("--last", type=int, metavar="N", help="undo the last N renames instead of the last run")
    args = ap.parse_args(argv)
    cfg = load_config()
    sample = {"title": "Deep learning for crash severity prediction: a case study", "year": 2025,
              "authors": ["Smith", "Jones", "Lee"], "journal": "Accid Anal Prev"}

    if args.cmd == "add-folder":
        add_folder(cfg, str(Path(args.path).expanduser().resolve()), not args.no_subfolders)
        save_config(cfg)
    elif args.cmd == "remove-folder":
        path = str(Path(args.path).expanduser().resolve())
        cfg["folders"] = [f for f in cfg["folders"] if pkey(f["path"]) != pkey(path)]
        save_config(cfg); print(f"Removed {path}")
    elif args.cmd == "set-key":
        cfg["openalex_key" if args.service == "openalex" else "s2_key"] = args.key.strip()
        save_config(cfg); print(f"{args.service} key saved.")
    elif args.cmd == "set-email":
        cfg["email"] = args.email.strip(); save_config(cfg); print("Email saved.")
    elif args.cmd == "set-format":
        fmt, sep = PRESETS.get(args.format, (args.format, cfg["word_sep"]))
        bad = set(re.findall(r"\{(\w*)\}", fmt)) - TOKENS
        if bad or "{" not in fmt:
            sys.exit(f"Unknown token(s) {sorted(bad)}. Use: " + " ".join("{%s}" % t for t in sorted(TOKENS)))
        cfg["format"], cfg["word_sep"] = fmt, args.word_sep or sep
        save_config(cfg)
        print("Format saved. Example:", build_name(sample, cfg, Path(".")))
        print("New files use it from now on. Existing files are unchanged; to convert them:")
        print("  python paper_renamer.py reformat --dry-run     (preview)")
        print("  python paper_renamer.py reformat               (apply)")
    elif args.cmd == "set-title-length":
        cfg["title_limit"] = max(args.n, 0); save_config(cfg)
        print("Title length:", f"at most {cfg['title_limit']} characters" if cfg["title_limit"] else "as long as the file name limit allows")
        print("To convert existing files:  python paper_renamer.py reformat")
    elif args.cmd == "set-year":
        cfg["year"] = args.mode; save_config(cfg)
        print("Year saved:", "first-online year" if args.mode == "online" else "citation (journal volume) year")
        print("New files use it from now on. To convert existing files:  python paper_renamer.py reformat")
    elif args.cmd == "formats":
        for name, (fmt, sep) in PRESETS.items():
            ex = build_name(sample, dict(cfg, format=fmt, word_sep=sep), Path("."))
            print(f"{name:28} {ex}")
        print("\nCustom tokens:", " ".join("{%s}" % t for t in sorted(TOKENS)))
    elif args.cmd == "show":
        print("Settings folder:", app_dir())
        print("Format:", cfg["format"], "| example:", build_name(sample, cfg, Path(".")))
        print("Title length:", f"at most {cfg['title_limit']} characters" if cfg.get("title_limit") else "as long as the file name limit allows")
        print("Year used:", "first-online year" if cfg.get("year", "citation") == "online" else "citation (journal volume) year")
        print("OpenAlex key:", "set" if cfg["openalex_key"] else "NOT set (OpenAlex is skipped)")
        print("Email:", cfg["email"] or "not set")
        for f in cfg["folders"]:
            print("Folder:", f["path"], "(+subfolders)" if f.get("recursive", True) else "")
    else:
        dry = getattr(args, "dry_run", False)
        lock = None if dry else acquire_lock()
        eng = Engine(cfg, dry=dry)
        if args.cmd == "scan":
            eng.scan()
        elif args.cmd == "reformat":
            eng.reformat(include_manual=args.include_manual)
        elif args.cmd == "watch":
            eng.watch(poll=args.poll)
        elif args.cmd == "undo":
            eng.undo(last=args.last)
        del lock


if __name__ == "__main__":
    main()
