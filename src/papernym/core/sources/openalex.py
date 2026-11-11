"""OpenAlex DOI and title search."""

from .common import record, surname


def from_openalex(data):
    if not isinstance(data, dict):
        return None
    authors = [surname((item.get("author") or {}).get("display_name") or "")
               for item in data.get("authorships") or []]
    journal = ((data.get("primary_location") or {}).get("source") or {}).get("display_name")
    return record(data.get("title"), data.get("publication_year"), authors, journal,
                  "openalex", data.get("publication_year"))


def doi_lookup(doi, config, http_get):
    if not config.get("openalex_key"):
        return None
    data = http_get(f"https://api.openalex.org/works/doi:{doi}",
                    params={"api_key": config["openalex_key"]})
    return from_openalex(data)


def title_search(title, config, http_get):
    if not config.get("openalex_key"):
        return []
    data = http_get("https://api.openalex.org/works",
                    params={"search": title, "per_page": 3, "api_key": config["openalex_key"]})
    return [item for item in (from_openalex(raw) for raw in (data or {}).get("results", [])) if item]
