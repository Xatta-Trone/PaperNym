from pathlib import Path

import pytest

from papernym.core.config import default_config
from papernym.core.db import Database
from papernym.core.engine import Engine
from papernym.core.identify import IdentifyOutcome, LookupStats, PaperMatch
from papernym.core.pdfread import PdfReadError


META = {"title": "A useful research article", "year": 2025, "year_online": 2024,
        "authors": ["Smith"], "journal": "Journal", "source": "crossref"}


class FakeIdentifier:
    def __init__(self, outcome):
        self.outcome = outcome
        self.calls = 0

    def identify(self, _path, _info):
        self.calls += 1
        return self.outcome


def outcome(status="ok", meta=None):
    match = PaperMatch("doi:10.1/test", meta or META, status) if status in ("ok", "check") else None
    return IdentifyOutcome(match, status, 1 if status == "unknown" else 0, LookupStats())


def engine(db, identifier, events=None, read=None, stable=None):
    return Engine(default_config(), db, identifier, (events if events is not None else []).append,
                  read_pdf_fn=read or (lambda _: {"text": "paper"}),
                  stable_fn=stable or (lambda _: True))


def test_identified_file_is_renamed_and_recorded_once(tmp_path):
    path = tmp_path / "download.pdf"
    path.write_bytes(b"PDF")
    events = []
    fake = FakeIdentifier(outcome())
    with Database(tmp_path / "home") as db:
        worker = engine(db, fake, events)
        result = worker.process(path)
        assert result.status == "ok"
        assert result.path.name == "2025_Smith_A_useful_research_article.pdf"
        assert not path.exists()
        assert db.get_file(result.path)["status"] == "ok"
        assert len(db.history()) == 1
        assert worker.process(result.path).status == "skipped"
        assert fake.calls == 1
        assert events[0]["type"] == "renamed"


def test_check_unknown_and_unreadable_statuses(tmp_path):
    check_path = tmp_path / "offline.pdf"
    check_path.write_bytes(b"PDF")
    offline = dict(META, source="pdf-only")
    with Database(tmp_path / "home") as db:
        check = engine(db, FakeIdentifier(outcome("check", offline))).process(check_path)
        assert check.status == "check"
        assert check.path.name.endswith("_CHECK.pdf")
        unknown_path = tmp_path / "unknown.pdf"
        unknown_path.write_bytes(b"OTHER")
        unknown = engine(db, FakeIdentifier(outcome("unknown"))).process(unknown_path)
        assert unknown.status == "unknown"
        assert unknown_path.exists()
        assert db.get_file(unknown_path)["attempts"] == 1
        bad_path = tmp_path / "bad.pdf"
        bad_path.write_bytes(b"broken")

        def unreadable(_path):
            raise PdfReadError("cannot open PDF")

        bad_engine = engine(db, FakeIdentifier(outcome()), read=unreadable)
        assert bad_engine.process(bad_path).status == "unreadable"
        assert bad_engine.process(bad_path, retry=True).status == "skipped"


def test_locked_rename_becomes_pending_and_retries_without_lookup(tmp_path, monkeypatch):
    path = tmp_path / "locked.pdf"
    path.write_bytes(b"PDF")
    fake = FakeIdentifier(outcome())
    with Database(tmp_path / "home") as db:
        worker = engine(db, fake)
        original = Path.rename

        def fail_once(self, target):
            raise PermissionError("in use")

        with monkeypatch.context() as patch:
            patch.setattr(Path, "rename", fail_once)
            assert worker.process(path).status == "pending"
        assert db.get_file(path)["status"] == "pending"
        assert worker.process(path, retry=True).status == "ok"
        assert fake.calls == 1


def test_hand_rename_and_move_are_respected(tmp_path):
    original = tmp_path / "download.pdf"
    original.write_bytes(b"PDF")
    fake = FakeIdentifier(outcome())
    with Database(tmp_path / "home") as db:
        worker = engine(db, fake)
        named = worker.process(original).path
        moved_dir = tmp_path / "other"
        moved_dir.mkdir()
        moved = moved_dir / "My chosen name.pdf"
        named.rename(moved)
        assert worker.process(moved, retry=True).status == "skipped"
        row = db.get_file(moved)
        assert row["given_name"] == named.name
        assert db.get_file(named) is None
        assert fake.calls == 1


def test_annotated_file_and_copy_need_no_new_lookup(tmp_path):
    original = tmp_path / "download.pdf"
    original.write_bytes(b"PDF")
    fake = FakeIdentifier(outcome())
    with Database(tmp_path / "home") as db:
        worker = engine(db, fake)
        named = worker.process(original).path
        old_fp = db.get_file(named)["fingerprint"]
        named.write_bytes(b"PDF plus annotation")
        assert worker.process(named).status == "skipped"
        assert db.get_file(named)["fingerprint"] != old_fp
        assert fake.calls == 1
        copy = tmp_path / "copy.pdf"
        copy.write_bytes(named.read_bytes())
        result = worker.process(copy)
        assert result.status == "ok"
        assert result.path.name.endswith("_dup2.pdf")
        assert fake.calls == 1


def test_excludes_file_globs_and_folder_names_before_reading(tmp_path):
    manuscript_dir = tmp_path / "Manuscripts"
    manuscript_dir.mkdir()
    paths = [tmp_path / "rough_draft.pdf", tmp_path / "paper_v2.pdf",
             manuscript_dir / "final.pdf"]
    for path in paths:
        path.write_bytes(b"PDF")

    def forbidden(_path):
        raise AssertionError("excluded PDF was read")

    with Database(tmp_path / "home") as db:
        worker = engine(db, FakeIdentifier(outcome()), read=forbidden)
        for path in paths:
            assert worker.process(path).status == "skipped"
            assert db.get_file(path) is None


def test_scan_emits_progress_and_prunes_only_reachable_folders(tmp_path):
    live = tmp_path / "live"
    offline = tmp_path / "offline"
    live.mkdir()
    offline.mkdir()
    (live / "one.pdf").write_bytes(b"one")
    (live / "two.PDF").write_bytes(b"two")
    offline_file = offline / "three.pdf"
    offline_file.write_bytes(b"three")
    events = []
    config = default_config()
    config["folders"] = [{"path": str(live), "recursive": True},
                         {"path": str(offline), "recursive": True}]
    with Database(tmp_path / "home") as db:
        worker = Engine(config, db, FakeIdentifier(outcome()), events.append,
                        read_pdf_fn=lambda _: {"text": "paper"}, stable_fn=lambda _: True)
        first = worker.scan()
        assert first["total"] == 3
        assert [event["type"] for event in events].count("scan_progress") == 3
        assert events[-1]["type"] == "scan_finished"
        original_rows = db.conn.execute("SELECT display_path FROM files").fetchall()
        lost = next(Path(row[0]) for row in original_rows if Path(row[0]).parent == offline)
        lost.unlink()
        offline.rmdir()
        live_lost = next(Path(row[0]) for row in original_rows if Path(row[0]).parent == live)
        live_lost.unlink()
        second = worker.scan()
        assert second["pruned"] == 1
        assert db.get_file(live_lost) is None
        assert db.get_file(lost) is not None
        assert any(event["type"] == "folder_unavailable" for event in events)
