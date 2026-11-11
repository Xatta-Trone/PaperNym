"""Desktop integration for each platform.

Start at login: the Windows Run key, a macOS LaunchAgent, or a Linux autostart .desktop file.
For pip/pipx installs, which have no installer: an app-menu entry on Linux, and a small
PaperNym.app launcher in ~/Applications on macOS.
"""

from __future__ import annotations

import os
import plistlib
import shlex
import sys
from pathlib import Path

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE = "PaperNym"
DESKTOP_ID = "papernym"  # papernym.desktop; the GUI sets the same desktop file name
MAC_LABEL = "io.github.xatta-trone.papernym"  # LaunchAgent label and app bundle identifier


def is_macos() -> bool:
    return sys.platform == "darwin"


def launch_command() -> str:
    """Command that starts the tray app minimised (frozen exe, or pythonw from a venv)."""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    exe = Path(sys.executable)
    windowless = exe.with_name("pythonw.exe")
    if os.name == "nt" and windowless.exists():
        exe = windowless
    return f'"{exe}" -m papernym.gui'


def launch_argv() -> list[str]:
    """The same command as a list (macOS LaunchAgent and app launcher)."""
    if getattr(sys, "frozen", False):
        return [sys.executable]
    return [sys.executable, "-m", "papernym.gui"]


def icon_path() -> Path:
    """The packaged 1024 px app icon (a .desktop Icon= may be an absolute path)."""
    return Path(__file__).resolve().parents[1] / "gui" / "icons" / "papernym.png"


def desktop_entry(command: str, *, autostart: bool = False) -> str:
    lines = ["[Desktop Entry]", "Type=Application", "Name=PaperNym", "GenericName=Paper renamer",
             "Comment=Rename research paper PDFs from their publication metadata",
             f"Exec={command}", f"Icon={icon_path()}", "Terminal=false",
             "Categories=Office;Education;Utility;", "Keywords=pdf;paper;rename;doi;arxiv;research;",
             "StartupWMClass=PaperNym"]
    if autostart:
        lines.append("X-GNOME-Autostart-enabled=true")
    return "\n".join(lines) + "\n"


def _write_if_changed(path: Path, data: str | bytes) -> bool:
    raw = data.encode("utf-8") if isinstance(data, str) else data
    try:
        if path.read_bytes() == raw:
            return False
    except OSError:
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return True


def _desktop_file() -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "autostart" / f"{DESKTOP_ID}.desktop"


def menu_file() -> Path:
    base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return base / "applications" / f"{DESKTOP_ID}.desktop"


def launch_agent_file() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{MAC_LABEL}.plist"


def launch_agent(argv: list[str]) -> bytes:
    """A per-user LaunchAgent that starts the tray app once when the user logs in."""
    return plistlib.dumps({
        "Label": MAC_LABEL,
        "ProgramArguments": argv,
        "RunAtLoad": True,
        "ProcessType": "Interactive",
        "LimitLoadToSessionType": "Aqua",  # the graphical login session only
    })


def _login_file() -> Path:
    return launch_agent_file() if is_macos() else _desktop_file()


def is_enabled() -> bool:
    if os.name == "nt":
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
                winreg.QueryValueEx(key, VALUE)
            return True
        except OSError:
            return False
    return _login_file().exists()


def set_enabled(enabled: bool) -> None:
    if os.name == "nt":
        import winreg

        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            if enabled:
                winreg.SetValueEx(key, VALUE, 0, winreg.REG_SZ, launch_command())
            else:
                try:
                    winreg.DeleteValue(key, VALUE)
                except FileNotFoundError:
                    pass
        return
    path = _login_file()
    if not enabled:
        path.unlink(missing_ok=True)
    elif is_macos():  # launchd reads it at the next login; nothing to load now
        _write_if_changed(path, launch_agent(launch_argv()))
    else:
        _write_if_changed(path, desktop_entry(launch_command(), autostart=True))


def app_bundle() -> Path:
    return Path.home() / "Applications" / "PaperNym.app"


def icns(png: bytes) -> bytes:
    """A one-image .icns holding the 1024 px PNG ("ic10"); macOS scales it for every size."""
    entry = b"ic10" + (8 + len(png)).to_bytes(4, "big") + png
    return b"icns" + (8 + len(entry)).to_bytes(4, "big") + entry


def _bundle_files(argv: list[str]) -> dict[str, bytes]:
    """Info.plist, the launcher script and the icon of ~/Applications/PaperNym.app."""
    from .. import __version__

    quoted = " ".join(shlex.quote(arg) for arg in argv)
    info = plistlib.dumps({
        "CFBundleName": "PaperNym",
        "CFBundleDisplayName": "PaperNym",
        "CFBundleIdentifier": MAC_LABEL,
        "CFBundleExecutable": "PaperNym",
        "CFBundleIconFile": "PaperNym",
        "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": __version__,
        "CFBundleVersion": __version__,
        "NSHighResolutionCapable": True,
    })
    # exec replaces the shell, so the app is this Python process; --show opens the window
    # (a second launch only asks the running copy to show its window).
    script = f'#!/bin/sh\nexec {quoted} --show "$@"\n'.encode("utf-8")
    return {"Contents/Info.plist": info, "Contents/MacOS/PaperNym": script,
            "Contents/Resources/PaperNym.icns": icns(icon_path().read_bytes())}


def needs_menu_entry() -> bool:
    """pip/pipx installs need their own launcher: an app-menu entry on Linux, an app in
    ~/Applications on macOS. The .deb and the Windows installer ship their own."""
    return (sys.platform.startswith("linux") or is_macos()) and not getattr(sys, "frozen", False)


def launcher_path() -> Path:
    """Where install_menu_entry() puts the launcher on this platform."""
    return app_bundle() if is_macos() else menu_file()


def install_menu_entry() -> bool:
    """Write (or refresh) the user's launcher. True if anything changed."""
    if not is_macos():
        return _write_if_changed(menu_file(), desktop_entry(launch_command() + " --show"))
    changed = False
    for name, data in _bundle_files(launch_argv()).items():
        changed |= _write_if_changed(app_bundle() / name, data)
    script = app_bundle() / "Contents/MacOS/PaperNym"
    if script.stat().st_mode & 0o777 != 0o755:
        script.chmod(0o755)
        changed = True
    return changed


def remove_menu_entry() -> bool:
    path = launcher_path()
    existed = path.exists()
    if path.is_dir():
        import shutil

        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)
    return existed


APP_KEY = r"Software\PaperNym"
INSTALLER_VALUE = "InstallerStartAtLogin"


def take_installer_choice() -> bool | None:
    """The installer's "Start at login" answer, read once and then removed (Windows only).

    The installer writes the Run key itself and leaves this marker (1 or 0), so the app can
    adopt the choice into its settings instead of undoing it on the next start.
    """
    if os.name != "nt":
        return None
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, APP_KEY, 0,
                            winreg.KEY_READ | winreg.KEY_SET_VALUE) as key:
            value, _ = winreg.QueryValueEx(key, INSTALLER_VALUE)
            winreg.DeleteValue(key, INSTALLER_VALUE)
    except OSError:
        return None
    return bool(value)
