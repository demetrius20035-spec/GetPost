"""Точка входа GUI-приложения GetPost."""
from __future__ import annotations

import sys
from typing import List, Optional

from . import theme
from .qtcompat import QtWidgets
from .storage import Storage
from .views.main_window import MainWindow


def main(argv: Optional[List[str]] = None) -> int:
    argv = argv if argv is not None else sys.argv
    app = QtWidgets.QApplication(argv)
    app.setApplicationName("GetPost")
    app.setOrganizationName("GetPost")
    app.setApplicationDisplayName("GetPost")

    # Тема выбирается в настройках и запоминается между запусками.
    storage = Storage()
    theme.apply(app, storage.load_settings().get("theme", theme.THEME_LIGHT))

    window = MainWindow(storage=storage)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
