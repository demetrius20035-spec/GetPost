"""OAuth 2.0 client credentials — получение токена по client_id/secret.

Реализован только поток ``client_credentials``: обычный POST на token endpoint,
без браузера и редиректов. Полученный токен кэшируется до истечения срока
жизни, чтобы не запрашивать его перед каждым запросом.

Модуль не зависит от Qt.
"""
from __future__ import annotations

import threading
import time
from typing import Dict, Optional, Tuple

import requests

from . import models
from .variables import substitute

# За сколько секунд до истечения считать токен просроченным.
EXPIRY_MARGIN = 30
# Если сервер не сообщил expires_in.
DEFAULT_LIFETIME = 3600


class TokenError(Exception):
    """Не удалось получить токен."""


class TokenCache:
    """Потокобезопасный кэш токенов по (token_url, client_id, scope).

    ``time_func`` можно подменить в тестах, чтобы проверять истечение срока
    без ожидания реального времени.
    """

    def __init__(self, time_func=time.monotonic):
        self._tokens: Dict[Tuple[str, str, str], Tuple[str, float]] = {}
        self._lock = threading.Lock()
        self._now = time_func

    def get(self, key: Tuple[str, str, str]) -> Optional[str]:
        with self._lock:
            entry = self._tokens.get(key)
            if entry is None:
                return None
            token, expires_at = entry
            if self._now() >= expires_at:
                del self._tokens[key]
                return None
            return token

    def put(self, key: Tuple[str, str, str], token: str, lifetime: float) -> None:
        with self._lock:
            # Обновляем чуть раньше истечения (EXPIRY_MARGIN), но токен со
            # совсем коротким сроком всё равно годится для текущего запроса.
            expires_at = self._now() + max(1.0, lifetime - EXPIRY_MARGIN)
            self._tokens[key] = (token, expires_at)

    def clear(self) -> None:
        with self._lock:
            self._tokens.clear()


# Общий кэш приложения.
cache = TokenCache()


def config_from(obj, variables: Optional[dict] = None) -> Dict[str, str]:
    """Собрать параметры OAuth2 из запроса/папки с подстановкой переменных."""
    variables = variables or {}
    return {
        "token_url": substitute(obj.auth_oauth2_token_url, variables).strip(),
        "client_id": substitute(obj.auth_oauth2_client_id, variables),
        "client_secret": substitute(obj.auth_oauth2_client_secret, variables),
        "scope": substitute(obj.auth_oauth2_scope, variables).strip(),
        "send_as": obj.auth_oauth2_send_as,
    }


def fetch_token(
    config: Dict[str, str],
    session: Optional[requests.Session] = None,
    timeout: float = 30,
    token_cache: Optional[TokenCache] = None,
    force: bool = False,
) -> str:
    """Получить токен (из кэша или запросом к token endpoint).

    Бросает :class:`TokenError` с понятным сообщением при неудаче.
    """
    token_url = config.get("token_url", "")
    if not token_url:
        raise TokenError("Не указан адрес token endpoint для OAuth2.")

    token_cache = token_cache if token_cache is not None else cache
    key = (token_url, config.get("client_id", ""), config.get("scope", ""))
    if not force:
        cached = token_cache.get(key)
        if cached:
            return cached

    data = {"grant_type": "client_credentials"}
    if config.get("scope"):
        data["scope"] = config["scope"]

    kwargs = {"data": data, "timeout": timeout}
    if config.get("send_as") == models.OAUTH_SEND_BASIC:
        kwargs["auth"] = (config.get("client_id", ""), config.get("client_secret", ""))
    else:
        data["client_id"] = config.get("client_id", "")
        data["client_secret"] = config.get("client_secret", "")

    caller = session if session is not None else requests
    try:
        response = caller.post(token_url, **kwargs)
    except requests.exceptions.RequestException as exc:
        raise TokenError(f"Не удалось обратиться к token endpoint: {exc}") from exc

    if response.status_code >= 400:
        raise TokenError(
            f"Token endpoint вернул {response.status_code}: {response.text[:200]}"
        )
    try:
        payload = response.json()
    except ValueError as exc:
        raise TokenError("Token endpoint вернул не JSON.") from exc

    token = payload.get("access_token")
    if not token:
        raise TokenError("В ответе token endpoint нет поля access_token.")

    lifetime = payload.get("expires_in", DEFAULT_LIFETIME)
    try:
        lifetime = float(lifetime)
    except (TypeError, ValueError):
        lifetime = DEFAULT_LIFETIME
    token_cache.put(key, str(token), lifetime)
    return str(token)
