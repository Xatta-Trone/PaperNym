"""Shared field mapping for scholarly service responses."""

import re


def first(value):
    return value[0] if isinstance(value, list) and value else (value or "")


def surname(name: str) -> str:
    name = re.sub(r"[\d*]", "", str(name or "")).strip()
    if "," in name:
        return name.split(",", 1)[0].strip()
    parts = [part for part in name.split() if part.rstrip(".").lower() not in
             {"jr", "sr", "ii", "iii", "phd"}]
    return parts[-1] if parts else ""


def record(title, year, authors, journal, source, year_online=None):
    title = " ".join(re.sub(r"<[^>]+>", "", str(first(title))).split())
    if not title:
        return None
    return {"title": title, "year": int(year) if year else None,
            "year_online": int(year_online) if year_online else None,
            "authors": [str(name) for name in authors if name], "journal": str(first(journal)),
            "source": source}


def from_csl(data, source):
    if not isinstance(data, dict):
        return None
    years = {}
    for key in ("issued", "published-print", "published-online", "published", "created"):
        parts = (data.get(key) or {}).get("date-parts") or []
        if parts and parts[0] and parts[0][0]:
            years[key] = int(parts[0][0])
    citation = next((years[key] for key in ("issued", "published-print", "published-online", "published", "created")
                     if key in years), None)
    authors = [author.get("family") or surname(author.get("name") or author.get("literal"))
               for author in data.get("author") or []]
    journal = first(data.get("short-container-title")) or first(data.get("container-title"))
    return record(data.get("title"), citation, authors, journal, source,
                  min(years.values()) if years else None)
