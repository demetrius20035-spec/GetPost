#!/usr/bin/env python3
"""Удобный запуск GUI-клиента GetPost.

Использование::

    python run_gui.py

Эквивалентно ``python -m getpost_gui``.
"""
import sys

from getpost_gui.app import main

if __name__ == "__main__":
    sys.exit(main())
