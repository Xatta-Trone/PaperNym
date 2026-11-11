"""Check GitHub for a newer release. Never downloads or installs anything.

One unauthenticated GET to the GitHub releases API; the request carries only a generic
``PaperNym/<version>`` user agent (no email, folders or ids).
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass

from papernym import __version__

REPO = "Xatta-Trone/PaperNym"
PROJECT_URL = f"https://github.com/{REPO}"
RELEASES_URL = f"{PROJECT_URL}/releases"
ISSUES_URL = f"{PROJECT_URL}/issues"
LICENSE_URL = f"{PROJECT_URL}/blob/main/LICENSE"
DEVELOPER_URL = "https://github.com/Xatta-Trone"
LATEST_API = f"https://api.github.com/repos/{REPO}/releases/latest"
CHECK_EVERY_S = 24 * 60 * 60
FIRST_CHECK_AFTER_MS = 30_000


@dataclass
class UpdateInfo:
    current: str
    latest: str | None = None     # None: no release published yet
    url: str = RELEASES_URL
    newer: bool = False


def parse_version(text: str) -> tuple[int, ...] | None:
    """``v0.10.2`` -> (0, 10, 2); None when the tag is not a plain version."""
    match = re.fullmatch(r"v?(\d+(?:\.\d+)*)", (text or "").strip())
    return tuple(int(part) for part in match.group(1).split(".")) if match else None


def is_newer(latest: str, current: str) -> bool:
    new, old = parse_version(latest), parse_version(current)
    if new is None or old is None:
        return False
    width = max(len(new), len(old))
    return new + (0,) * (width - len(new)) > old + (0,) * (width - len(old))


def check(http_get, current: str = __version__) -> UpdateInfo:
    """Ask GitHub for the latest release. ``http_get`` errors (offline etc.) propagate."""
    data = http_get(LATEST_API, headers={"Accept": "application/vnd.github+json"})
    info = UpdateInfo(current)
    if not data:  # 404: the repository has no published release yet
        return info
    tag = str(data.get("tag_name") or "")
    info.latest = tag.lstrip("v") or None
    info.url = data.get("html_url") or RELEASES_URL
    info.newer = bool(info.latest) and is_newer(tag, current)
    return info


def how_to_update() -> str:
    """The installed app downloads the installer; a source or pip install upgrades with pip."""
    if getattr(sys, "frozen", False):
        return "Download the new installer from the release page and run it."
    return "Update with:  pip install -U papernym   (or git pull for a source checkout)"
