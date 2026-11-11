"""Crossref DOI and title search."""

from .common import from_csl


def doi_lookup(doi, config, http_get):
    params = {"mailto": config["email"]} if config.get("email") else None
    data = http_get(f"https://api.crossref.org/works/{doi}", params=params)
    return from_csl(data.get("message"), "crossref") if data else None


def title_search(title, config, http_get):
    params = {"query.bibliographic": title, "rows": 3}
    if config.get("email"):
        params["mailto"] = config["email"]
    data = http_get("https://api.crossref.org/works", params=params)
    return [item for item in (from_csl(raw, "crossref") for raw in
            ((data or {}).get("message") or {}).get("items", [])) if item]
