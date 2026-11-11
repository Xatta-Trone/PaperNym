"""Validated settings stored in the per-user PaperNym directory."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Callable

from .naming import PRESETS, TemplateError, validate_template


DEFAULTS = {
    "folders": [],
    "exclude": ["*draft*", "*_v[0-9]*", "Manuscripts/"],
    "format": "{year}_{author}_{title}",
    "word_sep": "_",
    "title_limit": 0,
    "year": "citation",
    "title_search": True,
    "openalex_key": "",
    "s2_key": "",
    "email": "",
    "start_at_login": False,
    "notify_on_rename": True,
    "paused": False,
}

class ConfigError(ValueError):
    """Settings could not be loaded or validated."""


def settings_dir(home: str | Path | None = None) -> Path:
    """Return the settings directory without creating it."""
    if home is not None:
        return Path(home).expanduser()
    if os.environ.get("PAPERNYM_HOME"):
        return Path(os.environ["PAPERNYM_HOME"]).expanduser()
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "PaperNym"


def default_config() -> dict:
    """Return independent mutable defaults for each caller."""
    return {key: value.copy() if isinstance(value, list) else value for key, value in DEFAULTS.items()}


def _validate_template(template: str) -> None:
    if template in PRESETS:
        return  # A fixed preset stored by name (needed for citekey capitalisation).
    try:
        validate_template(template)
    except TemplateError as exc:
        raise ConfigError(f"invalid format: {exc}") from exc


def validate_config(config: dict) -> dict:
    """Return a complete validated copy; reject invalid settings explicitly."""
    if not isinstance(config, dict):
        raise ConfigError("config must be a JSON object")
    unknown = set(config) - set(DEFAULTS)
    if unknown:
        raise ConfigError(f"unknown config keys: {', '.join(sorted(unknown))}")
    result = default_config()
    result.update(config)
    if not isinstance(result["folders"], list):
        raise ConfigError("folders must be a list")
    for folder in result["folders"]:
        if (not isinstance(folder, dict) or set(folder) != {"path", "recursive"}
                or not isinstance(folder["path"], str) or not folder["path"]
                or type(folder["recursive"]) is not bool):
            raise ConfigError("each folder needs a nonempty path and boolean recursive")
    if not isinstance(result["exclude"], list) or any(not isinstance(x, str) for x in result["exclude"]):
        raise ConfigError("exclude must be a list of strings")
    if not isinstance(result["format"], str):
        raise ConfigError("format must be a string")
    _validate_template(result["format"])
    if result["word_sep"] not in ("_", " ", "-", ""):
        raise ConfigError("word_sep must be _, space, -, or empty")
    if type(result["title_limit"]) is not int or result["title_limit"] < 0:
        raise ConfigError("title_limit must be a nonnegative integer")
    if result["year"] not in ("citation", "online"):
        raise ConfigError("year must be citation or online")
    for key in ("title_search", "start_at_login", "notify_on_rename", "paused"):
        if type(result[key]) is not bool:
            raise ConfigError(f"{key} must be a boolean")
    for key in ("openalex_key", "s2_key", "email"):
        if not isinstance(result[key], str):
            raise ConfigError(f"{key} must be a string")
    return result


def load_config(home: str | Path | None = None, *, apply_env: bool = True) -> dict:
    """Load settings, applying environment API keys in memory only.

    Callers that modify and save settings pass ``apply_env=False`` so environment
    keys are never written to config.json.
    """
    path = settings_dir(home) / "config.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raw = {}
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"cannot read {path}: {exc}") from exc
    result = validate_config(raw)
    if not apply_env:
        return result
    for variable, key in (("OPENALEX_API_KEY", "openalex_key"), ("S2_API_KEY", "s2_key")):
        if variable in os.environ:
            result[key] = os.environ[variable]
    return result


def save_config(config: dict, home: str | Path | None = None) -> None:
    """Atomically replace config.json after validation."""
    validated = validate_config(config)
    directory = settings_dir(home)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "config.json"
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=directory,
                                         prefix=".config-", suffix=".tmp", delete=False) as stream:
            temp_path = Path(stream.name)
            json.dump(validated, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_path, path)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def _within(child: str | Path, parent: str | Path) -> bool:
    child_key = os.path.normcase(os.path.abspath(os.fspath(child)))
    parent_key = os.path.normcase(os.path.abspath(os.fspath(parent)))
    try:
        return os.path.commonpath((child_key, parent_key)) == parent_key
    except ValueError:
        return False


def add_folder(config: dict, path: str | Path, *, recursive: bool = True,
               on_warning: Callable[[str], None] | None = None) -> dict:
    """Return settings with a folder added, merged, or rejected for overlap."""
    root = Path(path).expanduser().resolve()
    if not root.is_dir():
        raise ConfigError(f"not a folder: {root}")
    result = validate_config(config)
    folders = [dict(folder) for folder in result["folders"]]
    same = next((folder for folder in folders if _within(root, folder["path"])
                 and _within(folder["path"], root)), None)
    if same:
        folders.remove(same)
    for folder in folders:
        if folder["recursive"] and _within(root, folder["path"]):
            raise ConfigError(f"{root} is already inside recursive watched folder {folder['path']}")
    if recursive:
        folders = [folder for folder in folders if not _within(folder["path"], root)]
    folders.append({"path": str(root), "recursive": recursive})
    result["folders"] = folders
    lower = str(root).replace("\\", "/").lower()
    if "zotero/storage" in lower or "mendeley" in lower or "endnote" in lower:
        if on_warning:
            on_warning("Reference-manager storage detected; renaming files there may break its links.")
    return result
