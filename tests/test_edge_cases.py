"""Additional section 14 behaviours that span core modules."""

import sqlite3

import pytest

from papernym.core.config import default_config
from papernym.core.db import Database
from papernym.core.engine import Engine
from papernym.core.identify import Identifier

from .test_engine import FakeIdentifier, engine, outcome


def test_different_pdf_same_doi_reuses_paper_cache(tmp_path):
    title = "A detailed study of crash severity"
    info = {"text": (title + " 10.1234/paper ") * 8, "page1": title,
            "md_dois": ["10.1234/paper"], "big_title": "", "md_title": "", "paperish": True}
    calls = []

    def get(url, **_kwargs):
        calls.append(url)
        return {"message": {"title": [title], "author": [{"family": "Smith"}],
                            "issued": {"date-parts": [[2025]]}}}

    first, second = tmp_path / "one.pdf", tmp_path / "two.pdf"
    first.write_bytes(b"publisher PDF")
    second.write_bytes(b"preprint PDF")
    with Database(tmp_path / "home") as db:
        cfg = default_config()
        identifier = Identifier(cfg, get, db=db)
        worker = Engine(cfg, db, identifier, read_pdf_fn=lambda _: info, stable_fn=lambda _: True)
        result1 = worker.process(first)
        result2 = worker.process(second)
        assert result1.status == result2.status == "ok"
        assert result2.path.name.endswith("_dup2.pdf")
        assert len(calls) == 1


def test_check_file_auto_corrects_on_retry(tmp_path):
    path = tmp_path / "paper.pdf"
    path.write_bytes(b"PDF")
    fake = FakeIdentifier(outcome("check", {"title": "A useful research article", "year": 2025,
        "year_online": 2025, "authors": ["Smith"], "journal": "", "source": "pdf-only"}))
    with Database(tmp_path / "home") as db:
        worker = engine(db, fake)
        checked = worker.process(path)
        assert checked.path.name.endswith("_CHECK.pdf")
        fake.outcome = outcome()
        corrected = worker.process(checked.path, retry=True)
        assert corrected.status == "ok"
        assert not corrected.path.name.endswith("_CHECK.pdf")
        assert fake.calls == 2


def test_partial_download_is_never_read(tmp_path):
    path = tmp_path / "partial.pdf"
    path.write_bytes(b"partial")

    def forbidden(_path):
        raise AssertionError("partial PDF was read")

    with Database(tmp_path / "home") as db:
        worker = engine(db, FakeIdentifier(outcome()), read=forbidden, stable=lambda _: False)
        assert worker.process(path).status == "skipped"
        assert db.get_file(path) is None


def test_unknown_stops_after_five_reached_attempts(tmp_path):
    path = tmp_path / "unknown.pdf"
    path.write_bytes(b"unknown")
    fake = FakeIdentifier(outcome("unknown"))
    with Database(tmp_path / "home") as db:
        worker = engine(db, fake)
        for _ in range(5):
            assert worker.process(path, retry=True).status == "unknown"
        assert worker.process(path, retry=True).status == "skipped"
        assert fake.calls == 5


def test_scanned_pdf_with_property_doi_is_trusted():
    title = "A paper whose pages have no text"
    info = {"text": "", "page1": "", "md_dois": ["10.1234/scanned"],
            "big_title": "", "md_title": "", "paperish": True}
    def get(_url, **_kwargs):
        return {"message": {"title": [title], "author": [{"family": "Smith"}],
                            "issued": {"date-parts": [[2025]]}}}
    match, _ = Identifier({"title_search": False}, get).identify_online("scan.pdf", info)
    assert match.paper_id == "doi:10.1234/scanned"


def test_invoice_stays_untouched_without_a_lookup(tmp_path):
    path = tmp_path / "invoice.pdf"
    path.write_bytes(b"invoice")
    cfg = default_config()
    cfg["title_search"] = False
    info = {"text": "Invoice for services", "page1": "Invoice for services", "md_dois": [],
            "big_title": "", "md_title": "", "paperish": False}
    def forbidden(*_args, **_kwargs):
        raise AssertionError("invoice sent to network")
    with Database(tmp_path / "home") as db:
        worker = Engine(cfg, db, Identifier(cfg, forbidden, db=db),
                        read_pdf_fn=lambda _: info, stable_fn=lambda _: True)
        assert worker.process(path).status == "unknown"
        assert path.exists()


def test_interrupted_scan_resumes_without_pruning(tmp_path):
    papers = tmp_path / "papers"
    papers.mkdir()
    (papers / "one.pdf").write_bytes(b"one")
    (papers / "two.pdf").write_bytes(b"two")
    cfg = default_config()
    cfg["folders"] = [{"path": str(papers), "recursive": True}]
    interrupted = False

    def on_event(event):
        nonlocal interrupted
        if event["type"] == "scan_progress" and not interrupted:
            interrupted = True
            raise KeyboardInterrupt

    with Database(tmp_path / "home") as db:
        worker = Engine(cfg, db, FakeIdentifier(outcome()), on_event,
                        read_pdf_fn=lambda _: {}, stable_fn=lambda _: True)
        with pytest.raises(KeyboardInterrupt):
            worker.scan()
        assert db.conn.execute("SELECT count(*) FROM files").fetchone()[0] == 1
        assert worker.scan()["total"] == 2
        assert len(db.history()) == 2


def test_database_failure_after_rename_restores_original(tmp_path, monkeypatch):
    path = tmp_path / "download.pdf"
    path.write_bytes(b"PDF")
    with Database(tmp_path / "home") as db:
        worker = engine(db, FakeIdentifier(outcome()))
        def fail(*_args, **_kwargs):
            raise sqlite3.OperationalError("simulated write failure")
        monkeypatch.setattr(db, "record_rename", fail)
        with pytest.raises(sqlite3.OperationalError):
            worker.process(path)
        assert path.exists() and path.read_bytes() == b"PDF"
        assert db.history() == []


def test_naming_change_affects_new_files_until_reformat(tmp_path):
    old = tmp_path / "old.pdf"
    old.write_bytes(b"old")
    new = tmp_path / "new.pdf"
    new.write_bytes(b"new")
    with Database(tmp_path / "home") as db:
        worker = engine(db, FakeIdentifier(outcome()))
        old_name = worker.process(old).path
        worker.config["format"] = "{author}_{year}"
        assert worker.process(old_name).status == "skipped"
        assert old_name.exists()
        new_name = worker.process(new).path
        assert new_name.name == "Smith_2025.pdf"
        assert old_name.exists()
        worker.reformat()
        assert not old_name.exists()
        assert any(path.name.startswith("Smith_2025") for path in tmp_path.glob("*.pdf"))


def test_preview_does_not_write_online_cache(tmp_path):
    folder = tmp_path / "papers"
    folder.mkdir()
    (folder / "one.pdf").write_bytes(b"PDF")
    title = "A detailed study of road safety"
    info = {"text": (title + " 10.1234/paper ") * 8, "page1": title,
            "md_dois": ["10.1234/paper"], "big_title": "", "md_title": "", "paperish": True}
    def get(_url, **_kwargs):
        return {"message": {"title": [title], "author": [{"family": "Smith"}],
                            "issued": {"date-parts": [[2025]]}}}
    cfg = default_config()
    cfg["folders"] = [{"path": str(folder), "recursive": True}]
    with Database(tmp_path / "home") as db:
        identifier = Identifier(cfg, get, db=db)
        worker = Engine(cfg, db, identifier, read_pdf_fn=lambda _: info, stable_fn=lambda _: True)
        assert worker.scan(dry_run=True)["preview"] == 1
        for table in ("papers", "files", "misses", "history"):
            assert db.conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0
