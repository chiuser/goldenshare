from __future__ import annotations

import time
from time import perf_counter

from src.foundation.connectors.factory import create_source_connector
from src.foundation.datasets.models import DatasetDefinition
from src.foundation.ingestion.error_mapper import IngestionErrorMapper
from src.foundation.ingestion.errors import IngestionSourceError
from src.foundation.ingestion.execution_plan import PlanUnitSnapshot


class SourceFetchResult:
    def __init__(
        self,
        *,
        unit_id: str,
        request_count: int,
        retry_count: int,
        latency_ms: int,
        rows_raw: list[dict],
    ) -> None:
        self.unit_id = unit_id
        self.request_count = request_count
        self.retry_count = retry_count
        self.latency_ms = latency_ms
        self.rows_raw = rows_raw


class DatasetSourceClient:
    def __init__(self, error_mapper: IngestionErrorMapper | None = None) -> None:
        self.error_mapper = error_mapper or IngestionErrorMapper()

    def fetch(self, *, definition: DatasetDefinition, unit: PlanUnitSnapshot) -> SourceFetchResult:
        connector = create_source_connector(str(unit.source_key or definition.source.adapter_key))
        page_limit = unit.page_limit
        pagination_policy = unit.pagination_policy or definition.planning.pagination_policy

        started_at = perf_counter()
        rows_raw, request_count, retry_count = self._fetch_rows_with_pagination(
            definition=definition,
            unit=unit,
            connector=connector,
            pagination_policy=pagination_policy,
            page_limit=page_limit,
        )
        latency_ms = max(int((perf_counter() - started_at) * 1000), 0)
        return SourceFetchResult(
            unit_id=unit.unit_id,
            request_count=request_count,
            retry_count=retry_count,
            latency_ms=latency_ms,
            rows_raw=rows_raw,
        )

    def _fetch_rows_with_pagination(
        self,
        *,
        definition: DatasetDefinition,
        unit: PlanUnitSnapshot,
        connector,
        pagination_policy: str | None,
        page_limit: int | None,
    ) -> tuple[list[dict], int, int]:
        if pagination_policy != "offset_limit" or page_limit is None:
            rows, retries = self._fetch_page(
                definition=definition,
                unit=unit,
                connector=connector,
                offset=None,
                page_limit=None,
            )
            return rows, 1, retries

        rows_raw: list[dict] = []
        request_count = 0
        retry_count = 0
        offset = 0
        while True:
            rows, retries = self._fetch_page(
                definition=definition,
                unit=unit,
                connector=connector,
                offset=offset,
                page_limit=page_limit,
            )
            request_count += 1
            retry_count += retries
            rows_raw.extend(rows)
            if len(rows) < page_limit:
                break
            offset += page_limit
        return rows_raw, request_count, retry_count

    def _fetch_page(
        self,
        *,
        definition: DatasetDefinition,
        unit: PlanUnitSnapshot,
        connector,
        offset: int | None,
        page_limit: int | None,
    ) -> tuple[list[dict], int]:
        params = dict(definition.source.base_params)
        params.update(unit.request_params)
        if offset is not None:
            params["offset"] = offset
        if page_limit is not None:
            params["limit"] = page_limit
        return self._execute_with_retry(
            definition=definition,
            unit=unit,
            connector=connector,
            params=params,
        )

    def _execute_with_retry(self, *, definition: DatasetDefinition, unit: PlanUnitSnapshot, connector, params: dict) -> tuple[list[dict], int]:
        max_retries = 3
        backoff = 0.5
        retries = 0
        while True:
            try:
                rows = connector.call(
                    api_name=definition.source.api_name,
                    params=params,
                    fields=definition.source.source_fields,
                )
                self._annotate_rows(definition=definition, rows=rows, params=params)
                return rows, retries
            except Exception as exc:
                structured = self.error_mapper.map_exception(exc=exc, phase="source_client", unit_id=unit.unit_id)
                if not structured.retryable or retries >= max_retries:
                    raise IngestionSourceError(structured) from exc
                retries += 1
                sleep_seconds = backoff * (2 ** (retries - 1))
                time.sleep(min(max(sleep_seconds, 0.05), 5.0))

    @staticmethod
    def _annotate_rows(*, definition: DatasetDefinition, rows: list[dict], params: dict) -> None:
        required_fields = set(definition.quality.required_fields)
        dataset_key = definition.dataset_key
        if "query_market" in required_fields:
            query_market = str(params.get("market") or "").strip()
            for row in rows:
                if query_market:
                    row["query_market"] = query_market
        if "query_hot_type" in required_fields:
            query_hot_type = str(params.get("hot_type") or "").strip()
            for row in rows:
                if query_hot_type:
                    row["query_hot_type"] = query_hot_type
        if "query_is_new" in required_fields:
            query_is_new = str(params.get("is_new") or "").strip()
            for row in rows:
                if query_is_new:
                    row["query_is_new"] = query_is_new
        if "query_limit_type" in required_fields:
            query_limit_type = str(params.get("limit_type") or "").strip()
            for row in rows:
                if query_limit_type:
                    row["query_limit_type"] = query_limit_type
        if "src" in required_fields and "src" not in definition.source.source_fields:
            query_src = str(params.get("src") or "").strip()
            for row in rows:
                if query_src and row.get("src") in (None, ""):
                    row["src"] = query_src
        if dataset_key == "stk_mins":
            query_freq = str(params.get("freq") or "").strip()
            for row in rows:
                row["freq"] = query_freq
