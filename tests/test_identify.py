from papernym.core.db import Database
import pytest

from papernym.core.identify import Identifier, author_on_page, offline_record, title_in_text, titles_match
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


def test_paper_cache_avoids_second_network_lookup(tmp_path):
    title = "A detailed study of road crash severity"
    calls = []

    def get(url, **_kwargs):
        calls.append(url)
        return {"message": csl(title)}

    with Database(tmp_path) as db:
        identifier = Identifier({"title_search": False}, get, db=db)
        pdf = info((title + " ") * 8, md_dois=["10.1234/paper"])
        first, _ = identifier.identify_online("one.pdf", pdf)
        second, stats = identifier.identify_online("two.pdf", pdf)
        assert first.paper_id == second.paper_id
        assert len(calls) == 1
        assert stats.reached == 0


def test_recent_miss_skips_lookup_but_old_miss_retries(tmp_path):
    from datetime import datetime, timedelta, timezone

    calls = []

    def get(url, **_kwargs):
        calls.append(url)
        return None

    with Database(tmp_path) as db:
        identifier = Identifier({"title_search": False}, get, db=db)
        pdf = info("A paper with DOI 10.1234/missing " * 8)
        match, _ = identifier.identify_online("paper.pdf", pdf)
        assert match is None
        assert db.get_miss("doi:10.1234/missing") is not None
        count = len(calls)
        _, stats = identifier.identify_online("paper.pdf", pdf)
        assert len(calls) == count
        assert stats.reached == 1
        old = (datetime.now(timezone.utc) - timedelta(days=31)).isoformat()
        db.put_miss("doi:10.1234/missing", old)
        identifier.identify_online("paper.pdf", pdf)
        assert len(calls) > count


def test_outage_fallback_and_unknown_rules():
    def down(_url, **_kwargs):
        raise NetError("offline")

    paper = info("Abstract 10.1234/paper", md_title="A useful research article", paperish=True)
    outcome = Identifier({"title_search": False}, down).identify("paper.pdf", paper)
    assert outcome.status == "check"
    assert outcome.match.meta["source"] == "pdf-only"
    assert outcome.attempts_delta == 0
    assert outcome.stats.failed > 0
    nonpaper = info("10.1234/paper", md_title="A useful research article", paperish=False)
    assert Identifier({"title_search": False}, down).identify("file.pdf", nonpaper).status == "unknown"
    answered = Identifier({"title_search": False}, lambda *_args, **_kwargs: None).identify(
        "paper.pdf", paper)
    assert answered.status == "unknown"
    assert answered.attempts_delta == 1


@pytest.mark.parametrize("md_author,author_line,page,expected", [
    ("Alice Smith", "Alice Smith and Bob Jones", "Alice Smith wrote this", "Smith"),
    ("Alice Smith", "Jane Jones and Bob Lee", "Alice Smith Jane Jones", ""),
    ("Alice Smith", "", "Alice Smith wrote this", "Smith"),
    ("Alice Smith", "", "Someone else wrote this", ""),
    ("", "Alice Smith and Bob Jones", "Alice Smith Bob Jones", "Smith"),
    ("", "Alice Smith", "Alice Smith wrote this", ""),
    ("Naveen Eluru, Prof", "Md Monzurul Islam*", "Md Monzurul Islam", ""),
])
def test_offline_author_decisions(md_author, author_line, page, expected):
    meta = offline_record(info(page, md_title="A useful research article",
                               md_author=md_author, author_line=author_line))
    assert meta["authors"] == ([expected] if expected else [])


@pytest.mark.parametrize("page,created,expected", [
    ("© 2025; received 2023", "2024", 2025),
    ("Available online 2024; accepted 2023", "2022", 2024),
    ("Accepted in 2023; received 2022", "2021", 2023),
    ("Received 2021; 2022 2022 and 2023", "2020", 2022),
    ("No year appears", "2020", 2020),
])
def test_offline_year_priority(page, created, expected):
    assert offline_record(info(page, md_title="A useful research article", created=created))["year"] == expected


def test_title_search_privacy_switch_sends_no_titles():
    calls = []

    def get(url, **kwargs):
        calls.append((url, kwargs))
        return None

    hidden = "Private unpublished research title"
    identifier = Identifier({"title_search": False}, get)
    identifier.identify_online("paper.pdf", info("Abstract", big_title=hidden, md_title=hidden))
    assert calls == []
    identifier.identify_online("paper.pdf", info("10.1234/example Abstract", big_title=hidden))
    assert calls
    assert all(hidden not in str(call) for call in calls)
    assert all("query.bibliographic" not in str(call) and "search/match" not in str(call)
               for call in calls)
