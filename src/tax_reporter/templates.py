"""Шаблоны форм и привязка полей.

Форма меняется почти каждый год, поэтому её описание вынесено из кода в JSON рядом
с PDF: где на странице лежит поле, откуда берётся значение и как его отформатировать.
Новый отчётный год — это новая пара файлов в templates/, а не правка рендерера.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any

from .models import Certificate


@dataclass(frozen=True, slots=True)
class SignaturePlacement:
    """Координаты в пунктах PDF, начало отсчёта — левый нижний угол страницы."""

    page: int
    x: float
    y: float
    width: float
    height: float


@dataclass(frozen=True, slots=True)
class FieldBinding:
    """Ячейка бланка: место на странице плюс источник значения.

    Значение приходит либо по пути в модели (source), либо константой (const) —
    константами заданы номера страниц в шапке бланка.
    """

    page: int
    x: float
    y: float
    width: float
    height: float
    source: str | None = None
    const: str | None = None
    format: str = "text"
    size: float = 9.0

    def __post_init__(self) -> None:
        if (self.source is None) == (self.const is None):
            raise ValueError("у поля должен быть ровно один из source и const")


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, Enum):
        return str(value.value)
    return str(value)


def _as_date(value: Any) -> str:
    return "" if value is None else f"{value:%d.%m.%Y}"


def _year(value: Any) -> str:
    if value is None:
        return ""
    return f"{value.year}" if isinstance(value, date) else f"{int(value):04d}"


def _rubles(value: Any) -> str:
    return "" if value is None else str(int(Decimal(value)))


def _kopecks(value: Any) -> str:
    if value is None:
        return ""
    amount = Decimal(value)
    return f"{int((amount - int(amount)) * 100):02d}"


def _flag(value: Any) -> str:
    return "1" if value else "0"


def _padded(width: int) -> Callable[[Any], str]:
    def render(value: Any) -> str:
        return "" if value is None else f"{int(value):0{width}d}"

    return render


FORMATTERS: dict[str, Callable[[Any], str]] = {
    "text": _text,
    "date": _as_date,
    "year": _year,
    "rubles": _rubles,
    "kopecks": _kopecks,
    "flag": _flag,
    "pad2": _padded(2),
    "pad3": _padded(3),
}


def resolve(cert: Certificate, path: str) -> Any:
    """Разыменовывает путь вида patient.document.series_number, пустой блок даёт None."""
    value: Any = cert
    for part in path.split("."):
        if value is None:
            return None
        value = getattr(value, part)
    return value


@dataclass(frozen=True, slots=True)
class Template:
    name: str
    tax_year: int
    pdf_path: Path
    fields: dict[str, FieldBinding]
    signatures: tuple[SignaturePlacement, ...]

    @classmethod
    def load(cls, path: str | Path) -> Template:
        path = Path(path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            name=payload["name"],
            tax_year=int(payload["tax_year"]),
            pdf_path=path.with_name(payload["pdf"]),
            fields={name: FieldBinding(**item) for name, item in payload["fields"].items()},
            signatures=tuple(SignaturePlacement(**item) for item in payload["signatures"]),
        )

    def value_of(self, cert: Certificate, binding: FieldBinding) -> str:
        if binding.const is not None:
            return binding.const
        formatter = FORMATTERS.get(binding.format)
        if formatter is None:
            raise KeyError(f"неизвестный формат {binding.format!r}")
        return formatter(resolve(cert, binding.source))

    def values_for(self, cert: Certificate) -> dict[str, str]:
        return {name: self.value_of(cert, binding) for name, binding in self.fields.items()}

    def filled_cells(self, cert: Certificate, page: int) -> list[tuple[FieldBinding, str]]:
        """Непустые значения одной страницы — ровно то, что нужно нарисовать."""
        cells = []
        for binding in self.fields.values():
            if binding.page != page:
                continue
            value = self.value_of(cert, binding)
            if value:
                cells.append((binding, value))
        return cells


class TemplateLibrary:
    """Шаблоны, разложенные по отчётным годам."""

    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory)
        self._by_year: dict[int, Template] = {}
        for descriptor in sorted(self.directory.glob("certificate-*.json")):
            template = Template.load(descriptor)
            self._by_year[template.tax_year] = template

    def __len__(self) -> int:
        return len(self._by_year)

    @property
    def years(self) -> list[int]:
        return sorted(self._by_year)

    def for_year(self, tax_year: int) -> Template:
        try:
            return self._by_year[tax_year]
        except KeyError:
            known = ", ".join(map(str, self.years)) or "нет ни одного"
            raise KeyError(f"нет шаблона за {tax_year} год (загружены: {known})") from None
