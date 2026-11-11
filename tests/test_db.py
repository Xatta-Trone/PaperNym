import os
import csv
import json
import sqlite3
import time

import pytest

from papernym.core.db import Database, DatabaseError, path_key


def paper(paper_id="doi:10.1/test"):
    return {"paper_id": paper_id, "title": "A paper", "year": 2025, "year_online": 2024,
            "authors": '["Smith"]', "journal": "Journal", "source": "crossref",
            "fetched_at": "2026-11-10T00:00:00"}


def file(path, paper_id="doi:10.1/test"):
    return {"path": str(path), "display_path": str(path), "fingerprint": "abc",
            "size": 10, "mtime": 123, "status": "ok", "given_name": path.name,
            "paper_id": paper_id, "attempts": 0, "updated_at": "2026-11-10T00:00:00"}


def test_schema_pragmas_and_queries(tmp_path):
    with Database(tmp_path) as db:
        assert db.conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert db.conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert db.conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0] == "1"
        db.put_paper(paper())
        name = tmp_path / "paper.pdf"
        db.put_file(file(name))
        db.put_miss("doi:10.2/missing", "2026-11-10")
        assert db.get_paper("doi:10.1/test")["year_online"] == 2024
        assert db.get_file(name)["path"] == path_key(name)
        assert len(db.files_by_fingerprint("abc")) == 1
        assert len(db.files_by_status("ok")) == 1
        assert db.get_miss("doi:10.2/missing")[0] == "2026-11-10"
        with pytest.raises(sqlite3.IntegrityError):
            db.put_file(file(tmp_path / "bad.pdf", "doi:missing"))


def test_rename_row_and_history_are_atomic(tmp_path):
    with Database(tmp_path) as db:
        db.put_paper(paper())
        old, new = tmp_path / "old.pdf", tmp_path / "new.pdf"
        db.put_file(file(old))
        db.record_rename(old, file(new), "crossref", "ok", "batch1", "2026-11-10")
        assert db.get_file(old) is None
        assert db.get_file(new) is not None
        assert db.history("batch1")[0]["old_path"] == str(old)
        invalid = file(tmp_path / "bad.pdf", "doi:missing")
        with pytest.raises(sqlite3.IntegrityError):
            db.record_rename(new, invalid, "crossref", "ok", "batch2", "2026-11-10")
        assert db.get_file(new) is not None
        assert db.history("batch2") == []


def test_backup_once_per_day_and_restore(tmp_path):
    with Database(tmp_path) as db:
        db.put_paper(paper())
        old_time = time.time() - 3 * 86400
        os.utime(db.backup_path, (old_time, old_time))
        assert db.backup_daily() is True
        assert db.backup_daily() is False
    (tmp_path / "papers.db").write_bytes(b"broken sqlite")
    with Database(tmp_path) as restored:
        assert restored.get_paper("doi:10.1/test")["title"] == "A paper"


def test_corruption_without_backup_stops(tmp_path):
    (tmp_path / "papers.db").write_bytes(b"broken sqlite")
    with pytest.raises(DatabaseError, match="corrupt"):
        Database(tmp_path)
    assert (tmp_path / "papers.db").read_bytes() == b"broken sqlite"


def test_unrelated_sqlite_backup_cannot_replace_corrupt_database(tmp_path):
    (tmp_path / "papers.db").write_bytes(b"broken sqlite")
    with sqlite3.connect(tmp_path / "papers.db.bak") as unrelated:
        unrelated.execute("CREATE TABLE unrelated (x TEXT)")
    with pytest.raises(DatabaseError, match="no valid backup"):
        Database(tmp_path)


def test_prototype_migration_imports_state_history_and_config(tmp_path):
    old = tmp_path / "PaperRenamer"
    old.mkdir()
    home = tmp_path / "PaperNym"
    legacy_path = str(tmp_path / "named.pdf")
    state = {"version": 2, "files": {legacy_path: {"path": legacy_path,
        "fp": "fingerprint", "sig": [100, 99], "status": "ok", "attempts": 2,
        "given": "named.pdf", "meta": {"title": "Test Article", "year": 2025,
        "year_online": 2024, "authors": ["Smith"], "journal": "J", "source": "crossref"}}}}
    (old / "state.json").write_text(json.dumps(state), encoding="utf-8")
    with (old / "history.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["time", "old_path", "new_path", "source", "status", "batch"])
        writer.writeheader()
        writer.writerow({"time": "now", "old_path": "old.pdf", "new_path": legacy_path,
                         "source": "crossref", "status": "ok", "batch": "b"})
    (old / "config.json").write_text(json.dumps({"year": "online"}), encoding="utf-8")
    with Database(home) as db:
        assert db.get_file(legacy_path)["given_name"] == "named.pdf"
        assert db.get_file(legacy_path)["paper_id"] == "title:test article"
        assert db.get_paper("title:test article")["year_online"] == 2024
        assert len(db.history("b")) == 1
    assert json.loads((home / "config.json").read_text())["year"] == "online"
    for name in ("state.json", "history.csv", "config.json"):
        assert not (old / name).exists()
        assert (old / (name + ".bak")).exists()
    with Database(home) as db:
        assert len(db.history()) == 1


def test_older_prototype_state_format(tmp_path):
    old = tmp_path / "PaperRenamer"
    old.mkdir()
    path = str(tmp_path / "old.pdf")
    (old / "state.json").write_text(json.dumps({"hash": {"path": path, "status": "check",
        "meta": {"title": "Older Article", "year": 2022, "authors": [], "source": "pdf-only"}}}))
    with Database(tmp_path / "PaperNym") as db:
        assert db.get_file(path)["given_name"] == "old.pdf"
        assert db.get_file(path)["fingerprint"] == "hash"


def test_bad_prototype_data_is_not_backed_up(tmp_path):
    old = tmp_path / "PaperRenamer"
    old.mkdir()
    (old / "state.json").write_text("{bad", encoding="utf-8")
    with pytest.raises(DatabaseError, match="cannot migrate"):
        Database(tmp_path / "PaperNym")
    assert (old / "state.json").exists()
    assert not (old / "state.json.bak").exists()
