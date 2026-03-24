from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from conftest import ROOT
from tax_reporter.api import create_app
from tax_reporter.config import Settings


@pytest.fixture
def client(tmp_path: Path):
    settings = Settings(
        templates_dir=ROOT / "templates",
        clinics_path=ROOT / "templates" / "clinics.json",
        output_dir=tmp_path / "out",
        gateway="local",
    )
    with TestClient(create_app(settings)) as test_client:
        yield test_client


def test_healthz(client: TestClient) -> None:
    assert client.get("/healthz").json() == {"status": "ok"}


def test_readyz_reports_loaded_templates(client: TestClient) -> None:
    body = client.get("/readyz").json()
    assert body["status"] == "ok"
    assert 2025 in body["templates"]
    assert body["gateway"] == "local"


def test_templates_are_listed(client: TestClient) -> None:
    assert client.get("/v1/templates").json() == [
        {"tax_year": 2025, "name": "certificate-2025"}
    ]


def test_validate_endpoint_returns_issue_codes(client: TestClient) -> None:
    payload = {
        "number": "1",
        "tax_year": 2025,
        "issued_at": "2026-03-24",
        "clinic": {"name": "Клиника «Первомайская»", "inn": "5001112228", "kpp": "500101001"},
        "taxpayer": {"last_name": "Белов", "first_name": "Артём", "inn": "123456789012"},
        "amount_standard": "8000.00",
        "signer": "Орлова Вера Сергеевна",
    }
    issues = client.post("/v1/certificates/validate", json=payload).json()
    assert {issue["code"] for issue in issues} == {"TAXPAYER_INN"}


def test_validate_endpoint_rejects_unknown_fields(client: TestClient) -> None:
    response = client.post("/v1/certificates/validate", json={"number": "1", "oops": 1})
    assert response.status_code == 422


def test_batch_upload(client: TestClient, sample_csv: Path) -> None:
    with sample_csv.open("rb") as handle:
        response = client.post(
            "/v1/batches",
            files={"file": ("requests.csv", handle, "text/csv")},
            params={"submit": "false"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["received"] == 7
    assert body["accepted"] == 3
    assert body["receipts"] == []

    stored = client.get(f"/v1/batches/{body['batch_id']}")
    assert stored.json()["batch_id"] == body["batch_id"]


def test_batch_documents_are_downloadable(client: TestClient, sample_csv: Path) -> None:
    with sample_csv.open("rb") as handle:
        body = client.post(
            "/v1/batches",
            files={"file": ("requests.csv", handle, "text/csv")},
            params={"submit": "false"},
        ).json()

    filename = next(o["filename"] for o in body["outcomes"] if o["accepted"])
    response = client.get(f"/v1/batches/{body['batch_id']}/documents/{filename}")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")


def test_unknown_batch_is_404(client: TestClient) -> None:
    assert client.get("/v1/batches/nope").status_code == 404


def test_broken_upload_is_reported(client: TestClient) -> None:
    response = client.post(
        "/v1/batches",
        files={"file": ("requests.csv", b"a,b\n1", "text/csv")},
        params={"submit": "false"},
    )
    assert response.status_code == 422
    assert "нет колонок" in response.json()["detail"]


def test_intake_source_must_be_configured(client: TestClient) -> None:
    assert client.post("/v1/batches/from-intake", params={"tax_year": 2025}).status_code == 503
