"""Conservative DOI, arXiv, and title identification pipeline."""

from __future__ import annotations

import difflib
import datetime as dt
import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .pdfread import ARXIV_FILE_RE, ARXIV_RE, YEAR_RE, find_dois
from .sources.common import surname
from .sources import arxiv, crossref, doiorg, openalex, semanticscholar
from .sources.http import HttpClient, NetError


DOI_SOURCES = (("crossref", crossref.doi_lookup), ("doi.org", doiorg.doi_lookup),
               ("openalex", openalex.doi_lookup), ("semanticscholar", semanticscholar.doi_lookup))
ARXIV_SOURCES = (("arxiv", arxiv.arxiv_lookup), ("semanticscholar", semanticscholar.arxiv_lookup))
TITLE_SOURCES = (("crossref", crossref.title_search), ("openalex", openalex.title_search),
                 ("semanticscholar", semanticscholar.title_search))


@dataclass
class LookupStats:
    reached: int = 0
    failed: int = 0


@dataclass
class PaperMatch:
    paper_id: str
    meta: dict
    status: str = "ok"


@dataclass
class IdentifyOutcome:
    match: PaperMatch | None
    status: str
    attempts_delta: int
    stats: LookupStats


def ascii_fold(text: str) -> str:
    return unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode()


def normal_title(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", ascii_fold(text).lower()).split())


def title_in_text(title: str, text: str) -> bool:
    words = [word for word in normal_title(title).split() if len(word) > 3]
    if not words:
        return True
    haystack = normal_title(text)
    return sum(word in haystack for word in words) / len(words) >= 0.6


def titles_match(left: str, right: str) -> bool:
    left, right = normal_title(left), normal_title(right)
    if not left or not right:
        return False
    if difflib.SequenceMatcher(None, left, right).ratio() >= 0.85:
        return True
    shorter, longer = sorted((left, right), key=len)
    return len(shorter) >= 25 and longer.startswith(shorter)


def author_on_page(surname: str, page1: str) -> bool:
    name = ascii_fold(surname).strip()
    page = ascii_fold(page1)
    return bool(name) and re.search(r"(?<![A-Za-z])" + re.escape(name) + r"(?![A-Za-z])", page) is not None


def title_hit_ok(meta: dict | None, query: str, info: dict) -> bool:
    return bool(meta and meta.get("authors") and titles_match(meta["title"], query)
                and author_on_page(meta["authors"][0], info["page1"]))


def _author_names(raw: str) -> list[str]:
    if not raw or ":" in raw:
        return []
    raw = re.sub(r"[\d*†‡§¶∗⁎]+", " ", raw)
    raw = re.sub(r"(?<=\s)[a-z](?:\s*,\s*[a-z])*(?=\s*(?:,|;|·|$|\band\b))", " ", raw)
    parts = [part.strip() for part in re.split(r"\s*(?:;|,|&|·|•|\band\b)\s*", raw) if part.strip()]
    if len(parts) >= 2 and len(parts[0].split()) == 1 and 2 <= len(parts[1].split()) <= 5:
        parts = [parts[1] + " " + parts[0]] + parts[2:]
    parts = [part for part in parts if part.rstrip(".").lower() not in {"prof", "dr"}]
    particles = {"de", "del", "van", "von", "der", "den", "da", "di", "la", "le", "bin", "al", "el"}
    for part in parts:
        words = part.split()
        if not 2 <= len(words) <= 5:
            return []
        if any(not (word[0].isupper() or word.lower() in particles) for word in words):
            return []
    return parts


def offline_record(info: dict) -> dict | None:
    """Build conservative metadata from a paper-like PDF during an outage."""
    title = info.get("md_title") or info.get("big_title")
    if not title:
        return None
    page = info.get("page1", "")
    year = None
    for prefix in (r"(?:©|\(c\)|copyright)", r"(?:available online|published)", r"accepted"):
        match = re.search(prefix + r"[^\n]{0,40}?\b(19[5-9]\d|20\d{2})\b", page, re.I)
        if match:
            year = int(match.group(1))
            break
    if year is None:
        plausible = [int(value) for value in YEAR_RE.findall(page)
                     if int(value) <= dt.date.today().year + 1]
        if plausible:
            counts = {value: plausible.count(value) for value in plausible}
            year = max(plausible, key=lambda value: counts[value])
        elif str(info.get("created", "")).isdigit():
            year = int(info["created"])
    md_names = _author_names(info.get("md_author", ""))
    line_names = _author_names(info.get("author_line", ""))
    md_first = surname(md_names[0]) if md_names else ""
    line_first = surname(line_names[0]) if line_names else ""
    if md_first and line_first:
        first = md_first if normal_title(md_first) == normal_title(line_first) else ""
    elif md_first:
        first = md_first if author_on_page(md_first, page) else ""
    elif len(line_names) >= 2:
        first = line_first
    else:
        first = ""
    return {"title": title, "year": year, "year_online": year,
            "authors": [first] if first else [], "journal": "", "source": "pdf-only"}


class Identifier:
    def __init__(self, config: dict, http_get: Callable | None = None,
                 on_event: Callable | None = None, db=None):
        self.config = config
        self.http_get = http_get or HttpClient(config).get
        self.on_event = on_event or (lambda event: None)
        self.db = db
        self.read_only = False
        self._warned = set()

    def _cached(self, ident: str) -> PaperMatch | None:
        if self.db is None:
            return None
        row = self.db.get_paper(ident)
        if row is None:
            return None
        meta = {key: row[key] for key in ("title", "year", "year_online", "journal", "source")}
        meta["authors"] = json.loads(row["authors"])
        return PaperMatch(ident, meta)

    def _miss_fresh(self, ident: str) -> bool:
        if self.db is None:
            return False
        row = self.db.get_miss(ident)
        if row is None:
            return False
        try:
            checked = dt.datetime.fromisoformat(row["checked_at"])
            if checked.tzinfo is None:
                checked = checked.replace(tzinfo=dt.timezone.utc)
            return dt.datetime.now(dt.timezone.utc) - checked < dt.timedelta(days=30)
        except ValueError:
            return False

    def _mark_miss(self, ident: str):
        if self.db is not None and not self.read_only:
            self.db.put_miss(ident, dt.datetime.now(dt.timezone.utc).isoformat())

    def _save_match(self, match: PaperMatch) -> PaperMatch:
        if self.db is not None and not self.read_only:
            meta = match.meta
            self.db.put_paper({"paper_id": match.paper_id, "title": meta["title"],
                               "year": meta.get("year"), "year_online": meta.get("year_online"),
                               "authors": json.dumps(meta.get("authors", []), ensure_ascii=False),
                               "journal": meta.get("journal", ""), "source": meta["source"],
                               "fetched_at": dt.datetime.now(dt.timezone.utc).isoformat()})
        return match

    def _call(self, source: str, function: Callable, value: str, stats: LookupStats, path: Path):
        if source == "openalex" and not self.config.get("openalex_key"):
            return None
        try:
            result = function(value, self.config, self.http_get)
            stats.reached += 1
            return result
        except NetError as exc:
            stats.failed += 1
            if source not in self._warned:
                self._warned.add(source)
                self.on_event({"type": "source_unavailable", "path": str(path), "source": source,
                               "message": f"{source} unavailable: {exc}"})
            return None

    def identify_online(self, path: str | Path, info: dict) -> tuple[PaperMatch | None, LookupStats]:
        path = Path(path)
        stats = LookupStats()
        meta_dois = [doi.lower() for doi in info.get("md_dois", [])]
        candidates = list(dict.fromkeys(meta_dois + find_dois(info.get("text", ""))))[:6]
        for doi in candidates:
            ident = "doi:" + doi
            cached = self._cached(ident)
            if cached:
                trusted = len(info.get("text", "")) < 200 and doi in meta_dois
                if trusted or title_in_text(cached.meta["title"], info.get("text", "")):
                    return cached, stats
                continue
            if self._miss_fresh(ident):
                stats.reached += 1
                continue
            before = (stats.reached, stats.failed)
            for source, function in DOI_SOURCES:
                meta = self._call(source, function, doi, stats, path)
                if meta:
                    trusted = len(info.get("text", "")) < 200 and doi in meta_dois
                    if trusted or title_in_text(meta["title"], info.get("text", "")):
                        return self._save_match(PaperMatch(ident, meta)), stats
                    break
            if stats.reached > before[0] and stats.failed == before[1]:
                self._mark_miss(ident)
        arxiv_match = ARXIV_RE.search(info.get("text", "")) or ARXIV_FILE_RE.match(path.stem)
        if arxiv_match:
            aid = arxiv_match.group(1)
            ident = "arxiv:" + aid
            cached = self._cached(ident)
            if cached and title_in_text(cached.meta["title"], info.get("text", "")):
                return cached, stats
            if self._miss_fresh(ident):
                stats.reached += 1
            else:
                before = (stats.reached, stats.failed)
                for source, function in ARXIV_SOURCES:
                    meta = self._call(source, function, aid, stats, path)
                    if meta and title_in_text(meta["title"], info.get("text", "")):
                        return self._save_match(PaperMatch(ident, meta)), stats
                if stats.reached > before[0] and stats.failed == before[1]:
                    self._mark_miss(ident)
        if self.config.get("title_search", True):
            queries = dict.fromkeys(title for title in (info.get("big_title"), info.get("md_title")) if title)
            for query in queries:
                ident = "title:" + normal_title(query)
                cached = self._cached(ident)
                if cached and title_hit_ok(cached.meta, query, info):
                    return cached, stats
                if self._miss_fresh(ident):
                    stats.reached += 1
                    continue
                before = (stats.reached, stats.failed)
                for source, function in TITLE_SOURCES:
                    for meta in self._call(source, function, query, stats, path) or []:
                        if title_hit_ok(meta, query, info):
                            return self._save_match(PaperMatch("title:" + normal_title(meta["title"]), meta)), stats
                if stats.reached > before[0] and stats.failed == before[1]:
                    self._mark_miss(ident)
        return None, stats

    def identify(self, path: str | Path, info: dict) -> IdentifyOutcome:
        match, stats = self.identify_online(path, info)
        if match:
            return IdentifyOutcome(match, "ok", 0, stats)
        if stats.reached:
            return IdentifyOutcome(None, "unknown", 1, stats)
        if info.get("paperish"):
            meta = offline_record(info)
            if meta:
                paper_id = "title:" + normal_title(meta["title"])
                return IdentifyOutcome(PaperMatch(paper_id, meta, "check"), "check", 0, stats)
        return IdentifyOutcome(None, "unknown", 0, stats)
