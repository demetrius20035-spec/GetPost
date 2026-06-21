"""Редактор запроса (центральная панель).

Содержит верхнюю строку (метод, URL, кнопка Send) и вкладки
«Params», «Headers», «Body», «Auth». Любое изменение немедленно
синхронизируется с моделью и сообщается наверх сигналом ``modified``,
что обеспечивает автосохранение.
"""
from __future__ import annotations

from typing import Optional

from .. import models
from ..highlighter import JsonHighlighter, XmlHighlighter
from ..qtcompat import Qt, QtWidgets, Signal
from .widgets import KeyValueTable, monospace_font


class RequestEditor(QtWidgets.QWidget):
    """Редактор одного HTTP-запроса."""

    send_requested = Signal()
    modified = Signal()
    name_changed = Signal(object)  # передаётся изменённый Request

    def __init__(self, parent=None):
        super().__init__(parent)
        self._req: Optional[models.Request] = None
        self._loading = False
        self._raw_highlighter = None

        self._build_ui()
        self._connect_signals()
        self.set_request(None)

    # -- построение интерфейса ---------------------------------------------
    def _build_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # Имя запроса
        self.name_edit = QtWidgets.QLineEdit()
        self.name_edit.setPlaceholderText("Название запроса")
        f = self.name_edit.font()
        f.setBold(True)
        self.name_edit.setFont(f)
        layout.addWidget(self.name_edit)

        # Строка: метод + URL + Send
        top = QtWidgets.QHBoxLayout()
        self.method_combo = QtWidgets.QComboBox()
        self.method_combo.addItems(models.HTTP_METHODS)
        self.method_combo.setMinimumWidth(90)

        self.url_edit = QtWidgets.QLineEdit()
        self.url_edit.setPlaceholderText("Введите URL (поддерживаются переменные {{base_url}})")
        self.url_edit.setClearButtonEnabled(True)

        self.send_btn = QtWidgets.QPushButton("Send")
        self.send_btn.setDefault(True)
        self.send_btn.setMinimumWidth(90)

        top.addWidget(self.method_combo)
        top.addWidget(self.url_edit, 1)
        top.addWidget(self.send_btn)
        layout.addLayout(top)

        # Вкладки
        self.tabs = QtWidgets.QTabWidget()
        self.params_table = KeyValueTable("Параметр", "Значение")
        self.headers_table = KeyValueTable("Заголовок", "Значение")
        self.tabs.addTab(self.params_table, "Params")
        self.tabs.addTab(self.headers_table, "Headers")
        self.tabs.addTab(self._build_body_tab(), "Body")
        self.tabs.addTab(self._build_auth_tab(), "Auth")
        self.tabs.addTab(self._build_options_tab(), "Options")
        layout.addWidget(self.tabs, 1)

    def _build_body_tab(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(page)
        v.setContentsMargins(6, 6, 6, 6)

        row = QtWidgets.QHBoxLayout()
        self.body_type_combo = QtWidgets.QComboBox()
        self.body_type_combo.addItem("None", models.BODY_NONE)
        self.body_type_combo.addItem("Raw", models.BODY_RAW)
        self.body_type_combo.addItem("Form-data", models.BODY_FORM_DATA)
        self.body_type_combo.addItem("x-www-form-urlencoded", models.BODY_URLENCODED)

        self.raw_lang_combo = QtWidgets.QComboBox()
        self.raw_lang_combo.addItem("JSON", models.RAW_JSON)
        self.raw_lang_combo.addItem("Text", models.RAW_TEXT)
        self.raw_lang_combo.addItem("XML", models.RAW_XML)

        row.addWidget(QtWidgets.QLabel("Тип тела:"))
        row.addWidget(self.body_type_combo)
        row.addSpacing(12)
        self.raw_lang_label = QtWidgets.QLabel("Формат:")
        row.addWidget(self.raw_lang_label)
        row.addWidget(self.raw_lang_combo)
        row.addStretch(1)
        v.addLayout(row)

        self.body_stack = QtWidgets.QStackedWidget()
        # 0: none
        none_page = QtWidgets.QLabel("У этого запроса нет тела.")
        none_page.setAlignment(Qt.AlignmentFlag.AlignCenter)
        none_page.setStyleSheet("color: #868e96;")
        self.body_stack.addWidget(none_page)
        # 1: raw
        self.raw_edit = QtWidgets.QPlainTextEdit()
        self.raw_edit.setFont(monospace_font())
        self.raw_edit.setPlaceholderText("Тело запроса…")
        self.body_stack.addWidget(self.raw_edit)
        # 2: form-data
        self.form_data_table = KeyValueTable("Поле", "Значение")
        self.body_stack.addWidget(self.form_data_table)
        # 3: urlencoded
        self.urlencoded_table = KeyValueTable("Поле", "Значение")
        self.body_stack.addWidget(self.urlencoded_table)

        v.addWidget(self.body_stack, 1)
        return page

    def _build_auth_tab(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(page)
        v.setContentsMargins(6, 6, 6, 6)

        row = QtWidgets.QHBoxLayout()
        self.auth_type_combo = QtWidgets.QComboBox()
        self.auth_type_combo.addItem("No Auth", models.AUTH_NONE)
        self.auth_type_combo.addItem("Basic Auth", models.AUTH_BASIC)
        self.auth_type_combo.addItem("Bearer Token", models.AUTH_BEARER)
        row.addWidget(QtWidgets.QLabel("Тип:"))
        row.addWidget(self.auth_type_combo)
        row.addStretch(1)
        v.addLayout(row)

        self.auth_stack = QtWidgets.QStackedWidget()
        # 0: none
        none_page = QtWidgets.QLabel("Авторизация не используется.")
        none_page.setAlignment(Qt.AlignmentFlag.AlignCenter)
        none_page.setStyleSheet("color: #868e96;")
        self.auth_stack.addWidget(none_page)

        # 1: basic
        basic_page = QtWidgets.QWidget()
        form = QtWidgets.QFormLayout(basic_page)
        self.basic_user_edit = QtWidgets.QLineEdit()
        self.basic_pass_edit = QtWidgets.QLineEdit()
        self.basic_pass_edit.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)
        self.show_pass_check = QtWidgets.QCheckBox("Показать пароль")
        form.addRow("Логин:", self.basic_user_edit)
        form.addRow("Пароль:", self.basic_pass_edit)
        form.addRow("", self.show_pass_check)
        self.auth_stack.addWidget(basic_page)

        # 2: bearer
        bearer_page = QtWidgets.QWidget()
        bform = QtWidgets.QFormLayout(bearer_page)
        self.bearer_token_edit = QtWidgets.QLineEdit()
        self.bearer_token_edit.setPlaceholderText("Токен")
        bform.addRow("Token:", self.bearer_token_edit)
        self.auth_stack.addWidget(bearer_page)

        v.addWidget(self.auth_stack, 1)
        v.addStretch(1)
        return page

    def _build_options_tab(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(page)
        v.setContentsMargins(8, 8, 8, 8)

        self.follow_check = QtWidgets.QCheckBox("Следовать редиректам")
        self.follow_check.setChecked(True)
        self.verify_check = QtWidgets.QCheckBox("Проверять TLS-сертификат")
        self.verify_check.setChecked(True)
        v.addWidget(self.follow_check)
        v.addWidget(self.verify_check)

        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("Тайм-аут (с):"))
        self.timeout_spin = QtWidgets.QDoubleSpinBox()
        self.timeout_spin.setRange(0.0, 3600.0)
        self.timeout_spin.setDecimals(1)
        self.timeout_spin.setSingleStep(1.0)
        self.timeout_spin.setSpecialValueText("по умолчанию")  # отображается при 0
        self.timeout_spin.setToolTip("0 — использовать глобальный тайм-аут")
        row.addWidget(self.timeout_spin)
        row.addStretch(1)
        v.addLayout(row)
        v.addStretch(1)
        return page

    # -- сигналы ------------------------------------------------------------
    def _connect_signals(self) -> None:
        self.send_btn.clicked.connect(self.send_requested.emit)
        self.url_edit.returnPressed.connect(self.send_requested.emit)

        self.name_edit.textEdited.connect(self._on_name_edited)
        self.method_combo.currentIndexChanged.connect(self._on_changed)
        # textEdited — только пользовательский ввод (программный setText не триггерит),
        # что важно для синхронизации URL ↔ Params без зацикливания.
        self.url_edit.textEdited.connect(self._on_url_edited)

        self.params_table.changed.connect(self._on_params_changed)
        self.headers_table.changed.connect(self._on_changed)

        self.follow_check.toggled.connect(self._on_changed)
        self.verify_check.toggled.connect(self._on_changed)
        self.timeout_spin.valueChanged.connect(self._on_changed)

        self.body_type_combo.currentIndexChanged.connect(self._on_body_type_changed)
        self.raw_lang_combo.currentIndexChanged.connect(self._on_raw_lang_changed)
        self.raw_edit.textChanged.connect(self._on_changed)
        self.form_data_table.changed.connect(self._on_changed)
        self.urlencoded_table.changed.connect(self._on_changed)

        self.auth_type_combo.currentIndexChanged.connect(self._on_auth_type_changed)
        self.basic_user_edit.textChanged.connect(self._on_changed)
        self.basic_pass_edit.textChanged.connect(self._on_changed)
        self.bearer_token_edit.textChanged.connect(self._on_changed)
        self.show_pass_check.toggled.connect(self._on_show_pass_toggled)

    # -- загрузка / выгрузка модели ----------------------------------------
    def set_request(self, req: Optional[models.Request]) -> None:
        """Загрузить запрос в редактор (или очистить, если ``None``)."""
        self._req = req
        self._loading = True
        try:
            has = req is not None
            self.setEnabled(has)
            if not has:
                self.name_edit.clear()
                self.url_edit.clear()
                self.method_combo.setCurrentIndex(0)
                self.params_table.set_items([])
                self.headers_table.set_items([])
                self.raw_edit.setPlainText("")
                self.form_data_table.set_items([])
                self.urlencoded_table.set_items([])
                self.body_type_combo.setCurrentIndex(0)
                self.auth_type_combo.setCurrentIndex(0)
                self.follow_check.setChecked(True)
                self.verify_check.setChecked(True)
                self.timeout_spin.setValue(0.0)
                return

            self.name_edit.setText(req.name)
            idx = self.method_combo.findText(req.method)
            self.method_combo.setCurrentIndex(idx if idx >= 0 else 0)
            self.url_edit.setText(req.url)
            self.params_table.set_items(req.params)
            self.headers_table.set_items(req.headers)

            self._set_combo_data(self.body_type_combo, req.body_type)
            self._set_combo_data(self.raw_lang_combo, req.body_raw_lang)
            self.raw_edit.setPlainText(req.body_raw)
            self.form_data_table.set_items(req.body_form)
            self.urlencoded_table.set_items(req.body_form)
            self._update_body_stack()
            self._apply_raw_highlighter()

            self._set_combo_data(self.auth_type_combo, req.auth_type)
            self.basic_user_edit.setText(req.auth_basic_username)
            self.basic_pass_edit.setText(req.auth_basic_password)
            self.bearer_token_edit.setText(req.auth_bearer_token)
            self._update_auth_stack()

            self.follow_check.setChecked(req.follow_redirects)
            self.verify_check.setChecked(req.verify_ssl)
            self.timeout_spin.setValue(req.timeout or 0.0)
        finally:
            self._loading = False

    def current_request(self) -> Optional[models.Request]:
        return self._req

    def update_name_display(self) -> None:
        """Обновить поле имени из модели (без повторной отправки сигналов)."""
        if self._req is None:
            return
        self._loading = True
        try:
            self.name_edit.setText(self._req.name)
        finally:
            self._loading = False

    @staticmethod
    def _set_combo_data(combo: QtWidgets.QComboBox, data) -> None:
        idx = combo.findData(data)
        combo.setCurrentIndex(idx if idx >= 0 else 0)

    def _sync_to_model(self) -> None:
        """Записать состояние интерфейса в модель."""
        if self._req is None:
            return
        r = self._req
        r.method = self.method_combo.currentText()
        r.url = self.url_edit.text()
        r.params = self.params_table.get_items()
        r.headers = self.headers_table.get_items()

        r.body_type = self.body_type_combo.currentData()
        r.body_raw = self.raw_edit.toPlainText()
        r.body_raw_lang = self.raw_lang_combo.currentData()
        # form-data и urlencoded используют одно поле модели — берём активное.
        if r.body_type == models.BODY_URLENCODED:
            r.body_form = self.urlencoded_table.get_items()
        elif r.body_type == models.BODY_FORM_DATA:
            r.body_form = self.form_data_table.get_items()

        r.auth_type = self.auth_type_combo.currentData()
        r.auth_basic_username = self.basic_user_edit.text()
        r.auth_basic_password = self.basic_pass_edit.text()
        r.auth_bearer_token = self.bearer_token_edit.text()

        r.follow_redirects = self.follow_check.isChecked()
        r.verify_ssl = self.verify_check.isChecked()
        timeout = self.timeout_spin.value()
        r.timeout = timeout if timeout > 0 else None

    # -- обработчики --------------------------------------------------------
    def _on_changed(self) -> None:
        if self._loading or self._req is None:
            return
        self._sync_to_model()
        self.modified.emit()

    def _on_name_edited(self, text: str) -> None:
        if self._loading or self._req is None:
            return
        self._req.name = text
        self.name_changed.emit(self._req)
        self.modified.emit()

    # -- синхронизация URL <-> Query Params --------------------------------
    def _on_url_edited(self, *_args) -> None:
        """Пользователь правит URL → обновляем таблицу Params из query-строки."""
        if self._loading:
            return
        self._sync_params_from_url()
        self._on_changed()

    def _on_params_changed(self) -> None:
        """Изменились Params → пересобираем query-строку в URL."""
        if self._loading:
            return
        self._sync_url_from_params()
        self._on_changed()

    def _sync_params_from_url(self) -> None:
        text = self.url_edit.text()
        _, _, query = text.partition("?")
        items = []
        if query:
            for part in query.split("&"):
                if not part:
                    continue
                key, _, value = part.partition("=")
                items.append({"enabled": True, "key": key, "value": value})
        # set_items не порождает сигнал changed (защита _mutating в таблице).
        self.params_table.set_items(items)

    def _sync_url_from_params(self) -> None:
        base = self.url_edit.text().partition("?")[0]
        pairs = []
        for it in self.params_table.get_items():
            if it.get("enabled", True) and str(it.get("key", "")).strip():
                pairs.append(f"{it['key']}={it['value']}")
        new_url = base + ("?" + "&".join(pairs) if pairs else "")
        if new_url != self.url_edit.text():
            # Программный setText не вызывает textEdited → рекурсии нет.
            self.url_edit.setText(new_url)

    def _on_body_type_changed(self) -> None:
        # form-data и urlencoded используют одно поле модели (body_form), но
        # разные виджеты. Чтобы при переключении не терять введённые поля,
        # переносим актуальные данные в становящуюся активной таблицу.
        if self._req is not None and not self._loading:
            data = self.body_type_combo.currentData()
            if data == models.BODY_URLENCODED:
                self.urlencoded_table.set_items(self._req.body_form)
            elif data == models.BODY_FORM_DATA:
                self.form_data_table.set_items(self._req.body_form)
        self._update_body_stack()
        self._on_changed()

    def _on_raw_lang_changed(self) -> None:
        self._apply_raw_highlighter()
        self._on_changed()

    def _on_auth_type_changed(self) -> None:
        self._update_auth_stack()
        self._on_changed()

    def _on_show_pass_toggled(self, checked: bool) -> None:
        mode = QtWidgets.QLineEdit.EchoMode.Normal if checked else QtWidgets.QLineEdit.EchoMode.Password
        self.basic_pass_edit.setEchoMode(mode)

    # -- вспомогательное ----------------------------------------------------
    def _update_body_stack(self) -> None:
        data = self.body_type_combo.currentData()
        mapping = {
            models.BODY_NONE: 0,
            models.BODY_RAW: 1,
            models.BODY_FORM_DATA: 2,
            models.BODY_URLENCODED: 3,
        }
        self.body_stack.setCurrentIndex(mapping.get(data, 0))
        is_raw = data == models.BODY_RAW
        self.raw_lang_label.setVisible(is_raw)
        self.raw_lang_combo.setVisible(is_raw)

    def _update_auth_stack(self) -> None:
        data = self.auth_type_combo.currentData()
        mapping = {models.AUTH_NONE: 0, models.AUTH_BASIC: 1, models.AUTH_BEARER: 2}
        self.auth_stack.setCurrentIndex(mapping.get(data, 0))

    def _apply_raw_highlighter(self) -> None:
        if self._raw_highlighter is not None:
            self._raw_highlighter.setDocument(None)
            self._raw_highlighter = None
        lang = self.raw_lang_combo.currentData()
        if lang == models.RAW_JSON:
            self._raw_highlighter = JsonHighlighter(self.raw_edit.document())
        elif lang == models.RAW_XML:
            self._raw_highlighter = XmlHighlighter(self.raw_edit.document())

    # -- состояние отправки -------------------------------------------------
    def set_sending(self, sending: bool) -> None:
        self.send_btn.setEnabled(not sending)
        self.send_btn.setText("Sending…" if sending else "Send")
