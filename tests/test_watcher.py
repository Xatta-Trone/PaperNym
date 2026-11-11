from watchdog.events import FileCreatedEvent, FileMovedEvent

from papernym.core.config import default_config
from papernym.core.config import save_config
from papernym.core.db import Database
from papernym.core.engine import Engine
from papernym.core.lock import WriterLock
from papernym.core.watcher import Watcher

from .test_engine import FakeIdentifier, outcome


class FakeObserver:
    def __init__(self):
        self.scheduled = []
        self.running = False
        self.unscheduled = []

    def start(self):
        self.running = True

    def schedule(self, handler, path, recursive=True):
        handle = object()
        self.scheduled.append((handler, path, recursive, handle))
        return handle

    def stop(self):
        self.running = False

    def unschedule(self, handle):
        self.unscheduled.append(handle)

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


def test_settings_reload_reconciles_folders(tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    (second / "new.pdf").write_bytes(b"new")
    cfg = default_config()
    cfg["folders"] = [{"path": str(first), "recursive": True}]
    home = tmp_path / "home"
    save_config(cfg, home)
    events = []
    observer = FakeObserver()
    with Database(home) as db:
        engine = Engine(cfg, db, FakeIdentifier(outcome()), events.append,
                        read_pdf_fn=lambda _: {}, stable_fn=lambda _: True)
        watcher = Watcher(engine, observer=observer, clock=lambda: 0)
        watcher.start()
        changed = dict(cfg, folders=[{"path": str(second), "recursive": True}])
        save_config(changed, home)
        watcher.tick(11)
        assert len(observer.unscheduled) == 1
        assert len(watcher.watches) == 1
        assert not (second / "new.pdf").exists()
        assert any(event["type"] == "settings_reloaded" for event in events)
        watcher.stop()


def test_pause_drops_events_and_resume_scans(tmp_path):
    papers = tmp_path / "papers"
    papers.mkdir()
    pending = papers / "pending.pdf"
    pending.write_bytes(b"PDF")
    cfg = default_config()
    cfg["folders"] = [{"path": str(papers), "recursive": True}]
    cfg["paused"] = True
    home = tmp_path / "home"
    save_config(cfg, home)
    with Database(home) as db:
        engine = Engine(cfg, db, FakeIdentifier(outcome()), read_pdf_fn=lambda _: {}, stable_fn=lambda _: True)
        watcher = Watcher(engine, observer=FakeObserver(), clock=lambda: 0)
        watcher.start()
        watcher.handler.on_created(FileCreatedEvent(str(pending)))
        assert watcher.process_next()
        assert pending.exists() and db.get_file(pending) is None
        cfg["paused"] = False
        save_config(cfg, home)
        watcher.tick(11)
        assert not pending.exists()
        watcher.stop()


def test_unplugged_folder_returns_and_retry_timer(tmp_path):
    papers = tmp_path / "papers"
    papers.mkdir()
    unknown = papers / "unknown.pdf"
    unknown.write_bytes(b"unknown")
    cfg = default_config()
    cfg["folders"] = [{"path": str(papers), "recursive": True}]
    fake = FakeIdentifier(outcome("unknown"))
    events = []
    observer = FakeObserver()
    with Database(tmp_path / "home") as db:
        engine = Engine(cfg, db, fake, events.append, read_pdf_fn=lambda _: {}, stable_fn=lambda _: True)
        watcher = Watcher(engine, observer=observer, clock=lambda: 0)
        watcher.start()
        assert db.get_file(unknown)["status"] == "unknown"
        unknown.unlink()
        papers.rmdir()
        watcher.tick(11)
        assert db.get_file(unknown) is not None
        assert not watcher.watches
        papers.mkdir()
        replacement = papers / "replacement.pdf"
        replacement.write_bytes(b"different")
        fake.outcome = outcome()
        watcher.tick(22)
        assert not replacement.exists()
        assert watcher.watches
        retry_file = papers / "retry.pdf"
        retry_file.write_bytes(b"retry")
        fake.outcome = outcome("unknown")
        engine.process(retry_file)
        fake.outcome = outcome()
        watcher.tick(1801)
        assert not retry_file.exists()
        watcher.stop()


def test_bad_settings_reload_keeps_previous_watches(tmp_path):
    papers = tmp_path / "papers"
    papers.mkdir()
    cfg = default_config()
    cfg["folders"] = [{"path": str(papers), "recursive": True}]
    home = tmp_path / "home"
    save_config(cfg, home)
    events = []
    with Database(home) as db:
        engine = Engine(cfg, db, FakeIdentifier(outcome()), events.append,
                        read_pdf_fn=lambda _: {}, stable_fn=lambda _: True)
        watcher = Watcher(engine, observer=FakeObserver(), clock=lambda: 0)
        watcher.start()
        (home / "config.json").write_text("{bad", encoding="utf-8")
        watcher.tick(11)
        assert len(watcher.watches) == 1
        assert any("cannot reload settings" in event["message"] for event in events)
        watcher.stop()
