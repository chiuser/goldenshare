from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from src.foundation.services.sync_v2.contracts import FetchResult, RunRequest
from src.foundation.services.sync_v2.dataset_strategies.margin import build_margin_units
from src.foundation.services.sync_v2.errors import SyncV2ValidationError
from src.foundation.services.sync_v2.normalizer import SyncV2Normalizer
from src.foundation.services.sync_v2.registry import get_sync_v2_contract
from src.foundation.services.sync_v2.validator import ContractValidator


def _fake_dao(open_dates: list[date]) -> SimpleNamespace:
    return SimpleNamespace(
        trade_calendar=SimpleNamespace(get_open_dates=lambda exchange, start, end: open_dates)
    )


def test_margin_point_incremental_requires_trade_date() -> None:
    contract = get_sync_v2_contract("margin")
    request = RunRequest(
        request_id="req-margin-missing-trade-date",
        dataset_key="margin",
        run_profile="point_incremental",
        trigger_source="test",
        params={},
    )
    with pytest.raises(SyncV2ValidationError) as exc_info:
        ContractValidator().validate(request, contract)
    assert exc_info.value.structured_error.error_code == "missing_anchor_fields"


def test_margin_point_incremental_default_request_builds_single_unit() -> None:
    contract = get_sync_v2_contract("margin")
    request = RunRequest(
        request_id="req-margin-point-default",
        dataset_key="margin",
        run_profile="point_incremental",
        trigger_source="test",
        trade_date=date(2026, 4, 16),
        params={},
    )
    validated = ContractValidator().validate(request, contract)
    units = build_margin_units(validated, contract, dao=_fake_dao([]), settings=SimpleNamespace(default_exchange="SSE"), session=None)

    assert len(units) == 1
    assert units[0].request_params == {"trade_date": "20260416"}


def test_margin_point_incremental_with_selected_exchanges() -> None:
    contract = get_sync_v2_contract("margin")
    request = RunRequest(
        request_id="req-margin-point-selected",
        dataset_key="margin",
        run_profile="point_incremental",
        trigger_source="test",
        trade_date=date(2026, 4, 16),
        params={"exchange_id": ["SSE", "BSE"]},
    )
    validated = ContractValidator().validate(request, contract)
    units = build_margin_units(validated, contract, dao=_fake_dao([]), settings=SimpleNamespace(default_exchange="SSE"), session=None)

    assert len(units) == 2
    exchanges = {unit.request_params["exchange_id"] for unit in units}
    assert exchanges == {"SSE", "BSE"}


def test_margin_range_rebuild_fans_out_trade_dates_and_exchanges() -> None:
    contract = get_sync_v2_contract("margin")
    request = RunRequest(
        request_id="req-margin-range",
        dataset_key="margin",
        run_profile="range_rebuild",
        trigger_source="test",
        start_date=date(2026, 4, 14),
        end_date=date(2026, 4, 15),
        params={"exchange_id": "SSE,SZSE"},
    )
    validated = ContractValidator().validate(request, contract)
    units = build_margin_units(
        validated,
        contract,
        dao=_fake_dao([date(2026, 4, 14), date(2026, 4, 15)]),
        settings=SimpleNamespace(default_exchange="SSE"),
        session=None,
    )

    assert len(units) == 4
    pairs = {(u.request_params["trade_date"], u.request_params["exchange_id"]) for u in units}
    assert pairs == {
        ("20260414", "SSE"),
        ("20260414", "SZSE"),
        ("20260415", "SSE"),
        ("20260415", "SZSE"),
    }


def test_margin_normalizer_coerces_numeric_fields() -> None:
    contract = get_sync_v2_contract("margin")
    batch = SyncV2Normalizer().normalize(
        contract=contract,
        fetch_result=FetchResult(
            unit_id="u-margin",
            request_count=1,
            retry_count=0,
            latency_ms=1,
            rows_raw=[
                {
                    "trade_date": "20260416",
                    "exchange_id": "SSE",
                    "rzye": "1.2",
                    "rzmre": "2.3",
                    "rzche": "3.4",
                    "rqye": "4.5",
                    "rqmcl": "5.6",
                    "rzrqye": "6.7",
                    "rqyl": "7.8",
                }
            ],
        ),
    )
    row = batch.rows_normalized[0]
    assert row["trade_date"] == date(2026, 4, 16)
    assert row["rzye"] == Decimal("1.2")
