"""SQLite storage for paper metadata, files, history, and lookup misses."""

from __future__ import annotations

import datetime as dt
import csv
import json
import os
import re
import shutil
import sqlite3
import unicodedata
from pathlib import Path

from .config import save_config, settings_dir, validate_config


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
            self.migrate_prototype()
            self.backup_daily()
        except (sqlite3.DatabaseError, ValueError, DatabaseError) as exc:
            if hasattr(self, "conn"):
                self.conn.close()
            if isinstance(exc, DatabaseError):
                raise
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

    def migrate_prototype(self) -> bool:
        """Import adjacent PaperRenamer files once, then preserve them as .bak."""
        legacy = self.home.parent / "PaperRenamer"
        sources = [legacy / name for name in ("state.json", "history.csv", "config.json")]
        present = [path for path in sources if path.exists()]
        if not present:
            return False
        marker = self.conn.execute("SELECT value FROM meta WHERE key='prototype_migrated'").fetchone()
        if marker:
            return False
        for path in present:
            if path.with_name(path.name + ".bak").exists():
                raise DatabaseError(f"cannot migrate {path}: .bak already exists")
        try:
            state = json.loads(sources[0].read_text(encoding="utf-8")) if sources[0].exists() else {}
            with sources[1].open(encoding="utf-8", newline="") if sources[1].exists() else _empty_csv() as stream:
                history = list(csv.DictReader(stream))
            old_config = json.loads(sources[2].read_text(encoding="utf-8")) if sources[2].exists() else None
            if old_config is not None:
                old_config = validate_config(old_config)
            records = state.get("files", {}) if "files" in state else state
            if not isinstance(records, dict):
                raise ValueError("state files must be an object")
            now = dt.datetime.now(dt.timezone.utc).isoformat()
            with self.conn:
                for key, record in records.items():
                    if not isinstance(record, dict) or not record.get("path"):
                        raise ValueError("state has a file without a path")
                    path = str(record["path"])
                    fp = str(record.get("fp", key))
                    meta = record.get("meta")
                    paper_id = None
                    if meta:
                        title = str(meta["title"])
                        folded = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode().lower()
                        normal = " ".join(re.sub(r"[^a-z0-9 ]", " ", folded).split())
                        paper_id = "title:" + normal
                        self.conn.execute("""INSERT OR IGNORE INTO papers VALUES (?,?,?,?,?,?,?,?)""",
                                          (paper_id, title, meta.get("year"), meta.get("year_online"),
                                           json.dumps(meta.get("authors", []), ensure_ascii=False),
                                           meta.get("journal", ""), meta.get("source", "pdf-only"), now))
                    sig = record.get("sig") or [None, None]
                    status = record.get("status", "unknown")
                    given = record.get("given")
                    if "files" not in state and status in ("ok", "check"):
                        given = Path(path).name
                    self.conn.execute("""INSERT OR REPLACE INTO files VALUES (?,?,?,?,?,?,?,?,?,?)""",
                                      (path_key(path), path, fp, sig[0], sig[1], status, given,
                                       paper_id, record.get("attempts", 0), now))
                for row in history:
                    self.conn.execute("""INSERT INTO history(time,old_path,new_path,source,status,batch)
                        VALUES (?,?,?,?,?,?)""",
                                      (row["time"], row["old_path"], row["new_path"],
                                       row["source"], row["status"], row.get("batch", "")))
                if old_config is not None and not (self.home / "config.json").exists():
                    save_config(old_config, self.home)
                self.conn.execute("INSERT INTO meta VALUES ('prototype_migrated','1')")
            for path in present:
                path.rename(path.with_name(path.name + ".bak"))
            return True
        except (OSError, ValueError, KeyError, sqlite3.DatabaseError) as exc:
            raise DatabaseError(f"cannot migrate prototype data in {legacy}: {exc}") from exc


class _empty_csv:
    def __enter__(self):
        return iter(())

    def __exit__(self, *_):
        return False
