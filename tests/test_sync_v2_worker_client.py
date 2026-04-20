from __future__ import annotations

from dataclasses import replace

import pytest
import requests

from src.foundation.services.sync_v2.adapters.base import SourceRequest
from src.foundation.services.sync_v2.contracts import PaginationSpec, PlanUnit, RateLimitSpec
from src.foundation.services.sync_v2.errors import SyncV2SourceError
from src.foundation.services.sync_v2.registry import get_sync_v2_contract
from src.foundation.services.sync_v2.worker_client import SyncV2WorkerClient


class _PaginationAdapter:
    def __init__(self) -> None:
        self.offsets: list[int] = []

    def build_request(self, *, contract, unit, offset=None, page_limit=None):  # type: ignore[no-untyped-def]
        params = dict(unit.request_params)
        if offset is not None:
            params["offset"] = offset
        if page_limit is not None:
            params["limit"] = page_limit
        return SourceRequest(source_key="tushare", api_name=contract.source_spec.api_name, params=params, fields=contract.source_spec.fields)

    def execute(self, request: SourceRequest) -> list[dict]:
        offset = int(request.params.get("offset") or 0)
        self.offsets.append(offset)
        if offset == 0:
            return [{"trade_date": "2026-04-01"}, {"trade_date": "2026-04-02"}]
        return [{"trade_date": "2026-04-03"}]


class _RetryAdapter:
    def __init__(self) -> None:
        self.calls = 0

    def build_request(self, *, contract, unit, offset=None, page_limit=None):  # type: ignore[no-untyped-def]
        return SourceRequest(source_key="tushare", api_name=contract.source_spec.api_name, params=dict(unit.request_params), fields=contract.source_spec.fields)

    def execute(self, request: SourceRequest) -> list[dict]:
        self.calls += 1
        if self.calls == 1:
            raise requests.Timeout("timeout")
        return [{"trade_date": "2026-04-01"}]


class _InvalidPayloadAdapter:
    def build_request(self, *, contract, unit, offset=None, page_limit=None):  # type: ignore[no-untyped-def]
        return SourceRequest(source_key="tushare", api_name=contract.source_spec.api_name, params=dict(unit.request_params), fields=contract.source_spec.fields)

    def execute(self, request: SourceRequest) -> list[dict]:
        raise ValueError("payload invalid")


def test_worker_client_fetch_handles_offset_limit_pagination(mocker) -> None:
    adapter = _PaginationAdapter()
    mocker.patch("src.foundation.services.sync_v2.worker_client.get_source_adapter", return_value=adapter)

    contract = get_sync_v2_contract("stk_limit")
    contract = replace(
        contract,
        pagination_spec=PaginationSpec(page_limit=2),
    )
    unit = PlanUnit(
        unit_id="u1",
        dataset_key="stk_limit",
        source_key="tushare",
        trade_date=None,
        request_params={"trade_date": "20260401"},
    )

    result = SyncV2WorkerClient().fetch(contract=contract, unit=unit)

    assert result.request_count == 2
    assert result.retry_count == 0
    assert len(result.rows_raw) == 3
    assert adapter.offsets == [0, 2]


def test_worker_client_retries_timeout_then_succeeds(mocker) -> None:
    adapter = _RetryAdapter()
    mocker.patch("src.foundation.services.sync_v2.worker_client.get_source_adapter", return_value=adapter)
    mocker.patch("src.foundation.services.sync_v2.worker_client.time.sleep", return_value=None)

    contract = get_sync_v2_contract("trade_cal")
    contract = replace(contract, rate_limit_spec=RateLimitSpec(max_retries=2, retry_backoff_seconds=0.01))
    unit = PlanUnit(
        unit_id="u2",
        dataset_key="trade_cal",
        source_key="tushare",
        trade_date=None,
        request_params={"exchange": "SSE"},
    )

    result = SyncV2WorkerClient().fetch(contract=contract, unit=unit)

    assert result.request_count == 1
    assert result.retry_count == 1
    assert len(result.rows_raw) == 1
    assert adapter.calls == 2


def test_worker_client_raises_source_error_for_non_retryable_exception(mocker) -> None:
    adapter = _InvalidPayloadAdapter()
    mocker.patch("src.foundation.services.sync_v2.worker_client.get_source_adapter", return_value=adapter)

    contract = get_sync_v2_contract("trade_cal")
    unit = PlanUnit(
        unit_id="u3",
        dataset_key="trade_cal",
        source_key="tushare",
        trade_date=None,
        request_params={"exchange": "SSE"},
    )

    with pytest.raises(SyncV2SourceError) as exc_info:
        SyncV2WorkerClient().fetch(contract=contract, unit=unit)

    assert exc_info.value.structured_error.error_code == "payload_invalid"
