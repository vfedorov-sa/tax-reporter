"""Контрольные соотношения справки.

Проверки уровня поля (длина, тип, диапазон) делает pydantic при разборе.
Здесь остаются только межполевые правила — то, что нельзя проверить, глядя
на одно значение: согласованность дат, документов, сумм и признака пациента.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum

from .inn import is_valid_inn, is_valid_kpp
from .models import Certificate, DocumentKind

# Возраст, с которого документом становится паспорт, а не свидетельство о рождении.
PASSPORT_AGE = 14

# Предельный срок обращения за вычетом, лет.
DEDUCTION_WINDOW_YEARS = 3


class Severity(StrEnum):
    ERROR = "error"
    WARNING = "warning"


@dataclass(frozen=True, slots=True)
class Issue:
    code: str
    field: str
    message: str
    severity: Severity = Severity.ERROR


def deduction_limit(tax_year: int) -> Decimal:
    """Предел социального вычета по обычному лечению: с 2024 года поднят до 150 тысяч."""
    return Decimal("150000") if tax_year >= 2024 else Decimal("120000")


def _check_clinic(cert: Certificate, today: date) -> Iterator[Issue]:
    if not is_valid_inn(cert.clinic.inn) or len(cert.clinic.inn) != 10:
        yield Issue(
            "CLINIC_INN",
            "clinic.inn",
            f"ИНН организации {cert.clinic.inn!r} не проходит проверку контрольного разряда",
        )
    if not is_valid_kpp(cert.clinic.kpp):
        yield Issue("CLINIC_KPP", "clinic.kpp", f"КПП {cert.clinic.kpp!r} не соответствует формату")


def _check_taxpayer_inn(cert: Certificate, today: date) -> Iterator[Issue]:
    inn = cert.taxpayer.inn
    if inn is None:
        # В форме ИНН физлица помечен сноской «указывается при наличии».
        yield Issue(
            "TAXPAYER_INN_MISSING",
            "taxpayer.inn",
            "ИНН налогоплательщика не указан: справка примется, "
            "но сопоставление в ФНС пойдёт по ФИО",
            Severity.WARNING,
        )
    elif not is_valid_inn(inn) or len(inn) != 12:
        yield Issue(
            "TAXPAYER_INN",
            "taxpayer.inn",
            f"ИНН физлица {inn!r} не проходит проверку контрольных разрядов",
        )


def _check_patient_inn(cert: Certificate, today: date) -> Iterator[Issue]:
    patient = cert.patient
    if patient is None or patient.inn is None:
        return
    if not is_valid_inn(patient.inn) or len(patient.inn) != 12:
        yield Issue(
            "PATIENT_INN",
            "patient.inn",
            f"ИНН пациента {patient.inn!r} не проходит проверку контрольных разрядов",
        )


def _check_amounts(cert: Certificate, today: date) -> Iterator[Issue]:
    if cert.total <= 0:
        yield Issue(
            "AMOUNT_EMPTY",
            "amount_standard",
            "хотя бы одна из сумм по кодам услуг «1» и «2» должна быть положительной",
        )
        return

    limit = deduction_limit(cert.tax_year)
    if cert.amount_standard > limit:
        yield Issue(
            "AMOUNT_OVER_LIMIT",
            "amount_standard",
            f"расходы по коду «1» ({cert.amount_standard}) превышают предел вычета "
            f"за {cert.tax_year} год ({limit}); справка верна, но зачтётся только предел",
            Severity.WARNING,
        )


def _check_period(cert: Certificate, today: date) -> Iterator[Issue]:
    if cert.tax_year > cert.issued_at.year:
        yield Issue(
            "PERIOD_AHEAD",
            "tax_year",
            f"отчётный год {cert.tax_year} позже даты выдачи {cert.issued_at:%d.%m.%Y}",
        )
    elif cert.issued_at.year - cert.tax_year > DEDUCTION_WINDOW_YEARS:
        yield Issue(
            "PERIOD_STALE",
            "tax_year",
            f"с конца {cert.tax_year} года прошло больше {DEDUCTION_WINDOW_YEARS} лет, "
            "вычет за этот период уже не заявить",
            Severity.WARNING,
        )

    if cert.issued_at > today:
        yield Issue(
            "ISSUED_IN_FUTURE",
            "issued_at",
            f"дата выдачи {cert.issued_at:%d.%m.%Y} в будущем",
        )


def _check_patient_block(cert: Certificate, today: date) -> Iterator[Issue]:
    patient = cert.patient
    if patient is None:
        return

    if (patient.last_name, patient.first_name, patient.birth_date) == (
        cert.taxpayer.last_name,
        cert.taxpayer.first_name,
        cert.taxpayer.birth_date,
    ):
        yield Issue(
            "PATIENT_DUPLICATES_TAXPAYER",
            "patient",
            "пациент совпадает с налогоплательщиком — вторая страница не нужна, "
            "признак должен быть «одно лицо»",
        )

    if patient.birth_date is None:
        yield Issue("PATIENT_BIRTH_DATE", "patient.birth_date", "не указана дата рождения пациента")
    elif patient.birth_date > cert.issued_at:
        yield Issue(
            "PATIENT_BORN_LATER",
            "patient.birth_date",
            "пациент родился позже даты выдачи справки",
        )

    if patient.document is None:
        yield Issue(
            "PATIENT_DOCUMENT",
            "patient.document",
            "для пациента, отличного от налогоплательщика, документ обязателен",
        )


def _check_patient_document_kind(cert: Certificate, today: date) -> Iterator[Issue]:
    patient = cert.patient
    if patient is None or patient.document is None:
        return

    age = patient.age_at(cert.issued_at)
    if age is None:
        return

    kind = patient.document.kind
    if age < PASSPORT_AGE and kind is not DocumentKind.BIRTH_CERTIFICATE:
        yield Issue(
            "DOCUMENT_KIND_MINOR",
            "patient.document.kind",
            f"пациенту {age} лет, ожидается свидетельство о рождении "
            f"(код {DocumentKind.BIRTH_CERTIFICATE.value}), указан код {kind.value}",
        )
    elif age >= PASSPORT_AGE and kind is DocumentKind.BIRTH_CERTIFICATE:
        yield Issue(
            "DOCUMENT_KIND_ADULT",
            "patient.document.kind",
            f"пациенту {age} лет, свидетельство о рождении больше не является "
            "документом, удостоверяющим личность",
        )

    if patient.document.issued_at > cert.issued_at:
        yield Issue(
            "DOCUMENT_ISSUED_LATER",
            "patient.document.issued_at",
            "документ пациента выдан позже самой справки",
        )


RULES = (
    _check_clinic,
    _check_taxpayer_inn,
    _check_patient_inn,
    _check_amounts,
    _check_period,
    _check_patient_block,
    _check_patient_document_kind,
)


def validate(cert: Certificate, *, today: date | None = None) -> list[Issue]:
    moment = today or date.today()
    return [issue for rule in RULES for issue in rule(cert, moment)]


def has_errors(issues: Iterable[Issue]) -> bool:
    return any(issue.severity is Severity.ERROR for issue in issues)


def find_duplicates(certificates: Iterable[Certificate]) -> dict[tuple, list[int]]:
    """Номер справки должен быть уникален в пределах клиники, года и корректировки."""
    seen: dict[tuple, list[int]] = defaultdict(list)
    for index, cert in enumerate(certificates):
        seen[cert.key].append(index)
    return {key: rows for key, rows in seen.items() if len(rows) > 1}
