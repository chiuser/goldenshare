from __future__ import annotations

from collections import Counter
from copy import deepcopy
from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from src.foundation.datasets.registry import get_dataset_definition
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
from src.foundation.ingestion.execution_plan import ValidatedDatasetActionRequest
from src.foundation.ingestion.executor import IngestionExecutor
from src.foundation.ingestion.normalizer import DatasetNormalizer
from src.foundation.ingestion.pre_write_validators import (
    PreWriteValidationError,
    get_pre_write_validator,
)
from src.foundation.ingestion.source_client import (
    DatasetSourceClient,
    SourceFetchResult,
)
from src.foundation.models.core_serving.sw_industry_daily import SwIndustryDaily
from src.ops.dataset_definition_projection import get_dataset_freshness_projection
from src.ops.queries.manual_action_query_service import ManualActionQueryService
from src.ops.services.schedule_automation_capability_resolver import (
    ScheduleAutomationCapabilityResolver,
)


SOURCE_FIELDS = (
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


def _source_row(
    ts_code: str,
    *,
    trade_date: str = "20260814",
    name: str | None = None,
) -> dict:
    return {
        "ts_code": ts_code,
        "trade_date": trade_date,
        "name": name or f"申万指数{ts_code[:6]}",
        "open": 100.0,
        "low": 99.0,
        "high": 103.0,
        "close": 102.0,
        "change": 2.0,
        "pct_change": 2.0,
        "vol": 1000.0,
        "amount": 2000.0,
        "pe": 12.5,
        "pb": 1.2,
        "float_mv": 100000.0,
        "total_mv": 120000.0,
    }


def _full_market_rows(*, trade_date: str = "20260814") -> list[dict]:
    rows = [
        _source_row("850412.SI", trade_date=trade_date, name="特钢Ⅲ"),
        *[
            _source_row(f"{880000 + index:06d}.SI", trade_date=trade_date)
            for index in range(413)
        ],
        *[
            _source_row(f"{990000 + index:06d}.SI", trade_date=trade_date)
            for index in range(25)
        ],
    ]
    rows[1]["pe"] = None
    return rows


def _plan(mocker, *, time_input: DatasetTimeInput, open_dates: list[date]):  # type: ignore[no-untyped-def]
    trade_calendar = SimpleNamespace(
        get_open_dates=mocker.Mock(return_value=list(open_dates))
    )
    mocker.patch(
        "src.foundation.ingestion.unit_planner.DAOFactory",
        return_value=SimpleNamespace(trade_calendar=trade_calendar),
    )
    plan = DatasetActionResolver(mocker.Mock()).build_plan(
        DatasetActionRequest(
            dataset_key="sw_daily",
            action="maintain",
            time_input=time_input,
        )
    )
    return plan, trade_calendar


def _validated_request(plan) -> ValidatedDatasetActionRequest:  # type: ignore[no-untyped-def]
    return ValidatedDatasetActionRequest(
        request_id=plan.plan_id,
        dataset_key=plan.dataset_key,
        action=plan.action,
        run_profile=plan.run_profile,
        trigger_source="test",
        params=dict(plan.filters),
        source_key=plan.source.source_key,
    )


@pytest.fixture()
def daily_session() -> Session:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    with engine.begin() as connection:
        connection.exec_driver_sql("ATTACH DATABASE ':memory:' AS core_serving")
        SwIndustryDaily.__table__.create(connection)
    testing_session_local = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        future=True,
    )
    session = testing_session_local()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


class _DailyConnector:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = deepcopy(rows)
        self.calls: list[dict] = []

    def call(
        self, *, api_name: str, params: dict, fields: tuple[str, ...]
    ) -> list[dict]:
        assert api_name == "sw_daily"
        assert fields == SOURCE_FIELDS
        assert set(params) == {"trade_date", "offset", "limit"}
        assert params["limit"] == 2000
        self.calls.append(dict(params))
        rows = [row for row in self.rows if row["trade_date"] == params["trade_date"]]
        offset = int(params["offset"])
        return deepcopy(rows[offset : offset + int(params["limit"])])


class _CountedDailyConnector:
    def __init__(self, total: int) -> None:
        self.total = total
        self.calls: list[dict] = []

    def call(
        self, *, api_name: str, params: dict, fields: tuple[str, ...]
    ) -> list[dict]:
        assert api_name == "sw_daily"
        assert fields == SOURCE_FIELDS
        assert set(params) == {"trade_date", "offset", "limit"}
        self.calls.append(dict(params))
        offset = int(params["offset"])
        page_end = min(offset + int(params["limit"]), self.total)
        return [{"ordinal": index} for index in range(offset, page_end)]


def test_sw_daily_definition_and_plan_freeze_daily_full_market_contract(mocker) -> None:
    definition = get_dataset_definition("sw_daily")
    open_dates = [date(2026, 8, 13), date(2026, 8, 14)]
    plan, trade_calendar = _plan(
        mocker,
        time_input=DatasetTimeInput(
            mode="range",
            start_date=date(2026, 8, 12),
            end_date=date(2026, 8, 14),
        ),
        open_dates=open_dates,
    )

    assert definition.source.source_fields == SOURCE_FIELDS
    assert definition.input_model.filters == ()
    assert definition.date_model.date_axis == "trade_open_day"
    assert definition.date_model.input_shape == "trade_date_or_start_end"
    assert definition.date_model.observed_field == "trade_date"
    assert definition.storage.raw_table is None
    assert definition.storage.raw_dao_name is None
    assert definition.storage.layer_plan == "source->serving"
    assert definition.storage.write_path == "serving_direct_scope_replace"
    assert definition.storage.replacement_scope_fields == ("trade_date",)
    assert definition.planning.page_limit == 2000
    assert definition.planning.max_source_rows_per_unit == 2000
    assert definition.planning.max_units_per_execution == 60
    assert definition.planning.fetch_concurrency == 1
    assert definition.planning.page_processing_mode == "buffer_all"
    assert definition.capabilities.get_action("maintain").schedule_enabled is False

    trade_calendar.get_open_dates.assert_called_once_with(
        "SSE", date(2026, 8, 12), date(2026, 8, 14)
    )
    assert plan.run_profile == "range_rebuild"
    assert [unit.trade_date for unit in plan.units] == open_dates
    assert [unit.request_params for unit in plan.units] == [
        {"trade_date": "20260813"},
        {"trade_date": "20260814"},
    ]
    assert all(unit.max_source_rows_per_unit == 2000 for unit in plan.units)
    assert all(set(unit.request_params) == {"trade_date"} for unit in plan.units)

    for invalid_time, invalid_filters in (
        (DatasetTimeInput(mode="none"), {}),
        (
            DatasetTimeInput(mode="point", trade_date=date(2026, 8, 14)),
            {"ts_code": "850412.SI"},
        ),
    ):
        with pytest.raises(IngestionValidationError):
            DatasetActionResolver(mocker.Mock()).build_plan(
                DatasetActionRequest(
                    dataset_key="sw_daily",
                    action="maintain",
                    time_input=invalid_time,
                    filters=invalid_filters,
                )
            )


def test_sw_daily_planner_rejects_non_open_point_and_more_than_sixty_units(
    mocker,
) -> None:
    with pytest.raises(IngestionPlanningError) as non_open:
        _plan(
            mocker,
            time_input=DatasetTimeInput(mode="point", trade_date=date(2026, 8, 15)),
            open_dates=[],
        )
    assert non_open.value.structured_error.error_code == "trade_date_not_open"

    start_date = date(2026, 5, 1)
    sixty_dates = [start_date + timedelta(days=index) for index in range(60)]
    plan, _ = _plan(
        mocker,
        time_input=DatasetTimeInput(
            mode="range", start_date=sixty_dates[0], end_date=sixty_dates[-1]
        ),
        open_dates=sixty_dates,
    )
    assert len(plan.units) == 60

    sixty_one_dates = [start_date + timedelta(days=index) for index in range(61)]
    with pytest.raises(IngestionPlanningError) as too_wide:
        _plan(
            mocker,
            time_input=DatasetTimeInput(
                mode="range",
                start_date=sixty_one_dates[0],
                end_date=sixty_one_dates[-1],
            ),
            open_dates=sixty_one_dates,
        )
    assert too_wide.value.structured_error.error_code == "units_exceeded"
    assert too_wide.value.structured_error.details == {
        "planned_units": 61,
        "max_units_per_execution": 60,
    }


def test_sw_daily_source_paginates_one_day_and_enforces_row_limit_before_normalize(
    daily_session: Session,
    mocker,
) -> None:
    definition = get_dataset_definition("sw_daily")
    plan, _ = _plan(
        mocker,
        time_input=DatasetTimeInput(mode="point", trade_date=date(2026, 8, 14)),
        open_dates=[date(2026, 8, 14)],
    )
    unit = plan.units[0]

    baseline_connector = _DailyConnector(_full_market_rows())
    mocker.patch(
        "src.foundation.ingestion.source_client.create_source_connector",
        return_value=baseline_connector,
    )
    baseline = DatasetSourceClient().fetch(definition=definition, unit=unit)
    assert len(baseline.rows_raw) == 439
    assert baseline.request_count == 1
    assert baseline_connector.calls == [
        {"trade_date": "20260814", "offset": 0, "limit": 2000}
    ]

    boundary_connector = _CountedDailyConnector(2000)
    mocker.patch(
        "src.foundation.ingestion.source_client.create_source_connector",
        return_value=boundary_connector,
    )
    boundary = DatasetSourceClient().fetch(definition=definition, unit=unit)
    assert len(boundary.rows_raw) == 2000
    assert [call["offset"] for call in boundary_connector.calls] == [0, 2000]

    oversized_connector = _CountedDailyConnector(2001)
    mocker.patch(
        "src.foundation.ingestion.source_client.create_source_connector",
        return_value=oversized_connector,
    )
    with pytest.raises(IngestionSourceError) as oversized:
        DatasetSourceClient().fetch(definition=definition, unit=unit)
    assert oversized.value.structured_error.error_code == "source_rows_exceeded"
    assert oversized.value.structured_error.details == {
        "max_source_rows_per_unit": 2000,
        "rows_before_page": 2000,
        "page_rows": 1,
        "observed_rows": 2001,
        "page_number": 2,
        "offset": 2000,
        "request_variant": {},
    }

    executor = IngestionExecutor(daily_session)
    normalize_spy = mocker.spy(executor.normalizer, "normalize")
    with pytest.raises(IngestionSourceError):
        executor.run(
            request=_validated_request(plan),
            definition=definition,
            units=plan.units,
        )
    normalize_spy.assert_not_called()
    assert daily_session.scalar(select(func.count()).select_from(SwIndustryDaily)) == 0


def test_sw_daily_normalization_preserves_all_source_rows_and_rejects_bad_codes() -> (
    None
):
    definition = get_dataset_definition("sw_daily")
    rows = _full_market_rows()
    batch = DatasetNormalizer().normalize(
        definition=definition,
        fetch_result=SourceFetchResult(
            unit_id="daily-normalize",
            request_count=1,
            retry_count=0,
            latency_ms=1,
            rows_raw=rows,
        ),
        expected_unit_date=date(2026, 8, 14),
    )

    assert len(batch.rows_normalized) == 439
    assert batch.rows_rejected == 0
    assert batch.rows_deduplicated == 0
    assert Counter(
        str(row["ts_code"]).startswith("99") for row in batch.rows_normalized
    ) == {False: 414, True: 25}
    nullable = next(row for row in batch.rows_normalized if row["pe"] is None)
    assert nullable["pe"] is None
    assert all(
        row["classification_version"] == "SW2021" for row in batch.rows_normalized
    )
    assert all(row["source"] == "tushare" for row in batch.rows_normalized)

    alias_row = _source_row("850401.SI")
    alias_batch = DatasetNormalizer().normalize(
        definition=definition,
        fetch_result=SourceFetchResult(
            unit_id="daily-alias",
            request_count=1,
            retry_count=0,
            latency_ms=1,
            rows_raw=[alias_row],
        ),
        expected_unit_date=date(2026, 8, 14),
    )
    assert alias_batch.rows_normalized[0]["source_ts_code"] == "850401.SI"
    assert alias_batch.rows_normalized[0]["ts_code"] == "850412.SI"

    typo_row = _source_row("840401.SI")
    typo_batch = DatasetNormalizer().normalize(
        definition=definition,
        fetch_result=SourceFetchResult(
            unit_id="daily-typo",
            request_count=1,
            retry_count=0,
            latency_ms=1,
            rows_raw=[typo_row],
        ),
        expected_unit_date=date(2026, 8, 14),
    )
    assert typo_batch.rows_rejected == 1
    assert typo_batch.rejected_reasons == {"normalize.sw_industry_code_invalid": 1}

    missing_open = _source_row("880999.SI")
    missing_open["open"] = None
    missing_batch = DatasetNormalizer().normalize(
        definition=definition,
        fetch_result=SourceFetchResult(
            unit_id="daily-missing-open",
            request_count=1,
            retry_count=0,
            latency_ms=1,
            rows_raw=[missing_open],
        ),
        expected_unit_date=date(2026, 8, 14),
    )
    assert missing_batch.rows_rejected == 1
    assert missing_batch.rejected_reasons == {
        "normalize.required_field_missing:open": 1
    }

    with pytest.raises(IngestionNormalizeError) as date_mismatch:
        DatasetNormalizer().normalize(
            definition=definition,
            fetch_result=SourceFetchResult(
                unit_id="daily-date-mismatch",
                request_count=1,
                retry_count=0,
                latency_ms=1,
                rows_raw=[_source_row("880999.SI", trade_date="20260813")],
            ),
            expected_unit_date=date(2026, 8, 14),
        )
    assert (
        date_mismatch.value.structured_error.error_code
        == "normalize.unit_date_mismatch"
    )

    conflicting = [deepcopy(rows[0]), deepcopy(rows[0])]
    conflicting[1]["name"] = "冲突名称"
    with pytest.raises(IngestionNormalizeError) as conflict:
        DatasetNormalizer().normalize(
            definition=definition,
            fetch_result=SourceFetchResult(
                unit_id="daily-conflict",
                request_count=1,
                retry_count=0,
                latency_ms=1,
                rows_raw=conflicting,
            ),
            expected_unit_date=date(2026, 8, 14),
        )
    assert (
        conflict.value.structured_error.error_code
        == "normalize.batch_unique_key_conflicting"
    )

    identical = DatasetNormalizer().normalize(
        definition=definition,
        fetch_result=SourceFetchResult(
            unit_id="daily-identical",
            request_count=1,
            retry_count=0,
            latency_ms=1,
            rows_raw=[deepcopy(rows[0]), deepcopy(rows[0])],
        ),
        expected_unit_date=date(2026, 8, 14),
    )
    assert len(identical.rows_normalized) == 1
    assert identical.rows_deduplicated == 1


def test_sw_daily_prewrite_rejects_invalid_market_facts(
    daily_session: Session, mocker
) -> None:
    definition = get_dataset_definition("sw_daily")
    plan, _ = _plan(
        mocker,
        time_input=DatasetTimeInput(mode="point", trade_date=date(2026, 8, 14)),
        open_dates=[date(2026, 8, 14)],
    )
    normalized = (
        DatasetNormalizer()
        .normalize(
            definition=definition,
            fetch_result=SourceFetchResult(
                unit_id="daily-prewrite",
                request_count=1,
                retry_count=0,
                latency_ms=1,
                rows_raw=[_source_row("850412.SI")],
            ),
            expected_unit_date=date(2026, 8, 14),
        )
        .rows_normalized
    )
    validator = get_pre_write_validator("sw2021_daily_scope")
    validator(daily_session, normalized, definition, plan.units[0])

    production_rounding_sample = deepcopy(normalized)
    production_rounding_sample[0].update(
        {
            "open": 2490.93,
            "low": 2485.29,
            "high": 2513.36,
            "close": 2513.37,
        }
    )
    validator(daily_session, production_rounding_sample, definition, plan.units[0])
    assert production_rounding_sample[0]["high"] == 2513.36
    assert production_rounding_sample[0]["close"] == 2513.37

    same_integer_without_fixed_decimal_tolerance = deepcopy(normalized)
    same_integer_without_fixed_decimal_tolerance[0].update(
        {
            "open": 2490.93,
            "low": 2485.29,
            "high": 2513.01,
            "close": 2513.49,
        }
    )
    validator(
        daily_session,
        same_integer_without_fixed_decimal_tolerance,
        definition,
        plan.units[0],
    )
    same_integer_lower_boundary = deepcopy(normalized)
    same_integer_lower_boundary[0].update(
        {
            "open": 2485.01,
            "low": 2485.49,
            "high": 2513.0,
            "close": 2490.0,
        }
    )
    validator(
        daily_session,
        same_integer_lower_boundary,
        definition,
        plan.units[0],
    )

    cases: list[tuple[list[dict], str]] = []
    wrong_version = deepcopy(normalized)
    wrong_version[0]["classification_version"] = "SW2014"
    cases.append((wrong_version, "只能写入 SW2021"))
    bad_ohlc = deepcopy(normalized)
    bad_ohlc[0]["low"] = 103.0
    cases.append((bad_ohlc, "OHLC 关系非法"))
    half_up_integer_boundary = deepcopy(normalized)
    half_up_integer_boundary[0].update(
        {
            "open": 2490.93,
            "low": 2485.29,
            "high": 2513.49,
            "close": 2513.50,
        }
    )
    cases.append((half_up_integer_boundary, "OHLC 关系非法"))
    half_up_lower_boundary = deepcopy(normalized)
    half_up_lower_boundary[0].update(
        {
            "open": 2485.49,
            "low": 2485.50,
            "high": 2513.0,
            "close": 2490.0,
        }
    )
    cases.append((half_up_lower_boundary, "OHLC 关系非法"))
    for field_name in ("vol", "amount", "float_mv", "total_mv"):
        negative = deepcopy(normalized)
        negative[0][field_name] = -1.0
        cases.append((negative, f"字段 {field_name} 不得为负"))
    wrong_date = deepcopy(normalized)
    wrong_date[0]["trade_date"] = date(2026, 8, 13)
    cases.append((wrong_date, "日期与执行单元不一致"))

    for rows, message in cases:
        with pytest.raises(PreWriteValidationError, match=message):
            validator(daily_session, rows, definition, plan.units[0])


def test_sw_daily_executor_replaces_only_one_day_and_is_atomic_and_idempotent(
    daily_session: Session,
    mocker,
) -> None:
    definition = get_dataset_definition("sw_daily")
    plan, _ = _plan(
        mocker,
        time_input=DatasetTimeInput(mode="point", trade_date=date(2026, 8, 14)),
        open_dates=[date(2026, 8, 14)],
    )
    daily_session.add_all(
        [
            SwIndustryDaily(
                **DatasetNormalizer()
                .normalize(
                    definition=definition,
                    fetch_result=SourceFetchResult(
                        unit_id="seed-previous",
                        request_count=1,
                        retry_count=0,
                        latency_ms=1,
                        rows_raw=[_source_row("880999.SI", trade_date="20260813")],
                    ),
                    expected_unit_date=date(2026, 8, 13),
                )
                .rows_normalized[0]
            ),
            SwIndustryDaily(
                **DatasetNormalizer()
                .normalize(
                    definition=definition,
                    fetch_result=SourceFetchResult(
                        unit_id="seed-ghost",
                        request_count=1,
                        retry_count=0,
                        latency_ms=1,
                        rows_raw=[_source_row("880998.SI")],
                    ),
                    expected_unit_date=date(2026, 8, 14),
                )
                .rows_normalized[0]
            ),
        ]
    )
    daily_session.commit()

    connector = _DailyConnector(_full_market_rows())
    mocker.patch(
        "src.foundation.ingestion.source_client.create_source_connector",
        return_value=connector,
    )
    first = IngestionExecutor(daily_session).run(
        request=_validated_request(plan),
        definition=definition,
        units=plan.units,
    )
    assert first.rows_fetched == 439
    assert first.rows_written == first.rows_committed == 439
    assert first.rows_rejected == 0
    assert first.unit_done == 1
    assert (
        daily_session.scalar(
            select(func.count())
            .select_from(SwIndustryDaily)
            .where(SwIndustryDaily.trade_date == date(2026, 8, 14))
        )
        == 439
    )
    assert (
        daily_session.scalar(
            select(func.count())
            .select_from(SwIndustryDaily)
            .where(
                SwIndustryDaily.trade_date == date(2026, 8, 14),
                SwIndustryDaily.ts_code.like("99%"),
            )
        )
        == 25
    )
    assert (
        daily_session.scalar(
            select(func.count())
            .select_from(SwIndustryDaily)
            .where(SwIndustryDaily.trade_date == date(2026, 8, 13))
        )
        == 1
    )

    first_readback = list(
        daily_session.execute(
            select(
                SwIndustryDaily.ts_code,
                SwIndustryDaily.trade_date,
                SwIndustryDaily.close,
                SwIndustryDaily.pe,
            )
            .where(SwIndustryDaily.trade_date == date(2026, 8, 14))
            .order_by(SwIndustryDaily.ts_code)
        ).all()
    )
    replay = IngestionExecutor(daily_session).run(
        request=_validated_request(plan),
        definition=definition,
        units=plan.units,
    )
    replay_readback = list(
        daily_session.execute(
            select(
                SwIndustryDaily.ts_code,
                SwIndustryDaily.trade_date,
                SwIndustryDaily.close,
                SwIndustryDaily.pe,
            )
            .where(SwIndustryDaily.trade_date == date(2026, 8, 14))
            .order_by(SwIndustryDaily.ts_code)
        ).all()
    )
    assert replay.rows_written == replay.rows_committed == 439
    assert replay_readback == first_readback

    rejected_rows = _full_market_rows()
    rejected_rows[-1]["ts_code"] = "840401.SI"
    connector.rows = rejected_rows
    with pytest.raises(IngestionWriteError) as rejected:
        IngestionExecutor(daily_session).run(
            request=_validated_request(plan),
            definition=definition,
            units=plan.units,
        )
    assert rejected.value.structured_error.error_code == "write.scope_rows_rejected"
    assert (
        list(
            daily_session.execute(
                select(
                    SwIndustryDaily.ts_code,
                    SwIndustryDaily.trade_date,
                    SwIndustryDaily.close,
                    SwIndustryDaily.pe,
                )
                .where(SwIndustryDaily.trade_date == date(2026, 8, 14))
                .order_by(SwIndustryDaily.ts_code)
            ).all()
        )
        == first_readback
    )

    invalid_ohlc = _full_market_rows()
    invalid_ohlc[0]["low"] = 103.0
    connector.rows = invalid_ohlc
    with pytest.raises(IngestionWriteError) as invalid:
        IngestionExecutor(daily_session).run(
            request=_validated_request(plan),
            definition=definition,
            units=plan.units,
        )
    assert invalid.value.structured_error.error_code == "write.scope_preflight_failed"
    assert (
        daily_session.scalar(
            select(func.count())
            .select_from(SwIndustryDaily)
            .where(SwIndustryDaily.trade_date == date(2026, 8, 14))
        )
        == 439
    )

    connector.rows = []
    with pytest.raises(IngestionWriteError) as empty:
        IngestionExecutor(daily_session).run(
            request=_validated_request(plan),
            definition=definition,
            units=plan.units,
        )
    assert empty.value.structured_error.error_code == "write.scope_empty"
    assert (
        daily_session.scalar(
            select(func.count())
            .select_from(SwIndustryDaily)
            .where(SwIndustryDaily.trade_date == date(2026, 8, 14))
        )
        == 439
    )


def test_sw_daily_ops_projection_is_manual_open_day_date_bucket() -> None:
    route = ManualActionQueryService().get_action_route("sw_daily.maintain")
    assert route is not None
    assert route.group_key == "board_theme"
    assert route.action_order == 100
    assert route.filters == ()
    assert route.time_form.default_mode == "point"
    assert route.time_form.max_units_per_execution == 60
    assert [mode.mode for mode in route.time_form.modes] == ["point", "range"]
    assert all(
        mode.selection_rule == "trading_day_only" for mode in route.time_form.modes
    )

    projection = get_dataset_freshness_projection("sw_daily")
    assert projection is not None
    assert projection.target_table == "core_serving.sw_industry_daily"
    assert projection.raw_table is None
    assert projection.freshness_policy == "continuous_open_day"
    assert projection.observed_date_column == "trade_date"
    assert projection.primary_action_key == "sw_daily.maintain"

    definition = get_dataset_definition("sw_daily")
    assert definition.completeness.scope == "date_bucket"
    assert definition.completeness.actual_key_fields == ()
    assert definition.date_model.observed_field == "trade_date"
    assert definition.date_model.audit_applicable is True
    assert definition.capabilities.get_action("maintain").schedule_enabled is False
    assert (
        ScheduleAutomationCapabilityResolver().resolve(
            target_type="dataset_action",
            target_key="sw_daily.maintain",
        )
        is None
    )
