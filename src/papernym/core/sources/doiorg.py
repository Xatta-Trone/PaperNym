"""doi.org content negotiation for DOI records."""

from .common import from_csl


def doi_lookup(doi, _config, http_get):
    data = http_get(f"https://doi.org/{doi}",
                    headers={"Accept": "application/vnd.citationstyles.csl+json"})
    return from_csl(data, "doi.org")
