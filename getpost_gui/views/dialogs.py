"""Диалоговые окна приложения."""
from __future__ import annotations

from typing import Dict, Optional

from .. import codegen, cookies, curl, diffing, http_client, models, share, theme
from ..qtcompat import QtCore, QtWidgets, Signal
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


class AuthEditor(QtWidgets.QWidget):
    """Переиспользуемый редактор авторизации (для запроса и для папки)."""

    changed = Signal()

    def __init__(self, allow_inherit: bool = True, parent=None):
        super().__init__(parent)
        self._loading = False

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        row = QtWidgets.QHBoxLayout()
        self.type_combo = QtWidgets.QComboBox()
        self.type_combo.addItem("No Auth", models.AUTH_NONE)
        if allow_inherit:
            self.type_combo.addItem("Наследовать от папки", models.AUTH_INHERIT)
        self.type_combo.addItem("Basic Auth", models.AUTH_BASIC)
        self.type_combo.addItem("Bearer Token", models.AUTH_BEARER)
        self.type_combo.addItem("API Key", models.AUTH_API_KEY)
        self.type_combo.addItem("OAuth 2.0 (client credentials)", models.AUTH_OAUTH2_CC)
        self.type_combo.currentIndexChanged.connect(self._on_type_changed)
        row.addWidget(QtWidgets.QLabel("Тип:"))
        row.addWidget(self.type_combo)
        row.addStretch(1)
        layout.addLayout(row)

        self.stack = QtWidgets.QStackedWidget()
        self.stack.addWidget(self._hint("Авторизация не используется."))          # none
        if allow_inherit:
            self.stack.addWidget(self._hint("Берётся из настроек папки."))        # inherit
        self.stack.addWidget(self._build_basic())                                  # basic
        self.stack.addWidget(self._build_bearer())                                 # bearer
        self.stack.addWidget(self._build_api_key())                                # apikey
        self.stack.addWidget(self._build_oauth())                                  # oauth2
        layout.addWidget(self.stack, 1)
        layout.addStretch(0)

        self._pages = {models.AUTH_NONE: 0}
        index = 1
        if allow_inherit:
            self._pages[models.AUTH_INHERIT] = index
            index += 1
        for auth_type in (models.AUTH_BASIC, models.AUTH_BEARER,
                          models.AUTH_API_KEY, models.AUTH_OAUTH2_CC):
            self._pages[auth_type] = index
            index += 1

    @staticmethod
    def _hint(text: str) -> QtWidgets.QWidget:
        label = QtWidgets.QLabel(text)
        label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        label.setStyleSheet("color: #868e96;")
        return label

    def _build_basic(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget()
        form = QtWidgets.QFormLayout(page)
        self.basic_user = QtWidgets.QLineEdit()
        self.basic_pass = QtWidgets.QLineEdit()
        self.basic_pass.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)
        self.show_pass = QtWidgets.QCheckBox("Показать пароль")
        self.show_pass.toggled.connect(
            lambda on: self.basic_pass.setEchoMode(
                QtWidgets.QLineEdit.EchoMode.Normal if on
                else QtWidgets.QLineEdit.EchoMode.Password
            )
        )
        for widget in (self.basic_user, self.basic_pass):
            widget.textChanged.connect(self._emit_changed)
        form.addRow("Логин:", self.basic_user)
        form.addRow("Пароль:", self.basic_pass)
        form.addRow("", self.show_pass)
        return page

    def _build_bearer(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget()
        form = QtWidgets.QFormLayout(page)
        self.bearer_token = QtWidgets.QLineEdit()
        self.bearer_token.setPlaceholderText("Токен (можно {{token}})")
        self.bearer_token.textChanged.connect(self._emit_changed)
        form.addRow("Token:", self.bearer_token)
        return page

    def _build_api_key(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget()
        form = QtWidgets.QFormLayout(page)
        self.api_key_name = QtWidgets.QLineEdit()
        self.api_key_name.setPlaceholderText("Например, X-API-Key или api_key")
        self.api_key_value = QtWidgets.QLineEdit()
        self.api_key_value.setPlaceholderText("Значение (можно {{api_key}})")
        self.api_key_location = QtWidgets.QComboBox()
        self.api_key_location.addItem("В заголовок", models.APIKEY_IN_HEADER)
        self.api_key_location.addItem("В query-параметры", models.APIKEY_IN_QUERY)
        for widget in (self.api_key_name, self.api_key_value):
            widget.textChanged.connect(self._emit_changed)
        self.api_key_location.currentIndexChanged.connect(self._emit_changed)
        form.addRow("Имя:", self.api_key_name)
        form.addRow("Значение:", self.api_key_value)
        form.addRow("Куда:", self.api_key_location)
        return page

    def _build_oauth(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget()
        form = QtWidgets.QFormLayout(page)
        self.oauth_token_url = QtWidgets.QLineEdit()
        self.oauth_token_url.setPlaceholderText("https://auth.example.com/oauth/token")
        self.oauth_client_id = QtWidgets.QLineEdit()
        self.oauth_client_secret = QtWidgets.QLineEdit()
        self.oauth_client_secret.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)
        self.oauth_scope = QtWidgets.QLineEdit()
        self.oauth_scope.setPlaceholderText("необязательно, через пробел")
        self.oauth_send_as = QtWidgets.QComboBox()
        self.oauth_send_as.addItem("В теле запроса", models.OAUTH_SEND_BODY)
        self.oauth_send_as.addItem("Basic-заголовком", models.OAUTH_SEND_BASIC)
        for widget in (self.oauth_token_url, self.oauth_client_id,
                       self.oauth_client_secret, self.oauth_scope):
            widget.textChanged.connect(self._emit_changed)
        self.oauth_send_as.currentIndexChanged.connect(self._emit_changed)
        form.addRow("Token URL:", self.oauth_token_url)
        form.addRow("Client ID:", self.oauth_client_id)
        form.addRow("Client Secret:", self.oauth_client_secret)
        form.addRow("Scope:", self.oauth_scope)
        form.addRow("Учётные данные:", self.oauth_send_as)
        note = QtWidgets.QLabel(
            "Токен запрашивается перед отправкой и кэшируется до истечения срока."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #868e96;")
        form.addRow("", note)
        return page

    # -- обмен с моделью ----------------------------------------------------
    def _emit_changed(self, *_args) -> None:
        if not self._loading:
            self.changed.emit()

    def _on_type_changed(self, *_args) -> None:
        self.stack.setCurrentIndex(self._pages.get(self.type_combo.currentData(), 0))
        self._emit_changed()

    def load(self, obj) -> None:
        """Заполнить поля из объекта (запрос или папка)."""
        self._loading = True
        try:
            index = self.type_combo.findData(obj.auth_type)
            self.type_combo.setCurrentIndex(index if index >= 0 else 0)
            self.basic_user.setText(obj.auth_basic_username)
            self.basic_pass.setText(obj.auth_basic_password)
            self.bearer_token.setText(obj.auth_bearer_token)
            self.api_key_name.setText(obj.auth_api_key_name)
            self.api_key_value.setText(obj.auth_api_key_value)
            loc = self.api_key_location.findData(obj.auth_api_key_location)
            self.api_key_location.setCurrentIndex(loc if loc >= 0 else 0)
            self.oauth_token_url.setText(obj.auth_oauth2_token_url)
            self.oauth_client_id.setText(obj.auth_oauth2_client_id)
            self.oauth_client_secret.setText(obj.auth_oauth2_client_secret)
            self.oauth_scope.setText(obj.auth_oauth2_scope)
            send = self.oauth_send_as.findData(obj.auth_oauth2_send_as)
            self.oauth_send_as.setCurrentIndex(send if send >= 0 else 0)
            self.stack.setCurrentIndex(self._pages.get(obj.auth_type, 0))
        finally:
            self._loading = False

    def store(self, obj) -> None:
        """Записать поля в объект (запрос или папка)."""
        obj.auth_type = self.type_combo.currentData()
        obj.auth_basic_username = self.basic_user.text()
        obj.auth_basic_password = self.basic_pass.text()
        obj.auth_bearer_token = self.bearer_token.text()
        obj.auth_api_key_name = self.api_key_name.text()
        obj.auth_api_key_value = self.api_key_value.text()
        obj.auth_api_key_location = self.api_key_location.currentData()
        obj.auth_oauth2_token_url = self.oauth_token_url.text()
        obj.auth_oauth2_client_id = self.oauth_client_id.text()
        obj.auth_oauth2_client_secret = self.oauth_client_secret.text()
        obj.auth_oauth2_scope = self.oauth_scope.text()
        obj.auth_oauth2_send_as = self.oauth_send_as.currentData()


class FolderSettingsDialog(QtWidgets.QDialog):
    """Общие настройки папки: базовый URL, заголовки, авторизация."""

    def __init__(self, folder: models.Folder, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Настройки папки «{folder.name}»")
        self.resize(620, 520)
        self._folder = folder

        layout = QtWidgets.QVBoxLayout(self)
        info = QtWidgets.QLabel(
            "Эти настройки применяются ко всем запросам внутри папки. Запрос может "
            "переопределить любой заголовок, а для авторизации должен быть выбран "
            "тип «Наследовать от папки»."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        url_row = QtWidgets.QHBoxLayout()
        url_row.addWidget(QtWidgets.QLabel("Базовый URL:"))
        self.base_url = QtWidgets.QLineEdit(folder.base_url)
        self.base_url.setPlaceholderText("https://api.example.com/v1  (можно {{base_url}})")
        url_row.addWidget(self.base_url, 1)
        layout.addLayout(url_row)
        hint = QtWidgets.QLabel(
            "Добавляется к запросам, чей URL не начинается с http:// или https://."
        )
        hint.setStyleSheet("color: #868e96;")
        layout.addWidget(hint)

        tabs = QtWidgets.QTabWidget()
        self.headers_table = KeyValueTable("Заголовок", "Значение")
        self.headers_table.set_items(folder.headers)
        tabs.addTab(self.headers_table, "Общие заголовки")

        self.auth_editor = AuthEditor(allow_inherit=False)
        self.auth_editor.load(folder)
        auth_page = QtWidgets.QWidget()
        auth_layout = QtWidgets.QVBoxLayout(auth_page)
        auth_layout.addWidget(self.auth_editor)
        tabs.addTab(auth_page, "Авторизация")
        layout.addWidget(tabs, 1)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def apply_to(self, folder: models.Folder) -> None:
        """Записать введённые настройки в папку."""
        folder.base_url = self.base_url.text().strip()
        folder.headers = self.headers_table.get_items()
        self.auth_editor.store(folder)


class DiffDialog(QtWidgets.QDialog):
    """Сравнение двух ответов из истории."""

    def __init__(self, older, newer, index: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Сравнение ответов #{index} и #{index + 1}")
        self.resize(760, 560)

        layout = QtWidgets.QVBoxLayout(self)
        self.view = QtWidgets.QPlainTextEdit()
        self.view.setReadOnly(True)
        self.view.setFont(monospace_font())
        self.view.setLineWrapMode(QtWidgets.QPlainTextEdit.LineWrapMode.NoWrap)
        self.view.setPlainText(diffing.compare(older, newer))
        layout.addWidget(self.view, 1)

        row = QtWidgets.QHBoxLayout()
        row.addStretch(1)
        copy_btn = QtWidgets.QPushButton("Копировать")
        copy_btn.clicked.connect(
            lambda: QtWidgets.QApplication.clipboard().setText(self.view.toPlainText())
        )
        close_btn = QtWidgets.QPushButton("Закрыть")
        close_btn.clicked.connect(self.accept)
        row.addWidget(copy_btn)
        row.addWidget(close_btn)
        layout.addLayout(row)


class CookiesDialog(QtWidgets.QDialog):
    """Просмотр и удаление cookies текущей сессии."""

    def __init__(self, session, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Cookies")
        self.resize(680, 420)
        self._session = session

        layout = QtWidgets.QVBoxLayout(self)
        self.summary = QtWidgets.QLabel("")
        layout.addWidget(self.summary)

        self.table = QtWidgets.QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Имя", "Значение", "Домен", "Путь"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows
        )
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.table, 1)

        row = QtWidgets.QHBoxLayout()
        delete_btn = QtWidgets.QPushButton("Удалить выбранную")
        delete_btn.clicked.connect(self._delete_selected)
        clear_btn = QtWidgets.QPushButton("Удалить все")
        clear_btn.clicked.connect(self._clear_all)
        row.addWidget(delete_btn)
        row.addWidget(clear_btn)
        row.addStretch(1)
        close_btn = QtWidgets.QPushButton("Закрыть")
        close_btn.clicked.connect(self.accept)
        row.addWidget(close_btn)
        layout.addLayout(row)

        self._reload()

    def _reload(self) -> None:
        self.table.setRowCount(0)
        for item in cookies.export_jar(self._session):
            row = self.table.rowCount()
            self.table.insertRow(row)
            for col, key in enumerate(("name", "value", "domain", "path")):
                self.table.setItem(row, col, QtWidgets.QTableWidgetItem(str(item.get(key, ""))))
        self.summary.setText(cookies.summary(self._session))

    def _delete_selected(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            return
        name = self.table.item(row, 0).text()
        domain = self.table.item(row, 2).text()
        path = self.table.item(row, 3).text() or "/"
        cookies.remove(self._session, name, domain, path)
        self._reload()

    def _clear_all(self) -> None:
        cookies.clear(self._session)
        self._reload()


class SettingsDialog(QtWidgets.QDialog):
    """Глобальные настройки приложения."""

    def __init__(self, settings: Dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Настройки")
        self.resize(520, 340)

        layout = QtWidgets.QVBoxLayout(self)
        form = QtWidgets.QFormLayout()

        self.theme_combo = QtWidgets.QComboBox()
        for key, title in theme.THEMES:
            self.theme_combo.addItem(title, key)
        index = self.theme_combo.findData(settings.get("theme", theme.THEME_LIGHT))
        self.theme_combo.setCurrentIndex(index if index >= 0 else 0)
        form.addRow("Тема:", self.theme_combo)

        self.timeout_spin = QtWidgets.QDoubleSpinBox()
        self.timeout_spin.setRange(1.0, 3600.0)
        self.timeout_spin.setDecimals(0)
        self.timeout_spin.setValue(float(settings.get("timeout", http_client.DEFAULT_TIMEOUT)))
        form.addRow("Тайм-аут по умолчанию (с):", self.timeout_spin)

        self.max_mb_spin = QtWidgets.QDoubleSpinBox()
        self.max_mb_spin.setRange(0.1, 512.0)
        self.max_mb_spin.setDecimals(1)
        self.max_mb_spin.setValue(
            float(settings.get("max_response_mb", http_client.MAX_RESPONSE_BYTES / (1024 * 1024)))
        )
        form.addRow("Максимальный размер ответа (МБ):", self.max_mb_spin)

        self.history_spin = QtWidgets.QSpinBox()
        self.history_spin.setRange(1, 100)
        self.history_spin.setValue(int(settings.get("history_per_request", 10)))
        form.addRow("Ответов в истории на запрос:", self.history_spin)

        self.proxy_edit = QtWidgets.QLineEdit(settings.get("proxy", ""))
        self.proxy_edit.setPlaceholderText("http://proxy.local:3128 (пусто — без прокси)")
        form.addRow("Прокси:", self.proxy_edit)

        self.cookies_check = QtWidgets.QCheckBox("Сохранять cookies между запусками")
        self.cookies_check.setChecked(bool(settings.get("persist_cookies", True)))
        form.addRow("", self.cookies_check)

        layout.addLayout(form)
        note = QtWidgets.QLabel("Смена темы применяется сразу.")
        note.setStyleSheet("color: #868e96;")
        layout.addWidget(note)
        layout.addStretch(1)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def values(self) -> Dict:
        return {
            "theme": self.theme_combo.currentData(),
            "timeout": self.timeout_spin.value(),
            "max_response_mb": self.max_mb_spin.value(),
            "history_per_request": self.history_spin.value(),
            "proxy": self.proxy_edit.text().strip(),
            "persist_cookies": self.cookies_check.isChecked(),
        }


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
