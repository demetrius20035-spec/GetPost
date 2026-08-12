"""Генерация кода запроса на разных языках.

Все генераторы работают от одного источника — :func:`build_request_kwargs`,
поэтому сгенерированный код соответствует тому, что реально отправит GetPost.

Доступные цели: ``curl`` (см. :mod:`getpost_gui.curl`), ``python``
(requests), ``javascript`` (fetch), ``httpie``.
"""
from __future__ import annotations

import json
import shlex
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlencode, urlsplit, urlunsplit, parse_qsl

from . import curl as curl_mod
from . import http_client, models

LANG_CURL = "curl"
LANG_PYTHON = "python"
LANG_JS = "javascript"
LANG_HTTPIE = "httpie"

LANGUAGES = [
    (LANG_CURL, "cURL"),
    (LANG_PYTHON, "Python (requests)"),
    (LANG_JS, "JavaScript (fetch)"),
    (LANG_HTTPIE, "HTTPie"),
]


def _url_with_params(url: str, params) -> str:
    if not params:
        return url
    sp = urlsplit(url)
    query = urlencode(parse_qsl(sp.query, keep_blank_values=True) + list(params))
    return urlunsplit((sp.scheme, sp.netloc, sp.path, query, sp.fragment))


def _body_text(kwargs: Dict) -> Optional[str]:
    data = kwargs.get("data")
    if isinstance(data, (bytes, bytearray)):
        return data.decode("utf-8", "replace")
    if isinstance(data, str):
        return data
    return None


def _form_pairs(kwargs: Dict) -> Optional[List[Tuple[str, str]]]:
    data = kwargs.get("data")
    return list(data) if isinstance(data, list) else None


def _files_pairs(kwargs: Dict):
    """Вернуть [(имя, значение|путь, is_file), ...] для multipart."""
    result = []
    for key, filetuple in kwargs.get("files") or []:
        filename, content = filetuple[0], filetuple[1]
        if filename:
            result.append((key, filename, True))
        else:
            result.append((key, content, False))
    return result


def _py_repr(value) -> str:
    return json.dumps(value, ensure_ascii=False) if isinstance(value, str) else repr(value)


def to_python(req: models.Request, variables: Optional[Dict[str, str]] = None) -> str:
    """Сгенерировать сниппет на Python (библиотека ``requests``)."""
    method, url, kwargs = http_client.build_request_kwargs(req, variables or {})
    lines = ["import requests", ""]

    headers = kwargs.get("headers") or {}
    if headers:
        lines.append("headers = {")
        for key, value in headers.items():
            lines.append(f"    {_py_repr(key)}: {_py_repr(value)},")
        lines.append("}")

    params = kwargs.get("params")
    if params:
        lines.append("params = [")
        for key, value in params:
            lines.append(f"    ({_py_repr(key)}, {_py_repr(value)}),")
        lines.append("]")

    raw = _body_text(kwargs)
    form = _form_pairs(kwargs)
    files = _files_pairs(kwargs)
    if raw is not None:
        if req.body_raw_lang == models.RAW_JSON:
            try:
                parsed = json.loads(raw)
                lines.append(f"json_body = {parsed!r}")
            except (ValueError, TypeError):
                lines.append(f"data = {_py_repr(raw)}")
        else:
            lines.append(f"data = {_py_repr(raw)}")
    elif form is not None:
        lines.append("data = {")
        for key, value in form:
            lines.append(f"    {_py_repr(key)}: {_py_repr(value)},")
        lines.append("}")
    elif files:
        lines.append("files = {")
        for key, value, is_file in files:
            if is_file:
                lines.append(f"    {_py_repr(key)}: open({_py_repr(value)}, 'rb'),")
            else:
                lines.append(f"    {_py_repr(key)}: (None, {_py_repr(value)}),")
        lines.append("}")

    auth = kwargs.get("auth")
    call = [f"    {_py_repr(method)}", f"    {_py_repr(url)}"]
    if headers:
        call.append("    headers=headers")
    if params:
        call.append("    params=params")
    if raw is not None:
        if req.body_raw_lang == models.RAW_JSON and any(ln.startswith("json_body") for ln in lines):
            call.append("    json=json_body")
        else:
            call.append("    data=data")
    elif form is not None:
        call.append("    data=data")
    elif files:
        call.append("    files=files")
    if auth is not None and hasattr(auth, "username"):
        call.append(f"    auth=({_py_repr(auth.username)}, {_py_repr(auth.password)})")
    if not req.follow_redirects:
        call.append("    allow_redirects=False")
    if not req.verify_ssl:
        call.append("    verify=False")
    call.append(f"    timeout={int(req.timeout or http_client.DEFAULT_TIMEOUT)}")

    lines.append("")
    lines.append("response = requests.request(")
    lines.append(",\n".join(call) + ",")
    lines.append(")")
    lines.append("print(response.status_code)")
    lines.append("print(response.text)")
    return "\n".join(lines)


def to_javascript(req: models.Request, variables: Optional[Dict[str, str]] = None) -> str:
    """Сгенерировать сниппет на JavaScript (``fetch``)."""
    method, url, kwargs = http_client.build_request_kwargs(req, variables or {})
    full_url = _url_with_params(url, kwargs.get("params"))

    headers = dict(kwargs.get("headers") or {})
    auth = kwargs.get("auth")
    if auth is not None and hasattr(auth, "username"):
        import base64

        token = base64.b64encode(f"{auth.username}:{auth.password}".encode()).decode()
        headers["Authorization"] = f"Basic {token}"

    options: List[str] = [f'  method: {json.dumps(method)}']
    if headers:
        rendered = ",\n".join(f"    {json.dumps(k)}: {json.dumps(v)}" for k, v in headers.items())
        options.append("  headers: {\n" + rendered + ",\n  }")

    raw = _body_text(kwargs)
    form = _form_pairs(kwargs)
    files = _files_pairs(kwargs)
    prelude: List[str] = []
    if raw is not None:
        options.append(f"  body: {json.dumps(raw)}")
    elif form is not None:
        rendered = ", ".join(f"[{json.dumps(k)}, {json.dumps(v)}]" for k, v in form)
        prelude.append(f"const body = new URLSearchParams([{rendered}]);")
        options.append("  body")
    elif files:
        prelude.append("const body = new FormData();")
        for key, value, is_file in files:
            if is_file:
                prelude.append(f"// добавьте файл: body.append({json.dumps(key)}, fileInput.files[0]);")
            else:
                prelude.append(f"body.append({json.dumps(key)}, {json.dumps(value)});")
        options.append("  body")
    if not req.follow_redirects:
        options.append('  redirect: "manual"')

    lines = list(prelude)
    if lines:
        lines.append("")
    lines.append(f"const response = await fetch({json.dumps(full_url)}, {{")
    lines.append(",\n".join(options) + ",")
    lines.append("});")
    lines.append("console.log(response.status);")
    lines.append("console.log(await response.text());")
    return "\n".join(lines)


def to_httpie(req: models.Request, variables: Optional[Dict[str, str]] = None) -> str:
    """Сгенерировать команду HTTPie."""
    method, url, kwargs = http_client.build_request_kwargs(req, variables or {})
    tokens = ["http"]
    if not req.verify_ssl:
        tokens.append("--verify=no")
    if req.follow_redirects:
        tokens.append("--follow")
    if req.timeout:
        tokens.append(f"--timeout={int(req.timeout)}")
    auth = kwargs.get("auth")
    if auth is not None and hasattr(auth, "username"):
        tokens += ["-a", f"{auth.username}:{auth.password}"]

    raw = _body_text(kwargs)
    if raw is not None and req.body_raw_lang == models.RAW_JSON:
        tokens.append("--json")
    tokens += [method, _url_with_params(url, kwargs.get("params"))]

    for key, value in (kwargs.get("headers") or {}).items():
        tokens.append(f"{key}:{value}")
    for key, value in _form_pairs(kwargs) or []:
        tokens.append(f"{key}={value}")
    for key, value, is_file in _files_pairs(kwargs):
        tokens.append(f"{key}@{value}" if is_file else f"{key}={value}")

    command = " ".join(shlex.quote(t) for t in tokens)
    if raw is not None:
        # Сырое тело передаём через stdin — так HTTPie отправит его как есть.
        return f"echo {shlex.quote(raw)} | {command}"
    return command


_GENERATORS = {
    LANG_PYTHON: to_python,
    LANG_JS: to_javascript,
    LANG_HTTPIE: to_httpie,
}


def generate(language: str, req: models.Request, variables: Optional[Dict[str, str]] = None) -> str:
    """Сгенерировать код на указанном языке."""
    if language == LANG_CURL:
        return curl_mod.to_curl(req, variables)
    generator = _GENERATORS.get(language)
    if generator is None:
        raise ValueError(f"Неизвестный язык: {language}")
    return generator(req, variables)
