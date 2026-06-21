"""Точка входа GUI-приложения GetPost."""
from __future__ import annotations

import sys
from typing import List, Optional

from .qtcompat import QtWidgets
from .views.main_window import MainWindow


def main(argv: Optional[List[str]] = None) -> int:
    argv = argv if argv is not None else sys.argv
    app = QtWidgets.QApplication(argv)
    app.setApplicationName("GetPost")
    app.setOrganizationName("GetPost")
    app.setApplicationDisplayName("GetPost")

    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
