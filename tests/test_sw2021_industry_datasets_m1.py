from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import date
from pathlib import Path
from types import SimpleNamespace
import runpy

import pytest
from sqlalchemy.sql.dml import Delete

from src.foundation.datasets.definitions import BOARD_HOTSPOT_ROWS
from src.foundation.datasets.definitions._builder import build_definition
from src.foundation.datasets.freshness_policies import (
    CONTINUOUS_OPEN_DAY,
    SNAPSHOT_RUN_TRACE,
)
from src.foundation.datasets.registry import get_dataset_definition
from src.foundation.datasets.sw_industry_contracts import (
    SW2021_INDEX_CODE_ALIASES_V1,
    SwIndustryContractError,
    normalize_sw2021_index_code,
)
from src.foundation.ingestion import (
    DatasetActionRequest,
    DatasetActionResolver,
    DatasetTimeInput,
)
from src.foundation.ingestion.errors import (
    IngestionNormalizeError,
    IngestionPlanningError,
    IngestionSourceError,
    IngestionValidationError,
    IngestionWriteError,
)
from src.foundation.ingestion.executor import IngestionExecutor, _RunState
from src.foundation.ingestion.execution_plan import PlanUnitSnapshot
from src.foundation.ingestion.normalizer import DatasetNormalizer, NormalizedBatch
from src.foundation.ingestion.pre_write_validators import get_pre_write_validator
from src.foundation.ingestion.source_client import (
    DatasetSourceClient,
    SourceFetchResult,
)
from src.foundation.ingestion.writer import DatasetWriter
from src.foundation.models.core_serving.sw_industry_classification import (
    SwIndustryClassification,
)
from src.foundation.models.core_serving.sw_industry_daily import SwIndustryDaily
from src.foundation.models.core_serving.sw_industry_member import SwIndustryMember
from src.foundation.models.table_model_registry import get_model_by_table_name
from src.ops.catalog.dataset_catalog_view_resolver import (
    resolve_default_dataset_catalog_item,
)


MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "alembic/versions/20260818_000138_add_sw2021_industry_serving_tables.py"
)


def _row(dataset_key: str) -> dict:
    return deepcopy(
        next(
            row
            for row in BOARD_HOTSPOT_ROWS
            if row["identity"]["dataset_key"] == dataset_key
        )
    )


def test_sw2021_code_contract_preserves_source_policy_and_rejects_typo() -> None:
    assert SW2021_INDEX_CODE_ALIASES_V1 == {"850401.SI": "850412.SI"}
    assert normalize_sw2021_index_code("850412.si") == "850412.SI"
    assert normalize_sw2021_index_code("850401.SI") == "850412.SI"
    assert (
        normalize_sw2021_index_code("850401.SI", classification_industry_code="230501")
        == "850412.SI"
    )
    with pytest.raises(SwIndustryContractError, match="230501"):
        normalize_sw2021_index_code("850401.SI", classification_industry_code="999999")
    with pytest.raises(SwIndustryContractError, match="840401"):
        normalize_sw2021_index_code("840401.SI")


def test_sw2021_definitions_project_direct_serving_and_internal_variant_contracts() -> (
    None
):
    classification = get_dataset_definition("index_classify")
    member = get_dataset_definition("index_member_all")
    daily = get_dataset_definition("sw_daily")

    assert classification.source.base_params == {"src": "SW2021"}
    assert classification.source.source_fields == (
        "index_code",
        "industry_name",
        "parent_code",
        "level",
        "industry_code",
        "is_pub",
        "src",
    )
    assert classification.storage.replacement_scope_fields == ("src",)
    assert classification.storage.raw_table is None
    assert classification.storage.write_path == "serving_direct_scope_replace"
    assert classification.planning.max_source_rows_per_unit == 2000
    assert classification.observability.freshness_policy == SNAPSHOT_RUN_TRACE

    assert member.input_model.filters == ()
    assert member.planning.enum_fanout_fields == ()
    assert member.planning.request_variant_fields == ("is_new",)
    assert member.planning.request_variant_defaults == {"is_new": ("Y", "N")}
    assert member.planning.max_source_rows_per_unit == 20000
    assert member.quality.empty_result_policy == "fail_unit_per_request_variant"
    assert member.storage.replacement_scope_fields == ("classification_version",)
    assert member.observability.freshness_policy == SNAPSHOT_RUN_TRACE

    assert daily.source.source_fields == (
        "ts_code",
        "trade_date",
        "name",
        "open",
        "low",
        "high",
        "close",
        "change",
        "pct_change",
        "vol",
        "amount",
        "pe",
        "pb",
        "float_mv",
        "total_mv",
    )
    assert daily.input_model.filters == ()
    assert daily.planning.unit_builder_key == "build_sw_daily_units"
    assert daily.storage.replacement_scope_fields == ("trade_date",)
    assert daily.observability.freshness_policy == CONTINUOUS_OPEN_DAY

    assert resolve_default_dataset_catalog_item("index_classify").item_order == 80
    assert resolve_default_dataset_catalog_item("index_member_all").item_order == 90
    assert resolve_default_dataset_catalog_item("sw_daily").item_order == 100


def test_scope_replace_builder_rejects_partial_contract() -> None:
    row = _row("index_classify")
    row["storage"]["replacement_scope_fields"] = ()
    with pytest.raises(ValueError, match="replacement_scope_fields"):
        build_definition(row)

    row = _row("index_member_all")
    row["input_model"]["filters"] = (
        {"name": "is_new", "field_type": "string", "required": False},
    )
    with pytest.raises(ValueError, match="不得暴露"):
        build_definition(row)

    row = _row("index_classify")
    row["planning"]["max_source_rows_per_unit"] = 0
    with pytest.raises(ValueError, match="max_source_rows_per_unit 必须为正整数"):
        build_definition(row)

    row = _row("index_member_all")
    row["planning"]["page_limit"] = 20001
    with pytest.raises(
        ValueError,
        match="page_limit 不得超过 max_source_rows_per_unit",
    ):
        build_definition(row)


def test_member_plan_keeps_y_n_inside_one_immutable_unit(mocker) -> None:
    resolver = DatasetActionResolver(mocker.Mock())
    plan = resolver.build_plan(
        DatasetActionRequest(
            dataset_key="index_member_all",
            action="maintain",
            time_input=DatasetTimeInput(mode="none"),
        )
    )

    assert plan.planning.unit_count == 1
    assert plan.planning.request_variant_fields == ("is_new",)
    assert plan.planning.max_source_rows_per_unit == 20000
    assert plan.quality.empty_result_policy == "fail_unit_per_request_variant"
    assert plan.writing.replacement_scope_fields == ("classification_version",)
    assert plan.units[0].request_params == {}
    assert plan.units[0].max_source_rows_per_unit == 20000
    assert plan.units[0].request_variants == ({"is_new": "Y"}, {"is_new": "N"})

    with pytest.raises(IngestionValidationError, match="存在未定义参数：is_new"):
        resolver.build_plan(
            DatasetActionRequest(
                dataset_key="index_member_all",
                action="maintain",
                time_input=DatasetTimeInput(mode="none"),
                filters={"is_new": "Y"},
            )
        )


def test_sw_daily_plan_expands_only_open_dates_and_rejects_non_open_point(
    mocker,
) -> None:
    trade_calendar = SimpleNamespace(
        get_open_dates=mocker.Mock(return_value=[date(2026, 8, 13), date(2026, 8, 14)])
    )
    mocker.patch(
        "src.foundation.ingestion.unit_planner.DAOFactory",
        return_value=SimpleNamespace(trade_calendar=trade_calendar),
    )
    resolver = DatasetActionResolver(mocker.Mock())
    plan = resolver.build_plan(
        DatasetActionRequest(
            dataset_key="sw_daily",
            action="maintain",
            time_input=DatasetTimeInput(
                mode="range",
                start_date=date(2026, 8, 12),
                end_date=date(2026, 8, 14),
            ),
        )
    )
    assert [unit.trade_date for unit in plan.units] == [
        date(2026, 8, 13),
        date(2026, 8, 14),
    ]
    assert [unit.request_params for unit in plan.units] == [
        {"trade_date": "20260813"},
        {"trade_date": "20260814"},
    ]

    trade_calendar.get_open_dates.return_value = []
    with pytest.raises(IngestionPlanningError, match="没有开市交易日") as exc_info:
        resolver.build_plan(
            DatasetActionRequest(
                dataset_key="sw_daily",
                action="maintain",
                time_input=DatasetTimeInput(mode="point", trade_date=date(2026, 8, 15)),
            )
        )
    assert exc_info.value.structured_error.error_code == "invalid_anchor_date"


class _VariantConnector:
    def __init__(self, *, empty_n: bool = False) -> None:
        self.empty_n = empty_n
        self.calls: list[dict] = []

    def call(
        self, *, api_name: str, params: dict, fields: tuple[str, ...]
    ) -> list[dict]:
        assert api_name == "index_member_all"
        assert len(fields) == 11
        self.calls.append(dict(params))
        if params["is_new"] == "N" and self.empty_n:
            return []
        page_size = 2 if params["offset"] == 0 else 1
        return [
            {"is_new": params["is_new"], "offset": params["offset"], "ordinal": index}
            for index in range(page_size)
        ]


def test_source_client_fans_in_variants_and_fails_closed_on_empty_variant(
    mocker,
) -> None:
    resolver = DatasetActionResolver(mocker.Mock())
    plan = resolver.build_plan(
        DatasetActionRequest(
            "index_member_all", "maintain", DatasetTimeInput(mode="none")
        )
    )
    definition = get_dataset_definition("index_member_all")
    connector = _VariantConnector()
    mocker.patch(
        "src.foundation.ingestion.source_client.create_source_connector",
        return_value=connector,
    )

    unit = replace(plan.units[0], page_limit=2)
    result = DatasetSourceClient().fetch(definition=definition, unit=unit)

    assert [(call["is_new"], call["offset"]) for call in connector.calls] == [
        ("Y", 0),
        ("Y", 2),
        ("N", 0),
        ("N", 2),
    ]
    assert all(call["limit"] == 2 for call in connector.calls)
    assert result.request_count == 4
    assert result.pagination_diagnostics["request_variants"] == [
        {
            "variant": {"is_new": "Y"},
            "page_count": 2,
            "total_rows": 3,
            "terminal_offset": 2,
            "terminal_page_rows": 1,
        },
        {
            "variant": {"is_new": "N"},
            "page_count": 2,
            "total_rows": 3,
            "terminal_offset": 2,
            "terminal_page_rows": 1,
        },
    ]

    empty_connector = _VariantConnector(empty_n=True)
    mocker.patch(
        "src.foundation.ingestion.source_client.create_source_connector",
        return_value=empty_connector,
    )
    with pytest.raises(IngestionSourceError) as exc_info:
        DatasetSourceClient().fetch(definition=definition, unit=unit)
    assert exc_info.value.structured_error.error_code == "source_variant_empty"


def test_task_run_pagination_diagnostics_keep_request_variant_breakdown(mocker) -> None:
    resolver = DatasetActionResolver(mocker.Mock())
    plan = resolver.build_plan(
        DatasetActionRequest(
            "index_member_all", "maintain", DatasetTimeInput(mode="none")
        )
    )
    state = _RunState()
    source_result = SimpleNamespace(
        retry_count=0,
        pagination_diagnostics={
            "page_count": 5,
            "total_rows_merged": 7899,
            "terminal_offset": 2000,
            "terminal_page_rows": 4,
            "observed_short_page": True,
            "request_variants": [
                {"variant": {"is_new": "Y"}, "page_count": 3, "total_rows": 5895},
                {"variant": {"is_new": "N"}, "page_count": 2, "total_rows": 2004},
            ],
        },
    )

    IngestionExecutor._record_pagination_diagnostics(
        state,
        unit=plan.units[0],
        source_result=source_result,
    )

    assert state.pagination_units == [
        {
            "unit_id": plan.units[0].unit_id,
            "page_count": 5,
            "terminal_offset": 2000,
            "terminal_page_rows": 4,
            "request_variants": [
                {"variant": {"is_new": "Y"}, "page_count": 3, "total_rows": 5895},
                {"variant": {"is_new": "N"}, "page_count": 2, "total_rows": 2004},
            ],
        }
    ]


def test_sw2021_normalizers_preserve_source_codes_and_reject_typo() -> None:
    definition = get_dataset_definition("index_classify")
    fetch = SourceFetchResult(
        unit_id="classification",
        request_count=1,
        retry_count=0,
        latency_ms=1,
        rows_raw=[
            {
                "index_code": "850401.SI",
                "industry_name": "特钢Ⅲ",
                "parent_code": "230500",
                "level": "L3",
                "industry_code": "230501",
                "is_pub": 1,
                "src": "SW2021",
            },
            {
                "index_code": "801000.SI",
                "industry_name": "钢铁",
                "parent_code": None,
                "level": "L1",
                "industry_code": "230000",
                "is_pub": 1,
                "src": "SW2021",
            },
            {
                "index_code": "801050.SI",
                "industry_name": "特钢",
                "parent_code": "230000",
                "level": "L2",
                "industry_code": "230500",
                "is_pub": 1,
                "src": "SW2021",
            },
        ],
    )
    batch = DatasetNormalizer().normalize(definition=definition, fetch_result=fetch)
    assert batch.rows_rejected == 0
    assert batch.rows_normalized[0]["source_index_code"] == "850401.SI"
    assert batch.rows_normalized[0]["index_code"] == "850412.SI"

    bad = deepcopy(fetch.rows_raw[0])
    bad["index_code"] = "840401.SI"
    rejected = DatasetNormalizer().normalize(
        definition=definition,
        fetch_result=SourceFetchResult(
            unit_id="bad", request_count=1, retry_count=0, latency_ms=1, rows_raw=[bad]
        ),
    )
    assert rejected.rows_rejected == 1
    assert rejected.rejected_reasons == {"normalize.sw_industry_code_invalid": 1}

    conflicting_rows = deepcopy(fetch.rows_raw)
    conflicting_rows.append({**conflicting_rows[0], "index_code": "850412.SI"})
    with pytest.raises(IngestionNormalizeError) as exc_info:
        DatasetNormalizer().normalize(
            definition=definition,
            fetch_result=SourceFetchResult(
                unit_id="conflict",
                request_count=1,
                retry_count=0,
                latency_ms=1,
                rows_raw=conflicting_rows,
            ),
        )
    assert (
        exc_info.value.structured_error.error_code
        == "normalize.batch_unique_key_conflicting"
    )


def test_classification_prewrite_validator_checks_three_level_closure() -> None:
    validator = get_pre_write_validator("sw2021_classification_snapshot")
    rows = [
        {
            "src": "SW2021",
            "industry_code": "230000",
            "source_index_code": "801000.SI",
            "index_code": "801000.SI",
            "level": "L1",
            "parent_code": None,
        },
        {
            "src": "SW2021",
            "industry_code": "230500",
            "source_index_code": "801050.SI",
            "index_code": "801050.SI",
            "level": "L2",
            "parent_code": "230000",
        },
        {
            "src": "SW2021",
            "industry_code": "230501",
            "source_index_code": "850401.SI",
            "index_code": "850412.SI",
            "level": "L3",
            "parent_code": "230500",
        },
    ]
    validator(SimpleNamespace(), rows, get_dataset_definition("index_classify"), None)
    rows[2]["parent_code"] = "999999"
    with pytest.raises(ValueError, match="不闭合"):
        validator(
            SimpleNamespace(), rows, get_dataset_definition("index_classify"), None
        )


class _FakeScopeDAO:
    model = SwIndustryDaily

    def __init__(self) -> None:
        self.rows: list[dict] = []

    def bulk_insert(self, rows: list[dict]) -> int:
        self.rows = deepcopy(rows)
        return len(rows)


def _daily_row(trade_date: date, ts_code: str = "801010.SI") -> dict:
    return {
        "source_ts_code": ts_code,
        "ts_code": ts_code,
        "trade_date": trade_date,
        "name": "农林牧渔",
        "open": 100.0,
        "low": 99.0,
        "high": 103.0,
        "close": 102.0,
        "change": 2.0,
        "pct_change": 2.0,
        "vol": 10.0,
        "amount": 20.0,
        "pe": None,
        "pb": 1.2,
        "float_mv": 100.0,
        "total_mv": 120.0,
        "classification_version": "SW2021",
        "source": "tushare",
        "normalization_rule_version": "sw2021-index-code-v1",
    }


def test_scope_replace_is_bounded_and_read_back_verified(mocker) -> None:
    session = mocker.Mock()
    session.get_bind.return_value = SimpleNamespace(
        dialect=SimpleNamespace(name="sqlite")
    )
    session.scalar.return_value = 2
    dao = _FakeScopeDAO()
    session.scalars.side_effect = lambda _stmt: [
        SimpleNamespace(
            **{
                column.name: row.get(column.name)
                for column in SwIndustryDaily.__table__.columns
            }
        )
        for row in dao.rows
    ]
    writer = DatasetWriter(session)
    writer.dao = SimpleNamespace(sw_industry_daily=dao)
    unit_date = date(2026, 8, 14)
    unit = PlanUnitSnapshot(
        unit_id="sw-daily-20260814",
        dataset_key="sw_daily",
        source_key="tushare",
        trade_date=unit_date,
        request_params={"trade_date": "20260814"},
        progress_context={"trade_date": "2026-08-14"},
    )
    batch = NormalizedBatch(
        unit_id=unit.unit_id,
        rows_normalized=[_daily_row(unit_date)],
        rows_rejected=0,
        rejected_reasons={},
    )

    result = writer.write(
        definition=get_dataset_definition("sw_daily"),
        batch=batch,
        plan_unit=unit,
        run_profile="point_incremental",
    )

    assert result.conflict_strategy == "serving_direct_scope_replace"
    assert result.rows_written == result.rows_inserted == 1
    delete_statements = [
        call.args[0]
        for call in session.execute.call_args_list
        if isinstance(call.args[0], Delete)
    ]
    assert len(delete_statements) == 1
    assert "WHERE core_serving.sw_industry_daily.trade_date" in str(
        delete_statements[0]
    )


def test_scope_replace_rejects_empty_rejected_multi_scope_and_date_mismatch_before_dml(
    mocker,
) -> None:
    session = mocker.Mock()
    writer = DatasetWriter(session)
    writer.dao = SimpleNamespace(sw_industry_daily=_FakeScopeDAO())
    definition = get_dataset_definition("sw_daily")
    unit = SimpleNamespace(unit_id="daily", trade_date=date(2026, 8, 14))

    cases = (
        (
            NormalizedBatch(
                unit_id="empty",
                rows_normalized=[],
                rows_rejected=0,
                rejected_reasons={},
            ),
            unit,
        ),
        (
            NormalizedBatch(
                unit_id="rejected",
                rows_normalized=[_daily_row(date(2026, 8, 14))],
                rows_rejected=1,
                rejected_reasons={"x": 1},
            ),
            unit,
        ),
        (
            NormalizedBatch(
                unit_id="multi",
                rows_normalized=[
                    _daily_row(date(2026, 8, 14)),
                    _daily_row(date(2026, 8, 13), "801020.SI"),
                ],
                rows_rejected=0,
                rejected_reasons={},
            ),
            None,
        ),
        (
            NormalizedBatch(
                unit_id="mismatch",
                rows_normalized=[_daily_row(date(2026, 8, 13))],
                rows_rejected=0,
                rejected_reasons={},
            ),
            unit,
        ),
    )
    expected_codes = (
        "write.scope_empty",
        "write.scope_rows_rejected",
        "write.scope_invalid",
        "write.scope_preflight_failed",
    )
    for (batch, plan_unit), expected_code in zip(cases, expected_codes, strict=True):
        with pytest.raises(IngestionWriteError) as exc_info:
            writer.write(definition=definition, batch=batch, plan_unit=plan_unit)
        assert exc_info.value.structured_error.error_code == expected_code
    session.execute.assert_not_called()


def test_sw2021_models_and_linear_migration_match_frozen_schema() -> None:
    assert tuple(
        column.name for column in SwIndustryClassification.__table__.primary_key.columns
    ) == ("src", "industry_code")
    assert tuple(
        column.name for column in SwIndustryMember.__table__.primary_key.columns
    ) == ("l3_code", "ts_code", "in_date")
    assert tuple(
        column.name for column in SwIndustryDaily.__table__.primary_key.columns
    ) == ("ts_code", "trade_date")
    assert any(
        constraint.name == "uq_sw_industry_classification_src_index_code"
        for constraint in SwIndustryClassification.__table__.constraints
    )
    assert any(
        constraint.name == "fk_sw_industry_member_classification_l3"
        for constraint in SwIndustryMember.__table__.constraints
    )
    assert (
        get_model_by_table_name("core_serving.sw_industry_classification")
        is SwIndustryClassification
    )
    assert (
        get_model_by_table_name("core_serving.sw_industry_member") is SwIndustryMember
    )
    assert get_model_by_table_name("core_serving.sw_industry_daily") is SwIndustryDaily

    migration = runpy.run_path(str(MIGRATION))
    migration_text = MIGRATION.read_text(encoding="utf-8")
    upgrade_text = migration_text.split("def upgrade()", maxsplit=1)[1].split(
        "def downgrade()", maxsplit=1
    )[0]
    assert migration["revision"] == "20260818_000138"
    assert migration["down_revision"] == "20260816_000137"
    assert (
        upgrade_text.index('"sw_industry_classification"')
        < upgrade_text.index('"sw_industry_member"')
        < upgrade_text.index('"sw_industry_daily"')
    )
    for forbidden in (
        "TRUNCATE",
        "DELETE FROM",
        "INSERT INTO",
        "GRANT ",
        "CREATE ROLE",
        "CREATE LOGIN",
    ):
        assert forbidden not in upgrade_text.upper()
