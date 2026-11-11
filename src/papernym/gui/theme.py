"""Colours taken from the app icon (deep teal, amber, white), for light and dark mode.

``apply(app, mode)`` with mode ``system``, ``light`` or ``dark``. Fusion style is used so the
palette applies the same way on Windows and Linux. Text never relies on colour alone.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QGuiApplication, QPalette

TEAL = "#0B5563"     # icon background
AMBER = "#FFB020"    # icon label
MODES = ("system", "light", "dark")

LIGHT = {
    "window": "#F3F7F8", "base": "#FFFFFF", "alt": "#EAF2F4", "text": "#10262C",
    "muted": "#4B6369", "button": "#E3ECEE", "border": "#C3D3D7", "highlight": TEAL,
    "on_highlight": "#FFFFFF", "accent": AMBER, "on_accent": "#1F1600", "link": TEAL,
    "tab": "#E3ECEE", "banner": "#FFF2D1", "on_banner": "#3A2C00", "banner_border": "#E0A41C",
    "disabled": "#8A9A9E",
}
DARK = {
    "window": "#0D1D22", "base": "#11272D", "alt": "#163039", "text": "#E4EEF0",
    "muted": "#9DB3B8", "button": "#1A3740", "border": "#2B4E58", "highlight": "#1C7A89",
    "on_highlight": "#FFFFFF", "accent": AMBER, "on_accent": "#1F1600", "link": "#FFC24D",
    "tab": "#14303A", "banner": "#3A2C00", "on_banner": "#FFE7A8", "banner_border": "#A87410",
    "disabled": "#5F767C",
}


def is_dark(mode: str) -> bool:
    if mode == "dark":
        return True
    if mode == "light":
        return False
    hints = QGuiApplication.styleHints()
    scheme = getattr(hints, "colorScheme", None)
    return bool(scheme) and scheme() == Qt.ColorScheme.Dark


def colours(mode: str) -> dict:
    return DARK if is_dark(mode) else LIGHT


def palette(c: dict) -> QPalette:
    p = QPalette()
    roles = {
        QPalette.Window: c["window"], QPalette.WindowText: c["text"], QPalette.Base: c["base"],
        QPalette.AlternateBase: c["alt"], QPalette.Text: c["text"], QPalette.Button: c["button"],
        QPalette.ButtonText: c["text"], QPalette.Highlight: c["highlight"],
        QPalette.HighlightedText: c["on_highlight"], QPalette.Link: c["link"],
        QPalette.LinkVisited: c["link"], QPalette.ToolTipBase: c["base"], QPalette.ToolTipText: c["text"],
        QPalette.PlaceholderText: c["muted"], QPalette.BrightText: c["accent"],
        QPalette.Mid: c["border"], QPalette.Dark: c["border"], QPalette.Light: c["base"],
    }
    for role, value in roles.items():
        p.setColor(role, QColor(value))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        p.setColor(QPalette.Disabled, role, QColor(c["disabled"]))
    return p


def stylesheet(c: dict) -> str:
    return f"""
QTabWidget::pane {{ border: 1px solid {c['border']}; border-radius: 4px; top: -1px; }}
QTabBar::tab {{ background: {c['tab']}; color: {c['muted']}; padding: 7px 14px;
    border: 1px solid {c['border']}; border-bottom: none; margin-right: 2px;
    border-top-left-radius: 4px; border-top-right-radius: 4px; }}
QTabBar::tab:selected {{ background: {c['base']}; color: {c['text']};
    border-top: 3px solid {c['accent']}; }}
QTabBar::tab:hover:!selected {{ color: {c['text']}; }}
QPushButton {{ background: {c['button']}; color: {c['text']}; border: 1px solid {c['border']};
    border-radius: 4px; padding: 5px 12px; }}
QPushButton:hover {{ border-color: {c['highlight']}; }}
QPushButton:focus {{ border: 2px solid {c['accent']}; }}
QPushButton:default {{ background: {c['accent']}; color: {c['on_accent']}; border-color: {c['accent']}; }}
QPushButton:disabled {{ color: {c['disabled']}; background: {c['window']}; }}
QLineEdit, QComboBox, QSpinBox, QPlainTextEdit, QTextEdit {{ background: {c['base']};
    color: {c['text']}; border: 1px solid {c['border']}; border-radius: 4px; padding: 4px; }}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{ border: 2px solid {c['highlight']}; }}
QTableView, QTreeView, QTreeWidget, QListWidget {{ background: {c['base']};
    alternate-background-color: {c['alt']}; gridline-color: {c['border']};
    border: 1px solid {c['border']}; border-radius: 4px; }}
QHeaderView::section {{ background: {c['tab']}; color: {c['text']}; padding: 5px;
    border: none; border-right: 1px solid {c['border']}; border-bottom: 2px solid {c['highlight']}; }}
QProgressBar {{ border: 1px solid {c['border']}; border-radius: 4px; text-align: center;
    background: {c['base']}; color: {c['text']}; }}
QProgressBar::chunk {{ background: {c['highlight']}; border-radius: 3px; }}
QLabel#banner {{ background: {c['banner']}; color: {c['on_banner']};
    border: 1px solid {c['banner_border']}; border-radius: 4px; padding: 6px; }}
QStatusBar {{ color: {c['muted']}; }}
QCheckBox::indicator {{ width: 14px; height: 14px; border: 1px solid {c['muted']}; border-radius: 3px;
    background: {c['base']}; }}
QCheckBox::indicator:checked {{ background: {c['highlight']}; border-color: {c['highlight']};
    image: url(:/qt-project.org/styles/commonstyle/images/standardbutton-apply-16.png); }}
QCheckBox::indicator:disabled {{ border-color: {c['disabled']}; }}
"""


def apply(app, mode: str = "system"):
    """Style the whole application; call again when the mode or the system scheme changes."""
    if mode not in MODES:
        mode = "system"
    c = colours(mode)
    dark = c is DARK
    if app.property("papernymDark") is dark:
        return c  # already styled this way; restyling repolishes every widget
    if app.property("papernymDark") is None:
        app.setStyle("Fusion")
    app.setPalette(palette(c))
    app.setStyleSheet(stylesheet(c))
    app.setProperty("papernymDark", dark)
    return c
