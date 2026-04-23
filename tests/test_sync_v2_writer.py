from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from src.foundation.services.sync_v2.contracts import NormalizedBatch
from src.foundation.services.sync_v2.errors import SyncV2WriteError
from src.foundation.services.sync_v2.registry import get_sync_v2_contract
from src.foundation.services.sync_v2.writer import SyncV2Writer


class _StubDao:
    def __init__(self, written: int) -> None:
        self.written = written
        self.calls: list[tuple[list[dict], list[str] | None]] = []
        self.deleted_ranges: list[tuple[date, date]] = []

    def bulk_upsert(self, rows: list[dict], conflict_columns: list[str] | None = None) -> int:
        self.calls.append((rows, conflict_columns))
        return self.written

    def delete_by_date_range(self, start_date: date, end_date: date) -> int:
        self.deleted_ranges.append((start_date, end_date))
        return 0


class _StubSnapshotDao:
    def __init__(self, written: int) -> None:
        self.written = written
        self.deleted_ranges: list[tuple[date, date]] = []
        self.inserted_rows: list[list[dict]] = []

    def delete_by_date_range(self, start_date: date, end_date: date) -> int:
        self.deleted_ranges.append((start_date, end_date))
        return 0

    def bulk_insert(self, rows: list[dict]) -> int:
        self.inserted_rows.append(rows)
        return self.written


def test_sync_v2_writer_keeps_default_raw_core_path(mocker) -> None:
    raw_dao = _StubDao(written=1)
    core_dao = _StubDao(written=1)
    mocker.patch(
        "src.foundation.services.sync_v2.writer.DAOFactory",
        return_value=SimpleNamespace(raw_daily_basic=raw_dao, equity_daily_basic=core_dao),
    )
    session = object()
    writer = SyncV2Writer(session=session)  # type: ignore[arg-type]
    contract = get_sync_v2_contract("daily_basic")
    batch = NormalizedBatch(
        unit_id="u-daily-basic",
        rows_normalized=[{"ts_code": "000001.SZ", "trade_date": date(2026, 4, 17), "close": 10.2}],
        rows_rejected=0,
        rejected_reasons={},
    )

    result = writer.write(contract=contract, batch=batch)

    assert len(raw_dao.calls) == 1
    assert len(core_dao.calls) == 1
    assert result.rows_written == 1
    assert result.target_table == "core_serving.equity_daily_basic"


def test_sync_v2_writer_supports_snapshot_insert_by_trade_date_path(mocker) -> None:
    raw_dao = _StubSnapshotDao(written=2)
    core_dao = _StubSnapshotDao(written=2)
    mocker.patch(
        "src.foundation.services.sync_v2.writer.DAOFactory",
        return_value=SimpleNamespace(raw_block_trade=raw_dao, equity_block_trade=core_dao),
    )
    writer = SyncV2Writer(session=object())  # type: ignore[arg-type]
    contract = get_sync_v2_contract("block_trade")
    batch = NormalizedBatch(
        unit_id="u-block-trade",
        rows_normalized=[
            {"ts_code": "000001.SZ", "trade_date": date(2026, 4, 17), "price": 10.0, "vol": 1, "amount": 10.0},
            {"ts_code": "000002.SZ", "trade_date": date(2026, 4, 17), "price": 11.0, "vol": 2, "amount": 22.0},
        ],
        rows_rejected=0,
        rejected_reasons={},
    )

    result = writer.write(contract=contract, batch=batch)

    assert raw_dao.deleted_ranges == [(date(2026, 4, 17), date(2026, 4, 17))]
    assert core_dao.deleted_ranges == [(date(2026, 4, 17), date(2026, 4, 17))]
    assert len(raw_dao.inserted_rows) == 1
    assert len(core_dao.inserted_rows) == 1
    assert result.rows_written == 2
    assert result.conflict_strategy == "snapshot_insert_by_trade_date"


def test_sync_v2_writer_supports_moneyflow_std_publish_path(mocker) -> None:
    raw_dao = _StubDao(written=2)
    std_dao = _StubDao(written=2)
    mocker.patch(
        "src.foundation.services.sync_v2.writer.DAOFactory",
        return_value=SimpleNamespace(raw_moneyflow=raw_dao, moneyflow_std=std_dao),
    )
    publish_spy = mocker.patch(
        "src.foundation.services.sync_v2.writer.publish_moneyflow_serving_for_keys",
        return_value=3,
    )
    session = object()
    writer = SyncV2Writer(session=session)  # type: ignore[arg-type]
    contract = get_sync_v2_contract("moneyflow")
    batch = NormalizedBatch(
        unit_id="u-moneyflow",
        rows_normalized=[
            {
                "ts_code": "000001.SZ",
                "trade_date": date(2026, 4, 17),
                "buy_sm_vol": 1,
                "buy_sm_amount": 2.0,
                "sell_sm_vol": 3,
                "sell_sm_amount": 4.0,
                "buy_md_vol": 5,
                "buy_md_amount": 6.0,
                "sell_md_vol": 7,
                "sell_md_amount": 8.0,
                "buy_lg_vol": 9,
                "buy_lg_amount": 10.0,
                "sell_lg_vol": 11,
                "sell_lg_amount": 12.0,
                "buy_elg_vol": 13,
                "buy_elg_amount": 14.0,
                "sell_elg_vol": 15,
                "sell_elg_amount": 16.0,
                "net_mf_vol": 17,
                "net_mf_amount": 18.0,
            }
        ],
        rows_rejected=0,
        rejected_reasons={},
    )

    result = writer.write(contract=contract, batch=batch)

    assert len(raw_dao.calls) == 1
    assert len(std_dao.calls) == 1
    std_rows, _ = std_dao.calls[0]
    assert std_rows[0]["source_key"] == "tushare"
    assert std_rows[0]["ts_code"] == "000001.SZ"
    assert std_rows[0]["trade_date"] == date(2026, 4, 17)
    called_keys = publish_spy.call_args.args[2]
    assert called_keys == {("000001.SZ", date(2026, 4, 17))}
    assert result.rows_written == 3
    assert result.target_table == "core_serving.equity_moneyflow"


def test_sync_v2_writer_supports_moneyflow_std_publish_biying_path(mocker) -> None:
    raw_dao = _StubDao(written=2)
    std_dao = _StubDao(written=2)
    mocker.patch(
        "src.foundation.services.sync_v2.writer.DAOFactory",
        return_value=SimpleNamespace(raw_biying_moneyflow=raw_dao, moneyflow_std=std_dao),
    )
    publish_spy = mocker.patch(
        "src.foundation.services.sync_v2.writer.publish_moneyflow_serving_for_keys",
        return_value=4,
    )
    writer = SyncV2Writer(session=object())  # type: ignore[arg-type]
    contract = get_sync_v2_contract("biying_moneyflow")
    batch = NormalizedBatch(
        unit_id="u-biying-moneyflow",
        rows_normalized=[
            {
                "dm": "000001",
                "trade_date": date(2026, 4, 17),
                "zmbtdcjl": 10,
                "zmstdcjl": 7,
                "zmbtdcje": 1000.0,
                "zmstdcje": 800.0,
            }
        ],
        rows_rejected=0,
        rejected_reasons={},
    )

    result = writer.write(contract=contract, batch=batch)

    assert len(raw_dao.calls) == 1
    assert len(std_dao.calls) == 1
    std_rows, _ = std_dao.calls[0]
    assert std_rows[0]["source_key"] == "biying"
    assert std_rows[0]["ts_code"] == "000001.SZ"
    assert std_rows[0]["trade_date"] == date(2026, 4, 17)
    called_keys = publish_spy.call_args.args[2]
    assert called_keys == {("000001.SZ", date(2026, 4, 17))}
    assert result.rows_written == 4
    assert result.target_table == "core_serving.equity_moneyflow"


def test_sync_v2_writer_supports_raw_only_upsert_path(mocker) -> None:
    raw_dao = _StubDao(written=3)
    mocker.patch(
        "src.foundation.services.sync_v2.writer.DAOFactory",
        return_value=SimpleNamespace(raw_biying_equity_daily_bar=raw_dao),
    )
    writer = SyncV2Writer(session=object())  # type: ignore[arg-type]
    contract = get_sync_v2_contract("biying_equity_daily")
    batch = NormalizedBatch(
        unit_id="u-biying-equity-daily",
        rows_normalized=[
            {
                "dm": "000001",
                "trade_date": date(2026, 4, 17),
                "adj_type": "f",
                "close": 10.5,
            }
        ],
        rows_rejected=0,
        rejected_reasons={},
    )

    result = writer.write(contract=contract, batch=batch)

    assert len(raw_dao.calls) == 1
    assert result.rows_written == 3
    assert result.target_table == "raw_biying.equity_daily_bar"


def test_sync_v2_writer_moneyflow_rejects_fractional_volume(mocker) -> None:
    raw_dao = _StubDao(written=1)
    std_dao = _StubDao(written=1)
    mocker.patch(
        "src.foundation.services.sync_v2.writer.DAOFactory",
        return_value=SimpleNamespace(raw_moneyflow=raw_dao, moneyflow_std=std_dao),
    )
    mocker.patch(
        "src.foundation.services.sync_v2.writer.publish_moneyflow_serving_for_keys",
        return_value=0,
    )
    writer = SyncV2Writer(session=object())  # type: ignore[arg-type]
    contract = get_sync_v2_contract("moneyflow")
    batch = NormalizedBatch(
        unit_id="u-moneyflow-invalid",
        rows_normalized=[
            {
                "ts_code": "000001.SZ",
                "trade_date": date(2026, 4, 17),
                "buy_sm_vol": 1.1,
            }
        ],
        rows_rejected=0,
        rejected_reasons={},
    )

    with pytest.raises(SyncV2WriteError) as exc_info:
        writer.write(contract=contract, batch=batch)

    assert exc_info.value.structured_error.error_code == "write_failed"


def test_sync_v2_writer_supports_index_period_serving_upsert_path(mocker) -> None:
    raw_dao = _StubDao(written=2)
    core_dao = SimpleNamespace(model=SimpleNamespace())
    mocker.patch(
        "src.foundation.services.sync_v2.writer.DAOFactory",
        return_value=SimpleNamespace(
            raw_index_weekly_bar=raw_dao,
            index_weekly_serving=core_dao,
            index_series_active=SimpleNamespace(list_active_codes=lambda resource: ["000300.SH"]),
            index_basic=SimpleNamespace(get_active_indexes=lambda: []),
        ),
    )
    writer = SyncV2Writer(session=object())  # type: ignore[arg-type]
    replace_spy = mocker.patch.object(writer, "_replace_index_period_serving_rows", return_value=2)
    start_date_spy = mocker.patch.object(
        writer,
        "_resolve_index_period_start_date",
        return_value=date(2026, 4, 14),
    )
    contract = get_sync_v2_contract("index_weekly")
    batch = NormalizedBatch(
        unit_id="u-index-weekly",
        rows_normalized=[
            {
                "ts_code": "000300.SH",
                "trade_date": date(2026, 4, 17),
                "open": 10.0,
                "high": 11.0,
                "low": 9.0,
                "close": 10.5,
                "pre_close": 10.0,
                "change": 0.5,
                "pct_chg": 5.0,
                "vol": 1000.0,
                "amount": 1000000.0,
            }
        ],
        rows_rejected=0,
        rejected_reasons={},
    )

    result = writer.write(contract=contract, batch=batch)

    assert len(raw_dao.calls) == 1
    assert len(raw_dao.calls[0][0]) == 1
    assert raw_dao.calls[0][0][0]["ts_code"] == "000300.SH"
    assert start_date_spy.call_count == 1
    replace_spy.assert_called_once()
    kwargs = replace_spy.call_args.kwargs
    assert kwargs["keep_api"] is False
    assert kwargs["rows"][0]["period_start_date"] == date(2026, 4, 14)
    assert kwargs["rows"][0]["source"] == "api"
    assert kwargs["rows"][0]["change_amount"] == 0.5
    assert result.rows_written == 2
    assert result.conflict_strategy == "index_period_upsert"


def test_sync_v2_writer_index_period_uses_derived_daily_fallback_for_missing_code(mocker) -> None:
    raw_dao = _StubDao(written=0)
    core_dao = SimpleNamespace(model=SimpleNamespace())
    mocker.patch(
        "src.foundation.services.sync_v2.writer.DAOFactory",
        return_value=SimpleNamespace(
            raw_index_weekly_bar=raw_dao,
            index_weekly_serving=core_dao,
            index_series_active=SimpleNamespace(list_active_codes=lambda resource: ["000300.SH"]),
            index_basic=SimpleNamespace(get_active_indexes=lambda: []),
        ),
    )
    writer = SyncV2Writer(session=object())  # type: ignore[arg-type]
    derived_spy = mocker.patch.object(
        writer,
        "_build_index_period_derived_rows",
        return_value=[
            {
                "ts_code": "000300.SH",
                "period_start_date": date(2026, 4, 14),
                "trade_date": date(2026, 4, 17),
                "open": 10.0,
                "high": 11.0,
                "low": 9.0,
                "close": 10.5,
                "pre_close": 10.0,
                "change_amount": 0.5,
                "pct_chg": 5.0,
                "vol": 1000.0,
                "amount": 1000000.0,
                "source": "derived_daily",
            }
        ],
    )
    replace_spy = mocker.patch.object(writer, "_replace_index_period_serving_rows", return_value=1)
    contract = get_sync_v2_contract("index_weekly")
    batch = NormalizedBatch(
        unit_id="u-index-weekly-empty",
        rows_normalized=[],
        rows_rejected=0,
        rejected_reasons={},
    )
    plan_unit = SimpleNamespace(
        unit_id="u-index-weekly-empty",
        request_params={"ts_code": "000300.SH", "trade_date": "20260417"},
        trade_date=date(2026, 4, 17),
    )

    result = writer.write(
        contract=contract,
        batch=batch,
        plan_unit=plan_unit,  # type: ignore[arg-type]
        run_profile="point_incremental",
    )

    derived_spy.assert_called_once()
    replace_spy.assert_called_once()
    assert replace_spy.call_args.kwargs["keep_api"] is True
    assert result.rows_written == 1
    assert result.conflict_strategy == "derived_daily_fallback"


def test_sync_v2_writer_index_period_filters_active_pool_and_appends_derived_missing_codes(mocker) -> None:
    raw_dao = _StubDao(written=1)
    core_dao = SimpleNamespace(model=SimpleNamespace())
    mocker.patch(
        "src.foundation.services.sync_v2.writer.DAOFactory",
        return_value=SimpleNamespace(
            raw_index_weekly_bar=raw_dao,
            index_weekly_serving=core_dao,
            index_series_active=SimpleNamespace(list_active_codes=lambda resource: ["000300.SH", "000905.SH"]),
            index_basic=SimpleNamespace(get_active_indexes=lambda: []),
            trade_calendar=SimpleNamespace(
                settings=SimpleNamespace(default_exchange="SSE"),
                get_open_dates=lambda exchange, start_date, end_date: [start_date, end_date],
            ),
        ),
    )
    writer = SyncV2Writer(session=object())  # type: ignore[arg-type]
    derived_spy = mocker.patch.object(
        writer,
        "_build_index_period_derived_rows_for_codes",
        return_value=[
            {
                "ts_code": "000905.SH",
                "period_start_date": date(2026, 4, 14),
                "trade_date": date(2026, 4, 17),
                "open": 20.0,
                "high": 21.0,
                "low": 19.0,
                "close": 20.5,
                "pre_close": 20.0,
                "change_amount": 0.5,
                "pct_chg": 2.5,
                "vol": 2000.0,
                "amount": 2000000.0,
                "source": "derived_daily",
            }
        ],
    )
    replace_spy = mocker.patch.object(writer, "_replace_index_period_serving_rows_by_trade_dates", return_value=2)
    contract = get_sync_v2_contract("index_weekly")
    batch = NormalizedBatch(
        unit_id="u-index-weekly-active-filter",
        rows_normalized=[
            {
                "ts_code": "000300.SH",
                "trade_date": date(2026, 4, 17),
                "open": 10.0,
                "high": 11.0,
                "low": 9.0,
                "close": 10.5,
                "pre_close": 10.0,
                "change": 0.5,
                "pct_chg": 5.0,
                "vol": 1000.0,
                "amount": 1000000.0,
            },
            {
                "ts_code": "999999.SH",
                "trade_date": date(2026, 4, 17),
                "open": 30.0,
                "high": 31.0,
                "low": 29.0,
                "close": 30.5,
                "pre_close": 30.0,
                "change": 0.5,
                "pct_chg": 1.6,
                "vol": 3000.0,
                "amount": 3000000.0,
            },
        ],
        rows_rejected=0,
        rejected_reasons={},
    )
    plan_unit = SimpleNamespace(
        unit_id="u-index-weekly-active-filter",
        request_params={"trade_date": "20260417"},
        trade_date=date(2026, 4, 17),
    )

    result = writer.write(
        contract=contract,
        batch=batch,
        plan_unit=plan_unit,  # type: ignore[arg-type]
        run_profile="point_incremental",
    )

    assert len(raw_dao.calls) == 1
    filtered_rows, _ = raw_dao.calls[0]
    assert {row["ts_code"] for row in filtered_rows} == {"000300.SH"}
    assert raw_dao.deleted_ranges == [(date(2026, 4, 17), date(2026, 4, 17))]
    derived_spy.assert_called_once()
    assert derived_spy.call_args.kwargs["ts_codes"] == ["000905.SH"]
    replace_spy.assert_called_once()
    assert result.rows_written == 2
    assert result.conflict_strategy == "index_period_upsert"
