"""Render scholarly metadata into safe, predictable PDF names."""

from __future__ import annotations

import re
import unicodedata
import os
from pathlib import Path


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


class TemplateError(ValueError):
    """A custom name template violates a naming rule."""


class NameBudgetError(ValueError):
    """The containing folder leaves no room for a valid PDF name."""


def validate_template(template: str) -> list[str]:
    """Validate a template and return non-blocking warnings."""
    if not isinstance(template, str) or not template:
        raise TemplateError("template must be a nonempty string")
    if template[0] in " ." or template[-1] in " .":
        raise TemplateError("template must not start or end with a space or dot")
    fixed = []
    tokens = []
    index = 0
    while index < len(template):
        char = template[index]
        if char == "}":
            raise TemplateError("unbalanced braces")
        if char == "{":
            end = template.find("}", index + 1)
            if end < 0 or "{" in template[index + 1:end]:
                raise TemplateError("unbalanced or nested braces")
            token = template[index + 1:end]
            if token not in TOKENS:
                raise TemplateError(f"unknown token: {{{token}}}")
            tokens.append(token)
            index = end + 1
            continue
        if not (char.isalpha() or char.isdigit() or char in " _-.,()[]+&'"):
            raise TemplateError(f"invalid fixed character: {char!r}")
        fixed.append(char)
        index += 1
    if not tokens:
        raise TemplateError("template needs at least one token")
    if len(fixed) > 60:
        raise TemplateError("fixed text must be at most 60 characters")
    return ([] if "title" in tokens or "shorttitle" in tokens else
            ["Template has no title token; names may collide."])


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
    raw_short = " ".join(_TAGS.sub("", str(meta.get("title", ""))).split()[:6])
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


def render_custom(template: str, meta: dict, word_sep: str = "_",
                  year_mode: str = "citation") -> str:
    """Render a validated custom template, preserving its fixed text."""
    validate_template(template)
    values = token_values(meta, year_mode, word_sep)
    return _render_stem(template, values) + ".pdf"


def name_budget(folder: str | Path, windows: bool | None = None) -> int:
    """Maximum filename size, in characters on Windows and bytes elsewhere."""
    windows = os.name == "nt" if windows is None else windows
    return min(255, 259 - len(os.path.abspath(os.fspath(folder))) - 1) if windows else 255


def _measure(value: str, windows: bool) -> int:
    return len(value) if windows else len(value.encode("utf-8"))


def cut_words(words: list[str], room: int, separator: str, windows: bool) -> str:
    """Take complete title words that fit the available room."""
    chosen = []
    for word in words:
        candidate = separator.join((*chosen, word))
        if _measure(candidate, windows) > room:
            break
        chosen.append(word)
    return separator.join(chosen)


def _hard_cut(value: str, room: int, windows: bool) -> str:
    out = ""
    for char in value:
        if _measure(out + char, windows) > room:
            break
        out += char
    return out


def build_name(meta: dict, template: str, folder: str | Path, *, word_sep: str = "_",
               year_mode: str = "citation", title_limit: int = 0, suffix: str = "",
               windows: bool | None = None, reserve: int = 6) -> str:
    """Render a preset name or custom template within the platform budget."""
    windows = os.name == "nt" if windows is None else windows
    citekey = template == "citekey"
    if template in PRESETS:
        template, word_sep = PRESETS[template]
    else:
        validate_template(template)
    if title_limit < 0:
        raise ValueError("title_limit must be nonnegative")
    limit = name_budget(folder, windows)
    if limit < _measure(suffix + ".pdf", windows) + 1:
        raise NameBudgetError("folder path leaves no room for a PDF name")
    values = token_values(meta, year_mode, word_sep)
    title_words = clean_field(meta.get("title", ""), " ").split()
    if citekey:
        title_words = [word.capitalize() for word in title_words]
        values["author"] = values["author"].capitalize()
    title_tokens = _TOKEN.findall(template)
    slots = sum(token in ("title", "shorttitle") for token in title_tokens)
    placeholder = dict(values, title="x", shorttitle="x")
    fixed_length = _measure(_render_stem(template, placeholder), windows) - slots
    room = max(0, limit - _measure(suffix + ".pdf", windows) - reserve - fixed_length)
    if title_limit:
        room = min(room, title_limit)
    per_slot = room // slots if slots else 0
    values["title"] = cut_words(title_words, per_slot, word_sep, windows)
    values["shorttitle"] = cut_words(title_words[:6], per_slot, word_sep, windows)
    stem = _render_stem(template, values)
    stem_room = limit - _measure(suffix + ".pdf", windows)
    if _measure(stem, windows) > stem_room:
        stem = _hard_cut(stem, stem_room, windows).rstrip(" ._-")
    if not stem:
        raise NameBudgetError("template produced an empty PDF name")
    return stem + suffix + ".pdf"


def _letter(index: int) -> str:
    result = ""
    while index:
        index, digit = divmod(index - 1, 26)
        result = chr(ord("a") + digit) + result
    return result


def unique_path(folder: str | Path, meta: dict, template: str, *, paper_id: str | None,
                fingerprint: str | None, known: dict[str, tuple[str | None, str | None]] | None = None,
                current: str | Path | None = None, word_sep: str = "_", year_mode: str = "citation",
                title_limit: int = 0, suffix: str = "", windows: bool | None = None) -> Path:
    """Choose a free path without overwriting any existing or planned file."""
    folder = Path(folder)
    windows = os.name == "nt" if windows is None else windows
    identities = {os.path.normcase(os.path.abspath(path)): value for path, value in (known or {}).items()}
    current_key = os.path.normcase(os.path.abspath(current)) if current is not None else None
    limit = name_budget(folder, windows)

    def owner(candidate: Path):
        key = os.path.normcase(os.path.abspath(candidate))
        if key == current_key:
            return "current"
        if key not in identities and not candidate.exists():
            return None
        other_id, other_fp = identities.get(key, (None, None))
        if (paper_id and other_id == paper_id) or (fingerprint and other_fp == fingerprint):
            return "same"
        return "different"

    def with_ending(base: str, ending: str) -> Path:
        stem = base[:-4]
        room = limit - _measure(ending + suffix + ".pdf", windows)
        if room < 1:
            raise NameBudgetError("folder path leaves no room for a collision suffix")
        stem = _hard_cut(stem.removesuffix(suffix), room, windows).rstrip(" ._-")
        return folder / f"{stem}{ending}{suffix}.pdf"

    base = build_name(meta, template, folder, word_sep=word_sep, year_mode=year_mode,
                      title_limit=title_limit, suffix=suffix, windows=windows)
    candidate = folder / base
    conflict = owner(candidate)
    if conflict in (None, "current"):
        return candidate
    if conflict == "same":
        for number in range(2, 10000):
            candidate = with_ending(base, f"_dup{number}")
            if owner(candidate) is None:
                return candidate
        raise NameBudgetError("too many duplicate names")

    title_words = clean_field(meta.get("title", ""), " ").split()
    if "{title}" in PRESETS.get(template, (template,))[0] or "{shorttitle}" in PRESETS.get(template, (template,))[0]:
        for count in range(1, len(title_words) + 1):
            extension_room = _measure(word_sep.join(title_words[:count]), windows)
            try:
                extended = build_name(meta, template, folder, word_sep=word_sep,
                                      year_mode=year_mode, title_limit=max(title_limit, extension_room),
                                      suffix=suffix, windows=windows, reserve=0)
            except NameBudgetError:
                break
            candidate = folder / extended
            if candidate.name == base:
                continue
            if owner(candidate) is None:
                return candidate
    for index in range(2, 10000):
        candidate = with_ending(base, "_" + _letter(index))
        if owner(candidate) is None:
            return candidate
    raise NameBudgetError("too many colliding names")
