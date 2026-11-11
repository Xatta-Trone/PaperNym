"""Queue watchdog events and process watched folders through one engine worker."""

from __future__ import annotations

import queue
import threading
import time
import uuid
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer
from watchdog.observers.polling import PollingObserver

from .config import ConfigError, load_config
from .db import path_key
from .lock import WriterLock


class _Handler(FileSystemEventHandler):
    def __init__(self, enqueue):
        super().__init__()
        self.enqueue = enqueue

    def on_created(self, event):
        if not event.is_directory:
            self.enqueue(event.src_path)

    def on_moved(self, event):
        if not event.is_directory:
            self.enqueue(event.dest_path)


class Watcher:
    def __init__(self, engine, *, poll: bool = False, observer=None, clock=None):
        self.engine = engine
        self.observer = observer or (PollingObserver() if poll else Observer())
        self.queue = queue.Queue()
        self.handler = _Handler(self.enqueue)
        self.watches: dict[str, tuple[dict, object]] = {}
        self._stop = threading.Event()
        self._started = False
        self._lock = WriterLock(engine.db.home)
        self.clock = clock or time.monotonic
        self._next_check = 0.0
        self._next_retry = 0.0
        self._config_stamp = self._stamp()
        self._unavailable = set()
        self._paused = engine.config.get("paused", False)
        self._bad_config_stamp = None

    def _stamp(self):
        try:
            return (self.engine.db.home / "config.json").stat().st_mtime_ns
        except OSError:
            return 0

    def enqueue(self, path: str):
        self.queue.put(Path(path))

    def start(self):
        if self._started:
            return
        self._lock.acquire()
        try:
            self.observer.start()
            attached = self.reconcile()
            self._started = True
            self._next_check = self.clock() + 10
            self._next_retry = self.clock() + 30 * 60
            if attached and not self.engine.config.get("paused", False):
                self.engine.scan(attached)
        except Exception:
            self.observer.stop()
            self.observer.join()
            self.watches.clear()
            self._started = False
            self._lock.release()
            raise

    def process_next(self, timeout: float = 0) -> bool:
        try:
            path = self.queue.get(timeout=timeout)
        except queue.Empty:
            return False
        try:
            if not self.engine.config.get("paused", False):
                watched = any(self.engine._inside(path, folder["path"], folder.get("recursive", True))
                              for folder in self.engine.config.get("folders", []))
                if watched:
                    try:
                        self.engine.process(path, batch=uuid.uuid4().hex)
                    except (OSError, ValueError) as exc:
                        self.engine._event("skipped", path, f"cannot process file: {exc}")
        finally:
            self.queue.task_done()
        return True

    def run(self):
        self.start()
        try:
            while not self._stop.is_set():
                self.process_next(timeout=1)
                self.tick()
        finally:
            self.stop()

    def stop(self):
        self._stop.set()
        if self._started:
            self.observer.stop()
            self.observer.join()
            self.watches.clear()
            self._started = False
        self._lock.release()

    def reconcile(self) -> list[dict]:
        """Detach missing watches and attach reachable new or returned folders."""
        configured = {path_key(folder["path"]): folder for folder in self.engine.config.get("folders", [])}
        for key, (folder, handle) in list(self.watches.items()):
            if key not in configured or folder != configured[key] or not Path(folder["path"]).is_dir():
                try:
                    self.observer.unschedule(handle)
                except Exception:
                    pass
                del self.watches[key]
                if key in configured and not Path(folder["path"]).is_dir() and key not in self._unavailable:
                    self._unavailable.add(key)
                    self.engine._event("folder_unavailable", Path(folder["path"]), "folder is unavailable")
        attached = []
        for key, folder in configured.items():
            root = Path(folder["path"])
            if not root.is_dir():
                if key not in self._unavailable:
                    self._unavailable.add(key)
                    self.engine._event("folder_unavailable", root, "folder is unavailable")
                continue
            self._unavailable.discard(key)
            if key in self.watches:
                continue
            try:
                handle = self.observer.schedule(self.handler, str(root),
                                                recursive=folder.get("recursive", True))
            except OSError as exc:
                self.engine._event("folder_unavailable", root, f"cannot watch folder: {exc}")
                continue
            self.watches[key] = (folder, handle)
            attached.append(folder)
            self.engine._event("folder_attached", root, "watching folder")
        return attached

    def tick(self, now: float | None = None):
        """Run due settings, reconcile, and retry timers."""
        now = self.clock() if now is None else now
        if now >= self._next_check:
            self._next_check = now + 10
            stamp = self._stamp()
            was_paused = self._paused
            if stamp != self._config_stamp:
                try:
                    config = load_config(self.engine.db.home)
                except ConfigError as exc:
                    if stamp != self._bad_config_stamp:
                        self._bad_config_stamp = stamp
                        self.engine._event("skipped", self.engine.db.home, f"cannot reload settings: {exc}")
                else:
                    self._bad_config_stamp = None
                    self._config_stamp = stamp
                    self.engine.config = config
                    if hasattr(self.engine.identifier, "reload_config"):
                        self.engine.identifier.reload_config(config)
                    self.engine._event("settings_reloaded", self.engine.db.home, "settings reloaded")
            attached = self.reconcile()
            self._paused = self.engine.config.get("paused", False)
            if not self.engine.config.get("paused", False):
                if was_paused:
                    self.engine.scan()
                elif attached:
                    self.engine.scan(attached)
        if now >= self._next_retry:
            self._next_retry = now + 30 * 60
            if not self.engine.config.get("paused", False):
                for row in self.engine.db.files_by_status("check", "unknown", "pending"):
                    path = Path(row["display_path"])
                    if path.is_file():
                        self.engine.process(path, retry=True, batch=uuid.uuid4().hex)
