from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from src.foundation.connectors.base import SourceConnector


class BiyingSourceConnector(SourceConnector):
    source_key = "biying"

    def call(
        self,
        api_name: str,
        params: dict[str, Any] | None = None,
        fields: Iterable[str] | None = None,
    ) -> list[dict[str, Any]]:
        raise NotImplementedError("Biying connector is not implemented yet.")
