"""Шрифт для вывода в PDF.

Базовых шрифтов PDF с кириллицей не существует, поэтому и бланк, и значения
рисуются одним TTF. Путь к нему берётся из окружения или из привычных мест,
в образе он ставится пакетом fonts-dejavu-core.
"""

from __future__ import annotations

import os
from pathlib import Path

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

FORM_FONT = "FormSans"

CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/TTF/DejaVuSans.ttf",
    "/Library/Fonts/Arial Unicode.ttf",
    r"C:\Windows\Fonts\arial.ttf",
    r"C:\Windows\Fonts\segoeui.ttf",
)


class FontNotFound(RuntimeError):
    pass


def register_form_font() -> str:
    """Регистрирует шрифт в reportlab и возвращает путь. Повторные вызовы бесплатны."""
    if FORM_FONT in pdfmetrics.getRegisteredFontNames():
        return getattr(pdfmetrics.getFont(FORM_FONT), "filename", FORM_FONT)

    override = os.environ.get("TAX_REPORTER_FONT")
    for path in filter(None, (override, *CANDIDATES)):
        if Path(path).is_file():
            pdfmetrics.registerFont(TTFont(FORM_FONT, path))
            return path

    raise FontNotFound(
        "не найден шрифт с кириллицей: поставьте fonts-dejavu-core "
        "или укажите путь в TAX_REPORTER_FONT"
    )
