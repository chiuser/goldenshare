from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable
from typing import Any


class SourceConnector(ABC):
    source_key: str

    @abstractmethod
    def call(
        self,
        api_name: str,
        params: dict[str, Any] | None = None,
        fields: Iterable[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Call one source API and return row dicts."""

    def supports_api(self, api_name: str) -> bool:
        return True
