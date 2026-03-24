"""Приём и нормализация выгрузки заявок.

Заявки приходят из формы обратной связи, где пациент пишет ФИО как получится:
лишние пробелы, суммы с разделителем-запятой и знаком рубля, даты в трёх форматах.
Модель намеренно строгая, поэтому весь разбор грязного ввода живёт здесь,
а наружу выходят либо готовые Certificate, либо строка с причиной отказа.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import pandas as pd
from pydantic import ValidationError

from .models import KOPECKS, Certificate, Clinic, IdentityDocument, Person

# Имена колонок такие, какими их отдаёт выгрузка формы: латиницей, транслитом.
COLUMNS = {
    "serial_number": "number",
    "nomer_korrektirovki": "correction",
    "za_kakoy_god_nuzhna_spravka": "tax_year",
    "data_vydachi": "issued_at",
    "gde_provodilos_lechenie": "clinic_name",
    "nalog_surname": "taxpayer_last_name",
    "nalog_name": "taxpayer_first_name",
    "nalog_patronymic": "taxpayer_patronymic",
    "nalog_inn": "taxpayer_inn",
    "nalog_birth_date": "taxpayer_birth_date",
    "odno_litso": "same_person",
    "patient_surname": "patient_last_name",
    "patient_name": "patient_first_name",
    "patient_patronymic": "patient_patronymic",
    "patient_inn": "patient_inn",
    "patient_birth_date": "patient_birth_date",
    "patient_doc_kind": "patient_document_kind",
    "patient_doc_number": "patient_document_number",
    "patient_doc_date": "patient_document_issued_at",
    "summa_kod_1": "amount_standard",
    "summa_kod_2": "amount_expensive",
    "podpisant": "signer",
}

KEY_COLUMNS = ("clinic_name", "tax_year", "number", "correction")

_WHITESPACE = re.compile(r"\s+")
_DATE_FORMATS = ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y")
_TRUE_WORDS = {"1", "да", "true", "yes", "y", "истина"}
_FALSE_WORDS = {"0", "нет", "false", "no", "n", "ложь", ""}


@dataclass(frozen=True, slots=True)
class Rejection:
    """Строка, которую не удалось превратить в справку."""

    row: int
    reason: str


class ClinicRegistry:
    """Справочник клиник: выгрузка приносит только название, реквизиты берём отсюда."""

    def __init__(self, clinics: Iterable[Clinic]) -> None:
        self._by_key = {self._key(c.name): c for c in clinics}

    @staticmethod
    def _key(name: str) -> str:
        return _WHITESPACE.sub(" ", name).strip().strip('«»"').casefold()

    @classmethod
    def from_file(cls, path: str | Path) -> ClinicRegistry:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(Clinic.model_validate(item) for item in payload)

    def resolve(self, name: str) -> Clinic:
        try:
            return self._by_key[self._key(name)]
        except KeyError:
            raise KeyError(f"клиника {name!r} отсутствует в справочнике") from None


def clean(value: Any) -> str | None:
    if value is None:
        return None
    text = _WHITESPACE.sub(" ", str(value)).strip()
    return text or None


def parse_money(value: Any) -> Decimal:
    text = clean(value)
    if text is None:
        return Decimal("0")
    normalized = text.replace(" ", "").replace(" ", "").replace("₽", "").replace(",", ".")
    try:
        return Decimal(normalized).quantize(KOPECKS)
    except InvalidOperation:
        raise ValueError(f"не разобрана сумма {text!r}") from None


def parse_date(value: Any) -> date | None:
    text = clean(value)
    if text is None:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"не разобрана дата {text!r}")


def parse_flag(value: Any) -> bool:
    text = (clean(value) or "").casefold()
    if text in _TRUE_WORDS:
        return True
    if text in _FALSE_WORDS:
        return False
    raise ValueError(f"не разобран признак {text!r}")


def parse_inn(value: Any) -> str | None:
    text = clean(value)
    if text is None:
        return None
    digits = re.sub(r"\D", "", text)
    return digits or None


def parse_int(value: Any, default: int = 0) -> int:
    text = clean(value)
    if text is None:
        return default
    try:
        return int(text)
    except ValueError:
        raise ValueError(f"ожидалось целое число, получено {text!r}") from None


def read_export(source: str | Path) -> pd.DataFrame:
    """Всё читаем строками: сумма 17500.00 не должна стать float, а ИНН — потерять ноль."""
    return pd.read_csv(source, dtype=str, keep_default_na=False)


def normalize(frame: pd.DataFrame) -> pd.DataFrame:
    """Приводит колонки к внутренним именам, чистит пробелы и снимает дубли заявок."""
    missing = set(COLUMNS) - set(frame.columns)
    if missing:
        raise ValueError(f"в выгрузке нет колонок: {', '.join(sorted(missing))}")

    result = frame.rename(columns=COLUMNS)[list(COLUMNS.values())]
    result = result.map(lambda value: clean(value) or "")
    result = result[result["number"] != ""]

    # Форму переотправляют, когда заметили опечатку: побеждает последняя версия.
    result = result.drop_duplicates(subset=list(KEY_COLUMNS), keep="last")
    return result.reset_index(drop=True)


def _person(row: dict[str, str], prefix: str) -> Person | None:
    last_name = clean(row.get(f"{prefix}_last_name"))
    first_name = clean(row.get(f"{prefix}_first_name"))
    if not last_name or not first_name:
        return None

    document = None
    kind = clean(row.get(f"{prefix}_document_kind"))
    if kind:
        document = IdentityDocument(
            kind=kind,
            series_number=clean(row.get(f"{prefix}_document_number")) or "",
            issued_at=parse_date(row.get(f"{prefix}_document_issued_at")),
        )

    return Person(
        last_name=last_name,
        first_name=first_name,
        patronymic=clean(row.get(f"{prefix}_patronymic")),
        inn=parse_inn(row.get(f"{prefix}_inn")),
        birth_date=parse_date(row.get(f"{prefix}_birth_date")),
        document=document,
    )


def to_certificates(
    frame: pd.DataFrame, clinics: ClinicRegistry
) -> tuple[list[Certificate], list[Rejection]]:
    certificates: list[Certificate] = []
    rejections: list[Rejection] = []

    for position, row in enumerate(frame.to_dict("records")):
        try:
            taxpayer = _person(row, "taxpayer")
            if taxpayer is None:
                raise ValueError("не указано ФИО налогоплательщика")

            patient = None if parse_flag(row["same_person"]) else _person(row, "patient")

            certificates.append(
                Certificate(
                    number=row["number"],
                    correction=parse_int(row["correction"]),
                    tax_year=parse_int(row["tax_year"]),
                    issued_at=parse_date(row["issued_at"]),
                    clinic=clinics.resolve(row["clinic_name"]),
                    taxpayer=taxpayer,
                    patient=patient,
                    amount_standard=parse_money(row["amount_standard"]),
                    amount_expensive=parse_money(row["amount_expensive"]),
                    signer=row["signer"],
                )
            )
        except (ValueError, KeyError, ValidationError) as exc:
            rejections.append(Rejection(row=position, reason=str(exc).replace("\n", "; ")))

    return certificates, rejections
