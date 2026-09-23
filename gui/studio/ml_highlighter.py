"""Syntax highlighting for CPN ML (declarations and inscriptions).

A small regular-expression highlighter, enough to make declarations easy to
scan: keywords, colour-set and function names, strings, numbers and
``(* comments *)`` -- including comments that span several lines.
"""

from __future__ import annotations

import re

from PySide6.QtGui import QColor, QFont, QSyntaxHighlighter, QTextCharFormat

from . import style

KEYWORDS = (
    "colset var val fun fn let in end if then else case of andalso orelse with and "
    "globref timed product record list index subset union by declare ms op not"
).split()
TYPES = "int bool string unit real time intinf".split()

_WORD = re.compile(r"\b(" + "|".join(KEYWORDS) + r")\b")
_TYPE = re.compile(r"\b(" + "|".join(TYPES) + r")\b")
_DEFINED = re.compile(r"\b(?:colset|fun|val|var|globref)\s+([A-Za-z_][\w']*(?:\s*,\s*[A-Za-z_][\w']*)*)")
_NUMBER = re.compile(r"(?<![\w.])~?\d+(\.\d+)?")
_STRING = re.compile(r'"(?:[^"\\]|\\.)*"')
_OPERATOR = re.compile(r"``|`|\+\+|--|@\+|::|\^\^|<>|<=|>=|=>")


def _format(colour: str, bold: bool = False, italic: bool = False) -> QTextCharFormat:
    fmt = QTextCharFormat()
    fmt.setForeground(QColor(colour))
    if bold:
        fmt.setFontWeight(QFont.DemiBold)
    fmt.setFontItalic(italic)
    return fmt


class MlHighlighter(QSyntaxHighlighter):
    IN_COMMENT = 1

    def highlightBlock(self, text: str) -> None:  # noqa: N802 - Qt naming
        t = style.tokens()
        keyword = _format(style.categorical(6), bold=True)
        type_ = _format(style.categorical(0))
        defined = _format(t.text, bold=True)
        number = _format(style.categorical(1))
        string = _format(style.categorical(2))
        operator = _format(t.text_secondary, bold=True)
        comment = _format(t.text_muted, italic=True)

        for pattern, fmt in ((_TYPE, type_), (_WORD, keyword), (_NUMBER, number),
                             (_OPERATOR, operator)):
            for match in pattern.finditer(text):
                self.setFormat(match.start(), match.end() - match.start(), fmt)
        for match in _DEFINED.finditer(text):
            self.setFormat(match.start(1), match.end(1) - match.start(1), defined)
        for match in _STRING.finditer(text):
            self.setFormat(match.start(), match.end() - match.start(), string)

        # (* comments *), possibly spanning lines.
        self.setCurrentBlockState(0)
        start = 0
        if self.previousBlockState() != self.IN_COMMENT:
            start = text.find("(*")
        while start >= 0:
            end = text.find("*)", start + 2 if self.previousBlockState() != self.IN_COMMENT
                            or start > 0 else 0)
            if end < 0:
                self.setCurrentBlockState(self.IN_COMMENT)
                length = len(text) - start
            else:
                length = end - start + 2
            self.setFormat(start, length, comment)
            start = text.find("(*", start + length)
