"""Оформление: светлая пастельная и тёмная темы.

Базовые цвета задаются через ``QPalette`` (чтобы не перекрашивать каждый виджет
вручную), а тонкая стилизация кнопок, вкладок, полей ввода и акцентной кнопки
«Send» — через QSS. Обе темы описаны одним набором токенов, поэтому добавить
третью можно, не меняя разметку.
"""
from __future__ import annotations

from .qtcompat import QtGui

THEME_LIGHT = "light"
THEME_DARK = "dark"
THEMES = [(THEME_LIGHT, "Светлая"), (THEME_DARK, "Тёмная")]

# --- Палитры ---------------------------------------------------------------
LIGHT = {
    "window": "#f4f6fb",     # еле заметный пастельно-голубой фон
    "base": "#ffffff",       # поля ввода, списки
    "alt_base": "#f7f9fc",
    "text": "#2c3038",
    "muted": "#525a68",
    "border": "#d7deea",
    "button": "#eef1f7",
    "button_hover": "#e3ebf9",
    "button_pressed": "#d4def3",
    "button_border_hover": "#b9c6de",
    "disabled_text": "#aab2c0",
    "disabled_bg": "#f0f2f6",
    "accent": "#4c6ef5",
    "accent_hover": "#4263eb",
    "accent_pressed": "#3b5bdb",
    "accent_disabled": "#a9b8f6",
    "accent_text": "#ffffff",
    "selection": "#dde6fb",
    "selection_text": "#1c2333",
    "splitter": "#e1e6f0",
    "scroll": "#c7d0e0",
    "scroll_hover": "#b3bfd6",
    "warning": "#b26a00",
}

DARK = {
    "window": "#1f2430",
    "base": "#252b38",
    "alt_base": "#2a3140",
    "text": "#dfe4ee",
    "muted": "#9aa4b8",
    "border": "#39424f",
    "button": "#2c3341",
    "button_hover": "#354052",
    "button_pressed": "#3d4a5f",
    "button_border_hover": "#4a5568",
    "disabled_text": "#6b7484",
    "disabled_bg": "#262c37",
    "accent": "#5c7cfa",
    "accent_hover": "#6b8afd",
    "accent_pressed": "#4c6ef5",
    "accent_disabled": "#3b4560",
    "accent_text": "#ffffff",
    "selection": "#33415c",
    "selection_text": "#e9edf5",
    "splitter": "#2e3646",
    "scroll": "#414b5c",
    "scroll_hover": "#4d5a6e",
    "warning": "#e8b339",
}

# Цвета подсветки синтаксиса и статусов — зависят от темы.
LIGHT_SYNTAX = {
    "key": "#0b7285", "string": "#2b8a3e", "number": "#1864ab",
    "keyword": "#c2255c", "punct": "#868e96", "tag": "#1864ab",
    "attr": "#0b7285", "comment": "#868e96",
    "ok": "#2b8a3e", "redirect": "#1864ab", "client_error": "#e8590c",
    "server_error": "#c92a2a", "idle": "#868e96",
}
DARK_SYNTAX = {
    "key": "#66d9e8", "string": "#8ce99a", "number": "#74c0fc",
    "keyword": "#faa2c1", "punct": "#909aad", "tag": "#74c0fc",
    "attr": "#66d9e8", "comment": "#7f8a9e",
    "ok": "#69db7c", "redirect": "#74c0fc", "client_error": "#ffa94d",
    "server_error": "#ff8787", "idle": "#909aad",
}

# Текущая тема (её читают подсветка синтаксиса и панель ответа).
_current = THEME_LIGHT


def current() -> str:
    return _current


def colors() -> dict:
    """Токены активной темы."""
    return DARK if _current == THEME_DARK else LIGHT


def syntax() -> dict:
    """Цвета подсветки для активной темы."""
    return DARK_SYNTAX if _current == THEME_DARK else LIGHT_SYNTAX


def _stylesheet(c: dict) -> str:
    return f"""
QPushButton, QToolButton {{
    background-color: {c['button']};
    border: 1px solid {c['border']};
    border-radius: 6px;
    padding: 4px 12px;
}}
QPushButton:hover, QToolButton:hover {{
    background-color: {c['button_hover']};
    border-color: {c['button_border_hover']};
}}
QPushButton:pressed, QToolButton:pressed {{ background-color: {c['button_pressed']}; }}
QPushButton:disabled, QToolButton:disabled {{
    color: {c['disabled_text']}; background-color: {c['disabled_bg']};
}}

QToolButton[autoRaise="true"] {{ background: transparent; border: 0; padding: 2px; }}
QToolButton[autoRaise="true"]:hover {{ background-color: {c['button_hover']}; border-radius: 4px; }}

QPushButton#SendButton {{
    background-color: {c['accent']};
    color: {c['accent_text']};
    border: 0;
    font-weight: bold;
    padding: 5px 18px;
}}
QPushButton#SendButton:hover {{ background-color: {c['accent_hover']}; }}
QPushButton#SendButton:pressed {{ background-color: {c['accent_pressed']}; }}
QPushButton#SendButton:disabled {{ background-color: {c['accent_disabled']}; color: {c['muted']}; }}

QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QPlainTextEdit, QTextBrowser, QListWidget {{
    background-color: {c['base']};
    border: 1px solid {c['border']};
    border-radius: 6px;
    selection-background-color: {c['selection']};
    selection-color: {c['selection_text']};
}}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{ padding: 4px 6px; }}
QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus, QTextBrowser:focus,
QSpinBox:focus, QDoubleSpinBox:focus {{ border: 1px solid {c['accent']}; }}
QComboBox::drop-down {{ border: 0; width: 18px; }}

QTabWidget::pane {{ border: 1px solid {c['border']}; border-radius: 6px; top: -1px; }}
QTabBar::tab {{
    background: {c['button']}; color: {c['muted']};
    padding: 5px 12px; border: 1px solid {c['border']}; border-bottom: 0;
    border-top-left-radius: 6px; border-top-right-radius: 6px; margin-right: 2px;
}}
QTabBar::tab:selected {{ background: {c['base']}; color: {c['text']}; }}
QTabBar::tab:hover {{ background: {c['button_hover']}; }}

QHeaderView::section {{
    background-color: {c['button']}; color: {c['muted']};
    padding: 4px; border: 0; border-bottom: 1px solid {c['border']};
}}
QTreeWidget, QTableWidget {{ border: 1px solid {c['border']}; border-radius: 6px; }}
QTreeWidget::item, QTableWidget::item {{ padding: 2px; }}
QTreeView::item:selected, QTableView::item:selected {{
    background: {c['selection']}; color: {c['selection_text']};
}}

QMenuBar::item:selected {{ background: {c['selection']}; }}
QMenu::item:selected {{ background: {c['selection']}; color: {c['selection_text']}; }}
QStatusBar {{ color: {c['muted']}; }}
QSplitter::handle {{ background: {c['splitter']}; }}
QGroupBox {{ border: 1px solid {c['border']}; border-radius: 6px; margin-top: 8px; padding-top: 6px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 8px; color: {c['muted']}; }}

QScrollBar:vertical {{ background: transparent; width: 12px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {c['scroll']}; border-radius: 6px; min-height: 24px; }}
QScrollBar::handle:vertical:hover {{ background: {c['scroll_hover']}; }}
QScrollBar:horizontal {{ background: transparent; height: 12px; margin: 0; }}
QScrollBar::handle:horizontal {{ background: {c['scroll']}; border-radius: 6px; min-width: 24px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; background: none; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}
"""


def apply(app, theme: str = THEME_LIGHT) -> None:
    """Применить тему к приложению (``light`` или ``dark``)."""
    global _current
    _current = THEME_DARK if theme == THEME_DARK else THEME_LIGHT
    c = colors()

    palette = QtGui.QPalette()
    Role = QtGui.QPalette.ColorRole
    Group = QtGui.QPalette.ColorGroup

    def color(token):
        return QtGui.QColor(c[token])

    palette.setColor(Role.Window, color("window"))
    palette.setColor(Role.Base, color("base"))
    palette.setColor(Role.AlternateBase, color("alt_base"))
    palette.setColor(Role.Button, color("button"))
    palette.setColor(Role.Text, color("text"))
    palette.setColor(Role.WindowText, color("text"))
    palette.setColor(Role.ButtonText, color("text"))
    palette.setColor(Role.PlaceholderText, color("muted"))
    palette.setColor(Role.ToolTipBase, color("base"))
    palette.setColor(Role.ToolTipText, color("text"))
    palette.setColor(Role.Highlight, color("selection"))
    palette.setColor(Role.HighlightedText, color("selection_text"))
    palette.setColor(Role.Link, color("accent"))
    for role in (Role.Text, Role.WindowText, Role.ButtonText):
        palette.setColor(Group.Disabled, role, color("disabled_text"))

    app.setPalette(palette)
    app.setStyleSheet(_stylesheet(c))
