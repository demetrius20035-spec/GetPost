"""Левая панель: выбор Workspace и дерево папок/запросов.

Дерево отражает иерархию ``Workspace → Folder → Request``. Поддерживаются
создание, переименование (двойной клик / F2) и удаление элементов, а также
контекстное меню. Вложенность папок ограничена двумя уровнями.
"""
from __future__ import annotations

from typing import List, Optional, Tuple, Union

from .. import models
from ..qtcompat import Qt, QtGui, QtWidgets, Signal

ROLE_OBJ = Qt.ItemDataRole.UserRole

Container = Union[models.Workspace, models.Folder]


class _RequestTree(QtWidgets.QTreeWidget):
    """Дерево с drag&drop, не нарушающим лимит вложенности папок."""

    dropped = Signal()

    @staticmethod
    def _is_folder(item) -> bool:
        return item is not None and isinstance(item.data(0, ROLE_OBJ), models.Folder)

    @staticmethod
    def _depth(item) -> int:
        depth = 0
        while item is not None:
            depth += 1
            item = item.parent()
        return depth

    def _folder_height(self, item) -> int:
        subs = [
            self._folder_height(item.child(i))
            for i in range(item.childCount())
            if self._is_folder(item.child(i))
        ]
        return 1 + (max(subs) if subs else 0)

    @staticmethod
    def _is_ancestor(ancestor, item) -> bool:
        node = item
        while node is not None:
            if node is ancestor:
                return True
            node = node.parent()
        return False

    def _drop_allowed(self, event) -> bool:
        pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
        target = self.itemAt(pos)
        indicator = self.dropIndicatorPosition()
        Pos = QtWidgets.QAbstractItemView.DropIndicatorPosition

        # Нельзя бросать элемент внутрь запроса.
        if indicator == Pos.OnItem and target is not None and not self._is_folder(target):
            return False

        # Определяем глубину контейнера, куда попадут перемещаемые элементы.
        if indicator == Pos.OnItem and self._is_folder(target):
            container_depth = self._depth(target)
            container_item = target
        elif target is not None and indicator in (Pos.AboveItem, Pos.BelowItem):
            container_item = target.parent()
            container_depth = self._depth(container_item)  # 0, если верхний уровень
        else:
            container_item = None
            container_depth = 0

        for it in self.selectedItems():
            # Запрет циклов: нельзя вложить папку в саму себя/потомка.
            if container_item is not None and self._is_ancestor(it, container_item):
                return False
            if self._is_folder(it):
                if container_depth + self._folder_height(it) > models.MAX_FOLDER_DEPTH:
                    return False
        return True

    def dropEvent(self, event) -> None:  # noqa: N802 - имя задано Qt
        if not self._drop_allowed(event):
            event.ignore()
            return
        super().dropEvent(event)
        self.dropped.emit()


class Sidebar(QtWidgets.QWidget):
    """Навигация по Workspace и его содержимому."""

    request_selected = Signal(object)        # выбран Request
    structure_changed = Signal()             # изменилось дерево → автосохранение
    item_renamed = Signal(object)            # переименован объект (Folder/Request)
    copy_curl_requested = Signal(object)     # «Copy as cURL» для запроса
    environment_switched = Signal(str)       # выбрано другое окружение
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

        # Выбор активного окружения.
        env_row = QtWidgets.QHBoxLayout()
        env_row.addWidget(QtWidgets.QLabel("Окружение:"))
        self.env_combo = QtWidgets.QComboBox()
        self.env_combo.setToolTip("Активное окружение переменных")
        self.env_combo.currentIndexChanged.connect(self._on_env_combo_changed)
        env_row.addWidget(self.env_combo, 1)
        layout.addLayout(env_row)

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
        self.tree = _RequestTree()
        self.tree.setHeaderHidden(True)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.setDragEnabled(True)
        self.tree.setAcceptDrops(True)
        self.tree.setDropIndicatorShown(True)
        self.tree.setDragDropMode(QtWidgets.QAbstractItemView.DragDropMode.InternalMove)
        self.tree.customContextMenuRequested.connect(self._show_context_menu)
        self.tree.currentItemChanged.connect(self._on_current_item_changed)
        self.tree.itemChanged.connect(self._on_item_changed)
        self.tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        self.tree.dropped.connect(self._on_dropped)
        layout.addWidget(self.tree, 1)

        # Удаление по клавише Delete.
        del_shortcut = QtGui.QShortcut(QtGui.QKeySequence(QtGui.QKeySequence.StandardKey.Delete), self.tree)
        del_shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)
        del_shortcut.activated.connect(self._delete_current)

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
        self.set_environments(ws)
        self._rebuild_tree()

    def set_environments(self, ws: Optional[models.Workspace]) -> None:
        self.env_combo.blockSignals(True)
        self.env_combo.clear()
        if ws is not None:
            for name in ws.env_names():
                self.env_combo.addItem(name)
            idx = self.env_combo.findText(ws.active_env)
            if idx >= 0:
                self.env_combo.setCurrentIndex(idx)
        self.env_combo.blockSignals(False)

    def _on_ws_combo_changed(self, index: int) -> None:
        ws_id = self.ws_combo.itemData(index)
        if ws_id:
            self.workspace_switched.emit(ws_id)

    def _on_env_combo_changed(self, index: int) -> None:
        name = self.env_combo.itemText(index)
        if name:
            self.environment_switched.emit(name)

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
            menu.addAction("Дублировать", lambda: self._duplicate_item(item))
            if isinstance(obj, models.Request):
                menu.addAction("Copy as cURL", lambda: self.copy_curl_requested.emit(obj))
            menu.addAction("Переименовать", lambda: self.tree.editItem(item, 0))
            menu.addAction("Удалить", lambda: self._delete_item(item))
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    # -- дублирование / drag&drop ------------------------------------------
    def _duplicate_item(self, item) -> None:
        obj = self._obj_of(item)
        if obj is None or self._ws is None:
            return
        container = self._container_of_item(item)
        parent_item = item.parent()
        if isinstance(obj, models.Folder):
            clone = obj.clone()
            container.folders.append(clone)
            new_item = self._add_folder_item(parent_item, clone)
        else:
            clone = obj.clone()
            container.requests.append(clone)
            new_item = self._add_request_item(parent_item, clone)
        if parent_item is not None:
            parent_item.setExpanded(True)
        self.tree.setCurrentItem(new_item)
        self.structure_changed.emit()

    def _delete_current(self) -> None:
        item = self.tree.currentItem()
        if item is not None:
            self._delete_item(item)

    def duplicate_current(self) -> None:
        item = self.tree.currentItem()
        if item is not None:
            self._duplicate_item(item)

    def add_imported_request(self, req: models.Request) -> None:
        """Добавить готовый запрос (например, импортированный из cURL)."""
        if self._ws is None:
            return
        container, parent_item = self._target_for_new()
        container.requests.append(req)
        new_item = self._add_request_item(parent_item, req)
        if parent_item is not None:
            parent_item.setExpanded(True)
        self.tree.setCurrentItem(new_item)
        self.structure_changed.emit()

    def _on_dropped(self) -> None:
        self._rebuild_model_from_tree()
        self.tree.expandAll()
        self.structure_changed.emit()

    def _rebuild_model_from_tree(self) -> None:
        """Перестроить модель Workspace по текущему виду дерева (после DnD)."""
        if self._ws is None:
            return
        self._ws.folders = []
        self._ws.requests = []

        def collect(parent_item, container: Container) -> None:
            for i in range(parent_item.childCount()):
                it = parent_item.child(i)
                obj = self._obj_of(it)
                if isinstance(obj, models.Folder):
                    obj.folders = []
                    obj.requests = []
                    container.folders.append(obj)
                    collect(it, obj)
                elif isinstance(obj, models.Request):
                    container.requests.append(obj)

        collect(self.tree.invisibleRootItem(), self._ws)

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
