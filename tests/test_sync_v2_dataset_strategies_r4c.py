from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from src.foundation.services.sync_v2.contracts import RunRequest
from src.foundation.services.sync_v2.dataset_strategies.biying_equity_daily import (
    build_biying_equity_daily_units,
)
from src.foundation.services.sync_v2.dataset_strategies.biying_moneyflow import (
    build_biying_moneyflow_units,
)
from src.foundation.services.sync_v2.registry import get_sync_v2_contract
from src.foundation.services.sync_v2.validator import ContractValidator


class _SessionResult:
    def __init__(self, rows) -> None:  # type: ignore[no-untyped-def]
        self._rows = rows

    def all(self):  # type: ignore[no-untyped-def]
        return self._rows


class _SessionStub:
    def __init__(self, rows) -> None:  # type: ignore[no-untyped-def]
        self._rows = rows
        self.statements = []

    def execute(self, stmt):  # type: ignore[no-untyped-def]
        self.statements.append(stmt)
        return _SessionResult(self._rows)


def test_biying_equity_daily_strategy_defaults_to_stock_pool_and_all_adj_types() -> None:
    contract = get_sync_v2_contract("biying_equity_daily")
    request = RunRequest(
        request_id="req-biying-equity-daily-point",
        dataset_key="biying_equity_daily",
        run_profile="point_incremental",
        trigger_source="manual",
        params={"trade_date": "20260417"},
    )
    validated = ContractValidator().validate(request=request, contract=contract, strict=True)
    session = _SessionStub(
        [
            SimpleNamespace(dm="000001", mc="平安银行"),
            SimpleNamespace(dm="000002", mc="万科A"),
        ]
    )

    units = build_biying_equity_daily_units(validated, contract, dao=None, settings=None, session=session)

    assert len(units) == 6
    assert {unit.source_key for unit in units} == {"biying"}
    assert {unit.request_params["adj_type"] for unit in units} == {"n", "f", "b"}
    assert {unit.request_params["st"] for unit in units} == {"20260417"}
    assert {unit.request_params["et"] for unit in units} == {"20260417"}
    assert {unit.request_params["lt"] for unit in units} == {"5000"}
    assert {unit.request_params["dm"] for unit in units} == {"000001", "000002"}


def test_biying_equity_daily_strategy_accepts_explicit_ts_code_and_adj_type() -> None:
    contract = get_sync_v2_contract("biying_equity_daily")
    request = RunRequest(
        request_id="req-biying-equity-daily-explicit",
        dataset_key="biying_equity_daily",
        run_profile="point_incremental",
        trigger_source="manual",
        params={
            "trade_date": "20260417",
            "ts_code": "000001.SZ,000777.SZ",
            "adj_type": "n,b",
        },
    )
    validated = ContractValidator().validate(request=request, contract=contract, strict=True)
    session = _SessionStub([])

    units = build_biying_equity_daily_units(validated, contract, dao=None, settings=None, session=session)

    assert len(units) == 4
    assert {unit.request_params["dm"] for unit in units} == {"000001", "000777"}
    assert {unit.request_params["adj_type"] for unit in units} == {"n", "b"}


def test_biying_moneyflow_strategy_splits_natural_range_by_100_day_windows() -> None:
    contract = get_sync_v2_contract("biying_moneyflow")
    request = RunRequest(
        request_id="req-biying-moneyflow-range",
        dataset_key="biying_moneyflow",
        run_profile="range_rebuild",
        trigger_source="manual",
        params={"start_date": "20260101", "end_date": "20260415"},
    )
    validated = ContractValidator().validate(request=request, contract=contract, strict=True)
    session = _SessionStub([SimpleNamespace(dm="000001", mc="平安银行")])

    units = build_biying_moneyflow_units(validated, contract, dao=None, settings=None, session=session)

    assert len(units) == 2
    assert [unit.request_params["st"] for unit in units] == ["20260101", "20260411"]
    assert [unit.request_params["et"] for unit in units] == ["20260410", "20260415"]
    assert [unit.trade_date for unit in units] == [date(2026, 4, 10), date(2026, 4, 15)]
    assert {unit.request_params["dm"] for unit in units} == {"000001"}
