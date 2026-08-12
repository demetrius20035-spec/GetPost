"""Работа с cookie jar: перенос между ``requests.Session`` и диском.

Cookies сохраняются между запусками, поэтому сессия на сервере не теряется.
Модуль не зависит от Qt.
"""
from __future__ import annotations

from typing import Dict, List

import requests


def export_jar(session: requests.Session) -> List[Dict[str, str]]:
    """Выгрузить cookies сессии в список словарей (для сохранения на диск)."""
    result: List[Dict[str, str]] = []
    for cookie in session.cookies:
        result.append(
            {
                "name": cookie.name,
                "value": cookie.value or "",
                "domain": cookie.domain or "",
                "path": cookie.path or "/",
                "secure": bool(cookie.secure),
                # None означает «до конца сессии» — сохраняем как есть.
                "expires": cookie.expires,
            }
        )
    return result


def import_jar(session: requests.Session, cookies: List[Dict]) -> int:
    """Загрузить cookies в сессию. Возвращает число добавленных."""
    count = 0
    for item in cookies or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        if not name:
            continue
        try:
            session.cookies.set(
                name,
                str(item.get("value", "")),
                domain=str(item.get("domain", "")),
                path=str(item.get("path", "/")) or "/",
                secure=bool(item.get("secure", False)),
                expires=item.get("expires"),
            )
            count += 1
        except Exception:
            # Некорректная запись не должна ломать запуск приложения.
            continue
    return count


def remove(session: requests.Session, name: str, domain: str = "", path: str = "") -> bool:
    """Удалить cookie из сессии.

    Домен и путь необязательны: подходящая запись ищется в jar, а удаление
    выполняется по её фактическим домену и пути (``clear`` требует оба).
    """
    removed = False
    for cookie in list(session.cookies):
        if cookie.name != name:
            continue
        if domain and cookie.domain != domain:
            continue
        if path and cookie.path != path:
            continue
        try:
            session.cookies.clear(cookie.domain, cookie.path, cookie.name)
            removed = True
        except (KeyError, ValueError):
            continue
    return removed


def clear(session: requests.Session) -> None:
    """Удалить все cookies."""
    session.cookies.clear()


def summary(session: requests.Session) -> str:
    """Краткое описание для интерфейса."""
    count = len(list(session.cookies))
    if not count:
        return "нет cookies"
    domains = {c.domain for c in session.cookies if c.domain}
    return f"{count} cookies, домены: {len(domains)}"
