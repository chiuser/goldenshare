from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from lake_console.backend.app.services.affected_partition import AffectedPartition
from lake_console.backend.app.services.indicators.indicator_recalc_queue import IndicatorRecalcQueueService
from lake_console.backend.app.services.parquet_writer import read_parquet_rows
from lake_console.backend.app.services.stk_mins_clean_next_gate import CleanNextGateStatus, CleanNextPartitionGateService
from lake_console.backend.app.services.stk_mins_clean_next_refresh_service import CleanNextRefreshService


def test_clean_next_refresh_rebuilds_partition_writes_ledger_and_passed_gate(tmp_path: Path) -> None:
    _write_stock_basic(tmp_path)
    _write_raw_partition(
        tmp_path,
        freq=1,
        trade_date=date(2026, 5, 8),
        rows=[
            _raw_row("000001.SZ", 1, f"2026-05-08 {hour:02d}:{minute:02d}:00")
            for hour, minute in _minute_times(include_after_hours=False)
        ],
    )

    summary = CleanNextRefreshService(lake_root=tmp_path, progress=lambda _: None).refresh(
        affected_partitions=[_affected_partition(tmp_path, freq=1, trade_date=date(2026, 5, 8))],
        dry_run=False,
        apply=True,
    )

    clean_file = tmp_path / "research" / "stk_mins_by_date_clean_next" / "freq=1" / "trade_date=2026-05-08" / "part-000.parquet"
    gate_rows = CleanNextPartitionGateService(lake_root=tmp_path).read_statuses()
    assert summary["status"] == "passed"
    assert summary["partition_results"][0]["issue_count"] == 0
    assert clean_file.exists()
    assert len(read_parquet_rows(clean_file)) == 241
    assert gate_rows[0]["status"] == "passed"
    assert gate_rows[0]["issue_count"] == 0
    assert gate_rows[0]["raw_rows"] == 241
    assert gate_rows[0]["clean_rows"] == 241
    event_rows = _source_event_rows(tmp_path)
    queue_items = IndicatorRecalcQueueService(lake_root=tmp_path).list_items()
    assert summary["indicator_recalc_events"] == 1
    assert len(event_rows) == 1
    assert event_rows[0]["layer"] == "research/stk_mins_by_date_clean_next"
    assert event_rows[0]["freq"] == 1
    assert event_rows[0]["trade_date"] == "2026-05-08"
    assert len(queue_items) == 1
    assert queue_items[0]["freq_value"] == 1
    assert queue_items[0]["invalid_from_time"].date() == date(2026, 5, 8)


def test_clean_next_refresh_blocks_gate_when_scoped_audit_finds_issue(tmp_path: Path) -> None:
    _write_stock_basic(tmp_path)
    _write_raw_partition(
        tmp_path,
        freq=1,
        trade_date=date(2026, 5, 8),
        rows=[
            _raw_row("000001.SZ", 1, f"2026-05-08 {hour:02d}:{minute:02d}:00")
            for hour, minute in _minute_times(include_after_hours=False)[:-1]
        ],
    )

    summary = CleanNextRefreshService(lake_root=tmp_path, progress=lambda _: None).refresh(
        affected_partitions=[_affected_partition(tmp_path, freq=1, trade_date=date(2026, 5, 8))],
        dry_run=False,
        apply=True,
    )

    gate_rows = CleanNextPartitionGateService(lake_root=tmp_path).read_statuses()
    ledger_rows = read_parquet_rows(tmp_path / "manifest" / "stk_mins_quality" / "clean_next_completeness_issue_ledger.parquet")
    assert summary["status"] == "blocked"
    assert summary["partition_results"][0]["issue_count"] == 1
    assert gate_rows[0]["status"] == "blocked"
    assert gate_rows[0]["issue_count"] == 1
    assert len(ledger_rows) == 1
    assert ledger_rows[0]["issue_state"] == "open"
    assert ledger_rows[0]["severity"] == "block"
    assert summary["indicator_recalc_events"] == 0
    assert _source_event_rows(tmp_path) == []
    assert IndicatorRecalcQueueService(lake_root=tmp_path).list_items() == []


def test_clean_next_refresh_marks_gate_publishing_before_rebuild(tmp_path: Path) -> None:
    _write_stock_basic(tmp_path)
    _write_raw_partition(
        tmp_path,
        freq=1,
        trade_date=date(2026, 5, 8),
        rows=[_raw_row("000001.SZ", 1, "2026-05-08 10:00:00")],
    )
    gate_service = CleanNextPartitionGateService(lake_root=tmp_path)
    gate_service.write_statuses(
        [
            CleanNextGateStatus(
                freq=1,
                trade_date=date(2026, 5, 8),
                clean_partition_path="research/stk_mins_by_date_clean_next/freq=1/trade_date=2026-05-08",
                source_run_id="old-source-run",
                clean_run_id="old-clean-run",
                write_revision="old-revision",
                status="passed",
                issue_count=0,
                raw_rows=241,
                clean_rows=241,
                ledger_path=str(tmp_path / "manifest" / "stk_mins_quality" / "clean_next_completeness_issue_ledger.parquet"),
                message="old passed gate",
            )
        ],
        run_id="seed-old-passed-gate",
    )
    service = CleanNextRefreshService(lake_root=tmp_path, progress=lambda _: None)

    def fail_rebuild(**_: object) -> dict[str, object]:
        raise RuntimeError("boom")

    service.clean_service._rebuild_formal_clean_next_from_raw = fail_rebuild  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="boom"):
        service.refresh(
            affected_partitions=[_affected_partition(tmp_path, freq=1, trade_date=date(2026, 5, 8))],
            dry_run=False,
            apply=True,
        )

    gate_rows = gate_service.read_statuses()
    assert len(gate_rows) == 1
    assert gate_rows[0]["status"] == "publishing"
    assert gate_rows[0]["source_run_id"] == "raw-run-1"
    assert gate_rows[0]["write_revision"] == "raw-run-1:raw_tushare:freq=1:trade_date=2026-05-08"
    assert _source_event_rows(tmp_path) == []
    assert IndicatorRecalcQueueService(lake_root=tmp_path).list_items() == []


def test_clean_next_refresh_keeps_gate_publishing_when_queue_upsert_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_stock_basic(tmp_path)
    _write_raw_partition(
        tmp_path,
        freq=1,
        trade_date=date(2026, 5, 8),
        rows=[
            _raw_row("000001.SZ", 1, f"2026-05-08 {hour:02d}:{minute:02d}:00")
            for hour, minute in _minute_times(include_after_hours=False)
        ],
    )
    gate_service = CleanNextPartitionGateService(lake_root=tmp_path)
    gate_service.write_statuses(
        [
            CleanNextGateStatus(
                freq=1,
                trade_date=date(2026, 5, 8),
                clean_partition_path="research/stk_mins_by_date_clean_next/freq=1/trade_date=2026-05-08",
                source_run_id="old-source-run",
                clean_run_id="old-clean-run",
                write_revision="old-revision",
                status="passed",
                issue_count=0,
                raw_rows=241,
                clean_rows=241,
                ledger_path=str(tmp_path / "manifest" / "stk_mins_quality" / "clean_next_completeness_issue_ledger.parquet"),
                message="old passed gate",
            )
        ],
        run_id="seed-old-passed-gate",
    )

    def fail_record(
        self: IndicatorRecalcQueueService,
        *,
        layer: str,
        partitions: list[dict[str, object]],
        run_id: str,
    ) -> list[dict[str, object]]:
        raise RuntimeError("queue boom")

    monkeypatch.setattr(IndicatorRecalcQueueService, "record_source_partitions_replaced", fail_record)

    with pytest.raises(RuntimeError, match="queue boom"):
        CleanNextRefreshService(lake_root=tmp_path, progress=lambda _: None).refresh(
            affected_partitions=[_affected_partition(tmp_path, freq=1, trade_date=date(2026, 5, 8))],
            dry_run=False,
            apply=True,
        )

    gate_rows = gate_service.read_statuses()
    assert len(gate_rows) == 1
    assert gate_rows[0]["status"] == "publishing"
    assert gate_rows[0]["source_run_id"] == "raw-run-1"
    assert gate_rows[0]["write_revision"] == "raw-run-1:raw_tushare:freq=1:trade_date=2026-05-08"
    assert _source_event_rows(tmp_path) == []
    assert IndicatorRecalcQueueService(lake_root=tmp_path).list_items() == []


def test_clean_next_refresh_range_publishes_gate_queue_and_derived_hints(tmp_path: Path) -> None:
    _write_stock_basic(tmp_path)
    for freq in (30, 60):
        _write_raw_partition(
            tmp_path,
            freq=freq,
            trade_date=date(2026, 5, 8),
            rows=[_raw_row("000001.SZ", freq, f"2026-05-08 {time_text}") for time_text in _bar_times_for_freq(freq)],
        )

    summary = CleanNextRefreshService(lake_root=tmp_path, progress=lambda _: None).refresh_raw_range(
        freqs=[30, 60],
        start_date=date(2026, 5, 8),
        end_date=date(2026, 5, 8),
        dry_run=False,
        apply=True,
        replace_existing=False,
    )

    gate_rows = CleanNextPartitionGateService(lake_root=tmp_path).read_statuses()
    event_rows = _source_event_rows(tmp_path)
    assert summary["status"] == "passed"
    assert summary["indicator_recalc_events"] == 2
    assert summary["derived_rebuild_required"] is True
    assert summary["derived_rebuild_requirements"] == [
        {
            "source_freq": 30,
            "target_freq": 90,
            "start_date": "2026-05-08",
            "end_date": "2026-05-08",
            "rebuild_owner": "orchestrator",
        },
        {
            "source_freq": 60,
            "target_freq": 120,
            "start_date": "2026-05-08",
            "end_date": "2026-05-08",
            "rebuild_owner": "orchestrator",
        },
    ]
    assert {row["status"] for row in gate_rows} == {"passed"}
    assert len(event_rows) == 2
    assert {row["freq"] for row in event_rows} == {30, 60}


def test_clean_next_refresh_range_refuses_existing_partition_without_replace_flag(tmp_path: Path) -> None:
    _write_stock_basic(tmp_path)
    _write_raw_partition(
        tmp_path,
        freq=1,
        trade_date=date(2026, 5, 8),
        rows=[_raw_row("000001.SZ", 1, "2026-05-08 10:00:00")],
    )
    _write_parquet(
        tmp_path / "research" / "stk_mins_by_date_clean_next" / "freq=1" / "trade_date=2026-05-08" / "part-000.parquet",
        [_raw_row("000001.SZ", 1, "2026-05-08 10:00:00")],
    )

    with pytest.raises(RuntimeError, match="目标分区已存在"):
        CleanNextRefreshService(lake_root=tmp_path, progress=lambda _: None).refresh_raw_range(
            freqs=[1],
            start_date=date(2026, 5, 8),
            end_date=date(2026, 5, 8),
            dry_run=False,
            apply=True,
            replace_existing=False,
        )


def _write_stock_basic(root: Path) -> None:
    _write_parquet(
        root / "manifest" / "security_universe" / "tushare_stock_basic.parquet",
        [{"ts_code": "000001.SZ", "list_date": "20100101", "delist_date": None}],
    )


def _write_raw_partition(root: Path, *, freq: int, trade_date: date, rows: list[dict[str, object]]) -> None:
    _write_parquet(
        root / "raw_tushare" / "stk_mins_by_date" / f"freq={freq}" / f"trade_date={trade_date.isoformat()}" / "part-000.parquet",
        rows,
    )


def _write_parquet(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_parquet(path, index=False, engine="pyarrow", compression="zstd")


def _source_event_rows(root: Path) -> list[dict[str, object]]:
    event_file = root / "manifest" / "source_partition_events" / "stk_mins.jsonl"
    if not event_file.exists():
        return []
    return [json.loads(line) for line in event_file.read_text(encoding="utf-8").splitlines() if line.strip()]


def _raw_row(ts_code: str, freq: int, trade_time: str) -> dict[str, object]:
    return {
        "ts_code": ts_code,
        "freq": freq,
        "trade_time": pd.Timestamp(trade_time),
        "open": 10.0,
        "close": 10.1,
        "high": 10.2,
        "low": 9.9,
        "vol": 1000,
        "amount": 10100.0,
        "exchange": None,
        "vwap": None,
    }


def _affected_partition(root: Path, *, freq: int, trade_date: date) -> AffectedPartition:
    partition_path = root / "raw_tushare" / "stk_mins_by_date" / f"freq={freq}" / f"trade_date={trade_date.isoformat()}"
    return AffectedPartition(
        dataset_key="stk_mins",
        source_key="tushare",
        layer="raw_tushare",
        partition_grain="trade_date",
        partition_values={"freq": str(freq), "trade_date": trade_date.isoformat()},
        partition_path=str(partition_path.relative_to(root)),
        source_run_id="raw-run-1",
        write_revision=f"raw-run-1:raw_tushare:freq={freq}:trade_date={trade_date.isoformat()}",
        rows_written=len(read_parquet_rows(partition_path / "part-000.parquet")),
        bytes_written=sum(item.stat().st_size for item in partition_path.glob("*.parquet")),
    )


def _minute_times(*, include_after_hours: bool) -> list[tuple[int, int]]:
    times = [(value // 60, value % 60) for value in range(9 * 60 + 30, 11 * 60 + 30 + 1)]
    times.extend((value // 60, value % 60) for value in range(13 * 60 + 1, 15 * 60 + 1))
    if include_after_hours:
        times.extend((15, minute) for minute in range(1, 31))
    return times


def _bar_times_for_freq(freq: int) -> list[str]:
    if freq == 30:
        return ["09:30:00", "10:00:00", "10:30:00", "11:00:00", "11:30:00", "13:30:00", "14:00:00", "14:30:00", "15:00:00"]
    if freq == 60:
        return ["10:30:00", "11:30:00", "13:30:00", "14:30:00", "15:00:00"]
    raise ValueError(f"unsupported freq={freq}")
