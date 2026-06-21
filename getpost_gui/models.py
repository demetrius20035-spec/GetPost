"""Модель данных GetPost.

Иерархия: ``Workspace`` → ``Folder`` (до 2 уровней) → ``Request``.

Все классы — обычный Python без зависимости от Qt и полностью
сериализуются в JSON-совместимые словари (``to_dict`` / ``from_dict``),
поэтому их легко тестировать и сохранять в файлы.
"""
from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

# --- HTTP-методы -----------------------------------------------------------
HTTP_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE"]
# Методы, для которых по умолчанию имеет смысл тело запроса.
METHODS_WITH_BODY = {"POST", "PUT", "PATCH", "DELETE"}

# --- Типы тела запроса -----------------------------------------------------
BODY_NONE = "none"
BODY_RAW = "raw"
BODY_FORM_DATA = "form-data"
BODY_URLENCODED = "x-www-form-urlencoded"
BODY_TYPES = [BODY_NONE, BODY_RAW, BODY_FORM_DATA, BODY_URLENCODED]

# --- Язык "сырого" тела (для подсветки и Content-Type) ---------------------
RAW_TEXT = "text"
RAW_JSON = "json"
RAW_XML = "xml"
RAW_LANGS = [RAW_JSON, RAW_TEXT, RAW_XML]

# --- Типы авторизации ------------------------------------------------------
AUTH_NONE = "none"
AUTH_BASIC = "basic"
AUTH_BEARER = "bearer"
AUTH_TYPES = [AUTH_NONE, AUTH_BASIC, AUTH_BEARER]

# Максимальная глубина вложенности папок (Workspace → 1 → 2).
MAX_FOLDER_DEPTH = 2


def new_id() -> str:
    """Сгенерировать уникальный идентификатор."""
    return uuid.uuid4().hex


def _coerce_choice(value: Any, choices: List[str], default: str) -> str:
    """Вернуть ``value`` если оно среди допустимых, иначе ``default``."""
    return value if value in choices else default


def normalize_kv_list(raw: Any) -> List[Dict[str, Any]]:
    """Нормализовать список пар «ключ-значение».

    Каждый элемент приводится к виду
    ``{"enabled": bool, "key": str, "value": str}``.
    """
    items: List[Dict[str, Any]] = []
    if isinstance(raw, list):
        for it in raw:
            if not isinstance(it, dict):
                continue
            items.append(
                {
                    "enabled": bool(it.get("enabled", True)),
                    "key": str(it.get("key", "")),
                    "value": str(it.get("value", "")),
                }
            )
    return items


class Request:
    """HTTP-запрос со всеми параметрами."""

    def __init__(self, name: str = "New Request", id: Optional[str] = None):
        self.id: str = id or new_id()
        self.name: str = name
        self.method: str = "GET"
        self.url: str = ""
        # Списки пар ключ-значение: [{"enabled", "key", "value"}, ...]
        self.params: List[Dict[str, Any]] = []
        self.headers: List[Dict[str, Any]] = []
        # Тело запроса
        self.body_type: str = BODY_NONE
        self.body_raw: str = ""
        self.body_raw_lang: str = RAW_JSON
        # Используется и для form-data, и для x-www-form-urlencoded
        self.body_form: List[Dict[str, Any]] = []
        # Авторизация
        self.auth_type: str = AUTH_NONE
        self.auth_basic_username: str = ""
        self.auth_basic_password: str = ""
        self.auth_bearer_token: str = ""

    # -- сериализация -------------------------------------------------------
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "method": self.method,
            "url": self.url,
            "params": self.params,
            "headers": self.headers,
            "body_type": self.body_type,
            "body_raw": self.body_raw,
            "body_raw_lang": self.body_raw_lang,
            "body_form": self.body_form,
            "auth_type": self.auth_type,
            "auth_basic_username": self.auth_basic_username,
            "auth_basic_password": self.auth_basic_password,
            "auth_bearer_token": self.auth_bearer_token,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Request":
        r = cls(name=str(d.get("name", "New Request")), id=d.get("id"))
        r.method = _coerce_choice(d.get("method"), HTTP_METHODS, "GET")
        r.url = str(d.get("url", ""))
        r.params = normalize_kv_list(d.get("params"))
        r.headers = normalize_kv_list(d.get("headers"))
        r.body_type = _coerce_choice(d.get("body_type"), BODY_TYPES, BODY_NONE)
        r.body_raw = str(d.get("body_raw", ""))
        r.body_raw_lang = _coerce_choice(d.get("body_raw_lang"), RAW_LANGS, RAW_JSON)
        r.body_form = normalize_kv_list(d.get("body_form"))
        r.auth_type = _coerce_choice(d.get("auth_type"), AUTH_TYPES, AUTH_NONE)
        r.auth_basic_username = str(d.get("auth_basic_username", ""))
        r.auth_basic_password = str(d.get("auth_basic_password", ""))
        r.auth_bearer_token = str(d.get("auth_bearer_token", ""))
        return r


class Folder:
    """Папка: содержит вложенные папки и запросы."""

    def __init__(self, name: str = "New Folder", id: Optional[str] = None):
        self.id: str = id or new_id()
        self.name: str = name
        self.folders: List["Folder"] = []
        self.requests: List[Request] = []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "folders": [f.to_dict() for f in self.folders],
            "requests": [r.to_dict() for r in self.requests],
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Folder":
        f = cls(name=str(d.get("name", "New Folder")), id=d.get("id"))
        f.folders = [Folder.from_dict(x) for x in d.get("folders", []) if isinstance(x, dict)]
        f.requests = [Request.from_dict(x) for x in d.get("requests", []) if isinstance(x, dict)]
        return f


class Workspace:
    """Рабочее пространство — корень иерархии."""

    def __init__(self, name: str = "My Workspace", id: Optional[str] = None):
        self.id: str = id or new_id()
        self.name: str = name
        # Переменные окружения: {"base_url": "https://...", ...}
        self.variables: Dict[str, str] = {}
        self.folders: List[Folder] = []
        self.requests: List[Request] = []
        # Путь к файлу на диске (заполняется хранилищем, не сериализуется).
        self.file_path: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "variables": self.variables,
            "folders": [f.to_dict() for f in self.folders],
            "requests": [r.to_dict() for r in self.requests],
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Workspace":
        ws = cls(name=str(d.get("name", "My Workspace")), id=d.get("id"))
        variables = d.get("variables", {})
        if isinstance(variables, dict):
            ws.variables = {str(k): str(v) for k, v in variables.items()}
        ws.folders = [Folder.from_dict(x) for x in d.get("folders", []) if isinstance(x, dict)]
        ws.requests = [Request.from_dict(x) for x in d.get("requests", []) if isinstance(x, dict)]
        return ws
