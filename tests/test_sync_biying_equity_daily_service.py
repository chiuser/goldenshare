from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from src.foundation.services.sync_v2.contracts import FetchResult, RunRequest
from src.foundation.services.sync_v2.dataset_strategies.biying_equity_daily import build_biying_equity_daily_units
from src.foundation.services.sync_v2.errors import SyncV2ValidationError
from src.foundation.services.sync_v2.normalizer import SyncV2Normalizer
from src.foundation.services.sync_v2.registry import get_sync_v2_contract
from src.foundation.services.sync_v2.validator import ContractValidator


def _fake_session(stocks: list[tuple[str, str]]) -> SimpleNamespace:
    rows = [SimpleNamespace(dm=dm, mc=mc) for dm, mc in stocks]
    return SimpleNamespace(execute=lambda stmt: SimpleNamespace(all=lambda: rows))


def test_biying_equity_daily_point_incremental_requires_trade_date() -> None:
    contract = get_sync_v2_contract("biying_equity_daily")
    request = RunRequest(
        request_id="req-biying-equity-daily-missing-trade-date",
        dataset_key="biying_equity_daily",
        run_profile="point_incremental",
        trigger_source="test",
        params={},
    )

    with pytest.raises(SyncV2ValidationError) as exc_info:
        ContractValidator().validate(request, contract)
    assert exc_info.value.structured_error.error_code == "missing_anchor_fields"


def test_biying_equity_daily_range_rebuild_builds_units_for_all_adj_types() -> None:
    contract = get_sync_v2_contract("biying_equity_daily")
    request = RunRequest(
        request_id="req-biying-equity-daily-range",
        dataset_key="biying_equity_daily",
        run_profile="range_rebuild",
        trigger_source="test",
        start_date=date(2026, 4, 3),
        end_date=date(2026, 4, 10),
        params={"ts_code": "600602.SH"},
    )
    validated = ContractValidator().validate(request, contract)
    units = build_biying_equity_daily_units(
        validated,
        contract,
        dao=None,
        settings=None,
        session=_fake_session([("600602", "云赛智联")]),
    )

    assert len(units) == 3
    adj_types = {unit.request_params["adj_type"] for unit in units}
    assert adj_types == {"n", "f", "b"}
    assert all(unit.request_params["dm"] == "600602" for unit in units)
    assert all(unit.request_params["st"] == "20260403" for unit in units)
    assert all(unit.request_params["et"] == "20260410" for unit in units)


def test_biying_equity_daily_normalizer_maps_quote_fields() -> None:
    contract = get_sync_v2_contract("biying_equity_daily")
    batch = SyncV2Normalizer().normalize(
        contract=contract,
        fetch_result=FetchResult(
            unit_id="u-biying-equity-daily",
            request_count=1,
            retry_count=0,
            latency_ms=1,
            rows_raw=[
                {
                    "dm": "600602.SH",
                    "mc": "云赛智联",
                    "adj_type": "f",
                    "t": "2026-04-09 00:00:00",
                    "o": "24.33",
                    "h": "24.93",
                    "l": "24.18",
                    "c": "24.38",
                    "v": "943525",
                    "a": "2307474664",
                    "pc": "25.05",
                    "sf": 0,
                }
            ],
        ),
    )
    row = batch.rows_normalized[0]
    assert row["dm"] == "600602.SH"
    assert row["trade_date"] == date(2026, 4, 9)
    assert row["adj_type"] == "f"
    assert row["open"] == Decimal("24.33")
    assert row["suspend_flag"] == 0
