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
from .window import MainWindow
from .worker import Worker

log = logging.getLogger("papernym")
REPO_SAMPLES = Path(__file__).resolve().parents[3] / "sample_pdfs"
OUTAGE = ("Metadata services unreachable; new papers are marked _CHECK and will be fixed "
          "automatically.")


class Controller(QObject):
    """Glue between the worker thread, the tray icon and the main window."""

    config_changed = Signal(dict)
    attention_changed = Signal(list)
    history_changed = Signal()

    def __init__(self, home: Path, *, sandbox: bool = False, welcome_folders: list[str] | None = None,
                 http_get=None, worker_kwargs: dict | None = None, first_run: bool | None = None,
                 interactive: bool = True):
        super().__init__()
        self.home = Path(home)
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
        self._frame = False
        self.worker = Worker(self.home, http_get=http_get, **(worker_kwargs or {}))
        self._animation = QTimer(self, interval=600, timeout=self._animate)
        self._refresh = QTimer(self, singleShot=True, interval=300, timeout=self._refresh_lists)
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
        self.status("Watching." if self.config["folders"] else "Add a folder to start.")
        self.worker.call(lambda w: w.recent_history(300), self._history_loaded)
        self.window.folders.refresh_states()
        self.window.history.reload()
        self.refresh_attention()
        if self.first_run and self.interactive:
            QTimer.singleShot(0, self.run_welcome)

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
            self._scan_renamed = []
            self._scan_attention = 0
            self.update_tray()
        elif kind == "scan_finished":
            self.scanning = False
            self._scan_summary()
            self._refresh.start()
            self.update_tray()
        elif kind in ("renamed", "needs_check"):
            self.recent.insert(0, (event.get("old_path", ""), event.get("new_path", event["path"])))
            del self.recent[5:]
            if kind == "renamed" and event.get("source") != "pdf-only":
                self.window.outage.hide()
            name = short(event.get("new_path", event["path"]))
            if self.scanning:
                self._scan_renamed.append(name)
                self._scan_attention += kind == "needs_check"
            elif kind == "renamed":
                self.notify("Paper renamed", name)
            else:
                self.notify("Paper needs checking", f"{name}\nNamed offline; it will be re-checked.")
            self._refresh.start()
        elif kind == "unidentified":
            if self.scanning:
                self._scan_attention += 1
            else:
                self.notify("Paper not identified", short(event["path"]))
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

    def _scan_summary(self):
        renamed = len(self._scan_renamed)
        if renamed == 1:
            self.notify("Paper renamed", self._scan_renamed[0])
        elif renamed > 1:
            listed = "\n".join(self._scan_renamed[:3]) + ("\n..." if renamed > 3 else "")
            self.notify(f"{renamed} papers renamed", listed)
        if self._scan_attention:
            self.notify("Papers need attention",
                        f"{self._scan_attention} file(s) need attention; open PaperNym to review.")

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
        box = QMessageBox(self.window)
        box.setWindowTitle("Add folder")
        text = f"{info['path']}\n\nThis folder contains {info['count']} PDF(s)."
        if info["warnings"]:
            text += "\n\nWarning: " + " ".join(info["warnings"])
        box.setText(text)
        preview = box.addButton("&Preview first", QMessageBox.AcceptRole)
        now = box.addButton("&Add and rename now", QMessageBox.YesRole)
        box.addButton(QMessageBox.Cancel)
        box.setDefaultButton(preview)
        box.exec()
        if box.clickedButton() is now:
            self.save_settings(info["config"], lambda _: self.status(f"Watching {info['path']}"))
        elif box.clickedButton() is preview:
            folder = info["config"]["folders"][-1]
            self.status("Preparing preview...")
            self.worker.call(lambda w: w.preview_folders([folder], info["config"]),
                             lambda items: self._preview_then_apply(items, info["config"]), self.error)

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
        wizard = WelcomeWizard(self.welcome_folders, self.window)
        if not wizard.exec():
            self.save_settings(self.config, lambda _: self.status("Add a folder to start."))
            return
        folders, preset, key = wizard.folders(), wizard.chosen_preset(), wizard.openalex_key()

        def build(w):
            warnings = []
            config = w.stored_config()
            config.update({"format": preset, "word_sep": PRESETS[preset][1], "openalex_key": key})
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

def make_sandbox() -> tuple[Path, Path, int]:
    """Fresh temporary settings folder plus a temporary copy of sample_pdfs/."""
    root = Path(tempfile.mkdtemp(prefix="papernym-sandbox-"))
    home, papers = root / "settings", root / "papers"
    home.mkdir()
    papers.mkdir()
    count = 0
    if REPO_SAMPLES.is_dir():
        for pdf in sorted(REPO_SAMPLES.glob("*.pdf")):
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
    if args.sandbox:
        home, papers, count = make_sandbox()
        os.environ["PAPERNYM_HOME"] = str(home)
        welcome = [str(papers)]
        log.info("sandbox: settings %s, papers %s (%d sample PDFs)", home, papers, count)
    home = settings_dir()
    name = server_name(home)
    if signal_existing(name):
        log.info("PaperNym is already running; asked it to show its window")
        return 0
    server = QLocalServer()
    if not server.listen(name):
        QLocalServer.removeServer(name)
        server.listen(name)
    setup_file_log(home, logging.DEBUG if args.debug else logging.INFO)
    try:
        ctl = Controller(home, sandbox=args.sandbox, welcome_folders=welcome)
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
