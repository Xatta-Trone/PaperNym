"""Start PaperNym at login: Windows Run key, or a Linux autostart .desktop file."""

from __future__ import annotations

import os
import sys
from pathlib import Path

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE = "PaperNym"


def launch_command() -> str:
    """Command that starts the tray app minimised (frozen exe, or pythonw from a venv)."""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    exe = Path(sys.executable)
    windowless = exe.with_name("pythonw.exe")
    if os.name == "nt" and windowless.exists():
        exe = windowless
    return f'"{exe}" -m papernym.gui'


def _desktop_file() -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "autostart" / "papernym.desktop"


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
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("[Desktop Entry]\nType=Application\nName=PaperNym\n"
                        f"Exec={launch_command()}\nX-GNOME-Autostart-enabled=true\n", encoding="utf-8")
    else:
        path.unlink(missing_ok=True)


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

