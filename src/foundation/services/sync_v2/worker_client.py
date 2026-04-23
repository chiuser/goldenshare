from __future__ import annotations

import time
from time import perf_counter

from src.foundation.services.sync_v2.adapters.registry import get_source_adapter
from src.foundation.services.sync_v2.contracts import DatasetSyncContract, FetchResult, PlanUnit
from src.foundation.services.sync_v2.error_mapper import SyncV2ErrorMapper
from src.foundation.services.sync_v2.errors import SyncV2SourceError
from src.foundation.services.sync_v2.strategy_helpers.pagination_loop import fetch_rows_with_pagination


class SyncV2WorkerClient:
    def __init__(self, error_mapper: SyncV2ErrorMapper | None = None) -> None:
        self.error_mapper = error_mapper or SyncV2ErrorMapper()

    def fetch(self, *, contract: DatasetSyncContract, unit: PlanUnit) -> FetchResult:
        adapter = self._resolve_adapter(contract=contract, unit=unit)
        page_limit = (
            unit.page_limit
            if unit.page_limit is not None
            else contract.pagination_spec.page_limit
        )
        pagination_policy = unit.pagination_policy or contract.planning_spec.pagination_policy

        started_at = perf_counter()
        rows_raw, request_count, retry_count = fetch_rows_with_pagination(
            pagination_policy=pagination_policy,
            page_limit=page_limit,
            fetch_page=lambda offset, limit: self._fetch_page(
                contract=contract,
                adapter=adapter,
                unit=unit,
                offset=offset,
                page_limit=limit,
            ),
        )

        latency_ms = max(int((perf_counter() - started_at) * 1000), 0)
        return FetchResult(
            unit_id=unit.unit_id,
            request_count=request_count,
            retry_count=retry_count,
            latency_ms=latency_ms,
            rows_raw=rows_raw,
            source_http_status=None,
        )

    @staticmethod
    def _resolve_adapter(*, contract: DatasetSyncContract, unit: PlanUnit):  # type: ignore[no-untyped-def]
        unit_source_key = str(unit.source_key or "").strip()
        if unit_source_key:
            try:
                return get_source_adapter(unit_source_key)
            except SyncV2SourceError:
                pass
        return get_source_adapter(contract.source_adapter_key)

    def _fetch_page(
        self,
        *,
        contract: DatasetSyncContract,
        adapter,
        unit: PlanUnit,
        offset: int | None,
        page_limit: int | None,
    ) -> tuple[list[dict], int]:
        request = adapter.build_request(
            contract=contract,
            unit=unit,
            offset=offset,
            page_limit=page_limit,
        )
        return self._execute_with_retry(
            contract=contract,
            adapter=adapter,
            request=request,
            unit_id=unit.unit_id,
        )

    def _execute_with_retry(self, *, contract: DatasetSyncContract, adapter, request, unit_id: str) -> tuple[list[dict], int]:  # type: ignore[no-untyped-def]
        max_retries = max(int(contract.rate_limit_spec.max_retries), 0)
        backoff = max(float(contract.rate_limit_spec.retry_backoff_seconds), 0.0)
        retries = 0
        while True:
            try:
                return adapter.execute(request), retries
            except Exception as exc:
                structured = self.error_mapper.map_exception(exc=exc, phase="worker_client", unit_id=unit_id)
                if not structured.retryable or retries >= max_retries:
                    raise SyncV2SourceError(structured) from exc
                retries += 1
                sleep_seconds = backoff * (2 ** (retries - 1))
                time.sleep(min(max(sleep_seconds, 0.05), 5.0))
