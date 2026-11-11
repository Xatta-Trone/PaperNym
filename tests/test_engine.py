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
        unknown_path.write_bytes(b"PDF")
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
