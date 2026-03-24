"""Сборка PDF: значения и подпись рисуются поверх бланка.

Бланк — обычная форма AcroForm, и первым заходом значения подставлялись прямо в её
поля. На кириллице это не работает: в /DA бланка стоит Helvetica, у которой нет
нужных глифов, и справка открывалась либо пустой, либо с «кракозябрами» — в
зависимости от того, чем её смотрели. Поэтому поля бланка схлопываются, а значения
выводятся наложением тем же шрифтом, которым нарисован сам бланк. Побочный плюс:
на выходе получается плоский PDF, который шлюз принимает без оговорок.
"""

from __future__ import annotations

from functools import lru_cache
from io import BytesIO
from pathlib import Path

from PIL import Image
from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, NameObject
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfgen import canvas

from .fonts import FORM_FONT, register_form_font
from .models import Certificate
from .templates import FieldBinding, Template, TemplateLibrary

# Всё, что светлее этого порога, считаем фоном скана подписи.
_BACKGROUND_THRESHOLD = 240

# Ниже этого кегля текст уже не читается, дальше обрезаем по ширине ячейки.
_MIN_FONT_SIZE = 6.0


class RenderError(RuntimeError):
    pass


@lru_cache(maxsize=8)
def _signature_image(path: str) -> ImageReader:
    """Скан подписи приходит на белом фоне, его нужно убрать в прозрачность."""
    image = Image.open(path).convert("RGBA")
    image.putdata(
        [
            (255, 255, 255, 0) if min(r, g, b) > _BACKGROUND_THRESHOLD else (r, g, b, a)
            for r, g, b, a in image.getdata()
        ]
    )
    return ImageReader(image)


def _flatten(writer: PdfWriter) -> None:
    """Убирает поля формы: их место занимает нарисованный слой."""
    for page in writer.pages:
        annotations = page.get("/Annots")
        if not annotations:
            continue
        kept = ArrayObject(
            item for item in annotations if item.get_object().get("/Subtype") != "/Widget"
        )
        if kept:
            page[NameObject("/Annots")] = kept
        else:
            del page[NameObject("/Annots")]

    if "/AcroForm" in writer.root_object:
        del writer.root_object[NameObject("/AcroForm")]


def _fitted_size(text: str, binding: FieldBinding) -> float:
    """Длинное название клиники ужимается по кеглю, а не вылезает за ячейку."""
    size = binding.size
    while size > _MIN_FONT_SIZE and pdfmetrics.stringWidth(text, FORM_FONT, size) > binding.width:
        size -= 0.5
    return size


class CertificateRenderer:
    def __init__(self, library: TemplateLibrary, signature_path: str | Path | None = None) -> None:
        self.library = library
        self.signature_path = Path(signature_path) if signature_path else None
        register_form_font()

    def render(self, cert: Certificate) -> bytes:
        template = self.library.for_year(cert.tax_year)
        writer = PdfWriter(clone_from=str(template.pdf_path))

        if len(writer.pages) < cert.pages:
            raise RenderError(
                f"шаблон {template.name} состоит из {len(writer.pages)} страниц, "
                f"а справке нужно {cert.pages}"
            )

        # Пациент — сам налогоплательщик: вторая страница пустая, её не печатаем.
        for index in range(len(writer.pages) - 1, cert.pages - 1, -1):
            writer.remove_page(index, clean=True)

        _flatten(writer)

        for number, page in enumerate(writer.pages):
            overlay = self._overlay(template, cert, number, page)
            if overlay is not None:
                page.merge_page(overlay)

        buffer = BytesIO()
        writer.write(buffer)
        return buffer.getvalue()

    def _overlay(self, template: Template, cert: Certificate, number: int, page):
        cells = template.filled_cells(cert, number)
        signatures = [s for s in template.signatures if s.page == number]
        if not cells and not (signatures and self.signature_path):
            return None

        box = page.mediabox
        buffer = BytesIO()
        # Размер холста берём у самой страницы: бланк не обязан быть A4.
        pen = canvas.Canvas(buffer, pagesize=(float(box.width), float(box.height)))

        for binding, value in cells:
            size = _fitted_size(value, binding)
            pen.setFont(FORM_FONT, size)
            baseline = binding.y + (binding.height - size) / 2 + size * 0.22
            pen.drawString(binding.x + 2, baseline, value)

        if self.signature_path is not None:
            image = _signature_image(str(self.signature_path))
            for placement in signatures:
                pen.drawImage(
                    image,
                    placement.x,
                    placement.y,
                    placement.width,
                    placement.height,
                    mask="auto",
                )

        pen.save()
        buffer.seek(0)
        return PdfReader(buffer).pages[0]
