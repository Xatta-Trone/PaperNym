import pytest

from papernym.core import updates


@pytest.mark.parametrize("latest,current,newer", [
    ("v0.2.0", "0.1.0", True), ("0.10.0", "0.9.9", True), ("v0.1.0", "0.1.0", False),
    ("v0.1", "0.1.0", False), ("v0.0.9", "0.1.0", False), ("nightly", "0.1.0", False),
])
def test_version_comparison(latest, current, newer):
    assert updates.is_newer(latest, current) is newer


def test_check_reads_the_latest_release_and_sends_nothing_personal():
    seen = []

    def http_get(url, params=None, headers=None, kind="json"):
        seen.append((url, params, headers))
        return {"tag_name": "v9.0.0", "html_url": "https://github.com/Xatta-Trone/papernym/releases/tag/v9.0.0"}

    info = updates.check(http_get, current="0.1.0")
    assert info.newer and info.latest == "9.0.0" and info.url.endswith("/v9.0.0")
    assert seen == [("https://api.github.com/repos/Xatta-Trone/papernym/releases/latest", None,
                     {"Accept": "application/vnd.github+json"})]


def test_no_release_yet():
    info = updates.check(lambda *a, **k: None, current="0.1.0")
    assert info.latest is None and not info.newer
