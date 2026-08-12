"""Позволяет запускать приложение как ``python -m getpost_gui``."""
import sys

from .app import main

sys.exit(main())
