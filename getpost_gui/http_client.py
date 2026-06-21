"""Построение и выполнение HTTP-запросов.

Логика разделена на «чистую» часть (``build_request_kwargs`` — собирает
аргументы для библиотеки ``requests`` без сети и без Qt) и выполнение
(``perform_prepared`` / ``perform_request``). Благодаря этому основную логику
легко покрыть тестами без реальной сети.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Tuple

import requests

from . import models
from .variables import substitute

# Тайм-аут запроса по умолчанию (секунды).
DEFAULT_TIMEOUT = 30


class ResponseData:
    """Готовый к отображению результат запроса (не зависит от ``requests``)."""

    def __init__(
        self,
        status_code: int,
        reason: str,
        headers: List[Tuple[str, str]],
        text: str,
        elapsed_ms: float,
        size_bytes: int,
        url: str,
        content_type: str,
        ok: bool,
        content: bytes = b"",
        cookies: Optional[List[Tuple[str, str]]] = None,
    ):
        self.status_code = status_code
        self.reason = reason
        self.headers = headers
        self.text = text
        self.elapsed_ms = elapsed_ms
        self.size_bytes = size_bytes
        self.url = url
        self.content_type = content_type
        self.ok = ok
        self.content = content
        self.cookies = cookies or []

    @property
    def status_line(self) -> str:
        reason = f" {self.reason}" if self.reason else ""
        return f"{self.status_code}{reason}"


def _enabled_pairs(items: List[Dict[str, Any]], variables: Dict[str, str]) -> List[Tuple[str, str]]:
    """Отобрать включённые пары ключ-значение и подставить переменные.

    Пары с пустым ключом пропускаются.
    """
    pairs: List[Tuple[str, str]] = []
    for it in items:
        if not it.get("enabled", True):
            continue
        key = substitute(str(it.get("key", "")), variables)
        if not key:
            continue
        value = substitute(str(it.get("value", "")), variables)
        pairs.append((key, value))
    return pairs


def _has_header(headers: List[Tuple[str, str]], name: str) -> bool:
    name = name.lower()
    return any(k.lower() == name for k, _ in headers)


def build_request_kwargs(
    req: models.Request, variables: Optional[Dict[str, str]] = None
) -> Tuple[str, str, Dict[str, Any]]:
    """Собрать ``(method, url, kwargs)`` для ``requests.request``.

    Чистая функция: не выполняет сетевых вызовов и не зависит от Qt.
    """
    variables = variables or {}
    method = req.method.upper()
    url = substitute(req.url, variables).strip()

    headers = _enabled_pairs(req.headers, variables)
    params = _enabled_pairs(req.params, variables)

    kwargs: Dict[str, Any] = {}

    # --- авторизация ---
    if req.auth_type == models.AUTH_BASIC:
        from requests.auth import HTTPBasicAuth

        kwargs["auth"] = HTTPBasicAuth(
            substitute(req.auth_basic_username, variables),
            substitute(req.auth_basic_password, variables),
        )
    elif req.auth_type == models.AUTH_BEARER:
        token = substitute(req.auth_bearer_token, variables)
        if not _has_header(headers, "authorization"):
            headers.append(("Authorization", f"Bearer {token}"))

    # --- тело запроса ---
    if req.body_type == models.BODY_RAW:
        raw = substitute(req.body_raw, variables)
        kwargs["data"] = raw.encode("utf-8")
        if raw and not _has_header(headers, "content-type"):
            content_types = {
                models.RAW_JSON: "application/json",
                models.RAW_XML: "application/xml",
                models.RAW_TEXT: "text/plain",
            }
            ct = content_types.get(req.body_raw_lang, "text/plain")
            headers.append(("Content-Type", f"{ct}; charset=utf-8"))
    elif req.body_type == models.BODY_URLENCODED:
        # requests сам выставит Content-Type: application/x-www-form-urlencoded
        kwargs["data"] = _enabled_pairs(req.body_form, variables)
    elif req.body_type == models.BODY_FORM_DATA:
        # multipart/form-data: текстовые поля передаются как (None, value)
        pairs = _enabled_pairs(req.body_form, variables)
        if pairs:
            kwargs["files"] = [(k, (None, v)) for k, v in pairs]

    # requests ожидает dict для заголовков (CaseInsensitiveDict).
    if headers:
        kwargs["headers"] = dict(headers)
    if params:
        kwargs["params"] = params

    return method, url, kwargs


def perform_prepared(
    method: str,
    url: str,
    kwargs: Dict[str, Any],
    timeout: float = DEFAULT_TIMEOUT,
    session: Optional[requests.Session] = None,
) -> ResponseData:
    """Выполнить уже подготовленный запрос и вернуть ``ResponseData``."""
    if not url:
        raise ValueError("URL пуст")

    caller = session if session is not None else requests
    start = time.perf_counter()
    resp = caller.request(method, url, timeout=timeout, **kwargs)
    content = resp.content  # принудительно читаем тело в этом потоке
    text = resp.text
    elapsed_ms = (time.perf_counter() - start) * 1000.0

    return ResponseData(
        status_code=resp.status_code,
        reason=resp.reason or "",
        headers=list(resp.headers.items()),
        text=text,
        elapsed_ms=elapsed_ms,
        size_bytes=len(content),
        url=resp.url,
        content_type=resp.headers.get("Content-Type", ""),
        ok=resp.ok,
        content=content,
        cookies=list(resp.cookies.items()),
    )


def perform_request(
    req: models.Request,
    variables: Optional[Dict[str, str]] = None,
    timeout: float = DEFAULT_TIMEOUT,
    session: Optional[requests.Session] = None,
) -> ResponseData:
    """Удобная обёртка: собрать и выполнить запрос за один вызов."""
    method, url, kwargs = build_request_kwargs(req, variables)
    return perform_prepared(method, url, kwargs, timeout=timeout, session=session)
