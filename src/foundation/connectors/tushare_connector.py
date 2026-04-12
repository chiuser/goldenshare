from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from src.foundation.clients.tushare_client import TushareHttpClient
from src.foundation.connectors.base import SourceConnector


class TushareSourceConnector(SourceConnector):
    source_key = "tushare"

    def __init__(self, client: TushareHttpClient | None = None) -> None:
        self.client = client or TushareHttpClient()

    def call(
        self,
        api_name: str,
        params: dict[str, Any] | None = None,
        fields: Iterable[str] | None = None,
    ) -> list[dict[str, Any]]:
        return self.client.call(api_name=api_name, params=params, fields=fields)
