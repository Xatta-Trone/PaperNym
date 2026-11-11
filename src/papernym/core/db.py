"""SQLite storage for paper metadata, files, history, and lookup misses."""

from __future__ import annotations

import datetime as dt
import os
import shutil
import sqlite3
from pathlib import Path

from .config import settings_dir


SCHEMA_VERSION = 1
SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS papers (
  paper_id TEXT PRIMARY KEY, title TEXT NOT NULL, year INTEGER, year_online INTEGER,
  authors TEXT NOT NULL, journal TEXT, source TEXT NOT NULL, fetched_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS files (
  path TEXT PRIMARY KEY, display_path TEXT NOT NULL, fingerprint TEXT NOT NULL,
  size INTEGER, mtime INTEGER, status TEXT NOT NULL, given_name TEXT,
  paper_id TEXT REFERENCES papers(paper_id), attempts INTEGER NOT NULL DEFAULT 0,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS files_fp ON files(fingerprint);
CREATE TABLE IF NOT EXISTS history (
  id INTEGER PRIMARY KEY AUTOINCREMENT, time TEXT NOT NULL, old_path TEXT NOT NULL,
  new_path TEXT NOT NULL, source TEXT NOT NULL, status TEXT NOT NULL,
  batch TEXT NOT NULL, undone INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS misses (ident TEXT PRIMARY KEY, checked_at TEXT NOT NULL);
"""


class DatabaseError(RuntimeError):
    """The database cannot be used or restored safely."""


def path_key(path: str | Path) -> str:
    return os.path.normcase(os.path.abspath(os.fspath(path)))


def _valid_database(path: Path) -> bool:
    if not path.is_file() or path.stat().st_size == 0:
        return False
    try:
        con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
        try:
            return con.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        finally:
            con.close()
    except sqlite3.DatabaseError:
        return False


class Database:
    def __init__(self, home: str | Path | None = None):
        self.home = settings_dir(home)
        self.home.mkdir(parents=True, exist_ok=True)
        self.path = self.home / "papers.db"
        self.backup_path = self.home / "papers.db.bak"
        if self.path.exists() and not _valid_database(self.path):
            if not _valid_database(self.backup_path):
                raise DatabaseError(f"{self.path} is corrupt and no valid backup exists")
            shutil.copy2(self.backup_path, self.path)
        try:
            self.conn = sqlite3.connect(self.path)
            self.conn.row_factory = sqlite3.Row
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA foreign_keys=ON")
            self.conn.executescript(SCHEMA)
            with self.conn:
                self.conn.execute("INSERT OR IGNORE INTO meta VALUES ('schema_version', ?)",
                                  (str(SCHEMA_VERSION),))
            version = self.conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0]
            if int(version) != SCHEMA_VERSION:
                raise DatabaseError(f"unsupported database schema version {version}")
            self.backup_daily()
        except (sqlite3.DatabaseError, ValueError) as exc:
            if hasattr(self, "conn"):
                self.conn.close()
            raise DatabaseError(f"cannot open {self.path}: {exc}") from exc

    def close(self) -> None:
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def backup_daily(self) -> bool:
        """Create one consistent SQLite backup per local day."""
        today = dt.date.today()
        if self.backup_path.exists() and dt.date.fromtimestamp(self.backup_path.stat().st_mtime) == today:
            return False
        temporary = self.home / ".papers.db.bak.tmp"
        try:
            backup = sqlite3.connect(temporary)
            try:
                self.conn.backup(backup)
            finally:
                backup.close()
            os.replace(temporary, self.backup_path)
        finally:
            temporary.unlink(missing_ok=True)
        return True

    def get_paper(self, paper_id: str):
        return self.conn.execute("SELECT * FROM papers WHERE paper_id=?", (paper_id,)).fetchone()

    def put_paper(self, paper: dict) -> None:
        columns = ("paper_id", "title", "year", "year_online", "authors", "journal", "source", "fetched_at")
        with self.conn:
            self.conn.execute("""INSERT INTO papers VALUES (?,?,?,?,?,?,?,?)
                ON CONFLICT(paper_id) DO UPDATE SET title=excluded.title, year=excluded.year,
                year_online=excluded.year_online, authors=excluded.authors,
                journal=excluded.journal, source=excluded.source, fetched_at=excluded.fetched_at""",
                              tuple(paper.get(key) for key in columns))

    def get_file(self, path: str | Path):
        return self.conn.execute("SELECT * FROM files WHERE path=?", (path_key(path),)).fetchone()

    def files_by_fingerprint(self, fingerprint: str):
        return self.conn.execute("SELECT * FROM files WHERE fingerprint=?", (fingerprint,)).fetchall()

    def files_by_status(self, *statuses: str):
        if not statuses:
            return []
        placeholders = ",".join("?" for _ in statuses)
        return self.conn.execute(f"SELECT * FROM files WHERE status IN ({placeholders}) ORDER BY updated_at",
                                 statuses).fetchall()

    def put_file(self, file: dict) -> None:
        columns = ("path", "display_path", "fingerprint", "size", "mtime", "status",
                   "given_name", "paper_id", "attempts", "updated_at")
        values = dict(file)
        values["path"] = path_key(values["path"])
        with self.conn:
            self.conn.execute("""INSERT INTO files VALUES (?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(path) DO UPDATE SET display_path=excluded.display_path,
                fingerprint=excluded.fingerprint, size=excluded.size, mtime=excluded.mtime,
                status=excluded.status, given_name=excluded.given_name,
                paper_id=excluded.paper_id, attempts=excluded.attempts, updated_at=excluded.updated_at""",
                              tuple(values.get(key) for key in columns))

    def delete_file(self, path: str | Path) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM files WHERE path=?", (path_key(path),))

    def record_rename(self, old_path: str | Path, new_file: dict, source: str,
                      status: str, batch: str, when: str) -> None:
        """Move a file row and write its history in the same transaction."""
        new_file = dict(new_file)
        new_file["path"] = path_key(new_file["path"])
        columns = ("path", "display_path", "fingerprint", "size", "mtime", "status",
                   "given_name", "paper_id", "attempts", "updated_at")
        with self.conn:
            self.conn.execute("DELETE FROM files WHERE path=?", (path_key(old_path),))
            self.conn.execute("INSERT INTO files VALUES (?,?,?,?,?,?,?,?,?,?)",
                              tuple(new_file.get(key) for key in columns))
            self.conn.execute("INSERT INTO history(time,old_path,new_path,source,status,batch) VALUES (?,?,?,?,?,?)",
                              (when, str(old_path), str(new_file["display_path"]), source, status, batch))

    def history(self, batch: str | None = None):
        if batch is None:
            return self.conn.execute("SELECT * FROM history ORDER BY id DESC").fetchall()
        return self.conn.execute("SELECT * FROM history WHERE batch=? ORDER BY id DESC", (batch,)).fetchall()

    def get_miss(self, ident: str):
        return self.conn.execute("SELECT checked_at FROM misses WHERE ident=?", (ident,)).fetchone()

    def put_miss(self, ident: str, checked_at: str) -> None:
        with self.conn:
            self.conn.execute("INSERT INTO misses VALUES (?,?) ON CONFLICT(ident) DO UPDATE SET checked_at=excluded.checked_at",
                              (ident, checked_at))
