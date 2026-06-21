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


def export_dict(obj) -> dict:
    """Сформировать «конверт» для экспорта объекта."""
    return {
        FORMAT_KEY: FORMAT_VERSION,
        "type": detect_kind(obj),
        "exported_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "data": obj.to_dict(),
    }


def export_str(obj) -> str:
    return json.dumps(export_dict(obj), ensure_ascii=False, indent=2)


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
