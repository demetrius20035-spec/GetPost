"""Диалоговые окна приложения."""
from __future__ import annotations

from typing import Dict, Optional

from .. import codegen, curl, models, share
from ..qtcompat import QtCore, QtWidgets
from .widgets import KeyValueTable, monospace_font


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
        self._secrets: set = set(ws.secret_vars)

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
            "параметрах и теле. Активное окружение помечено значком ★. Секретные "
            "значения не попадают в экспорт."
        )
        info.setWordWrap(True)
        right.addWidget(info)

        self.table = KeyValueTable("Переменная", "Значение", secret_column=True)
        right.addWidget(self.table, 1)

        mask_row = QtWidgets.QHBoxLayout()
        self.mask_check = QtWidgets.QCheckBox("Скрывать секретные значения")
        self.mask_check.setChecked(True)
        self.mask_check.toggled.connect(self._apply_mask)
        mask_row.addWidget(self.mask_check)
        mask_row.addStretch(1)
        right.addLayout(mask_row)
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
            items = [
                {
                    "enabled": True,
                    "key": k,
                    "value": v,
                    # Помечаем как секрет вручную отмеченные и «похожие» имена.
                    "secret": k in self._secrets or share.looks_secret(k),
                }
                for k, v in self._envs[name].items()
            ]
            self.table.set_items(items)
            self._apply_mask(self.mask_check.isChecked())

    def _apply_mask(self, mask: bool) -> None:
        self.table.set_secret_masked(mask)

    def _save_current(self) -> None:
        if self._current is not None and self._current in self._envs:
            self._envs[self._current] = _table_to_dict(self.table)
            # Обновляем набор секретных имён по галочкам таблицы.
            for it in self.table.get_items():
                key = str(it.get("key", "")).strip()
                if not key:
                    continue
                if it.get("secret"):
                    self._secrets.add(key)
                else:
                    self._secrets.discard(key)

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

    def secret_vars(self) -> list:
        return sorted(self._secrets)


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


class CodeExportDialog(QtWidgets.QDialog):
    """Генерация кода запроса на разных языках с копированием в буфер."""

    def __init__(self, req: models.Request, variables: Dict[str, str],
                 language: str = codegen.LANG_CURL, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Сгенерировать код")
        self.resize(680, 420)
        self._req = req
        self._variables = variables or {}

        layout = QtWidgets.QVBoxLayout(self)

        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("Язык:"))
        self.lang_combo = QtWidgets.QComboBox()
        for key, title in codegen.LANGUAGES:
            self.lang_combo.addItem(title, key)
        idx = self.lang_combo.findData(language)
        if idx >= 0:
            self.lang_combo.setCurrentIndex(idx)
        self.lang_combo.currentIndexChanged.connect(self._render)
        row.addWidget(self.lang_combo)
        row.addStretch(1)
        self.secret_note = QtWidgets.QLabel("Код может содержать токены — не публикуйте как есть.")
        self.secret_note.setStyleSheet("color: #b26a00;")
        row.addWidget(self.secret_note)
        layout.addLayout(row)

        self.edit = QtWidgets.QPlainTextEdit()
        self.edit.setReadOnly(True)
        self.edit.setFont(monospace_font())
        self.edit.setLineWrapMode(QtWidgets.QPlainTextEdit.LineWrapMode.NoWrap)
        layout.addWidget(self.edit, 1)

        buttons = QtWidgets.QHBoxLayout()
        buttons.addStretch(1)
        copy_btn = QtWidgets.QPushButton("Копировать")
        copy_btn.clicked.connect(self._copy)
        save_btn = QtWidgets.QPushButton("Сохранить…")
        save_btn.clicked.connect(self._save)
        close_btn = QtWidgets.QPushButton("Закрыть")
        close_btn.clicked.connect(self.accept)
        buttons.addWidget(copy_btn)
        buttons.addWidget(save_btn)
        buttons.addWidget(close_btn)
        layout.addLayout(buttons)

        self._render()

    def _render(self) -> None:
        language = self.lang_combo.currentData()
        try:
            code = codegen.generate(language, self._req, self._variables)
        except Exception as exc:  # noqa: BLE001 - показываем пользователю
            code = f"# Не удалось сгенерировать код: {exc}"
        self.edit.setPlainText(code)

    def _copy(self) -> None:
        QtWidgets.QApplication.clipboard().setText(self.edit.toPlainText())

    def _save(self) -> None:
        extensions = {
            codegen.LANG_PYTHON: "request.py",
            codegen.LANG_JS: "request.js",
            codegen.LANG_HTTPIE: "request.sh",
            codegen.LANG_CURL: "request.sh",
        }
        default = extensions.get(self.lang_combo.currentData(), "request.txt")
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Сохранить код", default)
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(self.edit.toPlainText())
        except OSError as exc:
            QtWidgets.QMessageBox.warning(self, "Сохранение", f"Не удалось сохранить файл:\n{exc}")


class QuickOpenDialog(QtWidgets.QDialog):
    """Быстрый переход к запросу: поиск по имени, пути и URL (Ctrl+P)."""

    def __init__(self, items, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Быстрый переход")
        self.resize(560, 420)
        self._items = list(items)  # [(path, request), ...]

        layout = QtWidgets.QVBoxLayout(self)
        self.search = QtWidgets.QLineEdit()
        self.search.setPlaceholderText("Начните вводить имя, путь или URL…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._refilter)
        layout.addWidget(self.search)

        self.list = QtWidgets.QListWidget()
        self.list.itemActivated.connect(lambda _: self.accept())
        self.list.itemDoubleClicked.connect(lambda _: self.accept())
        layout.addWidget(self.list, 1)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Open
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        # Стрелки из поля поиска управляют списком.
        self.search.installEventFilter(self)
        self._refilter("")

    def eventFilter(self, obj, event):  # noqa: N802 - имя задано Qt
        if obj is self.search and event.type() == QtCore.QEvent.Type.KeyPress:
            key = event.key()
            if key in (QtCore.Qt.Key.Key_Down, QtCore.Qt.Key.Key_Up):
                row = self.list.currentRow()
                self.list.setCurrentRow(max(0, row + (1 if key == QtCore.Qt.Key.Key_Down else -1)))
                return True
        return super().eventFilter(obj, event)

    @staticmethod
    def _matches(query: str, text: str) -> bool:
        """Нестрогое совпадение: символы запроса идут в тексте по порядку."""
        text = text.lower()
        position = 0
        for char in query.lower():
            position = text.find(char, position)
            if position < 0:
                return False
            position += 1
        return True

    def _refilter(self, query: str) -> None:
        query = (query or "").strip()
        self.list.clear()
        for path, req in self._items:
            haystack = f"{path} {req.method} {req.url}"
            if query and not self._matches(query, haystack):
                continue
            item = QtWidgets.QListWidgetItem(f"{req.method:6} {path}    {req.url}")
            item.setData(QtCore.Qt.ItemDataRole.UserRole, req)
            self.list.addItem(item)
        if self.list.count():
            self.list.setCurrentRow(0)

    def selected_request(self):
        item = self.list.currentItem()
        return item.data(QtCore.Qt.ItemDataRole.UserRole) if item is not None else None
