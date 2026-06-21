"""Подстановка переменных вида ``{{name}}`` в строках.

Значения берутся из словаря переменных Workspace. Неизвестные переменные
оставляются без изменений (``{{unknown}}``), чтобы пользователь видел, что
переменная не была разрешена.
"""
from __future__ import annotations

import re
from typing import Dict

# {{ name }} — пробелы вокруг имени допускаются и обрезаются.
_VAR_RE = re.compile(r"\{\{\s*([^}\s][^}]*?)\s*\}\}")


def substitute(text: str, variables: Dict[str, str]) -> str:
    """Заменить все ``{{var}}`` на значения из ``variables``.

    Если переменной нет в словаре — фрагмент остаётся как есть.
    """
    if not text or "{{" not in text:
        return text or ""

    def _replace(match: "re.Match[str]") -> str:
        name = match.group(1).strip()
        if name in variables:
            return str(variables[name])
        return match.group(0)

    return _VAR_RE.sub(_replace, text)


def find_variables(text: str) -> list:
    """Вернуть список имён переменных, встречающихся в строке."""
    if not text:
        return []
    return [m.strip() for m in _VAR_RE.findall(text)]
