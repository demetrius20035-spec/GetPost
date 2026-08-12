"""Подстановка переменных вида ``{{name}}`` в строках.

Поддерживается три вида переменных:

* обычные — значения из окружения Workspace (``{{base_url}}``);
* вложенные — значение может само содержать переменные
  (``{{url}}`` → ``{{host}}/api`` → ``https://x/api``), раскрываются
  рекурсивно с защитой от циклических ссылок;
* динамические — вычисляются на момент подстановки: ``{{$uuid}}``,
  ``{{$timestamp}}``, ``{{$isoTimestamp}}``, ``{{$randomInt}}`` и другие
  (см. :data:`DYNAMIC_VARIABLES`).

Неизвестные переменные остаются без изменений (``{{unknown}}``), чтобы
пользователь видел, что переменная не была разрешена.
"""
from __future__ import annotations

import datetime
import random
import re
import string
import uuid
from typing import Dict, List

# {{ name }} — пробелы вокруг имени допускаются и обрезаются.
_VAR_RE = re.compile(r"\{\{\s*([^}\s][^}]*?)\s*\}\}")

# Ограничение глубины раскрытия вложенных переменных (защита от циклов).
MAX_DEPTH = 10

# Признак динамической переменной.
DYNAMIC_PREFIX = "$"


def _random_int(argument: str = "") -> str:
    """``$randomInt`` или ``$randomInt(1,100)``."""
    low, high = 0, 1000
    if argument:
        parts = [p.strip() for p in argument.split(",")]
        try:
            if len(parts) == 1:
                high = int(parts[0])
            elif len(parts) >= 2:
                low, high = int(parts[0]), int(parts[1])
        except ValueError:
            pass
    if low > high:
        low, high = high, low
    return str(random.randint(low, high))


def _random_string(argument: str = "") -> str:
    """``$randomString`` или ``$randomString(16)``."""
    try:
        length = int(argument) if argument else 8
    except ValueError:
        length = 8
    length = max(1, min(length, 4096))
    alphabet = string.ascii_letters + string.digits
    return "".join(random.choice(alphabet) for _ in range(length))


# Имя динамической переменной (без ``$``) → функция, принимающая аргумент.
DYNAMIC_VARIABLES = {
    "uuid": lambda _arg="": str(uuid.uuid4()),
    "guid": lambda _arg="": str(uuid.uuid4()),
    "timestamp": lambda _arg="": str(int(datetime.datetime.now().timestamp())),
    "isotimestamp": lambda _arg="": datetime.datetime.now(datetime.timezone.utc)
    .replace(microsecond=0)
    .isoformat()
    .replace("+00:00", "Z"),
    "datetime": lambda _arg="": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    "date": lambda _arg="": datetime.date.today().isoformat(),
    "randomint": _random_int,
    "randomstring": _random_string,
}

# Человекочитаемые описания (для подсказок в интерфейсе).
DYNAMIC_HELP = [
    ("{{$uuid}}", "случайный UUID v4"),
    ("{{$timestamp}}", "Unix-время (секунды)"),
    ("{{$isoTimestamp}}", "время UTC в формате ISO 8601"),
    ("{{$datetime}}", "локальные дата и время"),
    ("{{$date}}", "сегодняшняя дата"),
    ("{{$randomInt}}", "случайное число (можно {{$randomInt(1,100)}})"),
    ("{{$randomString}}", "случайная строка (можно {{$randomString(16)}})"),
]

# Разбор ``$name`` и ``$name(arg)``.
_DYNAMIC_RE = re.compile(r"^\$([A-Za-z_][A-Za-z0-9_]*)\s*(?:\(([^)]*)\))?$")


def is_dynamic(name: str) -> bool:
    """Является ли имя динамической переменной (``$uuid`` и т. п.)."""
    match = _DYNAMIC_RE.match((name or "").strip())
    return bool(match) and match.group(1).lower() in DYNAMIC_VARIABLES


def resolve_dynamic(name: str):
    """Вычислить динамическую переменную. ``None``, если имя неизвестно."""
    match = _DYNAMIC_RE.match((name or "").strip())
    if not match:
        return None
    func = DYNAMIC_VARIABLES.get(match.group(1).lower())
    if func is None:
        return None
    return func(match.group(2) or "")


def substitute(text: str, variables: Dict[str, str]) -> str:
    """Заменить все ``{{var}}`` на значения из ``variables``.

    Значения раскрываются рекурсивно (вложенные переменные), динамические
    вычисляются на месте. Неизвестные фрагменты остаются как есть, а
    циклические ссылки не приводят к зависанию.
    """
    if not text or "{{" not in text:
        return text or ""

    variables = variables or {}

    def expand(value: str, depth: int, seen: frozenset) -> str:
        if depth <= 0 or "{{" not in value:
            return value

        def _replace(match: "re.Match[str]") -> str:
            name = match.group(1).strip()

            if name.startswith(DYNAMIC_PREFIX):
                computed = resolve_dynamic(name)
                # Неизвестную динамическую переменную оставляем как есть.
                return match.group(0) if computed is None else str(computed)

            if name not in variables:
                return match.group(0)
            if name in seen:
                # Циклическая ссылка: возвращаем как есть, не раскрывая дальше.
                return match.group(0)
            return expand(str(variables[name]), depth - 1, seen | {name})

        return _VAR_RE.sub(_replace, value)

    return expand(text, MAX_DEPTH, frozenset())


def find_variables(text: str) -> List[str]:
    """Вернуть список имён переменных, встречающихся в строке."""
    if not text:
        return []
    return [m.strip() for m in _VAR_RE.findall(text)]


def find_unresolved(text: str, variables: Dict[str, str]) -> List[str]:
    """Имена переменных, которые не удастся подставить.

    Динамические переменные считаются известными.
    """
    variables = variables or {}
    unresolved = []
    for name in find_variables(text):
        if name.startswith(DYNAMIC_PREFIX):
            if not is_dynamic(name):
                unresolved.append(name)
        elif name not in variables and name not in unresolved:
            unresolved.append(name)
    return unresolved
