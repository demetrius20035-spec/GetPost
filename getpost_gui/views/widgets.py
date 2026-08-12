"""Переиспользуемые виджеты.

``KeyValueTable`` — редактируемая таблица пар «ключ-значение» с флажком
включения и кнопкой удаления для каждой строки. Последняя строка всегда
пустая: как только пользователь начинает её заполнять, автоматически
добавляется новая пустая строка (поведение, привычное по Postman).
"""
from __future__ import annotations

from typing import Any, Dict, List

from ..http_client import FILE_PREFIX as HTTP_FILE_PREFIX
from ..qtcompat import Qt, QtGui, QtWidgets, Signal


def monospace_font() -> QtGui.QFont:
    """Системный моноширинный шрифт (для редакторов тела запроса/ответа)."""
    font = QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.SystemFont.FixedFont)
    font.setPointSize(max(10, font.pointSize()))
    return font


MASK_TEXT = "••••••••"


class KeyValueTable(QtWidgets.QWidget):
    """Таблица пар ключ-значение с автодобавлением пустой строки.

    Дополнительные режимы:

    * ``secret_column`` — колонка «секрет» (значение маскируется и не попадает
      в экспорт);
    * ``file_column``   — кнопка выбора файла, подставляющая ``@путь``
      (так поле уходит как файл в multipart/form-data).
    """

    changed = Signal()

    def __init__(self, key_label: str = "Key", value_label: str = "Value", parent=None,
                 secret_column: bool = False, file_column: bool = False):
        super().__init__(parent)
        self._mutating = False
        self._secret_column = secret_column
        self._file_column = file_column
        self._masked = False
        # Реальные значения секретных строк, пока они скрыты маской.
        self._hidden_values: dict = {}

        columns = ["", key_label, value_label]
        self._col_secret = -1
        self._col_file = -1
        if secret_column:
            self._col_secret = len(columns)
            columns.append("🔒")
        if file_column:
            self._col_file = len(columns)
            columns.append("")
        self._col_delete = len(columns)
        columns.append("")

        self.table = QtWidgets.QTableWidget(0, len(columns), self)
        self.table.setHorizontalHeaderLabels(columns)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.NoSelection)
        self.table.setEditTriggers(
            QtWidgets.QAbstractItemView.EditTrigger.DoubleClicked
            | QtWidgets.QAbstractItemView.EditTrigger.SelectedClicked
            | QtWidgets.QAbstractItemView.EditTrigger.AnyKeyPressed
            | QtWidgets.QAbstractItemView.EditTrigger.EditKeyPressed
        )

        header = self.table.horizontalHeader()
        for col in range(self.table.columnCount()):
            mode = (
                QtWidgets.QHeaderView.ResizeMode.Stretch
                if col in (1, 2)
                else QtWidgets.QHeaderView.ResizeMode.ResizeToContents
            )
            header.setSectionResizeMode(col, mode)

        # Массовое редактирование: те же данные текстом, построчно «Ключ: Значение».
        self.bulk_edit = QtWidgets.QPlainTextEdit()
        self.bulk_edit.setFont(monospace_font())
        self.bulk_edit.setPlaceholderText(
            "По одной паре в строке:\nContent-Type: application/json\n"
            "# строка с решёткой — выключенная пара"
        )
        self.bulk_edit.setVisible(False)

        self.bulk_toggle = QtWidgets.QToolButton()
        self.bulk_toggle.setText("Текстом")
        self.bulk_toggle.setCheckable(True)
        self.bulk_toggle.setToolTip(
            "Массовое редактирование: вставить или скопировать сразу все пары"
        )
        self.bulk_toggle.toggled.connect(self._toggle_bulk)

        toolbar = QtWidgets.QHBoxLayout()
        toolbar.setContentsMargins(0, 0, 0, 0)
        toolbar.addStretch(1)
        toolbar.addWidget(self.bulk_toggle)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(toolbar)
        layout.addWidget(self.table)
        layout.addWidget(self.bulk_edit)

        self.table.itemChanged.connect(self._on_item_changed)
        self._append_blank_row()

    # -- построение строк ---------------------------------------------------
    def _make_text_item(self, text: str) -> QtWidgets.QTableWidgetItem:
        item = QtWidgets.QTableWidgetItem(text)
        item.setFlags(
            Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsEditable | Qt.ItemFlag.ItemIsSelectable
        )
        return item

    def _make_check_item(self, enabled: bool) -> QtWidgets.QTableWidgetItem:
        item = QtWidgets.QTableWidgetItem()
        item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(Qt.CheckState.Checked if enabled else Qt.CheckState.Unchecked)
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        return item

    def _insert_row(self, row: int, enabled: bool, key: str, value: str,
                    secret: bool = False) -> None:
        self.table.insertRow(row)
        self.table.setItem(row, 0, self._make_check_item(enabled))
        self.table.setItem(row, 1, self._make_text_item(key))
        self.table.setItem(row, 2, self._make_text_item(value))

        if self._col_secret >= 0:
            item = self._make_check_item(secret)
            item.setToolTip("Секрет: значение маскируется и не попадает в экспорт")
            self.table.setItem(row, self._col_secret, item)

        if self._col_file >= 0:
            pick = QtWidgets.QToolButton(self.table)
            pick.setText("📎")
            pick.setAutoRaise(True)
            pick.setToolTip("Выбрать файл для отправки")
            pick.clicked.connect(lambda: self._pick_file(pick))
            self.table.setCellWidget(row, self._col_file, pick)

        btn = QtWidgets.QToolButton(self.table)
        btn.setText("✕")
        btn.setAutoRaise(True)
        btn.setToolTip("Удалить строку")
        btn.clicked.connect(lambda: self._remove_button_row(btn))
        self.table.setCellWidget(row, self._col_delete, btn)

    def _append_blank_row(self) -> None:
        self._insert_row(self.table.rowCount(), True, "", "")

    # -- выбор файла (multipart) --------------------------------------------
    def _row_of_widget(self, widget, column: int) -> int:
        for row in range(self.table.rowCount()):
            if self.table.cellWidget(row, column) is widget:
                return row
        return -1

    def _pick_file(self, button) -> None:
        row = self._row_of_widget(button, self._col_file)
        if row < 0:
            return
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Файл для отправки")
        if not path:
            return
        value_item = self.table.item(row, 2)
        if value_item is not None:
            # Соглашение "@путь" совпадает с CLI и обрабатывается ядром.
            value_item.setText(f"{HTTP_FILE_PREFIX}{path}")
        key_item = self.table.item(row, 1)
        if key_item is not None and not key_item.text().strip():
            key_item.setText("file")

    # -- реакции на изменения ----------------------------------------------
    def _remove_button_row(self, btn: QtWidgets.QToolButton) -> None:
        for row in range(self.table.rowCount()):
            if self.table.cellWidget(row, self._col_delete) is btn:
                # Не даём удалить единственную (пустую) строку — просто чистим её.
                if self.table.rowCount() == 1:
                    self.set_items([])
                else:
                    self.table.removeRow(row)
                    self._ensure_trailing_blank()
                self.changed.emit()
                return

    def _row_is_empty(self, row: int) -> bool:
        key = self.table.item(row, 1)
        value = self.table.item(row, 2)
        return not (key and key.text().strip()) and not (value and value.text().strip())

    def _ensure_trailing_blank(self) -> None:
        rows = self.table.rowCount()
        if rows == 0 or not self._row_is_empty(rows - 1):
            self._append_blank_row()

    def _on_item_changed(self, item: QtWidgets.QTableWidgetItem) -> None:
        if self._mutating:
            return
        self._mutating = True
        try:
            # Если заполнили последнюю строку — добавляем новую пустую.
            if item.column() in (1, 2) and item.row() == self.table.rowCount() - 1:
                if not self._row_is_empty(item.row()):
                    self._append_blank_row()
        finally:
            self._mutating = False
        self.changed.emit()

    # -- массовое редактирование текстом ------------------------------------
    def _items_to_text(self) -> str:
        lines = []
        for item in self.get_items():
            prefix = "" if item.get("enabled", True) else "# "
            lines.append(f"{prefix}{item.get('key', '')}: {item.get('value', '')}")
        return "\n".join(lines)

    @staticmethod
    def _text_to_items(text: str) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        for line in (text or "").splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            enabled = True
            if stripped.startswith("#"):
                enabled = False
                stripped = stripped[1:].strip()
                if not stripped:
                    continue
            # Разделителем считается первый «:» или «=» — что встретилось раньше.
            colon, equals = stripped.find(":"), stripped.find("=")
            candidates = [pos for pos in (colon, equals) if pos > 0]
            if candidates:
                pos = min(candidates)
                key, value = stripped[:pos], stripped[pos + 1:]
            else:
                key, value = stripped, ""
            items.append({"enabled": enabled, "key": key.strip(), "value": value.strip()})
        return items

    def _toggle_bulk(self, enabled: bool) -> None:
        """Переключиться между таблицей и текстовым режимом, сохранив данные."""
        if enabled:
            self.bulk_edit.setPlainText(self._items_to_text())
            self.table.setVisible(False)
            self.bulk_edit.setVisible(True)
        else:
            parsed = self._text_to_items(self.bulk_edit.toPlainText())
            secrets = {i.get("key"): i.get("secret", False) for i in self.get_items()}
            if self._col_secret >= 0:
                for item in parsed:
                    item["secret"] = secrets.get(item["key"], False)
            self.set_items(parsed)
            self.bulk_edit.setVisible(False)
            self.table.setVisible(True)
            self.changed.emit()

    def is_bulk_mode(self) -> bool:
        return self.bulk_toggle.isChecked()

    def commit_bulk(self) -> None:
        """Применить текстовый режим, если он включён (перед чтением данных)."""
        if self.bulk_toggle.isChecked():
            self.bulk_toggle.setChecked(False)

    # -- секреты и маскирование ---------------------------------------------
    def _is_secret_row(self, row: int) -> bool:
        if self._col_secret < 0:
            return False
        item = self.table.item(row, self._col_secret)
        return bool(item) and item.checkState() == Qt.CheckState.Checked

    def set_secret_masked(self, masked: bool) -> None:
        """Скрыть/показать значения секретных строк.

        Пока значение скрыто, ячейка недоступна для правки — так маска не может
        затереть настоящее значение.
        """
        if self._col_secret < 0:
            return
        self._mutating = True
        try:
            if masked and not self._masked:
                self._hidden_values = {}
                for row in range(self.table.rowCount()):
                    value_item = self.table.item(row, 2)
                    if value_item is None or not self._is_secret_row(row):
                        continue
                    real = value_item.text()
                    if not real:
                        continue
                    self._hidden_values[row] = real
                    value_item.setText(MASK_TEXT)
                    value_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            elif not masked and self._masked:
                for row, real in self._hidden_values.items():
                    value_item = self.table.item(row, 2)
                    if value_item is not None:
                        value_item.setText(real)
                        value_item.setFlags(
                            Qt.ItemFlag.ItemIsEnabled
                            | Qt.ItemFlag.ItemIsEditable
                            | Qt.ItemFlag.ItemIsSelectable
                        )
                self._hidden_values = {}
            self._masked = masked
        finally:
            self._mutating = False

    # -- публичный API ------------------------------------------------------
    def get_items(self) -> List[Dict[str, Any]]:
        """Вернуть непустые строки в виде списка словарей.

        Значения скрытых маской секретов возвращаются настоящими.
        """
        items: List[Dict[str, Any]] = []
        for row in range(self.table.rowCount()):
            if self._row_is_empty(row):
                continue
            check = self.table.item(row, 0)
            key = self.table.item(row, 1)
            value = self.table.item(row, 2)
            text = value.text() if value else ""
            if self._masked and row in self._hidden_values:
                text = self._hidden_values[row]
            entry = {
                "enabled": check.checkState() == Qt.CheckState.Checked if check else True,
                "key": key.text() if key else "",
                "value": text,
            }
            if self._col_secret >= 0:
                entry["secret"] = self._is_secret_row(row)
            items.append(entry)
        return items

    def add_item(self, key: str, value: str = "", enabled: bool = True) -> None:
        """Добавить строку перед завершающей пустой и уведомить об изменении."""
        self._mutating = True
        try:
            row = max(0, self.table.rowCount() - 1)  # перед последней пустой строкой
            self._insert_row(row, enabled, key, value)
        finally:
            self._mutating = False
        self.changed.emit()

    def set_items(self, items: List[Dict[str, Any]]) -> None:
        """Заполнить таблицу из списка словарей."""
        self._mutating = True
        try:
            self.table.setRowCount(0)
            # Строки заменяются — прежние скрытые значения больше не актуальны.
            self._hidden_values = {}
            self._masked = False
            for it in items or []:
                self._insert_row(
                    self.table.rowCount(),
                    bool(it.get("enabled", True)),
                    str(it.get("key", "")),
                    str(it.get("value", "")),
                    secret=bool(it.get("secret", False)),
                )
            self._append_blank_row()
        finally:
            self._mutating = False
