"""A searchable, paged table for long lists (thousands of files)."""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QHBoxLayout, QHeaderView, QLabel,
                               QLineEdit, QMenu, QPushButton, QTableView, QVBoxLayout, QWidget)

PAGE_SIZE = 200


class _Model(QAbstractTableModel):
    def __init__(self, columns: list[tuple[str, Callable[[dict], str]]]):
        super().__init__()
        self.columns = columns
        self.rows: list[dict] = []

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.columns)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        if role in (Qt.DisplayRole, Qt.ToolTipRole):
            return self.columns[index.column()][1](self.rows[index.row()])
        return None

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return self.columns[section][0]
        return None

    def set_rows(self, rows: list[dict]):
        self.beginResetModel()
        self.rows = rows
        self.endResetModel()


class PagedTable(QWidget):
    """Search box, optional status filter, a table view showing one page, and a pager.

    ``rows`` are plain dicts. ``search_text(row)`` gives the text the search box matches;
    ``status_of(row)`` gives the value the status filter compares.
    """

    selection_changed = Signal()
    activated = Signal(dict)

    def __init__(self, columns, *, name: str, search_text: Callable[[dict], str],
                 statuses: list[str] | None = None, status_of: Callable[[dict], str] | None = None,
                 page_size: int = PAGE_SIZE):
        super().__init__()
        self.search_text = search_text
        self.status_of = status_of
        self.page_size = page_size
        self.page = 0
        self.all_rows: list[dict] = []
        self.matches: list[dict] = []
        self.actions: list[tuple[str, Callable]] = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        top = QHBoxLayout()
        label = QLabel("Sea&rch:")
        self.search = QLineEdit()
        self.search.setPlaceholderText("Type part of a file name, title or folder")
        self.search.setClearButtonEnabled(True)
        self.search.setAccessibleName(f"Search {name}")
        label.setBuddy(self.search)
        self.search.textChanged.connect(lambda _: self._refilter(reset_page=True))
        top.addWidget(label)
        top.addWidget(self.search, 1)
        self.status = None
        if statuses:
            label = QLabel("Fi&lter:")
            self.status = QComboBox()
            self.status.addItem("All", None)
            for value in statuses:
                self.status.addItem(value, value)
            label.setBuddy(self.status)
            self.status.currentIndexChanged.connect(lambda _: self._refilter(reset_page=True))
            top.addWidget(label)
            top.addWidget(self.status)
        layout.addLayout(top)
        self.model = _Model(columns)
        self.view = QTableView()
        self.view.setModel(self.model)
        self.view.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.view.setSelectionMode(QAbstractItemView.SingleSelection)
        self.view.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.view.setWordWrap(False)
        self.view.setTextElideMode(Qt.ElideMiddle)
        self.view.verticalHeader().setVisible(False)
        self.view.horizontalHeader().setStretchLastSection(True)
        self.view.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.view.setAccessibleName(name)
        self.view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.view.customContextMenuRequested.connect(self._menu)
        self.view.doubleClicked.connect(lambda _: self._activate())
        self.view.activated.connect(lambda _: self._activate())  # Enter key
        self.view.selectionModel().selectionChanged.connect(lambda *_: self.selection_changed.emit())
        layout.addWidget(self.view)
        pager = QHBoxLayout()
        self.first_button = QPushButton("<< First")
        self.prev_button = QPushButton("< &Previous")
        self.next_button = QPushButton("Ne&xt >")
        self.last_button = QPushButton("Last >>")
        self.position = QLabel()
        self.position.setAccessibleName("Page position")
        for button, step in ((self.first_button, "first"), (self.prev_button, -1),
                             (self.next_button, 1), (self.last_button, "last")):
            button.clicked.connect(lambda _=False, s=step: self._go(s))
        pager.addWidget(self.position, 1)
        for button in (self.first_button, self.prev_button, self.next_button, self.last_button):
            pager.addWidget(button)
        layout.addLayout(pager)
        self._refilter(reset_page=True)

    # Data ----------------------------------------------------------------------------
    def set_rows(self, rows: list[dict]):
        """Replace all rows (newest first), keeping the current page if it still exists."""
        self.all_rows = list(rows)
        self._refilter(reset_page=False)

    def prepend(self, row: dict, limit: int | None = None):
        self.all_rows.insert(0, row)
        if limit is not None:
            del self.all_rows[limit:]
        self._refilter(reset_page=False)

    def _refilter(self, reset_page: bool):
        selected = self.current()
        needle = self.search.text().strip().lower()
        wanted = self.status.currentData() if self.status else None
        self.matches = [row for row in self.all_rows
                        if (not needle or needle in self.search_text(row).lower())
                        and (wanted is None or self.status_of(row) == wanted)]
        if reset_page:
            self.page = 0
        self.page = min(self.page, max(0, (len(self.matches) - 1) // self.page_size))
        self._show_page(keep=selected)

    def _show_page(self, keep: dict | None = None):
        start = self.page * self.page_size
        rows = self.matches[start:start + self.page_size]
        self.model.set_rows(rows)
        if keep is not None:
            for index, row in enumerate(rows):
                if row is keep:
                    self.view.selectRow(index)
                    break
        total, pages = len(self.matches), max(1, -(-len(self.matches) // self.page_size))
        if total:
            shown = f"{start + 1}-{start + len(rows)} of {total}"
        else:
            shown = "No matches" if self.all_rows else "Nothing yet"
        if len(self.matches) != len(self.all_rows):
            shown += f" (filtered from {len(self.all_rows)})"
        self.position.setText(f"{shown}   Page {self.page + 1} of {pages}")
        self.first_button.setEnabled(self.page > 0)
        self.prev_button.setEnabled(self.page > 0)
        self.next_button.setEnabled(self.page < pages - 1)
        self.last_button.setEnabled(self.page < pages - 1)
        self.selection_changed.emit()

    def _go(self, step):
        pages = max(1, -(-len(self.matches) // self.page_size))
        if step == "first":
            self.page = 0
        elif step == "last":
            self.page = pages - 1
        else:
            self.page = min(max(0, self.page + step), pages - 1)
        self._show_page()

    # Selection and actions -----------------------------------------------------------
    def current(self) -> dict | None:
        rows = self.view.selectionModel().selectedRows() if self.view.selectionModel() else []
        return self.model.rows[rows[0].row()] if rows and rows[0].row() < len(self.model.rows) else None

    def set_actions(self, actions: list[tuple[str, Callable]]):
        """Actions for the right-click menu; the first is also run by double-click / Enter."""
        self.actions = actions

    def _activate(self):
        row = self.current()
        if row is not None:
            self.activated.emit(row)
            if self.actions:
                self.actions[0][1]()

    def _menu(self, point):
        index = self.view.indexAt(point)
        if not index.isValid() or not self.actions:
            return
        self.view.selectRow(index.row())
        menu = QMenu(self)
        for text, slot in self.actions:
            menu.addAction(text, slot)
        menu.exec(self.view.viewport().mapToGlobal(point))
