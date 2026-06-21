"""Импорт и экспорт запросов в формате команды ``curl``.

* :func:`to_curl`   — собрать строку ``curl`` из модели запроса
  (переиспользует :func:`getpost_gui.http_client.build_request_kwargs`, поэтому
  поведение совпадает с реальной отправкой).
* :func:`from_curl` — разобрать команду ``curl`` обратно в модель запроса.

Модуль не зависит от Qt и легко тестируется.
"""
from __future__ import annotations

import base64
import shlex
from typing import Dict, List, Optional
from urllib.parse import urlencode, urlsplit, urlunsplit, parse_qsl

from . import http_client, models


def _looks_json(text: str) -> bool:
    return (text or "").lstrip()[:1] in "{["


def _split_kv(item: str):
    key, sep, value = item.partition("=")
    return key, (value if sep else "")


# --------------------------------------------------------------------------
# Экспорт: Request -> curl
# --------------------------------------------------------------------------
def to_curl(req: models.Request, variables: Optional[Dict[str, str]] = None) -> str:
    """Сформировать команду ``curl`` для запроса (переменные подставляются)."""
    method, url, kwargs = http_client.build_request_kwargs(req, variables or {})

    # Параметры запроса добавляем прямо в URL.
    params = kwargs.get("params")
    if params:
        sp = urlsplit(url)
        existing = parse_qsl(sp.query, keep_blank_values=True)
        query = urlencode(existing + list(params))
        url = urlunsplit((sp.scheme, sp.netloc, sp.path, query, sp.fragment))

    tokens: List[str] = ["curl"]
    if method != "GET":
        tokens += ["-X", method]
    tokens.append(url)

    for key, value in (kwargs.get("headers") or {}).items():
        tokens += ["-H", f"{key}: {value}"]

    auth = kwargs.get("auth")
    if auth is not None and hasattr(auth, "username"):
        tokens += ["-u", f"{auth.username}:{auth.password}"]

    data = kwargs.get("data")
    if isinstance(data, (bytes, bytearray)):
        tokens += ["--data-raw", data.decode("utf-8", "replace")]
    elif isinstance(data, str):
        tokens += ["--data-raw", data]
    elif isinstance(data, list):  # urlencoded
        for key, value in data:
            tokens += ["--data-urlencode", f"{key}={value}"]

    for key, filetuple in (kwargs.get("files") or []):
        filename, content = filetuple[0], filetuple[1]
        if filename:  # это файл
            tokens += ["-F", f"{key}=@{filename}"]
        else:
            tokens += ["-F", f"{key}={content}"]

    if req.follow_redirects:
        tokens.append("-L")
    if not req.verify_ssl:
        tokens.append("-k")
    if req.timeout:
        tokens += ["--max-time", str(int(req.timeout))]

    return " ".join(shlex.quote(t) for t in tokens)


# --------------------------------------------------------------------------
# Импорт: curl -> Request
# --------------------------------------------------------------------------
# Флаги, которые принимают значение следующим токеном.
_VALUE_FLAGS = {
    "-X", "--request", "-H", "--header", "-d", "--data", "--data-raw",
    "--data-ascii", "--data-binary", "--data-urlencode", "-F", "--form",
    "-u", "--user", "-b", "--cookie", "-A", "--user-agent", "-e", "--referer",
    "--url", "--max-time", "--connect-timeout", "-m",
}
# Булевы флаги без значения.
_BOOL_FLAGS = {
    "-L", "--location", "-k", "--insecure", "-G", "--get", "--compressed",
    "-s", "--silent", "-v", "--verbose", "-i", "--include", "-#", "--progress-bar",
    "-f", "--fail",
}


def from_curl(text: str) -> models.Request:
    """Разобрать команду ``curl`` в модель :class:`~getpost_gui.models.Request`."""
    text = text.strip()
    # Убираем переносы строк с обратным слешем и ведущий '$'.
    text = text.replace("\\\n", " ").replace("\\\r\n", " ")
    if text.startswith("$"):
        text = text[1:].strip()

    tokens = shlex.split(text)
    if tokens and tokens[0] == "curl":
        tokens = tokens[1:]

    req = models.Request(name="Импорт из cURL")
    method: Optional[str] = None
    url = ""
    headers: List[Dict] = []
    data_items: List[str] = []          # из -d/--data
    urlencode_items: List[str] = []     # из --data-urlencode
    form_items: List[str] = []          # из -F/--form
    get_with_data = False

    i = 0
    while i < len(tokens):
        tok = tokens[i]

        def take_value() -> str:
            nonlocal i
            # Поддержка вида --header=value и -Hvalue.
            if tok.startswith("--") and "=" in tok:
                return tok.split("=", 1)[1]
            if len(tok) > 2 and not tok.startswith("--"):
                return tok[2:]
            i += 1
            return tokens[i] if i < len(tokens) else ""

        base = tok.split("=", 1)[0] if tok.startswith("--") else tok[:2] if tok.startswith("-") and len(tok) > 2 else tok

        if base in ("-X", "--request"):
            method = take_value().upper()
        elif base in ("-H", "--header"):
            raw = take_value()
            k, _, v = raw.partition(":")
            headers.append({"enabled": True, "key": k.strip(), "value": v.strip()})
        elif base in ("-d", "--data", "--data-raw", "--data-ascii", "--data-binary"):
            data_items.append(take_value())
        elif base == "--data-urlencode":
            urlencode_items.append(take_value())
        elif base in ("-F", "--form"):
            form_items.append(take_value())
        elif base in ("-u", "--user"):
            user, _, pwd = take_value().partition(":")
            req.auth_type = models.AUTH_BASIC
            req.auth_basic_username = user
            req.auth_basic_password = pwd
        elif base in ("-b", "--cookie"):
            headers.append({"enabled": True, "key": "Cookie", "value": take_value()})
        elif base in ("-A", "--user-agent"):
            headers.append({"enabled": True, "key": "User-Agent", "value": take_value()})
        elif base in ("-e", "--referer"):
            headers.append({"enabled": True, "key": "Referer", "value": take_value()})
        elif base in ("-m", "--max-time", "--connect-timeout"):
            try:
                req.timeout = float(take_value())
            except ValueError:
                pass
        elif base == "--url":
            url = take_value()
        elif base in ("-L", "--location"):
            req.follow_redirects = True
        elif base in ("-k", "--insecure"):
            req.verify_ssl = False
        elif base in ("-G", "--get"):
            get_with_data = True
        elif tok in _BOOL_FLAGS:
            pass  # игнорируемые флаги
        elif tok.startswith("-"):
            # Неизвестный флаг: если выглядит как принимающий значение — съедаем токен.
            if tok in _VALUE_FLAGS:
                take_value()
        else:
            if not url:
                url = tok
        i += 1

    # Извлекаем query-параметры из URL в таблицу Params.
    if url:
        sp = urlsplit(url)
        if sp.query:
            for k, v in parse_qsl(sp.query, keep_blank_values=True):
                req.params.append({"enabled": True, "key": k, "value": v})
            url = urlunsplit((sp.scheme, sp.netloc, sp.path, "", sp.fragment))
    req.url = url

    # Авторизация из заголовка Authorization (Bearer/Basic) — переносим в Auth.
    kept_headers = []
    for h in headers:
        if h["key"].lower() == "authorization":
            value = h["value"]
            if value.startswith("Bearer "):
                req.auth_type = models.AUTH_BEARER
                req.auth_bearer_token = value[len("Bearer "):]
                continue
            if value.startswith("Basic "):
                try:
                    decoded = base64.b64decode(value[len("Basic "):]).decode("utf-8")
                    user, _, pwd = decoded.partition(":")
                    req.auth_type = models.AUTH_BASIC
                    req.auth_basic_username = user
                    req.auth_basic_password = pwd
                    continue
                except Exception:
                    pass
        kept_headers.append(h)
    req.headers = kept_headers

    # Тело запроса.
    if form_items:
        req.body_type = models.BODY_FORM_DATA
        req.body_form = [
            {"enabled": True, "key": k, "value": v} for k, v in (_split_kv(f) for f in form_items)
        ]
    elif urlencode_items:
        req.body_type = models.BODY_URLENCODED
        req.body_form = [
            {"enabled": True, "key": k, "value": v} for k, v in (_split_kv(x) for x in urlencode_items)
        ]
        if get_with_data:
            req.params += req.body_form
            req.body_form = []
            req.body_type = models.BODY_NONE
    elif data_items:
        joined = "&".join(data_items)
        if get_with_data:
            for part in joined.split("&"):
                k, v = _split_kv(part)
                req.params.append({"enabled": True, "key": k, "value": v})
        elif len(data_items) == 1 and _looks_json(data_items[0]):
            req.body_type = models.BODY_RAW
            req.body_raw = data_items[0]
            req.body_raw_lang = models.RAW_JSON
        elif all("=" in d for d in data_items):
            req.body_type = models.BODY_URLENCODED
            req.body_form = [
                {"enabled": True, "key": k, "value": v}
                for k, v in (_split_kv(d) for d in data_items)
            ]
        else:
            req.body_type = models.BODY_RAW
            req.body_raw = joined
            req.body_raw_lang = models.RAW_TEXT

    # Метод: явный -X, иначе POST при наличии тела, иначе GET.
    if method:
        req.method = method if method in models.HTTP_METHODS else "GET"
    elif req.body_type != models.BODY_NONE:
        req.method = "POST"
    else:
        req.method = "GET"

    return req
