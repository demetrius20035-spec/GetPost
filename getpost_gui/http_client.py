"""Построение и выполнение HTTP-запросов.

Логика разделена на «чистую» часть (``build_request_kwargs`` — собирает
аргументы для библиотеки ``requests`` без сети и без Qt) и выполнение
(``perform_prepared`` / ``perform_request``). Благодаря этому основную логику
легко покрыть тестами без реальной сети.
"""
from __future__ import annotations

import mimetypes
import os
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

import requests

from . import models
from .variables import substitute

# Тайм-аут запроса по умолчанию (секунды).
DEFAULT_TIMEOUT = 30

# Максимальный размер тела ответа, который читаем в память (16 МБ).
# Всё, что больше, обрезается — интерфейс не должен падать от гигантского файла.
MAX_RESPONSE_BYTES = 16 * 1024 * 1024

# Размер блока при потоковом чтении (позволяет прерывать загрузку).
_CHUNK = 64 * 1024

# Префикс значения поля form-data, означающий «это файл»: ``key=@/path/to/file``.
FILE_PREFIX = "@"


class Cancelled(Exception):
    """Запрос был отменён пользователем."""


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
        # Тело было обрезано по лимиту MAX_RESPONSE_BYTES.
        self.truncated = False

    @property
    def status_line(self) -> str:
        reason = f" {self.reason}" if self.reason else ""
        return f"{self.status_code}{reason}"

    def drop_body(self) -> None:
        """Освободить память под телом, оставив метаданные (для истории)."""
        self.content = b""
        self.text = ""


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


def is_file_value(value: str) -> bool:
    """Значение поля означает файл (``@/path/to/file``)?"""
    return isinstance(value, str) and value.startswith(FILE_PREFIX) and len(value) > 1


def build_multipart(pairs: List[Tuple[str, str]]) -> List[Tuple[str, Tuple]]:
    """Собрать ``files`` для multipart/form-data.

    Значение ``@путь`` читается как файл (с определением MIME-типа), остальные
    поля отправляются как обычные текстовые части. Используется и GUI, и CLI.
    """
    files: List[Tuple[str, Tuple]] = []
    for key, value in pairs:
        if is_file_value(value):
            path = value[len(FILE_PREFIX):]
            ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
            with open(path, "rb") as fh:
                content = fh.read()
            files.append((key, (os.path.basename(path), content, ctype)))
        else:
            files.append((key, (None, value)))
    return files


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
        # multipart/form-data: текстовые поля — (None, value); значение вида
        # "@/path/to/file" отправляется как файл.
        pairs = _enabled_pairs(req.body_form, variables)
        if pairs:
            kwargs["files"] = build_multipart(pairs)

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
    max_bytes: int = MAX_RESPONSE_BYTES,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> ResponseData:
    """Выполнить уже подготовленный запрос и вернуть ``ResponseData``.

    Тело читается потоком блоками: это позволяет прервать скачивание
    (``should_cancel``) и не читать в память больше ``max_bytes``.
    """
    if not url:
        raise ValueError("URL пуст")

    caller = session if session is not None else requests
    start = time.perf_counter()
    resp = caller.request(method, url, timeout=timeout, stream=True, **kwargs)
    try:
        chunks: List[bytes] = []
        total = 0
        truncated = False
        for chunk in resp.iter_content(chunk_size=_CHUNK):
            if should_cancel is not None and should_cancel():
                raise Cancelled()
            if not chunk:
                continue
            total += len(chunk)
            if total > max_bytes:
                # Забираем «хвост» до лимита и прекращаем чтение.
                allowed = max_bytes - (total - len(chunk))
                if allowed > 0:
                    chunks.append(chunk[:allowed])
                truncated = True
                break
            chunks.append(chunk)
        content = b"".join(chunks)
        elapsed_ms = (time.perf_counter() - start) * 1000.0

        # Кодировку берём только из заголовков: тело уже вычитано потоком,
        # поэтому resp.apparent_encoding обращаться к нему не может.
        encoding = resp.encoding
        if encoding:
            try:
                text = content.decode(encoding, "replace")
            except LookupError:  # неизвестное имя кодировки
                text = content.decode("utf-8", "replace")
        else:
            # Без charset в Content-Type: JSON и большинство API — UTF-8,
            # а latin-1 как запасной вариант декодирует любые байты.
            try:
                text = content.decode("utf-8")
            except UnicodeDecodeError:
                text = content.decode("latin-1", "replace")

        data = ResponseData(
            status_code=resp.status_code,
            reason=resp.reason or "",
            headers=list(resp.headers.items()),
            text=text,
            elapsed_ms=elapsed_ms,
            size_bytes=total,
            url=resp.url,
            content_type=resp.headers.get("Content-Type", ""),
            ok=resp.ok,
            content=content,
            cookies=list(resp.cookies.items()),
        )
        data.truncated = truncated
        return data
    finally:
        resp.close()


def perform_request(
    req: models.Request,
    variables: Optional[Dict[str, str]] = None,
    timeout: float = DEFAULT_TIMEOUT,
    session: Optional[requests.Session] = None,
) -> ResponseData:
    """Удобная обёртка: собрать и выполнить запрос за один вызов."""
    method, url, kwargs = build_request_kwargs(req, variables)
    return perform_prepared(method, url, kwargs, timeout=timeout, session=session)
