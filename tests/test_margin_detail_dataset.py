from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
import runpy
from types import SimpleNamespace

import pytest

from src.app.exceptions import WebAppError
from src.foundation.datasets.registry import get_dataset_definition
from src.foundation.ingestion import DatasetActionRequest, DatasetActionResolver, DatasetTimeInput
from src.foundation.ingestion.errors import IngestionNormalizeError, IngestionPlanningError
from src.foundation.ingestion.normalizer import DatasetNormalizer, NormalizedBatch
from src.foundation.ingestion.source_client import SourceFetchResult
from src.foundation.ingestion.writer import DatasetWriter
from src.foundation.models.core_serving.equity_margin_detail import EquityMarginDetail
from src.ops.queries.manual_action_query_service import ManualActionQueryService
from src.ops.schemas.manual_action import ManualActionTaskRunCreateRequest, ManualActionTimeInput
from src.ops.services.manual_action_service import ManualActionTaskRunResolver


MIGRATION_PATH = Path(__file__).resolve().parents[1] / "alembic/versions/20260802_000123_add_margin_detail_serving_dataset.py"


def _margin_detail_row() -> dict:
    return {
        "trade_date": date(2026, 7, 30),
        "ts_code": "600000.SH",
        "name": "浦发银行",
        "rzye": Decimal("100.0000"),
        "rqye": Decimal("10.0000"),
        "rzmre": Decimal("20.0000"),
        "rqyl": Decimal("30.0000"),
        "rzche": Decimal("40.0000"),
        "rqchl": Decimal("50.0000"),
        "rqmcl": Decimal("60.0000"),
        "rzrqye": Decimal("110.0000"),
    }


def test_margin_detail_point_and_range_plan_use_day_scoped_source_requests(mocker) -> None:
    session = mocker.Mock()
    fake_dao = SimpleNamespace(
        trade_calendar=SimpleNamespace(get_open_dates=mocker.Mock(return_value=[date(2026, 7, 30), date(2026, 7, 31)])),
    )
    mocker.patch("src.foundation.ingestion.unit_planner.DAOFactory", return_value=fake_dao)
    resolver = DatasetActionResolver(session)

    point_plan = resolver.build_plan(
        DatasetActionRequest(
            dataset_key="margin_detail",
            action="maintain",
            time_input=DatasetTimeInput(mode="point", trade_date=date(2026, 7, 30)),
        )
    )
    range_plan = resolver.build_plan(
        DatasetActionRequest(
            dataset_key="margin_detail",
            action="maintain",
            time_input=DatasetTimeInput(mode="range", start_date=date(2026, 7, 30), end_date=date(2026, 7, 31)),
        )
    )

    assert point_plan.writing.write_path == "serving_direct_upsert"
    assert point_plan.writing.observation_dao_name is None
    assert point_plan.writing.observation_table is None
    assert point_plan.units[0].request_params == {"trade_date": "20260730"}
    assert point_plan.units[0].pagination_policy == "offset_limit"
    assert point_plan.units[0].page_limit == 1000
    assert [unit.request_params for unit in range_plan.units] == [
        {"trade_date": "20260730"},
        {"trade_date": "20260731"},
    ]
    assert all("start_date" not in unit.request_params and "end_date" not in unit.request_params for unit in range_plan.units)


def test_margin_detail_scoped_repair_requires_existing_point_bucket(mocker) -> None:
    session = mocker.Mock()
    session.scalar.return_value = date(2026, 7, 30)
    fake_dao = SimpleNamespace(
        equity_margin_detail=SimpleNamespace(model=EquityMarginDetail),
        trade_calendar=SimpleNamespace(get_open_dates=mocker.Mock()),
    )
    mocker.patch("src.foundation.ingestion.unit_planner.DAOFactory", return_value=fake_dao)
    resolver = DatasetActionResolver(session)

    plan = resolver.build_plan(
        DatasetActionRequest(
            dataset_key="margin_detail",
            action="maintain",
            time_input=DatasetTimeInput(mode="point", trade_date=date(2026, 7, 30)),
            filters={"ts_code": "600000.SH"},
        )
    )

    assert plan.units[0].request_params == {"trade_date": "20260730", "ts_code": "600000.SH"}
    session.scalar.assert_called_once()


@pytest.mark.parametrize(
    ("time_input", "filters", "error_code"),
    (
        (DatasetTimeInput(mode="range", start_date=date(2026, 7, 30), end_date=date(2026, 7, 31)), {"ts_code": "600000.SH"}, "scoped_repair_point_required"),
        (DatasetTimeInput(mode="point", trade_date=date(2026, 7, 30)), {"ts_code": "600000,000001.SZ"}, "scoped_repair_code_invalid"),
    ),
)
def test_margin_detail_scoped_repair_rejects_invalid_scope(mocker, time_input, filters, error_code: str) -> None:  # type: ignore[no-untyped-def]
    mocker.patch("src.foundation.ingestion.unit_planner.DAOFactory", return_value=SimpleNamespace())
    resolver = DatasetActionResolver(mocker.Mock())

    with pytest.raises(IngestionPlanningError) as exc_info:
        resolver.build_plan(
            DatasetActionRequest(
                dataset_key="margin_detail",
                action="maintain",
                time_input=time_input,
                filters=filters,
            )
        )

    assert exc_info.value.structured_error.error_code == error_code


def test_margin_detail_scoped_repair_rejects_missing_physical_bucket(mocker) -> None:
    session = mocker.Mock()
    session.scalar.return_value = None
    mocker.patch(
        "src.foundation.ingestion.unit_planner.DAOFactory",
        return_value=SimpleNamespace(equity_margin_detail=SimpleNamespace(model=EquityMarginDetail)),
    )
    resolver = DatasetActionResolver(session)

    with pytest.raises(IngestionPlanningError) as exc_info:
        resolver.build_plan(
            DatasetActionRequest(
                dataset_key="margin_detail",
                action="maintain",
                time_input=DatasetTimeInput(mode="point", trade_date=date(2026, 7, 30)),
                filters={"ts_code": "600000.SH"},
            )
        )

    assert exc_info.value.structured_error.error_code == "scoped_repair_bucket_missing"


def test_margin_detail_direct_writer_uses_only_serving_dao(mocker) -> None:
    class ServingDao:
        model = EquityMarginDetail

        def __init__(self) -> None:
            self.calls: list[tuple[list[dict], list[str] | None]] = []

        def bulk_upsert(self, rows: list[dict], conflict_columns=None):  # type: ignore[no-untyped-def]
            self.calls.append((rows, list(conflict_columns or []) or None))
            return len(rows)

    serving_dao = ServingDao()
    mocker.patch(
        "src.foundation.ingestion.writer.DAOFactory",
        return_value=SimpleNamespace(equity_margin_detail=serving_dao),
    )
    batch = NormalizedBatch(
        unit_id="margin-detail-u1",
        rows_normalized=[_margin_detail_row()],
        rows_rejected=0,
        rejected_reasons={},
    )

    result = DatasetWriter(session=mocker.Mock()).write(
        definition=get_dataset_definition("margin_detail"),
        batch=batch,
    )

    assert serving_dao.calls == [(batch.rows_normalized, ["trade_date", "ts_code"])]
    assert result.rows_written == 1
    assert result.conflict_strategy == "serving_direct_upsert"


def test_margin_detail_normalizer_deduplicates_identical_pagination_overlap() -> None:
    row = _margin_detail_row()
    batch = DatasetNormalizer().normalize(
        definition=get_dataset_definition("margin_detail"),
        fetch_result=SourceFetchResult(
            unit_id="margin-detail-u1",
            request_count=2,
            retry_count=0,
            latency_ms=1,
            rows_raw=[row, dict(row)],
        ),
        expected_unit_date=date(2026, 7, 30),
    )

    assert batch.rows_normalized == [row]
    assert batch.rows_rejected == 1
    assert batch.rejected_reasons == {"normalize.duplicate_conflict_key_in_batch": 1}


@pytest.mark.parametrize(
    ("row", "error_code"),
    (
        ({**_margin_detail_row(), "trade_date": date(2026, 7, 31)}, "normalize.unit_date_mismatch"),
        ({**_margin_detail_row(), "rzye": Decimal("101.0000")}, "normalize.duplicate_conflict_key_inconsistent"),
    ),
)
def test_margin_detail_normalizer_rejects_date_drift_and_conflicting_duplicates(row, error_code: str) -> None:  # type: ignore[no-untyped-def]
    rows = [row] if error_code == "normalize.unit_date_mismatch" else [_margin_detail_row(), row]

    with pytest.raises(IngestionNormalizeError) as exc_info:
        DatasetNormalizer().normalize(
            definition=get_dataset_definition("margin_detail"),
            fetch_result=SourceFetchResult(
                unit_id="margin-detail-u1",
                request_count=1,
                retry_count=0,
                latency_ms=1,
                rows_raw=rows,
            ),
            expected_unit_date=date(2026, 7, 30),
        )

    assert exc_info.value.structured_error.error_code == error_code


def test_margin_detail_manual_action_exposes_and_enforces_conditional_time_rule() -> None:
    route = ManualActionQueryService().get_action_route("margin_detail.maintain")
    assert route is not None
    assert route.conditional_time_rules[0].filter_key == "ts_code"
    assert route.conditional_time_rules[0].allowed_time_modes == ["point"]

    with pytest.raises(WebAppError, match="仅支持一个已存在日期桶"):
        ManualActionTaskRunResolver(route).resolve(
            ManualActionTaskRunCreateRequest(
                time_input=ManualActionTimeInput(mode="range", start_date="2026-07-30", end_date="2026-07-31"),
                filters={"ts_code": "600000.SH"},
            )
        )


def test_margin_detail_migration_declares_only_partitioned_serving_table() -> None:
    migration = runpy.run_path(str(MIGRATION_PATH))
    migration_text = MIGRATION_PATH.read_text(encoding="utf-8")

    assert migration["revision"] == "20260802_000123"
    assert migration["down_revision"] == "20260802_000122"
    assert "CREATE TABLE core_serving.equity_margin_detail" in migration_text
    assert "PARTITION BY RANGE (trade_date)" in migration_text
    assert "raw_tushare.margin_detail" not in migration_text
