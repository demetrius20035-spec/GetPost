"""Выполнение HTTP-запроса в фоновом потоке (QThread).

Сетевой вызов вынесен из главного потока, поэтому интерфейс не подвисает
во время ожидания ответа. Результат передаётся через сигналы Qt.

Поток можно отменить: :meth:`RequestRunner.cancel` прерывает скачивание тела
между блоками и подавляет доставку результата.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

import requests

from . import http_client, oauth
from .qtcompat import QtCore, Signal


class RequestRunner(QtCore.QThread):
    """Поток, выполняющий один подготовленный запрос."""

    # Успех: передаётся объект ResponseData.
    succeeded = Signal(object)
    # Ошибка: передаётся понятное пользователю сообщение.
    failed = Signal(str)
    # Запрос отменён пользователем.
    cancelled = Signal()

    def __init__(
        self,
        method: str,
        url: str,
        kwargs: Dict[str, Any],
        timeout: float = http_client.DEFAULT_TIMEOUT,
        session: Optional[requests.Session] = None,
        oauth_config: Optional[Dict[str, str]] = None,
        parent: QtCore.QObject = None,
    ):
        super().__init__(parent)
        self._method = method
        self._url = url
        self._kwargs = kwargs
        self._timeout = timeout
        self._session = session
        # Параметры OAuth2 client credentials: токен запрашивается в этом же
        # потоке перед основным запросом, чтобы интерфейс не блокировался.
        self._oauth_config = oauth_config
        self._cancelled = False

    # -- отмена -------------------------------------------------------------
    def cancel(self) -> None:
        """Пометить запрос как отменённый.

        Скачивание тела прерывается между блоками; если ответ ещё не пришёл,
        результат будет отброшен, а интерфейс разблокирован сразу.
        """
        self._cancelled = True

    def is_cancelled(self) -> bool:
        return self._cancelled

    # -- выполнение ---------------------------------------------------------
    def run(self) -> None:  # noqa: D401 - вызывается Qt в отдельном потоке
        try:
            if self._oauth_config:
                token = oauth.fetch_token(
                    self._oauth_config, session=self._session, timeout=self._timeout
                )
                if self._cancelled:
                    self.cancelled.emit()
                    return
                http_client.apply_oauth_token(self._kwargs, token)

            data = http_client.perform_prepared(
                self._method,
                self._url,
                self._kwargs,
                timeout=self._timeout,
                session=self._session,
                should_cancel=self.is_cancelled,
            )
            if self._cancelled:
                self.cancelled.emit()
                return
            self.succeeded.emit(data)
        except http_client.Cancelled:
            self.cancelled.emit()
        except oauth.TokenError as exc:
            self._fail(f"OAuth2: {exc}")
        except requests.exceptions.Timeout:
            self._fail(f"Превышено время ожидания ответа ({self._timeout} с)")
        except requests.exceptions.SSLError as exc:
            self._fail(f"Ошибка SSL: {exc}")
        except requests.exceptions.ConnectionError:
            self._fail("Не удалось подключиться к серверу. Проверьте URL и соединение.")
        except requests.exceptions.MissingSchema:
            self._fail("Некорректный URL: отсутствует схема (например, http:// или https://).")
        except requests.exceptions.InvalidURL:
            self._fail("Некорректный URL.")
        except FileNotFoundError as exc:
            self._fail(f"Файл для отправки не найден: {exc.filename}")
        except requests.exceptions.RequestException as exc:
            self._fail(f"Ошибка запроса: {exc}")
        except Exception as exc:  # на всякий случай — любая иная ошибка
            self._fail(f"Непредвиденная ошибка: {exc}")

    def _fail(self, message: str) -> None:
        """Сообщить об ошибке, если запрос не был отменён пользователем."""
        if self._cancelled:
            self.cancelled.emit()
        else:
            self.failed.emit(message)
