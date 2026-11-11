"""Semantic Scholar DOI, arXiv, and title lookups."""

from .common import record, surname


FIELDS = "title,year,authors,venue,publicationDate"


def from_s2(data):
    if not isinstance(data, dict):
        return None
    published = str(data.get("publicationDate") or "")[:4]
    years = [int(year) for year in (data.get("year"), published) if str(year).isdigit()]
    return record(data.get("title"), data.get("year"),
                  [surname(item.get("name")) for item in data.get("authors") or []],
                  data.get("venue"), "semanticscholar", min(years) if years else None)


def _get(path, config, http_get, extra=None):
    headers = {"x-api-key": config["s2_key"]} if config.get("s2_key") else None
    params = {"fields": FIELDS}
    params.update(extra or {})
    return http_get(f"https://api.semanticscholar.org/graph/v1/paper/{path}",
                    params=params, headers=headers)


def doi_lookup(doi, config, http_get):
    return from_s2(_get(f"DOI:{doi}", config, http_get))


def arxiv_lookup(aid, config, http_get):
    return from_s2(_get(f"ARXIV:{aid}", config, http_get))


def title_search(title, config, http_get):
    data = _get("search/match", config, http_get, {"query": title})
    return [item for item in (from_s2(raw) for raw in (data or {}).get("data", [])) if item]
