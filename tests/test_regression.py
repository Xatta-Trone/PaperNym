"""Fixed, network-free cases from SPEC section 17."""

import pytest

from papernym.core.identify import Identifier, offline_record


@pytest.mark.parametrize("doi,citation,online,author", [
    ("10.1016/j.aap.2025.108048", 2025, 2025, "Islam"),
    ("10.1016/j.trc.2026.106087", 2027, 2026, "Li"),
    ("10.1016/j.trc.2025.105428", 2026, 2025, "Ling"),
    ("10.1177/03611981261468749", 2026, 2026, "Islam"),
    ("10.1038/s41598-026-74874-w", 2026, 2026, "Islam"),
])
def test_citation_year_and_first_author_regressions(doi, citation, online, author):
    title = "Research on transportation and road safety"
    csl = {"title": [title], "author": [{"family": author}],
           "issued": {"date-parts": [[citation]]},
           "created": {"date-parts": [[online]]}}

    def get(url, **_kwargs):
        assert doi in url
        return {"message": csl}

    text = (f"{title} {author} DOI {doi} ") * 8
    info = {"text": text, "page1": text, "md_dois": [doi], "big_title": "", "md_title": ""}
    match, _ = Identifier({"title_search": False}, get).identify_online("paper.pdf", info)
    assert match.paper_id == "doi:" + doi
    assert (match.meta["year"], match.meta["year_online"], match.meta["authors"][0]) == (
        citation, online, author)


def test_arxiv_1706_03762_regression():
    atom = """<feed xmlns="http://www.w3.org/2005/Atom"><entry>
    <title>Attention Is All You Need</title><published>2017-06-12T00:00:00Z</published>
    <author><name>Ashish Vaswani</name></author></entry></feed>"""
    text = "Attention Is All You Need Ashish Vaswani " * 8
    info = {"text": text, "page1": text, "md_dois": [], "big_title": "", "md_title": ""}
    match, _ = Identifier({"title_search": False}, lambda *_args, **_kwargs: atom).identify_online(
        "1706.03762.pdf", info)
    assert (match.meta["year"], match.meta["authors"][0]) == (2017, "Vaswani")


def test_journal_preproof_cover_cannot_match_unrelated_record():
    query = "Journal Pre-proof"
    unrelated = {"title": [query], "author": [{"family": "Other"}],
                 "issued": {"date-parts": [[2025]]}}
    info = {"text": "Journal Pre-proof A manuscript by Islam", "page1": "Journal Pre-proof by Islam",
            "md_dois": [], "big_title": query, "md_title": ""}
    match, _ = Identifier({"title_search": True},
                          lambda *_args, **_kwargs: {"message": {"items": [unrelated]}}).identify_online(
                              "cover.pdf", info)
    assert match is None


def test_conflicting_pdf_author_regression():
    info = {"md_title": "A road safety research paper", "big_title": "",
            "md_author": "Naveen Eluru, Prof", "author_line": "Md Monzurul Islam*",
            "page1": "Md Monzurul Islam* wrote this", "created": "2026"}
    assert offline_record(info)["authors"] == []
