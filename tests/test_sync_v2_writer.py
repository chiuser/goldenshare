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

    def bulk_upsert(self, rows: list[dict], conflict_columns: list[str] | None = None) -> int:
        self.calls.append((rows, conflict_columns))
        return self.written


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
