from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

pytest.importorskip("duckdb")
pytest.importorskip("pyarrow")

from lake_console.backend.app.services.stk_mins_raw_recovery_service import StkMinsRawRecoveryService


def test_audit_raw_integrity_detects_single_symbol_overwrite(tmp_path) -> None:
    _write_required_manifests(tmp_path)
    _write_raw_partition(tmp_path, freq=1, trade_date="2026-04-24", rows=[_mins_row("300114.SZ", 1, "2026-04-24 10:00:00")])
    _write_research_month(
        tmp_path,
        freq=1,
        trade_month="2026-04",
        rows=[
            _mins_row("000001.SZ", 1, "2026-04-24 10:00:00"),
            _mins_row("300114.SZ", 1, "2026-04-24 10:00:00"),
        ],
    )

    summary = StkMinsRawRecoveryService(lake_root=tmp_path).audit_raw_integrity(
        freqs=[1],
        start_date=date(2026, 4, 24),
        end_date=date(2026, 4, 24),
        patch_ts_code="300114.SZ",
        sample_limit=5,
    )

    freq_summary = summary["freq_summaries"][0]
    assert summary["mode"] == "read_only"
    assert summary["write_intent"] is False
    assert freq_summary["severely_low_partitions"] == 1
    assert freq_summary["research_has_more_rows_issue_partitions"] == 1
    assert freq_summary["issue_samples"][0]["raw_rows"] == 1
    assert freq_summary["issue_samples"][0]["research_rows"] == 2


def _write_required_manifests(root) -> None:
    _write_parquet(
        root / "manifest" / "trading_calendar" / "tushare_trade_cal.parquet",
        [{"cal_date": date(2026, 4, 24), "is_open": True}],
    )
    _write_parquet(
        root / "manifest" / "security_universe" / "tushare_stock_basic.parquet",
        [
            {"ts_code": "000001.SZ", "list_date": date(2000, 1, 1), "delist_date": None},
            {"ts_code": "300114.SZ", "list_date": date(2010, 8, 27), "delist_date": None},
        ],
    )


def _write_raw_partition(root, *, freq: int, trade_date: str, rows: list[dict[str, object]]) -> None:
    _write_parquet(
        root / "raw_tushare" / "stk_mins_by_date" / f"freq={freq}" / f"trade_date={trade_date}" / "part-000.parquet",
        rows,
    )


def _write_research_month(root, *, freq: int, trade_month: str, rows: list[dict[str, object]]) -> None:
    _write_parquet(
        root / "research" / "stk_mins_by_symbol_month" / f"freq={freq}" / f"trade_month={trade_month}" / "bucket=0" / "part-000.parquet",
        rows,
    )


def _write_parquet(path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_parquet(path, index=False, engine="pyarrow", compression="zstd")


def _mins_row(ts_code: str, freq: int, trade_time: str, *, close: float = 10.1) -> dict[str, object]:
    return {
        "ts_code": ts_code,
        "freq": freq,
        "trade_time": pd.Timestamp(trade_time),
        "open": 10.0,
        "close": close,
        "high": 10.2,
        "low": 9.9,
        "vol": 1000,
        "amount": 10100.0,
        "exchange": None,
        "vwap": None,
    }
