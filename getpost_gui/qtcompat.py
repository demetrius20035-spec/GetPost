"""Слой совместимости между PySide6 и PyQt6.

Импортирует один из доступных биндингов Qt и приводит различия в API к
единому виду, чтобы остальной код не зависел от выбранной библиотеки.

Приоритет: PySide6 (LGPL, официальный биндинг Qt), затем PyQt6.
Переопределить выбор можно переменной окружения ``GETPOST_QT_API``
(значения: ``PySide6`` или ``PyQt6``).
"""
from __future__ import annotations

import os

QT_API = None

_preferred = os.environ.get("GETPOST_QT_API")
_order = ["PySide6", "PyQt6"]
if _preferred in _order:
    _order.remove(_preferred)
    _order.insert(0, _preferred)

_errors = []
for _api in _order:
    try:
        if _api == "PySide6":
            from PySide6 import QtCore, QtGui, QtWidgets  # noqa: F401
            from PySide6.QtCore import Signal, Slot  # noqa: F401
            QT_API = "PySide6"
            break
        else:
            from PyQt6 import QtCore, QtGui, QtWidgets  # noqa: F401
            from PyQt6.QtCore import pyqtSignal as Signal  # noqa: F401
            from PyQt6.QtCore import pyqtSlot as Slot  # noqa: F401
            QT_API = "PyQt6"
            break
    except ImportError as exc:  # pragma: no cover - зависит от окружения
        _errors.append(f"{_api}: {exc}")

if QT_API is None:  # pragma: no cover - зависит от окружения
    raise ImportError(
        "Не найден ни один из биндингов Qt (PySide6 или PyQt6). "
        "Установите один из них: pip install PySide6\n"
        + "\n".join(_errors)
    )

# Удобные псевдонимы для часто используемых перечислений Qt.
Qt = QtCore.Qt

__all__ = ["QtCore", "QtGui", "QtWidgets", "Signal", "Slot", "Qt", "QT_API"]
