"""Диалоговые окна приложения."""
from __future__ import annotations

from typing import Dict

from ..qtcompat import QtWidgets
from .widgets import KeyValueTable


class VariablesDialog(QtWidgets.QDialog):
    """Редактор переменных Workspace (``{{имя}}`` → значение)."""

    def __init__(self, variables: Dict[str, str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Переменные рабочего пространства")
        self.resize(500, 360)

        layout = QtWidgets.QVBoxLayout(self)
        info = QtWidgets.QLabel(
            "Переменные можно использовать в URL, заголовках, параметрах и теле "
            "запроса в виде <code>{{имя}}</code>. Снимите флажок, чтобы временно "
            "отключить переменную."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        self.table = KeyValueTable("Переменная", "Значение")
        items = [{"enabled": True, "key": k, "value": v} for k, v in variables.items()]
        self.table.set_items(items)
        layout.addWidget(self.table, 1)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def variables(self) -> Dict[str, str]:
        result: Dict[str, str] = {}
        for it in self.table.get_items():
            key = str(it.get("key", "")).strip()
            if key and it.get("enabled", True):
                result[key] = str(it.get("value", ""))
        return result
