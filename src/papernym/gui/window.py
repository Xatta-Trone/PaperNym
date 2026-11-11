"""Main window: banner area above the seven tabs. Closing hides it; only Quit exits."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QMainWindow, QPushButton, QTabWidget,
                               QVBoxLayout, QWidget)

from .common import app_icon
from .tabs import (ActivityTab, AttentionTab, FoldersTab, GeneralTab, HistoryTab, NamingTab,
                   SourcesTab)

class Banner(QWidget):
    """A dismissible, non-blocking message line (text first, so it never relies on colour)."""

    def __init__(self):
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.label = QLabel()
        self.label.setObjectName("banner")
        self.label.setWordWrap(True)
        layout.addWidget(self.label, 1)
        close = QPushButton("&Dismiss")
        close.clicked.connect(self.hide)
        layout.addWidget(close)
        self.hide()

    def show_message(self, text: str):
        self.label.setText(text)
        self.show()


class MainWindow(QMainWindow):
    def __init__(self, ctl):
        super().__init__()
        self.ctl = ctl
        self.setWindowTitle("PaperNym" + ("  [SANDBOX]" if ctl.sandbox else ""))
        self.setWindowIcon(app_icon())
        self.resize(1100, 680)
        central = QWidget()
        layout = QVBoxLayout(central)
        if ctl.sandbox:
            sandbox = QLabel(f"SANDBOX: temporary settings in {ctl.home}; "
                             "only a temporary copy of the sample papers is watched.")
            sandbox.setObjectName("banner")
            sandbox.setWordWrap(True)
            layout.addWidget(sandbox)
        self.outage = Banner()
        self.notice = Banner()
        layout.addWidget(self.outage)
        layout.addWidget(self.notice)
        self.tabs = QTabWidget()
        self.activity = ActivityTab(ctl)
        self.attention = AttentionTab(ctl)
        self.folders = FoldersTab(ctl)
        self.naming = NamingTab(ctl)
        self.sources = SourcesTab(ctl)
        self.history = HistoryTab(ctl)
        self.general = GeneralTab(ctl)
        for widget, title in ((self.activity, "&Activity"), (self.attention, "Needs a&ttention"),
                              (self.folders, "&Folders"), (self.naming, "&Naming"),
                              (self.sources, "S&ources"), (self.history, "&History"),
                              (self.general, "&General")):
            self.tabs.addTab(widget, title)
        layout.addWidget(self.tabs)
        self.setCentralWidget(central)
        self.statusBar().showMessage("Starting...")
        for index in range(self.tabs.count()):
            QShortcut(QKeySequence(f"Ctrl+{index + 1}"), self,
                      activated=lambda i=index: self.tabs.setCurrentIndex(i))
        QShortcut(QKeySequence("Ctrl+W"), self, activated=self.hide)

    def set_attention_count(self, count: int):
        index = self.tabs.indexOf(self.attention)
        self.tabs.setTabText(index, f"Needs a&ttention ({count})" if count else "Needs a&ttention")

    def show_tab(self, widget):
        self.tabs.setCurrentWidget(widget)

    def bring_to_front(self):
        self.show()
        self.setWindowState((self.windowState() & ~Qt.WindowMinimized) | Qt.WindowActive)
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event):
        if self.ctl.quitting:
            event.accept()
            return
        event.ignore()
        self.hide()
