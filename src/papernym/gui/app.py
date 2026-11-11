"""Tray application entry point: ``papernym-gui [--sandbox] [--show] [--debug]``."""

from __future__ import annotations

import argparse
import copy
import hashlib
import logging
import os
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QAction
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon

from ..core import autostart
from ..core.config import ConfigError, add_folder, load_config, settings_dir
from ..core.logsetup import setup_file_log
from ..core.naming import PRESETS
from .common import app_icon, short, show_in_folder, tray_icon
from .dialogs import PreviewDialog, WelcomeWizard
from . import theme
from ..core import updates
from ..core.sources.http import HttpClient
from .window import MainWindow
from .worker import Worker

log = logging.getLogger("papernym")
REPO_SAMPLES = Path(__file__).resolve().parents[3] / "sample_pdfs"
TOAST_QUIET_MS = 4000   # one toast after this much quiet...
TOAST_MAX_WAIT = 20     # ...or at least every 20 s while files keep arriving
OUTAGE = ("Metadata services unreachable; new papers are marked _CHECK and will be fixed "
          "automatically.")


class UpdateRelay(QObject):
    """Carries an update-check result from its thread back to the UI thread."""

    finished = Signal(object, str, bool)  # UpdateInfo or None, error text, manual


class Controller(QObject):
    """Glue between the worker thread, the tray icon and the main window."""

    config_changed = Signal(dict)
    attention_changed = Signal(list)
    history_changed = Signal()

    def __init__(self, home: Path, *, sandbox: bool = False, welcome_folders: list[str] | None = None,
                 http_get=None, worker_kwargs: dict | None = None, first_run: bool | None = None,
                 interactive: bool = True, debug: bool = False):
        super().__init__()
        self.home = Path(home)
        self.debug = debug  # only debug mode shows where the settings folder is
        self.sandbox = sandbox
        self.http_get = http_get
        self.interactive = interactive
        self.quitting = False
        self.first_run = (not (self.home / "config.json").exists()) if first_run is None else first_run
        self.welcome_folders = welcome_folders or []
        self.config = load_config(self.home, apply_env=False)
        self.scanning = False
        self.attention_count = 0
        self.key_problem = None
        self.folder_states: dict[str, bool] = {}
        self.recent: list[tuple[str, str]] = []
        self._scan_renamed: list[str] = []
        self._scan_attention = 0
        self._toast_since: float | None = None
        self._frame = False
        self.worker = Worker(self.home, http_get=http_get, **(worker_kwargs or {}))
        self._animation = QTimer(self, interval=600, timeout=self._animate)
        self._refresh = QTimer(self, singleShot=True, interval=300, timeout=self._refresh_lists)
        self._toast_timer = QTimer(self, singleShot=True, interval=TOAST_QUIET_MS, timeout=self._flush_toast)
        self.update_info = None
        self.login_default = True  # the welcome wizard's Start-at-login tick (the installer may change it)
        self._update_checking = False
        self._update_result = UpdateRelay(self)
        self._update_result.finished.connect(self._update_checked)
        self._update_timer = QTimer(self, interval=updates.CHECK_EVERY_S * 1000,
                                    timeout=lambda: self.check_updates(manual=False))
        self._theme = None
        self.apply_theme()
        hints = QApplication.styleHints()
        if hasattr(hints, "colorSchemeChanged"):
            hints.colorSchemeChanged.connect(lambda _: self.apply_theme(force=True))
        self.config_changed.connect(lambda _: self.apply_theme())
        self.window = MainWindow(self)
        self._build_tray()
        self.worker.event.connect(self.on_event)
        self.worker.ready.connect(self.on_ready)
        self.worker.fatal.connect(self.on_fatal)
        self.config_changed.emit(self.config)
        self.worker.start()

    # Tray --------------------------------------------------------------------------
    def _build_tray(self):
        self.tray = QSystemTrayIcon(tray_icon("watching"), self)
        menu = QMenu()
        menu.addAction("&Open PaperNym", self.show_window)
        self.pause_action = menu.addAction("&Pause watching", self.toggle_pause)
        menu.addAction("&Scan now", self.scan_now)
        self.recent_menu = menu.addMenu("&Recent renames")
        self.recent_menu.aboutToShow.connect(self._fill_recent)
        menu.addAction("&Undo last rename", self.undo_last)
        self.attention_action = menu.addAction("&Needs attention (0)",
                                               lambda: self.show_window(self.window.attention))
        menu.addAction("Se&ttings", lambda: self.show_window(self.window.folders))
        menu.addAction("A&bout PaperNym", lambda: self.show_window(self.window.about))
        self.update_action = menu.addAction("Update available", lambda: self.show_window(self.window.about))
        self.update_action.setVisible(False)
        menu.addSeparator()
        menu.addAction("&Quit", self.quit)
        self.tray_menu = menu
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._tray_activated)
        self.tray.messageClicked.connect(lambda: self.show_window())
        self.tray.show()
        self.update_tray()

    def _tray_activated(self, reason):
        wanted = (QSystemTrayIcon.DoubleClick if sys.platform == "win32" else QSystemTrayIcon.Trigger)
        if reason == wanted:
            self.show_window()

    def _fill_recent(self):
        self.recent_menu.clear()
        if not self.recent:
            self.recent_menu.addAction("(none yet)").setEnabled(False)
        for old, new in self.recent[:5]:
            action = self.recent_menu.addAction(f"{short(old)} -> {short(new)}")
            action.triggered.connect(lambda _=False, p=new: show_in_folder(p))

    def tray_state(self) -> tuple[str, str]:
        folders = self.config["folders"]
        if self.scanning:
            return "working", "scanning"
        if folders and self.folder_states and not any(self.folder_states.values()):
            return "error", "no watched folder is reachable"
        if self.config["paused"]:
            return "paused", "paused"
        if self.attention_count or self.key_problem:
            parts = []
            if self.attention_count:
                parts.append(f"{self.attention_count} file(s) need attention")
            if self.key_problem:
                parts.append("an API key was rejected")
            return "attention", ", ".join(parts)
        return "watching", f"watching {len(folders)} folder(s)" if folders else "no folders yet"

    def update_tray(self):
        state, text = self.tray_state()
        if state == "working":
            if not self._animation.isActive():
                self._animation.start()
        else:
            self._animation.stop()
            self.tray.setIcon(tray_icon(state))
        self.tray.setToolTip(f"PaperNym{' [SANDBOX]' if self.sandbox else ''}: {text}")
        self.pause_action.setText("&Resume watching" if self.config["paused"] else "&Pause watching")
        self.attention_action.setText(f"&Needs attention ({self.attention_count})")
        self.window.set_attention_count(self.attention_count)

    def _animate(self):
        self._frame = not self._frame
        self.tray.setIcon(tray_icon("working" if self._frame else "watching"))

    def notify(self, title: str, text: str, critical: bool = False):
        if self.config.get("notify_on_rename", True) and self.tray.supportsMessages():
            icon = QSystemTrayIcon.Warning if critical else QSystemTrayIcon.Information
            self.tray.showMessage(title, text, icon, 6000)

    # Worker signals ---------------------------------------------------------------
    def on_ready(self):
        if self.interactive and not self.sandbox:
            self.adopt_installer_login()
        if self.interactive and not self.sandbox and not self.first_run:
            self.sync_start_at_login()
        self.status("Watching." if self.config["folders"] else "Add a folder to start.")
        self.worker.call(lambda w: w.recent_history(5000), self._history_loaded)
        self.window.folders.refresh_states()
        self.window.history.reload()
        self.refresh_attention()
        if self.first_run and self.interactive:
            QTimer.singleShot(0, self.run_welcome)
        if self.interactive:
            QTimer.singleShot(updates.FIRST_CHECK_AFTER_MS, lambda: self.check_updates(manual=False))
            self._update_timer.start()

    # Updates -----------------------------------------------------------------------
    def check_updates(self, manual: bool = True):
        """Ask GitHub for the latest release on a short background thread."""
        if self._update_checking or (not manual and not self.config.get("update_check", True)):
            return
        self._update_checking = True
        self.window.about.show_checking()
        get = self.http_get or HttpClient({"email": ""}).get  # no email for GitHub
        relay = self._update_result

        def run():
            try:
                relay.finished.emit(updates.check(get), "", manual)
            except Exception as exc:  # offline, rate limit, bad answer: report, never crash
                relay.finished.emit(None, str(exc), manual)

        threading.Thread(target=run, name="papernym-update-check", daemon=True).start()

    def _update_checked(self, info, error: str, manual: bool):
        self._update_checking = False
        if error:
            log.info("update check failed: %s", error)
        else:
            self.update_info = info
        self.window.about.show_update(info, error)
        newer = info is not None and info.newer
        self.update_action.setVisible(newer)
        if newer:
            self.update_action.setText(f"Update available: v{info.latest}")
            if manual or info.latest != self.config.get("skipped_version"):
                self.window.update_banner.show_update(info)
        elif manual and not error:
            self.status("PaperNym is up to date." if info.latest else "No release has been published yet.")

    def skip_version(self, version: str):
        config = copy.deepcopy(self.config)
        config["skipped_version"] = version
        self.save_settings(config, lambda _: self.status(f"You will not be reminded about v{version} again."))

    def _history_loaded(self, rows):
        self.window.activity.load_history(rows)
        self.recent = [(row["old_path"], row["new_path"]) for row in rows if not row["undone"]][:5]

    def on_fatal(self, message: str):
        log.error("cannot start: %s", message)
        if self.interactive:
            QMessageBox.critical(None, "PaperNym", f"PaperNym cannot start:\n\n{message}")
        self.quit()

    def on_event(self, event: dict):
        kind = event["type"]
        if kind == "scan_started":
            self.scanning = True
            self._toast_timer.stop()
            self.update_tray()
        elif kind == "scan_finished":
            self.scanning = False
            self._flush_toast()
            self._refresh.start()
            self.update_tray()
        elif kind in ("renamed", "needs_check"):
            self.recent.insert(0, (event.get("old_path", ""), event.get("new_path", event["path"])))
            del self.recent[5:]
            if kind == "renamed" and event.get("source") != "pdf-only":
                self.window.outage.hide()
            self._queue_toast(short(event.get("new_path", event["path"])), kind == "needs_check")
            self._refresh.start()
        elif kind == "unidentified":
            self._queue_toast(None, True)
            self._refresh.start()
        elif kind == "undo":
            self._refresh.start()
        elif kind == "source_unavailable":
            message = event.get("message", "")
            if "key rejected" in message or "HTTP 401" in message or "HTTP 403" in message:
                self.key_problem = message
                self.window.sources.show_rejected(message)
                self.update_tray()
            else:
                self.window.outage.show_message(OUTAGE)
        elif kind == "settings_reloaded":
            self.reload_config()
        elif kind == "error":
            self.status(event.get("message", "Error"))

    def _queue_toast(self, renamed_name: str | None, attention: bool):
        """Collect renames; one toast after a quiet spell, at the end of a scan, or every 20 s."""
        if renamed_name:
            self._scan_renamed.append(renamed_name)
        self._scan_attention += bool(attention)
        if self._toast_since is None:
            self._toast_since = time.monotonic()
        if self.scanning:
            return
        if time.monotonic() - self._toast_since >= TOAST_MAX_WAIT:
            self._flush_toast()
        else:
            self._toast_timer.start()

    def _flush_toast(self):
        self._toast_timer.stop()
        renamed, attention = len(self._scan_renamed), self._scan_attention
        self._scan_renamed, self._scan_attention, self._toast_since = [], 0, None
        if not renamed and not attention:
            return
        lines = []
        if renamed == 1:
            title = "Paper renamed"
            lines.append(self._last_names(1))
        elif renamed:
            title = f"{renamed} papers renamed"
        else:
            title = "Papers need attention"
        if attention:
            lines.append(f"{attention} file(s) need attention; open PaperNym to review.")
        self.notify(title, "\n".join(line for line in lines if line) or "Open PaperNym to see them.")

    def _last_names(self, count: int) -> str:
        return "\n".join(name for _, name in ((o, short(n)) for o, n in self.recent[:count]))

    def _refresh_lists(self):
        self.refresh_attention()
        self.history_changed.emit()

    # Actions used by the tabs ----------------------------------------------------
    def status(self, text: str):
        self.window.statusBar().showMessage(text, 15000)
        log.info(text)

    def error(self, message: str):
        self.status(f"Error: {message}")
        if self.interactive:
            QMessageBox.warning(self.window, "PaperNym", message)

    def show_window(self, tab=None):
        if tab is not None:
            self.window.show_tab(tab)
        self.window.bring_to_front()

    def refresh_attention(self):
        def done(rows):
            self.attention_count = len(rows)
            self.attention_changed.emit(rows)
            self.update_tray()

        self.worker.call(lambda w: w.attention(), done)

    def folder_states_changed(self, states: dict):
        self.folder_states = states
        self.update_tray()

    def apply_theme(self, force: bool = False):
        mode = self.config.get("theme", "system")
        if force and mode != "system":
            return
        if mode != self._theme or force:
            self._theme = mode
            theme.apply(QApplication.instance(), mode)

    def reload_config(self):
        self.worker.call(lambda w: w.stored_config(), self._set_config)

    def _set_config(self, config: dict):
        self.config = config
        self.config_changed.emit(config)
        self.update_tray()

    def save_settings(self, config: dict, on_done=None):
        def done(saved):
            self._set_config(saved)
            self.window.folders.refresh_states()
            if on_done:
                on_done(saved)

        self.worker.call(lambda w: w.apply_config(config), done,
                         lambda message: (self.error(message), self.config_changed.emit(self.config)))

    def scan_now(self):
        self.status("Scanning...")
        self.worker.call(lambda w: w.scan_now(), None, self.error)

    def toggle_pause(self):
        paused = not self.config["paused"]
        self.worker.call(lambda w: w.set_paused(paused), self._set_config, self.error)

    def undo_last(self):
        self.worker.call(lambda w: w.engine.undo(last=1), self.after_undo, self.error)

    def after_undo(self, counts: dict):
        if counts["undone"]:
            self.status(f"Undone: {counts['undone']} rename(s).")
        elif counts["skipped"]:
            self.status("Could not undo: the file was moved, is missing, or its old name is taken.")
        else:
            self.status("Nothing to undo.")
        self._refresh.start()

    def adopt_installer_login(self):
        """Take over the installer's Start-at-login answer (once) as the app setting."""
        try:
            choice = autostart.take_installer_choice()
        except OSError as exc:
            log.warning("cannot read the installer's start-at-login choice: %s", exc)
            return
        if choice is None:
            return
        self.login_default = choice
        if not self.first_run and choice != self.config["start_at_login"]:
            config = copy.deepcopy(self.config)
            config["start_at_login"] = choice
            self.config = config
            self.save_settings(config)

    def sync_start_at_login(self):
        """Keep the login entry matching the setting (and the current program path)."""
        try:
            if self.config["start_at_login"] or autostart.is_enabled():
                autostart.set_enabled(self.config["start_at_login"])
        except OSError as exc:
            log.warning("cannot update start at login: %s", exc)

    def set_start_at_login(self, enabled: bool):
        if self.sandbox:
            return
        try:
            autostart.set_enabled(enabled)
        except OSError as exc:
            self.error(f"Could not change start at login: {exc}")

    def add_folder_flow(self, path: str, recursive: bool = True):
        self.worker.call(lambda w: w.validate_new_folder(self.config, path, recursive),
                         self._confirm_folder, self.error)

    def _confirm_folder(self, info: dict):
        """Nothing is read or looked up until the user adds the folder here."""
        box = QMessageBox(self.window)
        box.setWindowTitle("Add folder")
        text = f"{info['path']}\n\nThis folder contains {info['count']} PDF(s)."
        if info["warnings"]:
            text += "\n\nWarning: " + " ".join(info["warnings"])
        text += ("\n\nAdd: PaperNym starts watching and renaming here now.\n"
                 "Add and preview: the folder is added and waits; you see the planned names "
                 "first and choose which files to rename.")
        box.setText(text)
        now = box.addButton("&Add", QMessageBox.YesRole)
        preview = box.addButton("Add and &preview", QMessageBox.AcceptRole)
        box.addButton(QMessageBox.Cancel)
        box.setDefaultButton(now)
        box.exec()
        if box.clickedButton() is now:
            self.save_settings(info["config"], lambda _: self.status(f"Added and watching {info['path']}"))
        elif box.clickedButton() is preview:
            path = info["config"]["folders"][-1]["path"]
            self.status(f"Added {path}; looking up {info['count']} PDF(s) for the preview "
                        "(nothing is renamed yet)...")
            self.worker.call(lambda w: w.add_held_folder(info["config"]), self._set_config, self.error)
            self.worker.call(lambda w: w.preview_held_folder(path),
                             lambda items: self._preview_added_folder(items, path), self.error)

    def _preview_added_folder(self, items: list[dict], path: str):
        self.window.folders.refresh_states()
        intro = ("The folder is added but nothing has been renamed. Ticked files will be renamed; "
                 "unticked files keep their names and PaperNym will leave them alone. "
                 "Closing this window removes the folder again.")
        if not items:
            intro = "No files need renaming here. New PDFs will be renamed as they arrive."
        dialog = PreviewDialog("Preview renames", intro, items, accept_text="&Rename ticked files",
                               parent=self.window)
        if dialog.exec():
            rename, keep = dialog.selected(), dialog.unselected()

            def apply(w):
                counts = w.apply_selection(rename, keep, None)
                w.release_folder(path)
                return counts

            self.worker.call(apply, lambda counts: (
                self.window.folders.refresh_states(),
                self.status(f"Watching {path}. Renamed {counts['renamed']}, kept {counts['kept']}.")),
                self.error)
        else:
            self.worker.call(lambda w: w.drop_folder(path), lambda saved: (
                self._set_config(saved), self.window.folders.refresh_states(),
                self.status(f"Preview closed; {path} was not added and nothing was renamed.")),
                self.error)

    def _preview_then_apply(self, items: list[dict], config: dict, *, paused_on_cancel: bool = False):
        intro = ("Nothing has been renamed yet. Ticked files will be renamed; unticked files keep "
                 "their names and PaperNym will leave them alone.")
        if not items:
            intro = "No files need renaming here. New PDFs will be renamed as they arrive."
        dialog = PreviewDialog("Preview renames", intro, items, accept_text="&Rename ticked files",
                               parent=self.window)
        if dialog.exec():
            rename, keep = dialog.selected(), dialog.unselected()
            self.worker.call(lambda w: w.apply_selection(rename, keep, config),
                             lambda counts: (self.reload_config(), self.window.folders.refresh_states(),
                                             self.status(f"Renamed {counts['renamed']}, kept {counts['kept']}.")),
                             self.error)
        elif paused_on_cancel:
            config = copy.deepcopy(config)
            config["paused"] = True
            self.save_settings(config, lambda _: self.window.notice.show_message(
                "Watching is paused, so nothing was renamed. Resume from the tray menu or the "
                "General tab when you are ready."))

    def offer_reformat(self):
        def counted(count):
            if count:
                self.worker.call(lambda w: w.preview_reformat(False),
                                 lambda items: self._reformat_dialog(items, count))
            else:
                self.status("Naming saved.")

        self.worker.call(lambda w: w.tool_named_count(), counted)

    def _reformat_dialog(self, items: list[dict], count: int):
        dialog = PreviewDialog("Apply to existing files?",
                               f"Apply the new naming to {count} existing file(s) named by PaperNym? "
                               "Files you renamed by hand are left alone.",
                               items, checkable=False, accept_text="&Apply", reject_text="&Not now",
                               include_manual=False, parent=self.window)
        dialog.include_manual_changed.connect(lambda include: self.worker.call(
            lambda w: w.preview_reformat(include), dialog.set_items))
        if dialog.exec():
            include = dialog.manual_box.isChecked()
            self.worker.call(lambda w: w.engine.reformat(include_manual=include),
                             lambda counts: (self.status("Existing files renamed."), self._refresh.start()),
                             self.error)
        else:
            self.status("Naming saved; existing files keep their names.")

    def run_welcome(self):
        wizard = WelcomeWizard(self.welcome_folders, self.window, allow_login=not self.sandbox,
                               login_default=self.login_default)
        if not wizard.exec():
            self.save_settings(self.config, lambda _: self.status("Add a folder to start."))
            return
        folders, preset, key = wizard.folders(), wizard.chosen_preset(), wizard.openalex_key()
        login = wizard.start_at_login()
        if login:
            self.set_start_at_login(True)

        def build(w):
            warnings = []
            config = w.stored_config()
            config.update({"format": preset, "word_sep": PRESETS[preset][1], "openalex_key": key,
                           "start_at_login": login})
            for folder in folders:
                config = add_folder(config, folder, recursive=True, on_warning=warnings.append)
            return config, warnings, w.preview_folders(config["folders"], config) if config["folders"] else []

        def built(result):
            config, warnings, items = result
            if warnings:
                self.window.notice.show_message("Warning: " + " ".join(dict.fromkeys(warnings)))
            if not config["folders"]:
                self.save_settings(config)
                return
            self._preview_then_apply(items, config, paused_on_cancel=True)

        self.show_window()
        self.status("Preparing preview...")
        self.worker.call(build, built, self.error)

    def quit(self):
        self.quitting = True
        self._animation.stop()
        self.tray.hide()
        self.worker.stop()
        self.window.close()
        app = QApplication.instance()
        if app is not None:
            app.quit()


# Start-up -------------------------------------------------------------------------

def sample_folder() -> Path | None:
    """sample_pdfs/ beside the source tree; for a built exe, PAPERNYM_SAMPLES or ./sample_pdfs."""
    for folder in (os.environ.get("PAPERNYM_SAMPLES"), REPO_SAMPLES, Path.cwd() / "sample_pdfs"):
        if folder and Path(folder).is_dir():
            return Path(folder)
    return None


def make_sandbox() -> tuple[Path, Path, int]:
    """Fresh temporary settings folder plus a temporary copy of sample_pdfs/."""
    root = Path(tempfile.mkdtemp(prefix="papernym-sandbox-"))
    home, papers = root / "settings", root / "papers"
    home.mkdir()
    papers.mkdir()
    count = 0
    samples = sample_folder()
    if samples is not None:
        for pdf in sorted(samples.glob("*.pdf")):
            shutil.copy2(pdf, papers / pdf.name)
            count += 1
    return home, papers, count


def _parent_pids() -> list[int]:
    """Ancestor process ids, nearest first (Windows only)."""
    import ctypes
    from ctypes import wintypes

    class Entry(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                    ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_void_p),
                    ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                    ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long),
                    ("dwFlags", wintypes.DWORD), ("szExeFile", ctypes.c_char * 260)]

    kernel32 = ctypes.windll.kernel32
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    snapshot = kernel32.CreateToolhelp32Snapshot(0x2, 0)
    parents = {}
    try:
        entry = Entry()
        entry.dwSize = ctypes.sizeof(Entry)
        ok = kernel32.Process32First(snapshot, ctypes.byref(entry))
        while ok:
            parents[entry.th32ProcessID] = entry.th32ParentProcessID
            ok = kernel32.Process32Next(snapshot, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snapshot)
    chain, pid = [], os.getpid()
    while pid in parents and parents[pid] and parents[pid] not in chain and len(chain) < 16:
        pid = parents[pid]
        chain.append(pid)
    return chain


def _attach_console():
    """Give a windowed (pythonw) launch a console for --debug output.

    The pip launcher chain has no console of its own, so attach to the nearest ancestor that
    has one (the terminal it was started from); open a new console only if none does.
    """
    if sys.platform != "win32" or (sys.stderr is not None and sys.stderr.isatty()):
        return
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        attached = any(kernel32.AttachConsole(pid) for pid in _parent_pids())
        if not attached:
            kernel32.AllocConsole()
        sys.stderr = open("CONOUT$", "w", encoding="utf-8", errors="replace", buffering=1)
        print("PaperNym debug log (close PaperNym from its tray menu to stop)", file=sys.stderr)
    except (AttributeError, OSError):
        pass


SANDBOX_SERVER = "PaperNym-sandbox-" + hashlib.sha1(os.path.expanduser("~").encode("utf-8")).hexdigest()[:8]


def server_name(home: Path) -> str:
    key = os.path.normcase(os.path.abspath(home)).encode("utf-8")
    return "PaperNym-" + hashlib.sha1(key).hexdigest()[:16]


def signal_existing(name: str) -> bool:
    """Ask a running instance to show its window; True if one answered."""
    socket = QLocalSocket()
    socket.connectToServer(name)
    if not socket.waitForConnected(500):
        return False
    socket.write(b"show\n")
    socket.flush()
    socket.waitForBytesWritten(500)
    socket.disconnectFromServer()
    return True


def parse_args(argv):
    parser = argparse.ArgumentParser(prog="papernym-gui", description="PaperNym tray application")
    parser.add_argument("--sandbox", action="store_true",
                        help="temporary settings and a temporary copy of sample_pdfs/; nothing real is touched")
    parser.add_argument("--show", action="store_true", help="open the main window at start")
    parser.add_argument("--debug", action="store_true", help="log to the console at debug level")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if args.debug:
        _attach_console()
        if sys.stderr is not None:
            handler = logging.StreamHandler(sys.stderr)
            handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
            log.addHandler(handler)
        log.setLevel(logging.DEBUG)
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("PaperNym")
    app.setQuitOnLastWindowClosed(False)
    app.setWindowIcon(app_icon())
    welcome = []
    # One sandbox at a time: each sandbox has a new temporary settings folder, so it gets a
    # fixed instance name instead of one derived from that folder (checked before creating it).
    name = SANDBOX_SERVER if args.sandbox else server_name(settings_dir())
    if signal_existing(name):
        log.info("PaperNym%s is already running; asked it to show its window",
                 " (sandbox)" if args.sandbox else "")
        return 0
    if args.sandbox:
        os.environ["PAPERNYM_KEYRING"] = "off"  # sandbox keys stay in its temporary folder
        home, papers, count = make_sandbox()
        os.environ["PAPERNYM_HOME"] = str(home)
        welcome = [str(papers)]
        log.info("sandbox: settings %s, papers %s (%d sample PDFs)", home, papers, count)
    home = settings_dir()
    server = QLocalServer()
    if not server.listen(name):
        QLocalServer.removeServer(name)
        server.listen(name)
    setup_file_log(home, logging.DEBUG if args.debug else logging.INFO)
    try:
        ctl = Controller(home, sandbox=args.sandbox, welcome_folders=welcome, debug=args.debug)
    except ConfigError as exc:
        QMessageBox.critical(None, "PaperNym", f"The settings file cannot be read:\n\n{exc}")
        return 1

    def on_connection():
        socket = server.nextPendingConnection()
        if socket is not None:
            socket.readyRead.connect(lambda: (socket.readAll(), ctl.show_window()))

    server.newConnection.connect(on_connection)
    if args.show or not QSystemTrayIcon.isSystemTrayAvailable():
        ctl.show_window()
    app.aboutToQuit.connect(lambda: ctl.worker.stop() if ctl.worker.isRunning() else None)
    return app.exec()


__all__ = ["Controller", "main", "make_sandbox"]
