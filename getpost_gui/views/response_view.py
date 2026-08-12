"""Панель ответа (правая панель).

Показывает статус/время/размер и вкладки:
«Response» (тело с подсветкой JSON/XML, Pretty/Raw, поиск, перенос строк),
«Preview» (рендер HTML и изображений), «Headers», «Cookies», «Time».
Поддерживает историю последних ответов на запрос.
"""
from __future__ import annotations

import json
from typing import List, Optional

from ..highlighter import JsonHighlighter, XmlHighlighter, guess_language
from ..http_client import ResponseData
from ..qtcompat import Qt, QtGui, QtWidgets
from .widgets import monospace_font

_HISTORY_LIMIT = 15


def _format_size(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{int(size)} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{num_bytes} B"


class ResponseView(QtWidgets.QWidget):
    """Отображение ответа сервера."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._highlighter = None
        self._raw_text = ""
        self._language = "text"
        self._current: Optional[ResponseData] = None
        self._history: List[ResponseData] = []
        self._history_guard = False
        self._build_ui()
        self.clear()

    # -- построение интерфейса ---------------------------------------------
    def _build_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # Строка статуса.
        status_row = QtWidgets.QHBoxLayout()
        self.status_label = QtWidgets.QLabel("—")
        self.status_label.setStyleSheet("font-weight: bold;")
        self.time_label = QtWidgets.QLabel("")
        self.size_label = QtWidgets.QLabel("")
        status_row.addWidget(self.status_label)
        status_row.addStretch(1)
        status_row.addWidget(self.time_label)
        status_row.addSpacing(12)
        status_row.addWidget(self.size_label)
        layout.addLayout(status_row)

        # История.
        hist_row = QtWidgets.QHBoxLayout()
        self.history_label = QtWidgets.QLabel("История:")
        self.history_combo = QtWidgets.QComboBox()
        self.history_combo.setMinimumWidth(200)
        self.history_combo.currentIndexChanged.connect(self._on_history_selected)
        hist_row.addWidget(self.history_label)
        hist_row.addWidget(self.history_combo, 1)
        layout.addLayout(hist_row)

        # Сообщения о проблемах извлечения переменных (вкладка Capture).
        self.notice = QtWidgets.QLabel("")
        self.notice.setWordWrap(True)
        self.notice.setStyleSheet("color: #b26a00;")
        self.notice.setVisible(False)
        layout.addWidget(self.notice)

        self.tabs = QtWidgets.QTabWidget()
        self.tabs.addTab(self._build_body_tab(), "Response")
        self.tabs.addTab(self._build_preview_tab(), "Preview")
        self.tabs.addTab(self._build_headers_tab(), "Headers")
        self.tabs.addTab(self._build_cookies_tab(), "Cookies")
        self.time_details = QtWidgets.QPlainTextEdit()
        self.time_details.setReadOnly(True)
        self.tabs.addTab(self.time_details, "Time")
        # «Что реально ушло» — отладка запроса без догадок.
        self.sent_view = QtWidgets.QPlainTextEdit()
        self.sent_view.setReadOnly(True)
        self.sent_view.setFont(monospace_font())
        self.sent_view.setLineWrapMode(QtWidgets.QPlainTextEdit.LineWrapMode.NoWrap)
        self.tabs.addTab(self.sent_view, "Request")
        layout.addWidget(self.tabs, 1)

    def _build_body_tab(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget()
        bv = QtWidgets.QVBoxLayout(page)
        bv.setContentsMargins(0, 0, 0, 0)

        controls = QtWidgets.QHBoxLayout()
        self.pretty_check = QtWidgets.QCheckBox("Pretty")
        self.pretty_check.setChecked(True)
        self.pretty_check.toggled.connect(self._render_body)
        self.wrap_check = QtWidgets.QCheckBox("Перенос")
        self.wrap_check.toggled.connect(self._toggle_wrap)
        self.lang_label = QtWidgets.QLabel("")
        self.lang_label.setStyleSheet("color: #868e96;")
        self.copy_btn = QtWidgets.QToolButton()
        self.copy_btn.setText("Копировать")
        self.copy_btn.clicked.connect(self._copy_body)
        self.save_btn = QtWidgets.QToolButton()
        self.save_btn.setText("Сохранить…")
        self.save_btn.clicked.connect(self._save_body)
        controls.addWidget(self.pretty_check)
        controls.addWidget(self.wrap_check)
        controls.addStretch(1)
        controls.addWidget(self.lang_label)
        controls.addWidget(self.copy_btn)
        controls.addWidget(self.save_btn)
        bv.addLayout(controls)

        # Строка поиска.
        search_row = QtWidgets.QHBoxLayout()
        self.search_edit = QtWidgets.QLineEdit()
        self.search_edit.setPlaceholderText("Поиск по телу ответа…")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.returnPressed.connect(lambda: self._find(True))
        prev_btn = QtWidgets.QToolButton()
        prev_btn.setText("▲")
        prev_btn.setToolTip("Назад")
        prev_btn.clicked.connect(lambda: self._find(False))
        next_btn = QtWidgets.QToolButton()
        next_btn.setText("▼")
        next_btn.setToolTip("Вперёд")
        next_btn.clicked.connect(lambda: self._find(True))
        search_row.addWidget(self.search_edit, 1)
        search_row.addWidget(prev_btn)
        search_row.addWidget(next_btn)
        bv.addLayout(search_row)

        self.body_edit = QtWidgets.QPlainTextEdit()
        self.body_edit.setReadOnly(True)
        self.body_edit.setFont(monospace_font())
        self.body_edit.setLineWrapMode(QtWidgets.QPlainTextEdit.LineWrapMode.NoWrap)
        bv.addWidget(self.body_edit, 1)
        return page

    def _build_preview_tab(self) -> QtWidgets.QWidget:
        self.preview_stack = QtWidgets.QStackedWidget()
        # 0: HTML
        self.preview_browser = QtWidgets.QTextBrowser()
        self.preview_browser.setOpenExternalLinks(True)
        self.preview_stack.addWidget(self.preview_browser)
        # 1: изображение
        self.preview_image = QtWidgets.QLabel()
        self.preview_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.preview_image)
        self.preview_stack.addWidget(scroll)
        # 2: заглушка
        self.preview_placeholder = QtWidgets.QLabel("Превью доступно для HTML и изображений.")
        self.preview_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_placeholder.setStyleSheet("color: #868e96;")
        self.preview_stack.addWidget(self.preview_placeholder)
        return self.preview_stack

    def _build_headers_tab(self) -> QtWidgets.QWidget:
        self.headers_table = QtWidgets.QTableWidget(0, 2)
        self.headers_table.setHorizontalHeaderLabels(["Заголовок", "Значение"])
        self.headers_table.verticalHeader().setVisible(False)
        self.headers_table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        hh = self.headers_table.horizontalHeader()
        hh.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.Stretch)
        return self.headers_table

    def _build_cookies_tab(self) -> QtWidgets.QWidget:
        self.cookies_table = QtWidgets.QTableWidget(0, 2)
        self.cookies_table.setHorizontalHeaderLabels(["Cookie", "Значение"])
        self.cookies_table.verticalHeader().setVisible(False)
        self.cookies_table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        ch = self.cookies_table.horizontalHeader()
        ch.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        ch.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.Stretch)
        return self.cookies_table

    # -- состояния ----------------------------------------------------------
    def clear(self) -> None:
        self._current = None
        self._history = []
        self._set_history_combo()
        self.status_label.setText("—")
        self.status_label.setStyleSheet("font-weight: bold; color: #868e96;")
        self.time_label.setText("")
        self.size_label.setText("")
        self.lang_label.setText("")
        self._raw_text = ""
        self.body_edit.setPlainText("Отправьте запрос, чтобы увидеть ответ.")
        self.headers_table.setRowCount(0)
        self.cookies_table.setRowCount(0)
        self.time_details.setPlainText("")
        self.preview_stack.setCurrentIndex(2)
        self._set_highlighter("text")

    def show_loading(self) -> None:
        self.status_label.setText("Отправка…")
        self.status_label.setStyleSheet("font-weight: bold; color: #1864ab;")
        self.time_label.setText("")
        self.size_label.setText("")
        self.body_edit.setPlainText("Ожидание ответа…")

    def show_error(self, message: str) -> None:
        self.status_label.setText("Ошибка")
        self.status_label.setStyleSheet("font-weight: bold; color: #c92a2a;")
        self.time_label.setText("")
        self.size_label.setText("")
        self.lang_label.setText("")
        self._raw_text = ""
        self._current = None
        self._set_highlighter("text")
        self.body_edit.setPlainText(message)
        self.headers_table.setRowCount(0)
        self.cookies_table.setRowCount(0)
        self.time_details.setPlainText(message)
        self.preview_stack.setCurrentIndex(2)

    def show_response(self, data: ResponseData, history: Optional[List[ResponseData]] = None) -> None:
        self.notice.setVisible(False)
        self._history = list(history) if history else [data]
        self._set_history_combo(select_last=True)
        self._render_data(data)

    def show_capture_problems(self, problems: List[str]) -> None:
        """Показать, какие правила извлечения переменных не сработали."""
        if not problems:
            self.notice.setVisible(False)
            return
        self.notice.setText("⚠ Извлечение переменных: " + "; ".join(problems))
        self.notice.setVisible(True)

    def show_sent_request(self, method: str, url: str, kwargs: dict) -> None:
        """Показать то, что реально отправляется (вкладка «Request»)."""
        lines = [f"{method} {url}", ""]
        params = kwargs.get("params")
        if params:
            lines.append("Query:")
            lines += [f"  {k} = {v}" for k, v in params]
            lines.append("")
        headers = kwargs.get("headers") or {}
        if headers:
            lines.append("Headers:")
            lines += [f"  {k}: {v}" for k, v in headers.items()]
            lines.append("")
        auth = kwargs.get("auth")
        if auth is not None and hasattr(auth, "username"):
            lines.append(f"Basic auth: {auth.username}:***")
            lines.append("")

        data = kwargs.get("data")
        if isinstance(data, (bytes, bytearray)):
            lines.append(f"Body ({len(data)} байт):")
            lines.append(data.decode("utf-8", "replace"))
        elif isinstance(data, list):
            lines.append("Body (x-www-form-urlencoded):")
            lines += [f"  {k} = {v}" for k, v in data]
        elif kwargs.get("files"):
            lines.append("Body (multipart/form-data):")
            for key, filetuple in kwargs["files"]:
                filename, content = filetuple[0], filetuple[1]
                if filename:
                    lines.append(f"  {key} = файл «{filename}» ({len(content)} байт)")
                else:
                    lines.append(f"  {key} = {content}")
        else:
            lines.append("Body: —")

        lines.append("")
        lines.append(
            f"Редиректы: {'да' if kwargs.get('allow_redirects', True) else 'нет'} · "
            f"Проверка TLS: {'да' if kwargs.get('verify', True) else 'нет'}"
        )
        self.sent_view.setPlainText("\n".join(lines))

    # -- история ------------------------------------------------------------
    def _set_history_combo(self, select_last: bool = False) -> None:
        self._history_guard = True
        try:
            self.history_combo.clear()
            for idx, d in enumerate(self._history, 1):
                self.history_combo.addItem(f"#{idx}  {d.status_line} · {d.elapsed_ms:.0f} мс")
            has_many = len(self._history) > 1
            self.history_label.setVisible(has_many)
            self.history_combo.setVisible(has_many)
            if select_last and self._history:
                self.history_combo.setCurrentIndex(len(self._history) - 1)
        finally:
            self._history_guard = False

    def _on_history_selected(self, index: int) -> None:
        if self._history_guard or not (0 <= index < len(self._history)):
            return
        self._render_data(self._history[index])

    # -- отрисовка ----------------------------------------------------------
    def _render_data(self, data: ResponseData) -> None:
        self._current = data
        color = "#2b8a3e" if data.ok else "#c92a2a"
        if data.status_code >= 500:
            color = "#c92a2a"
        elif data.status_code >= 400:
            color = "#e8590c"
        elif data.status_code >= 300:
            color = "#1864ab"
        self.status_label.setText(data.status_line)
        self.status_label.setStyleSheet(f"font-weight: bold; color: {color};")
        self.time_label.setText(f"Время: {data.elapsed_ms:.0f} мс")
        self.size_label.setText(f"Размер: {_format_size(data.size_bytes)}")

        # Заголовки.
        self._fill_table(self.headers_table, data.headers)
        # Cookies.
        self._fill_table(self.cookies_table, data.cookies)

        # Детали времени.
        details = [
            f"Статус:        {data.status_line}",
            f"Время ответа:  {data.elapsed_ms:.1f} мс",
            f"Размер тела:   {_format_size(data.size_bytes)} ({data.size_bytes} байт)",
            f"Итоговый URL:  {data.url}",
            f"Content-Type:  {data.content_type or '—'}",
            f"Заголовков:    {len(data.headers)}",
            f"Cookies:       {len(data.cookies)}",
        ]
        self.time_details.setPlainText("\n".join(details))

        # Тело.
        self._raw_text = data.text
        self._language = guess_language(data.content_type, data.text)
        self.lang_label.setText(self._language.upper())
        self.pretty_check.setEnabled(self._language in ("json", "xml"))
        self._render_body()
        self._render_preview(data)

    @staticmethod
    def _fill_table(table: QtWidgets.QTableWidget, rows) -> None:
        table.setRowCount(0)
        for key, value in rows:
            r = table.rowCount()
            table.insertRow(r)
            table.setItem(r, 0, QtWidgets.QTableWidgetItem(str(key)))
            table.setItem(r, 1, QtWidgets.QTableWidgetItem(str(value)))

    def _render_body(self) -> None:
        text = self._raw_text
        pretty = self.pretty_check.isChecked() and self.pretty_check.isEnabled()
        if pretty and self._language == "json":
            text = self._pretty_json(self._raw_text)
        self._set_highlighter(self._language)
        self.body_edit.setPlainText(text)

    def _render_preview(self, data: ResponseData) -> None:
        ct = (data.content_type or "").lower()
        if ct.startswith("image/"):
            pix = QtGui.QPixmap()
            if pix.loadFromData(data.content):
                self.preview_image.setPixmap(pix)
                self.preview_stack.setCurrentIndex(1)
                return
        if "html" in ct:
            self.preview_browser.setHtml(data.text)
            self.preview_stack.setCurrentIndex(0)
            return
        self.preview_stack.setCurrentIndex(2)

    # -- действия -----------------------------------------------------------
    def _toggle_wrap(self, wrap: bool) -> None:
        mode = (
            QtWidgets.QPlainTextEdit.LineWrapMode.WidgetWidth
            if wrap
            else QtWidgets.QPlainTextEdit.LineWrapMode.NoWrap
        )
        self.body_edit.setLineWrapMode(mode)

    def _copy_body(self) -> None:
        QtWidgets.QApplication.clipboard().setText(self.body_edit.toPlainText())

    def _save_body(self) -> None:
        if self._current is None:
            return
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Сохранить ответ")
        if not path:
            return
        with open(path, "wb") as fh:
            fh.write(self._current.content or self._current.text.encode("utf-8"))

    def _find(self, forward: bool) -> None:
        text = self.search_edit.text()
        if not text:
            return
        flags = QtGui.QTextDocument.FindFlag(0)
        if not forward:
            flags |= QtGui.QTextDocument.FindFlag.FindBackward
        if not self.body_edit.find(text, flags):
            # Перенос поиска в начало/конец документа.
            cursor = self.body_edit.textCursor()
            cursor.movePosition(
                QtGui.QTextCursor.MoveOperation.End if not forward else QtGui.QTextCursor.MoveOperation.Start
            )
            self.body_edit.setTextCursor(cursor)
            self.body_edit.find(text, flags)

    @staticmethod
    def _pretty_json(text: str) -> str:
        try:
            return json.dumps(json.loads(text), ensure_ascii=False, indent=2)
        except (ValueError, TypeError):
            return text

    def _set_highlighter(self, language: str) -> None:
        if self._highlighter is not None:
            self._highlighter.setDocument(None)
            self._highlighter = None
        if language == "json":
            self._highlighter = JsonHighlighter(self.body_edit.document())
        elif language == "xml":
            self._highlighter = XmlHighlighter(self.body_edit.document())
