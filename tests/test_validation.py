from __future__ import annotations

from datetime import date
from decimal import Decimal

from conftest import TODAY
from tax_reporter.models import Certificate, DocumentKind, IdentityDocument, Person
from tax_reporter.validation import (
    Severity,
    deduction_limit,
    find_duplicates,
    has_errors,
    validate,
)


def codes(cert: Certificate) -> set[str]:
    return {issue.code for issue in validate(cert, today=TODAY)}


def test_clean_certificate_passes(certificate: Certificate) -> None:
    assert validate(certificate, today=TODAY) == []


def test_broken_clinic_inn(certificate: Certificate) -> None:
    broken = certificate.model_copy(
        update={"clinic": certificate.clinic.model_copy(update={"inn": "5001112227"})}
    )
    assert "CLINIC_INN" in codes(broken)


def test_missing_taxpayer_inn_is_only_a_warning(certificate: Certificate) -> None:
    anonymous = certificate.model_copy(
        update={"taxpayer": certificate.taxpayer.model_copy(update={"inn": None})}
    )
    issues = validate(anonymous, today=TODAY)
    assert [i.code for i in issues] == ["TAXPAYER_INN_MISSING"]
    assert not has_errors(issues)


def test_broken_taxpayer_inn_blocks(certificate: Certificate) -> None:
    broken = certificate.model_copy(
        update={"taxpayer": certificate.taxpayer.model_copy(update={"inn": "123456789012"})}
    )
    assert has_errors(validate(broken, today=TODAY))


def test_zero_amounts_block(certificate: Certificate) -> None:
    empty = certificate.model_copy(
        update={"amount_standard": Decimal("0"), "amount_expensive": Decimal("0")}
    )
    assert "AMOUNT_EMPTY" in codes(empty)


def test_amount_over_limit_is_a_warning(certificate: Certificate) -> None:
    rich = certificate.model_copy(update={"amount_standard": Decimal("310000.00")})
    issues = validate(rich, today=TODAY)
    assert [i.severity for i in issues] == [Severity.WARNING]
    assert "AMOUNT_OVER_LIMIT" in {i.code for i in issues}


def test_expensive_treatment_has_no_limit(certificate: Certificate) -> None:
    """Код услуги «2» — дорогостоящее лечение, оно принимается к вычету целиком."""
    costly = certificate.model_copy(
        update={"amount_standard": Decimal("0"), "amount_expensive": Decimal("310000.00")}
    )
    assert validate(costly, today=TODAY) == []


def test_deduction_limit_raised_in_2024() -> None:
    assert deduction_limit(2023) == Decimal("120000")
    assert deduction_limit(2024) == Decimal("150000")
    assert deduction_limit(2025) == Decimal("150000")


def test_period_ahead_of_issue_date(certificate: Certificate) -> None:
    assert "PERIOD_AHEAD" in codes(certificate.model_copy(update={"tax_year": 2027}))


def test_stale_period_is_a_warning(certificate: Certificate) -> None:
    old = certificate.model_copy(update={"tax_year": 2021})
    issues = validate(old, today=TODAY)
    assert "PERIOD_STALE" in {i.code for i in issues}
    assert not has_errors(issues)


def test_issue_date_in_the_future(certificate: Certificate) -> None:
    assert "ISSUED_IN_FUTURE" in codes(
        certificate.model_copy(update={"issued_at": date(2026, 12, 31)})
    )


def test_patient_equal_to_taxpayer(certificate: Certificate, taxpayer: Person) -> None:
    twin = certificate.model_copy(update={"patient": taxpayer})
    assert "PATIENT_DUPLICATES_TAXPAYER" in codes(twin)


def test_patient_without_document(certificate: Certificate, child: Person) -> None:
    undocumented = certificate.model_copy(
        update={"patient": child.model_copy(update={"document": None})}
    )
    assert "PATIENT_DOCUMENT" in codes(undocumented)


def test_child_with_passport(certificate: Certificate, child: Person) -> None:
    wrong = child.model_copy(
        update={
            "document": IdentityDocument(
                kind=DocumentKind.RF_PASSPORT,
                series_number="45 20 112233",
                issued_at=date(2022, 6, 9),
            )
        }
    )
    assert "DOCUMENT_KIND_MINOR" in codes(certificate.model_copy(update={"patient": wrong}))


def test_adult_with_birth_certificate(certificate: Certificate, child: Person) -> None:
    grown = child.model_copy(update={"birth_date": date(1949, 2, 2)})
    assert "DOCUMENT_KIND_ADULT" in codes(certificate.model_copy(update={"patient": grown}))


def test_child_with_birth_certificate_passes(certificate: Certificate, child: Person) -> None:
    assert validate(certificate.model_copy(update={"patient": child}), today=TODAY) == []


def test_document_issued_after_certificate(certificate: Certificate, child: Person) -> None:
    late = child.model_copy(
        update={
            "document": child.document.model_copy(update={"issued_at": date(2026, 6, 1)})
        }
    )
    assert "DOCUMENT_ISSUED_LATER" in codes(certificate.model_copy(update={"patient": late}))


def test_duplicates_are_found_by_clinic_year_and_number(certificate: Certificate) -> None:
    same = certificate.model_copy()
    other = certificate.model_copy(update={"number": "2"})
    correction = certificate.model_copy(update={"correction": 1})

    duplicates = find_duplicates([certificate, same, other, correction])
    assert list(duplicates.values()) == [[0, 1]]
