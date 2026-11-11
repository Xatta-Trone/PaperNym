from watchdog.events import FileCreatedEvent, FileMovedEvent

from papernym.core.config import default_config
from papernym.core.db import Database
from papernym.core.engine import Engine
from papernym.core.lock import WriterLock
from papernym.core.watcher import Watcher

from .test_engine import FakeIdentifier, outcome


class FakeObserver:
    def __init__(self):
        self.scheduled = []
        self.running = False

    def start(self):
        self.running = True

    def schedule(self, handler, path, recursive=True):
        handle = object()
        self.scheduled.append((handler, path, recursive, handle))
        return handle

    def stop(self):
        self.running = False

    def join(self):
        pass


def test_startup_scan_and_created_moved_events(tmp_path):
    papers = tmp_path / "papers"
    papers.mkdir()
    (papers / "while_closed.pdf").write_bytes(b"one")
    cfg = default_config()
    cfg["folders"] = [{"path": str(papers), "recursive": True}]
    observer = FakeObserver()
    events = []
    with Database(tmp_path / "home") as db:
        engine = Engine(cfg, db, FakeIdentifier(outcome()), events.append,
                        read_pdf_fn=lambda _: {}, stable_fn=lambda _: True)
        watcher = Watcher(engine, observer=observer)
        watcher.start()
        assert observer.running
        assert observer.scheduled[0][2] is True
        assert not (papers / "while_closed.pdf").exists()
        assert any(event["type"] == "scan_finished" for event in events)
        new = papers / "new.pdf"
        new.write_bytes(b"two")
        watcher.handler.on_created(FileCreatedEvent(str(new)))
        assert watcher.process_next()
        assert not new.exists()
        moved = papers / "from_download.pdf"
        moved.write_bytes(b"three")
        watcher.handler.on_moved(FileMovedEvent(str(papers / "x.part"), str(moved)))
        assert watcher.process_next()
        assert not moved.exists()
        assert not watcher.process_next()
        watcher.stop()
        assert not observer.running
        with WriterLock(db.home):
            pass
