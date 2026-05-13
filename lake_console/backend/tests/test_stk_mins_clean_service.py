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


def test_formal_clean_next_keeps_zero_price_rows_and_writes_formal_schema(tmp_path) -> None:
    _write_stock_basic(tmp_path, [{"ts_code": "600988.SH", "list_date": "20100101", "delist_date": None}])
    _write_raw_partition(
        tmp_path,
        freq=1,
        trade_date="2011-12-12",
        rows=[
            _mins_row("600988.SH", 1, "2011-12-12 09:34:00", open=9.35, close=9.36, high=9.36, low=0.0),
            _mins_row("600988.SH", 1, "2011-12-12 09:35:00", open=0.0, close=0.0, high=0.0, low=0.0, vol=0, amount=0.0),
        ],
    )

    dry_run = StkMinsCleanService(lake_root=tmp_path, progress=lambda _: None).plan_rebuild_formal_clean_next(
        freqs=[1],
        start_date=date(2011, 12, 12),
        end_date=date(2011, 12, 12),
    )
    assert dry_run["operation"] == "rebuild_stk_mins_by_date_clean_next"
    assert dry_run["kept_rows"] == 2
    assert dry_run["filtered_rows"] == 0
    assert dry_run["schema"] == [
        "ts_code",
        "freq",
        "trade_time",
        "open",
        "close",
        "high",
        "low",
        "vol",
        "amount",
        "exchange",
        "vwap",
    ]

    summary = StkMinsCleanService(lake_root=tmp_path, progress=lambda _: None).rebuild_formal_clean_next_from_raw(
        freqs=[1],
        start_date=date(2011, 12, 12),
        end_date=date(2011, 12, 12),
        dry_run=False,
        apply=True,
    )

    clean_file = tmp_path / "research" / "stk_mins_by_date_clean_next" / "freq=1" / "trade_date=2011-12-12" / "part-000.parquet"
    rows = read_parquet_rows(clean_file)
    assert summary["kept_rows"] == 2
    assert rows
    assert list(rows[0]) == dry_run["schema"]
    assert "trade_date" not in rows[0]
    assert "source_ts_code" not in rows[0]
    assert "identity_id" not in rows[0]
    assert {row["trade_time"].strftime("%H:%M:%S") for row in rows} == {"09:34:00", "09:35:00"}


def test_formal_clean_next_refuses_to_overwrite_existing_partition_without_flag(tmp_path) -> None:
    _write_stock_basic(tmp_path, [{"ts_code": "000001.SZ", "list_date": "20100101", "delist_date": None}])
    _write_raw_partition(
        tmp_path,
        freq=1,
        trade_date="2026-03-02",
        rows=[_mins_row("000001.SZ", 1, "2026-03-02 10:00:00")],
    )
    service = StkMinsCleanService(lake_root=tmp_path, progress=lambda _: None)
    service.rebuild_formal_clean_next_from_raw(
        freqs=[1],
        start_date=date(2026, 3, 2),
        end_date=date(2026, 3, 2),
        dry_run=False,
        apply=True,
    )

    with pytest.raises(RuntimeError, match="clean candidate 目标分区已存在"):
        service.rebuild_formal_clean_next_from_raw(
            freqs=[1],
            start_date=date(2026, 3, 2),
            end_date=date(2026, 3, 2),
            dry_run=False,
            apply=True,
        )


def test_audit_formal_clean_next_allows_zero_price_structure_and_blocks_duplicates(tmp_path) -> None:
    _write_stock_basic(tmp_path, [{"ts_code": "600988.SH", "list_date": "20100101", "delist_date": None}])
    _write_parquet(
        tmp_path / "research" / "stk_mins_by_date_clean_next" / "freq=1" / "trade_date=2011-12-12" / "part-000.parquet",
        [
            _mins_row("600988.SH", 1, "2011-12-12 09:34:00", open=9.35, close=9.36, high=9.36, low=0.0),
            _mins_row("600988.SH", 1, "2011-12-12 09:34:00", open=9.35, close=9.36, high=9.36, low=0.0),
        ],
    )

    summary = StkMinsCleanService(lake_root=tmp_path, progress=lambda _: None).audit_formal_clean_next_layer(
        freqs=[1],
        start_date=date(2011, 12, 12),
        end_date=date(2011, 12, 12),
    )

    assert summary["status"] == "failed"
    assert summary["issue_type_counts"] == {"duplicate_same_payload": 1}
    assert "invalid_price_structure" not in summary["issue_type_counts"]


def test_audit_formal_clean_next_completeness_accepts_after_hours_extra_bars(tmp_path) -> None:
    _write_stock_basic(tmp_path, [{"ts_code": "000001.SZ", "list_date": "20100101", "delist_date": None}])
    rows = [
        _mins_row("000001.SZ", 1, f"2026-04-24 {hour:02d}:{minute:02d}:00")
        for hour, minute in _minute_times(include_after_hours=True)
    ]
    _write_parquet(
        tmp_path / "research" / "stk_mins_by_date_clean_next" / "freq=1" / "trade_date=2026-04-24" / "part-000.parquet",
        rows,
    )

    summary = StkMinsCleanService(lake_root=tmp_path, progress=lambda _: None).audit_formal_clean_next_completeness(
        freqs=[1],
        start_date=date(2026, 4, 24),
        end_date=date(2026, 4, 24),
    )

    assert summary["status"] == "success"
    assert summary["issue_count"] == 0


def test_audit_formal_clean_next_completeness_resolves_stale_ledger_when_no_issues(tmp_path) -> None:
    _write_stock_basic(tmp_path, [{"ts_code": "000001.SZ", "list_date": "20100101", "delist_date": None}])
    _write_parquet(
        tmp_path / "manifest" / "stk_mins_quality" / "clean_next_completeness_issue_ledger.parquet",
        [
            {
                "issue_id": "stale-issue",
                "gate": "G7",
                "issue_type": "missing_intraday_bar",
                "status": "needs_review",
                "latest_ts_code": "000001.SZ",
                "freq": 1,
                "trade_date": date(2026, 4, 24),
                "trade_time": None,
                "expected_value": "bar_count>=241",
                "actual_value": "bar_count=240",
                "evidence_dataset": "research/stk_mins_by_date_clean_next",
                "evidence_ref": "stale",
                "action": "stale",
                "reason": "stale historical ledger row",
                "created_at": pd.Timestamp("2026-05-13T00:00:00Z"),
                "resolved_at": None,
            }
        ],
    )
    rows = [
        _mins_row("000001.SZ", 1, f"2026-04-24 {hour:02d}:{minute:02d}:00")
        for hour, minute in _minute_times(include_after_hours=True)
    ]
    _write_parquet(
        tmp_path / "research" / "stk_mins_by_date_clean_next" / "freq=1" / "trade_date=2026-04-24" / "part-000.parquet",
        rows,
    )

    summary = StkMinsCleanService(lake_root=tmp_path, progress=lambda _: None).audit_formal_clean_next_completeness(
        freqs=[1],
        start_date=date(2026, 4, 24),
        end_date=date(2026, 4, 24),
        write_ledger=True,
    )

    ledger_file = tmp_path / "manifest" / "stk_mins_quality" / "clean_next_completeness_issue_ledger.parquet"
    assert summary["status"] == "success"
    assert summary["issue_count"] == 0
    assert summary["ledger"]["existing_rows"] == 1
    assert summary["ledger"]["new_records"] == 0
    assert summary["ledger"]["written_rows"] == 1
    assert summary["ledger"]["open_records"] == 0
    assert summary["ledger"]["resolved_records"] == 1
    assert summary["ledger"]["write_skipped"] is False
    ledger_rows = read_parquet_rows(ledger_file)
    assert len(ledger_rows) == 1
    assert ledger_rows[0]["ledger_schema_version"] == 2
    assert ledger_rows[0]["issue_state"] == "resolved"
    assert ledger_rows[0]["resolved_run_id"]
    assert ledger_rows[0]["partition_key"] == "freq=1/trade_date=2026-04-24"


def test_audit_formal_clean_next_completeness_keeps_one_open_record_for_repeated_issue(tmp_path) -> None:
    _write_stock_basic(tmp_path, [{"ts_code": "000001.SZ", "list_date": "20100101", "delist_date": None}])
    rows = [
        _mins_row("000001.SZ", 1, f"2026-04-24 {hour:02d}:{minute:02d}:00")
        for hour, minute in _minute_times(include_after_hours=False)[:-1]
    ]
    _write_parquet(
        tmp_path / "research" / "stk_mins_by_date_clean_next" / "freq=1" / "trade_date=2026-04-24" / "part-000.parquet",
        rows,
    )
    service = StkMinsCleanService(lake_root=tmp_path, progress=lambda _: None)

    first = service.audit_formal_clean_next_completeness(
        freqs=[1],
        start_date=date(2026, 4, 24),
        end_date=date(2026, 4, 24),
        write_ledger=True,
    )
    second = service.audit_formal_clean_next_completeness(
        freqs=[1],
        start_date=date(2026, 4, 24),
        end_date=date(2026, 4, 24),
        write_ledger=True,
    )

    ledger_file = tmp_path / "manifest" / "stk_mins_quality" / "clean_next_completeness_issue_ledger.parquet"
    ledger_rows = read_parquet_rows(ledger_file)
    assert first["issue_count"] == 1
    assert second["issue_count"] == 1
    assert len(ledger_rows) == 1
    assert ledger_rows[0]["issue_state"] == "open"
    assert ledger_rows[0]["severity"] == "block"
    assert ledger_rows[0]["seen_count"] == 2
    assert ledger_rows[0]["first_seen_run_id"]
    assert ledger_rows[0]["last_seen_run_id"]


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


def _mins_row(
    ts_code: str,
    freq: int,
    trade_time: str,
    *,
    open: float | None = None,
    close: float = 10.1,
    high: float | None = None,
    low: float | None = None,
    vol: int = 1000,
    amount: float = 10100.0,
) -> dict[str, object]:
    open_value = open if open is not None else (10.0 if close > 0 else 0.0)
    high_value = high if high is not None else (10.2 if close > 0 else 0.0)
    low_value = low if low is not None else (9.9 if close > 0 else 0.0)
    return {
        "ts_code": ts_code,
        "freq": freq,
        "trade_time": pd.Timestamp(trade_time),
        "open": open_value,
        "close": close,
        "high": high_value,
        "low": low_value,
        "vol": vol,
        "amount": amount,
        "exchange": None,
        "vwap": None,
    }


def _minute_times(*, include_after_hours: bool) -> list[tuple[int, int]]:
    times = [(value // 60, value % 60) for value in range(9 * 60 + 30, 11 * 60 + 30 + 1)]
    times.extend((value // 60, value % 60) for value in range(13 * 60 + 1, 15 * 60 + 1))
    if include_after_hours:
        times.extend((15, minute) for minute in range(1, 31))
    return times
