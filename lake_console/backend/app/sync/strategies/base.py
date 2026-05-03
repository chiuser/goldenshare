from __future__ import annotations

from datetime import date
from typing import Protocol

from lake_console.backend.app.sync.context import LakeSyncContext
from lake_console.backend.app.sync.results import LakeSyncResult


class LakeDatasetStrategy(Protocol):
    dataset_key: str

    def sync(
        self,
        *,
        context: LakeSyncContext,
        trade_date: date | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        ts_code: str | None = None,
        name: str | None = None,
        markets: list[str] | None = None,
        publisher: str | None = None,
        category: str | None = None,
    ) -> LakeSyncResult:
        ...
