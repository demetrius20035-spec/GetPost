"""Тесты интерфейса в offscreen-режиме (без реального дисплея).

Запускаются вместе с остальными: ``python -m unittest discover -s tests``.
Если Qt не установлен, набор пропускается, а не падает.
"""
import os
import tempfile
import unittest

# Должно быть выставлено до создания QApplication.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:  # pragma: no cover - зависит от окружения
    from getpost_gui.qtcompat import QtWidgets, Qt
    QT_AVAILABLE = True
    QT_IMPORT_ERROR = ""
except Exception as exc:  # pragma: no cover
    QT_AVAILABLE = False
    QT_IMPORT_ERROR = str(exc)

if QT_AVAILABLE:
    from getpost_gui import models
    from getpost_gui.controller import WorkspaceController
    from getpost_gui.http_client import ResponseData
    from getpost_gui.storage import Storage
    from getpost_gui.views.main_window import MainWindow
    from getpost_gui.views.sidebar import ROLE_OBJ
    from getpost_gui.views.widgets import KeyValueTable, MASK_TEXT


_app = None


def setUpModule():  # noqa: N802 - имя задано unittest
    """Одно приложение Qt на весь модуль + подавление модальных диалогов."""
    if not QT_AVAILABLE:
        raise unittest.SkipTest(f"Qt недоступен: {QT_IMPORT_ERROR}")
    global _app
    _app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    # В offscreen-режиме модальные окна заблокировали бы тесты.
    QtWidgets.QMessageBox.information = staticmethod(lambda *a, **k: None)
    QtWidgets.QMessageBox.warning = staticmethod(lambda *a, **k: None)
    QtWidgets.QMessageBox.question = staticmethod(
        lambda *a, **k: QtWidgets.QMessageBox.StandardButton.Yes
    )


@unittest.skipUnless(QT_AVAILABLE, "Qt недоступен")
class GuiTestCase(unittest.TestCase):
    """Базовый класс: свежий каталог конфигурации и главное окно на каждый тест."""

    def setUp(self):
        self.config_dir = tempfile.mkdtemp(prefix="getpost_test_")
        os.environ["GETPOST_CONFIG_DIR"] = self.config_dir
        self.storage = Storage(self.config_dir)
        self.window = MainWindow(storage=self.storage)
        # Показываем окно: иначе isVisible() у вложенных виджетов всегда False.
        self.window.show()
        self.ws = self.window.current_ws

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()

    # -- помощники ----------------------------------------------------------
    def type_url(self, text):
        """Имитировать ручной ввод URL.

        Программный ``setText`` намеренно не синхронизируется с моделью (иначе
        синхронизация URL↔Params зациклилась бы), поэтому дополнительно
        вызываем тот же обработчик, что и сигнал ``textEdited``.
        """
        self.window.editor.url_edit.setText(text)
        self.window.editor._on_url_edited()

    def find_item(self, obj):
        it = QtWidgets.QTreeWidgetItemIterator(self.window.sidebar.tree)
        while it.value():
            if it.value().data(0, ROLE_OBJ) is obj:
                return it.value()
            it += 1
        return None

    def select(self, obj):
        self.window.sidebar.tree.setCurrentItem(self.find_item(obj))

    def all_requests(self, container=None):
        container = container or self.ws
        found = list(container.requests)
        for folder in container.folders:
            found += self.all_requests(folder)
        return found


class TestStartup(GuiTestCase):
    def test_default_workspace_created(self):
        self.assertIsNotNone(self.ws)
        self.assertTrue(self.all_requests())

    def test_first_request_selected(self):
        self.assertIsNotNone(self.window.editor.current_request())

    def test_editor_edits_reach_model(self):
        req = self.window.editor.current_request()
        self.type_url("https://example.com/x")
        self.window.editor.method_combo.setCurrentText("POST")
        self.assertEqual(req.url, "https://example.com/x")
        self.assertEqual(req.method, "POST")


class TestTreeOperations(GuiTestCase):
    def test_new_request_prefilled_headers(self):
        self.window.sidebar.add_request()
        created = [r for r in self.all_requests() if r.name == "Новый запрос"][-1]
        self.assertEqual(len(created.headers), 3)
        self.assertTrue(all(not h["enabled"] for h in created.headers))
        self.assertIn("Content-Type", [h["key"] for h in created.headers])

    def test_folder_depth_limit(self):
        first = models.Folder("L1")
        self.ws.folders.append(first)
        self.window.sidebar.set_workspace(self.ws)
        self.select(first)
        self.window.sidebar.add_folder()  # второй уровень — можно
        self.assertEqual(len(first.folders), 1)
        second = first.folders[0]
        self.select(second)
        self.window.sidebar.add_folder()  # третий — нельзя
        self.assertEqual(len(second.folders), 0)

    def test_duplicate_is_deep_copy(self):
        req = self.window.editor.current_request()
        req.timeout = 7.0
        self.select(req)
        before = len(self.all_requests())
        self.window.sidebar.duplicate_current()
        self.assertEqual(len(self.all_requests()), before + 1)
        clone = self.all_requests()[-1]
        self.assertNotEqual(clone.id, req.id)
        self.assertEqual(clone.timeout, 7.0)

    def test_move_and_copy_between_folders(self):
        a, b = models.Folder("A"), models.Folder("B")
        req = models.Request("R")
        a.requests.append(req)
        self.ws.folders += [a, b]
        self.window.sidebar.set_workspace(self.ws)

        QtWidgets.QInputDialog.getItem = staticmethod(lambda *a, **k: ("B", True))
        self.window.sidebar._move_to(self.find_item(req))
        self.assertIn(req, b.requests)
        self.assertNotIn(req, a.requests)

        QtWidgets.QInputDialog.getItem = staticmethod(lambda *a, **k: ("A", True))
        self.window.sidebar._copy_to(self.find_item(req))
        self.assertEqual(len(a.requests), 1)
        self.assertNotEqual(a.requests[0].id, req.id)  # копия, а не тот же объект
        self.assertIn(req, b.requests)  # оригинал остался


class TestUndoRedo(GuiTestCase):
    def test_undo_restores_deleted_request(self):
        req = self.window.editor.current_request()
        self.select(req)
        count = len(self.all_requests())
        self.window.sidebar._delete_current()
        self.assertEqual(len(self.all_requests()), count - 1)

        self.window.controller.undo_stack.undo()
        self.assertEqual(len(self.all_requests()), count)
        # Идентификатор сохраняется — выбор восстанавливается.
        self.assertIn(req.id, [r.id for r in self.all_requests()])

    def test_undo_restores_deleted_folder_with_content(self):
        folder = models.Folder("Grp")
        folder.requests.append(models.Request("Inner"))
        self.ws.folders.append(folder)
        self.window.sidebar.set_workspace(self.ws)
        self.select(folder)
        self.window.sidebar._delete_current()
        self.assertEqual(self.ws.folders, [])

        self.window.controller.undo_stack.undo()
        self.assertEqual(len(self.ws.folders), 1)
        self.assertEqual(self.ws.folders[0].requests[0].name, "Inner")

    def test_redo_after_undo(self):
        self.window.sidebar.add_request()
        count = len(self.all_requests())
        self.window.controller.undo_stack.undo()
        self.assertEqual(len(self.all_requests()), count - 1)
        self.window.controller.undo_stack.redo()
        self.assertEqual(len(self.all_requests()), count)

    def test_rename_is_undoable(self):
        req = self.window.editor.current_request()
        original = req.name
        item = self.find_item(req)
        item.setText(0, "• Переименован")
        self.assertEqual(req.name, "Переименован")
        self.window.controller.undo_stack.undo()
        self.assertEqual(
            [r.name for r in self.all_requests() if r.id == req.id][0], original
        )


class TestSecrets(GuiTestCase):
    def test_export_strips_secrets_by_default(self):
        from getpost_gui import share

        req = self.window.editor.current_request()
        req.auth_type = models.AUTH_BEARER
        req.auth_bearer_token = "SECRET-TOKEN"
        self.ws.variables = {"api_key": "SECRET-KEY", "base_url": "https://api.io"}

        text = share.export_str(self.ws)
        self.assertNotIn("SECRET-TOKEN", text)
        self.assertNotIn("SECRET-KEY", text)
        self.assertIn("https://api.io", text)

    def test_export_does_not_damage_live_data(self):
        from getpost_gui import share

        self.ws.variables = {"api_key": "KEEP-ME"}
        share.export_str(self.ws)
        self.assertEqual(self.ws.variables["api_key"], "KEEP-ME")

    def test_secret_masking_in_table(self):
        table = KeyValueTable("Переменная", "Значение", secret_column=True)
        table.set_items([{"enabled": True, "key": "token", "value": "abc123", "secret": True}])
        table.set_secret_masked(True)
        # В ячейке — маска, но get_items отдаёт настоящее значение.
        self.assertEqual(table.table.item(0, 2).text(), MASK_TEXT)
        self.assertEqual(table.get_items()[0]["value"], "abc123")
        table.set_secret_masked(False)
        self.assertEqual(table.table.item(0, 2).text(), "abc123")

    def test_masked_cell_is_not_editable(self):
        table = KeyValueTable("K", "V", secret_column=True)
        table.set_items([{"enabled": True, "key": "t", "value": "v", "secret": True}])
        table.set_secret_masked(True)
        flags = table.table.item(0, 2).flags()
        self.assertFalse(bool(flags & Qt.ItemFlag.ItemIsEditable))


class TestCaptureTab(GuiTestCase):
    def test_capture_rules_sync_to_model(self):
        req = self.window.editor.current_request()
        editor = self.window.editor
        editor._capture_insert_row(True, "token", models.CAPTURE_JSON, "data.token")
        self.assertEqual(len(req.captures), 1)
        self.assertEqual(req.captures[0]["name"], "token")
        self.assertEqual(req.captures[0]["expr"], "data.token")

    def test_captures_applied_after_response(self):
        req = self.window.editor.current_request()
        req.captures = [
            {"enabled": True, "name": "token", "source": models.CAPTURE_JSON, "expr": "access_token"}
        ]
        self.window._sending_req = req
        data = ResponseData(
            200, "OK", [("Content-Type", "application/json")],
            '{"access_token": "AT-1"}', 5.0, 24, "http://x", "application/json", True,
        )
        self.window._on_response(data)
        self.assertEqual(self.ws.variables.get("token"), "AT-1")

    def test_capture_problem_is_reported(self):
        req = self.window.editor.current_request()
        req.captures = [
            {"enabled": True, "name": "x", "source": models.CAPTURE_JSON, "expr": "nope"}
        ]
        self.window._sending_req = req
        data = ResponseData(200, "OK", [], "{}", 1.0, 2, "http://x", "application/json", True)
        self.window._on_response(data)
        self.assertTrue(self.window.response.notice.isVisible())


class TestResponseView(GuiTestCase):
    def _response(self, **kwargs):
        defaults = dict(
            status_code=200, reason="OK",
            headers=[("Content-Type", "application/json")],
            text='{"a":1,"b":[1,2]}', elapsed_ms=5.0, size_bytes=17,
            url="http://x", content_type="application/json", ok=True,
            content=b'{"a":1,"b":[1,2]}', cookies=[("session", "abc")],
        )
        defaults.update(kwargs)
        return ResponseData(**defaults)

    def test_pretty_and_raw(self):
        view = self.window.response
        view.show_response(self._response())
        self.assertIn("\n", view.body_edit.toPlainText())  # отформатировано
        view.pretty_check.setChecked(False)
        self.assertEqual(view.body_edit.toPlainText(), '{"a":1,"b":[1,2]}')

    def test_cookies_and_html_preview(self):
        view = self.window.response
        view.show_response(
            self._response(content_type="text/html", text="<h1>Hi</h1>", content=b"<h1>Hi</h1>")
        )
        self.assertEqual(view.cookies_table.rowCount(), 1)
        self.assertEqual(view.preview_stack.currentIndex(), 0)  # HTML

    def test_sent_request_tab(self):
        view = self.window.response
        view.show_sent_request(
            "POST", "http://x",
            {"headers": {"X-Key": "1"}, "data": b'{"a":1}', "params": [("q", "2")]},
        )
        text = view.sent_view.toPlainText()
        self.assertIn("POST http://x", text)
        self.assertIn("X-Key: 1", text)
        self.assertIn('{"a":1}', text)
        self.assertIn("q = 2", text)

    def test_history_limits_memory(self):
        req = self.window.editor.current_request()
        self.window._sending_req = req
        for _ in range(12):
            self.window._on_response(self._response())
        history = self.window._history[req.id]
        self.assertLessEqual(len(history), 10)
        # У старых записей тело выброшено, у последних — сохранено.
        self.assertEqual(history[0].content, b"")
        self.assertNotEqual(history[-1].content, b"")


class TestSendingState(GuiTestCase):
    def test_send_button_becomes_cancel(self):
        editor = self.window.editor
        self.assertEqual(editor.send_btn.text(), "Send")
        editor.set_sending(True)
        self.assertEqual(editor.send_btn.text(), "Cancel")
        # Нажатие во время отправки просит отмену, а не новую отправку.
        received = []
        editor.cancel_requested.connect(lambda: received.append("cancel"))
        editor.send_btn.click()
        self.assertEqual(received, ["cancel"])
        editor.set_sending(False)
        self.assertEqual(editor.send_btn.text(), "Send")

    def test_empty_url_reports_error(self):
        """Пустой URL — понятная ошибка, без сетевого запроса."""
        self.type_url("")
        self.window._on_send()
        self.assertIn("URL", self.window.response.body_edit.toPlainText())
        self.assertIsNone(self.window._runner)  # запрос не запускался


class TestVariableWarning(GuiTestCase):
    def test_unresolved_variable_warns(self):
        editor = self.window.editor
        editor.set_known_variables(["base_url"])
        self.type_url("{{base_url}}/x")
        self.assertFalse(editor.var_warning.isVisible())

        self.type_url("{{unknown_var}}/x")
        self.assertTrue(editor.var_warning.isVisible())
        self.assertIn("unknown_var", editor.var_warning.text())


class TestFormDataFileUpload(GuiTestCase):
    def test_file_column_present_and_value_convention(self):
        from getpost_gui import http_client

        table = self.window.editor.form_data_table
        self.assertGreaterEqual(table._col_file, 0)  # кнопка выбора файла есть
        path = os.path.join(self.config_dir, "up.txt")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("DATA")

        req = self.window.editor.current_request()
        req.method = "POST"
        req.url = "http://x"
        req.body_type = models.BODY_FORM_DATA
        req.body_form = [{"enabled": True, "key": "file", "value": f"@{path}"}]
        _, _, kwargs = http_client.build_request_kwargs(req, {})
        self.assertEqual(kwargs["files"][0][1][0], "up.txt")
        self.assertEqual(kwargs["files"][0][1][1], b"DATA")


class TestQuickOpen(GuiTestCase):
    def test_fuzzy_filter_finds_request(self):
        from getpost_gui.views.dialogs import QuickOpenDialog

        req = models.Request("Create user")
        req.url = "https://api.io/users"
        self.ws.requests.append(req)
        items = list(self.window._iter_all_requests())
        dialog = QuickOpenDialog(items)
        dialog._refilter("creuse")  # нестрогое совпадение
        self.assertGreaterEqual(dialog.list.count(), 1)
        self.assertIs(dialog.selected_request(), req)

    def test_filter_by_url(self):
        from getpost_gui.views.dialogs import QuickOpenDialog

        req = models.Request("Anything")
        req.url = "https://special.example/path"
        self.ws.requests.append(req)
        dialog = QuickOpenDialog(list(self.window._iter_all_requests()))
        dialog._refilter("special")
        self.assertIs(dialog.selected_request(), req)


class TestImportExportGui(GuiTestCase):
    def setUp(self):
        super().setUp()
        self.work_dir = tempfile.mkdtemp(prefix="getpost_files_")
        self._save_target = {"path": ""}
        self._open_target = {"path": ""}
        QtWidgets.QFileDialog.getSaveFileName = staticmethod(
            lambda *a, **k: (self._save_target["path"], "")
        )
        QtWidgets.QFileDialog.getOpenFileName = staticmethod(
            lambda *a, **k: (self._open_target["path"], "")
        )

    def test_export_then_import_request(self):
        req = self.window.editor.current_request()
        self._save_target["path"] = os.path.join(self.work_dir, "req.getpost.json")
        self.window._export_object(req)
        self.assertTrue(os.path.exists(self._save_target["path"]))

        count = len(self.all_requests())
        self._open_target["path"] = self._save_target["path"]
        self.window._import_item()
        self.assertEqual(len(self.all_requests()), count + 1)
        self.assertNotEqual(self.all_requests()[-1].id, req.id)  # новые id

    def test_import_workspace_dedupes_name(self):
        self._save_target["path"] = os.path.join(self.work_dir, "ws.getpost.json")
        self.window._export_workspace()
        count = len(self.window.workspaces)
        self._open_target["path"] = self._save_target["path"]
        self.window._import_item()
        self.assertEqual(len(self.window.workspaces), count + 1)
        self.assertTrue(any("(импорт)" in w.name for w in self.window.workspaces))


class TestAutosave(GuiTestCase):
    def test_changes_persist_to_disk(self):
        req = self.window.editor.current_request()
        self.type_url("https://saved.example")
        self.window._flush_save()

        reloaded = self.storage.load_all_workspaces()
        found = None
        for ws in reloaded:
            for r in self.all_requests(ws):
                if r.id == req.id:
                    found = r
        self.assertIsNotNone(found)
        self.assertEqual(found.url, "https://saved.example")

    def test_save_error_is_surfaced(self):
        """Ошибка записи не должна проходить молча."""
        def boom(_ws):
            raise OSError(28, "No space left on device")

        self.window.storage.save_workspace = boom
        self.window._do_autosave()
        self.assertIn("НЕ СОХРАНЕНО", self.window.status.currentMessage())


@unittest.skipUnless(QT_AVAILABLE, "Qt недоступен")
class TestControllerUnit(unittest.TestCase):
    """Контроллер отдельно от окна."""

    def setUp(self):
        self.ws = models.Workspace("W")
        self.controller = WorkspaceController()
        self.controller.set_workspace(self.ws)

    def test_empty_transaction_not_pushed(self):
        with self.controller.transaction("Ничего"):
            pass
        self.assertEqual(self.controller.undo_stack.count(), 0)

    def test_transaction_pushes_once(self):
        with self.controller.transaction("Добавление"):
            self.ws.requests.append(models.Request("R"))
        self.assertEqual(self.controller.undo_stack.count(), 1)

    def test_nested_transaction_is_single_command(self):
        with self.controller.transaction("Внешняя"):
            self.ws.requests.append(models.Request("A"))
            with self.controller.transaction("Внутренняя"):
                self.ws.requests.append(models.Request("B"))
        self.assertEqual(self.controller.undo_stack.count(), 1)
        self.controller.undo_stack.undo()
        self.assertEqual(self.ws.requests, [])

    def test_switching_workspace_clears_history(self):
        with self.controller.transaction("Добавление"):
            self.ws.requests.append(models.Request("R"))
        self.controller.set_workspace(models.Workspace("Other"))
        self.assertEqual(self.controller.undo_stack.count(), 0)


if __name__ == "__main__":
    unittest.main()
