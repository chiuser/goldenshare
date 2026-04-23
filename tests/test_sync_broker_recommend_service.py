from __future__ import annotations

from datetime import date

from src.foundation.services.sync_v2.contracts import RunRequest
from src.foundation.services.sync_v2.dataset_strategies.broker_recommend import build_broker_recommend_units
from src.foundation.services.sync_v2.registry import get_sync_v2_contract
from src.foundation.services.sync_v2.validator import ContractValidator


def test_build_broker_recommend_units_supports_month_formats() -> None:
    contract = get_sync_v2_contract("broker_recommend")
    validator = ContractValidator()

    req_month_dash = RunRequest(
        request_id="req-br-month-dash",
        dataset_key="broker_recommend",
        run_profile="point_incremental",
        trigger_source="test",
        params={"month": "2026-03"},
    )
    validated_month_dash = validator.validate(req_month_dash, contract)
    units_month_dash = build_broker_recommend_units(validated_month_dash, contract, dao=None, settings=None, session=None)
    assert units_month_dash[0].request_params == {"month": "202603"}

    req_month_plain = RunRequest(
        request_id="req-br-month-plain",
        dataset_key="broker_recommend",
        run_profile="point_incremental",
        trigger_source="test",
        params={"month": "202603"},
    )
    validated_month_plain = validator.validate(req_month_plain, contract)
    units_month_plain = build_broker_recommend_units(validated_month_plain, contract, dao=None, settings=None, session=None)
    assert units_month_plain[0].request_params == {"month": "202603"}

    req_trade_date = RunRequest(
        request_id="req-br-trade-date",
        dataset_key="broker_recommend",
        run_profile="point_incremental",
        trigger_source="test",
        trade_date=date(2026, 3, 31),
        params={},
    )
    validated_trade_date = validator.validate(req_trade_date, contract)
    units_trade_date = build_broker_recommend_units(validated_trade_date, contract, dao=None, settings=None, session=None)
    assert units_trade_date[0].request_params == {"month": "202603"}
    assert units_trade_date[0].pagination_policy == "offset_limit"
    assert units_trade_date[0].page_limit == 1000
