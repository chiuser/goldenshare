from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest

from src.foundation.services.sync_v2.adapters.tushare import TushareSyncV2Adapter
from src.foundation.services.sync_v2.contracts import FetchResult, NormalizedBatch, PlanUnit, RunRequest, ValidatedRunRequest
from src.foundation.services.sync_v2.dataset_strategies.dc_hot import build_dc_hot_units
from src.foundation.services.sync_v2.dataset_strategies.kpl_list import build_kpl_list_units
from src.foundation.services.sync_v2.dataset_strategies.limit_list_ths import build_limit_list_ths_units
from src.foundation.services.sync_v2.dataset_strategies.ths_hot import build_ths_hot_units
from src.foundation.services.sync_v2.errors import SyncV2NormalizeError, SyncV2ValidationError, SyncV2WriteError
from src.foundation.services.sync_v2.linter import lint_contract
from src.foundation.services.sync_v2.normalizer import SyncV2Normalizer
from src.foundation.services.sync_v2.planner import SyncV2Planner
from src.foundation.services.sync_v2.registry import get_sync_v2_contract
from src.foundation.services.sync_v2.registry_parts.common.constants import (
    ALL_DC_HOT_MARKETS,
    ALL_DC_HOT_TYPES,
    ALL_KPL_LIST_TAGS,
    ALL_LIMIT_LIST_THS_LIMIT_TYPES,
    ALL_LIMIT_LIST_THS_MARKETS,
    ALL_RANKING_IS_NEW_FLAGS,
    ALL_THS_HOT_MARKETS,
)
from src.foundation.services.sync_v2.validator import ContractValidator
from src.foundation.services.sync_v2.writer import SyncV2Writer


FORBIDDEN_SENTINEL = "__ALL__"


def _validate(dataset_key: str, params: dict | None = None):
    contract = get_sync_v2_contract(dataset_key)
    request = RunRequest(
        request_id=f"req-{dataset_key}",
        dataset_key=dataset_key,
        run_profile="point_incremental",
        trigger_source="test",
        trade_date=date(2026, 4, 24),
        params=params or {},
    )
    return contract, ContractValidator().validate(request, contract)


def _assert_no_forbidden_sentinel(units: list[PlanUnit]) -> None:
    for unit in units:
        assert FORBIDDEN_SENTINEL not in str(unit.request_params)


def test_risk_002_default_hotspot_requests_expand_real_enum_values() -> None:
    contract, validated = _validate("dc_hot")
    dc_hot_units = build_dc_hot_units(validated, contract, dao=None, settings=None, session=None)
    assert len(dc_hot_units) == len(ALL_DC_HOT_MARKETS) * len(ALL_DC_HOT_TYPES) * len(ALL_RANKING_IS_NEW_FLAGS)
    assert {
        (unit.request_params["market"], unit.request_params["hot_type"], unit.request_params["is_new"])
        for unit in dc_hot_units
    } == {
        (market, hot_type, is_new)
        for market in ALL_DC_HOT_MARKETS
        for hot_type in ALL_DC_HOT_TYPES
        for is_new in ALL_RANKING_IS_NEW_FLAGS
    }
    _assert_no_forbidden_sentinel(dc_hot_units)

    contract, validated = _validate("ths_hot")
    ths_hot_units = build_ths_hot_units(validated, contract, dao=None, settings=None, session=None)
    assert len(ths_hot_units) == len(ALL_THS_HOT_MARKETS) * len(ALL_RANKING_IS_NEW_FLAGS)
    assert {
        (unit.request_params["market"], unit.request_params["is_new"])
        for unit in ths_hot_units
    } == {
        (market, is_new)
        for market in ALL_THS_HOT_MARKETS
        for is_new in ALL_RANKING_IS_NEW_FLAGS
    }
    _assert_no_forbidden_sentinel(ths_hot_units)


def test_risk_002_default_kpl_and_limit_requests_expand_real_enum_values() -> None:
    contract, validated = _validate("kpl_list")
    kpl_units = build_kpl_list_units(validated, contract, dao=None, settings=None, session=None)
    assert len(kpl_units) == len(ALL_KPL_LIST_TAGS)
    assert {unit.request_params["tag"] for unit in kpl_units} == set(ALL_KPL_LIST_TAGS)
    _assert_no_forbidden_sentinel(kpl_units)

    contract, validated = _validate("limit_list_ths")
    limit_units = build_limit_list_ths_units(validated, contract, dao=None, settings=None, session=None)
    assert len(limit_units) == len(ALL_LIMIT_LIST_THS_LIMIT_TYPES) * len(ALL_LIMIT_LIST_THS_MARKETS)
    assert {
        (unit.request_params["limit_type"], unit.request_params["market"])
        for unit in limit_units
    } == {
        (limit_type, market)
        for limit_type in ALL_LIMIT_LIST_THS_LIMIT_TYPES
        for market in ALL_LIMIT_LIST_THS_MARKETS
    }
    _assert_no_forbidden_sentinel(limit_units)


def test_risk_002_validator_rejects_forbidden_sentinel_input() -> None:
    contract = get_sync_v2_contract("dc_hot")
    request = RunRequest(
        request_id="req-dc-hot-forbidden",
        dataset_key="dc_hot",
        run_profile="point_incremental",
        trigger_source="test",
        trade_date=date(2026, 4, 24),
        params={"market": FORBIDDEN_SENTINEL},
    )

    with pytest.raises(SyncV2ValidationError) as exc_info:
        ContractValidator().validate(request, contract)

    assert exc_info.value.structured_error.error_code == "forbidden_sentinel"


def test_risk_002_adapter_rejects_forbidden_sentinel_plan_params() -> None:
    contract = get_sync_v2_contract("dc_hot")
    unit = PlanUnit(
        unit_id="u-dc-hot-forbidden",
        dataset_key="dc_hot",
        source_key="tushare",
        trade_date=date(2026, 4, 24),
        request_params={"trade_date": "20260424", "market": FORBIDDEN_SENTINEL},
    )

    with pytest.raises(ValueError):
        TushareSyncV2Adapter(connector=SimpleNamespace()).build_request(contract=contract, unit=unit)


def test_risk_002_limit_list_ths_adapter_injects_query_context_from_request_params() -> None:
    class _Connector:
        def call(self, *, api_name, params, fields):  # type: ignore[no-untyped-def]
            assert api_name == "limit_list_ths"
            assert params["limit_type"] == "涨停池"
            assert params["market"] == "HS"
            return [{"trade_date": "20260424", "ts_code": "000001.SZ", "limit_type": "涨停池", "market_type": "HS"}]

    request = TushareSyncV2Adapter(connector=_Connector()).build_request(
        contract=get_sync_v2_contract("limit_list_ths"),
        unit=PlanUnit(
            unit_id="u-limit-list-ths",
            dataset_key="limit_list_ths",
            source_key="tushare",
            trade_date=date(2026, 4, 24),
            request_params={"trade_date": "20260424", "limit_type": "涨停池", "market": "HS"},
        ),
    )
    rows = TushareSyncV2Adapter(connector=_Connector()).execute(request)

    assert rows[0]["query_limit_type"] == "涨停池"
    assert rows[0]["query_market"] == "HS"


def test_risk_002_normalizer_rejects_forbidden_sentinel_rows() -> None:
    contract = get_sync_v2_contract("dc_hot")

    with pytest.raises(SyncV2NormalizeError) as exc_info:
        SyncV2Normalizer().normalize(
            contract=contract,
            fetch_result=FetchResult(
                unit_id="u-dc-hot-normalize-forbidden",
                request_count=1,
                retry_count=0,
                latency_ms=1,
                rows_raw=[
                    {
                        "trade_date": "20260424",
                        "data_type": "热度",
                        "ts_code": "000001.SZ",
                        "rank_time": "10:00:00",
                        "query_market": FORBIDDEN_SENTINEL,
                        "query_hot_type": "人气榜",
                        "query_is_new": "Y",
                    }
                ],
            ),
        )

    assert exc_info.value.structured_error.error_code == "forbidden_sentinel"


def test_risk_002_writer_rejects_forbidden_sentinel_rows(mocker) -> None:
    mocker.patch(
        "src.foundation.services.sync_v2.writer.DAOFactory",
        return_value=SimpleNamespace(),
    )
    writer = SyncV2Writer(session=object())  # type: ignore[arg-type]

    with pytest.raises(SyncV2WriteError) as exc_info:
        writer.write(
            contract=get_sync_v2_contract("dc_hot"),
            batch=NormalizedBatch(
                unit_id="u-dc-hot-write-forbidden",
                rows_normalized=[{"trade_date": date(2026, 4, 24), "query_market": FORBIDDEN_SENTINEL}],
                rows_rejected=0,
                rejected_reasons={},
            ),
        )

    assert exc_info.value.structured_error.error_code == "forbidden_sentinel"


def test_risk_002_linter_rejects_forbidden_sentinel_defaults() -> None:
    contract = get_sync_v2_contract("dc_hot")
    broken_contract = replace(
        contract,
        planning_spec=replace(
            contract.planning_spec,
            enum_fanout_defaults={**contract.planning_spec.enum_fanout_defaults, "market": (FORBIDDEN_SENTINEL,)},
        ),
    )

    issues = lint_contract(broken_contract)

    assert any(issue.code == "forbidden_sentinel" for issue in issues)


def test_risk_002_planner_preserves_non_string_enum_values() -> None:
    contract = get_sync_v2_contract("dc_hot")
    narrowed_contract = replace(
        contract,
        planning_spec=replace(
            contract.planning_spec,
            enum_fanout_fields=("market",),
            enum_fanout_defaults={},
        ),
    )
    request = ValidatedRunRequest(
        request_id="req-dc-hot-numeric-market",
        dataset_key="dc_hot",
        run_profile="point_incremental",
        trigger_source="test",
        params={"market": 1},
        source_key=None,
        trade_date=date(2026, 4, 24),
        start_date=None,
        end_date=None,
        correlation_id="corr-dc-hot-numeric-market",
        rerun_id=None,
        execution_id=None,
        validated_at=datetime.now(timezone.utc),
    )

    planner = object.__new__(SyncV2Planner)
    assert planner._resolve_enum_fanout_values(request, narrowed_contract) == [{"market": 1}]
