import requests
import pytest

from papernym.core.sources.http import HttpClient, NetError


class Response:
    def __init__(self, status, body=None):
        self.status_code = status
        self.body = body
        self.text = str(body)

    def json(self):
        return self.body


class Session:
    def __init__(self, *results):
        self.results = list(results)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def test_user_agent_timeout_headers_and_text():
    session = Session(Response(200, "atom"))
    client = HttpClient({"email": "a@example.org"}, session=session, sleep=lambda _: None)
    assert client.get("https://example.org", headers={"Accept": "text/xml"}, kind="text") == "atom"
    _, kwargs = session.calls[0]
    assert kwargs["timeout"] == 12
    assert kwargs["headers"]["User-Agent"].startswith("PaperNym/0.1.0 (mailto:a@example.org)")
    assert kwargs["headers"]["Accept"] == "text/xml"


@pytest.mark.parametrize("first", [requests.ConnectionError("offline"), Response(429), Response(503)])
def test_one_retry_then_success(first):
    waits = []
    session = Session(first, Response(200, {"ok": True}))
    client = HttpClient({}, session=session, sleep=waits.append)
    assert client.get("https://example.org") == {"ok": True}
    assert len(session.calls) == 2
    assert waits == [1 if isinstance(first, Exception) else 2]


@pytest.mark.parametrize("status", [400, 404, 410])
def test_not_found_statuses(status):
    session = Session(Response(status))
    assert HttpClient({}, session=session).get("https://example.org") is None
    assert len(session.calls) == 1


@pytest.mark.parametrize("status", [401, 403])
def test_rejected_key_is_reported_without_retry(status):
    session = Session(Response(status))
    with pytest.raises(NetError) as error:
        HttpClient({}, session=session).get("https://example.org")
    assert error.value.status == status
    assert len(session.calls) == 1


def test_repeat_failure_raises_net_error():
    session = Session(Response(500), Response(500))
    with pytest.raises(NetError) as error:
        HttpClient({}, session=session, sleep=lambda _: None).get("https://example.org")
    assert error.value.status == 500
    assert len(session.calls) == 2


def test_errors_never_carry_the_api_key():
    import requests

    from papernym.core.sources.http import HttpClient, NetError

    class Broken:
        def get(self, url, params=None, headers=None, timeout=None):
            raise requests.ConnectionError(f"Max retries exceeded with url: /works?search=x&api_key=SECRET123 ({url})")

    client = HttpClient({"email": ""}, session=Broken(), sleep=lambda _: None)
    try:
        client.get("https://api.openalex.org/works", params={"api_key": "SECRET123"})
    except NetError as exc:
        assert "SECRET123" not in str(exc) and "api_key=***" in str(exc)
        assert exc.__cause__ is None
    else:
        raise AssertionError("expected NetError")
