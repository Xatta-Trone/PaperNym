"""Dialogs: rename preview with checkboxes, edit details, and the first-run welcome."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
                               QFormLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QPushButton, QSpinBox, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWizard, QWizardPage)

from ..core.naming import PRESETS, build_name
from .common import SAMPLE_PAPERS, LinkLabel, short


class PreviewDialog(QDialog):
    """List of old -> new. Ticked items are renamed; with ``checkable=False`` all are."""

    include_manual_changed = Signal(bool)

    def __init__(self, title: str, intro: str, items: list[dict], *, checkable: bool = True,
                 accept_text: str = "Rename", reject_text: str = "Cancel",
                 include_manual: bool | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(900, 480)
        layout = QVBoxLayout(self)
        self.intro = QLabel(intro)
        self.intro.setWordWrap(True)
        layout.addWidget(self.intro)
        self.checkable = checkable
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Current name", "New name"])
        self.tree.setRootIsDecorated(False)
        self.tree.setAccessibleName("Files that would be renamed")
        layout.addWidget(self.tree)
        self.manual_box = None
        if include_manual is not None:
            self.manual_box = QCheckBox("Also rename files I renamed by &hand")
            self.manual_box.setChecked(include_manual)
            self.manual_box.toggled.connect(self.include_manual_changed)
            layout.addWidget(QLabel("Files you renamed by hand are left alone unless you tick this."))
            layout.addWidget(self.manual_box)
        row = QHBoxLayout()
        if checkable:
            for text, state in (("Tick &all", True), ("Untick a&ll", False)):
                button = QPushButton(text)
                button.clicked.connect(lambda _=False, s=state: self.set_all(s))
                row.addWidget(button)
        row.addStretch(1)
        self.count = QLabel()
        row.addWidget(self.count)
        layout.addLayout(row)
        buttons = QDialogButtonBox()
        self.accept_button = buttons.addButton(accept_text, QDialogButtonBox.AcceptRole)
        buttons.addButton(reject_text, QDialogButtonBox.RejectRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.tree.itemChanged.connect(lambda *_: self._update_count())
        self.set_items(items)

    def set_items(self, items: list[dict]):
        self.tree.blockSignals(True)
        self.tree.clear()
        for item in items:
            node = QTreeWidgetItem([short(item["old_path"]), short(item["new_path"])])
            node.setData(0, Qt.UserRole, item["old_path"])
            node.setToolTip(0, item["old_path"])
            node.setToolTip(1, item["new_path"])
            if self.checkable:
                node.setCheckState(0, Qt.Checked)
            self.tree.addTopLevelItem(node)
        self.tree.blockSignals(False)
        self.tree.resizeColumnToContents(0)
        self.tree.setColumnWidth(0, min(self.tree.columnWidth(0) + 24, 340))
        self._update_count()

    def set_all(self, state: bool):
        for index in range(self.tree.topLevelItemCount()):
            self.tree.topLevelItem(index).setCheckState(0, Qt.Checked if state else Qt.Unchecked)

    def _paths(self, checked: bool) -> list[str]:
        result = []
        for index in range(self.tree.topLevelItemCount()):
            node = self.tree.topLevelItem(index)
            ticked = not self.checkable or node.checkState(0) == Qt.Checked
            if ticked == checked:
                result.append(node.data(0, Qt.UserRole))
        return result

    def selected(self) -> list[str]:
        return self._paths(True)

    def unselected(self) -> list[str]:
        return self._paths(False)

    def _update_count(self):
        total = self.tree.topLevelItemCount()
        chosen = len(self.selected())
        self.count.setText(f"{chosen} of {total} selected" if self.checkable else f"{total} files")


class DetailsDialog(QDialog):
    """Edit title, first author and year for a file that could not be identified."""

    def __init__(self, name: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit details")
        form = QFormLayout(self)
        form.addRow(QLabel(f"Details for {name}. They are saved as source 'manual'."))
        self.title = QLineEdit()
        self.author = QLineEdit()
        self.author.setPlaceholderText("First author, e.g. Smith or Ann Smith")
        self.year = QSpinBox()
        self.year.setRange(0, 2100)
        self.year.setSpecialValueText("unknown")
        form.addRow("&Title", self.title)
        form.addRow("First &author", self.author)
        form.addRow("&Year", self.year)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._check)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        self.error = QLabel()
        form.addRow(self.error)

    def _check(self):
        if not self.title.text().strip():
            self.error.setText("A title is required.")
            return
        self.accept()

    def values(self) -> dict:
        return {"title": self.title.text().strip(), "author": self.author.text().strip() or None,
                "year": self.year.value() or None}


class WelcomeWizard(QWizard):
    """First run: (1) folders, (2) name format with preview, (3) optional OpenAlex key."""

    def __init__(self, folders: list[str], parent=None, *, allow_login: bool = True,
                 login_default: bool = True):
        super().__init__(parent)
        self.setWindowTitle("Welcome to PaperNym")
        self.setWizardStyle(QWizard.ModernStyle)
        self.setButtonText(QWizard.FinishButton, "Preview renames")

        folders_page = QWizardPage()
        folders_page.setTitle("1. Choose folders")
        folders_page.setSubTitle("PaperNym watches these folders (and their subfolders) and renames "
                                 "new paper PDFs. You will see a preview before anything is renamed.")
        layout = QVBoxLayout(folders_page)
        self.folder_list = QListWidget()
        self.folder_list.setAccessibleName("Folders to watch")
        for folder in folders:
            self.folder_list.addItem(folder)
        layout.addWidget(self.folder_list)
        row = QHBoxLayout()
        add = QPushButton("&Add folder...")
        remove = QPushButton("&Remove")
        add.clicked.connect(self._add_folder)
        remove.clicked.connect(lambda: [self.folder_list.takeItem(self.folder_list.row(item))
                                        for item in self.folder_list.selectedItems()])
        row.addWidget(add)
        row.addWidget(remove)
        row.addStretch(1)
        layout.addLayout(row)
        self.addPage(folders_page)

        format_page = QWizardPage()
        format_page.setTitle("2. Choose a name format")
        layout = QVBoxLayout(format_page)
        self.preset = QComboBox()
        self.preset.setAccessibleName("Name format")
        for name in PRESETS:
            self.preset.addItem(name, name)
        self.preset.currentIndexChanged.connect(self._update_preview)
        layout.addWidget(self.preset)
        layout.addWidget(QLabel("Examples:"))
        self.preview = QLabel()
        self.preview.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.preview)
        layout.addWidget(QLabel("You can also write your own template later in the Naming tab."))
        layout.addStretch(1)
        self.addPage(format_page)

        key_page = QWizardPage()
        key_page.setTitle("3. OpenAlex key (optional)")
        key_page.setSubTitle("A free OpenAlex key adds a second source for lookups. PaperNym works "
                             "without it. The key is kept in your system's credential store "
                             "(Windows Credential Manager on Windows).")
        layout = QFormLayout(key_page)
        self.key = QLineEdit()
        layout.addRow("OpenAlex &key", self.key)
        layout.addRow(LinkLabel("Get a free key", "https://openalex.org/settings/api"))
        self.login = QCheckBox("Start PaperNym when I &log in (it waits quietly in the tray)")
        self.login.setChecked(allow_login and login_default)
        self.login.setEnabled(allow_login)
        if not allow_login:
            self.login.setToolTip("Not available in sandbox mode")
        layout.addRow(self.login)
        self.addPage(key_page)
        self._update_preview()

    def _add_folder(self):
        path = QFileDialog.getExistingDirectory(self, "Choose a folder of papers")
        if path and not self.folder_list.findItems(path, Qt.MatchExactly):
            self.folder_list.addItem(path)

    def _update_preview(self):
        name = self.preset.currentData()
        lines = [build_name(paper, name, ".") for paper in SAMPLE_PAPERS]
        self.preview.setText("\n".join(lines))

    def folders(self) -> list[str]:
        return [self.folder_list.item(i).text() for i in range(self.folder_list.count())]

    def chosen_preset(self) -> str:
        return self.preset.currentData()

    def start_at_login(self) -> bool:
        return self.login.isEnabled() and self.login.isChecked()

    def openalex_key(self) -> str:
        return self.key.text().strip()
