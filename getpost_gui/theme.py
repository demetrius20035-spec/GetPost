"""Лёгкая пастельная тема оформления.

Базовые цвета фона задаются через ``QPalette`` (чтобы не перекрашивать каждый
виджет вручную и не ловить артефакты), а тонкая стилизация кнопок, вкладок,
полей ввода и акцентной кнопки «Send» — через QSS.
"""
from __future__ import annotations

from .qtcompat import QtGui

# Палитра.
WINDOW_BG = "#f4f6fb"     # еле заметный пастельно-голубой фон
BASE_BG = "#ffffff"       # поля ввода, списки
ALT_BG = "#f7f9fc"
TEXT = "#2c3038"
MUTED = "#525a68"
BORDER = "#d7deea"
ACCENT = "#4c6ef5"        # индиго — акцент (кнопка Send, фокус)
ACCENT_HOVER = "#4263eb"
SELECTION_BG = "#dde6fb"
SELECTION_TEXT = "#1c2333"

_STYLESHEET = f"""
QPushButton, QToolButton {{
    background-color: #eef1f7;
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 4px 12px;
}}
QPushButton:hover, QToolButton:hover {{ background-color: #e3ebf9; border-color: #b9c6de; }}
QPushButton:pressed, QToolButton:pressed {{ background-color: #d4def3; }}
QPushButton:disabled, QToolButton:disabled {{ color: #aab2c0; background-color: #f0f2f6; }}

QToolButton[autoRaise="true"] {{ background: transparent; border: 0; padding: 2px; }}
QToolButton[autoRaise="true"]:hover {{ background-color: #e3ebf9; border-radius: 4px; }}

QPushButton#SendButton {{
    background-color: {ACCENT};
    color: #ffffff;
    border: 0;
    font-weight: bold;
    padding: 5px 18px;
}}
QPushButton#SendButton:hover {{ background-color: {ACCENT_HOVER}; }}
QPushButton#SendButton:pressed {{ background-color: #3b5bdb; }}
QPushButton#SendButton:disabled {{ background-color: #a9b8f6; color: #eef1ff; }}

QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QPlainTextEdit, QTextBrowser, QListWidget {{
    background-color: {BASE_BG};
    border: 1px solid {BORDER};
    border-radius: 6px;
    selection-background-color: {SELECTION_BG};
    selection-color: {SELECTION_TEXT};
}}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{ padding: 4px 6px; }}
QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus, QTextBrowser:focus,
QSpinBox:focus, QDoubleSpinBox:focus {{ border: 1px solid {ACCENT}; }}
QComboBox::drop-down {{ border: 0; width: 18px; }}

QTabWidget::pane {{ border: 1px solid {BORDER}; border-radius: 6px; top: -1px; }}
QTabBar::tab {{
    background: #eef1f7; color: {MUTED};
    padding: 5px 12px; border: 1px solid {BORDER}; border-bottom: 0;
    border-top-left-radius: 6px; border-top-right-radius: 6px; margin-right: 2px;
}}
QTabBar::tab:selected {{ background: {BASE_BG}; color: {TEXT}; }}
QTabBar::tab:hover {{ background: #e3ebf9; }}

QHeaderView::section {{
    background-color: #eef1f7; color: {MUTED};
    padding: 4px; border: 0; border-bottom: 1px solid {BORDER};
}}
QTreeWidget, QTableWidget {{ border: 1px solid {BORDER}; border-radius: 6px; }}
QTreeWidget::item, QTableWidget::item {{ padding: 2px; }}
QTreeView::item:selected, QTableView::item:selected {{
    background: {SELECTION_BG}; color: {SELECTION_TEXT};
}}

QMenuBar::item:selected {{ background: {SELECTION_BG}; }}
QMenu::item:selected {{ background: {SELECTION_BG}; color: {SELECTION_TEXT}; }}
QStatusBar {{ color: {MUTED}; }}
QSplitter::handle {{ background: #e1e6f0; }}

QScrollBar:vertical {{ background: transparent; width: 12px; margin: 0; }}
QScrollBar::handle:vertical {{ background: #c7d0e0; border-radius: 6px; min-height: 24px; }}
QScrollBar::handle:vertical:hover {{ background: #b3bfd6; }}
QScrollBar:horizontal {{ background: transparent; height: 12px; margin: 0; }}
QScrollBar::handle:horizontal {{ background: #c7d0e0; border-radius: 6px; min-width: 24px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; background: none; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}
"""


def apply(app) -> None:
    """Применить пастельную палитру и стиль к приложению."""
    palette = app.palette()
    Role = QtGui.QPalette.ColorRole

    def color(hex_str):
        return QtGui.QColor(hex_str)

    palette.setColor(Role.Window, color(WINDOW_BG))
    palette.setColor(Role.Base, color(BASE_BG))
    palette.setColor(Role.AlternateBase, color(ALT_BG))
    palette.setColor(Role.Button, color("#eef1f7"))
    palette.setColor(Role.Text, color(TEXT))
    palette.setColor(Role.WindowText, color(TEXT))
    palette.setColor(Role.ButtonText, color(TEXT))
    palette.setColor(Role.ToolTipBase, color(BASE_BG))
    palette.setColor(Role.ToolTipText, color(TEXT))
    palette.setColor(Role.Highlight, color(SELECTION_BG))
    palette.setColor(Role.HighlightedText, color(SELECTION_TEXT))
    app.setPalette(palette)
    app.setStyleSheet(_STYLESHEET)
