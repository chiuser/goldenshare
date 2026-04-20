from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from src.foundation.services.sync_v2.contracts import DatasetSyncContract, PlanUnit


@dataclass(slots=True, frozen=True)
class SourceRequest:
    source_key: str
    api_name: str
    params: dict[str, Any] = field(default_factory=dict)
    fields: tuple[str, ...] = ()


class SourceAdapter(Protocol):
    source_key: str

    def build_request(
        self,
        *,
        contract: DatasetSyncContract,
        unit: PlanUnit,
        offset: int | None = None,
        page_limit: int | None = None,
    ) -> SourceRequest:
        ...

    def execute(self, request: SourceRequest) -> list[dict[str, Any]]:
        ...
