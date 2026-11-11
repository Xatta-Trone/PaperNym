"""Render scholarly metadata into safe, predictable PDF names."""

from __future__ import annotations

import re
import unicodedata


TOKENS = frozenset({"year", "author", "authors", "title", "shorttitle", "journal"})
_TAGS = re.compile(r"<[^>]*>")
_TOKEN = re.compile(r"\{([^{}]+)\}")

PRESETS = {
    "year_author_title": ("{year}_{author}_{title}", "_"),
    "author_year_title": ("{author}_{year}_{title}", "_"),
    "year_authors_title": ("{year}_{authors}_{title}", "_"),
    "authors_year_title": ("{authors}_{year}_{title}", "_"),
    "year_author_shorttitle": ("{year}_{author}_{shorttitle}", "_"),
    "author_year_shorttitle": ("{author}_{year}_{shorttitle}", "_"),
    "year_author_journal_title": ("{year}_{author}_{journal}_{title}", "_"),
    "author_year_journal": ("{author}_{year}_{journal}", "_"),
    "title_author_year": ("{title}_{author}_{year}", "_"),
    "title_only": ("{title}", "_"),
    "author_year": ("{author}_{year}", "_"),
    "citekey": ("{author}{year}{shorttitle}", ""),
    "author_year_title_spaces": ("{author} ({year}) {title}", " "),
    "authors_year_title_spaces": ("{authors} ({year}) {title}", " "),
    "authors_year_title_zotero": ("{authors} - {year} - {title}", " "),
}


def clean_field(value: object, word_sep: str = "_") -> str:
    """Clean one metadata field while retaining wholly non-Latin text."""
    if word_sep not in ("_", " ", "-", ""):
        raise ValueError("word_sep must be _, space, -, or empty")
    raw = _TAGS.sub("", str(value or ""))
    folded = unicodedata.normalize("NFKD", raw).encode("ascii", "ignore").decode()
    text = folded if folded.strip() else raw
    text = text.replace("'", "").replace("’", "")
    text = "".join(ch if ch.isalnum() or ch in "- " else " " for ch in text)
    return word_sep.join(text.split())


def token_values(meta: dict, year_mode: str = "citation", word_sep: str = "_") -> dict[str, str]:
    """Resolve the six naming tokens before template substitution."""
    if year_mode not in ("citation", "online"):
        raise ValueError("year_mode must be citation or online")
    authors = [str(name) for name in meta.get("authors", []) if name]
    first = authors[0] if authors else "Unknown"
    if len(authors) == 2:
        many = f"{authors[0]} and {authors[1]}"
    elif len(authors) >= 3:
        many = f"{authors[0]} et al"
    else:
        many = first
    year = meta.get("year_online") if year_mode == "online" else meta.get("year")
    title = clean_field(meta.get("title", ""), word_sep)
    raw_short = " ".join(str(meta.get("title", "")).split()[:6])
    return {
        "year": str(year) if year else "nd",
        "author": clean_field(first, word_sep),
        "authors": clean_field(many, word_sep),
        "title": title,
        "shorttitle": clean_field(raw_short, word_sep),
        "journal": clean_field(meta.get("journal", ""), word_sep),
    }


def _render_stem(template: str, values: dict[str, str]) -> str:
    stem = _TOKEN.sub(lambda match: values[match.group(1)], template)
    stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", stem)
    stem = re.sub(r"([_\- ])\1+", r"\1", stem)
    stem = re.sub(r"\(\s*\)", "", stem)
    return stem.strip(" ._-")


def render_preset(name: str, meta: dict, year_mode: str = "citation") -> str:
    """Render one fixed preset, before the length budget is applied."""
    template, sep = PRESETS[name]
    values = token_values(meta, year_mode, sep)
    if name == "citekey":
        title_words = clean_field(meta.get("title", ""), " ").split()[:6]
        values["shorttitle"] = "".join(word.capitalize() for word in title_words)
        values["author"] = values["author"].capitalize()
    return _render_stem(template, values) + ".pdf"
