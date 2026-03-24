from __future__ import annotations

from io import BytesIO

import pytest
from pypdf import PdfReader

from tax_reporter.models import Certificate, Person
from tax_reporter.rendering import CertificateRenderer, _fitted_size
from tax_reporter.templates import FieldBinding


def read(content: bytes) -> PdfReader:
    return PdfReader(BytesIO(content))


def test_output_is_a_pdf(renderer: CertificateRenderer, certificate: Certificate) -> None:
    assert renderer.render(certificate).startswith(b"%PDF")


def test_single_page_when_patient_is_the_taxpayer(
    renderer: CertificateRenderer, certificate: Certificate
) -> None:
    assert len(read(renderer.render(certificate)).pages) == 1


def test_second_page_appears_for_a_separate_patient(
    renderer: CertificateRenderer, certificate: Certificate, child: Person
) -> None:
    with_child = certificate.model_copy(update={"patient": child})
    assert with_child.pages == 2
    assert len(read(renderer.render(with_child)).pages) == 2


def test_result_has_no_editable_fields(
    renderer: CertificateRenderer, certificate: Certificate
) -> None:
    """Шлюз отклоняет пакет с живой формой, поэтому поля должны быть схлопнуты."""
    assert read(renderer.render(certificate)).get_fields() is None


def test_values_land_on_the_page(
    renderer: CertificateRenderer, certificate: Certificate
) -> None:
    text = read(renderer.render(certificate)).pages[0].extract_text()
    assert "Соколова" in text
    assert "Петровна" in text
    assert certificate.clinic.inn in text
    assert "17500" in text


def test_patient_data_lands_on_the_second_page(
    renderer: CertificateRenderer, certificate: Certificate, child: Person
) -> None:
    pages = read(renderer.render(certificate.model_copy(update={"patient": child}))).pages
    assert "Мирон" in pages[1].extract_text()
    assert "Мирон" not in pages[0].extract_text()


def test_same_person_flag_follows_the_patient_block(
    renderer: CertificateRenderer, certificate: Certificate, child: Person
) -> None:
    template = renderer.library.for_year(certificate.tax_year)
    with_child = certificate.model_copy(update={"patient": child})
    assert template.values_for(certificate)["same_person"] == "1"
    assert template.values_for(with_child)["same_person"] == "0"


def test_amount_splits_into_rubles_and_kopecks(
    renderer: CertificateRenderer, certificate: Certificate
) -> None:
    from decimal import Decimal

    values = renderer.library.for_year(2025).values_for(
        certificate.model_copy(update={"amount_standard": Decimal("42300.50")})
    )
    assert values["amount1_rub"] == "42300"
    assert values["amount1_kop"] == "50"
    assert values["amount2_rub"] == "0"
    assert values["amount2_kop"] == "00"


def test_missing_template_year_is_reported(
    renderer: CertificateRenderer, certificate: Certificate
) -> None:
    with pytest.raises(KeyError, match="1999"):
        renderer.render(certificate.model_copy(update={"tax_year": 1999}))


def test_long_value_shrinks_instead_of_overflowing() -> None:
    binding = FieldBinding(page=0, x=0, y=0, width=80, height=15, source="clinic.name")
    short = _fitted_size("ООО «Ромашка»", binding)
    long = _fitted_size("ООО «Многопрофильный медицинский центр имени Пирогова»", binding)
    assert short == binding.size
    assert long < short
