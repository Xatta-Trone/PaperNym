r"""Crop the supplied tray sheet into one PNG per tray state (run once after art changes).

    .venv\Scripts\python.exe scripts\make_tray_icons.py
"""

from pathlib import Path
import shutil

from PySide6.QtGui import QImage

ROOT = Path(__file__).resolve().parents[1]
SHEET = ROOT / "assets" / "papernym-tray-sheet.png"
OUT = ROOT / "src" / "papernym" / "gui" / "icons"
STATES = ("watching", "paused", "working", "attention", "error")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    sheet = QImage(str(SHEET))
    assert not sheet.isNull(), SHEET
    for row, suffix in ((48, ""), (352, "-white"), (656, "-mono")):
        for column, state in enumerate(STATES):
            tile = sheet.copy(48 + 304 * column, row, 256, 256)
            tile.save(str(OUT / f"tray-{state}{suffix}.png"))
    shutil.copy2(ROOT / "assets" / "papernym-icon.ico", OUT / "papernym.ico")
    shutil.copy2(ROOT / "assets" / "papernym-icon-1024.png", OUT / "papernym.png")


if __name__ == "__main__":
    main()
