"""Check each metadata service with a known paper (used by `papernym test-apis` and the Sources tab)."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Iterable

from .identify import normal_title, titles_match
from .sources import arxiv, crossref, doiorg, openalex, semanticscholar
from .sources.http import NetError


TEST_DOI = "10.1038/nature16961"
TEST_TITLE = "Mastering the game of Go with deep neural networks and tree search"
TEST_EXPECT = ("Silver", 2016)
TEST_ARXIV = "1706.03762"
TEST_ARXIV_DOI = "10.48550/arXiv.1706.03762"
TEST_ARXIV_EXPECT = ("Vaswani", 2017)

# (service, label, function, value, expected (surname, year), is_list)
CHECKS = (
    ("crossref", "Crossref          DOI lookup", crossref.doi_lookup, TEST_DOI, TEST_EXPECT, False),
    ("crossref", "Crossref          title search", crossref.title_search, TEST_TITLE, TEST_EXPECT, True),
    ("doi.org", "doi.org           DOI lookup", doiorg.doi_lookup, TEST_DOI, TEST_EXPECT, False),
    ("doi.org", "doi.org           DataCite DOI", doiorg.doi_lookup, TEST_ARXIV_DOI, TEST_ARXIV_EXPECT, False),
    ("openalex", "OpenAlex          DOI lookup", openalex.doi_lookup, TEST_DOI, TEST_EXPECT, False),
    ("openalex", "OpenAlex          title search", openalex.title_search, TEST_TITLE, TEST_EXPECT, True),
    ("semanticscholar", "Semantic Scholar  DOI lookup", semanticscholar.doi_lookup, TEST_DOI, TEST_EXPECT, False),
    ("semanticscholar", "Semantic Scholar  arXiv lookup", semanticscholar.arxiv_lookup, TEST_ARXIV,
     TEST_ARXIV_EXPECT, False),
    ("semanticscholar", "Semantic Scholar  title search", semanticscholar.title_search, TEST_TITLE,
     TEST_EXPECT, True),
    ("arxiv", "arXiv             ID lookup", arxiv.arxiv_lookup, TEST_ARXIV, TEST_ARXIV_EXPECT, False),
)


@dataclass(frozen=True)
class CheckResult:
    service: str
    label: str
    status: str  # PASS, FAIL or SKIP
    detail: str


def run_checks(config: dict, http_get: Callable, services: Iterable[str] | None = None,
               on_result: Callable[[CheckResult], None] | None = None) -> list[CheckResult]:
    """Run the known-paper checks, optionally only for some services."""
    wanted = set(services) if services is not None else None
    results = []
    for service, label, function, value, (author, year), is_list in CHECKS:
        if wanted is not None and service not in wanted:
            continue
        if service == "openalex" and not config.get("openalex_key"):
            result = CheckResult(service, label, "SKIP", "no OpenAlex key")
        else:
            result = _check(service, label, function, value, author, year, is_list, config, http_get)
        results.append(result)
        if on_result:
            on_result(result)
    return results


def _check(service, label, function, value, author, year, is_list, config, http_get) -> CheckResult:
    started = time.monotonic()
    try:
        found = function(value, config, http_get)
        if is_list:
            found = next((item for item in found or [] if titles_match(item["title"], value)), None)
        if not found:
            return CheckResult(service, label, "FAIL", "reachable, but the test paper was not found")
        first = (found["authors"] or ["?"])[0]
        good = (normal_title(first) == normal_title(author)
                and found["year"] is not None and abs(found["year"] - year) <= 1)
        detail = (f"{found['year']} / {first} / {found['title'][:45]}  "
                  f"({time.monotonic() - started:.1f}s)" + ("" if good else "  <- unexpected values"))
        return CheckResult(service, label, "PASS" if good else "FAIL", detail)
    except NetError as exc:
        hint = ""
        if exc.status in (401, 403):
            hint = "  <- key rejected or access blocked"
        elif exc.status == 429:
            hint = "  <- rate limited; try again in a minute"
        return CheckResult(service, label, "FAIL", f"{exc}{hint}")
    except Exception as exc:  # unexpected response shape from a live service
        return CheckResult(service, label, "FAIL", f"{type(exc).__name__}: {exc}")
