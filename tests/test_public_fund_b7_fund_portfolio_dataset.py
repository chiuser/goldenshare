from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from src.foundation.dao.factory import DAOFactory
from src.foundation.dao.fund_portfolio_dao import FundPortfolioDAO, FundPortfolioDAOError
from src.foundation.datasets.public_fund_contracts import (
    FUND_PORTFOLIO_IDENTITY_FIELDS,
    FUND_PORTFOLIO_SOURCE_FIELDS,
)
from src.foundation.datasets.registry import get_dataset_definition
from src.foundation.ingestion.errors import (
    IngestionError,
    IngestionNormalizeError,
    IngestionPlanningError,
    IngestionValidationError,
    IngestionWriteError,
    StructuredError,
)
from src.foundation.ingestion.execution_plan import (
    DatasetActionRequest,
    DatasetTimeInput,
    PlanUnitSnapshot,
    ValidatedDatasetActionRequest,
)
from src.foundation.ingestion.executor import IngestionExecutor
from src.foundation.ingestion.linter import lint_all_dataset_definitions
from src.foundation.ingestion.normalizer import DatasetNormalizer
from src.foundation.ingestion.resolver import DatasetActionResolver
from src.foundation.ingestion.run_errors import IngestionCanceledError
from src.foundation.ingestion.source_client import (
    DatasetSourceClient,
    SourceFetchResult,
    SourcePageResult,
)
from src.foundation.models.core_serving.fund_portfolio import FundPortfolio
from src.foundation.models.staging.fund_portfolio_stage import FundPortfolioStage
from src.foundation.models.table_model_registry import table_model_registry
from src.ops.action_catalog import list_workflow_definitions
from src.ops.catalog.dataset_catalog_views import OPS_DATASET_DEFAULT_VIEW
from src.ops.queries.manual_action_query_service import ManualActionQueryService
from src.ops.services.dataset_schedule_time_policy_resolver import DatasetScheduleTimePolicyResolver
from src.ops.services.task_run_service import TaskRunCommandService


def _request(*, mode: str, trade_date: date | None = None, start_date: date | None = None, end_date: date | None = None, filters=None):
    return DatasetActionRequest(
        dataset_key="fund_portfolio",
        action="maintain",
        time_input=DatasetTimeInput(mode=mode, trade_date=trade_date, start_date=start_date, end_date=end_date),
        filters=dict(filters or {}),
    )


def _row(*, ts_code: str = "000001.OF", symbol: str = "600000.SH", mkv: str = "100.25") -> dict:
    return {
        "ts_code": ts_code,
        "ann_date": "20250720",
        "end_date": "20250630",
        "symbol": symbol,
        "mkv": mkv,
        "amount": "10",
        "stk_mkv_ratio": "1.25",
        "stk_float_ratio": "0.0001",
    }


def _normalized_row(*, ts_code: str = "000001.OF", symbol: str = "600000.SH", mkv: str = "100.25") -> dict:
    return {
        "ts_code": ts_code,
        "ann_date": date(2025, 7, 20),
        "end_date": date(2025, 6, 30),
        "symbol": symbol,
        "mkv": Decimal(mkv),
        "amount": Decimal("10"),
        "stk_mkv_ratio": Decimal("1.25"),
        "stk_float_ratio": Decimal("0.0001"),
    }


def _sqlite_session_with_fund_portfolio_tables() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    connection = engine.connect()
    connection.exec_driver_sql("ATTACH DATABASE ':memory:' AS core_serving")
    connection.exec_driver_sql("ATTACH DATABASE ':memory:' AS foundation")
    FundPortfolio.__table__.create(connection)
    FundPortfolioStage.__table__.create(connection)
    # Close the connection-owned DDL transaction before the Session starts.
    # Otherwise a later Session.rollback() also rolls back rows that an earlier
    # Session.commit() appeared to publish in SQLite's attached databases.
    connection.commit()
    return Session(bind=connection)


def test_fund_portfolio_definition_freezes_fields_staged_contract_and_lint() -> None:
    definition = get_dataset_definition("fund_portfolio")
    assert definition.source.source_fields == FUND_PORTFOLIO_SOURCE_FIELDS
    assert definition.date_model.selection_rule() == "quarter_end"
    assert definition.date_model.observed_field == "end_date"
    assert definition.date_model.audit_applicable is False
    assert definition.planning.pagination_policy == "offset_limit"
    assert definition.planning.page_limit == 2_000
    assert definition.planning.max_units_per_execution == 8
    assert definition.planning.fetch_concurrency == 1
    assert definition.planning.page_processing_mode == "staged_stream"
    assert definition.storage.write_path == "serving_staged_immutable_scope_publish"
    assert definition.storage.conflict_columns == FUND_PORTFOLIO_IDENTITY_FIELDS
    assert definition.storage.stage_table == "foundation.fund_portfolio_stage"
    assert lint_all_dataset_definitions().passed is True


def test_fund_portfolio_point_and_range_plan_only_natural_quarter_ends() -> None:
    session = Session(create_engine("sqlite+pysqlite:///:memory:"))
    resolver = DatasetActionResolver(session)
    point = resolver.build_plan(_request(mode="point", trade_date=date(2025, 6, 30)))
    assert len(point.units) == 1
    assert point.units[0].request_params == {"period": "20250630"}
    assert point.units[0].page_limit == 2_000

    range_plan = resolver.build_plan(
        _request(mode="range", start_date=date(2014, 1, 1), end_date=date(2014, 12, 31))
    )
    assert [unit.request_params["period"] for unit in range_plan.units] == [
        "20140331",
        "20140630",
        "20140930",
        "20141231",
    ]

    eight_quarters = resolver.build_plan(
        _request(mode="range", start_date=date(2014, 1, 1), end_date=date(2015, 12, 31))
    )
    assert [unit.request_params["period"] for unit in eight_quarters.units] == [
        "20140331",
        "20140630",
        "20140930",
        "20141231",
        "20150331",
        "20150630",
        "20150930",
        "20151231",
    ]

    with pytest.raises(IngestionValidationError) as invalid_point:
        resolver.build_plan(_request(mode="point", trade_date=date(2025, 6, 29)))
    assert invalid_point.value.structured_error.error_code == "quarter_end_required"
    with pytest.raises(IngestionPlanningError) as empty_range:
        resolver.build_plan(_request(mode="range", start_date=date(2014, 4, 1), end_date=date(2014, 6, 29)))
    assert empty_range.value.structured_error.error_code == "quarter_end_required"
    with pytest.raises(IngestionPlanningError) as too_many:
        resolver.build_plan(_request(mode="range", start_date=date(2014, 1, 1), end_date=date(2016, 3, 31)))
    assert too_many.value.structured_error.error_code == "units_exceeded"
    assert too_many.value.structured_error.details == {
        "planned_units": 9,
        "max_units_per_execution": 8,
    }


def test_fund_portfolio_scoped_repair_requires_safe_single_code_point_and_existing_period() -> None:
    session = _sqlite_session_with_fund_portfolio_tables()
    resolver = DatasetActionResolver(session)
    with pytest.raises(IngestionPlanningError) as missing:
        resolver.build_plan(_request(mode="point", trade_date=date(2025, 6, 30), filters={"ts_code": "000001.OF"}))
    assert missing.value.structured_error.error_code == "scoped_repair_scope_missing"

    session.execute(FundPortfolio.__table__.insert(), {**_normalized_row(), "source_content_hash": "a" * 64})
    session.commit()
    plan = resolver.build_plan(
        _request(mode="point", trade_date=date(2025, 6, 30), filters={"ts_code": " 000001.of "})
    )
    assert plan.units[0].request_params == {"period": "20250630", "ts_code": "000001.OF"}

    with pytest.raises(IngestionPlanningError) as range_repair:
        resolver.build_plan(
            _request(
                mode="range",
                start_date=date(2025, 3, 31),
                end_date=date(2025, 6, 30),
                filters={"ts_code": "000001.OF"},
            )
        )
    assert range_repair.value.structured_error.error_code == "scoped_repair_point_required"
    with pytest.raises(IngestionPlanningError) as invalid_code:
        resolver.build_plan(_request(mode="point", trade_date=date(2025, 6, 30), filters={"ts_code": "000001.OF,000002.OF"}))
    assert invalid_code.value.structured_error.error_code == "scoped_repair_code_invalid"


def test_source_page_iterator_requests_explicit_fields_and_fetches_terminal_empty_page(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    definition = get_dataset_definition("fund_portfolio")
    calls: list[tuple[dict, tuple[str, ...]]] = []

    class Connector:
        def call(self, *, api_name, params, fields):  # type: ignore[no-untyped-def]
            assert api_name == "fund_portfolio"
            calls.append((dict(params), tuple(fields)))
            if params["offset"] == 0:
                return [{"row": index} for index in range(2_000)]
            return []

    monkeypatch.setattr("src.foundation.ingestion.source_client.create_source_connector", lambda _key: Connector())
    unit = PlanUnitSnapshot(
        unit_id="fund_portfolio:20250630",
        dataset_key="fund_portfolio",
        source_key="tushare",
        trade_date=date(2025, 6, 30),
        request_params={"period": "20250630"},
        progress_context={},
        pagination_policy="offset_limit",
        page_limit=2_000,
    )
    pages = list(DatasetSourceClient().iter_pages(definition=definition, unit=unit))
    assert [page.offset for page in pages] == [0, 2_000]
    assert [len(page.rows_raw) for page in pages] == [2_000, 0]
    assert pages[-1].is_short_page is True
    assert all(fields == FUND_PORTFOLIO_SOURCE_FIELDS for _params, fields in calls)
    assert all(params["period"] == "20250630" and params["limit"] == 2_000 for params, _fields in calls)


def test_fund_portfolio_normalization_preserves_all_fields_and_fails_identity_conflict() -> None:
    definition = get_dataset_definition("fund_portfolio")
    normalizer = DatasetNormalizer()
    batch = normalizer.normalize(
        definition=definition,
        fetch_result=SourceFetchResult(
            unit_id="u1",
            request_count=1,
            retry_count=0,
            latency_ms=1,
            rows_raw=[_row(), _row()],
        ),
        expected_unit_date=date(2025, 6, 30),
    )
    assert batch.rows_deduplicated == 1
    assert set(FUND_PORTFOLIO_SOURCE_FIELDS).issubset(batch.rows_normalized[0])
    assert batch.rows_normalized[0]["mkv"] == Decimal("100.25")

    with pytest.raises(IngestionNormalizeError) as conflict:
        normalizer.normalize(
            definition=definition,
            fetch_result=SourceFetchResult(
                unit_id="u2",
                request_count=1,
                retry_count=0,
                latency_ms=1,
                rows_raw=[_row(), _row(mkv="101.25")],
            ),
            expected_unit_date=date(2025, 6, 30),
        )
    assert conflict.value.structured_error.error_code == "normalize.batch_unique_key_conflicting"


def test_staged_executor_streams_pages_and_only_counts_rows_after_finalize(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    definition = get_dataset_definition("fund_portfolio")
    plan = DatasetActionResolver(Session(create_engine("sqlite+pysqlite:///:memory:"))).build_plan(
        _request(mode="point", trade_date=date(2025, 6, 30))
    )
    request = ValidatedDatasetActionRequest(
        request_id="b7-success",
        dataset_key="fund_portfolio",
        action="maintain",
        run_profile="point_incremental",
        trigger_source="manual",
        trade_date=date(2025, 6, 30),
    )
    pages = [
        SourcePageResult(
            unit_id=plan.units[0].unit_id,
            page_number=1,
            offset=0,
            rows_raw=[_row()],
            retry_count=1,
            latency_ms=1,
            is_short_page=False,
        ),
        SourcePageResult(
            unit_id=plan.units[0].unit_id,
            page_number=2,
            offset=2_000,
            rows_raw=[_row(ts_code="000002.OF", symbol="000001.SZ")],
            retry_count=0,
            latency_ms=1,
            is_short_page=True,
        ),
    ]
    snapshots = []

    class FakePublisher:
        instance = None

        def __init__(self, **_kwargs) -> None:  # type: ignore[no-untyped-def]
            self.stage_calls: list[dict] = []
            self.finalize_calls: list[dict] = []
            FakePublisher.instance = self

        def __enter__(self):  # type: ignore[no-untyped-def]
            return self

        def __exit__(self, *_args) -> bool:  # type: ignore[no-untyped-def]
            return False

        def begin_unit(self):  # type: ignore[no-untyped-def]
            return uuid4()

        def stage_page(self, **kwargs):  # type: ignore[no-untyped-def]
            self.stage_calls.append(dict(kwargs))
            return SimpleNamespace(rows_staged=1, rows_deduplicated=0)

        def finalize_unit(self, **kwargs):  # type: ignore[no-untyped-def]
            self.finalize_calls.append(dict(kwargs))
            return SimpleNamespace(
                rows_source_unique=2,
                rows_inserted=2,
                rows_matched=0,
                final_scope_count=2,
            )

    monkeypatch.setattr("src.foundation.ingestion.executor.StagedStreamPublisher", FakePublisher)
    executor = IngestionExecutor(Session(create_engine("sqlite+pysqlite:///:memory:")))
    monkeypatch.setattr(
        executor.source_client, "iter_pages", lambda **_kwargs: iter(pages)
    )
    summary = executor.run(
        request=request,
        definition=definition,
        units=plan.units,
        progress_reporter=lambda snapshot, _message: snapshots.append(snapshot),
    )

    assert len(FakePublisher.instance.stage_calls) == 2
    assert len(FakePublisher.instance.finalize_calls) == 1
    assert (summary.rows_fetched, summary.rows_written, summary.rows_committed) == (2, 2, 2)
    pagination = summary.ingestion_diagnostics["source"]["pagination"]
    assert (pagination["total_page_count"], pagination["total_retry_count"]) == (2, 1)
    persistence = summary.ingestion_diagnostics["persistence"]["immutable_fact"]
    assert persistence["rows_normalized_before_dedupe"] == 2
    assert persistence["final_scope_count"] == 2
    assert [
        snapshot.ingestion_diagnostics["runtime"]["paged_unit"]["active"]["phase"]
        if snapshot.ingestion_diagnostics["runtime"]["paged_unit"]["active"] is not None
        else "completed"
        for snapshot in snapshots
    ] == [
        "processing_page",
        "processing_page",
        "reconciling",
        "publishing",
        "completed",
    ]
    page_two = snapshots[1]
    assert page_two.unit_done == 0
    assert page_two.rows_fetched == 1
    assert page_two.rows_committed == 0
    assert page_two.ingestion_diagnostics["runtime"]["paged_unit"]["active"] == {
        "unit_id": plan.units[0].unit_id,
        "unit_index": 1,
        "unit_total": 1,
        "time": {"field": "end_date", "point": "2025-06-30"},
        "phase": "processing_page",
        "current_page_number": 2,
        "completed_page_count": 1,
        "page_limit": 2_000,
        "unit_rows_fetched": 1,
        "unit_rows_normalized_before_dedupe": 1,
        "unit_rows_staged_unique": 1,
        "unit_rows_deduplicated": 0,
        "unit_rows_rejected": 0,
        "retry_count": 1,
        "observed_short_page": False,
        "terminal_page_rows": None,
    }
    completed = snapshots[-1].ingestion_diagnostics["runtime"]["paged_unit"]
    assert completed["active"] is None
    assert completed["completed"] == [
        {
            "unit_id": plan.units[0].unit_id,
            "unit_index": 1,
            "time": {"field": "end_date", "point": "2025-06-30"},
            "page_count": 2,
            "retry_count": 1,
            "terminal_page_rows": 1,
            "observed_short_page": True,
            "rows_fetched": 2,
            "rows_normalized_before_dedupe": 2,
            "rows_staged_unique": 2,
            "rows_deduplicated": 0,
            "rows_rejected": 0,
            "rows_inserted_new": 2,
            "rows_matched_existing": 0,
            "rows_committed": 2,
            "final_scope_count": 2,
        }
    ]


def test_staged_executor_finalize_failure_reports_zero_committed(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    definition = get_dataset_definition("fund_portfolio")
    plan = DatasetActionResolver(Session(create_engine("sqlite+pysqlite:///:memory:"))).build_plan(
        _request(mode="point", trade_date=date(2025, 6, 30))
    )
    request = ValidatedDatasetActionRequest(
        request_id="b7-failure",
        dataset_key="fund_portfolio",
        action="maintain",
        run_profile="point_incremental",
        trigger_source="manual",
        trade_date=date(2025, 6, 30),
    )
    page = SourcePageResult(
        unit_id=plan.units[0].unit_id,
        page_number=1,
        offset=0,
        rows_raw=[_row()],
        retry_count=0,
        latency_ms=1,
        is_short_page=True,
    )
    snapshots = []

    class FailingPublisher:
        def __init__(self, **_kwargs) -> None:  # type: ignore[no-untyped-def]
            pass

        def __enter__(self):  # type: ignore[no-untyped-def]
            return self

        def __exit__(self, *_args) -> bool:  # type: ignore[no-untyped-def]
            return False

        def begin_unit(self):  # type: ignore[no-untyped-def]
            return uuid4()

        def stage_page(self, **_kwargs):  # type: ignore[no-untyped-def]
            return SimpleNamespace(rows_staged=1, rows_deduplicated=0)

        def finalize_unit(self, **_kwargs):  # type: ignore[no-untyped-def]
            raise IngestionWriteError(
                StructuredError(
                    error_code="write.immutable_content_conflict",
                    error_type="write",
                    phase="staged_publisher",
                    message="conflict",
                    retryable=False,
                )
            )

    monkeypatch.setattr("src.foundation.ingestion.executor.StagedStreamPublisher", FailingPublisher)
    executor = IngestionExecutor(Session(create_engine("sqlite+pysqlite:///:memory:")))
    monkeypatch.setattr(executor.source_client, "iter_pages", lambda **_kwargs: iter([page]))

    with pytest.raises(IngestionWriteError):
        executor.run(
            request=request,
            definition=definition,
            units=plan.units,
            progress_reporter=lambda snapshot, _message: snapshots.append(snapshot),
        )
    assert snapshots[-1].rows_fetched == 1
    assert snapshots[-1].rows_written == 0
    assert snapshots[-1].rows_committed == 0
    paged_unit = snapshots[-1].ingestion_diagnostics["runtime"]["paged_unit"]
    assert paged_unit["active"]["phase"] == "failed"
    assert paged_unit["active"]["completed_page_count"] == 1
    assert paged_unit["active"]["unit_rows_fetched"] == 1
    assert paged_unit["completed"] == []


def test_staged_executor_keeps_completed_quarter_while_next_quarter_is_active(
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    definition = get_dataset_definition("fund_portfolio")
    plan = DatasetActionResolver(
        Session(create_engine("sqlite+pysqlite:///:memory:"))
    ).build_plan(
        _request(mode="range", start_date=date(2025, 3, 31), end_date=date(2025, 6, 30))
    )
    request = ValidatedDatasetActionRequest(
        request_id="b7-two-quarters",
        dataset_key="fund_portfolio",
        action="maintain",
        run_profile="range_rebuild",
        trigger_source="manual",
        start_date=date(2025, 3, 31),
        end_date=date(2025, 6, 30),
    )
    snapshots = []

    class FakePublisher:
        def __init__(self, **_kwargs) -> None:  # type: ignore[no-untyped-def]
            pass

        def __enter__(self):  # type: ignore[no-untyped-def]
            return self

        def __exit__(self, *_args) -> bool:  # type: ignore[no-untyped-def]
            return False

        def begin_unit(self):  # type: ignore[no-untyped-def]
            return uuid4()

        def stage_page(self, **_kwargs):  # type: ignore[no-untyped-def]
            return SimpleNamespace(rows_staged=1, rows_deduplicated=0)

        def finalize_unit(self, **_kwargs):  # type: ignore[no-untyped-def]
            return SimpleNamespace(
                rows_source_unique=1,
                rows_inserted=1,
                rows_matched=0,
                final_scope_count=1,
            )

    def iter_pages(*, unit, **_kwargs):  # type: ignore[no-untyped-def]
        row = _row()
        row["end_date"] = unit.trade_date.strftime("%Y%m%d")
        return iter(
            [
                SourcePageResult(
                    unit_id=unit.unit_id,
                    page_number=1,
                    offset=0,
                    rows_raw=[row],
                    retry_count=0,
                    latency_ms=1,
                    is_short_page=True,
                )
            ]
        )

    monkeypatch.setattr(
        "src.foundation.ingestion.executor.StagedStreamPublisher", FakePublisher
    )
    executor = IngestionExecutor(Session(create_engine("sqlite+pysqlite:///:memory:")))
    monkeypatch.setattr(executor.source_client, "iter_pages", iter_pages)

    summary = executor.run(
        request=request,
        definition=definition,
        units=plan.units,
        progress_reporter=lambda snapshot, _message: snapshots.append(snapshot),
    )

    second_quarter_started = next(
        snapshot
        for snapshot in snapshots
        if snapshot.ingestion_diagnostics["runtime"]["paged_unit"]["active"]
        and snapshot.ingestion_diagnostics["runtime"]["paged_unit"]["active"][
            "unit_index"
        ]
        == 2
    )
    paged_unit = second_quarter_started.ingestion_diagnostics["runtime"]["paged_unit"]
    assert second_quarter_started.unit_done == 1
    assert second_quarter_started.rows_fetched == 1
    assert paged_unit["active"]["unit_rows_fetched"] == 0
    assert [item["unit_index"] for item in paged_unit["completed"]] == [1]
    assert summary.unit_done == 2
    assert summary.ingestion_diagnostics["runtime"]["paged_unit"]["active"] is None
    assert [
        item["unit_index"]
        for item in summary.ingestion_diagnostics["runtime"]["paged_unit"]["completed"]
    ] == [1, 2]


def test_staged_executor_source_failure_freezes_last_page_without_completed_result(
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    definition = get_dataset_definition("fund_portfolio")
    plan = DatasetActionResolver(
        Session(create_engine("sqlite+pysqlite:///:memory:"))
    ).build_plan(_request(mode="point", trade_date=date(2025, 6, 30)))
    request = ValidatedDatasetActionRequest(
        request_id="b7-source-failure",
        dataset_key="fund_portfolio",
        action="maintain",
        run_profile="point_incremental",
        trigger_source="manual",
        trade_date=date(2025, 6, 30),
    )
    snapshots = []

    class FakePublisher:
        def __init__(self, **_kwargs) -> None:  # type: ignore[no-untyped-def]
            pass

        def __enter__(self):  # type: ignore[no-untyped-def]
            return self

        def __exit__(self, *_args) -> bool:  # type: ignore[no-untyped-def]
            return False

        def begin_unit(self):  # type: ignore[no-untyped-def]
            return uuid4()

        def stage_page(self, **_kwargs):  # type: ignore[no-untyped-def]
            return SimpleNamespace(rows_staged=1, rows_deduplicated=0)

        def finalize_unit(self, **_kwargs):  # type: ignore[no-untyped-def]
            raise AssertionError("source 失败后不得发布")

    def failing_pages():
        yield SourcePageResult(
            unit_id=plan.units[0].unit_id,
            page_number=1,
            offset=0,
            rows_raw=[_row()],
            retry_count=0,
            latency_ms=1,
            is_short_page=False,
        )
        raise RuntimeError("source failed on page 2")

    monkeypatch.setattr(
        "src.foundation.ingestion.executor.StagedStreamPublisher", FakePublisher
    )
    executor = IngestionExecutor(Session(create_engine("sqlite+pysqlite:///:memory:")))
    monkeypatch.setattr(
        executor.source_client, "iter_pages", lambda **_kwargs: failing_pages()
    )

    with pytest.raises(IngestionError):
        executor.run(
            request=request,
            definition=definition,
            units=plan.units,
            progress_reporter=lambda snapshot, _message: snapshots.append(snapshot),
        )

    final = snapshots[-1]
    active = final.ingestion_diagnostics["runtime"]["paged_unit"]["active"]
    assert final.rows_fetched == 1
    assert final.rows_committed == 0
    assert active["phase"] == "failed"
    assert active["current_page_number"] == 2
    assert active["completed_page_count"] == 1
    assert active["unit_rows_fetched"] == 1
    assert final.ingestion_diagnostics["runtime"]["paged_unit"]["completed"] == []


@pytest.mark.parametrize("failure_kind", ["normalize", "stage"])
def test_staged_executor_page_failure_does_not_count_unstaged_page_as_completed(
    monkeypatch,
    failure_kind: str,
) -> None:  # type: ignore[no-untyped-def]
    definition = get_dataset_definition("fund_portfolio")
    plan = DatasetActionResolver(
        Session(create_engine("sqlite+pysqlite:///:memory:"))
    ).build_plan(_request(mode="point", trade_date=date(2025, 6, 30)))
    request = ValidatedDatasetActionRequest(
        request_id=f"b7-{failure_kind}-failure",
        dataset_key="fund_portfolio",
        action="maintain",
        run_profile="point_incremental",
        trigger_source="manual",
        trade_date=date(2025, 6, 30),
    )
    snapshots = []

    class FakePublisher:
        def __init__(self, **_kwargs) -> None:  # type: ignore[no-untyped-def]
            pass

        def __enter__(self):  # type: ignore[no-untyped-def]
            return self

        def __exit__(self, *_args) -> bool:  # type: ignore[no-untyped-def]
            return False

        def begin_unit(self):  # type: ignore[no-untyped-def]
            return uuid4()

        def stage_page(self, **_kwargs):  # type: ignore[no-untyped-def]
            if failure_kind == "stage":
                raise IngestionWriteError(
                    StructuredError(
                        error_code="stage_page_failed",
                        error_type="write",
                        phase="writer",
                        message="stage failed",
                        retryable=False,
                    )
                )
            return SimpleNamespace(rows_staged=1, rows_deduplicated=0)

        def finalize_unit(self, **_kwargs):  # type: ignore[no-untyped-def]
            raise AssertionError("分页失败后不得发布")

    row = _row()
    if failure_kind == "normalize":
        row["end_date"] = "20250331"

    monkeypatch.setattr(
        "src.foundation.ingestion.executor.StagedStreamPublisher", FakePublisher
    )
    executor = IngestionExecutor(Session(create_engine("sqlite+pysqlite:///:memory:")))
    monkeypatch.setattr(
        executor.source_client,
        "iter_pages",
        lambda **_kwargs: iter(
            [
                SourcePageResult(
                    unit_id=plan.units[0].unit_id,
                    page_number=1,
                    offset=0,
                    rows_raw=[row],
                    retry_count=0,
                    latency_ms=1,
                    is_short_page=True,
                )
            ]
        ),
    )

    with pytest.raises(IngestionError):
        executor.run(
            request=request,
            definition=definition,
            units=plan.units,
            progress_reporter=lambda snapshot, _message: snapshots.append(snapshot),
        )

    final = snapshots[-1]
    active = final.ingestion_diagnostics["runtime"]["paged_unit"]["active"]
    assert final.rows_fetched == 1
    assert final.rows_committed == 0
    assert active["phase"] == "failed"
    assert active["current_page_number"] == 1
    assert active["completed_page_count"] == 0
    assert active["unit_rows_fetched"] == 1
    assert final.ingestion_diagnostics["runtime"]["paged_unit"]["completed"] == []


def test_staged_executor_cancellation_freezes_initial_page(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    definition = get_dataset_definition("fund_portfolio")
    plan = DatasetActionResolver(
        Session(create_engine("sqlite+pysqlite:///:memory:"))
    ).build_plan(_request(mode="point", trade_date=date(2025, 6, 30)))
    request = ValidatedDatasetActionRequest(
        request_id="b7-canceled",
        dataset_key="fund_portfolio",
        action="maintain",
        run_profile="point_incremental",
        trigger_source="manual",
        trade_date=date(2025, 6, 30),
        run_id=99,
    )
    snapshots = []

    class FakePublisher:
        def __init__(self, **_kwargs) -> None:  # type: ignore[no-untyped-def]
            pass

        def __enter__(self):  # type: ignore[no-untyped-def]
            return self

        def __exit__(self, *_args) -> bool:  # type: ignore[no-untyped-def]
            return False

        def begin_unit(self):  # type: ignore[no-untyped-def]
            return uuid4()

    monkeypatch.setattr(
        "src.foundation.ingestion.executor.StagedStreamPublisher", FakePublisher
    )
    executor = IngestionExecutor(Session(create_engine("sqlite+pysqlite:///:memory:")))

    with pytest.raises(IngestionCanceledError):
        executor.run(
            request=request,
            definition=definition,
            units=plan.units,
            progress_reporter=lambda snapshot, _message: snapshots.append(snapshot),
            cancel_checker=lambda _run_id: True,
        )

    active = snapshots[-1].ingestion_diagnostics["runtime"]["paged_unit"]["active"]
    assert active["phase"] == "canceled"
    assert active["current_page_number"] == 1
    assert active["completed_page_count"] == 0
    assert active["unit_rows_fetched"] == 0


def test_fund_portfolio_stage_dao_deduplicates_cross_page_and_atomically_reconciles() -> None:
    session = _sqlite_session_with_fund_portfolio_tables()
    dao = FundPortfolioDAO(session)
    period = date(2025, 6, 30)
    stage_run_id = uuid4()
    rows = [_normalized_row(), _normalized_row(ts_code="000002.OF", symbol="000001.SZ")]
    first = dao.stage_page(stage_run_id=stage_run_id, period=period, repair_ts_code=None, rows=rows)
    session.commit()
    duplicate = dao.stage_page(stage_run_id=stage_run_id, period=period, repair_ts_code=None, rows=[rows[0]])
    session.commit()
    assert first.rows_staged == 2
    assert duplicate.rows_staged == 0
    assert duplicate.rows_deduplicated == 1

    finalized = dao.finalize_scope(stage_run_id=stage_run_id, period=period, repair_ts_code=None)
    session.commit()
    assert (finalized.rows_source_unique, finalized.rows_inserted, finalized.rows_matched, finalized.final_scope_count) == (2, 2, 0, 2)

    rerun_id = uuid4()
    dao.stage_page(stage_run_id=rerun_id, period=period, repair_ts_code=None, rows=rows)
    session.commit()
    rerun = dao.finalize_scope(stage_run_id=rerun_id, period=period, repair_ts_code=None)
    session.commit()
    assert (rerun.rows_inserted, rerun.rows_matched, rerun.final_scope_count) == (0, 2, 2)

    regression_id = uuid4()
    dao.stage_page(stage_run_id=regression_id, period=period, repair_ts_code=None, rows=[rows[0]])
    session.commit()
    with pytest.raises(FundPortfolioDAOError) as regression:
        dao.finalize_scope(stage_run_id=regression_id, period=period, repair_ts_code=None)
    session.rollback()
    assert regression.value.code == "immutable_scope_regression"

    conflict_id = uuid4()
    changed = [_normalized_row(mkv="999"), rows[1]]
    dao.stage_page(stage_run_id=conflict_id, period=period, repair_ts_code=None, rows=changed)
    session.commit()
    with pytest.raises(FundPortfolioDAOError) as conflict:
        dao.finalize_scope(stage_run_id=conflict_id, period=period, repair_ts_code=None)
    session.rollback()
    assert conflict.value.code == "immutable_content_conflict"
    assert len(session.scalars(select(FundPortfolio).where(FundPortfolio.end_date == period)).all()) == 2


def test_fund_portfolio_registry_ops_and_schedule_contract_have_no_workflow_or_probe() -> None:
    definition = get_dataset_definition("fund_portfolio")
    assert table_model_registry()["core_serving.fund_portfolio"] is FundPortfolio
    assert table_model_registry()["foundation.fund_portfolio_stage"] is FundPortfolioStage
    factory = DAOFactory(Session(create_engine("sqlite+pysqlite:///:memory:")))
    assert factory.fund_portfolio.model is FundPortfolio
    assert isinstance(factory.fund_portfolio_stage, FundPortfolioDAO)
    item = next(item for item in OPS_DATASET_DEFAULT_VIEW.items if item.dataset_key == "fund_portfolio")
    assert (item.group_key, item.item_order) == ("public_fund", 70)
    assert all(
        all(step.dataset_key != "fund_portfolio" for step in workflow.steps)
        for workflow in list_workflow_definitions()
    )

    route = ManualActionQueryService().get_action_route("fund_portfolio.maintain")
    assert route is not None
    assert [mode.label for mode in route.time_form.modes] == ["只处理一个报告期", "处理一个报告期范围"]
    assert all(mode.selection_rule == "quarter_end" for mode in route.time_form.modes)
    assert route.conditional_time_rules[0].help_text == "单基金补录只适用于已有报告期。"

    rules = DatasetScheduleTimePolicyResolver().resolve(definition=definition, action="maintain")
    assert len(rules) == 1
    assert rules[0].policy == "latest_completed_calendar_quarter"
    assert rules[0].schedule_types == ("cron", "once")
    assert rules[0].cron_repeat_modes == ("weekly", "monthly")
    assert TaskRunCommandService._latest_completed_quarter_for_schedule(
        scheduled_at=datetime.fromisoformat("2026-06-30T19:00:00+08:00"), timezone_name="Asia/Shanghai"
    ) == date(2026, 3, 31)
    assert TaskRunCommandService._latest_completed_quarter_for_schedule(
        scheduled_at=datetime.fromisoformat("2026-07-01T09:00:00+08:00"), timezone_name="Asia/Shanghai"
    ) == date(2026, 6, 30)
