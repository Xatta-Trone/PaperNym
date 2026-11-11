"""Queue watchdog events and process watched folders through one engine worker."""

from __future__ import annotations

import queue
import threading
import uuid
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer
from watchdog.observers.polling import PollingObserver

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
    def __init__(self, engine, *, poll: bool = False, observer=None):
        self.engine = engine
        self.observer = observer or (PollingObserver() if poll else Observer())
        self.queue = queue.Queue()
        self.handler = _Handler(self.enqueue)
        self.watches: dict[str, tuple[dict, object]] = {}
        self._stop = threading.Event()
        self._started = False
        self._lock = WriterLock(engine.db.home)

    def enqueue(self, path: str):
        self.queue.put(Path(path))

    def start(self):
        if self._started:
            return
        self._lock.acquire()
        try:
            self.observer.start()
            attached = []
            for folder in self.engine.config.get("folders", []):
                root = Path(folder["path"])
                if not root.is_dir():
                    self.engine._event("folder_unavailable", root, "folder is unavailable")
                    continue
                handle = self.observer.schedule(self.handler, str(root),
                                                recursive=folder.get("recursive", True))
                self.watches[str(root)] = (folder, handle)
                attached.append(folder)
                self.engine._event("folder_attached", root, "watching folder")
            self._started = True
            if attached:
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
            self.engine.process(path, batch=uuid.uuid4().hex)
        finally:
            self.queue.task_done()
        return True

    def run(self):
        self.start()
        try:
            while not self._stop.is_set():
                self.process_next(timeout=1)
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
