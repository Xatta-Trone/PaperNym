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
from .identify import Identifier, PaperMatch, normal_title
from .naming import unique_path
from .pdfread import DOI_RE, PdfReadError, read_pdf
from .sources.common import surname


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


def stable_file(path: Path, timeout: float = 120, pause: float = 1.5,
                settled_after: float = 30) -> bool:
    """Wait for a nonempty file whose size remains unchanged for two checks."""
    try:
        stat = path.stat()
    except OSError:
        return False
    if stat.st_size > 0 and time.time() - stat.st_mtime > settled_after:
        return True  # Untouched for a while: no writer is active, skip the wait.
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


def move_no_replace(source: Path, target: Path) -> None:
    """Move within one folder without replacing a concurrently created target."""
    if target.exists():
        raise FileExistsError(target)
    if os.name == "nt":
        source.rename(target)  # Windows rename refuses an occupied destination.
    else:
        os.link(source, target)  # Atomic exclusive creation on the same filesystem.
        try:
            source.unlink()
        except OSError:
            target.unlink()
            raise


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
            move_no_replace(path, target)
        except OSError as exc:
            self.db.put_file(self._row(path, fp, "pending", match.paper_id, given_name, attempts))
            self._event("busy", path, f"rename failed: {exc}; will retry", source=match.meta["source"])
            return ProcessResult("pending", path, str(exc))
        new_row = self._row(target, fp, match.status, match.paper_id, target.name, attempts)
        try:
            self.db.record_rename(path, new_row, source or match.meta["source"], match.status,
                                  batch or self._batch(), self._stamp())
        except Exception:
            move_no_replace(target, path)
            raise
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
            if stale and self._original_returned(stale, path):
                # The tool-named file is gone and the same PDF is back under the name it had
                # before PaperNym renamed it (for example the original download pasted again):
                # name it again from the saved record, with no web call.
                if not dry_run:
                    self.db.delete_file(stale["path"])
                twin, stale = stale, None
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
                    if not dry_run:
                        self._event("skipped", path, "moved or renamed by you; your name is kept")
                    return ProcessResult("skipped", path, "moved or hand-renamed file")
            elif twin is None:
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

    def _original_returned(self, stale, path: Path) -> bool:
        """True if ``stale`` was named by PaperNym and ``path`` has that file's pre-rename name."""
        if stale["status"] != "ok" or not stale["paper_id"]:
            return False
        if stale["given_name"] != Path(stale["display_path"]).name:
            return False  # the user had already renamed it
        row = self.db.conn.execute(
            "SELECT old_path FROM history WHERE new_path=? AND undone=0 ORDER BY id DESC LIMIT 1",
            (str(stale["display_path"]),)).fetchone()
        return bool(row) and os.path.normcase(Path(row["old_path"]).name) == os.path.normcase(path.name)

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
        try:
            for index, path in enumerate(files, 1):
                result = self.process(path, retry=True, batch=batch, dry_run=dry_run)
                counts[result.status] += 1
                self._event("scan_progress", path, f"{index}/{len(files)}", done=index, total=len(files))
        finally:
            self._planned.clear()  # previewed names must not block later real renames
        removed = 0 if dry_run else self.prune(reachable)
        counts["pruned"] = removed
        counts["total"] = len(files)
        self._event("scan_finished", Path("."), f"scan finished: {len(files)} PDFs", counts=counts)
        return counts

    def reformat(self, *, dry_run: bool = False, include_manual: bool = False) -> dict[str, int]:
        """Render saved paper records with the current template."""
        self._planned.clear()
        try:
            return self._reformat(dry_run, include_manual)
        finally:
            self._planned.clear()

    def _reformat(self, dry_run: bool, include_manual: bool) -> dict[str, int]:
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
            if self.config.get("year") == "online" and match.meta.get("year_online") is None:
                marker = "online_lookup:" + row["paper_id"]
                attempted = self.db.conn.execute("SELECT 1 FROM meta WHERE key=?", (marker,)).fetchone()
                if not attempted:
                    fresh = None
                    if hasattr(self.identifier, "identify_online"):
                        old_read_only = getattr(self.identifier, "read_only", None)
                        if dry_run and old_read_only is not None:
                            self.identifier.read_only = True
                        try:
                            fresh, _ = self.identifier.identify_online(path, self.read_pdf(path), refresh=True)
                        except PdfReadError:
                            pass
                        finally:
                            if dry_run and old_read_only is not None:
                                self.identifier.read_only = old_read_only
                    if fresh:
                        match = PaperMatch(row["paper_id"], fresh.meta, match.status)
                        if not dry_run:
                            self._put_paper(match)
                    if not dry_run:
                        with self.db.conn:
                            self.db.conn.execute("INSERT OR IGNORE INTO meta VALUES (?,?)", (marker, self._stamp()))
            result = self._rename(path, row["fingerprint"], match, row["attempts"], batch,
                                  source="reformat", given_name=row["given_name"], dry_run=dry_run)
            counts[result.status] = counts.get(result.status, 0) + 1
        return counts

    def undo(self, last: int | None = None) -> dict[str, int]:
        """Undo the latest batch or the latest N renames, never overwriting."""
        if last is not None and last < 1:
            raise ValueError("last must be a positive integer")
        rows = self.db.conn.execute("SELECT * FROM history WHERE undone=0 ORDER BY id DESC").fetchall()
        if not rows:
            return {"undone": 0, "skipped": 0}
        chosen = rows[:last] if last is not None else [row for row in rows if row["batch"] == rows[0]["batch"]]
        return self._undo_rows(chosen)

    def undo_ids(self, ids) -> dict[str, int]:
        """Undo specific history rows (a row or a whole batch), newest first."""
        ids = [int(value) for value in ids]
        if not ids:
            return {"undone": 0, "skipped": 0}
        marks = ",".join("?" for _ in ids)
        rows = self.db.conn.execute(f"SELECT * FROM history WHERE undone=0 AND id IN ({marks}) "
                                    "ORDER BY id DESC", ids).fetchall()
        return self._undo_rows(rows)

    def undo_path(self, path: str | Path) -> dict[str, int]:
        """Undo the newest rename that produced ``path``."""
        row = self.db.conn.execute("SELECT * FROM history WHERE undone=0 AND new_path=? ORDER BY id DESC",
                                   (str(path),)).fetchone()
        return self._undo_rows([row] if row else [])

    def _undo_rows(self, chosen) -> dict[str, int]:
        counts = {"undone": 0, "skipped": 0}
        for history in chosen:
            old = Path(history["old_path"])
            new = Path(history["new_path"])
            current = self.db.get_file(new)
            if not new.exists() or old.exists() or current is None:
                counts["skipped"] += 1
                self._event("skipped", new, "cannot undo: moved, missing, or old name occupied")
                continue
            move_no_replace(new, old)
            old_file = dict(current)
            old_file.update({"path": str(old), "display_path": str(old),
                             "given_name": old.name if history["source"] == "reformat" else current["given_name"],
                             "updated_at": self._stamp()})
            try:
                self.db.undo_history_row(history["id"], new, old_file)
            except Exception:
                move_no_replace(old, new)
                raise
            counts["undone"] += 1
            self._event("undo", old, f"{new.name} -> {old.name}", old_path=str(new), new_path=str(old))
        return counts

    def fix(self, path: str | Path, *, doi: str | None = None, title: str | None = None,
            author: str | None = None, year: int | None = None) -> ProcessResult:
        """Replace a check/unknown file's metadata by DOI or edited fields."""
        path = Path(path)
        row = self.db.get_file(path)
        if row is None or row["status"] not in ("check", "unknown") or not path.is_file():
            raise ValueError("manual fix requires an existing check or unknown PDF")
        if bool(doi) == bool(title):
            raise ValueError("provide exactly one of DOI or edited title")
        if doi:
            doi = doi.strip().lower().rstrip(".)('")
            if not DOI_RE.fullmatch(doi):
                raise ValueError("invalid DOI")
            info = self.read_pdf(path)
            match, _ = self.identifier.identify_online(path, info, refresh=True, only_doi=doi)
            if match is None:
                return ProcessResult(row["status"], path, "DOI could not be verified")
        else:
            if year is not None and (type(year) is not int or year < 0):
                raise ValueError("year must be a nonnegative integer")
            clean_title = " ".join(title.split())
            if not clean_title:
                raise ValueError("title must not be empty")
            first = surname(author) if author else ""
            meta = {"title": clean_title, "year": year, "year_online": year,
                    "authors": [first] if first else [], "journal": "", "source": "manual"}
            match = PaperMatch("title:" + normal_title(clean_title), meta)
        return self._rename(path, fingerprint(path), match, 0, source=match.meta["source"],
                            given_name=row["given_name"])

    def keep_name(self, path: str | Path) -> ProcessResult:
        """Treat a PDF as hand-named: never renamed or asked about again.

        Used for "Ignore" in Needs attention and for unticked files in a preview.
        """
        path = Path(path)
        if not path.is_file():
            raise ValueError("keep_name requires an existing PDF")
        prior = self.db.get_file(path)
        self.db.put_file(self._row(path, fingerprint(path), "ok", None, path.name,
                                   prior["attempts"] if prior else 0))
        self._event("skipped", path, "name kept; PaperNym will leave this file alone")
        return ProcessResult("ok", path, "name kept")

    def refresh(self, path: str | Path) -> ProcessResult:
        """Re-query one known PDF, preserving its name if services fail."""
        path = Path(path)
        row = self.db.get_file(path)
        if row is None or not path.is_file():
            raise ValueError("refresh requires a known PDF")
        if row["given_name"] and row["given_name"] != path.name:
            return ProcessResult("skipped", path, "hand-renamed file")
        match, _ = self.identifier.identify_online(path, self.read_pdf(path), refresh=True)
        if match is None:
            return ProcessResult(row["status"], path, "metadata refresh did not find a verified record")
        return self._rename(path, fingerprint(path), match, row["attempts"],
                            source=match.meta["source"], given_name=row["given_name"])
