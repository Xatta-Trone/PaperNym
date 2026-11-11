"""Safe per-file processing, scan, reformat, and undo operations."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .db import Database
from .identify import Identifier, PaperMatch
from .naming import unique_path
from .pdfread import PdfReadError, read_pdf


@dataclass(frozen=True)
class ProcessResult:
    status: str
    path: Path
    message: str = ""


def fingerprint(path: Path) -> str:
    size = path.stat().st_size
    digest = hashlib.sha1(str(size).encode("ascii"))
    with path.open("rb") as stream:
        digest.update(stream.read(262144))
    return digest.hexdigest()


def stable_file(path: Path, timeout: float = 120, pause: float = 1.5) -> bool:
    """Wait for a nonempty file whose size remains unchanged for two checks."""
    deadline = time.monotonic() + timeout
    previous = None
    while time.monotonic() < deadline:
        try:
            size = path.stat().st_size
        except OSError:
            return False
        if size > 0 and size == previous:
            return True
        previous = size
        time.sleep(pause)
    return False


class Engine:
    def __init__(self, config: dict, db: Database, identifier: Identifier | None = None,
                 on_event: Callable | None = None, read_pdf_fn: Callable = read_pdf,
                 stable_fn: Callable = stable_file):
        self.config = config
        self.db = db
        self.on_event = on_event or (lambda event: None)
        self.identifier = identifier or Identifier(config, db=db, on_event=self.on_event)
        self.read_pdf = read_pdf_fn
        self.stable = stable_fn

    def _event(self, kind: str, path: Path, message: str, **extra):
        event = {"type": kind, "path": str(path), "message": message}
        event.update(extra)
        self.on_event(event)

    @staticmethod
    def _stamp() -> str:
        return dt.datetime.now(dt.timezone.utc).isoformat()

    @staticmethod
    def _batch() -> str:
        return uuid.uuid4().hex

    def _row(self, path: Path, fp: str, status: str, paper_id: str | None = None,
             given_name: str | None = None, attempts: int = 0) -> dict:
        stat = path.stat()
        return {"path": str(path), "display_path": str(path), "fingerprint": fp,
                "size": stat.st_size, "mtime": int(stat.st_mtime), "status": status,
                "given_name": given_name, "paper_id": paper_id, "attempts": attempts,
                "updated_at": self._stamp()}

    def _put_paper(self, match: PaperMatch):
        meta = match.meta
        self.db.put_paper({"paper_id": match.paper_id, "title": meta["title"],
                           "year": meta.get("year"), "year_online": meta.get("year_online"),
                           "authors": json.dumps(meta.get("authors", []), ensure_ascii=False),
                           "journal": meta.get("journal", ""), "source": meta["source"],
                           "fetched_at": self._stamp()})

    def _paper_match(self, paper_id: str) -> PaperMatch:
        row = self.db.get_paper(paper_id)
        meta = {key: row[key] for key in ("title", "year", "year_online", "journal", "source")}
        meta["authors"] = json.loads(row["authors"])
        return PaperMatch(paper_id, meta, "check" if meta["source"] == "pdf-only" else "ok")

    def _target(self, path: Path, fp: str, match: PaperMatch) -> Path:
        known = {row["display_path"]: (row["paper_id"], row["fingerprint"])
                 for row in self.db.conn.execute("SELECT display_path,paper_id,fingerprint FROM files")}
        return unique_path(path.parent, match.meta, self.config["format"],
                           paper_id=match.paper_id, fingerprint=fp, known=known, current=path,
                           word_sep=self.config.get("word_sep", "_"),
                           year_mode=self.config.get("year", "citation"),
                           title_limit=self.config.get("title_limit", 0),
                           suffix="_CHECK" if match.status == "check" else "")

    def _rename(self, path: Path, fp: str, match: PaperMatch, attempts: int,
                batch: str | None = None, source: str | None = None,
                given_name: str | None = None) -> ProcessResult:
        self._put_paper(match)
        target = self._target(path, fp, match)
        if target == path:
            self.db.put_file(self._row(path, fp, match.status, match.paper_id, path.name, attempts))
            return ProcessResult(match.status, path, "already correctly named")
        if target.exists():
            raise FileExistsError(target)
        try:
            path.rename(target)
        except OSError as exc:
            self.db.put_file(self._row(path, fp, "pending", match.paper_id, given_name, attempts))
            self._event("busy", path, f"rename failed: {exc}; will retry", source=match.meta["source"])
            return ProcessResult("pending", path, str(exc))
        new_row = self._row(target, fp, match.status, match.paper_id, target.name, attempts)
        self.db.record_rename(path, new_row, source or match.meta["source"], match.status,
                              batch or self._batch(), self._stamp())
        kind = "needs_check" if match.status == "check" else "renamed"
        self._event(kind, target, f"{path.name} -> {target.name}", old_path=str(path),
                    new_path=str(target), source=match.meta["source"])
        return ProcessResult(match.status, target, f"{path.name} -> {target.name}")

    def process(self, path: str | Path, *, retry: bool = False,
                batch: str | None = None) -> ProcessResult:
        path = Path(path)
        if path.suffix.lower() != ".pdf" or path.name.startswith((".", "~$")) or not path.is_file():
            return ProcessResult("skipped", path, "not an eligible PDF")
        prior = self.db.get_file(path)
        if prior and prior["status"] == "ok":
            stat = path.stat()
            if prior["size"] != stat.st_size or prior["mtime"] != int(stat.st_mtime):
                self.db.put_file(self._row(path, fingerprint(path), "ok", prior["paper_id"],
                                           prior["given_name"], prior["attempts"]))
            return ProcessResult("skipped", path, "already named")
        if prior and prior["status"] == "unreadable":
            stat = path.stat()
            if prior["size"] == stat.st_size and prior["mtime"] == int(stat.st_mtime):
                return ProcessResult("skipped", path, "unchanged unreadable PDF")
        if not self.stable(path):
            self._event("skipped", path, "file is still changing")
            return ProcessResult("skipped", path, "file is still changing")
        fp = fingerprint(path)
        if prior and prior["fingerprint"] != fp and prior["status"] != "ok":
            self.db.delete_file(path)
            prior = None
        twin = None
        if prior is None:
            twins = self.db.files_by_fingerprint(fp)
            stale = next((row for row in twins if not Path(row["display_path"]).exists()), None)
            if stale:
                moved = dict(stale)
                moved.update(self._row(path, fp, stale["status"], stale["paper_id"],
                                       stale["given_name"], stale["attempts"]))
                self.db.relocate_file(stale["display_path"], moved)
                prior = self.db.get_file(path)
                if prior["status"] == "ok":
                    return ProcessResult("skipped", path, "moved or hand-renamed file")
            else:
                twin = next((row for row in twins if row["paper_id"]), None)
        if prior and prior["given_name"] and prior["given_name"] != path.name:
            return ProcessResult("skipped", path, "hand-renamed file")
        if prior and not retry:
            return ProcessResult("skipped", path, "awaiting retry pass")
        if prior and prior["attempts"] >= 5 and prior["status"] == "unknown":
            return ProcessResult("skipped", path, "lookup attempts exhausted")
        if prior and prior["status"] == "pending" and prior["paper_id"]:
            return self._rename(path, fp, self._paper_match(prior["paper_id"]),
                                prior["attempts"], batch, given_name=prior["given_name"])
        if twin:
            return self._rename(path, fp, self._paper_match(twin["paper_id"]),
                                0, batch)
        try:
            info = self.read_pdf(path)
        except PdfReadError as exc:
            self.db.put_file(self._row(path, fp, "unreadable", attempts=0))
            self._event("unidentified", path, f"unreadable PDF: {exc}")
            return ProcessResult("unreadable", path, str(exc))
        outcome = self.identifier.identify(path, info)
        attempts = (prior["attempts"] if prior else 0) + outcome.attempts_delta
        if outcome.match is None:
            self.db.put_file(self._row(path, fp, "unknown", attempts=attempts))
            self._event("unidentified", path, "paper not identified")
            return ProcessResult("unknown", path, "paper not identified")
        return self._rename(path, fp, outcome.match, attempts, batch,
                            given_name=prior["given_name"] if prior else None)
