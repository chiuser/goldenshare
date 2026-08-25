from __future__ import annotations

import logging
import time
from time import perf_counter

from src.foundation.connectors.factory import create_source_connector
from src.foundation.datasets.models import DatasetDefinition
from src.foundation.ingestion.error_mapper import IngestionErrorMapper
from src.foundation.ingestion.errors import IngestionSourceError, StructuredError
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
        pagination_diagnostics: dict | None = None,
    ) -> None:
        self.unit_id = unit_id
        self.request_count = request_count
        self.retry_count = retry_count
        self.latency_ms = latency_ms
        self.rows_raw = rows_raw
        self.pagination_diagnostics = dict(pagination_diagnostics or {})


class SourcePageResult:
    def __init__(
        self,
        *,
        unit_id: str,
        page_number: int,
        offset: int | None,
        rows_raw: list[dict],
        retry_count: int,
        latency_ms: int,
        is_short_page: bool,
        request_variant: dict | None = None,
    ) -> None:
        self.unit_id = unit_id
        self.page_number = page_number
        self.offset = offset
        self.rows_raw = rows_raw
        self.retry_count = retry_count
        self.latency_ms = latency_ms
        self.is_short_page = is_short_page
        self.request_variant = dict(request_variant or {})


class DatasetSourceClient:
    RATE_LIMIT_RETRY_SLEEP_SECONDS = 65.0

    def __init__(self, error_mapper: IngestionErrorMapper | None = None) -> None:
        self.error_mapper = error_mapper or IngestionErrorMapper()
        self.logger = logging.getLogger(self.__class__.__name__)

    def fetch(self, *, definition: DatasetDefinition, unit: PlanUnitSnapshot) -> SourceFetchResult:
        started_at = perf_counter()
        rows_raw: list[dict] = []
        request_count = 0
        retry_count = 0
        terminal_offset: int | None = None
        terminal_page_rows = 0
        observed_short_page = False
        variant_diagnostics: list[dict] = []
        current_variant: dict | None = None
        current_variant_rows = 0
        current_variant_pages = 0
        current_variant_terminal_offset: int | None = None
        current_variant_terminal_rows = 0
        for page in self.iter_pages(definition=definition, unit=unit):
            projected_row_count = len(rows_raw) + len(page.rows_raw)
            if (
                unit.max_source_rows_per_unit is not None
                and projected_row_count > unit.max_source_rows_per_unit
            ):
                raise IngestionSourceError(
                    StructuredError(
                        error_code="source_rows_exceeded",
                        error_type="source",
                        phase="source_client",
                        message="执行单元源端行数超过声明上限，已停止继续分页",
                        retryable=False,
                        unit_id=unit.unit_id,
                        details={
                            "max_source_rows_per_unit": unit.max_source_rows_per_unit,
                            "rows_before_page": len(rows_raw),
                            "page_rows": len(page.rows_raw),
                            "observed_rows": projected_row_count,
                            "page_number": page.page_number,
                            "offset": page.offset,
                            "request_variant": dict(page.request_variant),
                        },
                    )
                )
            if current_variant != page.request_variant:
                if current_variant is not None:
                    variant_diagnostics.append(
                        self._variant_diagnostics(
                            variant=current_variant,
                            rows=current_variant_rows,
                            pages=current_variant_pages,
                            terminal_offset=current_variant_terminal_offset,
                            terminal_rows=current_variant_terminal_rows,
                        )
                    )
                current_variant = page.request_variant
                current_variant_rows = 0
                current_variant_pages = 0
            request_count += 1
            retry_count += page.retry_count
            rows_raw.extend(page.rows_raw)
            current_variant_rows += len(page.rows_raw)
            current_variant_pages += 1
            current_variant_terminal_offset = page.offset
            current_variant_terminal_rows = len(page.rows_raw)
            terminal_offset = page.offset
            terminal_page_rows = len(page.rows_raw)
            observed_short_page = page.is_short_page
        if current_variant is not None:
            variant_diagnostics.append(
                self._variant_diagnostics(
                    variant=current_variant,
                    rows=current_variant_rows,
                    pages=current_variant_pages,
                    terminal_offset=current_variant_terminal_offset,
                    terminal_rows=current_variant_terminal_rows,
                )
            )
        if definition.quality.empty_result_policy == "fail_unit_per_request_variant":
            empty_variants = [item["variant"] for item in variant_diagnostics if item["total_rows"] == 0]
            if empty_variants:
                raise IngestionSourceError(
                    StructuredError(
                        error_code="source_variant_empty",
                        error_type="source",
                        phase="source_client",
                        message="固定请求变体返回空结果，拒绝发布不完整全集",
                        retryable=False,
                        unit_id=unit.unit_id,
                        details={"empty_variants": empty_variants},
                    )
                )
        pagination_policy = unit.pagination_policy or definition.planning.pagination_policy
        pagination_diagnostics = {}
        if pagination_policy == "offset_limit" and unit.page_limit is not None:
            pagination_diagnostics = {
                "policy": "offset_limit",
                "page_limit": unit.page_limit,
                "page_count": request_count,
                "total_rows_merged": len(rows_raw),
                "terminal_offset": terminal_offset,
                "terminal_page_rows": terminal_page_rows,
                "observed_short_page": observed_short_page,
            }
            if unit.request_variants:
                pagination_diagnostics["request_variants"] = variant_diagnostics
        latency_ms = max(int((perf_counter() - started_at) * 1000), 0)
        return SourceFetchResult(
            unit_id=unit.unit_id,
            request_count=request_count,
            retry_count=retry_count,
            latency_ms=latency_ms,
            rows_raw=rows_raw,
            pagination_diagnostics=pagination_diagnostics,
        )

    def iter_pages(self, *, definition: DatasetDefinition, unit: PlanUnitSnapshot):  # type: ignore[no-untyped-def]
        connector = create_source_connector(str(unit.source_key or definition.source.adapter_key))
        request_variants = unit.request_variants or ({},)
        for request_variant in request_variants:
            request_params = dict(unit.request_params)
            request_params.update(request_variant)
            yield from self._iter_request_pages(
                definition=definition,
                unit=unit,
                connector=connector,
                request_params=request_params,
                request_variant=request_variant,
            )

    def _iter_request_pages(
        self,
        *,
        definition: DatasetDefinition,
        unit: PlanUnitSnapshot,
        connector,
        request_params: dict,
        request_variant: dict,
    ):  # type: ignore[no-untyped-def]
        page_limit = unit.page_limit
        pagination_policy = unit.pagination_policy or definition.planning.pagination_policy
        if pagination_policy != "offset_limit" or page_limit is None:
            started_at = perf_counter()
            rows, retries = self._fetch_page(
                definition=definition,
                unit=unit,
                connector=connector,
                request_params=request_params,
                offset=None,
                page_limit=None,
            )
            yield SourcePageResult(
                unit_id=unit.unit_id,
                page_number=1,
                offset=None,
                rows_raw=rows,
                retry_count=retries,
                latency_ms=max(int((perf_counter() - started_at) * 1000), 0),
                is_short_page=True,
                request_variant=request_variant,
            )
            return

        offset = 0
        page_number = 1
        while True:
            started_at = perf_counter()
            rows, retries = self._fetch_page(
                definition=definition,
                unit=unit,
                connector=connector,
                request_params=request_params,
                offset=offset,
                page_limit=page_limit,
            )
            is_short_page = len(rows) < page_limit
            self.logger.info(
                "dataset_source_page api_name=%s unit_id=%s ann_date=%s period=%s offset=%s limit=%s page_rows=%s is_short_page=%s",
                definition.source.api_name,
                unit.unit_id,
                unit.request_params.get("ann_date"),
                unit.request_params.get("period"),
                offset,
                page_limit,
                len(rows),
                is_short_page,
            )
            yield SourcePageResult(
                unit_id=unit.unit_id,
                page_number=page_number,
                offset=offset,
                rows_raw=rows,
                retry_count=retries,
                latency_ms=max(int((perf_counter() - started_at) * 1000), 0),
                is_short_page=is_short_page,
                request_variant=request_variant,
            )
            if is_short_page:
                return
            offset += page_limit
            page_number += 1

    def _fetch_page(
        self,
        *,
        definition: DatasetDefinition,
        unit: PlanUnitSnapshot,
        connector,
        request_params: dict,
        offset: int | None,
        page_limit: int | None,
    ) -> tuple[list[dict], int]:
        params = dict(definition.source.base_params)
        params.update(request_params)
        if offset is not None:
            params["offset"] = offset
        if page_limit is not None:
            params["limit"] = page_limit
        rows, retries = self._execute_with_retry(
            definition=definition,
            unit=unit,
            connector=connector,
            params=params,
        )
        self._validate_request_variant_rows(
            definition=definition,
            rows=rows,
            request_params=request_params,
            unit_id=unit.unit_id,
        )
        self._validate_etf_mins_freq_rows(
            definition=definition,
            rows=rows,
            request_params=request_params,
            unit_id=unit.unit_id,
        )
        return rows, retries

    @staticmethod
    def _validate_etf_mins_freq_rows(
        *,
        definition: DatasetDefinition,
        rows: list[dict],
        request_params: dict,
        unit_id: str,
    ) -> None:
        if definition.source.api_name != "etf_mins":
            return
        expected = str(request_params.get("freq") or "").strip()
        mismatched = [
            {"row_index": index, "actual": row.get("freq")}
            for index, row in enumerate(rows)
            if str(row.get("freq") or "").strip() != expected
        ]
        if mismatched:
            raise IngestionSourceError(
                StructuredError(
                    error_code="source_variant_mismatch",
                    error_type="source",
                    phase="source_client",
                    message="ETF 历史分钟行情返回频率与请求频率不一致",
                    retryable=False,
                    unit_id=unit_id,
                    details={
                        "field_name": "freq",
                        "expected": expected,
                        "mismatch_count": len(mismatched),
                        "samples": mismatched[:3],
                    },
                )
            )

    @staticmethod
    def _validate_request_variant_rows(
        *,
        definition: DatasetDefinition,
        rows: list[dict],
        request_params: dict,
        unit_id: str,
    ) -> None:
        for field_name in definition.planning.request_variant_fields:
            expected_value = request_params.get(field_name)
            expected = "" if expected_value is None else str(expected_value).strip()
            mismatched = [
                {
                    "row_index": index,
                    "actual": row.get(field_name),
                }
                for index, row in enumerate(rows)
                if (
                    ""
                    if row.get(field_name) is None
                    else str(row.get(field_name)).strip()
                )
                != expected
            ]
            if mismatched:
                raise IngestionSourceError(
                    StructuredError(
                        error_code="source_variant_mismatch",
                        error_type="source",
                        phase="source_client",
                        message="固定请求变体的返回行与请求值不一致",
                        retryable=False,
                        unit_id=unit_id,
                        details={
                            "field_name": field_name,
                            "expected": expected,
                            "mismatch_count": len(mismatched),
                            "samples": mismatched[:3],
                        },
                    )
                )

    @staticmethod
    def _variant_diagnostics(
        *,
        variant: dict,
        rows: int,
        pages: int,
        terminal_offset: int | None,
        terminal_rows: int,
    ) -> dict:
        return {
            "variant": dict(variant),
            "page_count": pages,
            "total_rows": rows,
            "terminal_offset": terminal_offset,
            "terminal_page_rows": terminal_rows,
        }

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
                if structured.error_code == "source_rate_limited":
                    sleep_seconds = self.RATE_LIMIT_RETRY_SLEEP_SECONDS
                else:
                    sleep_seconds = min(max(backoff * (2 ** (retries - 1)), 0.05), 5.0)
                time.sleep(sleep_seconds)

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
        if dataset_key == "index_mins":
            query_freq = str(params.get("freq") or "").strip()
            for row in rows:
                if row.get("freq") in (None, ""):
                    row["freq"] = query_freq
