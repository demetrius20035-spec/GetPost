"""Переиспользуемые виджеты.

``KeyValueTable`` — редактируемая таблица пар «ключ-значение» с флажком
включения и кнопкой удаления для каждой строки. Последняя строка всегда
пустая: как только пользователь начинает её заполнять, автоматически
добавляется новая пустая строка (поведение, привычное по Postman).
"""
from __future__ import annotations

from typing import Any, Dict, List

from ..qtcompat import Qt, QtGui, QtWidgets, Signal


def monospace_font() -> QtGui.QFont:
    """Системный моноширинный шрифт (для редакторов тела запроса/ответа)."""
    font = QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.SystemFont.FixedFont)
    font.setPointSize(max(10, font.pointSize()))
    return font


class KeyValueTable(QtWidgets.QWidget):
    """Таблица пар ключ-значение с автодобавлением пустой строки."""

    changed = Signal()

    def __init__(self, key_label: str = "Key", value_label: str = "Value", parent=None):
        super().__init__(parent)
        self._mutating = False

        self.table = QtWidgets.QTableWidget(0, 4, self)
        self.table.setHorizontalHeaderLabels(["", key_label, value_label, ""])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.NoSelection)
        self.table.setEditTriggers(
            QtWidgets.QAbstractItemView.EditTrigger.DoubleClicked
            | QtWidgets.QAbstractItemView.EditTrigger.SelectedClicked
            | QtWidgets.QAbstractItemView.EditTrigger.AnyKeyPressed
            | QtWidgets.QAbstractItemView.EditTrigger.EditKeyPressed
        )

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.table)

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

    def _insert_row(self, row: int, enabled: bool, key: str, value: str) -> None:
        self.table.insertRow(row)
        self.table.setItem(row, 0, self._make_check_item(enabled))
        self.table.setItem(row, 1, self._make_text_item(key))
        self.table.setItem(row, 2, self._make_text_item(value))

        btn = QtWidgets.QToolButton(self.table)
        btn.setText("✕")  # ✕
        btn.setAutoRaise(True)
        btn.setToolTip("Удалить строку")
        btn.clicked.connect(lambda: self._remove_button_row(btn))
        self.table.setCellWidget(row, 3, btn)

    def _append_blank_row(self) -> None:
        self._insert_row(self.table.rowCount(), True, "", "")

    # -- реакции на изменения ----------------------------------------------
    def _remove_button_row(self, btn: QtWidgets.QToolButton) -> None:
        for row in range(self.table.rowCount()):
            if self.table.cellWidget(row, 3) is btn:
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

    # -- публичный API ------------------------------------------------------
    def get_items(self) -> List[Dict[str, Any]]:
        """Вернуть непустые строки в виде списка словарей."""
        items: List[Dict[str, Any]] = []
        for row in range(self.table.rowCount()):
            if self._row_is_empty(row):
                continue
            check = self.table.item(row, 0)
            key = self.table.item(row, 1)
            value = self.table.item(row, 2)
            items.append(
                {
                    "enabled": check.checkState() == Qt.CheckState.Checked if check else True,
                    "key": key.text() if key else "",
                    "value": value.text() if value else "",
                }
            )
        return items

    def set_items(self, items: List[Dict[str, Any]]) -> None:
        """Заполнить таблицу из списка словарей."""
        self._mutating = True
        try:
            self.table.setRowCount(0)
            for it in items or []:
                self._insert_row(
                    self.table.rowCount(),
                    bool(it.get("enabled", True)),
                    str(it.get("key", "")),
                    str(it.get("value", "")),
                )
            self._append_blank_row()
        finally:
            self._mutating = False
