"""Диалоговые окна приложения."""
from __future__ import annotations

from typing import Dict, Optional

from .. import curl, models
from ..qtcompat import QtWidgets
from .widgets import KeyValueTable


def _table_to_dict(table: KeyValueTable) -> Dict[str, str]:
    result: Dict[str, str] = {}
    for it in table.get_items():
        key = str(it.get("key", "")).strip()
        if key and it.get("enabled", True):
            result[key] = str(it.get("value", ""))
    return result


class EnvironmentsDialog(QtWidgets.QDialog):
    """Управление окружениями Workspace и их переменными."""

    def __init__(self, ws: models.Workspace, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Окружения и переменные")
        self.resize(620, 420)

        # Рабочие копии (применяются только при OK).
        self._envs: Dict[str, Dict[str, str]] = {n: dict(v) for n, v in ws.environments.items()}
        self._active: str = ws.active_env
        self._current: Optional[str] = None

        main = QtWidgets.QHBoxLayout(self)

        # Левая колонка — список окружений.
        left = QtWidgets.QVBoxLayout()
        self.env_list = QtWidgets.QListWidget()
        self.env_list.currentRowChanged.connect(self._on_env_selected)
        left.addWidget(self.env_list, 1)

        btns = QtWidgets.QHBoxLayout()
        for text, slot in (("+", self._add), ("Имя", self._rename), ("−", self._delete)):
            b = QtWidgets.QToolButton()
            b.setText(text)
            b.clicked.connect(slot)
            btns.addWidget(b)
        self.active_btn = QtWidgets.QToolButton()
        self.active_btn.setText("★ Активное")
        self.active_btn.setToolTip("Сделать выбранное окружение активным")
        self.active_btn.clicked.connect(self._make_active)
        btns.addWidget(self.active_btn)
        btns.addStretch(1)
        left.addLayout(btns)
        main.addLayout(left, 1)

        # Правая колонка — переменные выбранного окружения.
        right = QtWidgets.QVBoxLayout()
        info = QtWidgets.QLabel(
            "Переменные используются как <code>{{имя}}</code> в URL, заголовках, "
            "параметрах и теле. Активное окружение помечено значком ★."
        )
        info.setWordWrap(True)
        right.addWidget(info)
        self.table = KeyValueTable("Переменная", "Значение")
        right.addWidget(self.table, 1)
        main.addLayout(right, 2)

        # Кнопки OK/Cancel — справа снизу.
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        right.addWidget(buttons)

        self._reload_list(select=self._active)

    # -- список окружений ---------------------------------------------------
    def _reload_list(self, select: Optional[str] = None) -> None:
        self.env_list.blockSignals(True)
        self.env_list.clear()
        for name in self._envs:
            label = ("★ " if name == self._active else "    ") + name
            self.env_list.addItem(label)
        self.env_list.blockSignals(False)
        names = list(self._envs)
        idx = names.index(select) if select in names else 0
        self.env_list.setCurrentRow(idx)

    def _name_at(self, row: int) -> Optional[str]:
        names = list(self._envs)
        return names[row] if 0 <= row < len(names) else None

    def _on_env_selected(self, row: int) -> None:
        self._save_current()
        name = self._name_at(row)
        self._current = name
        if name is not None:
            items = [{"enabled": True, "key": k, "value": v} for k, v in self._envs[name].items()]
            self.table.set_items(items)

    def _save_current(self) -> None:
        if self._current is not None and self._current in self._envs:
            self._envs[self._current] = _table_to_dict(self.table)

    # -- действия -----------------------------------------------------------
    def _add(self) -> None:
        name, ok = QtWidgets.QInputDialog.getText(self, "Новое окружение", "Название:")
        name = name.strip()
        if ok and name and name not in self._envs:
            self._save_current()
            self._envs[name] = {}
            self._reload_list(select=name)

    def _rename(self) -> None:
        old = self._name_at(self.env_list.currentRow())
        if not old:
            return
        name, ok = QtWidgets.QInputDialog.getText(self, "Переименовать окружение", "Название:", text=old)
        name = name.strip()
        if ok and name and name not in self._envs:
            self._save_current()
            self._envs = {(name if k == old else k): v for k, v in self._envs.items()}
            if self._active == old:
                self._active = name
            self._current = name
            self._reload_list(select=name)

    def _delete(self) -> None:
        name = self._name_at(self.env_list.currentRow())
        if not name or len(self._envs) <= 1:
            QtWidgets.QMessageBox.information(self, "Окружения", "Должно остаться хотя бы одно окружение.")
            return
        del self._envs[name]
        if self._active == name:
            self._active = next(iter(self._envs))
        self._current = None
        self._reload_list(select=self._active)

    def _make_active(self) -> None:
        name = self._name_at(self.env_list.currentRow())
        if name:
            self._active = name
            self._reload_list(select=name)

    def _accept(self) -> None:
        self._save_current()
        self.accept()

    # -- результат ----------------------------------------------------------
    def environments(self) -> Dict[str, Dict[str, str]]:
        return self._envs

    def active(self) -> str:
        return self._active


class ImportCurlDialog(QtWidgets.QDialog):
    """Импорт запроса из команды ``curl``."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Импорт из cURL")
        self.resize(560, 280)
        self._request: Optional[models.Request] = None

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(QtWidgets.QLabel("Вставьте команду curl:"))
        self.edit = QtWidgets.QPlainTextEdit()
        self.edit.setPlaceholderText("curl -X POST https://api.example.com/login -H 'Content-Type: application/json' -d '{\"u\":\"a\"}'")
        layout.addWidget(self.edit, 1)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Ok).setText("Импортировать")
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _accept(self) -> None:
        text = self.edit.toPlainText().strip()
        if not text:
            self.reject()
            return
        try:
            self._request = curl.from_curl(text)
        except Exception as exc:  # noqa: BLE001 - показываем пользователю
            QtWidgets.QMessageBox.warning(self, "Ошибка разбора", f"Не удалось разобрать команду:\n{exc}")
            return
        if not self._request.url:
            QtWidgets.QMessageBox.warning(self, "Импорт", "Не удалось определить URL в команде.")
            return
        self.accept()

    def request(self) -> Optional[models.Request]:
        return self._request


class CurlExportDialog(QtWidgets.QDialog):
    """Показ сгенерированной команды ``curl`` с кнопкой копирования."""

    def __init__(self, command: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Copy as cURL")
        self.resize(620, 240)
        layout = QtWidgets.QVBoxLayout(self)
        self.edit = QtWidgets.QPlainTextEdit()
        self.edit.setPlainText(command)
        self.edit.setReadOnly(True)
        layout.addWidget(self.edit, 1)

        row = QtWidgets.QHBoxLayout()
        row.addStretch(1)
        copy_btn = QtWidgets.QPushButton("Копировать")
        copy_btn.clicked.connect(self._copy)
        close_btn = QtWidgets.QPushButton("Закрыть")
        close_btn.clicked.connect(self.accept)
        row.addWidget(copy_btn)
        row.addWidget(close_btn)
        layout.addLayout(row)

    def _copy(self) -> None:
        QtWidgets.QApplication.clipboard().setText(self.edit.toPlainText())
