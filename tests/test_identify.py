from papernym.core.identify import Identifier, author_on_page, title_in_text, titles_match
from papernym.core.sources.http import NetError


def csl(title, author="Smith", year=2025):
    return {"title": [title], "author": [{"family": author}],
            "issued": {"date-parts": [[year]]}}


def info(text="", **updates):
    result = {"text": text, "page1": text, "md_dois": [], "big_title": "", "md_title": "",
              "md_author": "", "author_line": "", "paperish": True, "created": ""}
    result.update(updates)
    return result


def test_doi_fallback_order_and_verification():
    calls = []
    title = "A detailed study of road crash severity"

    def get(url, **_kwargs):
        calls.append(url)
        if "api.crossref" in url:
            return None
        if "doi.org" in url:
            return csl(title)
        raise AssertionError(url)

    match, stats = Identifier({"title_search": False}, get).identify_online(
        "paper.pdf", info((title + " ") * 8, md_dois=["10.1234/PAPER"]))
    assert match.paper_id == "doi:10.1234/paper"
    assert match.meta["source"] == "doi.org"
    assert stats.reached == 2
    assert [url.split("/")[2] for url in calls] == ["api.crossref.org", "doi.org"]


def test_reference_doi_trap_moves_to_next_candidate():
    calls = []
    target = "A detailed study of road crash severity"

    def get(url, **_kwargs):
        calls.append(url)
        if "10.1234/reference" in url:
            return {"message": csl("Unrelated marine biology research")}
        if "10.1234/target" in url:
            return {"message": csl(target)}
        raise AssertionError(url)

    text = (target + " 10.1234/reference 10.1234/target ") * 8
    match, _ = Identifier({"title_search": False}, get).identify_online("paper.pdf", info(text))
    assert match.paper_id == "doi:10.1234/target"
    assert len(calls) == 2  # A verified mismatch stops further sources for that DOI.


def test_arxiv_path_and_title_author_check():
    atom = """<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Attention Is All You Need</title>
    <published>2017-06-12T00:00:00Z</published><author><name>Ashish Vaswani</name></author></entry></feed>"""
    calls = []

    def get(url, **_kwargs):
        calls.append(url)
        return atom

    match, _ = Identifier({"title_search": False}, get).identify_online(
        "1706.03762.pdf", info("Attention Is All You Need by Vaswani " * 8))
    assert match.paper_id == "arxiv:1706.03762"
    assert len(calls) == 1


def test_title_search_requires_matching_first_author_on_page():
    query = "Journal Pre-proof and research methods"
    calls = []

    def get(url, **_kwargs):
        calls.append(url)
        return {"message": {"items": [csl(query, "Wrong"), csl(query, "Smith")]}}

    match, _ = Identifier({"title_search": True}, get).identify_online(
        "paper.pdf", info("Alice Smith wrote this manuscript", big_title=query))
    assert match.paper_id.startswith("title:")
    assert match.meta["authors"] == ["Smith"]
    assert len(calls) == 1
    assert not author_on_page("Smith", "Smithsonian")
    assert titles_match("A sufficiently long title for research", "A sufficiently long title for research methods")
    assert not title_in_text("Unrelated marine biology research", "A detailed road safety analysis")


def test_service_failure_event_once_and_next_service_used():
    events = []
    title = "A detailed study of road crash severity"

    def get(url, **_kwargs):
        if "crossref" in url:
            raise NetError("offline")
        return csl(title)

    identifier = Identifier({"title_search": False}, get, events.append)
    for _ in range(2):
        match, stats = identifier.identify_online("paper.pdf", info(title * 8, md_dois=["10.1234/paper"]))
        assert match.meta["source"] == "doi.org"
        assert stats.failed == 1
    assert [event["type"] for event in events] == ["source_unavailable"]
