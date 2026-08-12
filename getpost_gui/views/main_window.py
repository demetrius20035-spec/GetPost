"""Главное окно приложения GetPost.

Связывает три панели (дерево, редактор запроса, панель ответа), управляет
рабочими пространствами, автосохранением и отправкой запросов в фоновом
потоке.
"""
from __future__ import annotations

import re
from typing import List, Optional

import requests

from .. import capture, codegen, http_client, models, share
from ..controller import WorkspaceController
from ..qtcompat import QtCore, QtGui, QtWidgets
from ..runner import RequestRunner
from ..storage import Storage, build_default_workspace
from .dialogs import CodeExportDialog, EnvironmentsDialog, ImportCurlDialog, QuickOpenDialog
from .request_editor import RequestEditor
from .response_view import ResponseView
from .sidebar import Sidebar

_URL_HISTORY_LIMIT = 50

# Сколько ответов держать в истории на один запрос и сколько из них — с телом.
_HISTORY_PER_REQUEST = 10
_HISTORY_WITH_BODY = 3

# Задержка автосохранения (мс) — изменения объединяются в одну запись.
_AUTOSAVE_DELAY_MS = 500


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, storage: Optional[Storage] = None):
        super().__init__()
        self.storage = storage or Storage()
        self.settings = self.storage.load_settings()
        self.timeout = float(self.settings.get("timeout", http_client.DEFAULT_TIMEOUT))

        self.workspaces: List[models.Workspace] = []
        self.current_ws: Optional[models.Workspace] = None
        self._runner: Optional[RequestRunner] = None
        # История ответов по id запроса (только в памяти, с ограничениями).
        self._history: dict = {}
        self._sending_req: Optional[models.Request] = None
        self._save_error_shown = False
        # Контроллер: единая точка изменений модели + история отмен.
        self.controller = WorkspaceController(self)
        # Одна сессия на приложение: keep-alive соединений и общие cookies.
        self.session = requests.Session()

        self.setWindowTitle("GetPost — HTTP-клиент")
        self.resize(1200, 720)

        self._build_ui()
        self._build_menu()
        self._connect_signals()

        self._save_timer = QtCore.QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(_AUTOSAVE_DELAY_MS)
        self._save_timer.timeout.connect(self._do_autosave)

        self._restore_geometry()
        self._load_initial_data()

    # -- интерфейс ----------------------------------------------------------
    def _build_ui(self) -> None:
        self.sidebar = Sidebar()
        self.sidebar.set_controller(self.controller)
        self.editor = RequestEditor()
        self.editor.set_controller(self.controller)
        self.response = ResponseView()

        # Автодополнение URL по истории отправленных адресов.
        self._url_model = QtCore.QStringListModel(self.settings.get("url_history", []))
        completer = QtWidgets.QCompleter(self._url_model, self)
        completer.setCaseSensitivity(QtCore.Qt.CaseSensitivity.CaseInsensitive)
        completer.setFilterMode(QtCore.Qt.MatchFlag.MatchContains)
        self.editor.url_edit.setCompleter(completer)

        self.splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        self.splitter.addWidget(self.sidebar)
        self.splitter.addWidget(self.editor)
        self.splitter.addWidget(self.response)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setStretchFactor(2, 1)
        self.splitter.setSizes([260, 520, 420])
        self.setCentralWidget(self.splitter)

        self.status = self.statusBar()
        self.status.showMessage("Готово")

    def _build_menu(self) -> None:
        menubar = self.menuBar()

        file_menu = menubar.addMenu("Файл")
        file_menu.addAction("Новое рабочее пространство", self.new_workspace)
        file_menu.addAction("Окружения и переменные…", self.edit_variables)
        save_action = file_menu.addAction("Сохранить сейчас", self._flush_save)
        save_action.setShortcut("Ctrl+S")
        file_menu.addSeparator()
        import_action = file_menu.addAction("Импорт…", self._import_item)
        import_action.setShortcut("Ctrl+O")
        import_action.setStatusTip("Импортировать Workspace, папку или запрос из файла")
        file_menu.addAction("Экспорт текущего Workspace…", self._export_workspace)
        file_menu.addSeparator()
        reset_action = file_menu.addAction("Сбросить конфигурацию…", self.reset_config)
        reset_action.setStatusTip("Удалить все рабочие пространства и настройки")
        file_menu.addSeparator()
        quit_action = file_menu.addAction("Выход", self.close)
        quit_action.setShortcut(QtGui.QKeySequence.StandardKey.Quit)

        edit_menu = menubar.addMenu("Правка")
        edit_menu.addAction(self.controller.create_undo_action(self))
        edit_menu.addAction(self.controller.create_redo_action(self))
        edit_menu.addSeparator()
        quick_action = edit_menu.addAction("Быстрый переход к запросу…", self.quick_open)
        quick_action.setShortcut("Ctrl+P")
        quick_action.setStatusTip("Найти запрос по имени или URL")

        ws_menu = menubar.addMenu("Рабочее пространство")
        ws_menu.addAction("Создать", self.new_workspace)
        ws_menu.addAction("Переименовать", self.rename_workspace)
        ws_menu.addAction("Удалить", self.delete_workspace)
        ws_menu.addSeparator()
        ws_menu.addAction("Окружения и переменные…", self.edit_variables)

        req_menu = menubar.addMenu("Запрос")
        send_action = req_menu.addAction("Отправить", self._on_send)
        send_action.setShortcut(QtGui.QKeySequence("Ctrl+Return"))
        new_req_action = req_menu.addAction("Новый запрос", self.sidebar.add_request)
        new_req_action.setShortcut("Ctrl+N")
        new_folder_action = req_menu.addAction("Новая папка", self.sidebar.add_folder)
        new_folder_action.setShortcut("Ctrl+Shift+N")
        dup_action = req_menu.addAction("Дублировать", self.sidebar.duplicate_current)
        dup_action.setShortcut("Ctrl+D")
        req_menu.addSeparator()
        req_menu.addAction("Импорт из cURL…", self.import_curl)
        code_action = req_menu.addAction("Сгенерировать код…", self.export_code)
        code_action.setShortcut("Ctrl+G")
        code_action.setStatusTip("cURL, Python, JavaScript, HTTPie")

        help_menu = menubar.addMenu("Справка")
        help_menu.addAction("О программе", self._show_about)

    def _connect_signals(self) -> None:
        # Дерево.
        self.sidebar.request_selected.connect(self._on_request_selected)
        self.sidebar.structure_changed.connect(self._schedule_save)
        self.sidebar.item_renamed.connect(self._on_item_renamed)
        self.sidebar.copy_curl_requested.connect(self._on_copy_curl)
        self.sidebar.export_requested.connect(self._export_object)
        self.sidebar.export_workspace_requested.connect(self._export_workspace)
        self.sidebar.import_requested.connect(self._import_item)
        self.sidebar.environment_switched.connect(self._on_env_switched)
        self.sidebar.workspace_switched.connect(self.switch_workspace)
        self.sidebar.new_workspace_requested.connect(self.new_workspace)
        self.sidebar.rename_workspace_requested.connect(self.rename_workspace)
        self.sidebar.delete_workspace_requested.connect(self.delete_workspace)
        self.sidebar.edit_variables_requested.connect(self.edit_variables)

        # Контроллер: отмена/повтор перестраивают дерево и требуют сохранения.
        self.controller.structure_changed.connect(self._on_structure_restored)
        self.controller.modified.connect(self._schedule_save)

        # Редактор.
        self.editor.modified.connect(self._schedule_save)
        self.editor.name_changed.connect(self.sidebar.update_item_name)
        self.editor.send_requested.connect(self._on_send)
        self.editor.cancel_requested.connect(self._on_cancel)

    # -- начальная загрузка -------------------------------------------------
    def _load_initial_data(self) -> None:
        self.workspaces = self.storage.load_all_workspaces()
        if not self.workspaces:
            ws = build_default_workspace()
            self.storage.save_workspace(ws)
            self.workspaces = [ws]

        last_id = self.settings.get("last_workspace_id")
        current = next((w for w in self.workspaces if w.id == last_id), None)
        if current is None:
            current = self.workspaces[0]

        self.sidebar.set_workspaces(self.workspaces, current.id)
        self._set_current_workspace(current, select_first=True)

    # -- управление Workspace ----------------------------------------------
    def _set_current_workspace(self, ws: models.Workspace, select_first: bool = False) -> None:
        self.current_ws = ws
        self.controller.set_workspace(ws)
        self.sidebar.set_workspace(ws)
        self.editor.set_request(None)
        self.response.clear()
        self.settings["last_workspace_id"] = ws.id
        self.storage.save_settings(self.settings)
        self.setWindowTitle(f"GetPost — {ws.name}")
        if select_first:
            self.sidebar.select_first_request()

    def switch_workspace(self, ws_id: str) -> None:
        if self.current_ws is not None and ws_id == self.current_ws.id:
            return
        self._flush_save()
        ws = next((w for w in self.workspaces if w.id == ws_id), None)
        if ws is not None:
            self._set_current_workspace(ws, select_first=True)

    def new_workspace(self) -> None:
        name, ok = QtWidgets.QInputDialog.getText(
            self, "Новое рабочее пространство", "Название:", text="My Workspace"
        )
        if not ok or not name.strip():
            return
        ws = self.storage.create_workspace(name.strip())
        self.workspaces.append(ws)
        self.workspaces.sort(key=lambda w: w.name.lower())
        self.sidebar.set_workspaces(self.workspaces, ws.id)
        self._set_current_workspace(ws, select_first=True)
        self.status.showMessage(f"Создано рабочее пространство «{ws.name}»", 4000)

    def rename_workspace(self) -> None:
        if self.current_ws is None:
            return
        name, ok = QtWidgets.QInputDialog.getText(
            self, "Переименовать", "Название:", text=self.current_ws.name
        )
        if not ok or not name.strip():
            return
        self.current_ws.name = name.strip()
        self.storage.save_workspace(self.current_ws)
        self.workspaces.sort(key=lambda w: w.name.lower())
        self.sidebar.set_workspaces(self.workspaces, self.current_ws.id)
        self.setWindowTitle(f"GetPost — {self.current_ws.name}")

    def delete_workspace(self) -> None:
        if self.current_ws is None:
            return
        reply = QtWidgets.QMessageBox.question(
            self,
            "Удаление рабочего пространства",
            f"Удалить рабочее пространство «{self.current_ws.name}» со всем содержимым?",
            QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
            QtWidgets.QMessageBox.StandardButton.No,
        )
        if reply != QtWidgets.QMessageBox.StandardButton.Yes:
            return

        self._save_timer.stop()
        self.storage.delete_workspace(self.current_ws)
        self.workspaces = [w for w in self.workspaces if w.id != self.current_ws.id]
        if not self.workspaces:
            ws = build_default_workspace()
            self.storage.save_workspace(ws)
            self.workspaces = [ws]
        self.sidebar.set_workspaces(self.workspaces, self.workspaces[0].id)
        self._set_current_workspace(self.workspaces[0], select_first=True)

    def edit_variables(self) -> None:
        if self.current_ws is None:
            return
        dialog = EnvironmentsDialog(self.current_ws, self)
        if dialog.exec():
            with self.controller.transaction("Изменение окружений"):
                envs = dialog.environments()
                self.current_ws.environments = envs or {models.DEFAULT_ENV: {}}
                self.current_ws.secret_vars = dialog.secret_vars()
                self.current_ws.set_active_env(dialog.active())
                if self.current_ws.active_env not in self.current_ws.environments:
                    self.current_ws.active_env = next(iter(self.current_ws.environments))
            self.sidebar.set_environments(self.current_ws)
            self._refresh_known_variables()
            self.status.showMessage("Окружения сохранены", 3000)

    def _refresh_known_variables(self) -> None:
        """Сообщить редактору, какие переменные доступны (для подсветки)."""
        names = self.current_ws.variables.keys() if self.current_ws is not None else []
        self.editor.set_known_variables(names)

    def _on_env_switched(self, name: str) -> None:
        if self.current_ws is None:
            return
        self.current_ws.set_active_env(name)
        self._refresh_known_variables()
        self._schedule_save()
        self.status.showMessage(f"Активное окружение: {name}", 3000)

    def _on_copy_curl(self, req) -> None:
        self._show_code(req, codegen.LANG_CURL)

    def export_code(self) -> None:
        """Сгенерировать код текущего запроса (cURL/Python/JS/HTTPie)."""
        self._show_code(self.editor.current_request(), codegen.LANG_CURL)

    def _show_code(self, req, language: str) -> None:
        if req is None or self.current_ws is None:
            self.status.showMessage("Выберите запрос", 3000)
            return
        dialog = CodeExportDialog(req, self.current_ws.variables, language, self)
        dialog.exec()

    def quick_open(self) -> None:
        """Быстрый переход к запросу по имени или URL (Ctrl+P)."""
        if self.current_ws is None:
            return
        items = list(self._iter_all_requests())
        if not items:
            self.status.showMessage("В этом рабочем пространстве нет запросов", 3000)
            return
        dialog = QuickOpenDialog(items, self)
        if dialog.exec():
            req = dialog.selected_request()
            if req is not None:
                self.sidebar.select_request(req)
                self.editor.set_request(req)
                self._on_request_selected(req)

    def import_curl(self) -> None:
        if self.current_ws is None:
            return
        dialog = ImportCurlDialog(self)
        if dialog.exec():
            req = dialog.request()
            if req is not None:
                self.sidebar.add_imported_request(req)
                self.status.showMessage(f"Импортирован запрос: {req.method} {req.url}", 4000)

    # -- импорт / экспорт ---------------------------------------------------
    @staticmethod
    def _safe_filename(name: str) -> str:
        cleaned = re.sub(r"[^\w\-. ]+", "_", name or "").strip()
        return cleaned or "export"

    _FILE_FILTER = f"GetPost (*{share.FILE_EXTENSION} *.json);;Все файлы (*)"

    def _export_object(self, obj) -> None:
        if obj is None:
            return
        try:
            kind = share.detect_kind(obj)
        except TypeError:
            return
        default = self._safe_filename(getattr(obj, "name", "export")) + share.FILE_EXTENSION
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Экспорт", default, self._FILE_FILTER)
        if not path:
            return

        # Файл предназначен для обмена — по умолчанию без секретов.
        include_secrets = False
        preview = share.export_dict(obj, include_secrets=False)
        stripped = preview.get("stripped")
        if stripped:
            answer = QtWidgets.QMessageBox.question(
                self,
                "Секреты в экспорте",
                "Из файла будут удалены:\n  • " + "\n  • ".join(stripped) +
                "\n\nЭто безопасно для передачи другим людям.\n\n"
                "Включить секреты в файл? (только для личной резервной копии)",
                QtWidgets.QMessageBox.StandardButton.No | QtWidgets.QMessageBox.StandardButton.Yes,
                QtWidgets.QMessageBox.StandardButton.No,
            )
            include_secrets = answer == QtWidgets.QMessageBox.StandardButton.Yes

        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(share.export_str(obj, include_secrets=include_secrets))
        except OSError as exc:
            QtWidgets.QMessageBox.warning(self, "Экспорт", f"Не удалось сохранить файл:\n{exc}")
            return
        labels = {share.KIND_WORKSPACE: "рабочее пространство", share.KIND_FOLDER: "папка", share.KIND_REQUEST: "запрос"}
        suffix = " (с секретами)" if include_secrets else " (без секретов)"
        self.status.showMessage(f"Экспортировано ({labels.get(kind, kind)}){suffix}: {path}", 6000)

    def _export_workspace(self) -> None:
        if self.current_ws is not None:
            self._export_object(self.current_ws)

    def _import_item(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Импорт", "", self._FILE_FILTER)
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as fh:
                text = fh.read()
            kind, obj = share.parse(text)
        except (OSError, ValueError) as exc:
            QtWidgets.QMessageBox.warning(self, "Импорт", f"Не удалось импортировать файл:\n{exc}")
            return

        if kind == share.KIND_WORKSPACE:
            self._import_workspace(obj)
        elif kind == share.KIND_FOLDER:
            if self.current_ws is None:
                return
            relocated = self.sidebar.add_imported_folder(obj)
            extra = " (помещена в корень из-за лимита вложенности)" if relocated else ""
            self.status.showMessage(f"Импортирована папка «{obj.name}»{extra}", 5000)
        else:  # request
            if self.current_ws is None:
                return
            self.sidebar.add_imported_request(obj)
            self.status.showMessage(f"Импортирован запрос «{obj.name}»", 5000)

    def _import_workspace(self, ws: models.Workspace) -> None:
        existing = {w.name for w in self.workspaces}
        if ws.name in existing:
            ws.name = f"{ws.name} (импорт)"
        self.storage.save_workspace(ws)
        self.workspaces.append(ws)
        self.workspaces.sort(key=lambda w: w.name.lower())
        self.sidebar.set_workspaces(self.workspaces, ws.id)
        self._set_current_workspace(ws, select_first=True)
        self.status.showMessage(f"Импортировано рабочее пространство «{ws.name}»", 5000)

    def reset_config(self) -> None:
        reply = QtWidgets.QMessageBox.warning(
            self,
            "Сброс конфигурации",
            "Все рабочие пространства и настройки будут удалены без возможности "
            "восстановления. Продолжить?",
            QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
            QtWidgets.QMessageBox.StandardButton.No,
        )
        if reply != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        self._save_timer.stop()
        self.storage.reset()
        self.settings = {}
        self._load_initial_data()
        self.status.showMessage("Конфигурация сброшена", 4000)

    # -- переименование элементов ------------------------------------------
    def _on_item_renamed(self, obj) -> None:
        # Если переименован открытый запрос — обновим поле имени в редакторе.
        if obj is self.editor.current_request():
            self.editor.update_name_display()

    def _on_request_selected(self, req) -> None:
        self.editor.set_request(req)
        self._refresh_known_variables()
        # Показываем историю ответов выбранного запроса (если есть).
        history = self._history.get(req.id) if req is not None else None
        if history:
            self.response.show_response(history[-1], history)
        else:
            self.response.clear()

    # -- автосохранение -----------------------------------------------------
    def _schedule_save(self) -> None:
        self._save_timer.start()

    def _do_autosave(self) -> None:
        if self.current_ws is None:
            return
        try:
            self.storage.save_workspace(self.current_ws)
        except OSError as exc:
            # Молча терять данные нельзя: сообщаем явно (один диалог на сессию,
            # чтобы не заваливать пользователя при каждой правке).
            self.status.showMessage(f"НЕ СОХРАНЕНО: {exc.strerror or exc}", 10000)
            if not self._save_error_shown:
                self._save_error_shown = True
                QtWidgets.QMessageBox.warning(
                    self,
                    "Не удалось сохранить",
                    "Не получилось записать рабочее пространство на диск:\n"
                    f"{exc}\n\nИзменения остаются в памяти. Освободите место или "
                    "проверьте права доступа, затем сохраните через «Файл → Сохранить сейчас».",
                )
            return
        self._save_error_shown = False
        self.status.showMessage("Сохранено", 1500)

    def _on_structure_restored(self) -> None:
        """Дерево изменилось извне (отмена/повтор) — перестроить и вернуть выбор."""
        current = self.editor.current_request()
        current_id = current.id if current is not None else None
        self.sidebar.set_workspace(self.current_ws)
        self.sidebar.set_environments(self.current_ws)
        restored = self._find_request_by_id(current_id) if current_id else None
        if restored is not None:
            self.sidebar.select_request(restored)
            self.editor.set_request(restored)
        else:
            self.editor.set_request(None)
            self.response.clear()

    def _iter_all_requests(self, container=None):
        """Перебрать все запросы текущего Workspace с путями («Папка/Имя»)."""
        if container is None:
            container = self.current_ws
        if container is None:
            return
        stack = [(container, "")]
        while stack:
            node, prefix = stack.pop()
            for req in node.requests:
                yield prefix + req.name, req
            for folder in node.folders:
                stack.append((folder, prefix + folder.name + "/"))

    def _find_request_by_id(self, req_id: str):
        for _, req in self._iter_all_requests():
            if req.id == req_id:
                return req
        return None

    def _flush_save(self) -> None:
        if self._save_timer.isActive():
            self._save_timer.stop()
            self._do_autosave()

    # -- отправка запроса ---------------------------------------------------
    def _on_send(self) -> None:
        if self.current_ws is None:
            return
        req = self.editor.current_request()
        if req is None:
            self.status.showMessage("Выберите запрос для отправки", 3000)
            return
        try:
            method, url, kwargs = http_client.build_request_kwargs(req, self.current_ws.variables)
        except Exception as exc:  # ошибка сборки запроса
            self.response.show_error(f"Не удалось подготовить запрос: {exc}")
            return
        if not url:
            self.response.show_error("URL пуст. Укажите адрес запроса.")
            return

        # Параметры выполнения уровня запроса.
        kwargs["allow_redirects"] = req.follow_redirects
        kwargs["verify"] = req.verify_ssl
        if not req.verify_ssl:
            try:
                import urllib3

                urllib3.disable_warnings()
            except Exception:
                pass
        timeout = req.timeout if req.timeout else self.timeout

        self.response.show_loading()
        self.response.show_sent_request(method, url, kwargs)
        self.editor.set_sending(True)
        self.status.showMessage(f"Отправка {method} {url}…")
        self._sending_req = req
        self._add_url_history(url)

        self._runner = RequestRunner(
            method, url, kwargs, timeout=timeout, session=self.session, parent=self
        )
        self._runner.succeeded.connect(self._on_response)
        self._runner.failed.connect(self._on_request_error)
        self._runner.cancelled.connect(self._on_request_cancelled)
        self._runner.finished.connect(self._on_runner_finished)
        self._runner.start()

    def _on_cancel(self) -> None:
        """Отменить текущий запрос (кнопка Cancel)."""
        if self._runner is not None and self._runner.isRunning():
            self._runner.cancel()
            self.status.showMessage("Запрос отменён", 3000)
            self.editor.set_sending(False)

    def _on_request_cancelled(self) -> None:
        self.response.show_error("Запрос отменён.")
        self.status.showMessage("Запрос отменён", 3000)

    def _on_response(self, data) -> None:
        req = self._sending_req
        if req is not None:
            history = self._history.setdefault(req.id, [])
            history.append(data)
            # Ограничиваем и число ответов, и объём памяти: у старых записей
            # тело выбрасываем, оставляя статус/время/заголовки.
            del history[:-_HISTORY_PER_REQUEST]
            for old in history[:-_HISTORY_WITH_BODY]:
                old.drop_body()
            self.response.show_response(data, history)
        else:
            self.response.show_response(data)

        message = f"{data.status_line} · {data.elapsed_ms:.0f} мс"
        if data.truncated:
            message += " · тело обрезано по лимиту"
        if req is not None:
            captured = self._apply_captures(req, data)
            if captured:
                message += " · переменные: " + ", ".join(captured)
        self.status.showMessage(message, 6000)

    def _apply_captures(self, req: models.Request, data) -> List[str]:
        """Извлечь значения из ответа в переменные активного окружения."""
        if not req.captures or self.current_ws is None:
            return []
        values, problems = capture.apply_captures(
            req.captures, data.status_code, data.headers, data.text
        )
        if values:
            with self.controller.transaction("Извлечение переменных из ответа"):
                env = self.current_ws.variables
                env.update(values)
        if problems:
            self.response.show_capture_problems(problems)
        return list(values)

    def _add_url_history(self, url: str) -> None:
        if not url:
            return
        history = self.settings.get("url_history", [])
        if url in history:
            history.remove(url)
        history.insert(0, url)
        del history[_URL_HISTORY_LIMIT:]
        self.settings["url_history"] = history
        self._url_model.setStringList(history)

    def _on_request_error(self, message: str) -> None:
        self.response.show_error(message)
        self.status.showMessage("Ошибка запроса", 5000)

    def _on_runner_finished(self) -> None:
        self.editor.set_sending(False)
        self._runner = None

    # -- прочее -------------------------------------------------------------
    def _show_about(self) -> None:
        from ..qtcompat import QT_API
        from .. import __version__

        QtWidgets.QMessageBox.about(
            self,
            "О программе",
            f"<h3>GetPost {__version__}</h3>"
            "<p>Простой GUI-клиент для HTTP-запросов "
            "(аналог Postman/Insomnia).</p>"
            f"<p>Qt-биндинг: {QT_API}</p>",
        )

    def _restore_geometry(self) -> None:
        geo = self.settings.get("window_geometry")
        if isinstance(geo, str) and geo:
            try:
                self.restoreGeometry(QtCore.QByteArray.fromBase64(geo.encode("ascii")))
            except Exception:
                pass

    def closeEvent(self, event) -> None:  # noqa: N802 - имя задано Qt
        self._flush_save()
        try:
            self.settings["window_geometry"] = bytes(self.saveGeometry().toBase64()).decode("ascii")
            self.storage.save_settings(self.settings)
        except Exception:
            pass
        if self._runner is not None and self._runner.isRunning():
            self._runner.cancel()
            self._runner.wait(2000)
        try:
            self.session.close()
        except Exception:
            pass
        super().closeEvent(event)
