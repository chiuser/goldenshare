from __future__ import annotations

import math
from datetime import date, datetime

import pytest

from lake_console.backend.app.services.parquet_writer import read_parquet_rows, write_rows_to_parquet
from lake_console.backend.app.services.stk_mins_clean_next_gate import CleanNextGateStatus, CleanNextPartitionGateService
from lake_console.backend.app.services.stk_mins_research_service import StkMinsResearchService, stable_bucket


def test_rebuild_month_reads_clean_layer_and_buckets_by_canonical_ts_code(tmp_path) -> None:
    pytest.importorskip("pandas")
    pytest.importorskip("pyarrow")
    write_rows_to_parquet(
        [
            _bar("302132.SZ", "2025-02-14 10:00:00"),
        ],
        tmp_path / "research" / "stk_mins_by_date_clean_next" / "freq=30" / "trade_date=2025-02-14" / "part-000.parquet",
    )
    write_rows_to_parquet(
        [
            _bar("302132.SZ", "2025-02-17 10:00:00"),
        ],
        tmp_path / "research" / "stk_mins_by_date_clean_next" / "freq=30" / "trade_date=2025-02-17" / "part-000.parquet",
    )
    _write_passed_gate(tmp_path, freq=30, trade_date=date(2025, 2, 14))
    _write_passed_gate(tmp_path, freq=30, trade_date=date(2025, 2, 17))

    summary = StkMinsResearchService(lake_root=tmp_path, bucket_count=4, progress=lambda _: None).rebuild_month(
        freq=30,
        trade_month="2025-02",
    )

    bucket = stable_bucket(ts_code="302132.SZ", bucket_count=4)
    rows = read_parquet_rows(
        tmp_path
        / "research"
        / "stk_mins_by_symbol_month"
        / "freq=30"
        / "trade_month=2025-02"
        / f"bucket={bucket}"
        / "part-000.parquet"
    )
    assert summary["source_node_key"] == "clean_next_by_date"
    assert summary["source_rows"] == 2
    assert summary["written_rows"] == 2
    assert {row["ts_code"] for row in rows} == {"302132.SZ"}
    assert "source_ts_code" not in rows[0]
    assert "identity_id" not in rows[0]


def test_rebuild_month_keeps_optional_field_schema_stable(tmp_path) -> None:
    pytest.importorskip("pandas")
    pytest.importorskip("pyarrow")
    write_rows_to_parquet(
        [
            _bar("600000.SH", "2009-08-03 10:00:00", freq=5, exchange=None),
        ],
        tmp_path / "research" / "stk_mins_by_date_clean_next" / "freq=5" / "trade_date=2009-08-03" / "part-000.parquet",
    )
    write_rows_to_parquet(
        [
            _bar("600000.SH", "2009-08-04 10:00:00", freq=5, exchange="SSE"),
        ],
        tmp_path / "research" / "stk_mins_by_date_clean_next" / "freq=5" / "trade_date=2009-08-04" / "part-000.parquet",
    )
    _write_passed_gate(tmp_path, freq=5, trade_date=date(2009, 8, 3))
    _write_passed_gate(tmp_path, freq=5, trade_date=date(2009, 8, 4))

    summary = StkMinsResearchService(lake_root=tmp_path, bucket_count=4, progress=lambda _: None).rebuild_month(
        freq=5,
        trade_month="2009-08",
    )

    bucket = stable_bucket(ts_code="600000.SH", bucket_count=4)
    rows = read_parquet_rows(
        tmp_path
        / "research"
        / "stk_mins_by_symbol_month"
        / "freq=5"
        / "trade_month=2009-08"
        / f"bucket={bucket}"
        / "part-000.parquet"
    )
    assert summary["source_rows"] == 2
    assert summary["written_rows"] == 2
    assert _is_missing(rows[0]["exchange"])
    assert rows[1]["exchange"] == "SSE"


def _bar(ts_code: str, trade_time: str, *, freq: int = 30, exchange: str | None = None) -> dict[str, object]:
    return {
        "ts_code": ts_code,
        "freq": freq,
        "trade_date": trade_time[:10],
        "trade_time": datetime.fromisoformat(trade_time),
        "open": 10.0,
        "close": 10.0,
        "high": 10.0,
        "low": 10.0,
        "vol": 100.0,
        "amount": 1000.0,
        "exchange": exchange,
        "vwap": 10.0,
    }


def _write_passed_gate(root, *, freq: int, trade_date: date) -> None:
    CleanNextPartitionGateService(lake_root=root).write_statuses(
        [
            CleanNextGateStatus(
                freq=freq,
                trade_date=trade_date,
                clean_partition_path=f"research/stk_mins_by_date_clean_next/freq={freq}/trade_date={trade_date.isoformat()}",
                source_run_id="raw-run",
                clean_run_id="clean-run",
                write_revision=f"raw-run:freq={freq}:trade_date={trade_date.isoformat()}",
                status="passed",
                issue_count=0,
                raw_rows=1,
                clean_rows=1,
                ledger_path="manifest/stk_mins_quality/clean_next_completeness_issue_ledger.parquet",
                message="passed",
            )
        ],
        run_id=f"gate-run-{trade_date.isoformat()}",
    )


def _is_missing(value: object) -> bool:
    return value is None or (isinstance(value, float) and math.isnan(value))
