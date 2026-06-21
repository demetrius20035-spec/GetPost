"""Выполнение HTTP-запроса в фоновом потоке (QThread).

Сетевой вызов вынесен из главного потока, поэтому интерфейс не подвисает
во время ожидания ответа. Результат передаётся через сигналы Qt.
"""
from __future__ import annotations

from typing import Any, Dict

import requests

from . import http_client
from .qtcompat import QtCore, Signal


class RequestRunner(QtCore.QThread):
    """Поток, выполняющий один подготовленный запрос."""

    # Успех: передаётся объект ResponseData.
    succeeded = Signal(object)
    # Ошибка: передаётся понятное пользователю сообщение.
    failed = Signal(str)

    def __init__(
        self,
        method: str,
        url: str,
        kwargs: Dict[str, Any],
        timeout: float = http_client.DEFAULT_TIMEOUT,
        parent: QtCore.QObject = None,
    ):
        super().__init__(parent)
        self._method = method
        self._url = url
        self._kwargs = kwargs
        self._timeout = timeout

    def run(self) -> None:  # noqa: D401 - вызывается Qt в отдельном потоке
        try:
            data = http_client.perform_prepared(
                self._method, self._url, self._kwargs, timeout=self._timeout
            )
            self.succeeded.emit(data)
        except requests.exceptions.Timeout:
            self.failed.emit(f"Превышено время ожидания ответа ({self._timeout} с)")
        except requests.exceptions.SSLError as exc:
            self.failed.emit(f"Ошибка SSL: {exc}")
        except requests.exceptions.ConnectionError:
            self.failed.emit("Не удалось подключиться к серверу. Проверьте URL и соединение.")
        except requests.exceptions.MissingSchema:
            self.failed.emit("Некорректный URL: отсутствует схема (например, http:// или https://).")
        except requests.exceptions.InvalidURL:
            self.failed.emit("Некорректный URL.")
        except requests.exceptions.RequestException as exc:
            self.failed.emit(f"Ошибка запроса: {exc}")
        except Exception as exc:  # на всякий случай — любая иная ошибка
            self.failed.emit(f"Непредвиденная ошибка: {exc}")
