from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from tax_reporter.intake import (
    ClinicRegistry,
    normalize,
    parse_date,
    parse_flag,
    parse_inn,
    parse_money,
    read_export,
    to_certificates,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("17 500,00", Decimal("17500.00")),
        ("17500.00", Decimal("17500.00")),
        ("17 500,50", Decimal("17500.50")),
        ("8 000 ₽", Decimal("8000.00")),
        ("", Decimal("0.00")),
        (None, Decimal("0.00")),
    ],
)
def test_money_formats(raw, expected: Decimal) -> None:
    assert parse_money(raw) == expected


def test_money_rejects_garbage() -> None:
    with pytest.raises(ValueError):
        parse_money("тысяч двадцать")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("16.04.1984", date(1984, 4, 16)),
        ("1984-04-16", date(1984, 4, 16)),
        ("16/04/1984", date(1984, 4, 16)),
        ("", None),
    ],
)
def test_date_formats(raw, expected) -> None:
    assert parse_date(raw) == expected


def test_date_rejects_garbage() -> None:
    with pytest.raises(ValueError):
        parse_date("апрель 1984")


@pytest.mark.parametrize("raw", ["да", "Да", "1", "true", "YES"])
def test_flag_truthy(raw: str) -> None:
    assert parse_flag(raw) is True


@pytest.mark.parametrize("raw", ["нет", "0", "false", ""])
def test_flag_falsy(raw: str) -> None:
    assert parse_flag(raw) is False


def test_inn_keeps_only_digits() -> None:
    assert parse_inn(" 5001 1122 2355 ") == "500111222355"
    assert parse_inn("—") is None


def test_registry_ignores_quotes_case_and_double_spaces(clinics: ClinicRegistry) -> None:
    variants = [
        "Клиника «Первомайская»",
        "клиника  «первомайская»",
        " Клиника «Первомайская» ",
    ]
    resolved = {clinics.resolve(name).inn for name in variants}
    assert resolved == {"5001112228"}


def test_registry_reports_unknown_clinic(clinics: ClinicRegistry) -> None:
    with pytest.raises(KeyError):
        clinics.resolve("Медцентр «Незнакомый»")


def test_normalize_keeps_last_version_of_a_resubmitted_request(sample_csv: Path) -> None:
    """Заявку №1 отправили дважды: в работу идёт вторая, с исправленной суммой."""
    raw = read_export(sample_csv)
    frame = normalize(raw)

    assert len(raw[raw["serial_number"] == "1"]) == 2
    resubmitted = frame[frame["number"] == "1"]
    assert len(resubmitted) == 1
    assert resubmitted.iloc[0]["amount_standard"] == "19 900,00"


def test_normalize_requires_all_columns() -> None:
    import pandas as pd

    with pytest.raises(ValueError, match="нет колонок"):
        normalize(pd.DataFrame({"serial_number": ["1"]}))


def test_sample_export_splits_into_certificates_and_rejections(
    sample_csv: Path, clinics: ClinicRegistry
) -> None:
    certificates, rejections = to_certificates(normalize(read_export(sample_csv)), clinics)

    assert [r.row for r in rejections] == [6]
    assert "Медцентр «Незнакомый»" in rejections[0].reason

    by_number = {c.number: c for c in certificates}
    assert by_number["1"].amount_standard == Decimal("19900.00")
    assert by_number["1"].patient is None

    child_case = by_number["2"]
    assert child_case.patient is not None
    assert child_case.patient.last_name == "Ковалёва"
    assert child_case.patient.document.kind.value == "03"
    assert child_case.pages == 2


def test_stray_spaces_are_trimmed(sample_csv: Path, clinics: ClinicRegistry) -> None:
    certificates, _ = to_certificates(normalize(read_export(sample_csv)), clinics)
    third = next(c for c in certificates if c.number == "3")
    assert third.taxpayer.last_name == "Тимофеев"
    assert third.clinic.inn == "5001112228"
