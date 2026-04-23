from __future__ import annotations

from src.foundation.services.sync_v2.contracts import RunRequest
from src.foundation.services.sync_v2.dataset_strategies.stock_basic import build_stock_basic_units
from src.foundation.services.sync_v2.registry import get_sync_v2_contract
from src.foundation.services.sync_v2.validator import ContractValidator


def test_stock_basic_strategy_defaults_to_tushare_snapshot_unit() -> None:
    contract = get_sync_v2_contract("stock_basic")
    request = RunRequest(
        request_id="req-stock-basic-default",
        dataset_key="stock_basic",
        run_profile="snapshot_refresh",
        trigger_source="manual",
        params={},
    )
    validated = ContractValidator().validate(request=request, contract=contract, strict=True)

    units = build_stock_basic_units(validated, contract, dao=None, settings=None, session=None)

    assert len(units) == 1
    assert units[0].source_key == "tushare"
    assert units[0].requested_source_key == "tushare"
    assert units[0].request_params["list_status"] == "L,D,P,G"
    assert units[0].page_limit == 6000


def test_stock_basic_strategy_supports_all_source_mode() -> None:
    contract = get_sync_v2_contract("stock_basic")
    request = RunRequest(
        request_id="req-stock-basic-all",
        dataset_key="stock_basic",
        run_profile="snapshot_refresh",
        trigger_source="manual",
        params={"source_key": "all"},
        source_key="all",
    )
    validated = ContractValidator().validate(request=request, contract=contract, strict=True)

    units = build_stock_basic_units(validated, contract, dao=None, settings=None, session=None)

    assert [unit.source_key for unit in units] == ["tushare", "biying"]
    assert {unit.requested_source_key for unit in units} == {"all"}
    assert units[0].request_params["list_status"] == "L,D,P,G"
    assert units[1].request_params == {}


def test_stock_basic_strategy_fanouts_market_and_exchange_combinations() -> None:
    contract = get_sync_v2_contract("stock_basic")
    request = RunRequest(
        request_id="req-stock-basic-fanout",
        dataset_key="stock_basic",
        run_profile="snapshot_refresh",
        trigger_source="manual",
        params={
            "market": "主板,创业板",
            "exchange": "SSE,SZSE",
            "list_status": "L",
        },
    )
    validated = ContractValidator().validate(request=request, contract=contract, strict=True)

    units = build_stock_basic_units(validated, contract, dao=None, settings=None, session=None)

    assert len(units) == 4
    combos = {(unit.request_params["market"], unit.request_params["exchange"]) for unit in units}
    assert combos == {("主板", "SSE"), ("主板", "SZSE"), ("创业板", "SSE"), ("创业板", "SZSE")}
    assert {unit.request_params["list_status"] for unit in units} == {"L"}
