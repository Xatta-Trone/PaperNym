"""Small UI helpers shared by the window, tabs and tray."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices, QIcon, QPixmap

ICONS = Path(__file__).resolve().parent / "icons"
TRAY_STATES = ("watching", "paused", "working", "attention", "error")

# Plain-text status names: status is never shown by colour alone.
EVENT_STATUS = {"renamed": "Renamed", "needs_check": "Check", "unidentified": "Not identified",
                "undo": "Undone", "busy": "Busy", "skipped": "Skipped", "preview": "Preview"}
FILE_STATUS = {"ok": "Named", "check": "Check (offline guess)", "unknown": "Not identified",
               "pending": "Rename pending", "unreadable": "Unreadable"}
REASONS = {"check": "Named from the PDF alone while services were unreachable; will be re-checked.",
           "unknown": "No source could identify this paper.",
           "pending": "Identified, but the file was locked; the rename will be retried.",
           "unreadable": "The PDF is password-protected or damaged."}

SAMPLE_PAPERS = (
    {"title": "Deep learning for crash severity prediction", "year": 2025, "year_online": 2024,
     "authors": ["Smith", "Jones", "Lee"], "journal": "Accid Anal Prev", "source": "sample"},
    {"title": "Attention is all you need", "year": 2017, "year_online": 2017,
     "authors": ["Vaswani", "Shazeer"], "journal": "NeurIPS", "source": "sample"},
    {"title": "Short-term demand forecasting in mobility-on-demand systems: a systematic review",
     "year": 2027, "year_online": 2026, "authors": ["Li"], "journal": "Transp Res Part C",
     "source": "sample"},
)


def app_icon() -> QIcon:
    icon = QIcon(str(ICONS / "papernym.ico"))
    icon.addFile(str(ICONS / "papernym.png"))
    return icon


def tray_icon(state: str) -> QIcon:
    return QIcon(QPixmap(str(ICONS / f"tray-{state}.png")))


def open_path(path: str | Path):
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


def show_in_folder(path: str | Path):
    """Open the containing folder with the file selected (Windows), or just the folder."""
    path = Path(path)
    if sys.platform == "win32" and path.exists():
        subprocess.Popen(["explorer", "/select,", str(path)])
    else:
        open_path(path.parent if path.suffix else path)


def short(path: str) -> str:
    return os.path.basename(path) if path else ""
