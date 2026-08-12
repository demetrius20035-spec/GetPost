"""Подсветка синтаксиса для JSON и XML.

Реализована через ``QSyntaxHighlighter`` и регулярные выражения. Подсветка
намеренно простая (без полноценного парсинга), что достаточно для просмотра
тел запросов и ответов и не влияет на производительность.
"""
from __future__ import annotations

import re
from typing import List, Tuple

from . import theme
from .qtcompat import QtGui


def _fmt(color: str, bold: bool = False) -> QtGui.QTextCharFormat:
    fmt = QtGui.QTextCharFormat()
    fmt.setForeground(QtGui.QColor(color))
    if bold:
        fmt.setFontWeight(QtGui.QFont.Weight.Bold)
    return fmt


class JsonHighlighter(QtGui.QSyntaxHighlighter):
    """Подсветка JSON: ключи, строки, числа, булевы значения, null."""

    def __init__(self, document):
        super().__init__(document)
        palette = theme.syntax()
        key_fmt = _fmt(palette["key"], bold=True)
        string_fmt = _fmt(palette["string"])
        number_fmt = _fmt(palette["number"])
        keyword_fmt = _fmt(palette["keyword"], bold=True)
        punct_fmt = _fmt(palette["punct"])

        self._rules: List[Tuple[re.Pattern, QtGui.QTextCharFormat]] = [
            # Ключ объекта: "ключ" перед двоеточием.
            (re.compile(r'"(?:\\.|[^"\\])*"(?=\s*:)'), key_fmt),
            # Строковое значение.
            (re.compile(r'"(?:\\.|[^"\\])*"'), string_fmt),
            # Числа (включая дробные и экспоненту).
            (re.compile(r"-?\b\d+(?:\.\d+)?(?:[eE][+-]?\d+)?\b"), number_fmt),
            # Ключевые слова.
            (re.compile(r"\b(?:true|false|null)\b"), keyword_fmt),
            # Структурные символы.
            (re.compile(r"[\{\}\[\]:,]"), punct_fmt),
        ]

    def highlightBlock(self, text: str) -> None:  # noqa: N802 - имя задано Qt
        for pattern, fmt in self._rules:
            for m in pattern.finditer(text):
                self.setFormat(m.start(), m.end() - m.start(), fmt)


class XmlHighlighter(QtGui.QSyntaxHighlighter):
    """Подсветка XML/HTML: теги, атрибуты, значения, комментарии."""

    def __init__(self, document):
        super().__init__(document)
        palette = theme.syntax()
        self._tag_fmt = _fmt(palette["tag"], bold=True)
        self._attr_fmt = _fmt(palette["attr"])
        self._value_fmt = _fmt(palette["string"])
        self._comment_fmt = _fmt(palette["comment"])

        self._rules: List[Tuple[re.Pattern, QtGui.QTextCharFormat]] = [
            (re.compile(r"</?[A-Za-z_][\w:.-]*"), self._tag_fmt),
            (re.compile(r"/?>"), self._tag_fmt),
            (re.compile(r"\b[A-Za-z_][\w:.-]*(?=\s*=)"), self._attr_fmt),
            (re.compile(r'"[^"]*"|\'[^\']*\''), self._value_fmt),
        ]
        self._comment_re = re.compile(r"<!--.*?-->")

    def highlightBlock(self, text: str) -> None:  # noqa: N802 - имя задано Qt
        for pattern, fmt in self._rules:
            for m in pattern.finditer(text):
                self.setFormat(m.start(), m.end() - m.start(), fmt)
        # Однострочные комментарии.
        for m in self._comment_re.finditer(text):
            self.setFormat(m.start(), m.end() - m.start(), self._comment_fmt)


def guess_language(content_type: str, body: str) -> str:
    """Определить язык содержимого по Content-Type и/или телу.

    Возвращает один из: ``"json"``, ``"xml"``, ``"text"``.
    """
    ct = (content_type or "").lower()
    if "json" in ct:
        return "json"
    if "xml" in ct or "html" in ct:
        return "xml"

    sample = (body or "").lstrip()
    if sample[:1] in "{[":
        return "json"
    if sample[:1] == "<":
        return "xml"
    return "text"
