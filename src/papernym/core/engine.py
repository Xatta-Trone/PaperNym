"""Safe per-file processing, scan, reformat, and undo operations."""

from __future__ import annotations

import datetime as dt
import fnmatch
import hashlib
import json
import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .db import Database, path_key
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
        self._planned: dict[str, tuple[str | None, str | None]] = {}

    def _event(self, kind: str, path: Path, message: str, **extra):
        event = {"type": kind, "path": str(path), "message": message}
        event.update(extra)
        self.on_event(event)

    def excluded(self, path: Path) -> bool:
        for pattern in self.config.get("exclude", []):
            if pattern.endswith("/"):
                folder_pattern = pattern[:-1]
                if any(fnmatch.fnmatch(part, folder_pattern) for part in path.parent.parts):
                    return True
            elif fnmatch.fnmatch(path.name, pattern):
                return True
        return False

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
        known.update(self._planned)
        return unique_path(path.parent, match.meta, self.config["format"],
                           paper_id=match.paper_id, fingerprint=fp, known=known, current=path,
                           word_sep=self.config.get("word_sep", "_"),
                           year_mode=self.config.get("year", "citation"),
                           title_limit=self.config.get("title_limit", 0),
                           suffix="_CHECK" if match.status == "check" else "")

    def _rename(self, path: Path, fp: str, match: PaperMatch, attempts: int,
                batch: str | None = None, source: str | None = None,
                given_name: str | None = None, dry_run: bool = False) -> ProcessResult:
        if not dry_run:
            self._put_paper(match)
        target = self._target(path, fp, match)
        if target == path:
            if not dry_run:
                self.db.put_file(self._row(path, fp, match.status, match.paper_id, path.name, attempts))
            return ProcessResult(match.status, path, "already correctly named")
        if dry_run:
            self._planned[str(target)] = (match.paper_id, fp)
            self._event("preview", path, f"{path.name} -> {target.name}",
                        old_path=str(path), new_path=str(target), source=source or match.meta["source"])
            return ProcessResult("preview", target, f"{path.name} -> {target.name}")
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
                batch: str | None = None, dry_run: bool = False) -> ProcessResult:
        path = Path(path)
        if (path.suffix.lower() != ".pdf" or path.name.startswith((".", "~$"))
                or self.excluded(path) or not path.is_file()):
            return ProcessResult("skipped", path, "not an eligible PDF")
        prior = self.db.get_file(path)
        if prior and prior["status"] == "ok":
            stat = path.stat()
            if not dry_run and (prior["size"] != stat.st_size or prior["mtime"] != int(stat.st_mtime)):
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
            if not dry_run:
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
                if not dry_run:
                    self.db.relocate_file(stale["display_path"], moved)
                    prior = self.db.get_file(path)
                else:
                    prior = moved
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
                                prior["attempts"], batch, given_name=prior["given_name"], dry_run=dry_run)
        if twin:
            return self._rename(path, fp, self._paper_match(twin["paper_id"]),
                                0, batch, dry_run=dry_run)
        try:
            info = self.read_pdf(path)
        except PdfReadError as exc:
            if not dry_run:
                self.db.put_file(self._row(path, fp, "unreadable", attempts=0))
            self._event("unidentified", path, f"unreadable PDF: {exc}")
            return ProcessResult("unreadable", path, str(exc))
        old_read_only = getattr(self.identifier, "read_only", None)
        if dry_run and old_read_only is not None:
            self.identifier.read_only = True
        try:
            outcome = self.identifier.identify(path, info)
        finally:
            if dry_run and old_read_only is not None:
                self.identifier.read_only = old_read_only
        attempts = (prior["attempts"] if prior else 0) + outcome.attempts_delta
        if outcome.match is None:
            if not dry_run:
                self.db.put_file(self._row(path, fp, "unknown", attempts=attempts))
            self._event("unidentified", path, "paper not identified")
            return ProcessResult("unknown", path, "paper not identified")
        return self._rename(path, fp, outcome.match, attempts, batch,
                            given_name=prior["given_name"] if prior else None, dry_run=dry_run)

    @staticmethod
    def _inside(path: str | Path, root: str | Path, recursive: bool = True) -> bool:
        try:
            relative = Path(path_key(path)).relative_to(Path(path_key(root)))
            return recursive or len(relative.parts) == 1
        except ValueError:
            return False

    def _scan_files(self, folders: list[dict]) -> tuple[list[Path], list[dict]]:
        files = []
        reachable = []
        seen = set()
        for folder in folders:
            root = Path(folder["path"])
            if not root.is_dir():
                self._event("folder_unavailable", root, "folder is unavailable")
                continue
            reachable.append(folder)
            iterator = root.rglob("*") if folder.get("recursive", True) else root.iterdir()
            for path in iterator:
                if path.suffix.lower() == ".pdf" and path.is_file() and path_key(path) not in seen:
                    seen.add(path_key(path))
                    files.append(path)
        return sorted(files), reachable

    def prune(self, reachable: list[dict]) -> int:
        """Forget deleted files only beneath currently reachable watched folders."""
        removed = 0
        for row in self.db.conn.execute("SELECT path,display_path FROM files").fetchall():
            if (not Path(row["display_path"]).exists()
                    and any(self._inside(row["display_path"], folder["path"],
                                         folder.get("recursive", True)) for folder in reachable)):
                self.db.delete_file(row["path"])
                removed += 1
        return removed

    def scan(self, folders: list[dict] | None = None, *, dry_run: bool = False) -> dict[str, int]:
        """Process every eligible PDF, emit progress, and prune disappeared rows."""
        folders = self.config.get("folders", []) if folders is None else folders
        files, reachable = self._scan_files(folders)
        counts = {key: 0 for key in ("ok", "check", "unknown", "pending", "unreadable", "skipped", "preview")}
        self._event("scan_started", Path("."), f"scanning {len(files)} PDFs", total=len(files))
        batch = self._batch()
        self._planned.clear()
        for index, path in enumerate(files, 1):
            result = self.process(path, retry=True, batch=batch, dry_run=dry_run)
            counts[result.status] += 1
            self._event("scan_progress", path, f"{index}/{len(files)}", done=index, total=len(files))
        removed = 0 if dry_run else self.prune(reachable)
        counts["pruned"] = removed
        counts["total"] = len(files)
        self._event("scan_finished", Path("."), f"scan finished: {len(files)} PDFs", counts=counts)
        return counts

    def reformat(self, *, dry_run: bool = False, include_manual: bool = False) -> dict[str, int]:
        """Render saved paper records with the current template."""
        self._planned.clear()
        counts = {"preview": 0, "ok": 0, "check": 0, "skipped": 0}
        batch = self._batch()
        rows = self.db.conn.execute("SELECT * FROM files WHERE status IN ('ok','check')").fetchall()
        for row in rows:
            path = Path(row["display_path"])
            if (not path.exists() or not row["paper_id"] or
                    (row["given_name"] != path.name and not include_manual)):
                counts["skipped"] += 1
                continue
            match = self._paper_match(row["paper_id"])
            result = self._rename(path, row["fingerprint"], match, row["attempts"], batch,
                                  source="reformat", given_name=row["given_name"], dry_run=dry_run)
            counts[result.status] = counts.get(result.status, 0) + 1
        return counts
