from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

pytest.importorskip("pyarrow")

from lake_console.backend.app.services.parquet_writer import read_parquet_rows
from lake_console.backend.app.services.stk_mins_clean_service import StkMinsCleanService


def test_bootstrap_clean_from_raw_copies_partition_without_touching_raw(tmp_path) -> None:
    _write_raw_partition(
        tmp_path,
        freq=1,
        trade_date="2026-04-24",
        rows=[_mins_row("000001.SZ", 1, "2026-04-24 10:00:00")],
    )

    dry_run = StkMinsCleanService(lake_root=tmp_path, progress=lambda _: None).bootstrap_clean_from_raw(
        freqs=[1],
        start_date=date(2026, 4, 24),
        end_date=date(2026, 4, 24),
        dry_run=True,
        apply=False,
    )

    clean_file = tmp_path / "research" / "stk_mins_by_date_clean" / "freq=1" / "trade_date=2026-04-24" / "part-000.parquet"
    assert dry_run["raw_partitions"] == 1
    assert dry_run["raw_rows"] == 1
    assert dry_run["write_intent"] is False
    assert not clean_file.exists()

    summary = StkMinsCleanService(lake_root=tmp_path, progress=lambda _: None).bootstrap_clean_from_raw(
        freqs=[1],
        start_date=date(2026, 4, 24),
        end_date=date(2026, 4, 24),
        dry_run=False,
        apply=True,
    )

    raw_file = tmp_path / "raw_tushare" / "stk_mins_by_date" / "freq=1" / "trade_date=2026-04-24" / "part-000.parquet"
    assert summary["written_partitions"] == 1
    assert summary["written_rows"] == 1
    assert raw_file.exists()
    assert read_parquet_rows(clean_file)[0]["ts_code"] == "000001.SZ"


def test_build_security_identity_map_infers_namechange_alias(tmp_path) -> None:
    _write_stock_basic(tmp_path, [{"ts_code": "302132.SZ", "list_date": "20100827", "delist_date": None}])
    _write_namechange(
        tmp_path,
        [
            {"ts_code": "300114.SZ", "name": "中航电测", "start_date": date(2010, 8, 27), "end_date": date(2025, 2, 16)},
            {"ts_code": "300114.SZ", "name": "中航成飞", "start_date": date(2025, 2, 17), "end_date": None},
            {"ts_code": "302132.SZ", "name": "中航电测", "start_date": date(2010, 8, 27), "end_date": date(2025, 2, 16)},
            {"ts_code": "302132.SZ", "name": "中航成飞", "start_date": date(2025, 2, 17), "end_date": None},
        ],
    )

    summary = StkMinsCleanService(lake_root=tmp_path, progress=lambda _: None).build_security_identity_map(
        dry_run=True,
        apply=False,
    )

    rows_by_source = {row["source_ts_code"]: row for row in summary["samples"]}
    assert summary["identity_rows"] == 2
    assert rows_by_source["300114.SZ"]["latest_ts_code"] == "302132.SZ"
    assert rows_by_source["300114.SZ"]["identity_source"] == "namechange"
    assert rows_by_source["300114.SZ"]["effective_list_date"] == date(2010, 8, 27)
    assert "identity_id" not in rows_by_source["300114.SZ"]


def test_plan_rebuild_clean_counts_filters_and_kept_rows(tmp_path) -> None:
    _write_stock_basic(tmp_path, [{"ts_code": "302132.SZ", "list_date": "20100827", "delist_date": None}])
    _write_namechange(
        tmp_path,
        [
            {"ts_code": "300114.SZ", "name": "中航电测", "start_date": date(2010, 8, 27), "end_date": date(2025, 2, 16)},
            {"ts_code": "300114.SZ", "name": "中航成飞", "start_date": date(2025, 2, 17), "end_date": None},
            {"ts_code": "302132.SZ", "name": "中航电测", "start_date": date(2010, 8, 27), "end_date": date(2025, 2, 16)},
            {"ts_code": "302132.SZ", "name": "中航成飞", "start_date": date(2025, 2, 17), "end_date": None},
        ],
    )
    _write_raw_partition(
        tmp_path,
        freq=1,
        trade_date="2010-08-26",
        rows=[_mins_row("300114.SZ", 1, "2010-08-26 10:00:00")],
    )
    _write_raw_partition(
        tmp_path,
        freq=1,
        trade_date="2010-08-27",
        rows=[
            _mins_row("300114.SZ", 1, "2010-08-27 10:00:00", close=10.1),
            _mins_row("300114.SZ", 1, "2010-08-27 10:01:00", close=0.0),
            _mins_row("999999.SZ", 1, "2010-08-27 10:02:00", close=8.0),
        ],
    )

    summary = StkMinsCleanService(lake_root=tmp_path, progress=lambda _: None).plan_rebuild_clean(
        freqs=[1],
        start_date=date(2010, 8, 26),
        end_date=date(2010, 8, 27),
        sample_limit=10,
    )

    assert summary["mode"] == "dry_run"
    assert summary["raw_rows"] == 4
    assert summary["kept_rows"] == 1
    assert summary["filter_reasons"] == {
        "before_list_date": 1,
        "identity_missing": 1,
        "invalid_price": 1,
    }
    assert summary["write_intent"] is False


def test_plan_rebuild_clean_filters_delisted_security_entirely(tmp_path) -> None:
    _write_stock_basic(tmp_path, [{"ts_code": "000002.SZ", "list_date": "20100101", "delist_date": "20200101"}])
    _write_raw_partition(
        tmp_path,
        freq=1,
        trade_date="2019-12-31",
        rows=[_mins_row("000002.SZ", 1, "2019-12-31 10:00:00")],
    )

    summary = StkMinsCleanService(lake_root=tmp_path, progress=lambda _: None).plan_rebuild_clean(
        freqs=[1],
        start_date=date(2019, 12, 31),
        end_date=date(2019, 12, 31),
    )

    assert summary["raw_rows"] == 1
    assert summary["kept_rows"] == 0
    assert summary["filter_reasons"] == {"delisted_security": 1}


def test_rebuild_clean_apply_writes_normalized_clean_partition_without_touching_raw(tmp_path) -> None:
    _write_stock_basic(tmp_path, [{"ts_code": "302132.SZ", "list_date": "20100827", "delist_date": None}])
    _write_namechange(
        tmp_path,
        [
            {"ts_code": "300114.SZ", "name": "中航电测", "start_date": date(2010, 8, 27), "end_date": date(2025, 2, 16)},
            {"ts_code": "300114.SZ", "name": "中航成飞", "start_date": date(2025, 2, 17), "end_date": None},
            {"ts_code": "302132.SZ", "name": "中航电测", "start_date": date(2010, 8, 27), "end_date": date(2025, 2, 16)},
            {"ts_code": "302132.SZ", "name": "中航成飞", "start_date": date(2025, 2, 17), "end_date": None},
        ],
    )
    _write_raw_partition(
        tmp_path,
        freq=1,
        trade_date="2010-08-27",
        rows=[
            _mins_row("300114.SZ", 1, "2010-08-27 10:00:00", close=10.1),
            _mins_row("300114.SZ", 1, "2010-08-27 10:01:00", close=0.0),
        ],
    )
    _write_parquet(
        tmp_path / "research" / "stk_mins_by_date_clean" / "freq=1" / "trade_date=2010-08-27" / "part-old.parquet",
        [_mins_row("300114.SZ", 1, "2010-08-27 10:01:00", close=0.0)],
    )

    summary = StkMinsCleanService(lake_root=tmp_path, progress=lambda _: None).rebuild_clean_from_raw(
        freqs=[1],
        start_date=date(2010, 8, 27),
        end_date=date(2010, 8, 27),
        dry_run=False,
        apply=True,
    )

    clean_file = tmp_path / "research" / "stk_mins_by_date_clean" / "freq=1" / "trade_date=2010-08-27" / "part-000.parquet"
    raw_file = tmp_path / "raw_tushare" / "stk_mins_by_date" / "freq=1" / "trade_date=2010-08-27" / "part-000.parquet"
    clean_rows = read_parquet_rows(clean_file)
    raw_rows = read_parquet_rows(raw_file)
    assert summary["mode"] == "apply"
    assert summary["raw_rows"] == 2
    assert summary["kept_rows"] == 1
    assert summary["filter_reasons"] == {"invalid_price": 1}
    assert len(clean_rows) == 1
    assert clean_rows[0]["ts_code"] == "302132.SZ"
    assert "source_ts_code" not in clean_rows[0]
    assert "identity_id" not in clean_rows[0]
    assert "list_date" not in clean_rows[0]
    assert "delist_date" not in clean_rows[0]
    assert "identity_version" not in clean_rows[0]
    assert len(raw_rows) == 2
    assert {row["ts_code"] for row in raw_rows} == {"300114.SZ"}


def test_audit_clean_completeness_writes_issue_ledger_without_mutating_clean_rows(tmp_path) -> None:
    _write_stock_basic(
        tmp_path,
        [
            {"ts_code": "000001.SZ", "list_date": "20100101", "delist_date": None},
            {"ts_code": "000002.SZ", "list_date": "20100101", "delist_date": "20200101"},
        ],
    )
    clean_file = tmp_path / "research" / "stk_mins_by_date_clean" / "freq=1" / "trade_date=2026-04-24" / "part-000.parquet"
    _write_parquet(
        clean_file,
        [
            _mins_row("000001.SZ", 1, "2026-04-24 10:00:00", close=10.1),
            _mins_row("000001.SZ", 1, "2026-04-24 10:01:00", close=0.0),
            _mins_row("000002.SZ", 1, "2026-04-24 10:00:00", close=9.8),
        ],
    )

    summary = StkMinsCleanService(lake_root=tmp_path, progress=lambda _: None).audit_clean_completeness(
        freqs=[1],
        start_date=date(2026, 4, 24),
        end_date=date(2026, 4, 24),
        write_ledger=True,
        sample_limit=20,
    )

    ledger_file = tmp_path / "manifest" / "stk_mins_quality" / "clean_completeness_issue_ledger.parquet"
    ledger_rows = read_parquet_rows(ledger_file)
    clean_rows = read_parquet_rows(clean_file)
    issue_types = {row["issue_type"] for row in ledger_rows}
    assert summary["status"] == "failed"
    assert summary["ledger"]["written_rows"] == len(ledger_rows)
    assert {"invalid_price", "delisted_security", "missing_intraday_bar"}.issubset(issue_types)
    assert all("issue_id" not in row for row in clean_rows)
    assert all("issue_type" not in row for row in clean_rows)
    assert all("source_ts_code" not in row for row in clean_rows)
    assert len(clean_rows) == 3


def _write_stock_basic(root, rows: list[dict[str, object]]) -> None:
    _write_parquet(root / "manifest" / "security_universe" / "tushare_stock_basic.parquet", rows)


def _write_namechange(root, rows: list[dict[str, object]]) -> None:
    normalized = []
    for row in rows:
        item = dict(row)
        item.setdefault("ann_date", None)
        item.setdefault("change_reason", "改名")
        normalized.append(item)
    _write_parquet(root / "manifest" / "security_reference" / "tushare_namechange.parquet", normalized)


def _write_raw_partition(root, *, freq: int, trade_date: str, rows: list[dict[str, object]]) -> None:
    _write_parquet(
        root / "raw_tushare" / "stk_mins_by_date" / f"freq={freq}" / f"trade_date={trade_date}" / "part-000.parquet",
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
        "open": 10.0 if close > 0 else 0.0,
        "close": close,
        "high": 10.2 if close > 0 else 0.0,
        "low": 9.9 if close > 0 else 0.0,
        "vol": 1000,
        "amount": 10100.0,
        "exchange": None,
        "vwap": None,
    }
