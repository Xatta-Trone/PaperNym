# PyInstaller spec: one folder, two programs sharing it.
#   PaperNym.exe  windowed tray app (same options as `papernym-gui`)
#   papernym.exe  console command-line interface (same as `papernym`)
# Run through scripts/build_windows.py, which writes build/version_info.txt first.
# On Windows the two names differ only in case, so the console one is papernym-cli.exe
# in the folder and the installer adds a `papernym.cmd` shim so `papernym` works in cmd.

import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(SPECPATH).parent
ICON = str(ROOT / "src" / "papernym" / "gui" / "icons" / "papernym.ico")
VERSION_FILE = os.environ.get("PAPERNYM_VERSION_FILE")

datas = collect_data_files("papernym")
# keyring finds its backends through entry points; bundle the Windows one explicitly.
hidden = (collect_submodules("keyring.backends")
          + collect_submodules("win32ctypes"))
excludes = ["tkinter", "pytest", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
            "PySide6.Qt3DCore", "PySide6.QtQuick", "PySide6.QtQml", "PySide6.QtMultimedia",
            "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtPdf"]


def analysis(script):
    return Analysis([str(ROOT / "packaging" / script)], pathex=[str(ROOT / "src")], datas=datas,
                    hiddenimports=hidden, excludes=excludes, noarchive=False)


# Qt parts the app never uses (about 35 MB): software OpenGL, the virtual keyboard and the
# Qt Quick/QML stack it pulls in, PDF rendering, and Qt's own translations.
DROP = ("opengl32sw.dll", "qt6pdf.dll", "qpdf.dll", "qtvirtualkeyboardplugin.dll",
        "qt6virtualkeyboard.dll", "qt6quick.dll", "qt6qml", "/translations/", "\\translations\\",
        # Windows ships icuuc.dll in System32; a copy found on PATH (Anaconda) breaks Qt6Core.
        "icuuc", "icudt", "icuin")


def trim(entries):
    return [entry for entry in entries
            if not any(part in entry[0].replace("\\", "/").lower() + "/" or
                       part in entry[0].lower() for part in DROP)]


gui = analysis("launch_gui.py")
cli = analysis("launch_cli.py")
for item in (gui, cli):
    item.binaries = trim(item.binaries)
    item.datas = trim(item.datas)

gui_exe = EXE(PYZ(gui.pure), gui.scripts, [], exclude_binaries=True, name="PaperNym",
              icon=ICON, version=VERSION_FILE, console=False, upx=False)
cli_exe = EXE(PYZ(cli.pure), cli.scripts, [], exclude_binaries=True, name="papernym-cli",
              icon=ICON, version=VERSION_FILE, console=True, upx=False)

COLLECT(gui_exe, gui.binaries, gui.datas, cli_exe, cli.binaries, cli.datas,
        name="PaperNym", upx=False)
