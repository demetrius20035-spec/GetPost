"""Левая панель: выбор Workspace и дерево папок/запросов.

Дерево отражает иерархию ``Workspace → Folder → Request``. Поддерживаются
создание, переименование (двойной клик / F2) и удаление элементов, а также
контекстное меню. Вложенность папок ограничена двумя уровнями.
"""
from __future__ import annotations

from typing import List, Optional, Tuple, Union

from .. import models
from ..qtcompat import Qt, QtWidgets, Signal

ROLE_OBJ = Qt.ItemDataRole.UserRole

Container = Union[models.Workspace, models.Folder]


class Sidebar(QtWidgets.QWidget):
    """Навигация по Workspace и его содержимому."""

    request_selected = Signal(object)        # выбран Request
    structure_changed = Signal()             # изменилось дерево → автосохранение
    item_renamed = Signal(object)            # переименован объект (Folder/Request)
    workspace_switched = Signal(str)         # выбран другой Workspace (по id)
    new_workspace_requested = Signal()
    rename_workspace_requested = Signal()
    delete_workspace_requested = Signal()
    edit_variables_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._ws: Optional[models.Workspace] = None
        self._building = False
        self._build_ui()

    # -- построение интерфейса ---------------------------------------------
    def _build_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        # Выбор Workspace + меню управления.
        ws_row = QtWidgets.QHBoxLayout()
        self.ws_combo = QtWidgets.QComboBox()
        self.ws_combo.setToolTip("Текущее рабочее пространство")
        self.ws_combo.currentIndexChanged.connect(self._on_ws_combo_changed)

        self.ws_menu_btn = QtWidgets.QToolButton()
        self.ws_menu_btn.setText("⋮")
        self.ws_menu_btn.setToolTip("Управление рабочими пространствами")
        self.ws_menu_btn.setPopupMode(QtWidgets.QToolButton.ToolButtonPopupMode.InstantPopup)
        ws_menu = QtWidgets.QMenu(self.ws_menu_btn)
        ws_menu.addAction("Новое рабочее пространство", self.new_workspace_requested.emit)
        ws_menu.addAction("Переименовать", self.rename_workspace_requested.emit)
        ws_menu.addAction("Удалить", self.delete_workspace_requested.emit)
        ws_menu.addSeparator()
        ws_menu.addAction("Переменные…", self.edit_variables_requested.emit)
        self.ws_menu_btn.setMenu(ws_menu)

        ws_row.addWidget(self.ws_combo, 1)
        ws_row.addWidget(self.ws_menu_btn)
        layout.addLayout(ws_row)

        # Кнопки создания папок/запросов.
        btn_row = QtWidgets.QHBoxLayout()
        self.add_folder_btn = QtWidgets.QToolButton()
        self.add_folder_btn.setText("+ Папка")
        self.add_folder_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.add_folder_btn.clicked.connect(self.add_folder)
        self.add_request_btn = QtWidgets.QToolButton()
        self.add_request_btn.setText("+ Запрос")
        self.add_request_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.add_request_btn.clicked.connect(self.add_request)
        btn_row.addWidget(self.add_folder_btn)
        btn_row.addWidget(self.add_request_btn)
        btn_row.addStretch(1)
        layout.addLayout(btn_row)

        # Дерево.
        self.tree = QtWidgets.QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._show_context_menu)
        self.tree.currentItemChanged.connect(self._on_current_item_changed)
        self.tree.itemChanged.connect(self._on_item_changed)
        self.tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        layout.addWidget(self.tree, 1)

    # -- работа с Workspace -------------------------------------------------
    def set_workspaces(self, workspaces: List[models.Workspace], current_id: Optional[str]) -> None:
        self.ws_combo.blockSignals(True)
        self.ws_combo.clear()
        for ws in workspaces:
            self.ws_combo.addItem(ws.name, ws.id)
        idx = self.ws_combo.findData(current_id)
        if idx >= 0:
            self.ws_combo.setCurrentIndex(idx)
        self.ws_combo.blockSignals(False)

    def set_workspace(self, ws: Optional[models.Workspace]) -> None:
        self._ws = ws
        if ws is not None:
            idx = self.ws_combo.findData(ws.id)
            if idx >= 0 and idx != self.ws_combo.currentIndex():
                self.ws_combo.blockSignals(True)
                self.ws_combo.setCurrentIndex(idx)
                self.ws_combo.blockSignals(False)
        self._rebuild_tree()

    def _on_ws_combo_changed(self, index: int) -> None:
        ws_id = self.ws_combo.itemData(index)
        if ws_id:
            self.workspace_switched.emit(ws_id)

    # -- построение дерева --------------------------------------------------
    def _rebuild_tree(self) -> None:
        self._building = True
        try:
            self.tree.clear()
            if self._ws is None:
                return
            for folder in self._ws.folders:
                self._add_folder_item(None, folder)
            for req in self._ws.requests:
                self._add_request_item(None, req)
            self.tree.expandAll()
        finally:
            self._building = False

    def _new_item(self, parent_item, obj, icon_text: str) -> QtWidgets.QTreeWidgetItem:
        item = QtWidgets.QTreeWidgetItem([f"{icon_text} {obj.name}"])
        item.setData(0, ROLE_OBJ, obj)
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
        if parent_item is None:
            self.tree.addTopLevelItem(item)
        else:
            parent_item.addChild(item)
        return item

    def _add_folder_item(self, parent_item, folder: models.Folder) -> QtWidgets.QTreeWidgetItem:
        item = self._new_item(parent_item, folder, "📁")
        for sub in folder.folders:
            self._add_folder_item(item, sub)
        for req in folder.requests:
            self._add_request_item(item, req)
        return item

    def _add_request_item(self, parent_item, req: models.Request) -> QtWidgets.QTreeWidgetItem:
        return self._new_item(parent_item, req, "•")

    @staticmethod
    def _label_for(obj) -> str:
        icon = "📁" if isinstance(obj, models.Folder) else "•"
        return f"{icon} {obj.name}"

    # -- helpers для текущего выделения ------------------------------------
    @staticmethod
    def _obj_of(item) -> Optional[object]:
        return item.data(0, ROLE_OBJ) if item is not None else None

    def _container_of_item(self, item) -> Container:
        """Контейнер (Workspace или Folder), которому принадлежит элемент."""
        if item is None:
            return self._ws
        parent = item.parent()
        if parent is None:
            return self._ws
        return self._obj_of(parent)

    @staticmethod
    def _folder_depth(item) -> int:
        """Глубина папки в дереве (верхний уровень = 1)."""
        depth = 0
        node = item
        while node is not None:
            depth += 1
            node = node.parent()
        return depth

    def _target_for_new(self) -> Tuple[Container, Optional[QtWidgets.QTreeWidgetItem]]:
        """Куда добавлять новый элемент и какой пункт дерева раскрыть."""
        item = self.tree.currentItem()
        obj = self._obj_of(item)
        if isinstance(obj, models.Folder):
            return obj, item
        if isinstance(obj, models.Request):
            return self._container_of_item(item), item.parent()
        return self._ws, None

    # -- создание элементов -------------------------------------------------
    def add_folder(self) -> None:
        if self._ws is None:
            return
        container, parent_item = self._target_for_new()
        # Проверяем ограничение вложенности.
        container_depth = 0 if isinstance(container, models.Workspace) else self._folder_depth(parent_item)
        if container_depth >= models.MAX_FOLDER_DEPTH:
            QtWidgets.QMessageBox.information(
                self,
                "Ограничение вложенности",
                f"Папки можно вкладывать не глубже {models.MAX_FOLDER_DEPTH} уровней.",
            )
            return
        folder = models.Folder(name="Новая папка")
        container.folders.append(folder)
        new_item = self._add_folder_item(parent_item, folder)
        if parent_item is not None:
            parent_item.setExpanded(True)
        self.tree.setCurrentItem(new_item)
        self.structure_changed.emit()
        self.tree.editItem(new_item, 0)

    def add_request(self) -> None:
        if self._ws is None:
            return
        container, parent_item = self._target_for_new()
        req = models.Request(name="Новый запрос")
        container.requests.append(req)
        new_item = self._add_request_item(parent_item, req)
        if parent_item is not None:
            parent_item.setExpanded(True)
        self.tree.setCurrentItem(new_item)
        self.structure_changed.emit()
        self.tree.editItem(new_item, 0)

    # -- переименование / удаление -----------------------------------------
    def _on_item_double_clicked(self, item, column) -> None:
        self.tree.editItem(item, 0)

    def _on_item_changed(self, item, column) -> None:
        if self._building:
            return
        obj = self._obj_of(item)
        if obj is None:
            return
        # Текст в дереве содержит иконку — извлекаем имя.
        text = item.text(0)
        for prefix in ("📁 ", "• "):
            if text.startswith(prefix):
                text = text[len(prefix):]
                break
        new_name = text.strip()
        if not new_name:
            new_name = obj.name  # пустое имя не допускаем
        obj.name = new_name
        # Возвращаем иконку в подпись (без повторного срабатывания сигнала).
        self._building = True
        try:
            item.setText(0, self._label_for(obj))
        finally:
            self._building = False
        self.item_renamed.emit(obj)
        self.structure_changed.emit()

    def _delete_item(self, item) -> None:
        obj = self._obj_of(item)
        if obj is None or self._ws is None:
            return
        kind = "папку" if isinstance(obj, models.Folder) else "запрос"
        extra = ""
        if isinstance(obj, models.Folder) and (obj.folders or obj.requests):
            extra = "\nВсё её содержимое также будет удалено."
        reply = QtWidgets.QMessageBox.question(
            self,
            "Удаление",
            f"Удалить {kind} «{obj.name}»?{extra}",
            QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
            QtWidgets.QMessageBox.StandardButton.No,
        )
        if reply != QtWidgets.QMessageBox.StandardButton.Yes:
            return

        container = self._container_of_item(item)
        if isinstance(obj, models.Folder):
            container.folders.remove(obj)
        else:
            container.requests.remove(obj)
        (item.parent() or self.tree.invisibleRootItem()).removeChild(item)

        if isinstance(obj, models.Request):
            self.request_selected.emit(None)
        self.structure_changed.emit()

    # -- контекстное меню ---------------------------------------------------
    def _show_context_menu(self, pos) -> None:
        item = self.tree.itemAt(pos)
        obj = self._obj_of(item)
        menu = QtWidgets.QMenu(self)
        if item is not None:
            self.tree.setCurrentItem(item)

        menu.addAction("Новый запрос", self.add_request)
        menu.addAction("Новая папка", self.add_folder)
        if obj is not None:
            menu.addSeparator()
            menu.addAction("Переименовать", lambda: self.tree.editItem(item, 0))
            menu.addAction("Удалить", lambda: self._delete_item(item))
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    # -- выделение ----------------------------------------------------------
    def _on_current_item_changed(self, current, previous) -> None:
        if self._building:
            return
        obj = self._obj_of(current)
        if isinstance(obj, models.Request):
            self.request_selected.emit(obj)

    def update_item_name(self, obj) -> None:
        """Обновить подпись элемента дерева (например, после правки в редакторе)."""
        it = QtWidgets.QTreeWidgetItemIterator(self.tree)
        while it.value():
            item = it.value()
            if self._obj_of(item) is obj:
                self._building = True
                try:
                    item.setText(0, self._label_for(obj))
                finally:
                    self._building = False
                return
            it += 1

    def select_first_request(self) -> None:
        """Выбрать первый запрос в дереве (если есть)."""
        it = QtWidgets.QTreeWidgetItemIterator(self.tree)
        while it.value():
            item = it.value()
            if isinstance(self._obj_of(item), models.Request):
                self.tree.setCurrentItem(item)
                return
            it += 1
