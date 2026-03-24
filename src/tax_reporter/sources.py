"""Клиент источника заявок."""

from __future__ import annotations

import httpx
import pandas as pd


class IntakeClient:
    """Забирает заявки постранично: за сезон их несколько тысяч, разом отдавать нечего."""

    def __init__(
        self,
        url: str,
        token: str = "",
        *,
        timeout: float = 30.0,
        page_size: int = 500,
        client: httpx.Client | None = None,
    ) -> None:
        self.url = url
        self.token = token
        self.timeout = timeout
        self.page_size = page_size
        self._client = client

    def fetch(self, tax_year: int) -> pd.DataFrame:
        client = self._client or httpx.Client(timeout=self.timeout)
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        rows: list[dict] = []
        offset = 0

        try:
            while True:
                response = client.get(
                    self.url,
                    headers=headers,
                    params={"tax_year": tax_year, "limit": self.page_size, "offset": offset},
                )
                response.raise_for_status()
                page = response.json()
                items = page["items"] if isinstance(page, dict) else page
                rows.extend(items)
                if len(items) < self.page_size:
                    break
                offset += self.page_size
        finally:
            if self._client is None:
                client.close()

        return pd.DataFrame(rows, dtype=str).fillna("")
