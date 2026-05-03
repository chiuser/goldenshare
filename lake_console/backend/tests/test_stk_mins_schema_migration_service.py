from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

pa = pytest.importorskip("pyarrow")
pq = pytest.importorskip("pyarrow.parquet")

from lake_console.backend.app.catalog.tushare_stk_mins import STK_MINS_FIELDS
from lake_console.backend.app.services.stk_mins_schema_migration_service import StkMinsSchemaMigrationService


def test_stk_mins_schema_migration_adds_columns_and_timestamp(tmp_path) -> None:
    parquet_file = _write_old_stk_mins_file(tmp_path)

    summary = StkMinsSchemaMigrationService(lake_root=tmp_path, progress=lambda _: None).migrate(
        dry_run=False,
        apply=True,
        freq=30,
        trade_date=date(2026, 4, 24),
    )

    assert summary["action_counts"] == {"migrated": 1}
    schema = pq.read_schema(parquet_file)
    assert schema.names == list(STK_MINS_FIELDS)
    assert pa.types.is_timestamp(schema.field("trade_time").type)
    assert pa.types.is_integer(schema.field("freq").type)
    assert pa.types.is_integer(schema.field("vol").type)
    frame = pd.read_parquet(parquet_file, engine="pyarrow")
    assert frame["freq"].tolist() == [30, 30]
    assert frame["exchange"].isna().all()
    assert frame["vwap"].isna().all()


def test_stk_mins_schema_migration_dry_run_does_not_write(tmp_path) -> None:
    parquet_file = _write_old_stk_mins_file(tmp_path)

    summary = StkMinsSchemaMigrationService(lake_root=tmp_path, progress=lambda _: None).migrate(
        dry_run=True,
        apply=False,
        freq=30,
        trade_date=date(2026, 4, 24),
    )

    assert summary["action_counts"] == {"would_migrate": 1}
    schema = pq.read_schema(parquet_file)
    assert "exchange" not in schema.names
    assert not pa.types.is_timestamp(schema.field("trade_time").type)


def test_stk_mins_schema_migration_skips_current_file(tmp_path) -> None:
    parquet_file = _write_current_stk_mins_file(tmp_path)

    summary = StkMinsSchemaMigrationService(lake_root=tmp_path, progress=lambda _: None).migrate(
        dry_run=True,
        apply=False,
        freq=30,
        trade_date=date(2026, 4, 24),
    )

    assert summary["action_counts"] == {"skip_current": 1}
    assert pq.read_schema(parquet_file).names == list(STK_MINS_FIELDS)


def _write_old_stk_mins_file(root) -> object:
    path = root / "raw_tushare" / "stk_mins_by_date" / "freq=30" / "trade_date=2026-04-24" / "part-00000.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(
        [
            {
                "ts_code": "600000.SH",
                "trade_time": "2026-04-24 10:00:00",
                "open": 10.0,
                "close": 10.2,
                "high": 10.3,
                "low": 9.9,
                "vol": 1000.0,
                "amount": 10100.0,
            },
            {
                "ts_code": "600000.SH",
                "trade_time": "2026-04-24 10:30:00",
                "open": 10.2,
                "close": 10.4,
                "high": 10.5,
                "low": 10.1,
                "vol": 2000.0,
                "amount": 20500.0,
            },
        ]
    )
    frame.to_parquet(path, index=False, engine="pyarrow", compression="zstd")
    return path


def _write_current_stk_mins_file(root) -> object:
    path = root / "raw_tushare" / "stk_mins_by_date" / "freq=30" / "trade_date=2026-04-24" / "part-00000.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(
        [
            {
                "ts_code": "600000.SH",
                "freq": 30,
                "trade_time": pd.Timestamp("2026-04-24 10:00:00"),
                "open": 10.0,
                "close": 10.2,
                "high": 10.3,
                "low": 9.9,
                "vol": 1000,
                "amount": 10100.0,
                "exchange": None,
                "vwap": None,
            }
        ],
        columns=list(STK_MINS_FIELDS),
    )
    frame.to_parquet(path, index=False, engine="pyarrow", compression="zstd")
    return path
