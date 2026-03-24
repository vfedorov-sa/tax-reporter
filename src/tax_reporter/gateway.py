"""Передача готового пакета в приёмный шлюз."""

from __future__ import annotations

import json
import time
import zipfile
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Any, Protocol

import httpx

MANIFEST_NAME = "manifest.json"


@dataclass(frozen=True, slots=True)
class Document:
    filename: str
    content: bytes


@dataclass(frozen=True, slots=True)
class Receipt:
    accepted: bool
    reference: str
    detail: str = ""


@dataclass(slots=True)
class Package:
    batch_id: str
    tax_year: int
    documents: list[Document] = field(default_factory=list)

    @property
    def manifest(self) -> dict[str, Any]:
        return {
            "batch_id": self.batch_id,
            "tax_year": self.tax_year,
            "count": len(self.documents),
            "documents": [d.filename for d in self.documents],
        }

    def to_zip(self) -> bytes:
        buffer = BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(
                MANIFEST_NAME,
                json.dumps(self.manifest, ensure_ascii=False, indent=2),
            )
            for document in self.documents:
                archive.writestr(document.filename, document.content)
        return buffer.getvalue()


class Gateway(Protocol):
    def submit(self, package: Package) -> Receipt: ...


class LocalGateway:
    """Складывает пакет на диск. Используется на дев-стенде и в прогоне вхолостую."""

    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory)

    def submit(self, package: Package) -> Receipt:
        self.directory.mkdir(parents=True, exist_ok=True)
        target = self.directory / f"{package.batch_id}.zip"
        target.write_bytes(package.to_zip())
        return Receipt(accepted=True, reference=str(target), detail="сохранено локально")


class HttpGateway:
    """Приёмный узел: один POST с архивом, идемпотентность по номеру пакета."""

    def __init__(
        self,
        url: str,
        token: str = "",
        *,
        timeout: float = 30.0,
        max_attempts: int = 3,
        client: httpx.Client | None = None,
    ) -> None:
        self.url = url
        self.token = token
        self.timeout = timeout
        self.max_attempts = max_attempts
        self._client = client

    def _headers(self, package: Package) -> dict[str, str]:
        headers = {"Idempotency-Key": package.batch_id}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def submit(self, package: Package) -> Receipt:
        client = self._client or httpx.Client(timeout=self.timeout)
        payload = package.to_zip()
        last_error = ""

        try:
            for attempt in range(1, self.max_attempts + 1):
                try:
                    response = client.post(
                        self.url,
                        headers=self._headers(package),
                        files={"package": (f"{package.batch_id}.zip", payload, "application/zip")},
                    )
                except httpx.HTTPError as exc:
                    last_error = f"сеть: {exc}"
                else:
                    if response.status_code < 400:
                        body = _safe_json(response)
                        return Receipt(
                            accepted=True,
                            reference=str(body.get("reference", package.batch_id)),
                            detail=str(body.get("detail", "")),
                        )
                    # 4xx означает, что пакет неверен: повтор ничего не изменит.
                    if response.status_code < 500:
                        return Receipt(
                            accepted=False,
                            reference=package.batch_id,
                            detail=f"шлюз ответил {response.status_code}: {response.text[:300]}",
                        )
                    last_error = f"шлюз ответил {response.status_code}"

                if attempt < self.max_attempts:
                    time.sleep(2 ** (attempt - 1))
        finally:
            if self._client is None:
                client.close()

        return Receipt(accepted=False, reference=package.batch_id, detail=last_error)


def _safe_json(response: httpx.Response) -> dict[str, Any]:
    try:
        body = response.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


def build_gateway(settings: Any) -> Gateway:
    if settings.gateway == "http":
        if not settings.gateway_url:
            raise ValueError("для gateway=http нужен TAX_REPORTER_GATEWAY_URL")
        return HttpGateway(
            settings.gateway_url,
            settings.gateway_token,
            timeout=settings.request_timeout,
            max_attempts=settings.max_attempts,
        )
    return LocalGateway(settings.output_dir / "packages")
