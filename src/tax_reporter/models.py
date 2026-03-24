"""Доменная модель справки об оплате медицинских услуг (форма по КНД 1151156)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

KOPECKS = Decimal("0.01")


class DocumentKind(StrEnum):
    """Подмножество справочника ФНС «Коды видов документов, удостоверяющих личность»."""

    BIRTH_CERTIFICATE = "03"
    MILITARY_ID = "07"
    FOREIGN_PASSPORT = "10"
    RF_PASSPORT = "21"
    RESIDENCE_PERMIT = "12"


class Base(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class IdentityDocument(Base):
    kind: DocumentKind
    series_number: str = Field(min_length=1, max_length=25)
    issued_at: date


class Person(Base):
    last_name: str = Field(min_length=1, max_length=60)
    first_name: str = Field(min_length=1, max_length=60)
    patronymic: str | None = Field(default=None, max_length=60)
    inn: str | None = None
    birth_date: date | None = None
    document: IdentityDocument | None = None

    @property
    def full_name(self) -> str:
        return " ".join(filter(None, (self.last_name, self.first_name, self.patronymic)))

    def age_at(self, moment: date) -> int | None:
        if self.birth_date is None:
            return None
        years = moment.year - self.birth_date.year
        if (moment.month, moment.day) < (self.birth_date.month, self.birth_date.day):
            years -= 1
        return years


class Clinic(Base):
    name: str = Field(min_length=1, max_length=250)
    inn: str
    kpp: str


class Certificate(Base):
    """Одна справка. Пациент задан только если лечился не сам налогоплательщик."""

    number: str = Field(min_length=1, max_length=20)
    correction: int = Field(default=0, ge=0, le=99)
    tax_year: int = Field(ge=2000, le=2100)
    issued_at: date
    clinic: Clinic
    taxpayer: Person
    patient: Person | None = None
    amount_standard: Decimal = Decimal("0")
    amount_expensive: Decimal = Decimal("0")
    signer: str = Field(min_length=1, max_length=120)

    @field_validator("amount_standard", "amount_expensive")
    @classmethod
    def _round_to_kopecks(cls, value: Decimal) -> Decimal:
        if value < 0:
            raise ValueError("сумма расходов не может быть отрицательной")
        return value.quantize(KOPECKS)

    @property
    def patient_is_taxpayer(self) -> bool:
        return self.patient is None

    @property
    def treated(self) -> Person:
        return self.patient or self.taxpayer

    @property
    def total(self) -> Decimal:
        return self.amount_standard + self.amount_expensive

    @property
    def pages(self) -> int:
        """Вторая страница печатается только под данные пациента."""
        return 1 if self.patient_is_taxpayer else 2

    @property
    def key(self) -> tuple[str, int, str, int]:
        """Идентичность справки: одна клиника, год, номер и номер корректировки."""
        return (self.clinic.inn, self.tax_year, self.number, self.correction)

    def filename(self) -> str:
        parts = [
            self.clinic.inn,
            str(self.tax_year),
            self.number,
            self.taxpayer.last_name,
            self.taxpayer.first_name,
        ]
        if self.correction:
            parts.append(f"corr{self.correction}")
        stem = "_".join(p.replace(" ", "-") for p in parts)
        return f"{stem}.pdf"
