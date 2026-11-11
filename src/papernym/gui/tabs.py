"""The main window's tabs: Activity, Needs attention, Folders, Naming, Sources, History, General."""

from __future__ import annotations

import copy
import datetime as dt
import os
import threading
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QFileDialog, QFormLayout,
                               QGridLayout, QGroupBox, QHBoxLayout, QHeaderView, QInputDialog,
                               QLabel, QLineEdit, QListWidget, QMessageBox, QProgressBar,
                               QPushButton, QTableWidget, QTableWidgetItem, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget)

from .. import __version__
from ..core.apitest import run_checks
from ..core.config import ConfigError, validate_config
from ..core.logsetup import log_path
from ..core.naming import PRESETS, TOKENS, TemplateError, build_name, validate_template
from ..core import updates
from ..core.keystore import SecretStore
from ..core.sources.http import HttpClient, mask_secrets
from .common import (EVENT_STATUS, FILE_STATUS, REASONS, SAMPLE_PAPERS, LinkLabel, app_icon, open_path,
                     short,
                     show_in_folder)
from .dialogs import DetailsDialog, PreviewDialog
from .table import PagedTable

NO_TITLE = {"author_year", "author_year_journal"}
SEPARATORS = (("Underscore  _", "_"), ("Space", " "), ("Hyphen  -", "-"), ("None (words run together)", ""))


def _table(headers: list[str], name: str) -> QTableWidget:
    table = QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.setSelectionBehavior(QAbstractItemView.SelectRows)
    table.setSelectionMode(QAbstractItemView.SingleSelection)
    table.setEditTriggers(QAbstractItemView.NoEditTriggers)
    table.verticalHeader().setVisible(False)
    table.horizontalHeader().setStretchLastSection(True)
    table.setWordWrap(False)
    table.setTextElideMode(Qt.ElideMiddle)
    table.setAccessibleName(name)
    return table


def _item(text: str, data=None) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    item.setToolTip(text)
    if data is not None:
        item.setData(Qt.UserRole, data)
    return item


def _secret_field() -> QLineEdit:
    """A key field that hides its text unless the user is editing it."""
    field = QLineEdit()
    field.setEchoMode(QLineEdit.PasswordEchoOnEdit)
    return field


def _buddy(text: str, widget) -> QLabel:
    """A form label whose Alt+letter mnemonic focuses ``widget`` (needed when the field is a layout)."""
    label = QLabel(text)
    label.setBuddy(widget)
    return label


def _time(stamp: str | None = None) -> str:
    if not stamp:
        return dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    try:
        return dt.datetime.fromisoformat(stamp).astimezone().strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return stamp


class _Background(QObject):
    """Run a function on a plain thread (network checks that must not hold up the worker)."""

    finished = Signal(object)

    def run(self, function):
        threading.Thread(target=lambda: self.finished.emit(function()), daemon=True).start()


# Activity -------------------------------------------------------------------------

ACTIVITY_LIMIT = 20000  # rows kept in memory; older renames remain in History and the CSV export


class ActivityTab(QWidget):
    SHOWN = ("renamed", "needs_check", "unidentified", "undo", "busy", "skipped")

    def __init__(self, ctl):
        super().__init__()
        self.ctl = ctl
        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        self.scan_button = QPushButton("&Scan now")
        self.scan_button.clicked.connect(ctl.scan_now)
        top.addWidget(self.scan_button)
        self.progress = QProgressBar()
        self.progress.setTextVisible(True)
        self.progress.setFormat("Idle")
        self.progress.setValue(0)
        top.addWidget(self.progress, 1)
        layout.addLayout(top)
        self.table = PagedTable(
            [("Time", lambda r: r["time"]), ("Status", lambda r: r["status"]),
             ("Source", lambda r: r["source"]), ("Old name", lambda r: r["old"]),
             ("New name / details", lambda r: r["new"])],
            name="Activity", search_text=lambda r: f"{r['old']} {r['new']} {r['path']}",
            statuses=[EVENT_STATUS[key] for key in self.SHOWN], status_of=lambda r: r["status"])
        for column, width in enumerate((125, 105, 100, 330)):
            self.table.view.setColumnWidth(column, width)
        self.table.set_actions([("Open file", self._open), ("Show in folder", self._reveal),
                                ("Undo this rename", self._undo), ("Refresh metadata", self._refresh)])
        layout.addWidget(self.table)
        actions = QHBoxLayout()
        self.buttons = []
        for text, slot in (("&Open file", self._open), ("Show in &folder", self._reveal),
                           ("&Undo", self._undo), ("Refresh &metadata", self._refresh)):
            button = QPushButton(text)
            button.clicked.connect(slot)
            actions.addWidget(button)
            self.buttons.append(button)
        self.hint = QLabel("Select a row to use these buttons (or right-click a row).")
        actions.addWidget(self.hint)
        actions.addStretch(1)
        layout.addLayout(actions)
        self.table.selection_changed.connect(self._update_buttons)
        self._update_buttons()
        ctl.worker.event.connect(self.on_event)

    def load_history(self, rows: list[dict]):
        entries = []
        for row in rows:  # newest first
            undone = bool(row["undone"])
            entries.append({"time": _time(row["time"]),
                            "status": "Undone" if undone else ("Check" if row["status"] == "check" else "Renamed"),
                            "source": row["source"], "old": short(row["old_path"]),
                            "new": short(row["new_path"]),
                            "path": row["old_path"] if undone else row["new_path"],
                            "undoable": not undone})
        self.table.set_rows(self.table.all_rows + entries)

    def on_event(self, event: dict):
        kind = event["type"]
        if kind == "scan_started":
            total = event.get("total", 0)
            self.progress.setRange(0, max(total, 1))
            self.progress.setValue(0)
            self.progress.setFormat(f"Scanning 0 / {total}")
            self.scan_button.setEnabled(False)
        elif kind == "scan_progress":
            self.progress.setValue(event["done"])
            self.progress.setFormat(f"Scanning {event['done']} / {event['total']}")
        elif kind == "scan_finished":
            counts = event.get("counts", {})
            self.progress.setValue(self.progress.maximum())
            self.progress.setFormat(f"Last scan: {counts.get('total', 0)} PDFs, {counts.get('ok', 0)} named, "
                                    f"{counts.get('check', 0)} to check, {counts.get('unknown', 0)} not identified")
            self.scan_button.setEnabled(True)
        elif kind in self.SHOWN:
            renamed = kind in ("renamed", "needs_check", "undo")
            if kind == "undo":
                self._mark_undone(event.get("old_path", ""))
            self.table.prepend({"time": _time(), "status": EVENT_STATUS[kind], "source": event.get("source", ""),
                                "old": short(event.get("old_path") or event["path"]),
                                "new": short(event.get("new_path", "")) if renamed else event["message"],
                                "path": event.get("new_path") or event["path"],
                                "undoable": kind in ("renamed", "needs_check")}, ACTIVITY_LIMIT)

    def _mark_undone(self, renamed_path: str):
        for row in self.table.all_rows:
            if row.get("undoable") and row["path"] == renamed_path:
                row["undoable"] = False

    def _update_buttons(self):
        row = self.table.current()
        for button in self.buttons:
            button.setEnabled(row is not None)
        if row is not None:
            self.buttons[2].setEnabled(bool(row.get("undoable")))
        self.hint.setVisible(row is None)

    def _path(self):
        row = self.table.current()
        if row is None:
            self.ctl.status("Select a row first.")
            return None
        return row["path"]

    def _existing(self):
        path = self._path()
        if path and not os.path.exists(path):
            self.ctl.status(f"{short(path)} is no longer there (moved, renamed or deleted).")
            return None
        return path

    def _open(self):
        path = self._existing()
        if path:
            self.ctl.status(f"Opening {short(path)}")
            open_path(path)

    def _reveal(self):
        path = self._existing()
        if path:
            show_in_folder(path)

    def _undo(self):
        row = self.table.current()
        if row is None or not row.get("undoable"):
            self.ctl.status("This row is not a rename that can be undone.")
            return
        path = row["path"]
        self.ctl.worker.call(lambda w: w.engine.undo_path(path), self.ctl.after_undo, self.ctl.error)

    def _refresh(self):
        path = self._existing()
        if path:
            self.ctl.status(f"Refreshing metadata for {short(path)}...")
            self.ctl.worker.call(lambda w: w.engine.refresh(path),
                                 lambda result: self.ctl.status(f"{short(str(result.path))}: "
                                                                f"{result.message or result.status}"),
                                 self.ctl.error)


# Needs attention ------------------------------------------------------------------

class AttentionTab(QWidget):
    def __init__(self, ctl):
        super().__init__()
        self.ctl = ctl
        layout = QVBoxLayout(self)
        self.summary = QLabel("Nothing needs attention.")
        layout.addWidget(self.summary)
        self.table = PagedTable(
            [("File", lambda r: short(r["display_path"])),
             ("Status", lambda r: FILE_STATUS.get(r["status"], r["status"])),
             ("Reason", lambda r: REASONS.get(r["status"], "")),
             ("Folder", lambda r: os.path.dirname(r["display_path"]))],
            name="Files needing attention", search_text=lambda r: r["display_path"],
            statuses=[FILE_STATUS[key] for key in ("check", "unknown", "pending", "unreadable")],
            status_of=lambda r: FILE_STATUS.get(r["status"], r["status"]))
        for column, width in enumerate((320, 150, 360)):
            self.table.view.setColumnWidth(column, width)
        self.table.set_actions([("Open file", self._open), ("Enter DOI...", self._doi),
                                ("Edit details...", self._edit), ("Retry now", self._retry),
                                ("Ignore (never ask again)", self._ignore)])
        self.table.selection_changed.connect(self._update_buttons)
        layout.addWidget(self.table)
        row = QHBoxLayout()
        self.doi_button = QPushButton("Enter &DOI...")
        self.edit_button = QPushButton("&Edit details...")
        self.retry_button = QPushButton("Retr&y now")
        self.ignore_button = QPushButton("&Ignore (never ask again)")
        self.open_button = QPushButton("&Open file")
        for button, slot in ((self.doi_button, self._doi), (self.edit_button, self._edit),
                             (self.retry_button, self._retry), (self.ignore_button, self._ignore),
                             (self.open_button, self._open)):
            button.clicked.connect(slot)
            row.addWidget(button)
        self.hint = QLabel("Select a file to fix it (or right-click it).")
        row.addWidget(self.hint)
        row.addStretch(1)
        layout.addLayout(row)
        ctl.attention_changed.connect(self.show_rows)
        self._update_buttons()

    def show_rows(self, rows: list[dict]):
        self.table.set_rows(rows)
        self.summary.setText(f"{len(rows)} file(s) need attention." if rows else "Nothing needs attention.")
        self._update_buttons()

    def _current(self):
        row = self.table.current()
        return (row["display_path"], row["status"]) if row else None

    def _update_buttons(self):
        current = self._current()
        fixable = bool(current) and current[1] in ("check", "unknown")
        self.doi_button.setEnabled(fixable)
        self.edit_button.setEnabled(fixable)
        for button in (self.retry_button, self.ignore_button, self.open_button):
            button.setEnabled(bool(current))
        self.hint.setVisible(current is None)

    def _done(self, result):
        self.ctl.status(f"{short(str(result.path))}: {result.message or result.status}")
        self.ctl.refresh_attention()

    def _fixable(self):
        current = self._current()
        if not current or current[1] not in ("check", "unknown"):
            self.ctl.status("This works for files marked Check or Not identified.")
            return None
        return current[0]

    def _doi(self):
        path = self._fixable()
        if not path:
            return
        doi, ok = QInputDialog.getText(self, "Enter DOI", f"DOI for {short(path)} (e.g. 10.1016/j.aap.2025.108048):")
        if ok and doi.strip():
            doi = doi.strip()
            for prefix in ("https://doi.org/", "http://doi.org/", "https://dx.doi.org/", "doi:"):
                if doi.lower().startswith(prefix):
                    doi = doi[len(prefix):]
            self.ctl.worker.call(lambda w: w.engine.fix(path, doi=doi), self._done, self.ctl.error)

    def _edit(self):
        path = self._fixable()
        if not path:
            return
        dialog = DetailsDialog(short(path), self)
        if dialog.exec():
            values = dialog.values()
            self.ctl.worker.call(lambda w: w.engine.fix(path, **values), self._done, self.ctl.error)

    def _retry(self):
        current = self._current()
        if current:
            path = current[0]
            self.ctl.status(f"Retrying {short(path)}...")
            self.ctl.worker.call(lambda w: w.retry(path), self._done, self.ctl.error)

    def _ignore(self):
        current = self._current()
        if current:
            path = current[0]
            self.ctl.worker.call(lambda w: w.engine.keep_name(path), self._done, self.ctl.error)

    def _open(self):
        current = self._current()
        if current and os.path.exists(current[0]):
            open_path(current[0])
        elif current:
            self.ctl.status(f"{short(current[0])} is no longer there.")


# Folders --------------------------------------------------------------------------

class FoldersTab(QWidget):
    def __init__(self, ctl):
        super().__init__()
        self.ctl = ctl
        layout = QVBoxLayout(self)
        box = QGroupBox("Watched folders")
        inner = QVBoxLayout(box)
        self.table = _table(["Folder", "Subfolders", "State"], "Watched folders")
        self.table.setColumnWidth(0, 520)
        self.table.itemChanged.connect(self._toggled)
        self.table.cellDoubleClicked.connect(self._open_row)
        self.table.setToolTip("Double-click a folder to open it")
        inner.addWidget(self.table)
        row = QHBoxLayout()
        for text, slot in (("&Add folder...", self._add), ("&Remove", self._remove),
                           ("Show in &Explorer", self._reveal), ("Re&check", self.refresh_states)):
            button = QPushButton(text)
            button.clicked.connect(slot)
            row.addWidget(button)
        row.addStretch(1)
        inner.addLayout(row)
        layout.addWidget(box, 2)
        box = QGroupBox("Exclude patterns (file names like *draft*, or folder names ending with /)")
        inner = QVBoxLayout(box)
        self.excludes = QListWidget()
        self.excludes.setAccessibleName("Exclude patterns")
        inner.addWidget(self.excludes)
        row = QHBoxLayout()
        self.pattern = QLineEdit()
        self.pattern.setPlaceholderText("New pattern, e.g. *_review* or Drafts/")
        self.pattern.returnPressed.connect(self._add_pattern)
        add = QPushButton("Add &pattern")
        add.clicked.connect(self._add_pattern)
        remove = QPushButton("Remove pa&ttern")
        remove.clicked.connect(self._remove_pattern)
        row.addWidget(self.pattern, 1)
        row.addWidget(add)
        row.addWidget(remove)
        inner.addLayout(row)
        layout.addWidget(box, 1)
        self.states: dict[str, bool] = {}
        ctl.config_changed.connect(self.show_config)
        ctl.worker.event.connect(self._on_event)

    def show_config(self, config: dict):
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        for folder in config["folders"]:
            index = self.table.rowCount()
            self.table.insertRow(index)
            self.table.setItem(index, 0, _item(folder["path"], folder["path"]))
            toggle = QTableWidgetItem("include")
            toggle.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            toggle.setCheckState(Qt.Checked if folder["recursive"] else Qt.Unchecked)
            self.table.setItem(index, 1, toggle)
            state = self.states.get(folder["path"])
            self.table.setItem(index, 2, _item("Checking..." if state is None else
                                               ("Reachable" if state else "UNREACHABLE")))
        self.table.blockSignals(False)
        self.excludes.clear()
        self.excludes.addItems(config["exclude"])

    def refresh_states(self):
        def done(states):
            self.states = states
            self.show_config(self.ctl.config)
            self.ctl.folder_states_changed(states)

        self.ctl.worker.call(lambda w: w.folder_states(), done)

    def _on_event(self, event):
        if event["type"] in ("folder_attached", "folder_unavailable", "settings_reloaded"):
            self.refresh_states()

    def _toggled(self, item: QTableWidgetItem):
        if item.column() != 1:
            return
        path = self.table.item(item.row(), 0).data(Qt.UserRole)
        recursive = item.checkState() == Qt.Checked
        config = copy.deepcopy(self.ctl.config)
        config["folders"] = [folder for folder in config["folders"] if folder["path"] != path]
        self.ctl.worker.call(lambda w: w.validate_new_folder(config, path, recursive),
                             lambda info: self.ctl.save_settings(info["config"]),
                             lambda message: (self.ctl.error(message), self.show_config(self.ctl.config)))

    def _add(self):
        path = QFileDialog.getExistingDirectory(self, "Choose a folder of papers")
        if path:
            self.ctl.add_folder_flow(path, recursive=True)

    def _selected_path(self):
        rows = self.table.selectionModel().selectedRows()
        return self.table.item(rows[0].row(), 0).data(Qt.UserRole) if rows else None

    def _remove(self):
        path = self._selected_path()
        if path and QMessageBox.question(self, "Remove folder",
                                         f"Stop watching {path}?\nFiles there keep their names.") == QMessageBox.Yes:
            config = copy.deepcopy(self.ctl.config)
            config["folders"] = [folder for folder in config["folders"] if folder["path"] != path]
            self.ctl.save_settings(config)

    def _open_row(self, row: int, column: int):
        if column == 1:  # the Subfolders checkbox: a double-click there just toggles it
            return
        item = self.table.item(row, 0)
        if item is None:
            return
        path = item.text()
        if os.path.isdir(path):
            open_path(path)
        else:
            self.ctl.status(f"{path} is not reachable right now.")

    def _reveal(self):
        path = self._selected_path()
        if path:
            open_path(path)

    def _add_pattern(self):
        pattern = self.pattern.text().strip()
        if not pattern or pattern in self.ctl.config["exclude"]:
            return
        config = copy.deepcopy(self.ctl.config)
        config["exclude"].append(pattern)
        self.ctl.save_settings(config)
        self.pattern.clear()

    def _remove_pattern(self):
        item = self.excludes.currentItem()
        if item:
            config = copy.deepcopy(self.ctl.config)
            config["exclude"].remove(item.text())
            self.ctl.save_settings(config)


# Naming ---------------------------------------------------------------------------

class NamingTab(QWidget):
    def __init__(self, ctl):
        super().__init__()
        self.ctl = ctl
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.preset = QComboBox()
        for name in PRESETS:
            label = name + ("  (default)" if name == "year_author_title" else "")
            label += "  - no title, names may collide" if name in NO_TITLE else ""
            self.preset.addItem(label, name)
        self.preset.addItem("Custom", None)
        form.addRow("Name &format", self.preset)
        self.template = QLineEdit()
        self.template.setAccessibleName("Template")
        form.addRow("&Template", self.template)
        tokens = QHBoxLayout()
        self.token_buttons = []
        for token in ("year", "author", "authors", "title", "shorttitle", "journal"):
            button = QPushButton("{" + token + "}")
            button.setToolTip(f"Insert the {token} token at the cursor")
            button.clicked.connect(lambda _=False, t=token: self._insert(t))
            tokens.addWidget(button)
            self.token_buttons.append(button)
        tokens.addStretch(1)
        self.tokens_row = QWidget()
        self.tokens_row.setLayout(tokens)
        form.addRow("", self.tokens_row)
        self.separator = QComboBox()
        for label, value in SEPARATORS:
            self.separator.addItem(label, value)
        form.addRow("&Word separator", self.separator)
        self.year = QComboBox()
        self.year.addItem("Citation year (journal volume)", "citation")
        self.year.addItem("First-online year", "online")
        form.addRow("&Year", self.year)
        layout.addLayout(form)
        self.message = QLabel()
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        layout.addWidget(QLabel("Preview:"))
        self.preview = QLabel()
        self.preview.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.preview.setAccessibleName("Name preview")
        layout.addWidget(self.preview)
        layout.addStretch(1)
        row = QHBoxLayout()
        self.save_button = QPushButton("&Save naming")
        self.save_button.clicked.connect(self._save)
        self.revert_button = QPushButton("Re&vert")
        self.revert_button.clicked.connect(lambda: self.show_config(self.ctl.config))
        row.addStretch(1)
        row.addWidget(self.revert_button)
        row.addWidget(self.save_button)
        layout.addLayout(row)
        layout.addWidget(QLabel("Saving never renames existing files by itself; you are asked first."))
        for signal in (self.preset.currentIndexChanged, self.template.textChanged,
                       self.separator.currentIndexChanged,
                       self.year.currentIndexChanged):
            signal.connect(self._changed)
        ctl.config_changed.connect(self.show_config)

    def show_config(self, config: dict):
        widgets = (self.preset, self.template, self.separator, self.year)
        for widget in widgets:
            widget.blockSignals(True)
        fmt = config["format"]
        preset = fmt if fmt in PRESETS else next(
            (name for name, (template, sep) in PRESETS.items()
             if template == fmt and sep == config["word_sep"] and name != "citekey"), None)
        self.preset.setCurrentIndex(self.preset.findData(preset))
        self.template.setText(PRESETS[preset][0] if preset else fmt)
        self.separator.setCurrentIndex(max(0, self.separator.findData(
            PRESETS[preset][1] if preset else config["word_sep"])))
        self.year.setCurrentIndex(self.year.findData(config["year"]))
        for widget in widgets:
            widget.blockSignals(False)
        self._changed()

    def _insert(self, token: str):
        self.template.insert("{" + token + "}")
        self.template.setFocus()

    def _changed(self, *_):
        preset = self.preset.currentData()
        custom = preset is None
        if not custom:
            self.template.blockSignals(True)
            self.template.setText(PRESETS[preset][0])
            self.template.blockSignals(False)
            self.separator.blockSignals(True)
            self.separator.setCurrentIndex(self.separator.findData(PRESETS[preset][1]))
            self.separator.blockSignals(False)
        self.template.setReadOnly(not custom)
        self.tokens_row.setEnabled(custom)
        self.separator.setEnabled(custom)
        try:
            warnings = [] if not custom else validate_template(self.template.text())
            lines = [build_name(paper, preset or self.template.text(), ".",
                                word_sep=self.separator.currentData(), year_mode=self.year.currentData())
                     for paper in SAMPLE_PAPERS]
        except (TemplateError, ValueError) as exc:
            self.message.setText(f"Error: {exc}. This template cannot be saved.")
            self.preview.setText("")
            self.save_button.setEnabled(False)
            return
        if preset in NO_TITLE:
            warnings.append("This format has no title; names may collide and get _b, _c endings.")
        self.message.setText("Warning: " + " ".join(warnings) if warnings else "")
        self.preview.setText("\n".join(lines))
        self.save_button.setEnabled(self._pending() != self._current())

    def _current(self) -> tuple:
        config = self.ctl.config
        fmt = config["format"]
        same = next((name for name, (template, sep) in PRESETS.items()
                     if template == fmt and sep == config["word_sep"] and name != "citekey"), None)
        fmt = same or fmt
        sep = PRESETS[fmt][1] if fmt in PRESETS else config["word_sep"]
        return (fmt, sep, config["year"])

    def _pending(self) -> tuple:
        preset = self.preset.currentData()
        fmt = preset or self.template.text()
        sep = PRESETS[preset][1] if preset else self.separator.currentData()
        return (fmt, sep, self.year.currentData())

    def _save(self):
        config = copy.deepcopy(self.ctl.config)
        config["format"], config["word_sep"], config["year"] = self._pending()
        try:
            validate_config(config)
        except ConfigError as exc:
            self.message.setText(f"Error: {exc}")
            return
        self.ctl.save_settings(config, lambda _: self.ctl.offer_reformat())


# Sources --------------------------------------------------------------------------

class SourcesTab(QWidget):
    def __init__(self, ctl):
        super().__init__()
        self.ctl = ctl
        self.background = _Background()
        self.background.finished.connect(self._show_results)
        layout = QVBoxLayout(self)
        self.banner = QLabel()
        self.banner.setWordWrap(True)
        self.banner.setObjectName("banner")
        self.banner.hide()
        layout.addWidget(self.banner)
        form = QFormLayout()
        self.openalex = _secret_field()
        self.openalex.setPlaceholderText("optional")
        row = QHBoxLayout()
        row.addWidget(self.openalex, 1)
        test = QPushButton("&Test")
        test.clicked.connect(lambda: self._test({"openalex"}))
        row.addWidget(test)
        row.addWidget(LinkLabel("Get a free key", "https://openalex.org/settings/api"))
        form.addRow(_buddy("&OpenAlex key", self.openalex), row)
        self.s2 = _secret_field()
        self.s2.setPlaceholderText("optional")
        row = QHBoxLayout()
        row.addWidget(self.s2, 1)
        test = QPushButton("T&est")
        test.clicked.connect(lambda: self._test({"semanticscholar"}))
        row.addWidget(test)
        form.addRow(_buddy("Semantic &Scholar key", self.s2), row)
        self.email = QLineEdit()
        self.email.setPlaceholderText("you@example.org (sent to Crossref for faster, polite access)")
        form.addRow("&Email", self.email)
        self.title_search = QCheckBox("Search by &title when a PDF has no DOI or arXiv id")
        form.addRow("", self.title_search)
        form.addRow("", QLabel("Privacy: when on, a paper's title may be sent to Crossref, OpenAlex and "
                               "Semantic Scholar. When off, only DOIs and arXiv ids are looked up."))
        store = SecretStore(ctl.home)
        self.key_store = QLabel(f"Keys are kept in {store.describe()}, not in the settings file."
                                if store.available() else
                                "No system credential store was found, so keys are kept in the settings "
                                "file, readable only by you.")
        self.key_store.setWordWrap(True)
        form.addRow("", self.key_store)
        layout.addLayout(form)
        row = QHBoxLayout()
        save = QPushButton("Sa&ve sources")
        save.clicked.connect(self._save)
        self.test_all = QPushButton("Test &all sources")
        self.test_all.clicked.connect(lambda: self._test(None))
        row.addWidget(self.test_all)
        row.addStretch(1)
        row.addWidget(save)
        layout.addLayout(row)
        self.results = _table(["Result", "Check", "Details"], "Source test results")
        self.results.setColumnWidth(0, 70)
        self.results.setColumnWidth(1, 240)
        layout.addWidget(self.results)
        ctl.config_changed.connect(self.show_config)

    def show_config(self, config: dict):
        self.openalex.setText(config["openalex_key"])
        self.s2.setText(config["s2_key"])
        self.email.setText(config["email"])
        self.title_search.setChecked(config["title_search"])

    def _edited(self) -> dict:
        config = copy.deepcopy(self.ctl.config)
        config.update({"openalex_key": self.openalex.text().strip(), "s2_key": self.s2.text().strip(),
                       "email": self.email.text().strip(), "title_search": self.title_search.isChecked()})
        return config

    def _save(self):
        self.ctl.save_settings(self._edited(), lambda _: self.ctl.status("Sources saved."))

    def show_rejected(self, message: str | None):
        self.banner.setText(f"Key problem: {message}. Other sources keep working." if message else "")
        self.banner.setVisible(bool(message))

    def _test(self, services):
        config = self._edited()
        http_get = self.ctl.http_get or HttpClient(config).get
        self.test_all.setEnabled(False)
        self.results.setRowCount(0)
        self.results.insertRow(0)
        self.results.setItem(0, 0, _item("..."))
        self.results.setItem(0, 2, _item("Testing; this takes a few seconds..."))
        self.background.run(lambda: run_checks(config, http_get, services))

    def _show_results(self, results):
        self.test_all.setEnabled(True)
        self.results.setRowCount(0)
        for result in results:
            index = self.results.rowCount()
            self.results.insertRow(index)
            for column, text in enumerate((result.status, " ".join(result.label.split()), result.detail)):
                self.results.setItem(index, column, _item(text))
        if any(result.status == "FAIL" and "key rejected" in result.detail for result in results):
            self.show_rejected("a key was rejected by its service")


# History --------------------------------------------------------------------------

class HistoryTab(QWidget):
    def __init__(self, ctl):
        super().__init__()
        self.ctl = ctl
        layout = QVBoxLayout(self)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["When / old name", "New name", "Source", "Status"])
        self.tree.setColumnWidth(0, 380)
        self.tree.setColumnWidth(1, 460)
        self.tree.setAccessibleName("Rename history grouped by batch")
        layout.addWidget(self.tree)
        row = QHBoxLayout()
        for text, slot in (("&Undo selected (row or whole batch)", self._undo),
                           ("&Export CSV...", self._export), ("&Reload", self.reload)):
            button = QPushButton(text)
            button.clicked.connect(slot)
            row.addWidget(button)
        row.addStretch(1)
        layout.addLayout(row)
        ctl.history_changed.connect(self.reload)

    def reload(self):
        self.ctl.worker.call(lambda w: w.recent_history(5000), self.show_rows)

    def show_rows(self, rows: list[dict]):
        self.tree.clear()
        batches: dict[str, QTreeWidgetItem] = {}
        live: dict[str, list[int]] = {}
        for row in rows:  # newest first
            parent = batches.get(row["batch"])
            if parent is None:
                parent = QTreeWidgetItem([f"{_time(row['time'])}  batch", "", "", ""])
                batches[row["batch"]] = parent
                live[row["batch"]] = []
                self.tree.addTopLevelItem(parent)
            status = "undone" if row["undone"] else row["status"]
            child = QTreeWidgetItem([short(row["old_path"]), short(row["new_path"]), row["source"], status])
            child.setToolTip(0, row["old_path"])
            child.setToolTip(1, row["new_path"])
            child.setData(0, Qt.UserRole, [row["id"]] if not row["undone"] else [])
            parent.addChild(child)
            if not row["undone"]:
                live[row["batch"]].append(row["id"])
        for batch, parent in batches.items():
            ids = live[batch]
            parent.setData(0, Qt.UserRole, ids)
            parent.setText(0, f"{parent.text(0)}: {parent.childCount()} rename(s)"
                              + ("" if ids else ", all undone"))

    def _undo(self):
        item = self.tree.currentItem()
        ids = item.data(0, Qt.UserRole) if item else []
        if not ids:
            self.ctl.status("Select a rename or a batch that has not been undone.")
            return
        self.ctl.worker.call(lambda w: w.engine.undo_ids(ids), self.ctl.after_undo, self.ctl.error)

    def _export(self):
        target, _ = QFileDialog.getSaveFileName(self, "Export history", "papernym-history.csv", "CSV (*.csv)")
        if target:
            self.ctl.worker.call(lambda w: w.export_history(target),
                                 lambda count: self.ctl.status(f"Exported {count} rows to {target}"),
                                 self.ctl.error)


# General --------------------------------------------------------------------------

class GeneralTab(QWidget):
    def __init__(self, ctl):
        super().__init__()
        self.ctl = ctl
        layout = QVBoxLayout(self)
        self.login = QCheckBox("Start PaperNym when I &log in (minimised to the tray)")
        self.notify = QCheckBox("Show a &notification when papers are renamed")
        self.paused = QCheckBox("&Pause watching")
        for box in (self.login, self.notify, self.paused):
            box.toggled.connect(self._save)
            layout.addWidget(box)
        if ctl.sandbox:
            self.login.setEnabled(False)
            self.login.setToolTip("Disabled in sandbox mode")
        theme_row = QHBoxLayout()
        self.theme = QComboBox()
        for text, value in (("System (follow Windows)", "system"), ("Light", "light"), ("Dark", "dark")):
            self.theme.addItem(text, value)
        self.theme.currentIndexChanged.connect(self._save)
        theme_row.addWidget(_buddy("&Theme:", self.theme))
        theme_row.addWidget(self.theme)
        theme_row.addStretch(1)
        layout.addLayout(theme_row)
        grid = QGridLayout()
        buttons = (("Save &diagnostics...", self._save_diagnostics),)
        if ctl.debug:  # the settings folder holds the database; shown only for debugging
            buttons = (("Open &settings folder", lambda: open_path(ctl.home)),
                       ("Open &log", self._open_log)) + buttons
        for column, (text, slot) in enumerate(buttons):
            button = QPushButton(text)
            button.clicked.connect(slot)
            grid.addWidget(button, 0, column)
        grid.setColumnStretch(len(buttons), 1)
        layout.addLayout(grid)
        if ctl.debug:
            layout.addWidget(QLabel(f"Settings folder: {ctl.home}"))
        layout.addStretch(1)
        ctl.config_changed.connect(self.show_config)

    def show_config(self, config: dict):
        for box, key in ((self.login, "start_at_login"), (self.notify, "notify_on_rename"),
                         (self.paused, "paused")):
            box.blockSignals(True)
            box.setChecked(config[key])
            box.blockSignals(False)
        self.theme.blockSignals(True)
        self.theme.setCurrentIndex(max(0, self.theme.findData(config.get("theme", "system"))))
        self.theme.blockSignals(False)

    def _save(self):
        config = copy.deepcopy(self.ctl.config)
        login_changed = config["start_at_login"] != self.login.isChecked()
        config.update({"start_at_login": self.login.isChecked(),
                       "notify_on_rename": self.notify.isChecked(), "paused": self.paused.isChecked(),
                       "theme": self.theme.currentData()})
        if login_changed:
            self.ctl.set_start_at_login(self.login.isChecked())
        self.ctl.save_settings(config)

    def _save_diagnostics(self):
        """A copy of the log with keys and email addresses masked, saved where the user chooses."""
        source = log_path(self.ctl.home)
        start = str(Path.home() / "Documents" / "papernym-diagnostics.txt")
        target, _ = QFileDialog.getSaveFileName(self, "Save diagnostics", start, "Text files (*.txt)")
        if not target:
            return
        text = source.read_text(encoding="utf-8", errors="replace") if source.exists() else ""
        Path(target).write_text(mask_diagnostics(text, self.ctl.home), encoding="utf-8")
        self.ctl.status(f"Diagnostics saved to {target}")

    def _open_log(self):
        path = log_path(self.ctl.home)
        open_path(path if path.exists() else path.parent)


def mask_diagnostics(text: str, home: Path) -> str:
    """Hide API keys, email addresses and the settings-folder path in a log copy."""
    import re

    text = mask_secrets(text)
    text = re.sub(r"[\w.+-]+@[\w-]+\.[\w.-]+", "<email>", text)
    for form in {str(home), str(home).replace("\\", "/")}:
        text = text.replace(form, "<settings>")
    return text


# About ----------------------------------------------------------------------------

class AboutTab(QWidget):
    def __init__(self, ctl):
        super().__init__()
        self.ctl = ctl
        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(app_icon().pixmap(88, 88))
        logo.setAccessibleName("PaperNym logo")
        top.addWidget(logo, 0, Qt.AlignTop)
        title = QVBoxLayout()
        name = QLabel(f"<span style='font-size:20pt; font-weight:600'>PaperNym</span>"
                      f"&nbsp;&nbsp;version {__version__}")
        title.addWidget(name)
        title.addWidget(QLabel("Names your research papers automatically: it watches your folders, "
                               "looks each PDF up in scholarly databases, and renames it the way you choose."))
        top.addLayout(title, 1)
        layout.addLayout(top)
        links = QFormLayout()
        for label, text, url in (("Developer", "Xatta-Trone on GitHub", updates.DEVELOPER_URL),
                                 ("Project", "github.com/" + updates.REPO, updates.PROJECT_URL),
                                 ("Report a problem", "Open an issue", updates.ISSUES_URL),
                                 ("Licence", "MIT License", updates.LICENSE_URL)):
            links.addRow(label, LinkLabel(text, url))
        layout.addLayout(links)
        credits = QLabel("Paper details come from Crossref, OpenAlex, Semantic Scholar, arXiv and doi.org. "
                         "PaperNym is not affiliated with these services.")
        credits.setWordWrap(True)
        layout.addWidget(credits)
        layout.addSpacing(12)
        layout.addWidget(QLabel("<b>Updates</b>"))
        self.update_status = QLabel("Not checked yet.")
        self.update_status.setWordWrap(True)
        self.update_status.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.update_status)
        row = QHBoxLayout()
        self.check_button = QPushButton("Check for &updates now")
        self.check_button.clicked.connect(lambda: ctl.check_updates(manual=True))
        row.addWidget(self.check_button)
        self.download_button = QPushButton("&Open the release page")
        self.download_button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(self._url)))
        self.download_button.hide()
        row.addWidget(self.download_button)
        row.addStretch(1)
        layout.addLayout(row)
        self.auto = QCheckBox("Check for updates &automatically (once a day; only the version number "
                              "is fetched from GitHub)")
        self.auto.toggled.connect(self._save)
        layout.addWidget(self.auto)
        layout.addStretch(1)
        self._url = updates.RELEASES_URL
        ctl.config_changed.connect(self.show_config)

    def show_config(self, config: dict):
        self.auto.blockSignals(True)
        self.auto.setChecked(config.get("update_check", True))
        self.auto.blockSignals(False)

    def _save(self):
        config = copy.deepcopy(self.ctl.config)
        config["update_check"] = self.auto.isChecked()
        self.ctl.save_settings(config)

    def show_checking(self):
        self.check_button.setEnabled(False)
        self.update_status.setText("Checking GitHub for a newer version...")

    def show_update(self, info, error: str):
        self.check_button.setEnabled(True)
        stamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
        if error:
            self.update_status.setText(f"Could not check for updates ({error}). Checked {stamp}.")
            return
        self._url = info.url
        self.download_button.setVisible(info.newer)
        if info.newer:
            self.update_status.setText(f"Version {info.latest} is available (you have {info.current}). "
                                       f"{updates.how_to_update()}")
        elif info.latest:
            self.update_status.setText(f"PaperNym {info.current} is up to date. Checked {stamp}.")
        else:
            self.update_status.setText(f"No release has been published yet. Checked {stamp}.")

