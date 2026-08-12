"""Хранение данных в JSON-файлах.

Структура каталога конфигурации::

    <config_dir>/
    ├── workspaces/
    │   ├── <id1>.json
    │   └── <id2>.json
    └── settings.json        # глобальные настройки

Каталог по умолчанию: ``~/.getpost`` (можно переопределить переменной
окружения ``GETPOST_CONFIG_DIR``). Имя файла Workspace основано на его
идентификаторе, поэтому переименование не приводит к конфликтам.

Запись выполняется атомарно (через временный файл + ``os.replace``), что
защищает от повреждения данных при сбое в момент сохранения.
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Dict, List, Optional

from .models import Request, Workspace

_ENV_CONFIG_DIR = "GETPOST_CONFIG_DIR"


def default_config_dir() -> Path:
    """Каталог конфигурации по умолчанию."""
    override = os.environ.get(_ENV_CONFIG_DIR)
    if override:
        return Path(override).expanduser()
    return Path.home() / ".getpost"


class Storage:
    """Чтение и запись Workspaces и настроек на диск."""

    def __init__(self, base_dir: Optional[os.PathLike] = None):
        self.base_dir = Path(base_dir).expanduser() if base_dir else default_config_dir()
        self.workspaces_dir = self.base_dir / "workspaces"
        self.settings_file = self.base_dir / "settings.json"
        self.ensure_dirs()

    # -- служебное ----------------------------------------------------------
    def ensure_dirs(self) -> None:
        self.workspaces_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _atomic_write(path: Path, text: str) -> None:
        """Атомарно записать текст в файл."""
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp_", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(text)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)

    def _workspace_path(self, ws: Workspace) -> Path:
        return self.workspaces_dir / f"{ws.id}.json"

    # -- Workspaces ---------------------------------------------------------
    def list_workspace_files(self) -> List[Path]:
        if not self.workspaces_dir.exists():
            return []
        return sorted(self.workspaces_dir.glob("*.json"))

    def load_all_workspaces(self) -> List[Workspace]:
        """Загрузить все Workspaces. Битые файлы пропускаются."""
        result: List[Workspace] = []
        for path in self.list_workspace_files():
            ws = self._load_workspace_file(path)
            if ws is not None:
                result.append(ws)
        # Стабильный порядок — по имени.
        result.sort(key=lambda w: w.name.lower())
        return result

    def _load_workspace_file(self, path: Path) -> Optional[Workspace]:
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            ws = Workspace.from_dict(data)
            ws.file_path = str(path)
            return ws
        except (OSError, ValueError, json.JSONDecodeError):
            return None

    def save_workspace(self, ws: Workspace) -> Path:
        """Сохранить Workspace. Перед перезаписью делается копия ``*.bak``.

        Может выбросить ``OSError`` (нет места, нет прав) — вызывающая сторона
        обязана сообщить об этом пользователю, а не проглатывать ошибку.
        """
        path = self._workspace_path(ws)
        text = json.dumps(ws.to_dict(), ensure_ascii=False, indent=2)
        self._backup(path)
        self._atomic_write(path, text)
        ws.file_path = str(path)
        return path

    @staticmethod
    def _backup(path: Path) -> None:
        """Сохранить предыдущую версию файла рядом (``*.json.bak``).

        Ошибка резервного копирования не должна мешать основной записи.
        """
        if not path.exists():
            return
        try:
            shutil.copy2(path, path.with_suffix(path.suffix + ".bak"))
        except OSError:
            pass

    def delete_workspace(self, ws: Workspace) -> None:
        path = self._workspace_path(ws)
        if path.exists():
            path.unlink()

    def create_workspace(self, name: str = "My Workspace") -> Workspace:
        ws = Workspace(name=name)
        self.save_workspace(ws)
        return ws

    # -- настройки ----------------------------------------------------------
    def load_settings(self) -> Dict:
        try:
            with open(self.settings_file, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError, json.JSONDecodeError):
            return {}

    def save_settings(self, settings: Dict) -> None:
        text = json.dumps(settings, ensure_ascii=False, indent=2)
        self._atomic_write(self.settings_file, text)

    # -- сброс --------------------------------------------------------------
    def reset(self) -> None:
        """Удалить все Workspaces и настройки (сброс к значениям по умолчанию)."""
        for path in list(self.list_workspace_files()) + list(self.workspaces_dir.glob("*.bak")):
            try:
                path.unlink()
            except OSError:
                pass
        if self.settings_file.exists():
            try:
                self.settings_file.unlink()
            except OSError:
                pass
        self.ensure_dirs()


def build_default_workspace() -> Workspace:
    """Создать демонстрационный Workspace для первого запуска."""
    ws = Workspace(name="My Workspace")
    ws.variables = {"base_url": "https://httpbin.org"}
    req = Request(name="Get IP")
    req.method = "GET"
    req.url = "{{base_url}}/get"
    ws.requests.append(req)
    return ws
