"""Оркестрация: выгрузка → нормализация → проверки → PDF → пакет → шлюз."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import pandas as pd

from .gateway import Document, Gateway, Package, Receipt
from .intake import ClinicRegistry, Rejection, normalize, to_certificates
from .models import Certificate
from .rendering import CertificateRenderer, RenderError
from .templates import TemplateLibrary
from .validation import Issue, Severity, find_duplicates, has_errors, validate


@dataclass(frozen=True, slots=True)
class Outcome:
    number: str
    tax_year: int
    taxpayer: str
    accepted: bool
    filename: str | None
    issues: list[Issue]


@dataclass(slots=True)
class BatchReport:
    batch_id: str
    received: int = 0
    accepted: int = 0
    rejected: int = 0
    outcomes: list[Outcome] = field(default_factory=list)
    rejections: list[Rejection] = field(default_factory=list)
    receipts: list[Receipt] = field(default_factory=list)

    @property
    def submitted(self) -> bool:
        return bool(self.receipts) and all(r.accepted for r in self.receipts)


class Pipeline:
    def __init__(
        self,
        *,
        library: TemplateLibrary,
        renderer: CertificateRenderer,
        clinics: ClinicRegistry,
        gateway: Gateway,
        output_dir: str | Path,
        today: date | None = None,
    ) -> None:
        self.library = library
        self.renderer = renderer
        self.clinics = clinics
        self.gateway = gateway
        self.output_dir = Path(output_dir)
        self.today = today

    def run(
        self, frame: pd.DataFrame, *, batch_id: str | None = None, submit: bool = True
    ) -> BatchReport:
        batch_id = batch_id or uuid.uuid4().hex[:12]
        report = BatchReport(batch_id=batch_id)

        certificates, rejections = to_certificates(normalize(frame), self.clinics)
        report.received = len(certificates) + len(rejections)
        report.rejections = rejections
        report.rejected = len(rejections)

        stale = _superseded_rows(certificates)
        packages: dict[int, Package] = {}
        destination = self.output_dir / batch_id

        for index, cert in enumerate(certificates):
            issues = validate(cert, today=self.today)
            if index in stale:
                issues.append(
                    Issue(
                        "DUPLICATE_NUMBER",
                        "number",
                        f"справка №{cert.number} за {cert.tax_year} год встречается в выгрузке "
                        "несколько раз, в пакет уходит последняя версия",
                    )
                )

            if has_errors(issues):
                report.rejected += 1
                report.outcomes.append(_outcome(cert, False, None, issues))
                continue

            try:
                content = self.renderer.render(cert)
            except (RenderError, KeyError) as exc:
                issues.append(Issue("RENDER_FAILED", "template", str(exc), Severity.ERROR))
                report.rejected += 1
                report.outcomes.append(_outcome(cert, False, None, issues))
                continue

            filename = cert.filename()
            destination.mkdir(parents=True, exist_ok=True)
            (destination / filename).write_bytes(content)

            package = packages.setdefault(
                cert.tax_year,
                Package(batch_id=f"{batch_id}-{cert.tax_year}", tax_year=cert.tax_year),
            )
            package.documents.append(Document(filename=filename, content=content))

            report.accepted += 1
            report.outcomes.append(_outcome(cert, True, filename, issues))

        if submit:
            # Приёмный узел ждёт по пакету на отчётный год, смешивать периоды нельзя.
            report.receipts = [self.gateway.submit(packages[year]) for year in sorted(packages)]

        return report


def _outcome(
    cert: Certificate, accepted: bool, filename: str | None, issues: list[Issue]
) -> Outcome:
    return Outcome(
        number=cert.number,
        tax_year=cert.tax_year,
        taxpayer=cert.taxpayer.full_name,
        accepted=accepted,
        filename=filename,
        issues=issues,
    )


def _superseded_rows(certificates: list[Certificate]) -> set[int]:
    """Из каждой группы одинаковых справок в пакет идёт только последняя."""
    superseded: set[int] = set()
    for rows in find_duplicates(certificates).values():
        superseded.update(rows[:-1])
    return superseded
