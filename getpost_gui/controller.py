"""Контроллер рабочего пространства — единая точка изменения модели.

Раньше модель правили напрямую из представления (дерево), из-за чего нельзя
было отменить действие. Теперь любое структурное изменение выполняется внутри
транзакции:

    with controller.transaction("Удаление папки"):
        container.folders.remove(folder)

Транзакция снимает «до» и «после» состояния Workspace и складывает их в
``QUndoStack``, поэтому ``Ctrl+Z`` возвращает удалённое, перемещённое или
переименованное. Снимки — обычные словари (``to_dict``), что делает отмену
надёжной для любых операций, включая drag & drop.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Dict, Optional

from . import models
from .qtcompat import QtCore, QtGui, Signal

# Сколько шагов отмены хранить.
UNDO_LIMIT = 50


def snapshot(ws: models.Workspace) -> Dict[str, Any]:
    """Снять состояние Workspace (структура + окружения)."""
    return ws.to_dict()


def restore(ws: models.Workspace, data: Dict[str, Any]) -> None:
    """Восстановить состояние Workspace из снимка (на месте, не заменяя объект).

    Объект Workspace остаётся тем же (на него ссылаются представления), а его
    содержимое заменяется. Идентификаторы вложенных объектов сохраняются, что
    позволяет заново выбрать тот же запрос после отмены.
    """
    fresh = models.Workspace.from_dict(data)
    ws.name = fresh.name
    ws.environments = fresh.environments
    ws.active_env = fresh.active_env
    ws.secret_vars = fresh.secret_vars
    ws.folders = fresh.folders
    ws.requests = fresh.requests


class _StructureCommand(QtGui.QUndoCommand):
    """Отменяемое изменение структуры Workspace (по снимкам «до»/«после»)."""

    def __init__(self, controller: "WorkspaceController", text: str, before: Dict, after: Dict):
        super().__init__(text)
        self._controller = controller
        self._before = before
        self._after = after
        self._first_redo = True

    def redo(self) -> None:  # noqa: D401 - вызывается Qt
        # Первый redo происходит в момент push() — модель уже изменена.
        if self._first_redo:
            self._first_redo = False
            return
        self._controller._apply(self._after)

    def undo(self) -> None:  # noqa: D401 - вызывается Qt
        self._controller._apply(self._before)


class WorkspaceController(QtCore.QObject):
    """Владеет текущим Workspace и историей отмен."""

    # Структура изменилась — представлениям нужно перестроиться.
    structure_changed = Signal()
    # Данные изменились — пора сохранять.
    modified = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.workspace: Optional[models.Workspace] = None
        self.undo_stack = QtGui.QUndoStack(self)
        self.undo_stack.setUndoLimit(UNDO_LIMIT)
        self._depth = 0  # вложенность транзакций

    # -- рабочее пространство ----------------------------------------------
    def set_workspace(self, ws: Optional[models.Workspace]) -> None:
        self.workspace = ws
        self.undo_stack.clear()  # история отмен не переносится между Workspace

    # -- транзакции ---------------------------------------------------------
    @contextmanager
    def transaction(self, description: str):
        """Выполнить изменение модели как отменяемую операцию.

        Если внутри ничего не изменилось, команда в стек не попадает.
        """
        ws = self.workspace
        if ws is None or self._depth > 0:
            # Без Workspace или во вложенной транзакции просто выполняем тело.
            yield
            return

        before = snapshot(ws)
        self._depth += 1
        try:
            yield
        finally:
            self._depth -= 1
        after = snapshot(ws)
        if after == before:
            return
        self.undo_stack.push(_StructureCommand(self, description, before, after))
        self.modified.emit()

    def _apply(self, data: Dict) -> None:
        """Применить снимок (используется отменой/повтором)."""
        if self.workspace is None:
            return
        restore(self.workspace, data)
        self.structure_changed.emit()
        self.modified.emit()

    # -- действия для меню --------------------------------------------------
    def create_undo_action(self, parent) -> QtGui.QAction:
        action = self.undo_stack.createUndoAction(parent, "Отменить")
        action.setShortcut(QtGui.QKeySequence.StandardKey.Undo)
        return action

    def create_redo_action(self, parent) -> QtGui.QAction:
        action = self.undo_stack.createRedoAction(parent, "Повторить")
        action.setShortcut(QtGui.QKeySequence.StandardKey.Redo)
        return action
