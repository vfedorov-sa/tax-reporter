from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from tax_reporter.intake import ClinicRegistry
from tax_reporter.models import Certificate, DocumentKind, IdentityDocument, Person
from tax_reporter.rendering import CertificateRenderer
from tax_reporter.templates import TemplateLibrary

ROOT = Path(__file__).resolve().parents[1]
TODAY = date(2026, 3, 24)


@pytest.fixture(scope="session")
def library() -> TemplateLibrary:
    return TemplateLibrary(ROOT / "templates")


@pytest.fixture(scope="session")
def clinics() -> ClinicRegistry:
    return ClinicRegistry.from_file(ROOT / "templates" / "clinics.json")


@pytest.fixture(scope="session")
def renderer(library: TemplateLibrary) -> CertificateRenderer:
    return CertificateRenderer(library)


@pytest.fixture(scope="session")
def sample_csv() -> Path:
    return ROOT / "samples" / "requests.csv"


@pytest.fixture
def taxpayer() -> Person:
    return Person(
        last_name="Соколова",
        first_name="Анна",
        patronymic="Петровна",
        inn="500111222355",
        birth_date=date(1985, 3, 12),
    )


@pytest.fixture
def child() -> Person:
    return Person(
        last_name="Соколов",
        first_name="Мирон",
        patronymic="Ильич",
        birth_date=date(2014, 11, 18),
        document=IdentityDocument(
            kind=DocumentKind.BIRTH_CERTIFICATE,
            series_number="II-МЮ 123456",
            issued_at=date(2014, 11, 26),
        ),
    )


@pytest.fixture
def certificate(clinics: ClinicRegistry, taxpayer: Person) -> Certificate:
    return Certificate(
        number="1",
        tax_year=2025,
        issued_at=TODAY,
        clinic=clinics.resolve("Клиника «Первомайская»"),
        taxpayer=taxpayer,
        amount_standard=Decimal("17500.00"),
        signer="Орлова Вера Сергеевна",
    )
