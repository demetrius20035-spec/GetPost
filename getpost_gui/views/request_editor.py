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
from ..variables import find_unresolved
from .dialogs import AuthEditor
from .widgets import KeyValueTable, monospace_font


class RequestEditor(QtWidgets.QWidget):
    """Редактор одного HTTP-запроса."""

    send_requested = Signal()
    cancel_requested = Signal()
    modified = Signal()
    name_changed = Signal(object)  # передаётся изменённый Request

    def __init__(self, parent=None):
        super().__init__(parent)
        self._req: Optional[models.Request] = None
        self._loading = False
        self._raw_highlighter = None
        self._controller = None
        self._sending = False
        self._known_vars: set = set()

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
        self.send_btn.setObjectName("SendButton")  # для акцентного стиля темы
        self.send_btn.setDefault(True)
        self.send_btn.setMinimumWidth(90)

        top.addWidget(self.method_combo)
        top.addWidget(self.url_edit, 1)
        top.addWidget(self.send_btn)
        layout.addLayout(top)

        # Предупреждение о переменных, которых нет в активном окружении.
        self.var_warning = QtWidgets.QLabel("")
        self.var_warning.setStyleSheet("color: #c92a2a;")
        self.var_warning.setVisible(False)
        layout.addWidget(self.var_warning)

        # Что запрос берёт из настроек папки (базовый URL, заголовки, авторизация).
        self.inherit_note = QtWidgets.QLabel("")
        self.inherit_note.setWordWrap(True)
        self.inherit_note.setStyleSheet("color: #868e96;")
        self.inherit_note.setVisible(False)
        layout.addWidget(self.inherit_note)

        # Вкладки
        self.tabs = QtWidgets.QTabWidget()
        self.params_table = KeyValueTable("Параметр", "Значение")
        self.headers_table = KeyValueTable("Заголовок", "Значение")
        self.tabs.addTab(self.params_table, "Params")
        self.tabs.addTab(self._build_headers_tab(), "Headers")
        self.tabs.addTab(self._build_body_tab(), "Body")
        self.tabs.addTab(self._build_auth_tab(), "Auth")
        self.tabs.addTab(self._build_capture_tab(), "Capture")
        self.tabs.addTab(self._build_options_tab(), "Options")
        layout.addWidget(self.tabs, 1)

    def _build_headers_tab(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(page)
        v.setContentsMargins(6, 6, 6, 6)
        v.setSpacing(4)

        row = QtWidgets.QHBoxLayout()
        row.addStretch(1)
        add_btn = QtWidgets.QToolButton()
        add_btn.setText("＋ Частый заголовок")
        add_btn.setPopupMode(QtWidgets.QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QtWidgets.QMenu(add_btn)
        for name, value in models.COMMON_HEADERS:
            menu.addAction(name, lambda n=name, val=value: self.headers_table.add_item(n, val))
        add_btn.setMenu(menu)
        row.addWidget(add_btn)
        v.addLayout(row)

        v.addWidget(self.headers_table, 1)
        return page

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
        self.body_type_combo.addItem("GraphQL", models.BODY_GRAPHQL)

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
        # 2: form-data (с выбором файла — значение вида "@путь")
        self.form_data_table = KeyValueTable("Поле", "Значение", file_column=True)
        self.body_stack.addWidget(self.form_data_table)
        # 3: urlencoded
        self.urlencoded_table = KeyValueTable("Поле", "Значение")
        self.body_stack.addWidget(self.urlencoded_table)
        # 4: GraphQL — запрос и переменные
        self.body_stack.addWidget(self._build_graphql_page())

        v.addWidget(self.body_stack, 1)
        return page

    def _build_graphql_page(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget()
        splitter = QtWidgets.QSplitter(Qt.Orientation.Vertical)

        query_box = QtWidgets.QWidget()
        query_layout = QtWidgets.QVBoxLayout(query_box)
        query_layout.setContentsMargins(0, 0, 0, 0)
        query_layout.addWidget(QtWidgets.QLabel("Query:"))
        self.graphql_query_edit = QtWidgets.QPlainTextEdit()
        self.graphql_query_edit.setFont(monospace_font())
        self.graphql_query_edit.setPlaceholderText("query { user(id: 1) { name } }")
        query_layout.addWidget(self.graphql_query_edit, 1)
        splitter.addWidget(query_box)

        vars_box = QtWidgets.QWidget()
        vars_layout = QtWidgets.QVBoxLayout(vars_box)
        vars_layout.setContentsMargins(0, 0, 0, 0)
        vars_layout.addWidget(QtWidgets.QLabel("Variables (JSON):"))
        self.graphql_vars_edit = QtWidgets.QPlainTextEdit()
        self.graphql_vars_edit.setFont(monospace_font())
        self.graphql_vars_edit.setPlaceholderText('{"id": 1}')
        self._graphql_vars_highlighter = JsonHighlighter(self.graphql_vars_edit.document())
        vars_layout.addWidget(self.graphql_vars_edit, 1)
        splitter.addWidget(vars_box)

        splitter.setSizes([220, 120])
        layout = QtWidgets.QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(splitter)
        return page

    def _build_auth_tab(self) -> QtWidgets.QWidget:
        """Вкладка Auth: общий редактор (тот же используется для папок)."""
        page = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(page)
        v.setContentsMargins(6, 6, 6, 6)
        self.auth_editor = AuthEditor(allow_inherit=True)
        self.auth_editor.changed.connect(self._on_changed)
        v.addWidget(self.auth_editor, 1)
        return page

    def set_inherited_note(self, notes) -> None:
        """Показать, какие настройки приходят из папок."""
        if notes:
            self.inherit_note.setText("Наследуется: " + "; ".join(notes))
            self.inherit_note.setVisible(True)
        else:
            self.inherit_note.setVisible(False)

    def _build_capture_tab(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(page)
        v.setContentsMargins(6, 6, 6, 6)

        info = QtWidgets.QLabel(
            "После успешного ответа значения записываются в переменные активного "
            "окружения — так строятся цепочки: «Login» кладёт токен, остальные "
            "запросы используют <code>{{token}}</code>."
        )
        info.setWordWrap(True)
        v.addWidget(info)

        row = QtWidgets.QHBoxLayout()
        row.addStretch(1)
        add_btn = QtWidgets.QToolButton()
        add_btn.setText("＋ Правило")
        add_btn.clicked.connect(lambda: self._capture_insert_row(True, "", models.CAPTURE_JSON, ""))
        row.addWidget(add_btn)
        v.addLayout(row)

        self.capture_table = QtWidgets.QTableWidget(0, 5)
        self.capture_table.setHorizontalHeaderLabels(
            ["", "Переменная", "Источник", "Путь / имя", ""]
        )
        self.capture_table.verticalHeader().setVisible(False)
        header = self.capture_table.horizontalHeader()
        for col, mode in (
            (0, QtWidgets.QHeaderView.ResizeMode.ResizeToContents),
            (1, QtWidgets.QHeaderView.ResizeMode.Stretch),
            (2, QtWidgets.QHeaderView.ResizeMode.ResizeToContents),
            (3, QtWidgets.QHeaderView.ResizeMode.Stretch),
            (4, QtWidgets.QHeaderView.ResizeMode.ResizeToContents),
        ):
            header.setSectionResizeMode(col, mode)
        self.capture_table.itemChanged.connect(self._on_capture_changed)
        v.addWidget(self.capture_table, 1)

        hint = QtWidgets.QLabel(
            "Примеры пути: <code>access_token</code>, <code>data.items[0].id</code>. "
            "Для источника «header» укажите имя заголовка."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #868e96;")
        v.addWidget(hint)
        return page

    # -- вкладка Capture ----------------------------------------------------
    _CAPTURE_LABELS = [
        (models.CAPTURE_JSON, "JSON"),
        (models.CAPTURE_HEADER, "Header"),
        (models.CAPTURE_STATUS, "Status"),
        (models.CAPTURE_BODY, "Body"),
    ]

    def _capture_insert_row(self, enabled: bool, name: str, source: str, expr: str) -> None:
        table = self.capture_table
        was_loading = self._loading
        self._loading = True
        try:
            row = table.rowCount()
            table.insertRow(row)

            check = QtWidgets.QTableWidgetItem()
            check.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
            check.setCheckState(Qt.CheckState.Checked if enabled else Qt.CheckState.Unchecked)
            table.setItem(row, 0, check)
            table.setItem(row, 1, QtWidgets.QTableWidgetItem(name))

            combo = QtWidgets.QComboBox()
            for key, title in self._CAPTURE_LABELS:
                combo.addItem(title, key)
            idx = combo.findData(source)
            combo.setCurrentIndex(idx if idx >= 0 else 0)
            combo.currentIndexChanged.connect(self._on_capture_changed)
            table.setCellWidget(row, 2, combo)

            table.setItem(row, 3, QtWidgets.QTableWidgetItem(expr))

            remove = QtWidgets.QToolButton()
            remove.setText("✕")
            remove.setAutoRaise(True)
            remove.clicked.connect(lambda: self._capture_remove_row(remove))
            table.setCellWidget(row, 4, remove)
        finally:
            self._loading = was_loading
        if not was_loading:
            self._on_capture_changed()

    def _capture_remove_row(self, button) -> None:
        for row in range(self.capture_table.rowCount()):
            if self.capture_table.cellWidget(row, 4) is button:
                self.capture_table.removeRow(row)
                self._on_capture_changed()
                return

    def _captures_from_table(self) -> list:
        rules = []
        for row in range(self.capture_table.rowCount()):
            name_item = self.capture_table.item(row, 1)
            expr_item = self.capture_table.item(row, 3)
            combo = self.capture_table.cellWidget(row, 2)
            check = self.capture_table.item(row, 0)
            name = name_item.text().strip() if name_item else ""
            if not name:
                continue
            rules.append(
                {
                    "enabled": check.checkState() == Qt.CheckState.Checked if check else True,
                    "name": name,
                    "source": combo.currentData() if combo else models.CAPTURE_JSON,
                    "expr": expr_item.text().strip() if expr_item else "",
                }
            )
        return rules

    def _on_capture_changed(self, *_args) -> None:
        if self._loading or self._req is None:
            return
        self._req.captures = self._captures_from_table()
        self.modified.emit()

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
    def set_controller(self, controller) -> None:
        """Подключить контроллер (правки полей становятся отменяемыми)."""
        self._controller = controller

    def set_known_variables(self, names) -> None:
        """Сообщить редактору имена доступных переменных (для подсветки)."""
        self._known_vars = set(names or [])
        self._update_var_warning()

    def _connect_signals(self) -> None:
        self.send_btn.clicked.connect(self._on_send_clicked)
        self.url_edit.returnPressed.connect(self._on_send_clicked)

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

        self.graphql_query_edit.textChanged.connect(self._on_changed)
        self.graphql_vars_edit.textChanged.connect(self._on_changed)

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
                self.graphql_query_edit.setPlainText("")
                self.graphql_vars_edit.setPlainText("")
                self.auth_editor.load(models.Request())
                self.inherit_note.setVisible(False)
                self.follow_check.setChecked(True)
                self.verify_check.setChecked(True)
                self.timeout_spin.setValue(0.0)
                self.capture_table.setRowCount(0)
                self.var_warning.setVisible(False)
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
            self.graphql_query_edit.setPlainText(req.body_graphql_query)
            self.graphql_vars_edit.setPlainText(req.body_graphql_variables)
            self._update_body_stack()
            self._apply_raw_highlighter()

            self.auth_editor.load(req)

            self.follow_check.setChecked(req.follow_redirects)
            self.verify_check.setChecked(req.verify_ssl)
            self.timeout_spin.setValue(req.timeout or 0.0)

            self.capture_table.setRowCount(0)
            for rule in req.captures:
                self._capture_insert_row(
                    bool(rule.get("enabled", True)),
                    str(rule.get("name", "")),
                    rule.get("source", models.CAPTURE_JSON),
                    str(rule.get("expr", "")),
                )
        finally:
            self._loading = False
        self._update_var_warning()

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
        r.body_graphql_query = self.graphql_query_edit.toPlainText()
        r.body_graphql_variables = self.graphql_vars_edit.toPlainText()

        self.auth_editor.store(r)

        r.follow_redirects = self.follow_check.isChecked()
        r.verify_ssl = self.verify_check.isChecked()
        timeout = self.timeout_spin.value()
        r.timeout = timeout if timeout > 0 else None

    # -- обработчики --------------------------------------------------------
    def _on_changed(self) -> None:
        if self._loading or self._req is None:
            return
        self._sync_to_model()
        self._update_var_warning()
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


    # -- вспомогательное ----------------------------------------------------
    def _update_body_stack(self) -> None:
        data = self.body_type_combo.currentData()
        mapping = {
            models.BODY_NONE: 0,
            models.BODY_RAW: 1,
            models.BODY_FORM_DATA: 2,
            models.BODY_URLENCODED: 3,
            models.BODY_GRAPHQL: 4,
        }
        self.body_stack.setCurrentIndex(mapping.get(data, 0))
        is_raw = data == models.BODY_RAW
        self.raw_lang_label.setVisible(is_raw)
        self.raw_lang_combo.setVisible(is_raw)

    def refresh_highlighting(self) -> None:
        """Пересоздать подсветку после смены темы."""
        self._apply_raw_highlighter()
        self._graphql_vars_highlighter = JsonHighlighter(self.graphql_vars_edit.document())

    def commit_pending_edits(self) -> None:
        """Применить незакрытые режимы редактирования (таблицы «текстом»)."""
        for table in (self.params_table, self.headers_table,
                      self.form_data_table, self.urlencoded_table):
            table.commit_bulk()

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
    def _on_send_clicked(self) -> None:
        """Одна кнопка: во время отправки работает как Cancel."""
        if self._sending:
            self.cancel_requested.emit()
        else:
            self.send_requested.emit()

    def set_sending(self, sending: bool) -> None:
        self._sending = sending
        self.send_btn.setText("Cancel" if sending else "Send")
        self.send_btn.setToolTip("Прервать запрос" if sending else "Отправить запрос (Ctrl+Enter)")

    # -- подсветка неразрешённых переменных ---------------------------------
    def _collect_texts(self) -> list:
        """Все тексты запроса, в которых могут быть переменные."""
        if self._req is None:
            return []
        req = self._req
        texts = [req.url, req.body_raw, req.body_graphql_query, req.body_graphql_variables,
                 req.auth_bearer_token, req.auth_basic_username, req.auth_basic_password,
                 req.auth_api_key_name, req.auth_api_key_value,
                 req.auth_oauth2_token_url, req.auth_oauth2_client_id,
                 req.auth_oauth2_client_secret, req.auth_oauth2_scope]
        for collection in (req.headers, req.params, req.body_form):
            for item in collection:
                if item.get("enabled", True):
                    texts.append(str(item.get("key", "")))
                    texts.append(str(item.get("value", "")))
        return texts

    def _update_var_warning(self) -> None:
        """Показать переменные, которых нет в активном окружении."""
        if self._req is None:
            self.var_warning.setVisible(False)
            return
        known = {name: "" for name in self._known_vars}
        unresolved = []
        for text in self._collect_texts():
            for name in find_unresolved(text, known):
                if name not in unresolved:
                    unresolved.append(name)
        if unresolved:
            names = ", ".join("{{" + n + "}}" for n in unresolved[:6])
            more = "…" if len(unresolved) > 6 else ""
            self.var_warning.setText(f"⚠ Не заданы переменные: {names}{more}")
            self.var_warning.setToolTip(
                "Задайте их в «Файл → Окружения и переменные…» — иначе они уйдут в запрос как есть."
            )
            self.var_warning.setVisible(True)
        else:
            self.var_warning.setVisible(False)
