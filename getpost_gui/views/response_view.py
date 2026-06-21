"""Панель ответа (правая панель).

Показывает статус, время и размер ответа, а также вкладки:
«Response» (тело с подсветкой JSON/XML и переключателем Pretty/Raw),
«Headers» (заголовки ответа) и «Time» (детали выполнения).
"""
from __future__ import annotations

import json

from ..highlighter import JsonHighlighter, XmlHighlighter, guess_language
from ..http_client import ResponseData
from ..qtcompat import QtWidgets
from .widgets import monospace_font


def _format_size(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{num_bytes} B"


class ResponseView(QtWidgets.QWidget):
    """Отображение ответа сервера."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._highlighter = None
        self._raw_text = ""
        self._language = "text"
        self._build_ui()
        self.clear()

    def _build_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # Строка статуса
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

        self.tabs = QtWidgets.QTabWidget()

        # Вкладка Response (тело)
        body_page = QtWidgets.QWidget()
        bv = QtWidgets.QVBoxLayout(body_page)
        bv.setContentsMargins(0, 0, 0, 0)
        controls = QtWidgets.QHBoxLayout()
        self.pretty_check = QtWidgets.QCheckBox("Pretty")
        self.pretty_check.setChecked(True)
        self.pretty_check.toggled.connect(self._render_body)
        self.lang_label = QtWidgets.QLabel("")
        self.lang_label.setStyleSheet("color: #868e96;")
        controls.addWidget(self.pretty_check)
        controls.addStretch(1)
        controls.addWidget(self.lang_label)
        bv.addLayout(controls)

        self.body_edit = QtWidgets.QPlainTextEdit()
        self.body_edit.setReadOnly(True)
        self.body_edit.setFont(monospace_font())
        self.body_edit.setLineWrapMode(QtWidgets.QPlainTextEdit.LineWrapMode.NoWrap)
        bv.addWidget(self.body_edit, 1)
        self.tabs.addTab(body_page, "Response")

        # Вкладка Headers
        self.headers_table = QtWidgets.QTableWidget(0, 2)
        self.headers_table.setHorizontalHeaderLabels(["Заголовок", "Значение"])
        self.headers_table.verticalHeader().setVisible(False)
        self.headers_table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        hh = self.headers_table.horizontalHeader()
        hh.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.Stretch)
        self.tabs.addTab(self.headers_table, "Headers")

        # Вкладка Time
        self.time_details = QtWidgets.QPlainTextEdit()
        self.time_details.setReadOnly(True)
        self.tabs.addTab(self.time_details, "Time")

        layout.addWidget(self.tabs, 1)

    # -- состояния ----------------------------------------------------------
    def clear(self) -> None:
        self.status_label.setText("—")
        self.status_label.setStyleSheet("font-weight: bold; color: #868e96;")
        self.time_label.setText("")
        self.size_label.setText("")
        self.lang_label.setText("")
        self._raw_text = ""
        self.body_edit.setPlainText("Отправьте запрос, чтобы увидеть ответ.")
        self.headers_table.setRowCount(0)
        self.time_details.setPlainText("")
        self._set_highlighter("text")

    def show_loading(self) -> None:
        self.status_label.setText("Отправка…")
        self.status_label.setStyleSheet("font-weight: bold; color: #1864ab;")
        self.time_label.setText("")
        self.size_label.setText("")
        self.body_edit.setPlainText("Ожидание ответа…")
        self.headers_table.setRowCount(0)
        self.time_details.setPlainText("")

    def show_error(self, message: str) -> None:
        self.status_label.setText("Ошибка")
        self.status_label.setStyleSheet("font-weight: bold; color: #c92a2a;")
        self.time_label.setText("")
        self.size_label.setText("")
        self.lang_label.setText("")
        self._raw_text = ""
        self._set_highlighter("text")
        self.body_edit.setPlainText(message)
        self.headers_table.setRowCount(0)
        self.time_details.setPlainText(message)

    def show_response(self, data: ResponseData) -> None:
        # Статус с цветовой индикацией.
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

        # Заголовки
        self.headers_table.setRowCount(0)
        for key, value in data.headers:
            row = self.headers_table.rowCount()
            self.headers_table.insertRow(row)
            self.headers_table.setItem(row, 0, QtWidgets.QTableWidgetItem(str(key)))
            self.headers_table.setItem(row, 1, QtWidgets.QTableWidgetItem(str(value)))

        # Детали времени
        details = [
            f"Статус:        {data.status_line}",
            f"Время ответа:  {data.elapsed_ms:.1f} мс",
            f"Размер тела:   {_format_size(data.size_bytes)} ({data.size_bytes} байт)",
            f"Итоговый URL:  {data.url}",
            f"Content-Type:  {data.content_type or '—'}",
            f"Заголовков:    {len(data.headers)}",
        ]
        self.time_details.setPlainText("\n".join(details))

        # Тело
        self._raw_text = data.text
        self._language = guess_language(data.content_type, data.text)
        self.lang_label.setText(self._language.upper())
        self.pretty_check.setEnabled(self._language in ("json", "xml"))
        self._render_body()

    # -- отрисовка тела -----------------------------------------------------
    def _render_body(self) -> None:
        text = self._raw_text
        pretty = self.pretty_check.isChecked() and self.pretty_check.isEnabled()
        if pretty and self._language == "json":
            text = self._pretty_json(self._raw_text)
        self._set_highlighter(self._language)
        self.body_edit.setPlainText(text)

    @staticmethod
    def _pretty_json(text: str) -> str:
        try:
            parsed = json.loads(text)
            return json.dumps(parsed, ensure_ascii=False, indent=2)
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
