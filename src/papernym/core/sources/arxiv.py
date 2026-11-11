"""arXiv Atom API mapping."""

import xml.etree.ElementTree as ET

from .common import record, surname


def arxiv_lookup(aid, _config, http_get):
    body = http_get("https://export.arxiv.org/api/query", params={"id_list": aid}, kind="text")
    if not body:
        return None
    ns = {"a": "http://www.w3.org/2005/Atom"}
    try:
        entry = ET.fromstring(body).find("a:entry", ns)
        if entry is None:
            return None
        published = entry.findtext("a:published", default="", namespaces=ns)
        return record(entry.findtext("a:title", default="", namespaces=ns),
                      published[:4],
                      [surname(author.findtext("a:name", default="", namespaces=ns))
                       for author in entry.findall("a:author", ns)],
                      "arXiv", "arxiv", published[:4])
    except (ET.ParseError, ValueError):
        return None
