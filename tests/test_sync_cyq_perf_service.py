from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from src.foundation.services.sync_v2.contracts import FetchResult, RunRequest
from src.foundation.services.sync_v2.dataset_strategies.cyq_perf import build_cyq_perf_units
from src.foundation.services.sync_v2.errors import SyncV2ValidationError
from src.foundation.services.sync_v2.normalizer import SyncV2Normalizer
from src.foundation.services.sync_v2.registry import get_sync_v2_contract
from src.foundation.services.sync_v2.validator import ContractValidator


def _fake_dao(open_dates: list[date]) -> SimpleNamespace:
    return SimpleNamespace(
        trade_calendar=SimpleNamespace(get_open_dates=lambda exchange, start, end: open_dates)
    )


def test_cyq_perf_point_incremental_requires_trade_date() -> None:
    contract = get_sync_v2_contract("cyq_perf")
    request = RunRequest(
        request_id="req-cyq-perf-missing-trade-date",
        dataset_key="cyq_perf",
        run_profile="point_incremental",
        trigger_source="test",
        params={},
    )

    with pytest.raises(SyncV2ValidationError) as exc_info:
        ContractValidator().validate(request, contract)
    assert exc_info.value.structured_error.error_code == "missing_anchor_fields"


def test_cyq_perf_point_incremental_builds_single_unit() -> None:
    contract = get_sync_v2_contract("cyq_perf")
    request = RunRequest(
        request_id="req-cyq-perf-point",
        dataset_key="cyq_perf",
        run_profile="point_incremental",
        trigger_source="test",
        trade_date=date(2026, 4, 16),
        params={"ts_code": "000001.sz"},
    )
    validated = ContractValidator().validate(request, contract)
    units = build_cyq_perf_units(validated, contract, dao=_fake_dao([]), settings=SimpleNamespace(default_exchange="SSE"), session=None)

    assert len(units) == 1
    assert units[0].request_params == {"trade_date": "20260416", "ts_code": "000001.SZ"}
    assert units[0].pagination_policy == "offset_limit"
    assert units[0].page_limit == 5000


def test_cyq_perf_range_rebuild_fans_out_by_trade_calendar() -> None:
    contract = get_sync_v2_contract("cyq_perf")
    request = RunRequest(
        request_id="req-cyq-perf-range",
        dataset_key="cyq_perf",
        run_profile="range_rebuild",
        trigger_source="test",
        start_date=date(2026, 4, 1),
        end_date=date(2026, 4, 2),
        params={},
    )
    validated = ContractValidator().validate(request, contract)
    units = build_cyq_perf_units(
        validated,
        contract,
        dao=_fake_dao([date(2026, 4, 1), date(2026, 4, 2)]),
        settings=SimpleNamespace(default_exchange="SSE"),
        session=None,
    )

    assert len(units) == 2
    assert units[0].request_params["trade_date"] == "20260401"
    assert units[1].request_params["trade_date"] == "20260402"


def test_cyq_perf_normalizer_coerces_numeric_fields() -> None:
    contract = get_sync_v2_contract("cyq_perf")
    batch = SyncV2Normalizer().normalize(
        contract=contract,
        fetch_result=FetchResult(
            unit_id="u-cyq-perf",
            request_count=1,
            retry_count=0,
            latency_ms=1,
            rows_raw=[
                {
                    "ts_code": "000001.SZ",
                    "trade_date": "20260416",
                    "his_low": "8.01",
                    "his_high": "22.33",
                    "cost_5pct": "10.11",
                    "cost_15pct": "11.22",
                    "cost_50pct": "12.33",
                    "cost_85pct": "13.44",
                    "cost_95pct": "14.55",
                    "weight_avg": "12.50",
                    "winner_rate": "0.5821",
                }
            ],
        ),
    )
    row = batch.rows_normalized[0]
    assert row["trade_date"] == date(2026, 4, 16)
    assert row["cost_50pct"] == Decimal("12.33")
    assert row["winner_rate"] == Decimal("0.5821")
