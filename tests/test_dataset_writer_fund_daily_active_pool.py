from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from src.foundation.datasets.registry import get_dataset_definition
from src.foundation.ingestion.execution_plan import PlanUnitSnapshot
from src.foundation.ingestion.normalizer import NormalizedBatch
from src.foundation.ingestion.writer import DatasetWriter
from src.foundation.models.core.fund_daily_bar import FundDailyBar
from src.foundation.models.raw.raw_fund_daily import RawFundDaily


class _StubDao:
    def __init__(self, *, model=None) -> None:  # type: ignore[no-untyped-def]
        self.model = model
        self.bulk_upsert_calls: list[list[dict]] = []

    def bulk_upsert(self, rows: list[dict], conflict_columns=None):  # type: ignore[no-untyped-def]
        self.bulk_upsert_calls.append(rows)
        return len(rows)


class _StubSession:
    pass


def _fund_daily_row(ts_code: str, trade_date: date) -> dict:
    return {
        "ts_code": ts_code,
        "trade_date": trade_date,
        "open": 1,
        "high": 2,
        "low": 1,
        "close": 2,
        "pre_close": 1,
        "change_amount": 1,
        "pct_chg": 1,
        "vol": 10,
        "amount": 100,
    }


def _plan_unit(*, ts_code: str | None = None) -> PlanUnitSnapshot:
    request_params = {"trade_date": "20260617"}
    if ts_code is not None:
        request_params["ts_code"] = ts_code
    return PlanUnitSnapshot(
        unit_id="u-fund-daily",
        dataset_key="fund_daily",
        source_key="tushare",
        trade_date=date(2026, 6, 17),
        request_params=request_params,
        progress_context={},
        pagination_policy="offset_limit",
        page_limit=5000,
    )


def _patch_writer_dao(mocker, dao):  # type: ignore[no-untyped-def]
    mocker.patch("src.foundation.ingestion.writer.DAOFactory", return_value=dao)


def test_fund_daily_writer_writes_all_rows_to_raw_and_active_rows_to_serving(mocker) -> None:
    raw_dao = _StubDao(model=RawFundDaily)
    serving_dao = _StubDao(model=FundDailyBar)
    dao = SimpleNamespace(
        raw_fund_daily=raw_dao,
        fund_daily_bar=serving_dao,
        etf_series_active=SimpleNamespace(list_active_codes=mocker.Mock(return_value=["510300.SH"])),
        etf_basic=SimpleNamespace(get_fund_daily_candidates=mocker.Mock()),
    )
    _patch_writer_dao(mocker, dao)
    writer = DatasetWriter(session=_StubSession())  # type: ignore[arg-type]
    definition = get_dataset_definition("fund_daily")
    batch = NormalizedBatch(
        unit_id="u-fund-daily",
        rows_normalized=[
            _fund_daily_row("510300.SH", date(2026, 6, 17)),
            _fund_daily_row("999999.SH", date(2026, 6, 17)),
        ],
        rows_rejected=0,
        rejected_reasons={},
    )

    result = writer.write(
        definition=definition,
        batch=batch,
        plan_unit=_plan_unit(),
        run_profile="point_incremental",
    )

    assert [[row["ts_code"] for row in call] for call in raw_dao.bulk_upsert_calls] == [["510300.SH", "999999.SH"]]
    assert [[row["ts_code"] for row in call] for call in serving_dao.bulk_upsert_calls] == [["510300.SH"]]
    assert result.rows_written == 1
    assert result.rows_rejected == 0
    assert result.rejected_reason_counts == {}
    assert result.conflict_strategy == "fund_daily_etf_active_gate"
    dao.etf_series_active.list_active_codes.assert_called_once_with("fund_daily")
    dao.etf_basic.get_fund_daily_candidates.assert_not_called()


def test_fund_daily_explicit_non_active_ts_code_writes_raw_without_serving(mocker) -> None:
    raw_dao = _StubDao(model=RawFundDaily)
    serving_dao = _StubDao(model=FundDailyBar)
    dao = SimpleNamespace(
        raw_fund_daily=raw_dao,
        fund_daily_bar=serving_dao,
        etf_series_active=SimpleNamespace(list_active_codes=mocker.Mock(return_value=["510300.SH"])),
        etf_basic=SimpleNamespace(get_fund_daily_candidates=mocker.Mock()),
    )
    _patch_writer_dao(mocker, dao)
    writer = DatasetWriter(session=_StubSession())  # type: ignore[arg-type]
    definition = get_dataset_definition("fund_daily")
    batch = NormalizedBatch(
        unit_id="u-fund-daily-explicit",
        rows_normalized=[_fund_daily_row("999999.SH", date(2026, 6, 17))],
        rows_rejected=0,
        rejected_reasons={},
    )

    result = writer.write(
        definition=definition,
        batch=batch,
        plan_unit=_plan_unit(ts_code="999999.SH"),
        run_profile="point_incremental",
    )

    assert [[row["ts_code"] for row in call] for call in raw_dao.bulk_upsert_calls] == [["999999.SH"]]
    assert serving_dao.bulk_upsert_calls == []
    assert result.rows_written == 0
    assert result.rows_rejected == 0
    assert result.rejected_reason_counts == {}
    dao.etf_series_active.list_active_codes.assert_called_once_with("fund_daily")
    dao.etf_basic.get_fund_daily_candidates.assert_not_called()


def test_fund_daily_writer_does_not_fallback_when_active_pool_is_empty(mocker) -> None:
    raw_dao = _StubDao(model=RawFundDaily)
    serving_dao = _StubDao(model=FundDailyBar)
    dao = SimpleNamespace(
        raw_fund_daily=raw_dao,
        fund_daily_bar=serving_dao,
        etf_series_active=SimpleNamespace(list_active_codes=mocker.Mock(return_value=[])),
        etf_basic=SimpleNamespace(get_fund_daily_candidates=mocker.Mock(side_effect=AssertionError("no fallback"))),
    )
    _patch_writer_dao(mocker, dao)
    writer = DatasetWriter(session=_StubSession())  # type: ignore[arg-type]
    definition = get_dataset_definition("fund_daily")
    batch = NormalizedBatch(
        unit_id="u-fund-daily-empty-pool",
        rows_normalized=[
            _fund_daily_row("510300.SH", date(2026, 6, 17)),
            _fund_daily_row("999999.SH", date(2026, 6, 17)),
        ],
        rows_rejected=0,
        rejected_reasons={},
    )

    result = writer.write(
        definition=definition,
        batch=batch,
        plan_unit=_plan_unit(),
        run_profile="point_incremental",
    )

    assert [[row["ts_code"] for row in call] for call in raw_dao.bulk_upsert_calls] == [["510300.SH", "999999.SH"]]
    assert serving_dao.bulk_upsert_calls == []
    assert result.rows_written == 0
    assert result.rows_rejected == 0
    dao.etf_series_active.list_active_codes.assert_called_once_with("fund_daily")
    dao.etf_basic.get_fund_daily_candidates.assert_not_called()


def test_fund_daily_duplicate_diagnostics_only_count_serving_candidates(mocker) -> None:
    raw_dao = _StubDao(model=RawFundDaily)
    serving_dao = _StubDao(model=FundDailyBar)
    dao = SimpleNamespace(
        raw_fund_daily=raw_dao,
        fund_daily_bar=serving_dao,
        etf_series_active=SimpleNamespace(list_active_codes=mocker.Mock(return_value=["510300.SH"])),
    )
    _patch_writer_dao(mocker, dao)
    writer = DatasetWriter(session=_StubSession())  # type: ignore[arg-type]
    definition = get_dataset_definition("fund_daily")
    batch = NormalizedBatch(
        unit_id="u-fund-daily-duplicates",
        rows_normalized=[
            _fund_daily_row("510300.SH", date(2026, 6, 17)),
            _fund_daily_row("510300.SH", date(2026, 6, 17)),
            _fund_daily_row("999999.SH", date(2026, 6, 17)),
            _fund_daily_row("999999.SH", date(2026, 6, 17)),
        ],
        rows_rejected=0,
        rejected_reasons={},
    )

    result = writer.write(
        definition=definition,
        batch=batch,
        plan_unit=_plan_unit(),
        run_profile="point_incremental",
    )

    assert [[row["ts_code"] for row in call] for call in raw_dao.bulk_upsert_calls] == [
        ["510300.SH", "510300.SH", "999999.SH", "999999.SH"]
    ]
    assert [[row["ts_code"] for row in call] for call in serving_dao.bulk_upsert_calls] == [["510300.SH", "510300.SH"]]
    assert result.rows_rejected == 1
    assert result.rejected_reason_counts == {"write.duplicate_conflict_key_in_batch:ts_code,trade_date": 1}
