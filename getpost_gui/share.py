"""Импорт и экспорт элементов (Workspace / папка / запрос).

Формат обмена — самодостаточный JSON-«конверт»::

    {
      "getpost": "1.0",        # маркер формата и версия
      "type": "workspace",     # workspace | folder | request
      "exported_at": "...",    # ISO-время экспорта
      "data": { ... }          # сериализованный объект (to_dict)
    }

Такой файл (расширение ``.getpost.json``) можно переслать другому человеку и
импортировать на другой машине. При импорте всем элементам присваиваются новые
идентификаторы, поэтому существующие данные не затираются.

Модуль не зависит от Qt и легко тестируется.
"""
from __future__ import annotations

import datetime
import json
from typing import Tuple

from . import models

FORMAT_KEY = "getpost"
FORMAT_VERSION = "1.0"

KIND_WORKSPACE = "workspace"
KIND_FOLDER = "folder"
KIND_REQUEST = "request"
KINDS = (KIND_WORKSPACE, KIND_FOLDER, KIND_REQUEST)

# Рекомендуемое расширение файлов обмена.
FILE_EXTENSION = ".getpost.json"


def detect_kind(obj) -> str:
    if isinstance(obj, models.Workspace):
        return KIND_WORKSPACE
    if isinstance(obj, models.Folder):
        return KIND_FOLDER
    if isinstance(obj, models.Request):
        return KIND_REQUEST
    raise TypeError(f"Нельзя экспортировать объект типа {type(obj).__name__}")


# Поля запроса, содержащие секреты (вычищаются при экспорте по умолчанию).
SECRET_REQUEST_FIELDS = ("auth_basic_password", "auth_bearer_token")

# Эвристика: переменные с такими подстроками в имени считаются секретными,
# даже если пользователь не пометил их вручную.
_SECRET_NAME_HINTS = (
    "token", "secret", "password", "passwd", "pwd", "apikey", "api_key",
    "auth", "credential", "bearer", "private", "session",
)


def looks_secret(name: str) -> bool:
    """Похоже ли имя переменной на секрет (по общепринятым признакам)."""
    lowered = (name or "").lower().replace("-", "_")
    return any(hint in lowered for hint in _SECRET_NAME_HINTS)


def _strip_requests(node: dict) -> None:
    """Рекурсивно вычистить секреты из запросов в сериализованном узле."""
    for req in node.get("requests", []) or []:
        if isinstance(req, dict):
            for field in SECRET_REQUEST_FIELDS:
                if req.get(field):
                    req[field] = ""
    for folder in node.get("folders", []) or []:
        if isinstance(folder, dict):
            _strip_requests(folder)


def strip_secrets(data: dict, secret_vars=None) -> list:
    """Убрать секреты из сериализованных данных. Возвращает список того,
    что было вычищено (для показа пользователю)."""
    removed = []
    secret_vars = set(secret_vars or [])

    def count_requests(node: dict) -> int:
        total = sum(
            1
            for r in node.get("requests", []) or []
            if isinstance(r, dict) and any(r.get(f) for f in SECRET_REQUEST_FIELDS)
        )
        for f in node.get("folders", []) or []:
            if isinstance(f, dict):
                total += count_requests(f)
        return total

    n_auth = count_requests(data)
    if n_auth:
        removed.append(f"пароли/токены авторизации: {n_auth}")
    _strip_requests(data)

    # Значения секретных переменных окружений (имя остаётся — структура нужна).
    envs = data.get("environments")
    if isinstance(envs, dict):
        cleared = set()
        for env_vars in envs.values():
            if not isinstance(env_vars, dict):
                continue
            for name in list(env_vars):
                if name in secret_vars or looks_secret(name):
                    if env_vars[name]:
                        cleared.add(name)
                    env_vars[name] = ""
        if cleared:
            removed.append("переменные: " + ", ".join(sorted(cleared)))
    return removed


def export_dict(obj, include_secrets: bool = False) -> dict:
    """Сформировать «конверт» для экспорта объекта.

    По умолчанию секреты (пароли, токены, значения секретных переменных)
    вычищаются: экспортированный файл предназначен для обмена с другими людьми.
    """
    data = obj.to_dict()
    removed = []
    if not include_secrets:
        secret_vars = getattr(obj, "secret_vars", None)
        removed = strip_secrets(data, secret_vars)

    envelope = {
        FORMAT_KEY: FORMAT_VERSION,
        "type": detect_kind(obj),
        "exported_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "contains_secrets": bool(include_secrets),
        "data": data,
    }
    if removed:
        envelope["stripped"] = removed
    return envelope


def export_str(obj, include_secrets: bool = False) -> str:
    return json.dumps(export_dict(obj, include_secrets), ensure_ascii=False, indent=2)


def _reassign_request(req: models.Request) -> None:
    req.id = models.new_id()


def _reassign_folder(folder: models.Folder) -> None:
    folder.id = models.new_id()
    for req in folder.requests:
        _reassign_request(req)
    for sub in folder.folders:
        _reassign_folder(sub)


def reassign_ids(obj) -> None:
    """Присвоить новые идентификаторы объекту и всему его содержимому."""
    if isinstance(obj, models.Request):
        _reassign_request(obj)
    elif isinstance(obj, models.Folder):
        _reassign_folder(obj)
    elif isinstance(obj, models.Workspace):
        obj.id = models.new_id()
        for folder in obj.folders:
            _reassign_folder(folder)
        for req in obj.requests:
            _reassign_request(req)


def parse(text: str, reassign: bool = True) -> Tuple[str, object]:
    """Разобрать файл обмена. Возвращает ``(kind, object)``.

    Поддерживается и «сырой» файл Workspace (без конверта) — для совместимости
    с файлами из каталога конфигурации.
    """
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("Файл не содержит объекта JSON.")

    if FORMAT_KEY in data:
        kind = data.get("type")
        payload = data.get("data")
        if kind not in KINDS or not isinstance(payload, dict):
            raise ValueError("Некорректный формат файла GetPost.")
    else:
        # Фолбэк: возможно, это «сырой» файл Workspace.
        if any(k in data for k in ("requests", "folders", "environments", "variables")):
            kind = KIND_WORKSPACE
            payload = data
        else:
            raise ValueError("Неизвестный формат файла.")

    if kind == KIND_WORKSPACE:
        obj = models.Workspace.from_dict(payload)
    elif kind == KIND_FOLDER:
        obj = models.Folder.from_dict(payload)
    else:
        obj = models.Request.from_dict(payload)

    if reassign:
        reassign_ids(obj)
    return kind, obj


def folder_height(folder: models.Folder) -> int:
    """Высота поддерева папки (число уровней папок, включая саму)."""
    subs = [folder_height(f) for f in folder.folders]
    return 1 + (max(subs) if subs else 0)
