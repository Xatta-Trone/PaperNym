"""Desktop integration: Start at login (Windows Run key, or a Linux autostart .desktop file) and,
on Linux, the app-menu entry for pip/pipx installs."""

from __future__ import annotations

import os
import sys
from pathlib import Path

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE = "PaperNym"
DESKTOP_ID = "papernym"  # papernym.desktop; the GUI sets the same desktop file name


def launch_command() -> str:
    """Command that starts the tray app minimised (frozen exe, or pythonw from a venv)."""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    exe = Path(sys.executable)
    windowless = exe.with_name("pythonw.exe")
    if os.name == "nt" and windowless.exists():
        exe = windowless
    return f'"{exe}" -m papernym.gui'


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


def _write_if_changed(path: Path, text: str) -> bool:
    try:
        if path.read_text(encoding="utf-8") == text:
            return False
    except OSError:
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return True


def _desktop_file() -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "autostart" / f"{DESKTOP_ID}.desktop"


def menu_file() -> Path:
    base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return base / "applications" / f"{DESKTOP_ID}.desktop"


def is_enabled() -> bool:
    if os.name == "nt":
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
                winreg.QueryValueEx(key, VALUE)
            return True
        except OSError:
            return False
    return _desktop_file().exists()


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
    path = _desktop_file()
    if enabled:
        _write_if_changed(path, desktop_entry(launch_command(), autostart=True))
    else:
        path.unlink(missing_ok=True)


def needs_menu_entry() -> bool:
    """Linux pip/pipx installs need their own menu entry; the .deb and Windows ship one."""
    return sys.platform.startswith("linux") and not getattr(sys, "frozen", False)


def install_menu_entry() -> bool:
    """Write (or refresh) the user's app-menu entry. True if the file changed."""
    return _write_if_changed(menu_file(), desktop_entry(launch_command() + " --show"))


def remove_menu_entry() -> bool:
    path = menu_file()
    existed = path.exists()
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
