from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from lake_console.backend.app.services.stk_mins_clean_next_gate import (
    CleanNextGateBlockedError,
    CleanNextGateStatus,
    CleanNextPartitionGateService,
)


def test_clean_next_gate_writes_and_updates_one_partition_status(tmp_path: Path) -> None:
    service = CleanNextPartitionGateService(lake_root=tmp_path)

    first = service.write_statuses(
        [
            CleanNextGateStatus(
                freq=1,
                trade_date=date(2026, 5, 8),
                clean_partition_path="research/stk_mins_by_date_clean_next/freq=1/trade_date=2026-05-08",
                source_run_id="raw-run-1",
                clean_run_id="clean-run-1",
                write_revision="raw-run-1:freq=1:trade_date=2026-05-08",
                status="passed",
                issue_count=0,
                raw_rows=100,
                clean_rows=98,
                ledger_path="manifest/stk_mins_quality/clean_next_completeness_issue_ledger.parquet",
                message="passed",
            )
        ],
        run_id="gate-run-1",
    )
    second = service.write_statuses(
        [
            CleanNextGateStatus(
                freq=1,
                trade_date=date(2026, 5, 8),
                clean_partition_path="research/stk_mins_by_date_clean_next/freq=1/trade_date=2026-05-08",
                source_run_id="raw-run-2",
                clean_run_id="clean-run-2",
                write_revision="raw-run-2:freq=1:trade_date=2026-05-08",
                status="blocked",
                issue_count=2,
                raw_rows=100,
                clean_rows=98,
                ledger_path="manifest/stk_mins_quality/clean_next_completeness_issue_ledger.parquet",
                message="blocked by completeness audit",
            )
        ],
        run_id="gate-run-2",
    )

    rows = service.read_statuses()
    assert first["updated_partitions"] == 1
    assert second["updated_partitions"] == 1
    assert len(rows) == 1
    assert rows[0]["partition_key"] == "freq=1/trade_date=2026-05-08"
    assert rows[0]["status"] == "blocked"
    assert rows[0]["issue_count"] == 2
    assert rows[0]["source_run_id"] == "raw-run-2"


def test_clean_next_gate_require_passed_rejects_missing_or_blocked_partition(tmp_path: Path) -> None:
    service = CleanNextPartitionGateService(lake_root=tmp_path)

    with pytest.raises(CleanNextGateBlockedError, match="缺少分区状态"):
        service.require_passed(freq=1, trade_date=date(2026, 5, 8))

    service.write_statuses(
        [
            CleanNextGateStatus(
                freq=1,
                trade_date=date(2026, 5, 8),
                clean_partition_path="research/stk_mins_by_date_clean_next/freq=1/trade_date=2026-05-08",
                source_run_id="raw-run-1",
                clean_run_id="clean-run-1",
                write_revision="raw-run-1:freq=1:trade_date=2026-05-08",
                status="blocked",
                issue_count=1,
                raw_rows=100,
                clean_rows=98,
                ledger_path="manifest/stk_mins_quality/clean_next_completeness_issue_ledger.parquet",
                message="blocked",
            )
        ],
        run_id="gate-run-1",
    )

    with pytest.raises(CleanNextGateBlockedError, match="未通过"):
        service.require_passed(freq=1, trade_date=date(2026, 5, 8))
