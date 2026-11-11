from papernym.core.sources import arxiv, crossref, doiorg, openalex, semanticscholar


CSL = {"title": ["<i>A Paper</i> on Roads"],
       "issued": {"date-parts": [[2027]]}, "created": {"date-parts": [[2026]]},
       "author": [{"family": "Li"}], "short-container-title": ["Transp Res C"]}


class FakeGet:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def __call__(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


def test_crossref_and_doiorg_citation_and_online_years():
    cross = FakeGet({"message": CSL})
    meta = crossref.doi_lookup("10.1/test", {"email": "a@example.org"}, cross)
    assert (meta["title"], meta["year"], meta["year_online"], meta["authors"]) == (
        "A Paper on Roads", 2027, 2026, ["Li"])
    assert cross.calls[0][1]["params"] == {"mailto": "a@example.org"}
    doi = FakeGet(CSL)
    assert doiorg.doi_lookup("10.1/test", {}, doi)["source"] == "doi.org"
    assert doi.calls[0][1]["headers"]["Accept"].endswith("csl+json")
    search = FakeGet({"message": {"items": [CSL]}})
    assert crossref.title_search("A Paper", {}, search)[0]["year"] == 2027


def test_openalex_mapping_and_required_key():
    raw = {"title": "An OpenAlex Paper", "publication_year": 2025,
           "authorships": [{"author": {"display_name": "Smith, Alice"}}],
           "primary_location": {"source": {"display_name": "Journal A"}}}
    fake = FakeGet(raw)
    assert openalex.doi_lookup("10.1/test", {}, fake) is None
    assert fake.calls == []
    meta = openalex.doi_lookup("10.1/test", {"openalex_key": "key"}, fake)
    assert (meta["year"], meta["year_online"], meta["authors"]) == (2025, 2025, ["Smith"])
    assert fake.calls[0][1]["params"]["api_key"] == "key"
    assert openalex.title_search("Paper", {"openalex_key": "key"}, FakeGet({"results": [raw]}))[0] == meta


def test_semantic_scholar_mapping_and_paths():
    raw = {"title": "An S2 Paper", "year": 2026, "publicationDate": "2025-08-01",
           "authors": [{"name": "Jane Smith Jr"}], "venue": "Venue"}
    fake = FakeGet(raw)
    meta = semanticscholar.doi_lookup("10.1/test", {"s2_key": "secret"}, fake)
    assert (meta["year"], meta["year_online"], meta["authors"]) == (2026, 2025, ["Smith"])
    assert "DOI:10.1/test" in fake.calls[0][0]
    assert fake.calls[0][1]["headers"] == {"x-api-key": "secret"}
    assert semanticscholar.arxiv_lookup("1706.03762", {}, fake)["source"] == "semanticscholar"
    assert "ARXIV:1706.03762" in fake.calls[1][0]
    assert semanticscholar.title_search("paper", {}, FakeGet({"data": [raw]}))[0] == meta


def test_arxiv_atom_mapping():
    atom = """<feed xmlns="http://www.w3.org/2005/Atom"><entry>
    <title>Attention Is All You Need</title><published>2017-06-12T00:00:00Z</published>
    <author><name>Ashish Vaswani</name></author></entry></feed>"""
    fake = FakeGet(atom)
    meta = arxiv.arxiv_lookup("1706.03762", {}, fake)
    assert (meta["title"], meta["year"], meta["authors"]) == (
        "Attention Is All You Need", 2017, ["Vaswani"])
    assert fake.calls[0][1]["kind"] == "text"
    assert arxiv.arxiv_lookup("1706.03762", {}, FakeGet("<invalid")) is None
