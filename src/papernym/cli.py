"""Command-line interface: a thin layer over ``core.config``, ``core.engine`` and ``core.watcher``."""

from __future__ import annotations

import argparse
import logging
import os
import re
import sys
import time
from pathlib import Path
from typing import Callable

from . import __version__
from .core import engine as engine_module
from .core.config import (ConfigError, add_folder, load_config, save_config, settings_dir,
                          _within)
from .core.db import Database, DatabaseError
from .core.identify import (ARXIV_SOURCES, DOI_SOURCES, TITLE_SOURCES, Identifier,
                            title_hit_ok, title_in_text)
from .core.keystore import SecretStore
from .core.lock import LockBusyError, WriterLock
from .core.logsetup import setup_file_log
from .core.naming import PRESETS, TemplateError, render_preset, validate_template
from .core.pdfread import ARXIV_FILE_RE, ARXIV_RE, PdfReadError, find_dois, read_pdf
from .core.sources.http import HttpClient, NetError


EXAMPLE = {"title": "Deep learning for crash severity prediction models", "year": 2025,
           "year_online": 2024, "authors": ["Smith", "Jones", "Lee"],
           "journal": "Accid Anal Prev", "source": "example"}
NO_TITLE_PRESETS = {"author_year", "author_year_journal"}
WORD_SEPS = {"_": "_", " ": " ", "space": " ", "-": "-", "none": "", "": ""}
KEY_NAMES = {"openalex": ("openalex_key", "OPENALEX_API_KEY"),
             "semanticscholar": ("s2_key", "S2_API_KEY")}
BUSY_MESSAGE = ("PaperNym is already running (tray app or 'papernym watch') and owns the "
                "database. Stop it first, or use --dry-run.")
log = logging.getLogger("papernym")


class CliError(Exception):
    """A command failed; the message is printed and the exit code is 1."""


COLORS = {"ok": "32", "check": "33", "?": "35", "busy": "34", "skip": "90",
          "warn": "1;31", "preview": "36", "undo": "94"}


def _enable_windows_ansi(stream) -> bool:
    """Turn on ANSI escape handling for a Windows console; False if impossible."""
    try:
        import ctypes
        import msvcrt
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = msvcrt.get_osfhandle(stream.fileno())
        mode = wintypes.DWORD()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        return bool(mode.value & 0x0004 or kernel32.SetConsoleMode(handle, mode.value | 0x0004))
    except (AttributeError, OSError, ValueError, ImportError):
        return False


def use_color(stream, disabled: bool = False) -> bool:
    """Colour only an interactive terminal, unless NO_COLOR or --no-color is set."""
    if disabled or os.environ.get("NO_COLOR") or os.environ.get("TERM") == "dumb":
        return False
    try:
        if not stream.isatty():
            return False
    except (AttributeError, ValueError):
        return False
    return _enable_windows_ansi(stream) if os.name == "nt" else True


class Output:
    """Prefixed console lines (coloured on a terminal), mirrored to the rotating log file."""

    def __init__(self, stream=None, err=None, *, color: bool | None = None):
        self.stream = stream or sys.stdout
        self.err = err or sys.stderr
        self.color = use_color(self.stream) if color is None else color
        self.err_color = use_color(self.err) if color is None else color
        self.tally: dict[str, int] = {}

    @staticmethod
    def _paint(text: str, code: str, enabled: bool) -> str:
        return f"\033[{code}m{text}\033[0m" if enabled else text

    def line(self, text: str = "", prefix: str | None = None):
        if prefix:
            message = f"[{prefix}] {text}"
            shown = f"{self._paint(f'[{prefix}]', COLORS.get(prefix, '0'), self.color)} {text}"
        else:
            message = shown = text
            if text.startswith("Summary:"):
                shown = self._paint(text, "1", self.color)
        print(shown, file=self.stream, flush=True)
        if prefix:
            log.info(message)

    def error(self, text: str):
        print(f"{self._paint('[warn]', COLORS['warn'], self.err_color)} {text}", file=self.err, flush=True)
        log.warning(text)

    def event(self, event: dict):
        kind = event.get("type")
        self.tally[kind] = self.tally.get(kind, 0) + 1
        name = Path(event.get("path", "")).name
        message = event.get("message", "")
        if kind == "renamed":
            self.line(message, "ok")
        elif kind == "needs_check":
            self.line(message, "check")
        elif kind == "preview":
            self.line(message, "preview")
        elif kind == "unidentified":
            self.line(f"{name}: {message}", "?")
        elif kind == "busy":
            self.line(f"{name}: {message}", "busy")
        elif kind == "skipped":
            self.line(f"{name}: {message}", "skip")
        elif kind == "undo":
            self.line(message, "undo")
        elif kind == "source_unavailable":
            self.line(message, "warn")
        elif kind == "folder_unavailable":
            self.line(f"{event.get('path')}: {message}", "warn")
        elif kind == "folder_attached":
            self.line(f"watching {event.get('path')}", "ok")
        elif kind == "settings_reloaded":
            self.line("settings reloaded", "ok")
        elif kind == "scan_started":
            self.line(f"Scanning {event.get('total', 0)} PDFs...")
        elif kind == "scan_finished":
            self.line(scan_summary(event.get("counts", {})))


def scan_summary(counts: dict) -> str:
    parts = [f"{counts.get('total', 0)} PDFs"]
    for key, label in (("preview", "would be renamed"), ("ok", "named"), ("check", "to check"),
                       ("unknown", "unidentified"), ("unreadable", "unreadable"),
                       ("pending", "pending"), ("skipped", "unchanged"), ("pruned", "forgotten")):
        if counts.get(key):
            parts.append(f"{counts[key]} {label}")
    return "Summary: " + ", ".join(parts)


class Context:
    def __init__(self, args, out: Output, http_get: Callable | None):
        self.args = args
        self.out = out
        self.http_get = http_get
        self.home = settings_dir()

    # Settings -----------------------------------------------------------------
    def settings(self) -> dict:
        """Settings as stored on disk (environment keys not applied)."""
        return load_config(self.home, apply_env=False)

    def save(self, config: dict):
        save_config(config, self.home)

    # Engine -------------------------------------------------------------------
    def engine(self, db: Database):
        config = load_config(self.home)
        identifier = Identifier(config, http_get=self.http_get, db=db, on_event=self.out.event)
        return engine_module.Engine(config, db, identifier, on_event=self.out.event,
                                    stable_fn=engine_module.stable_file)

    def writer(self, dry_run: bool):
        """The writer lock for renaming commands; a no-op for dry runs."""
        if dry_run:
            return _NoLock()
        lock = WriterLock(self.home)
        try:
            return lock.acquire()
        except LockBusyError as exc:
            raise CliError(BUSY_MESSAGE) from exc


class _NoLock:
    def release(self):
        pass


# Settings commands ---------------------------------------------------------------

def cmd_add_folder(ctx: Context) -> int:
    warnings = []
    config = add_folder(ctx.settings(), ctx.args.path, recursive=not ctx.args.no_subfolders,
                        on_warning=warnings.append)
    ctx.save(config)
    for warning in warnings:
        ctx.out.line(warning, "warn")
    added = config["folders"][-1]
    scope = "with subfolders" if added["recursive"] else "without subfolders"
    ctx.out.line(f"watching {added['path']} ({scope})", "ok")
    return 0


def cmd_remove_folder(ctx: Context) -> int:
    config = ctx.settings()
    target = os.path.abspath(os.path.expanduser(ctx.args.path))
    keep = [folder for folder in config["folders"]
            if not (_within(folder["path"], target) and _within(target, folder["path"]))]
    if len(keep) == len(config["folders"]):
        raise CliError(f"not a watched folder: {target}")
    config["folders"] = keep
    ctx.save(config)
    ctx.out.line(f"stopped watching {target}", "ok")
    return 0


def cmd_exclude(ctx: Context) -> int:
    config = ctx.settings()
    pattern = ctx.args.pattern
    if not pattern.strip():
        raise CliError("pattern must not be empty")
    if ctx.args.remove:
        if pattern not in config["exclude"]:
            raise CliError(f"not in the exclude list: {pattern}")
        config["exclude"].remove(pattern)
        ctx.save(config)
        ctx.out.line(f"no longer excluded: {pattern}", "ok")
    else:
        if pattern in config["exclude"]:
            ctx.out.line(f"already excluded: {pattern}", "skip")
            return 0
        config["exclude"].append(pattern)
        ctx.save(config)
        kind = "folder name" if pattern.endswith("/") else "file-name pattern"
        ctx.out.line(f"excluded {kind}: {pattern}", "ok")
    return 0


def cmd_set_key(ctx: Context) -> int:
    key_name, variable = KEY_NAMES[ctx.args.service]
    config = ctx.settings()
    config[key_name] = ctx.args.key.strip()
    ctx.save(config)
    store = SecretStore(ctx.home)
    if config[key_name] and store.available():
        ctx.out.line(f"{ctx.args.service} key saved in {store.describe()}", "ok")
    elif config[key_name]:
        ctx.out.line(f"{ctx.args.service} key saved", "ok")
        ctx.out.line("no system credential store found, so the key is in config.json "
                     "(readable only by you). Install and unlock a keyring such as GNOME Keyring "
                     f"or KWallet, or set {variable} in the environment instead.", "warn")
    else:
        ctx.out.line(f"{ctx.args.service} key removed", "ok")
    if variable in os.environ:
        ctx.out.line(f"{variable} is set in the environment and takes precedence", "warn")
    return 0


def cmd_set_email(ctx: Context) -> int:
    email = ctx.args.email.strip()
    if email and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise CliError(f"not an email address: {email}")
    config = ctx.settings()
    config["email"] = email
    ctx.save(config)
    ctx.out.line(f"Crossref email set to {email}" if email else "Crossref email removed", "ok")
    return 0


def preset_name(config: dict) -> str | None:
    if config["format"] in PRESETS:
        return config["format"]
    for name, (template, sep) in PRESETS.items():
        if config["format"] == template and config["word_sep"] == sep and name != "citekey":
            return name
    return None


def cmd_formats(ctx: Context) -> int:
    current = preset_name(ctx.settings())
    width = max(map(len, PRESETS))
    ctx.out.line("Fixed presets (set one with: papernym set-format PRESET)")
    for name in PRESETS:
        mark = "*" if name == current else " "
        note = "   (no title: names may collide)" if name in NO_TITLE_PRESETS else ""
        ctx.out.line(f" {mark} {name:<{width}}  {render_preset(name, EXAMPLE)}{note}")
    ctx.out.line()
    ctx.out.line('Custom: papernym set-format --custom "TEMPLATE" [--word-sep _|space|-|none]')
    ctx.out.line("Tokens: {year} {author} {authors} {title} {shorttitle} {journal}")
    if current is None:
        config = ctx.settings()
        ctx.out.line(f" * custom: {config['format']}  (word separator {config['word_sep']!r})")
    return 0


def cmd_set_format(ctx: Context) -> int:
    args = ctx.args
    config = ctx.settings()
    if args.custom is not None:
        if args.preset:
            raise CliError("give either a preset or --custom, not both")
        separator = "_" if args.word_sep is None else WORD_SEPS[args.word_sep]
        try:
            warnings = validate_template(args.custom)
        except TemplateError as exc:
            raise CliError(f"invalid template: {exc}") from exc
        config["format"] = args.custom
        config["word_sep"] = separator
        ctx.save(config)
        for warning in warnings:
            ctx.out.line(warning, "warn")
        ctx.out.line(f"custom format set: {args.custom}", "ok")
    else:
        if not args.preset:
            raise CliError("give a preset name or --custom TEMPLATE (see: papernym formats)")
        if args.word_sep is not None:
            raise CliError("--word-sep applies only to --custom; presets have a fixed separator")
        if args.preset not in PRESETS:
            raise CliError(f"unknown preset: {args.preset} (see: papernym formats)")
        config["format"] = args.preset
        config["word_sep"] = PRESETS[args.preset][1]
        ctx.save(config)
        if args.preset in NO_TITLE_PRESETS:
            ctx.out.line("this preset has no title; names may collide and get _b, _c endings", "warn")
        ctx.out.line(f"format set: {args.preset}  e.g. {render_preset(args.preset, EXAMPLE)}", "ok")
    ctx.out.line("existing files keep their names; run 'papernym reformat --dry-run' to preview", "ok")
    return 0


def cmd_set_year(ctx: Context) -> int:
    config = ctx.settings()
    config["year"] = ctx.args.mode
    ctx.save(config)
    ctx.out.line(f"year mode: {ctx.args.mode}", "ok")
    return 0


def cmd_set_title_search(ctx: Context) -> int:
    config = ctx.settings()
    config["title_search"] = ctx.args.state == "on"
    ctx.save(config)
    if config["title_search"]:
        ctx.out.line("title search on: titles may be sent to Crossref, OpenAlex, Semantic Scholar", "ok")
    else:
        ctx.out.line("title search off: only DOI and arXiv lookups run", "ok")
    return 0


def _key_state(stored: str, variable: str, where: str) -> str:
    if os.environ.get(variable):
        return f"set (from {variable})"
    return f"set (in {where})" if stored else "not set"


def cmd_show(ctx: Context) -> int:
    config = ctx.settings()
    out = ctx.out
    out.line(f"PaperNym {__version__}")
    out.line(f"Settings folder: {ctx.home}")
    out.line("Folders:")
    if not config["folders"]:
        out.line("  (none) add one with: papernym add-folder PATH")
    for folder in config["folders"]:
        flags = ["subfolders" if folder["recursive"] else "no subfolders"]
        if not Path(folder["path"]).is_dir():
            flags.append("UNAVAILABLE")
        out.line(f"  {folder['path']}  ({', '.join(flags)})")
    out.line("Exclude:      " + (", ".join(config["exclude"]) or "(none)"))
    name = preset_name(config)
    if name:
        out.line(f"Format:       {name}  e.g. {render_preset(name, EXAMPLE)}")
    else:
        out.line(f"Format:       custom {config['format']}  (word separator {config['word_sep']!r})")
    out.line(f"Year:         {config['year']}")
    out.line(f"Title search: {'on' if config['title_search'] else 'off'}")
    out.line(f"Email:        {config['email'] or 'not set'}")
    where = SecretStore(ctx.home).describe()
    out.line(f"OpenAlex key: {_key_state(config['openalex_key'], 'OPENALEX_API_KEY', where)}")
    out.line(f"S2 key:       {_key_state(config['s2_key'], 'S2_API_KEY', where)}")
    out.line(f"Key store:    {where}")
    if config["paused"]:
        out.line("Paused:       yes (the watcher ignores new files)")
    return 0


# Renaming commands ---------------------------------------------------------------

def cmd_scan(ctx: Context) -> int:
    dry_run = ctx.args.dry_run
    lock = ctx.writer(dry_run)
    try:
        with Database(ctx.home) as db:
            worker = ctx.engine(db)
            folders = None
            if ctx.args.folder:
                root = Path(ctx.args.folder).expanduser().resolve()
                if not root.is_dir():
                    raise CliError(f"not a folder: {root}")
                folders = [{"path": str(root), "recursive": not ctx.args.no_subfolders}]
                scope = "with subfolders" if folders[0]["recursive"] else "without subfolders"
                ctx.out.line(f"scanning {root} ({scope}) once; it is not added to the watched folders")
            elif not worker.config["folders"]:
                ctx.out.line("no folders configured; add one with: papernym add-folder PATH, "
                             "or scan the current folder once with: papernym scan .", "warn")
                ctx.out.line(scan_summary({"total": 0}))
                return 0
            if dry_run:
                ctx.out.line("dry run: nothing will be renamed", "preview")
            worker.scan(folders, dry_run=dry_run)
    finally:
        lock.release()
    return 0


def cmd_watch(ctx: Context) -> int:
    from .core.watcher import Watcher

    with Database(ctx.home) as db:
        worker = ctx.engine(db)
        if not worker.config["folders"]:
            ctx.out.line("no folders configured yet; add one with: papernym add-folder PATH", "warn")
        watcher = Watcher(worker, poll=ctx.args.poll)
        try:
            watcher.start()
        except LockBusyError as exc:
            raise CliError(BUSY_MESSAGE) from exc
        ctx.out.line("watching for new PDFs; press Ctrl+C to stop", "ok")
        try:
            while True:
                watcher.process_next(timeout=1)
                watcher.tick()
        except KeyboardInterrupt:
            ctx.out.line("stopped", "ok")
        finally:
            watcher.stop()
    return 0


def cmd_reformat(ctx: Context) -> int:
    dry_run = ctx.args.dry_run
    lock = ctx.writer(dry_run)
    try:
        with Database(ctx.home) as db:
            if dry_run:
                ctx.out.line("dry run: nothing will be renamed", "preview")
            counts = ctx.engine(db).reformat(dry_run=dry_run, include_manual=ctx.args.include_manual)
    finally:
        lock.release()
    tally = ctx.out.tally
    if dry_run:
        changed = f"{tally.get('preview', 0)} would be renamed"
    else:
        changed = f"{tally.get('renamed', 0) + tally.get('needs_check', 0)} renamed"
    handled = sum(counts.get(key, 0) for key in ("preview", "ok", "check"))
    unchanged = handled - tally.get("preview", 0) - tally.get("renamed", 0) - tally.get("needs_check", 0)
    ctx.out.line(f"Summary: {changed}, {unchanged} already match, {counts.get('skipped', 0)} skipped"
                 + ("" if ctx.args.include_manual else " (hand-renamed files are left alone)"))
    return 0


def cmd_undo(ctx: Context) -> int:
    lock = ctx.writer(False)
    try:
        with Database(ctx.home) as db:
            counts = ctx.engine(db).undo(last=ctx.args.last)
    finally:
        lock.release()
    if not counts["undone"] and not counts["skipped"]:
        ctx.out.line("nothing to undo", "skip")
        return 0
    ctx.out.line(f"Summary: {counts['undone']} undone, {counts['skipped']} could not be undone")
    return 0 if not counts["skipped"] else 1


def _clean_doi(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^(?:https?://)?(?:dx\.)?doi\.org/", "", text, flags=re.I)
    return re.sub(r"^doi:\s*", "", text, flags=re.I)


def cmd_fix(ctx: Context) -> int:
    path = Path(ctx.args.path).expanduser().resolve()
    lock = ctx.writer(False)
    try:
        with Database(ctx.home) as db:
            worker = ctx.engine(db)
            row = db.get_file(path)
            if row is None:
                raise CliError(f"PaperNym has no record of {path}; run 'papernym scan' first")
            if row["status"] not in ("check", "unknown"):
                raise CliError(f"{path.name} is not waiting for a fix (status: {row['status']})")
            try:
                result = worker.fix(path, doi=_clean_doi(ctx.args.doi))
            except ValueError as exc:
                raise CliError(str(exc)) from exc
    finally:
        lock.release()
    if result.status in ("ok", "check") and result.path != path:
        return 0
    if result.status in ("ok", "check"):
        ctx.out.line(f"{path.name}: already named for this DOI", "ok")
        return 0
    ctx.out.line(f"{path.name}: {result.message}", "?")
    return 1


def cmd_status(ctx: Context) -> int:
    with Database(ctx.home) as db:
        rows = db.conn.execute("SELECT status, COUNT(*) AS n FROM files GROUP BY status").fetchall()
        counts = {row["status"]: row["n"] for row in rows}
        attention = db.files_by_status("check", "unknown", "unreadable", "pending")
        renames = db.conn.execute("SELECT COUNT(*) FROM history WHERE undone=0").fetchone()[0]
    lock = WriterLock(ctx.home)
    try:
        lock.acquire()
        running = False
    except LockBusyError:
        running = True
    finally:
        lock.release()
    labels = (("ok", "named"), ("check", "to check"), ("unknown", "unidentified"),
              ("unreadable", "unreadable"), ("pending", "pending"))
    ctx.out.line("Files: " + ", ".join(f"{counts.get(key, 0)} {label}" for key, label in labels))
    ctx.out.line(f"Renames in history: {renames}")
    ctx.out.line("Watcher: " + ("running (tray app or 'papernym watch')" if running else "not running"))
    if not attention:
        ctx.out.line("Nothing needs attention.")
        return 0
    ctx.out.line("Needs attention:")
    prefix = {"check": "check", "unknown": "?", "unreadable": "?", "pending": "busy"}
    hints = {"check": "offline guess; verify, or: papernym fix PATH --doi DOI",
             "unknown": "not identified; papernym fix PATH --doi DOI",
             "unreadable": "PDF could not be read",
             "pending": "rename waiting for retry"}
    for row in attention:
        missing = "" if Path(row["display_path"]).exists() else " (missing)"
        ctx.out.line(f"{row['display_path']}{missing}  -- {hints[row['status']]}",
                     prefix[row["status"]])
    return 0


# Diagnostics ---------------------------------------------------------------------

def cmd_test_apis(ctx: Context) -> int:
    from .core.apitest import run_checks

    config = load_config(ctx.home)
    http_get = ctx.http_get or HttpClient(config).get
    ctx.out.line(f"Settings folder: {ctx.home}")
    ctx.out.line(f"OpenAlex key: {'set' if config['openalex_key'] else 'not set'}   "
                 f"Semantic Scholar key: {'set' if config['s2_key'] else 'not set'}   "
                 f"Email: {config['email'] or 'not set'}")

    def show(result):
        detail = result.detail
        if result.status == "SKIP":
            detail += " (papernym set-key openalex KEY)"
        prefix = {"PASS": "ok", "FAIL": "warn", "SKIP": "skip"}[result.status]
        ctx.out.line(f"{result.status}  {result.label}  {detail}", prefix)

    results = run_checks(config, http_get, on_result=show)
    tally = {key: sum(r.status == key for r in results) for key in ("PASS", "FAIL", "SKIP")}
    ctx.out.line(f"Summary: {tally['PASS']} passed, {tally['FAIL']} failed, {tally['SKIP']} skipped")
    if tally["FAIL"] and tally["FAIL"] == len(results) - tally["SKIP"]:
        ctx.out.line("everything failed: check your internet connection, VPN, firewall or proxy", "warn")
    elif tally["FAIL"]:
        ctx.out.line("PaperNym still works: it falls back to the sources that passed", "warn")
    return 1 if tally["FAIL"] else 0


def _describe(meta: dict | None) -> str:
    if not meta:
        return "not found"
    years = str(meta.get("year") or "nd")
    if meta.get("year_online") and meta["year_online"] != meta.get("year"):
        years += f" (online {meta['year_online']})"
    author = (meta.get("authors") or ["Unknown"])[0]
    return f"{years} | {author} | {meta['title'][:60]}"


def cmd_compare(ctx: Context, sleep: Callable = time.sleep) -> int:
    config = load_config(ctx.home)
    http_get = ctx.http_get or HttpClient(config).get
    if ctx.args.folder:
        root = Path(ctx.args.folder).expanduser()
        if not root.is_dir():
            raise CliError(f"not a folder: {root}")
        roots = [(root, True)]
    else:
        roots = [(Path(folder["path"]), folder["recursive"]) for folder in config["folders"]]
        if not roots:
            raise CliError("no folders configured; give a FOLDER or run: papernym add-folder PATH")
    files = []
    for root, recursive in roots:
        if root.is_dir():
            files.extend(sorted(path for path in (root.rglob("*") if recursive else root.iterdir())
                                if path.suffix.lower() == ".pdf" and path.is_file()))
        else:
            ctx.out.line(f"{root}: folder is unavailable", "warn")
    ctx.out.line(f"Comparing sources for {len(files)} PDFs (nothing is renamed)")

    def ask(source, function, value):
        if source == "openalex" and not config["openalex_key"]:
            return None, "skipped (no key)"
        if source == "semanticscholar" and not config["s2_key"]:
            sleep(1.2)  # keyless Semantic Scholar is easily rate limited
        try:
            return function(value, config, http_get), ""
        except NetError as exc:
            return None, f"error: {exc}"

    for path in files:
        ctx.out.line()
        ctx.out.line(f"== {path}")
        try:
            info = read_pdf(path)
        except PdfReadError as exc:
            ctx.out.line(f"unreadable PDF: {exc}", "?")
            continue
        dois = list(dict.fromkeys([doi.lower() for doi in info["md_dois"]] + find_dois(info["text"])))[:6]
        arxiv_match = ARXIV_RE.search(info["text"]) or ARXIV_FILE_RE.match(path.stem)
        ctx.out.line(f"   DOIs found:   {', '.join(dois) or 'none'}")
        ctx.out.line(f"   arXiv id:     {arxiv_match.group(1) if arxiv_match else 'none'}")
        ctx.out.line(f"   Title guess:  {info['big_title'] or info['md_title'] or 'none'}")
        for doi in dois[:3]:
            ctx.out.line(f"   DOI {doi}")
            for source, function in DOI_SOURCES:
                meta, note = ask(source, function, doi)
                flag = ""
                if meta and not title_in_text(meta["title"], info["text"]):
                    flag = "   <- title not in this PDF (reference DOI?)"
                ctx.out.line(f"     {source:16} {note or _describe(meta)}{flag}")
        if arxiv_match:
            ctx.out.line(f"   arXiv {arxiv_match.group(1)}")
            for source, function in ARXIV_SOURCES:
                meta, note = ask(source, function, arxiv_match.group(1))
                ctx.out.line(f"     {source:16} {note or _describe(meta)}")
        query = info["big_title"] or info["md_title"]
        if query and config["title_search"]:
            ctx.out.line(f"   Title search")
            for source, function in TITLE_SOURCES:
                hits, note = ask(source, function, query)
                accepted = next((hit for hit in hits or [] if title_hit_ok(hit, query, info)), None)
                if accepted:
                    text = _describe(accepted)
                elif hits:
                    text = f"no confident match (best: {_describe(hits[0])})"
                else:
                    text = note or "not found"
                ctx.out.line(f"     {source:16} {text}")
        elif query:
            ctx.out.line("   Title search: off")
    return 0


# Parser --------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="papernym", description="Rename academic paper PDFs using scholarly metadata.",
        epilog="Settings live in %APPDATA%\\PaperNym (or $PAPERNYM_HOME). "
               "Typical start: papernym add-folder PATH, then papernym scan --dry-run. "
               "To rename the PDFs in the current folder once: papernym scan .")
    parser.add_argument("--version", action="version", version=f"papernym {__version__}")
    parser.add_argument("--no-color", action="store_true", help="plain output without colours")
    shared = argparse.ArgumentParser(add_help=False)
    shared.add_argument("--no-color", action="store_true", default=argparse.SUPPRESS,
                        help="plain output without colours")
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")

    def command(name, func, help_text):
        p = sub.add_parser(name, help=help_text, description=help_text, parents=[shared])
        p.set_defaults(func=func)
        return p

    p = command("add-folder", cmd_add_folder, "Watch a folder")
    p.add_argument("path")
    p.add_argument("--no-subfolders", action="store_true", help="do not include subfolders")
    p = command("remove-folder", cmd_remove_folder, "Stop watching a folder")
    p.add_argument("path")
    p = command("exclude", cmd_exclude, "Add or remove an exclude pattern (folder names end with /)")
    p.add_argument("pattern")
    p.add_argument("--remove", action="store_true", help="remove the pattern instead")
    p = command("set-key", cmd_set_key, "Store an API key")
    p.add_argument("service", choices=sorted(KEY_NAMES))
    p.add_argument("key", help='the key ("" removes it)')
    p = command("set-email", cmd_set_email, "Email sent to Crossref for its polite pool")
    p.add_argument("email", help='your email ("" removes it)')
    command("formats", cmd_formats, "List the fixed presets with an example each")
    p = command("set-format", cmd_set_format, "Choose a preset or a custom template")
    p.add_argument("preset", nargs="?")
    p.add_argument("--custom", metavar="TEMPLATE", help="custom template, e.g. \"{year}_{author}_{title}\"")
    p.add_argument("--word-sep", choices=["_", " ", "space", "-", "none"],
                   help="separator between words of a field (custom only)")
    p = command("set-year", cmd_set_year, "Year mode")
    p.add_argument("mode", choices=["citation", "online"])
    p = command("set-title-search", cmd_set_title_search, "Allow sending titles to search services")
    p.add_argument("state", choices=["on", "off"])
    command("show", cmd_show, "Print settings, folders and the settings-folder path")
    p = command("scan", cmd_scan, "Process every PDF in the watched folders, or in FOLDER, once")
    p.add_argument("folder", nargs="?",
                   help="scan only this folder (e.g. . for the current one); it is not added to the watch list")
    p.add_argument("--dry-run", action="store_true", help="show old -> new without renaming")
    p.add_argument("--no-subfolders", action="store_true", help="with FOLDER: do not include subfolders")
    p = command("watch", cmd_watch, "Scan, then keep watching until Ctrl+C")
    p.add_argument("--poll", action="store_true", help="polling observer (network drives)")
    p = command("reformat", cmd_reformat, "Apply the current naming to earlier renames")
    p.add_argument("--dry-run", action="store_true", help="show old -> new without renaming")
    p.add_argument("--include-manual", action="store_true", help="also rename hand-renamed files")
    p = command("undo", cmd_undo, "Revert the last batch, or the last N renames")
    p.add_argument("--last", type=int, metavar="N")
    p = command("fix", cmd_fix, "Manual fix of a check/unidentified file by DOI")
    p.add_argument("path")
    p.add_argument("--doi", required=True)
    command("status", cmd_status, "Counts by status; list files needing attention")
    command("test-apis", cmd_test_apis, "Check each metadata service with a known paper")
    p = command("compare", cmd_compare, "Show what every source returns for each PDF; renames nothing")
    p.add_argument("folder", nargs="?")
    return parser


def main(argv: list[str] | None = None, *, stdout=None, stderr=None,
         http_get: Callable | None = None) -> int:
    for stream in (stdout or sys.stdout, stderr or sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(errors="replace")
            except (OSError, ValueError):
                pass
    parser = build_parser()
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        parser.print_help(stdout or sys.stdout)
        return 0
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code or 0)
    if getattr(args, "last", None) is not None and args.last < 1:
        parser.print_usage(stderr or sys.stderr)
        print("papernym undo: error: --last must be 1 or more", file=stderr or sys.stderr)
        return 2
    if args.command == "scan" and args.no_subfolders and not args.folder:
        parser.print_usage(stderr or sys.stderr)
        print("papernym scan: error: --no-subfolders needs a FOLDER", file=stderr or sys.stderr)
        return 2
    out = Output(stdout, stderr, color=False if args.no_color else None)
    ctx = Context(args, out, http_get)
    if args.command in ("scan", "watch", "reformat", "undo", "fix"):
        setup_file_log(ctx.home)
    try:
        return args.func(ctx)
    except (CliError, ConfigError, DatabaseError) as exc:
        out.error(str(exc))
        return 1
    except KeyboardInterrupt:
        out.error("interrupted")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
