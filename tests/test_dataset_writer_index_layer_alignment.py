from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from src.foundation.datasets.registry import get_dataset_definition
from src.foundation.ingestion.execution_plan import PlanUnitSnapshot
from src.foundation.ingestion.normalizer import NormalizedBatch
from src.foundation.ingestion.writer import DatasetWriter
from src.foundation.models.core_serving.index_daily_serving import IndexDailyServing
from src.foundation.models.core_serving.index_monthly_serving import IndexMonthlyServing
from src.foundation.models.core_serving.index_weekly_serving import IndexWeeklyServing
from src.foundation.models.raw.raw_index_daily import RawIndexDaily
from src.foundation.models.raw.raw_index_monthly_bar import RawIndexMonthlyBar
from src.foundation.models.raw.raw_index_weekly_bar import RawIndexWeeklyBar


class _StubDao:
    def __init__(self, *, model=None) -> None:  # type: ignore[no-untyped-def]
        self.model = model
        self.bulk_upsert_calls: list[list[dict]] = []
        self.bulk_insert_calls: list[list[dict]] = []
        self.deleted_ranges: list[tuple[date, date]] = []

    def bulk_upsert(self, rows: list[dict], conflict_columns=None):  # type: ignore[no-untyped-def]
        self.bulk_upsert_calls.append(rows)
        return len(rows)

    def bulk_insert(self, rows: list[dict]) -> int:
        self.bulk_insert_calls.append(rows)
        return len(rows)

    def delete_by_date_range(self, start_date: date, end_date: date) -> None:
        self.deleted_ranges.append((start_date, end_date))


class _StubSession:
    def __init__(self) -> None:
        self.execute_calls: list[object] = []

    def execute(self, statement, params=None):  # type: ignore[no-untyped-def]
        self.execute_calls.append(statement)
        return SimpleNamespace(mappings=lambda: [])


def _index_row(ts_code: str, trade_date: date) -> dict:
    return {
        "ts_code": ts_code,
        "trade_date": trade_date,
        "open": 1,
        "high": 2,
        "low": 1,
        "close": 2,
        "pre_close": 1,
        "change": 1,
        "pct_chg": 1,
        "vol": 10,
        "amount": 100,
    }


def _plan_unit(
    *,
    dataset_key: str,
    trade_date: date,
    request_params: dict | None = None,
) -> PlanUnitSnapshot:
    return PlanUnitSnapshot(
        unit_id=f"u-{dataset_key}",
        dataset_key=dataset_key,
        source_key="tushare",
        trade_date=trade_date,
        request_params=request_params or {},
        progress_context={},
        pagination_policy="offset_limit",
        page_limit=1000,
    )


def _patch_writer_dao(mocker, dao):  # type: ignore[no-untyped-def]
    mocker.patch("src.foundation.ingestion.writer.DAOFactory", return_value=dao)


def test_index_daily_writer_writes_raw_full_and_serving_active_only(mocker) -> None:
    raw_dao = _StubDao(model=RawIndexDaily)
    serving_dao = _StubDao(model=IndexDailyServing)
    dao = SimpleNamespace(
        raw_index_daily=raw_dao,
        index_daily_serving=serving_dao,
        index_series_active=SimpleNamespace(list_active_codes=mocker.Mock(return_value=["000001.SH"])),
        index_basic=SimpleNamespace(get_active_indexes=mocker.Mock()),
    )
    _patch_writer_dao(mocker, dao)
    writer = DatasetWriter(session=_StubSession())  # type: ignore[arg-type]
    definition = get_dataset_definition("index_daily")
    batch = NormalizedBatch(
        unit_id="u-index-daily",
        rows_normalized=[
            _index_row("000001.SH", date(2026, 4, 24)),
            _index_row("999999.SH", date(2026, 4, 24)),
        ],
        rows_rejected=0,
        rejected_reasons={},
    )

    result = writer.write(
        definition=definition,
        batch=batch,
        plan_unit=_plan_unit(dataset_key="index_daily", trade_date=date(2026, 4, 24)),
        run_profile="point_incremental",
    )

    assert [[row["ts_code"] for row in call] for call in raw_dao.bulk_upsert_calls] == [["000001.SH", "999999.SH"]]
    assert [[row["ts_code"] for row in call] for call in serving_dao.bulk_upsert_calls] == [["000001.SH"]]
    assert result.rows_written == 1
    assert result.rejected_reason_counts == {}


def test_index_daily_explicit_non_active_ts_code_does_not_write_serving(mocker) -> None:
    raw_dao = _StubDao(model=RawIndexDaily)
    serving_dao = _StubDao(model=IndexDailyServing)
    dao = SimpleNamespace(
        raw_index_daily=raw_dao,
        index_daily_serving=serving_dao,
        index_series_active=SimpleNamespace(list_active_codes=mocker.Mock(return_value=["000001.SH"])),
        index_basic=SimpleNamespace(get_active_indexes=mocker.Mock()),
    )
    _patch_writer_dao(mocker, dao)
    writer = DatasetWriter(session=_StubSession())  # type: ignore[arg-type]
    definition = get_dataset_definition("index_daily")
    batch = NormalizedBatch(
        unit_id="u-index-daily-explicit",
        rows_normalized=[_index_row("999999.SH", date(2026, 4, 24))],
        rows_rejected=0,
        rejected_reasons={},
    )

    result = writer.write(
        definition=definition,
        batch=batch,
        plan_unit=_plan_unit(
            dataset_key="index_daily",
            trade_date=date(2026, 4, 24),
            request_params={"ts_code": "999999.SH", "trade_date": "20260424"},
        ),
        run_profile="point_incremental",
    )

    assert [[row["ts_code"] for row in call] for call in raw_dao.bulk_upsert_calls] == [["999999.SH"]]
    assert serving_dao.bulk_upsert_calls == []
    assert result.rows_written == 0
    assert result.rejected_reason_counts == {}


@pytest.mark.parametrize(
    ("dataset_key", "raw_model", "serving_model", "raw_attr", "serving_attr", "anchor_start"),
    (
        ("index_weekly", RawIndexWeeklyBar, IndexWeeklyServing, "raw_index_weekly_bar", "index_weekly_serving", date(2026, 4, 20)),
        ("index_monthly", RawIndexMonthlyBar, IndexMonthlyServing, "raw_index_monthly_bar", "index_monthly_serving", date(2026, 4, 1)),
    ),
)
def test_index_period_writer_writes_raw_full_and_serving_active_with_derived(
    mocker,
    dataset_key: str,
    raw_model,
    serving_model,
    raw_attr: str,
    serving_attr: str,
    anchor_start: date,
) -> None:
    raw_dao = _StubDao(model=raw_model)
    serving_dao = _StubDao(model=serving_model)
    dao = SimpleNamespace(
        index_series_active=SimpleNamespace(list_active_codes=mocker.Mock(return_value=["000001.SH", "000002.SH"])),
        index_basic=SimpleNamespace(get_active_indexes=mocker.Mock()),
        trade_calendar=SimpleNamespace(
            settings=SimpleNamespace(default_exchange="SSE"),
            get_open_dates=mocker.Mock(return_value=[anchor_start]),
        ),
    )
    setattr(dao, raw_attr, raw_dao)
    setattr(dao, serving_attr, serving_dao)
    _patch_writer_dao(mocker, dao)
    writer = DatasetWriter(session=_StubSession())  # type: ignore[arg-type]
    definition = get_dataset_definition(dataset_key)
    trade_date = date(2026, 4, 24) if dataset_key == "index_weekly" else date(2026, 4, 30)
    mocker.patch.object(
        writer,
        "_build_index_period_derived_rows_for_codes",
        return_value=[
            {
                **_index_row("000002.SH", trade_date),
                "period_start_date": anchor_start,
                "change_amount": 1,
                "source": "derived_daily",
            }
        ],
    )
    batch = NormalizedBatch(
        unit_id=f"u-{dataset_key}",
        rows_normalized=[
            _index_row("000001.SH", trade_date),
            _index_row("999999.SH", trade_date),
        ],
        rows_rejected=0,
        rejected_reasons={},
    )

    result = writer.write(
        definition=definition,
        batch=batch,
        plan_unit=_plan_unit(dataset_key=dataset_key, trade_date=trade_date),
        run_profile="point_incremental",
    )

    assert [[row["ts_code"] for row in call] for call in raw_dao.bulk_upsert_calls] == [["000001.SH", "999999.SH"]]
    assert raw_dao.deleted_ranges == [(trade_date, trade_date)]
    assert len(serving_dao.bulk_insert_calls) == 1
    assert [row["ts_code"] for row in serving_dao.bulk_insert_calls[0]] == ["000001.SH", "000002.SH"]
    assert [row["source"] for row in serving_dao.bulk_insert_calls[0]] == ["api", "derived_daily"]
    assert result.rows_written == 2
    assert result.rejected_reason_counts == {}


def test_index_period_explicit_non_active_ts_code_writes_raw_only(mocker) -> None:
    raw_dao = _StubDao(model=RawIndexWeeklyBar)
    serving_dao = _StubDao(model=IndexWeeklyServing)
    dao = SimpleNamespace(
        raw_index_weekly_bar=raw_dao,
        index_weekly_serving=serving_dao,
        index_series_active=SimpleNamespace(list_active_codes=mocker.Mock(return_value=["000001.SH"])),
        index_basic=SimpleNamespace(get_active_indexes=mocker.Mock()),
        trade_calendar=SimpleNamespace(
            settings=SimpleNamespace(default_exchange="SSE"),
            get_open_dates=mocker.Mock(return_value=[date(2026, 4, 20)]),
        ),
    )
    _patch_writer_dao(mocker, dao)
    writer = DatasetWriter(session=_StubSession())  # type: ignore[arg-type]
    derived_mock = mocker.patch.object(writer, "_build_index_period_derived_rows", return_value=[])
    definition = get_dataset_definition("index_weekly")
    batch = NormalizedBatch(
        unit_id="u-index-weekly-explicit",
        rows_normalized=[_index_row("999999.SH", date(2026, 4, 24))],
        rows_rejected=0,
        rejected_reasons={},
    )

    result = writer.write(
        definition=definition,
        batch=batch,
        plan_unit=_plan_unit(
            dataset_key="index_weekly",
            trade_date=date(2026, 4, 24),
            request_params={"ts_code": "999999.SH", "trade_date": "20260424"},
        ),
        run_profile="point_incremental",
    )

    assert [[row["ts_code"] for row in call] for call in raw_dao.bulk_upsert_calls] == [["999999.SH"]]
    assert serving_dao.bulk_insert_calls == []
    assert result.rows_written == 0
    assert result.rejected_reason_counts == {}
    derived_mock.assert_not_called()
