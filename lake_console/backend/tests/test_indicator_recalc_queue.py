from __future__ import annotations

import json
from datetime import date, datetime

import pytest

from lake_console.backend.app.cli.main import main
from lake_console.backend.app.services.indicators import IndicatorRecalcQueueService


def test_indicator_recalc_queue_records_source_event_and_pending_item(tmp_path) -> None:
    pytest.importorskip("pandas")
    pytest.importorskip("pyarrow")
    service = IndicatorRecalcQueueService(lake_root=tmp_path)

    summary = service.record_source_partition_replaced(
        layer="research/stk_mins_by_date_clean_next",
        freq=30,
        trade_date=date(2026, 4, 24),
        run_id="test-source-replace",
        written_rows=2,
    )

    event_rows = [
        json.loads(line)
        for line in (tmp_path / "manifest" / "source_partition_events" / "stk_mins.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    queue_items = service.list_items(include_done=True)
    assert summary["event"]["event_type"] == "partition_replaced"
    assert event_rows[0]["dataset_key"] == "stk_mins"
    assert event_rows[0]["layer"] == "research/stk_mins_by_date_clean_next"
    assert queue_items[0]["indicator_key"] == "macd"
    assert queue_items[0]["params_key"] == "12_26_9"
    assert queue_items[0]["freq_scope"] == "single"
    assert queue_items[0]["freq_value"] == 30
    assert queue_items[0]["security_scope"] == "all"
    assert queue_items[0]["ts_code"] is None
    assert queue_items[0]["invalid_from_time"] == datetime(2026, 4, 24)
    assert queue_items[0]["status"] == "pending"


def test_indicator_recalc_queue_dedupes_same_source_event(tmp_path) -> None:
    pytest.importorskip("pandas")
    pytest.importorskip("pyarrow")
    service = IndicatorRecalcQueueService(lake_root=tmp_path)

    first = service.record_source_partition_replaced(
        layer="research/stk_mins_by_date_clean_next",
        freq=30,
        trade_date=date(2026, 4, 24),
        run_id="test-source-replace",
        written_rows=2,
    )
    second = service.record_source_partition_replaced(
        layer="research/stk_mins_by_date_clean_next",
        freq=30,
        trade_date=date(2026, 4, 24),
        run_id="test-source-replace",
        written_rows=2,
    )

    event_lines = (tmp_path / "manifest/source_partition_events/stk_mins.jsonl").read_text(encoding="utf-8").splitlines()
    queue_items = service.list_items(include_done=True)
    assert first["event_written"] is True
    assert second["event_written"] is False
    assert len(event_lines) == 1
    assert len(queue_items) == 1


def test_indicator_recalc_queue_list_outputs_suggested_command_and_mark_done(tmp_path, capsys) -> None:
    pytest.importorskip("pandas")
    pytest.importorskip("pyarrow")
    service = IndicatorRecalcQueueService(lake_root=tmp_path)
    queue_id = service.record_source_partition_replaced(
        layer="derived",
        freq=90,
        trade_date=date(2026, 4, 24),
        run_id="test-derived-replace",
        written_rows=1,
    )["queue_item"]["queue_id"]

    exit_code = main(["list-indicator-recalc-queue", "--lake-root", str(tmp_path), "--indicator", "macd"])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert queue_id in output
    assert "lake-console compute-stk-mins-indicator" in output
    assert "--all-market" in output
    assert "--freq 90" in output
    assert "--start-date 2026-04-24" in output
    assert "lake-console mark-indicator-recalc-done" in output

    mark_exit_code = main(["mark-indicator-recalc-done", "--lake-root", str(tmp_path), "--queue-id", queue_id])
    assert mark_exit_code == 0
    done_items = service.list_items(include_done=True)
    pending_items = service.list_items()
    assert done_items[0]["status"] == "done"
    assert pending_items == []
