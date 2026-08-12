"""Сравнение двух ответов из истории.

Тела приводятся к сопоставимому виду (JSON форматируется с сортировкой ключей,
чтобы порядок полей не создавал ложных различий), после чего строится
построчный diff. Модуль не зависит от Qt.
"""
from __future__ import annotations

import difflib
import json
from typing import List, Tuple


def normalize_body(text: str, content_type: str = "") -> str:
    """Привести тело к виду, удобному для сравнения."""
    text = text or ""
    looks_json = "json" in (content_type or "").lower() or text.lstrip()[:1] in "{["
    if looks_json:
        try:
            parsed = json.loads(text)
            return json.dumps(parsed, ensure_ascii=False, indent=2, sort_keys=True)
        except (ValueError, TypeError):
            pass
    return text


def diff_lines(left: str, right: str, left_label: str = "старый",
               right_label: str = "новый") -> List[str]:
    """Построчный unified diff двух текстов."""
    return list(
        difflib.unified_diff(
            left.splitlines(),
            right.splitlines(),
            fromfile=left_label,
            tofile=right_label,
            lineterm="",
        )
    )


def diff_headers(left: List[Tuple[str, str]], right: List[Tuple[str, str]]) -> List[str]:
    """Различия в заголовках: добавленные, удалённые и изменённые."""
    left_map = {k.lower(): (k, v) for k, v in left or []}
    right_map = {k.lower(): (k, v) for k, v in right or []}
    lines: List[str] = []
    for key in sorted(set(left_map) | set(right_map)):
        in_left, in_right = left_map.get(key), right_map.get(key)
        if in_left and not in_right:
            lines.append(f"- {in_left[0]}: {in_left[1]}")
        elif in_right and not in_left:
            lines.append(f"+ {in_right[0]}: {in_right[1]}")
        elif in_left and in_right and in_left[1] != in_right[1]:
            lines.append(f"- {in_left[0]}: {in_left[1]}")
            lines.append(f"+ {in_right[0]}: {in_right[1]}")
    return lines


def compare(left, right) -> str:
    """Собрать текстовый отчёт о различиях двух ответов (``ResponseData``)."""
    parts: List[str] = []

    if left.status_line != right.status_line:
        parts.append(f"Статус: {left.status_line} → {right.status_line}")
    else:
        parts.append(f"Статус: {left.status_line} (без изменений)")

    parts.append(
        f"Время: {left.elapsed_ms:.0f} мс → {right.elapsed_ms:.0f} мс "
        f"({right.elapsed_ms - left.elapsed_ms:+.0f} мс)"
    )
    parts.append(
        f"Размер: {left.size_bytes} → {right.size_bytes} байт "
        f"({right.size_bytes - left.size_bytes:+d})"
    )

    header_diff = diff_headers(left.headers, right.headers)
    parts.append("")
    if header_diff:
        parts.append("Заголовки:")
        parts.extend(header_diff)
    else:
        parts.append("Заголовки: без изменений")

    body_diff = diff_lines(
        normalize_body(left.text, left.content_type),
        normalize_body(right.text, right.content_type),
    )
    parts.append("")
    if body_diff:
        parts.append("Тело:")
        parts.extend(body_diff)
    else:
        parts.append("Тело: без изменений")

    return "\n".join(parts)
