"""Background thread that owns the database, engine and watcher.

The UI never touches disk or network directly for PaperNym work: it submits jobs (functions
that receive the worker) and gets results back through Qt signals, which Qt delivers on the
UI thread.
"""

from __future__ import annotations

import csv
import itertools
import logging
import queue
import threading
import uuid
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, QThread, Signal

from ..core import engine as engine_module
from ..core.config import ConfigError, add_folder, load_config, save_config, with_env
from ..core.db import Database
from ..core.identify import Identifier
from ..core.lock import LockBusyError
from ..core.watcher import Watcher

log = logging.getLogger("papernym")

BUSY_MESSAGE = ("PaperNym is already renaming files from another window or from "
                "'papernym watch'. Quit that one first.")
ATTENTION = ("check", "unknown", "pending", "unreadable")


def _rows(rows) -> list[dict]:
    return [dict(row) for row in rows]


class Worker(QThread):
    """One thread, one queue: watcher events, timers and UI jobs run here in turn."""

    event = Signal(object)        # core event dict
    done = Signal(int, object)    # job id, result
    failed = Signal(int, str)     # job id, message
    fatal = Signal(str)           # could not start (lock busy, bad settings, bad database)
    ready = Signal()

    def __init__(self, home: Path, *, poll: bool = False, http_get: Callable | None = None,
                 read_pdf_fn: Callable | None = None, stable_fn: Callable | None = None,
                 observer=None, parent=None):
        super().__init__(parent)
        self.home = Path(home)
        self.poll = poll
        self.http_get = http_get
        self.read_pdf_fn = read_pdf_fn
        self.stable_fn = stable_fn
        self.observer = observer
        self.engine = None
        self.watcher = None
        self.db = None
        self._jobs: queue.Queue = queue.Queue()
        self._stop = threading.Event()
        self._ids = itertools.count(1)
        self._callbacks: dict[int, tuple[Callable | None, Callable | None]] = {}
        self.done.connect(self._dispatch_done)
        self.failed.connect(self._dispatch_failed)

    # UI-thread API --------------------------------------------------------------
    def call(self, function: Callable, on_done: Callable | None = None,
             on_fail: Callable | None = None) -> int:
        """Run ``function(worker)`` on the worker thread; callbacks run on the UI thread."""
        job = next(self._ids)
        self._callbacks[job] = (on_done, on_fail)
        self._jobs.put((job, function))
        return job

    def stop(self, timeout_ms: int = 15000):
        self._stop.set()
        self.wait(timeout_ms)

    def _dispatch_done(self, job: int, result):
        on_done, _ = self._callbacks.pop(job, (None, None))
        if on_done:
            on_done(result)

    def _dispatch_failed(self, job: int, message: str):
        _, on_fail = self._callbacks.pop(job, (None, None))
        if on_fail:
            on_fail(message)
        else:
            self.event.emit({"type": "error", "path": "", "message": message})

    # Worker thread --------------------------------------------------------------
    def _emit(self, event: dict):
        log.info("%s %s", event.get("type"), event.get("message", ""))
        self.event.emit(dict(event))

    def run(self):
        try:
            self.db = Database(self.home)
            config = load_config(self.home)
            identifier = Identifier(config, http_get=self.http_get, db=self.db, on_event=self._emit)
            kwargs = {"stable_fn": self.stable_fn or engine_module.stable_file}
            if self.read_pdf_fn:
                kwargs["read_pdf_fn"] = self.read_pdf_fn
            self.engine = engine_module.Engine(config, self.db, identifier, on_event=self._emit, **kwargs)
            self.watcher = Watcher(self.engine, poll=self.poll, observer=self.observer)
            self.watcher.start()
        except LockBusyError:
            self._close_db()
            self.fatal.emit(BUSY_MESSAGE)
            return
        except Exception as exc:  # settings, database or folder errors must reach the user
            log.exception("worker failed to start")
            self._close_db()
            self.fatal.emit(str(exc))
            return
        self.ready.emit()
        try:
            while not self._stop.is_set():
                self._run_jobs()
                self.watcher.process_next(timeout=0.2)
                self.watcher.tick()
            self._run_jobs()
        finally:
            self.watcher.stop()
            self._close_db()

    def _close_db(self):
        if self.db is not None:
            self.db.close()
            self.db = None

    def _run_jobs(self):
        while True:
            try:
                job, function = self._jobs.get_nowait()
            except queue.Empty:
                return
            try:
                result = function(self)
            except Exception as exc:
                log.exception("job failed")
                self.failed.emit(job, str(exc))
            else:
                self.done.emit(job, result)

    # Jobs (run on the worker thread; called through ``call``) ------------------
    def apply_config(self, config: dict) -> dict:
        """Save settings and make the watcher use them at once."""
        save_config(config, self.home)
        fresh = load_config(self.home)
        self.engine.config = fresh
        if hasattr(self.engine.identifier, "reload_config"):
            self.engine.identifier.reload_config(fresh)
        self.watcher._config_stamp = self.watcher._stamp()
        self.watcher._next_check = 0
        return load_config(self.home, apply_env=False)

    def stored_config(self) -> dict:
        return load_config(self.home, apply_env=False)

    def collect(self, function: Callable) -> tuple[object, list[dict]]:
        """Run ``function()`` and also return the events it emitted (for previews)."""
        events = []
        forward = self.engine.on_event

        def both(event):
            events.append(dict(event))
            forward(event)

        self.engine.on_event = both
        try:
            return function(), events
        finally:
            self.engine.on_event = forward

    def _use_config(self, config: dict):
        """Make the engine and identifier use ``config`` (not saved)."""
        runtime = with_env(config)
        self.engine.config = runtime
        if hasattr(self.engine.identifier, "reload_config"):
            self.engine.identifier.reload_config(runtime)

    def preview_folders(self, folders: list[dict], config: dict | None = None) -> list[dict]:
        """Dry run over ``folders`` (with candidate settings if given); nothing is renamed."""
        previous = self.engine.config
        if config is not None:
            self._use_config(config)
        try:
            _, events = self.collect(lambda: self.engine.scan(folders, dry_run=True))
        finally:
            if config is not None:
                self._use_config(previous)
        return [event for event in events if event["type"] == "preview"]

    def apply_selection(self, rename: list[str], keep: list[str], config: dict | None = None) -> dict:
        """Keep the unticked names, save settings (if given), then rename the ticked files.

        Everything runs in this one job, so the watcher cannot scan the folder in between.
        """
        batch = uuid.uuid4().hex
        counts = {"renamed": 0, "kept": 0, "other": 0}
        for path in keep:
            if Path(path).is_file():
                self.engine.keep_name(path)
                counts["kept"] += 1
        if config is not None:
            self.apply_config(config)
        for path in rename:
            result = self.engine.process(path, retry=True, batch=batch)
            counts["renamed" if result.status in ("ok", "check") and str(result.path) != path else "other"] += 1
        return counts

    def validate_new_folder(self, config: dict, path: str, recursive: bool) -> dict:
        warnings = []
        new_config = add_folder(config, path, recursive=recursive, on_warning=warnings.append)
        root = Path(new_config["folders"][-1]["path"])
        pattern = root.rglob("*") if recursive else root.iterdir()
        count = sum(1 for item in pattern if item.suffix.lower() == ".pdf" and item.is_file())
        return {"config": new_config, "warnings": warnings, "count": count, "path": str(root)}

    def folder_states(self) -> dict[str, bool]:
        return {folder["path"]: Path(folder["path"]).is_dir()
                for folder in self.engine.config.get("folders", [])}

    def recent_history(self, limit: int = 300) -> list[dict]:
        return _rows(self.db.conn.execute("SELECT * FROM history ORDER BY id DESC LIMIT ?", (limit,)))

    def attention(self) -> list[dict]:
        return _rows(self.db.files_by_status(*ATTENTION))

    def tool_named_count(self) -> int:
        count = 0
        for row in self.db.conn.execute("SELECT display_path, given_name FROM files "
                                        "WHERE status IN ('ok','check') AND paper_id IS NOT NULL"):
            if row["given_name"] == Path(row["display_path"]).name:
                count += 1
        return count

    def preview_reformat(self, include_manual: bool) -> list[dict]:
        _, events = self.collect(lambda: self.engine.reformat(dry_run=True, include_manual=include_manual))
        return [event for event in events if event["type"] == "preview"]

    def export_history(self, target: str) -> int:
        rows = self.db.conn.execute("SELECT * FROM history ORDER BY id").fetchall()
        with open(target, "w", newline="", encoding="utf-8") as stream:
            writer = csv.writer(stream)
            writer.writerow(["time", "old_path", "new_path", "source", "status", "batch", "undone"])
            for row in rows:
                writer.writerow([row["time"], row["old_path"], row["new_path"], row["source"],
                                 row["status"], row["batch"], row["undone"]])
        return len(rows)

    def retry(self, path: str):
        return self.engine.process(path, retry=True, batch=uuid.uuid4().hex)

    def scan_now(self):
        return self.engine.scan()

    def set_paused(self, paused: bool) -> dict:
        config = load_config(self.home, apply_env=False)
        config["paused"] = paused
        return self.apply_config(config)


__all__ = ["Worker", "BUSY_MESSAGE", "ConfigError"]
