"""Извлечение значений из ответа в переменные окружения.

Позволяет строить цепочки запросов без скриптов: например, запрос «Login»
кладёт `data.access_token` из ответа в переменную ``{{token}}``, а остальные
запросы используют её в заголовке ``Authorization``.

Поддерживаемые источники (см. :mod:`getpost_gui.models`):

* ``json``   — путь по телу-JSON: ``data.items[0].token``;
* ``header`` — значение заголовка ответа по имени;
* ``status`` — код статуса;
* ``body``   — всё тело как текст.

Модуль не зависит от Qt и покрыт тестами.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple

from . import models

# Элемент пути: имя ключа или индекс в квадратных скобках.
_INDEX_RE = re.compile(r"\[(-?\d+)\]")

_MISSING = object()


def _split_path(path: str) -> List[Any]:
    """Разобрать ``a.b[0].c`` в ``['a', 'b', 0, 'c']``."""
    parts: List[Any] = []
    for chunk in (path or "").split("."):
        chunk = chunk.strip()
        if not chunk:
            continue
        # Отделяем возможные индексы: items[0][1] -> 'items', 0, 1
        name = _INDEX_RE.split(chunk)[0]
        if name:
            parts.append(name)
        for idx in _INDEX_RE.findall(chunk):
            parts.append(int(idx))
    return parts


def extract_json_path(data: Any, path: str) -> Any:
    """Достать значение по точечному пути. Возвращает ``None``, если нет."""
    current = data
    for part in _split_path(path):
        if isinstance(part, int):
            if isinstance(current, (list, tuple)):
                try:
                    current = current[part]
                except IndexError:
                    return None
            else:
                return None
        else:
            if isinstance(current, dict):
                current = current.get(part, _MISSING)
                if current is _MISSING:
                    return None
            else:
                return None
    return current


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    # Сложные структуры — компактным JSON.
    return json.dumps(value, ensure_ascii=False)


def _header_value(headers: List[Tuple[str, str]], name: str) -> Optional[str]:
    name = (name or "").strip().lower()
    for key, value in headers or []:
        if key.lower() == name:
            return value
    return None


def apply_captures(
    captures: List[Dict[str, Any]],
    status_code: int,
    headers: List[Tuple[str, str]],
    body_text: str,
) -> Tuple[Dict[str, str], List[str]]:
    """Применить правила извлечения к ответу.

    Возвращает ``(значения, проблемы)``: словарь «имя переменной → значение»
    и список понятных сообщений о том, что извлечь не удалось.
    """
    values: Dict[str, str] = {}
    problems: List[str] = []
    if not captures:
        return values, problems

    parsed_json: Any = _MISSING  # тело разбираем лениво и только один раз

    for rule in captures:
        if not rule.get("enabled", True):
            continue
        name = str(rule.get("name", "")).strip()
        if not name:
            continue
        source = rule.get("source", models.CAPTURE_JSON)
        expr = str(rule.get("expr", "")).strip()

        if source == models.CAPTURE_STATUS:
            values[name] = str(status_code)
            continue
        if source == models.CAPTURE_BODY:
            values[name] = body_text or ""
            continue
        if source == models.CAPTURE_HEADER:
            found = _header_value(headers, expr)
            if found is None:
                problems.append(f"{name}: в ответе нет заголовка «{expr}»")
            else:
                values[name] = found
            continue

        # json
        if parsed_json is _MISSING:
            try:
                parsed_json = json.loads(body_text) if body_text else None
            except (ValueError, TypeError):
                parsed_json = None
        if parsed_json is None:
            problems.append(f"{name}: тело ответа не является JSON")
            continue
        found = extract_json_path(parsed_json, expr)
        if found is None:
            problems.append(f"{name}: путь «{expr}» не найден в ответе")
        else:
            values[name] = _stringify(found)

    return values, problems
