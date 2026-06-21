"""Главное окно приложения GetPost.

Связывает три панели (дерево, редактор запроса, панель ответа), управляет
рабочими пространствами, автосохранением и отправкой запросов в фоновом
потоке.
"""
from __future__ import annotations

import re
from typing import List, Optional

from .. import curl, http_client, models, share
from ..qtcompat import QtCore, QtGui, QtWidgets
from ..runner import RequestRunner
from ..storage import Storage, build_default_workspace
from .dialogs import CurlExportDialog, EnvironmentsDialog, ImportCurlDialog
from .request_editor import RequestEditor
from .response_view import ResponseView
from .sidebar import Sidebar

_URL_HISTORY_LIMIT = 50

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
        # История ответов по id запроса (только в памяти).
        self._history: dict = {}
        self._sending_req: Optional[models.Request] = None

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
        self.editor = RequestEditor()
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

        # Редактор.
        self.editor.modified.connect(self._schedule_save)
        self.editor.name_changed.connect(self.sidebar.update_item_name)
        self.editor.send_requested.connect(self._on_send)

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
            envs = dialog.environments()
            self.current_ws.environments = envs or {models.DEFAULT_ENV: {}}
            self.current_ws.set_active_env(dialog.active())
            if self.current_ws.active_env not in self.current_ws.environments:
                self.current_ws.active_env = next(iter(self.current_ws.environments))
            self.storage.save_workspace(self.current_ws)
            self.sidebar.set_environments(self.current_ws)
            self.status.showMessage("Окружения сохранены", 3000)

    def _on_env_switched(self, name: str) -> None:
        if self.current_ws is None:
            return
        self.current_ws.set_active_env(name)
        self._schedule_save()
        self.status.showMessage(f"Активное окружение: {name}", 3000)

    def _on_copy_curl(self, req) -> None:
        if req is None or self.current_ws is None:
            return
        try:
            command = curl.to_curl(req, self.current_ws.variables)
        except Exception as exc:  # noqa: BLE001
            QtWidgets.QMessageBox.warning(self, "Copy as cURL", f"Не удалось сформировать команду: {exc}")
            return
        CurlExportDialog(command, self).exec()

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
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(share.export_str(obj))
        except OSError as exc:
            QtWidgets.QMessageBox.warning(self, "Экспорт", f"Не удалось сохранить файл:\n{exc}")
            return
        labels = {share.KIND_WORKSPACE: "рабочее пространство", share.KIND_FOLDER: "папка", share.KIND_REQUEST: "запрос"}
        self.status.showMessage(f"Экспортировано ({labels.get(kind, kind)}): {path}", 5000)

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
        if self.current_ws is not None:
            self.storage.save_workspace(self.current_ws)
            self.status.showMessage("Сохранено", 1500)

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
        self.editor.set_sending(True)
        self.status.showMessage(f"Отправка {method} {url}…")
        self._sending_req = req
        self._add_url_history(url)

        self._runner = RequestRunner(method, url, kwargs, timeout=timeout, parent=self)
        self._runner.succeeded.connect(self._on_response)
        self._runner.failed.connect(self._on_request_error)
        self._runner.finished.connect(self._on_runner_finished)
        self._runner.start()

    def _on_response(self, data) -> None:
        if self._sending_req is not None:
            history = self._history.setdefault(self._sending_req.id, [])
            history.append(data)
            if len(history) > 15:
                del history[0]
            self.response.show_response(data, history)
        else:
            self.response.show_response(data)
        self.status.showMessage(
            f"{data.status_line} · {data.elapsed_ms:.0f} мс", 5000
        )

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
            self._runner.wait(2000)
        super().closeEvent(event)
