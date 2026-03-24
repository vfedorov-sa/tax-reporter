"""Собирает бланк справки и карту полей к нему.

PDF и templates/<name>.json порождаются из одного описания, поэтому геометрия
ячеек в бланке и в карте не могут разъехаться. Запускать нужно только при смене
формы — готовый бланк лежит в репозитории.

    python scripts/build_template.py --tax-year 2025
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

from reportlab.lib.colors import Color, black
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tax_reporter.fonts import FORM_FONT, FontNotFound, register_form_font  # noqa: E402

PAGE_W, PAGE_H = A4
LEFT = 30.0
CELL = Color(0.92, 0.94, 0.99)
RULE = Color(0.70, 0.75, 0.88)


@dataclass(slots=True)
class Cell:
    name: str
    page: int
    x: float
    y: float
    width: float
    height: float
    binding: dict[str, object]

    def describe(self) -> dict[str, object]:
        return {
            "page": self.page,
            "x": round(self.x, 2),
            "y": round(self.y, 2),
            "width": round(self.width, 2),
            "height": round(self.height, 2),
            **self.binding,
        }


@dataclass(slots=True)
class Sheet:
    """Тонкая обёртка над canvas: координаты сверху вниз и подписи к ячейкам."""

    pen: canvas.Canvas
    page: int
    cells: list[Cell] = field(default_factory=list)

    def label(self, x: float, top: float, text: str, size: float = 7.0) -> None:
        self.pen.setFont(FORM_FONT, size)
        self.pen.setFillColor(black)
        self.pen.drawString(x, PAGE_H - top, text)

    def title(self, top: float, text: str, size: float = 10.0) -> None:
        self.pen.setFont(FORM_FONT, size)
        self.pen.setFillColor(black)
        self.pen.drawCentredString(PAGE_W / 2, PAGE_H - top, text)

    def rule(self, x: float, top: float, width: float) -> None:
        self.pen.setStrokeColor(black)
        self.pen.setLineWidth(0.6)
        self.pen.line(x, PAGE_H - top, x + width, PAGE_H - top)

    def cell(
        self,
        name: str,
        x: float,
        top: float,
        width: float,
        binding: dict[str, object],
        height: float = 15.0,
    ) -> None:
        y = PAGE_H - top - height
        self.pen.setFillColor(CELL)
        self.pen.setStrokeColor(RULE)
        self.pen.setLineWidth(0.4)
        self.pen.rect(x, y, width, height, stroke=1, fill=1)
        self.cells.append(Cell(name, self.page, x, y, width, height, binding))

    def labelled(
        self,
        caption: str,
        name: str,
        x: float,
        top: float,
        width: float,
        binding: dict[str, object],
        caption_width: float = 70.0,
    ) -> None:
        self.label(x, top + 11, caption)
        self.cell(name, x + caption_width, top, width, binding)


def header(sheet: Sheet, prefix: str, page_no: str) -> None:
    sheet.label(LEFT + 118, 44, "ИНН")
    sheet.cell(f"{prefix}_clinic_inn", LEFT + 150, 32, 130, {"source": "clinic.inn"})
    sheet.label(LEFT + 118, 64, "КПП")
    sheet.cell(f"{prefix}_clinic_kpp", LEFT + 150, 52, 110, {"source": "clinic.kpp"})
    sheet.label(LEFT + 272, 64, "Стр.")
    sheet.cell(f"{prefix}_page_no", LEFT + 295, 52, 40, {"const": page_no})


def build_page_one(pen: canvas.Canvas) -> Sheet:
    sheet = Sheet(pen, page=0)
    header(sheet, "p1", "001")

    sheet.label(LEFT, 98, "Форма по КНД 1151156", 8)
    sheet.title(96, "Справка")
    sheet.title(111, "об оплате медицинских услуг для представления")
    sheet.title(126, "в налоговый орган")

    sheet.labelled("Номер справки", "number", LEFT, 152, 120, {"source": "number"}, 80)
    sheet.labelled(
        "Номер корректировки", "correction", LEFT + 225, 152, 40, {"source": "correction"}, 105
    )
    sheet.labelled("Отчётный год", "tax_year", LEFT + 395, 152, 60, {"source": "tax_year"}, 70)

    sheet.label(
        LEFT,
        182,
        "Данные медицинской организации / индивидуального предпринимателя, "
        "осуществляющего медицинскую деятельность:",
    )
    sheet.cell("clinic_name", LEFT, 188, PAGE_W - 2 * LEFT, {"source": "clinic.name"}, 20)
    sheet.label(
        LEFT + 95,
        222,
        "(наименование медицинской организации / фамилия, имя, отчество "
        "индивидуального предпринимателя)",
        6.5,
    )

    sheet.label(
        LEFT,
        248,
        "Данные физического лица (его супруга/супруги), оплатившего медицинские услуги "
        "(далее — налогоплательщик):",
    )
    sheet.labelled("Фамилия", "tp_last_name", LEFT, 256, 240, {"source": "taxpayer.last_name"}, 55)
    sheet.labelled("Имя", "tp_first_name", LEFT, 276, 240, {"source": "taxpayer.first_name"}, 55)
    sheet.labelled(
        "Отчество", "tp_patronymic", LEFT, 296, 240, {"source": "taxpayer.patronymic"}, 55
    )
    sheet.labelled("ИНН", "tp_inn", LEFT, 316, 160, {"source": "taxpayer.inn"}, 55)
    sheet.labelled(
        "Дата рождения",
        "tp_birth_date",
        LEFT + 250,
        316,
        110,
        {"source": "taxpayer.birth_date", "format": "date"},
        75,
    )

    sheet.label(LEFT, 350, "Сведения о документе, удостоверяющем личность:")
    sheet.labelled(
        "Код вида документа",
        "tp_doc_kind",
        LEFT,
        358,
        40,
        {"source": "taxpayer.document.kind"},
        100,
    )
    sheet.labelled(
        "Серия и номер",
        "tp_doc_number",
        LEFT + 250,
        358,
        160,
        {"source": "taxpayer.document.series_number"},
        75,
    )
    sheet.labelled(
        "Дата выдачи",
        "tp_doc_date",
        LEFT,
        378,
        110,
        {"source": "taxpayer.document.issued_at", "format": "date"},
        75,
    )

    sheet.label(LEFT, 414, "Налогоплательщик и пациент являются одним лицом")
    sheet.cell(
        "same_person", LEFT + 275, 404, 30, {"source": "patient_is_taxpayer", "format": "flag"}
    )
    sheet.label(LEFT + 320, 410, "0 — нет")
    sheet.label(LEFT + 320, 420, "1 — да")

    _amount_row(
        sheet,
        442,
        "Сумма расходов на оказанные медицинские услуги по коду услуги «1»",
        "amount1",
        "amount_standard",
    )
    _amount_row(
        sheet,
        467,
        "Сумма расходов на оказанные медицинские услуги по коду услуги «2»",
        "amount2",
        "amount_expensive",
    )

    sheet.label(
        LEFT, 508, "Достоверность и полноту сведений, указанных в настоящей справке, подтверждаю:"
    )
    sheet.cell("signer_name", LEFT, 514, 300, {"source": "signer"})
    sheet.label(LEFT + 85, 546, "(фамилия, имя, отчество)", 6.5)

    sheet.label(LEFT, 578, "Подпись")
    sheet.rule(LEFT + 45, 582, 130)
    sheet.labelled(
        "Дата", "sign_date", LEFT + 200, 570, 110, {"source": "issued_at", "format": "date"}, 30
    )

    sheet.label(LEFT, 614, "Справка составлена на")
    sheet.cell("pages", LEFT + 110, 604, 40, {"source": "pages", "format": "pad3"})
    sheet.label(LEFT + 158, 614, "страницах")
    return sheet


def _amount_row(sheet: Sheet, top: float, caption: str, prefix: str, source: str) -> None:
    sheet.label(LEFT, top + 11, caption)
    sheet.cell(f"{prefix}_rub", LEFT + 370, top, 110, {"source": source, "format": "rubles"})
    sheet.label(LEFT + 484, top + 11, ".", 11)
    sheet.cell(f"{prefix}_kop", LEFT + 492, top, 35, {"source": source, "format": "kopecks"})


def build_page_two(pen: canvas.Canvas) -> Sheet:
    sheet = Sheet(pen, page=1)
    header(sheet, "p2", "002")

    sheet.label(LEFT, 102, "Данные физического лица, которому оказаны медицинские услуги:")
    sheet.labelled("Фамилия", "pt_last_name", LEFT, 110, 240, {"source": "patient.last_name"}, 55)
    sheet.labelled("Имя", "pt_first_name", LEFT, 130, 240, {"source": "patient.first_name"}, 55)
    sheet.labelled(
        "Отчество", "pt_patronymic", LEFT, 150, 240, {"source": "patient.patronymic"}, 55
    )
    sheet.labelled("ИНН", "pt_inn", LEFT, 170, 160, {"source": "patient.inn"}, 55)
    sheet.labelled(
        "Дата рождения",
        "pt_birth_date",
        LEFT + 250,
        170,
        110,
        {"source": "patient.birth_date", "format": "date"},
        75,
    )

    sheet.label(LEFT, 205, "Сведения о документе, удостоверяющем личность:")
    sheet.labelled(
        "Код вида документа", "pt_doc_kind", LEFT, 213, 40, {"source": "patient.document.kind"}, 100
    )
    sheet.labelled(
        "Серия и номер",
        "pt_doc_number",
        LEFT + 250,
        213,
        160,
        {"source": "patient.document.series_number"},
        75,
    )
    sheet.labelled(
        "Дата выдачи",
        "pt_doc_date",
        LEFT,
        233,
        110,
        {"source": "patient.document.issued_at", "format": "date"},
        75,
    )

    sheet.label(
        LEFT, 772, "Достоверность и полноту сведений, указанных на данной странице, подтверждаю:"
    )
    sheet.rule(LEFT + 20, 800, 130)
    sheet.label(LEFT + 60, 810, "(подпись)", 6.5)
    sheet.labelled(
        "Дата", "p2_sign_date", LEFT + 250, 790, 110, {"source": "issued_at", "format": "date"}, 30
    )
    return sheet


def build(tax_year: int, directory: Path) -> tuple[Path, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    name = f"certificate-{tax_year}"
    pdf_path = directory / f"{name}.pdf"

    pen = canvas.Canvas(str(pdf_path), pagesize=A4)
    pen.setTitle(f"Справка об оплате медицинских услуг, {tax_year}")
    sheets = [build_page_one(pen)]
    pen.showPage()
    sheets.append(build_page_two(pen))
    pen.showPage()
    pen.save()

    descriptor = {
        "name": name,
        "tax_year": tax_year,
        "pdf": pdf_path.name,
        "signatures": [
            {"page": 0, "x": LEFT + 48, "y": PAGE_H - 582, "width": 100, "height": 28},
            {"page": 1, "x": LEFT + 25, "y": PAGE_H - 800, "width": 100, "height": 28},
        ],
        "fields": {cell.name: cell.describe() for sheet in sheets for cell in sheet.cells},
    }
    json_path = directory / f"{name}.json"
    json_path.write_text(
        json.dumps(descriptor, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return pdf_path, json_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tax-year", type=int, default=2025)
    parser.add_argument("--out", type=Path, default=Path("templates"))
    args = parser.parse_args()

    try:
        font = register_form_font()
    except FontNotFound as exc:
        raise SystemExit(str(exc)) from exc

    pdf_path, json_path = build(args.tax_year, args.out)
    print(f"шрифт: {font}")
    print(f"бланк: {pdf_path}")
    print(f"карта: {json_path}")


if __name__ == "__main__":
    main()
