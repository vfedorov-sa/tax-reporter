"""HTTP-интерфейс сервиса."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass
from io import BytesIO

import pandas as pd
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from .config import Settings, load_settings
from .gateway import build_gateway
from .intake import ClinicRegistry
from .models import Certificate
from .pipeline import BatchReport, Pipeline
from .rendering import CertificateRenderer
from .sources import IntakeClient
from .templates import TemplateLibrary
from .validation import Issue, validate

logger = logging.getLogger("tax_reporter")


class IssueOut(BaseModel):
    code: str
    field: str
    message: str
    severity: str

    @classmethod
    def of(cls, issue: Issue) -> IssueOut:
        return cls(
            code=issue.code,
            field=issue.field,
            message=issue.message,
            severity=issue.severity.value,
        )


class OutcomeOut(BaseModel):
    number: str
    tax_year: int
    taxpayer: str
    accepted: bool
    filename: str | None
    issues: list[IssueOut]


class RejectionOut(BaseModel):
    row: int
    reason: str


class ReceiptOut(BaseModel):
    accepted: bool
    reference: str
    detail: str


class ReportOut(BaseModel):
    batch_id: str
    received: int
    accepted: int
    rejected: int
    submitted: bool
    outcomes: list[OutcomeOut]
    rejections: list[RejectionOut]
    receipts: list[ReceiptOut]

    @classmethod
    def of(cls, report: BatchReport) -> ReportOut:
        return cls(
            batch_id=report.batch_id,
            received=report.received,
            accepted=report.accepted,
            rejected=report.rejected,
            submitted=report.submitted,
            outcomes=[
                OutcomeOut(
                    number=o.number,
                    tax_year=o.tax_year,
                    taxpayer=o.taxpayer,
                    accepted=o.accepted,
                    filename=o.filename,
                    issues=[IssueOut.of(i) for i in o.issues],
                )
                for o in report.outcomes
            ],
            rejections=[RejectionOut(row=r.row, reason=r.reason) for r in report.rejections],
            receipts=[
                ReceiptOut(accepted=r.accepted, reference=r.reference, detail=r.detail)
                for r in report.receipts
            ],
        )


@dataclass
class Services:
    settings: Settings
    library: TemplateLibrary
    pipeline: Pipeline
    # Отчёты держатся в памяти процесса: в проде за ними стоит таблица в Postgres.
    reports: dict[str, BatchReport]


def build_services(settings: Settings | None = None) -> Services:
    settings = settings or load_settings()
    library = TemplateLibrary(settings.templates_dir)
    if not len(library):
        raise RuntimeError(f"в {settings.templates_dir} не найдено ни одного шаблона")

    pipeline = Pipeline(
        library=library,
        renderer=CertificateRenderer(library, settings.signature_path),
        clinics=ClinicRegistry.from_file(settings.clinics_path),
        gateway=build_gateway(settings),
        output_dir=settings.output_dir,
    )
    return Services(settings=settings, library=library, pipeline=pipeline, reports={})


def services(request: Request) -> Services:
    return request.app.state.services


router = APIRouter()


@router.get("/healthz", tags=["service"])
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz", tags=["service"])
def readyz(svc: Services = Depends(services)) -> dict[str, object]:
    return {
        "status": "ok",
        "templates": svc.library.years,
        "gateway": svc.settings.gateway,
    }


@router.get("/v1/templates", tags=["templates"])
def list_templates(svc: Services = Depends(services)) -> list[dict[str, object]]:
    return [
        {"tax_year": year, "name": svc.library.for_year(year).name} for year in svc.library.years
    ]


@router.post("/v1/certificates/validate", tags=["certificates"])
def validate_certificate(cert: Certificate) -> list[IssueOut]:
    """Прогон проверок без генерации PDF — этим пользуется форма приёма заявок."""
    return [IssueOut.of(issue) for issue in validate(cert)]


@router.post("/v1/batches", response_model=ReportOut, tags=["batches"])
async def create_batch(
    file: UploadFile,
    submit: bool = Query(default=True, description="отправить пакет в шлюз"),
    svc: Services = Depends(services),
) -> ReportOut:
    try:
        frame = pd.read_csv(BytesIO(await file.read()), dtype=str, keep_default_na=False)
    except (ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=400, detail=f"не прочитана выгрузка: {exc}") from exc

    return _run(svc, frame, submit=submit)


@router.post("/v1/batches/from-intake", response_model=ReportOut, tags=["batches"])
def create_batch_from_intake(
    tax_year: int = Query(ge=2000, le=2100),
    submit: bool = Query(default=True),
    svc: Services = Depends(services),
) -> ReportOut:
    if not svc.settings.intake_url:
        raise HTTPException(status_code=503, detail="источник заявок не настроен")

    client = IntakeClient(
        svc.settings.intake_url,
        svc.settings.intake_token,
        timeout=svc.settings.request_timeout,
    )
    return _run(svc, client.fetch(tax_year), submit=submit)


@router.get("/v1/batches/{batch_id}", response_model=ReportOut, tags=["batches"])
def get_batch(batch_id: str, svc: Services = Depends(services)) -> ReportOut:
    report = svc.reports.get(batch_id)
    if report is None:
        raise HTTPException(status_code=404, detail=f"пакет {batch_id} не найден")
    return ReportOut.of(report)


@router.get("/v1/batches/{batch_id}/documents/{filename}", tags=["batches"])
def get_document(batch_id: str, filename: str, svc: Services = Depends(services)) -> Response:
    if svc.reports.get(batch_id) is None:
        raise HTTPException(status_code=404, detail=f"пакет {batch_id} не найден")

    path = (svc.settings.output_dir / batch_id / filename).resolve()
    root = (svc.settings.output_dir / batch_id).resolve()
    if root not in path.parents or not path.is_file():
        raise HTTPException(status_code=404, detail=f"справка {filename} не найдена")

    return Response(content=path.read_bytes(), media_type="application/pdf")


def _run(svc: Services, frame: pd.DataFrame, *, submit: bool) -> ReportOut:
    try:
        report = svc.pipeline.run(frame, submit=submit)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    svc.reports[report.batch_id] = report
    logger.info(
        "пакет %s: принято %s, отклонено %s", report.batch_id, report.accepted, report.rejected
    )
    return ReportOut.of(report)


def create_app(settings: Settings | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application: FastAPI):
        application.state.services = build_services(settings)
        logger.info("шаблоны: %s", application.state.services.library.years)
        yield

    application = FastAPI(
        title="tax-reporter",
        version="1.0.0",
        summary="Подготовка справок об оплате медицинских услуг для налогового органа",
        lifespan=lifespan,
    )
    application.include_router(router)
    return application


app = create_app()
