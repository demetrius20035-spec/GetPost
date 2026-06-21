#!/usr/bin/env python3
"""GetPost CLI — функциональный консольный HTTP-клиент.

Это «младший брат» GUI-приложения GetPost: он переиспользует то же ядро
(пакет ``getpost_gui``) для сборки запросов, подстановки переменных и работы
с сохранёнными рабочими пространствами.

Подкоманды
----------
  send    отправить произвольный HTTP-запрос
  run     отправить запрос, сохранённый в Workspace (через GUI)
  ls      показать рабочие пространства или их содержимое

Форму ``getpost.py <METHOD> <URL>`` тоже понимает (как ``send``).

Примеры
-------
  # Простой GET с красивым JSON
  python getpost.py GET https://httpbin.org/get

  # POST с JSON-телом и Bearer-токеном
  python getpost.py POST https://httpbin.org/post --json '{"a":1}' --bearer TOKEN

  # Заголовки, query-параметры и переменные
  python getpost.py GET '{{base}}/items' -H 'X-Key: 1' -q page=2 --var base=https://api.test

  # form-urlencoded и multipart с загрузкой файла
  python getpost.py POST https://httpbin.org/post -F user=bob -F pass=secret
  python getpost.py POST https://httpbin.org/post --multipart file=@./report.pdf --multipart note=hi

  # Basic-авторизация, отключение проверки TLS, тайм-аут, сохранение тела в файл
  python getpost.py GET https://example.com -u admin:admin -k --timeout 10 -o page.html

  # Запросы из сохранённых рабочих пространств
  python getpost.py ls
  python getpost.py ls "My Workspace"
  python getpost.py run "My Workspace" "Get IP"
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import sys

import requests

# Подключаем общее ядро из соседнего пакета (без зависимости от Qt).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from getpost_gui import http_client, models, storage  # noqa: E402
from getpost_gui.variables import substitute  # noqa: E402

__version__ = "2.0.0"

HTTP_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]
SUBCOMMANDS = {"send", "run", "ls", "list"}

# Коды возврата.
EXIT_OK = 0
EXIT_ERROR = 1
EXIT_REQUEST = 3   # сетевая ошибка / ошибка запроса
EXIT_HTTP = 22     # --fail и статус >= 400 (как у curl)


# --------------------------------------------------------------------------
# Вывод и цвета
# --------------------------------------------------------------------------
class Ansi:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    GREY = "\033[90m"


_USE_COLOR = False


def _c(text: str, *codes: str) -> str:
    if not _USE_COLOR or not codes:
        return text
    return "".join(codes) + text + Ansi.RESET


def info(text: str = "") -> None:
    """Служебная информация — в stderr (чтобы stdout оставался чистым для данных)."""
    print(text, file=sys.stderr)


_JSON_TOKEN = re.compile(
    r"""
    (?P<key>"(?:\\.|[^"\\])*"(?=\s*:)) |
    (?P<str>"(?:\\.|[^"\\])*")          |
    (?P<num>-?\b\d+(?:\.\d+)?(?:[eE][+-]?\d+)?\b) |
    (?P<kw>\b(?:true|false|null)\b)
    """,
    re.VERBOSE,
)


def colorize_json(text: str) -> str:
    if not _USE_COLOR:
        return text

    def repl(m: "re.Match[str]") -> str:
        if m.lastgroup == "key":
            return _c(m.group(), Ansi.CYAN, Ansi.BOLD)
        if m.lastgroup == "str":
            return _c(m.group(), Ansi.GREEN)
        if m.lastgroup == "num":
            return _c(m.group(), Ansi.YELLOW)
        return _c(m.group(), Ansi.MAGENTA, Ansi.BOLD)

    return _JSON_TOKEN.sub(repl, text)


def status_color(code: int) -> str:
    if code >= 500:
        return Ansi.RED
    if code >= 400:
        return Ansi.YELLOW
    if code >= 300:
        return Ansi.BLUE
    if code >= 200:
        return Ansi.GREEN
    return Ansi.GREY


# --------------------------------------------------------------------------
# Разбор аргументов в параметры запроса
# --------------------------------------------------------------------------
def _split_pair(item: str, sep: str, what: str):
    if sep not in item:
        raise ValueError(f"Неверный формат {what}: «{item}». Ожидается key{sep}value.")
    key, value = item.split(sep, 1)
    return key.strip(), value


def parse_headers(items):
    return [{"enabled": True, "key": k, "value": v.strip()}
            for k, v in (_split_pair(i, ":", "заголовка") for i in items or [])]


def parse_kv(items, what):
    return [{"enabled": True, "key": k, "value": v}
            for k, v in (_split_pair(i, "=", what) for i in items or [])]


def read_value(value: str) -> str:
    """Поддержка ``@file`` и ``@-`` (stdin) для тела запроса."""
    if value == "@-":
        return sys.stdin.read()
    if value.startswith("@"):
        path = value[1:]
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read()
    return value


def collect_variables(args) -> dict:
    variables = {}
    # Переменные из Workspace (если указан --use-workspace).
    ws_name = getattr(args, "use_workspace", None)
    if ws_name:
        ws = find_workspace(ws_name)
        if ws is None:
            info(_c(f"Предупреждение: рабочее пространство «{ws_name}» не найдено", Ansi.YELLOW))
        else:
            variables.update(ws.variables)
    # Переменные из командной строки имеют приоритет.
    for item in getattr(args, "var", None) or []:
        k, v = _split_pair(item, "=", "переменной")
        variables[k] = v
    return variables


def build_multipart_files(items, variables):
    """Собрать ``files`` для multipart/form-data, поддерживая ``key=@path``."""
    files = []
    for item in items:
        key, value = _split_pair(item, "=", "поля")
        key = substitute(key, variables)
        value = substitute(value, variables)
        if value.startswith("@"):
            path = value[1:]
            ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
            with open(path, "rb") as fh:
                content = fh.read()
            files.append((key, (os.path.basename(path), content, ctype)))
        else:
            files.append((key, (None, value)))
    return files


def request_from_args(args) -> models.Request:
    """Построить модель запроса из аргументов командной строки."""
    req = models.Request()
    req.method = args.method.upper()
    req.url = args.url
    req.headers = parse_headers(args.header)
    req.params = parse_kv(args.query, "параметра")

    if args.user_agent:
        req.headers.append({"enabled": True, "key": "User-Agent", "value": args.user_agent})

    # Авторизация.
    if args.user:
        user, _, password = args.user.partition(":")
        req.auth_type = models.AUTH_BASIC
        req.auth_basic_username = user
        req.auth_basic_password = password
    elif args.bearer:
        req.auth_type = models.AUTH_BEARER
        req.auth_bearer_token = args.bearer

    # Тело (multipart обрабатывается отдельно в send()).
    if args.json is not None:
        req.body_type = models.BODY_RAW
        req.body_raw = read_value(args.json)
        req.body_raw_lang = models.RAW_JSON
    elif args.data is not None:
        req.body_type = models.BODY_RAW
        req.body_raw = read_value(args.data)
        req.body_raw_lang = models.RAW_TEXT
    elif args.form:
        req.body_type = models.BODY_URLENCODED
        req.body_form = parse_kv(args.form, "поля")

    return req


# --------------------------------------------------------------------------
# Отправка и вывод ответа
# --------------------------------------------------------------------------
def send_request(req: models.Request, variables: dict, args, multipart_items=None) -> int:
    method, url, kwargs = http_client.build_request_kwargs(req, variables)
    if not url:
        info(_c("Ошибка: пустой URL", Ansi.RED))
        return EXIT_ERROR

    if multipart_items:
        kwargs["files"] = build_multipart_files(multipart_items, variables)
        kwargs.pop("data", None)

    kwargs["allow_redirects"] = not args.no_redirect
    kwargs["verify"] = not args.insecure
    if args.proxy:
        kwargs["proxies"] = {"http": args.proxy, "https": args.proxy}

    if args.insecure:
        try:
            requests.packages.urllib3.disable_warnings()  # type: ignore[attr-defined]
        except Exception:
            pass

    if args.verbose:
        _print_request(method, url, kwargs)

    try:
        resp = requests.request(method, url, timeout=args.timeout, stream=bool(args.output), **kwargs)
    except requests.exceptions.Timeout:
        info(_c(f"Ошибка: превышено время ожидания ({args.timeout} с)", Ansi.RED))
        return EXIT_REQUEST
    except requests.exceptions.SSLError as exc:
        info(_c(f"Ошибка SSL: {exc}", Ansi.RED))
        return EXIT_REQUEST
    except requests.exceptions.ConnectionError:
        info(_c("Ошибка: не удалось подключиться к серверу.", Ansi.RED))
        return EXIT_REQUEST
    except requests.exceptions.RequestException as exc:
        info(_c(f"Ошибка запроса: {exc}", Ansi.RED))
        return EXIT_REQUEST

    _print_response(resp, args)

    if args.fail and resp.status_code >= 400:
        return EXIT_HTTP
    return EXIT_OK


def _print_request(method: str, url: str, kwargs: dict) -> None:
    info(_c(f"> {method} {url}", Ansi.BOLD, Ansi.BLUE))
    for k, v in (kwargs.get("headers") or {}).items():
        info(_c(f"> {k}: {v}", Ansi.GREY))
    if kwargs.get("params"):
        info(_c(f"> (query) {kwargs['params']}", Ansi.GREY))
    if "data" in kwargs:
        data = kwargs["data"]
        size = len(data) if isinstance(data, (bytes, str)) else len(str(data))
        info(_c(f"> (body) {size} байт", Ansi.GREY))
    if "files" in kwargs:
        info(_c(f"> (multipart) {len(kwargs['files'])} полей", Ansi.GREY))
    info()


def _print_response(resp: requests.Response, args) -> None:
    elapsed_ms = resp.elapsed.total_seconds() * 1000
    version = {10: "1.0", 11: "1.1", 20: "2"}.get(getattr(resp.raw, "version", 11), "1.1")

    # Статусная строка и сводка — в stderr (если не --silent).
    if not args.silent:
        line = f"HTTP/{version} {resp.status_code} {resp.reason}"
        info(_c(line, Ansi.BOLD, status_color(resp.status_code)))
        if len(resp.history) > 0:
            chain = " → ".join(str(r.status_code) for r in resp.history) + f" → {resp.status_code}"
            info(_c(f"Редиректы: {chain}", Ansi.GREY))
        info(_c(f"Время: {elapsed_ms:.0f} мс · Размер: {_human_size(len(resp.content))}", Ansi.GREY))

    # Заголовки ответа.
    show_headers = args.include or args.headers_only or args.verbose
    if show_headers:
        out = sys.stdout if (args.include or args.headers_only) else sys.stderr
        for k, v in resp.headers.items():
            print(_c(f"{k}:", Ansi.CYAN) + f" {v}", file=out)
        if args.include:
            print()  # пустая строка между заголовками и телом в stdout

    if args.headers_only:
        return

    # Сохранение тела в файл.
    if args.output:
        with open(args.output, "wb") as fh:
            fh.write(resp.content)
        if not args.silent:
            info(_c(f"Тело сохранено в {args.output} ({_human_size(len(resp.content))})", Ansi.GREEN))
        return

    # Тело в stdout.
    body = resp.text
    is_json = "json" in resp.headers.get("Content-Type", "").lower() or _looks_json(body)
    if is_json and not args.raw:
        try:
            body = json.dumps(json.loads(body), ensure_ascii=False, indent=2)
            body = colorize_json(body)
        except (ValueError, TypeError):
            pass
    if body:
        print(body)


def _looks_json(text: str) -> bool:
    s = (text or "").lstrip()
    return s[:1] in "{["


def _human_size(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{int(size)} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{num_bytes} B"


# --------------------------------------------------------------------------
# Работа с сохранёнными Workspace
# --------------------------------------------------------------------------
def find_workspace(name_or_id: str):
    store = storage.Storage()
    for ws in store.load_all_workspaces():
        if ws.id == name_or_id or ws.name.lower() == name_or_id.lower():
            return ws
    return None


def iter_requests(container, prefix=""):
    """Перебрать все запросы Workspace/папки с их «путями»."""
    for r in container.requests:
        yield prefix + r.name, r
    for f in container.folders:
        yield from iter_requests(f, prefix + f.name + "/")


def find_request(ws, name_or_path: str):
    matches = []
    for path, req in iter_requests(ws):
        if path == name_or_path or req.name == name_or_path:
            matches.append((path, req))
    return matches


# --------------------------------------------------------------------------
# Подкоманды
# --------------------------------------------------------------------------
def cmd_send(args) -> int:
    variables = collect_variables(args)
    req = request_from_args(args)
    return send_request(req, variables, args, multipart_items=args.multipart)


def cmd_run(args) -> int:
    ws = find_workspace(args.workspace)
    if ws is None:
        info(_c(f"Рабочее пространство «{args.workspace}» не найдено.", Ansi.RED))
        names = ", ".join(w.name for w in storage.Storage().load_all_workspaces())
        info("Доступные: " + (names or "—"))
        return EXIT_ERROR

    matches = find_request(ws, args.request)
    if not matches:
        info(_c(f"Запрос «{args.request}» не найден в «{ws.name}».", Ansi.RED))
        info("Доступные запросы:")
        for path, _ in iter_requests(ws):
            info(f"  {path}")
        return EXIT_ERROR
    if len(matches) > 1:
        info(_c(f"Найдено несколько запросов «{args.request}». Уточните путь:", Ansi.YELLOW))
        for path, _ in matches:
            info(f"  {path}")
        return EXIT_ERROR

    _, req = matches[0]
    variables = dict(ws.variables)
    for item in args.var or []:
        k, v = _split_pair(item, "=", "переменной")
        variables[k] = v

    if not args.silent:
        info(_c(f"# {ws.name} → {req.name}  [{req.method}]  {req.url}", Ansi.DIM))
    return send_request(req, variables, args)


def cmd_ls(args) -> int:
    store = storage.Storage()
    workspaces = store.load_all_workspaces()

    if not args.workspace:
        if not workspaces:
            info("Рабочих пространств нет. Создайте их в GUI: python run_gui.py")
            return EXIT_OK
        info(_c("Рабочие пространства:", Ansi.BOLD))
        for ws in workspaces:
            count = sum(1 for _ in iter_requests(ws))
            nvars = len(ws.variables)
            print(f"  {_c(ws.name, Ansi.CYAN, Ansi.BOLD)}  "
                  f"{_c(f'({count} запросов, {nvars} переменных)', Ansi.GREY)}")
        return EXIT_OK

    ws = find_workspace(args.workspace)
    if ws is None:
        info(_c(f"Рабочее пространство «{args.workspace}» не найдено.", Ansi.RED))
        return EXIT_ERROR

    info(_c(f"Workspace: {ws.name}", Ansi.BOLD))
    if ws.variables:
        info(_c("Переменные:", Ansi.BOLD))
        for k, v in ws.variables.items():
            print(f"  {_c(k, Ansi.CYAN)} = {v}")
    info(_c("Запросы:", Ansi.BOLD))
    for path, req in iter_requests(ws):
        method = _c(f"{req.method:6}", status_color(200), Ansi.BOLD)
        print(f"  {method} {path}  {_c(req.url, Ansi.GREY)}")
    return EXIT_OK


# --------------------------------------------------------------------------
# Парсер аргументов
# --------------------------------------------------------------------------
def _add_request_options(p: argparse.ArgumentParser) -> None:
    """Опции, общие для отправки запроса (send/run)."""
    out = p.add_argument_group("вывод")
    out.add_argument("-i", "--include", action="store_true", help="включить заголовки ответа в вывод")
    out.add_argument("-I", "--headers-only", action="store_true", help="показать только заголовки ответа")
    out.add_argument("-v", "--verbose", action="store_true", help="показать детали запроса")
    out.add_argument("-s", "--silent", action="store_true", help="только тело ответа (без сводки)")
    out.add_argument("--raw", action="store_true", help="не форматировать JSON")
    out.add_argument("-o", "--output", metavar="FILE", help="сохранить тело ответа в файл")
    out.add_argument("--no-color", action="store_true", help="отключить цветной вывод")
    out.add_argument("--color", choices=["auto", "always", "never"], default="auto", help="режим цвета")
    out.add_argument("--fail", action="store_true", help="код возврата != 0 при статусе >= 400")

    conn = p.add_argument_group("соединение")
    conn.add_argument("--timeout", type=float, default=http_client.DEFAULT_TIMEOUT, metavar="SEC",
                      help="тайм-аут запроса в секундах")
    conn.add_argument("--no-redirect", action="store_true", help="не следовать редиректам")
    conn.add_argument("-k", "--insecure", action="store_true", help="не проверять TLS-сертификат")
    conn.add_argument("--proxy", metavar="URL", help="использовать HTTP(S)-прокси")
    conn.add_argument("--var", action="append", metavar="K=V", help="переменная для {{подстановки}} (можно повторять)")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="getpost.py",
        description="GetPost CLI — функциональный консольный HTTP-клиент.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Подсказка: форму «getpost.py GET <url>» можно использовать без слова send.",
    )
    parser.add_argument("--version", action="version", version=f"GetPost CLI {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="<команда>")

    # send
    p_send = sub.add_parser("send", help="отправить произвольный HTTP-запрос",
                            formatter_class=argparse.RawDescriptionHelpFormatter)
    p_send.add_argument("method", choices=HTTP_METHODS, type=str.upper, help="HTTP-метод")
    p_send.add_argument("url", help="URL (поддерживает переменные {{var}})")
    body = p_send.add_argument_group("запрос")
    body.add_argument("-H", "--header", action="append", metavar="'K: V'", help="заголовок (можно повторять)")
    body.add_argument("-q", "--query", action="append", metavar="K=V", help="query-параметр (можно повторять)")
    body.add_argument("-d", "--data", metavar="DATA", help="сырое тело (@file или @- для stdin)")
    body.add_argument("--json", metavar="JSON", help="JSON-тело (@file/@-), ставит Content-Type")
    body.add_argument("-F", "--form", action="append", metavar="K=V", help="поле x-www-form-urlencoded")
    body.add_argument("--multipart", action="append", metavar="K=V|K=@file", help="поле multipart/form-data")
    body.add_argument("-u", "--user", metavar="USER:PASS", help="Basic-авторизация")
    body.add_argument("--bearer", metavar="TOKEN", help="Bearer-токен")
    body.add_argument("-A", "--user-agent", metavar="UA", help="заголовок User-Agent")
    body.add_argument("--use-workspace", metavar="NAME", help="взять переменные из этого Workspace")
    _add_request_options(p_send)
    p_send.set_defaults(func=cmd_send)

    # run
    p_run = sub.add_parser("run", help="отправить сохранённый в Workspace запрос")
    p_run.add_argument("workspace", help="имя или id рабочего пространства")
    p_run.add_argument("request", help="имя или путь запроса (Папка/Имя)")
    _add_request_options(p_run)
    p_run.set_defaults(func=cmd_run)

    # ls
    p_ls = sub.add_parser("ls", aliases=["list"], help="показать Workspaces или их содержимое")
    p_ls.add_argument("workspace", nargs="?", help="имя/id Workspace (без него — список всех)")
    p_ls.add_argument("--no-color", action="store_true", help="отключить цветной вывод")
    p_ls.add_argument("--color", choices=["auto", "always", "never"], default="auto")
    p_ls.set_defaults(func=cmd_ls)

    return parser


def _setup_color(args) -> None:
    global _USE_COLOR
    mode = getattr(args, "color", "auto")
    if getattr(args, "no_color", False) or mode == "never" or os.environ.get("NO_COLOR"):
        _USE_COLOR = False
    elif mode == "always":
        _USE_COLOR = True
    else:  # auto
        _USE_COLOR = sys.stdout.isatty()


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    # Обратная совместимость: «getpost.py GET <url>» == «getpost.py send GET <url>».
    if argv and argv[0].upper() in HTTP_METHODS and argv[0] not in SUBCOMMANDS:
        argv = ["send"] + argv

    parser = build_parser()
    args = parser.parse_args(argv)

    if not getattr(args, "command", None):
        parser.print_help()
        return EXIT_ERROR

    _setup_color(args)
    try:
        return args.func(args)
    except FileNotFoundError as exc:
        info(_c(f"Файл не найден: {exc.filename}", Ansi.RED))
        return EXIT_ERROR
    except ValueError as exc:
        info(_c(f"Ошибка: {exc}", Ansi.RED))
        return EXIT_ERROR
    except KeyboardInterrupt:
        info("\nПрервано.")
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
