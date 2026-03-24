from __future__ import annotations

import zipfile
from io import BytesIO
from pathlib import Path

import pytest

from conftest import TODAY
from tax_reporter.gateway import LocalGateway, Package
from tax_reporter.intake import ClinicRegistry, read_export
from tax_reporter.pipeline import Pipeline
from tax_reporter.rendering import CertificateRenderer
from tax_reporter.templates import TemplateLibrary


@pytest.fixture
def pipeline(
    library: TemplateLibrary,
    renderer: CertificateRenderer,
    clinics: ClinicRegistry,
    tmp_path: Path,
) -> Pipeline:
    return Pipeline(
        library=library,
        renderer=renderer,
        clinics=clinics,
        gateway=LocalGateway(tmp_path / "packages"),
        output_dir=tmp_path / "out",
        today=TODAY,
    )


@pytest.fixture
def report(pipeline: Pipeline, sample_csv: Path):
    return pipeline.run(read_export(sample_csv), batch_id="test")


def test_counts_add_up(report) -> None:
    assert report.received == 7
    assert report.accepted == 3
    assert report.rejected == 4
    assert report.accepted + report.rejected == report.received


def test_accepted_numbers(report) -> None:
    accepted = sorted(o.number for o in report.outcomes if o.accepted)
    assert accepted == ["1", "2", "3"]


def test_each_rejection_names_its_reason(report) -> None:
    reasons = {
        o.number: {i.code for i in o.issues} for o in report.outcomes if not o.accepted
    }
    assert "TAXPAYER_INN" in reasons["5"]
    assert "DOCUMENT_KIND_MINOR" in reasons["6"]
    assert "AMOUNT_EMPTY" in reasons["7"]


def test_unknown_clinic_stops_at_intake(report) -> None:
    assert len(report.rejections) == 1
    assert "Незнакомый" in report.rejections[0].reason


def test_documents_are_written(report, tmp_path: Path) -> None:
    written = sorted(p.name for p in (tmp_path / "out" / "test").glob("*.pdf"))
    assert len(written) == 3
    assert all(name.endswith(".pdf") for name in written)
    assert any("Соколова" in name for name in written)


def test_package_reaches_the_gateway(report, tmp_path: Path) -> None:
    assert report.submitted
    assert len(report.receipts) == 1

    archive_path = tmp_path / "packages" / "test-2025.zip"
    assert archive_path.is_file()
    with zipfile.ZipFile(archive_path) as archive:
        names = archive.namelist()
    assert "manifest.json" in names
    assert len(names) == 4


def test_dry_run_keeps_the_package_at_home(pipeline: Pipeline, sample_csv: Path) -> None:
    report = pipeline.run(read_export(sample_csv), batch_id="dry", submit=False)
    assert report.accepted == 3
    assert report.receipts == []
    assert not report.submitted


def test_manifest_lists_every_document() -> None:
    package = Package(batch_id="b1", tax_year=2025)
    assert package.manifest["count"] == 0

    with zipfile.ZipFile(BytesIO(package.to_zip())) as archive:
        assert archive.namelist() == ["manifest.json"]
