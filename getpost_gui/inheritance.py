"""Наследование настроек от папок.

Папка может задать базовый URL, общие заголовки и авторизацию — вложенные
запросы применяют их, не дублируя у себя. Правила слияния:

* **URL** — если после подстановки переменных URL запроса не содержит схемы
  (``http://``/``https://``), к нему добавляется ближайший непустой
  ``base_url`` из цепочки папок;
* **заголовки** — собираются от внешней папки к внутренней, затем добавляются
  заголовки запроса; при совпадении имени (без учёта регистра) побеждает
  ближайший к запросу;
* **авторизация** — если у запроса ``auth_type`` равен
  :data:`~getpost_gui.models.AUTH_INHERIT`, берётся ближайшая папка, которая
  задаёт авторизацию.

Результат — новый объект :class:`~getpost_gui.models.Request`, поэтому
остальной код (сборка запроса, генерация кода, предпросмотр) работает без
изменений и всегда видит одни и те же итоговые значения.
"""
from __future__ import annotations

from typing import List, Optional, Tuple

from . import models
from .variables import substitute

# Схемы, при которых base_url не применяется.
_ABSOLUTE_PREFIXES = ("http://", "https://")


def find_chain(container, request: models.Request) -> Optional[List[models.Folder]]:
    """Найти цепочку папок от корня до запроса.

    Возвращает список папок (внешняя → внутренняя) или ``None``, если запрос
    в этом контейнере не найден. Для запроса в корне возвращается ``[]``.
    """
    if any(r is request for r in container.requests):
        return []
    for folder in container.folders:
        found = find_chain(folder, request)
        if found is not None:
            return [folder] + found
    return None


def join_url(base: str, path: str) -> str:
    """Соединить базовый URL и относительный путь без двойных слешей."""
    base = (base or "").rstrip("/")
    path = (path or "").strip()
    if not base:
        return path
    if not path:
        return base
    return f"{base}/{path.lstrip('/')}"


def is_absolute(url: str) -> bool:
    """Содержит ли URL схему (то есть уже полный)."""
    return (url or "").strip().lower().startswith(_ABSOLUTE_PREFIXES)


def _merge_headers(chain: List[models.Folder], request: models.Request) -> List[dict]:
    """Собрать заголовки папок и запроса; ближайший к запросу побеждает."""
    merged: List[dict] = []
    for folder in chain:
        for item in folder.headers:
            merged.append(dict(item))
    for item in request.headers:
        merged.append(dict(item))

    # Убираем дубликаты по имени, оставляя последний (самый близкий к запросу).
    result: List[dict] = []
    seen_positions = {}
    for item in merged:
        key = str(item.get("key", "")).strip().lower()
        if not key:
            result.append(item)
            continue
        if key in seen_positions:
            result[seen_positions[key]] = item
        else:
            seen_positions[key] = len(result)
            result.append(item)
    return result


def _inherited_auth_source(chain: List[models.Folder]):
    """Ближайшая папка, задающая авторизацию (или ``None``)."""
    for folder in reversed(chain):
        if models.defines_auth(folder):
            return folder
    return None


def resolve(
    request: models.Request,
    chain: Optional[List[models.Folder]] = None,
    variables: Optional[dict] = None,
) -> models.Request:
    """Вернуть запрос с применёнными настройками папок.

    Исходный объект не изменяется. ``variables`` нужны только для проверки,
    получается ли из URL абсолютный адрес после подстановки.
    """
    chain = chain or []
    if not chain:
        return request

    effective = models.Request.from_dict(request.to_dict())
    effective.id = request.id
    effective.name = request.name

    # --- URL ---
    resolved_url = substitute(request.url, variables or {})
    if not is_absolute(resolved_url):
        for folder in reversed(chain):
            if folder.base_url:
                effective.url = join_url(folder.base_url, request.url)
                break

    # --- заголовки ---
    effective.headers = _merge_headers(chain, request)

    # --- авторизация ---
    if request.auth_type == models.AUTH_INHERIT:
        source = _inherited_auth_source(chain)
        if source is not None:
            models.auth_from_dict(effective, models.auth_to_dict(source))
        else:
            effective.auth_type = models.AUTH_NONE

    return effective


def describe(request: models.Request, chain: Optional[List[models.Folder]] = None) -> List[str]:
    """Описать, что именно унаследовано (для подсказки в интерфейсе)."""
    chain = chain or []
    notes: List[str] = []
    if not chain:
        return notes

    for folder in reversed(chain):
        if folder.base_url:
            notes.append(f"базовый URL из «{folder.name}»: {folder.base_url}")
            break
    header_count = sum(len(f.headers) for f in chain)
    if header_count:
        notes.append(f"заголовки из папок: {header_count}")
    if request.auth_type == models.AUTH_INHERIT:
        source = _inherited_auth_source(chain)
        if source is not None:
            notes.append(f"авторизация из «{source.name}» ({source.auth_type})")
        else:
            notes.append("авторизация: не задана ни в одной папке")
    return notes


def resolve_in(workspace, request: models.Request,
               variables: Optional[dict] = None) -> Tuple[models.Request, List[models.Folder]]:
    """Найти цепочку папок в Workspace и применить наследование."""
    chain = find_chain(workspace, request) or []
    return resolve(request, chain, variables), chain
