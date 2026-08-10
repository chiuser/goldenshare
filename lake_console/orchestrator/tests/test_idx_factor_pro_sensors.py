from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from orchestrator.defs.asset_guards.bounded_continuity import (
    ContinuityDateReadiness,
)
from orchestrator.defs.asset_guards.idx_factor_pro_lake_readiness import (
    raw_idx_factor_pro_lake_readiness,
    silver_idx_factor_pro_lake_readiness,
)
from orchestrator.defs.asset_guards.idx_factor_pro_source_probe import (
    IdxFactorProSourceProbeResult,
    probe_idx_factor_pro_source,
)
from orchestrator.defs.io.idx_factor_pro_silver_writer import (
    write_idx_factor_pro_silver_partition,
)
from orchestrator.defs.partitions import cn_major_index_factor_trade_days
from orchestrator.defs.paths import (
    raw_idx_factor_pro_path,
    silver_trade_calendar_path,
)
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.run_contracts.idx_factor_pro import (
    IDX_FACTOR_PRO_RAW_CHECKS,
    IDX_FACTOR_PRO_RAW_JOB_NAME,
    IDX_FACTOR_PRO_SILVER_JOB_NAME,
    IDX_FACTOR_PRO_SOURCE_COLUMNS,
    active_idx_factor_pro_daily_codes,
)
from orchestrator.defs.sensors import (
    idx_factor_pro_partition_sensor,
    idx_factor_pro_sensor,
)
from orchestrator.defs.sensors.readiness import CN_A_SENSOR_TIMEZONE
from tests._idx_factor_pro_helpers import (
    FakeIdxFactorProTushare,
    idx_factor_pro_row,
    write_idx_factor_pro_rows,
)

TRADE_DATE = "2026-08-07"
SOURCE_TRADE_DATE = "20260807"
AFTER_CLOSE = datetime(2026, 8, 7, 17, 0, tzinfo=CN_A_SENSOR_TIMEZONE)
BEFORE_CLOSE = datetime(2026, 8, 7, 15, 59, tzinfo=CN_A_SENSOR_TIMEZONE)


class _NoEventHistoryInstance:
    def __init__(self, *, registered: bool = True) -> None:
        self.registered = registered
        self.event_history_calls = 0

    def get_dynamic_partitions(self, name: str) -> list[str]:
        assert name == cn_major_index_factor_trade_days.name
        return [TRADE_DATE] if self.registered else []

    def get_event_records(self, *args, **kwargs):
        self.event_history_calls += 1
        raise AssertionError("idx_factor_pro sensors must not read event history")


class _CountingDuckDB:
    def __init__(self) -> None:
        self.connection_count = 0

    @contextmanager
    def connect(self):
        self.connection_count += 1
        yield object()


class _TestLakeRoot:
    def __init__(self, root: Path) -> None:
        self._root = root

    def root(self) -> Path:
        return self._root

    def ensure_available_for_run(self) -> None:
        return None


def _context(tmp_path: Path, *, registered: bool = True) -> SimpleNamespace:
    root = tmp_path / "data_lake"
    root.mkdir(parents=True, exist_ok=True)
    return SimpleNamespace(
        resources=SimpleNamespace(
            lake_root=_TestLakeRoot(root),
            duckdb=_CountingDuckDB(),
            tushare=object(),
        ),
        instance=_NoEventHistoryInstance(registered=registered),
    )


def _gate() -> idx_factor_pro_sensor.IdxFactorProCurrentDateGate:
    return idx_factor_pro_sensor.IdxFactorProCurrentDateGate(
        trade_date=TRADE_DATE,
        window_started=True,
        open_day=True,
        registered=True,
    )


def _readiness(
    *,
    materialized: bool,
    checks_passed: bool,
) -> ContinuityDateReadiness:
    return ContinuityDateReadiness(
        trade_date=TRADE_DATE,
        ready=materialized and checks_passed,
        materialized=materialized,
        checks_passed=checks_passed,
        reason="ready" if materialized and checks_passed else "not_ready",
        missing_check_names=IDX_FACTOR_PRO_RAW_CHECKS if not materialized else (),
        failed_check_names=IDX_FACTOR_PRO_RAW_CHECKS if materialized else (),
    )


def _probe(*, ready: bool) -> IdxFactorProSourceProbeResult:
    expected_count = len(active_idx_factor_pro_daily_codes(TRADE_DATE))
    return IdxFactorProSourceProbeResult(
        trade_date=TRADE_DATE,
        ready=ready,
        reason_code="ready" if ready else "source_probe_incomplete",
        expected_code_count=expected_count,
        returned_code_count=expected_count if ready else expected_count - 1,
        source_row_count=expected_count if ready else expected_count - 1,
        request_count=1,
        retry_count=0,
        elapsed_ms=1.0,
    )


def _source_rows() -> list[dict[str, object]]:
    return [
        idx_factor_pro_row(code, SOURCE_TRADE_DATE)
        for code in active_idx_factor_pro_daily_codes(TRADE_DATE)
    ]


def test_partition_sensor_registers_only_current_open_date_after_close(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path, registered=False)
    calendar_path = silver_trade_calendar_path(
        context.resources.lake_root.root()
    )
    calendar_path.parent.mkdir(parents=True, exist_ok=True)
    calendar_path.touch()

    with patch.object(
        idx_factor_pro_partition_sensor,
        "is_sse_open_day",
        return_value=True,
    ):
        result = (
            idx_factor_pro_partition_sensor._evaluate_idx_factor_pro_trade_day_sensor(
                context,
                evaluated_at=AFTER_CLOSE,
            )
        )

    assert result.run_requests == []
    assert len(result.dynamic_partitions_requests) == 1
    assert result.dynamic_partitions_requests[0].partition_keys == [TRADE_DATE]
    cursor = json.loads(result.cursor)
    assert cursor["target_date"] == TRADE_DATE
    assert cursor["selected_count"] == 1
    assert context.instance.event_history_calls == 0


def test_partition_sensor_waits_until_close_without_touching_resources(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path, registered=False)

    result = (
        idx_factor_pro_partition_sensor._evaluate_idx_factor_pro_trade_day_sensor(
            context,
            evaluated_at=BEFORE_CLOSE,
        )
    )

    assert result.dynamic_partitions_requests == []
    assert context.resources.duckdb.connection_count == 0
    assert json.loads(result.cursor)["details"]["reason_code"] == (
        "before_closing_window"
    )


def test_raw_sensor_requests_exactly_one_current_partition_run(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)
    with (
        patch.object(idx_factor_pro_sensor, "_load_current_date_gate", return_value=_gate()),
        patch.object(
            idx_factor_pro_sensor,
            "raw_idx_factor_pro_lake_readiness",
            return_value=_readiness(materialized=False, checks_passed=False),
        ),
        patch.object(
            idx_factor_pro_sensor,
            "probe_idx_factor_pro_source",
            return_value=_probe(ready=True),
        ) as source_probe,
    ):
        result = idx_factor_pro_sensor._evaluate_raw_sensor(
            context,
            evaluated_at=AFTER_CLOSE,
        )

    assert len(result.run_requests) == 1
    assert result.run_requests[0].partition_key == TRADE_DATE
    assert result.run_requests[0].run_key == (
        f"{IDX_FACTOR_PRO_RAW_JOB_NAME}:{TRADE_DATE}:v1"
    )
    assert source_probe.call_count == 1
    assert context.instance.event_history_calls == 0
    assert len(result.cursor.encode("utf-8")) < 8192
    assert json.loads(result.cursor)["details"]["reason_code"] == "request_run"


def test_raw_sensor_never_probes_or_overwrites_existing_invalid_file(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)
    with (
        patch.object(idx_factor_pro_sensor, "_load_current_date_gate", return_value=_gate()),
        patch.object(
            idx_factor_pro_sensor,
            "raw_idx_factor_pro_lake_readiness",
            return_value=_readiness(materialized=True, checks_passed=False),
        ),
        patch.object(idx_factor_pro_sensor, "probe_idx_factor_pro_source") as source_probe,
    ):
        result = idx_factor_pro_sensor._evaluate_raw_sensor(
            context,
            evaluated_at=AFTER_CLOSE,
        )

    assert result.run_requests == []
    assert source_probe.call_count == 0
    assert json.loads(result.cursor)["details"]["reason_code"] == (
        "materialized_check_failed"
    )


def test_raw_sensor_waits_when_single_source_probe_is_incomplete(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)
    with (
        patch.object(idx_factor_pro_sensor, "_load_current_date_gate", return_value=_gate()),
        patch.object(
            idx_factor_pro_sensor,
            "raw_idx_factor_pro_lake_readiness",
            return_value=_readiness(materialized=False, checks_passed=False),
        ),
        patch.object(
            idx_factor_pro_sensor,
            "probe_idx_factor_pro_source",
            return_value=_probe(ready=False),
        ),
    ):
        result = idx_factor_pro_sensor._evaluate_raw_sensor(
            context,
            evaluated_at=AFTER_CLOSE,
        )

    assert result.run_requests == []
    assert json.loads(result.cursor)["details"]["reason_code"] == (
        "source_probe_incomplete"
    )


def test_silver_sensor_requests_one_run_only_after_same_date_raw_is_ready(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)
    with (
        patch.object(idx_factor_pro_sensor, "_load_current_date_gate", return_value=_gate()),
        patch.object(
            idx_factor_pro_sensor,
            "silver_idx_factor_pro_lake_readiness",
            return_value=_readiness(materialized=False, checks_passed=False),
        ),
        patch.object(
            idx_factor_pro_sensor,
            "raw_idx_factor_pro_lake_readiness",
            return_value=_readiness(materialized=True, checks_passed=True),
        ),
    ):
        result = idx_factor_pro_sensor._evaluate_silver_sensor(
            context,
            evaluated_at=AFTER_CLOSE,
        )

    assert len(result.run_requests) == 1
    assert result.run_requests[0].partition_key == TRADE_DATE
    assert result.run_requests[0].run_key == (
        f"{IDX_FACTOR_PRO_SILVER_JOB_NAME}:{TRADE_DATE}:v1"
    )
    assert context.instance.event_history_calls == 0


def test_silver_sensor_waits_for_raw_and_refuses_invalid_existing_target(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)
    missing = _readiness(materialized=False, checks_passed=False)
    failed = _readiness(materialized=True, checks_passed=False)
    with (
        patch.object(idx_factor_pro_sensor, "_load_current_date_gate", return_value=_gate()),
        patch.object(
            idx_factor_pro_sensor,
            "silver_idx_factor_pro_lake_readiness",
            side_effect=(missing, failed),
        ),
        patch.object(
            idx_factor_pro_sensor,
            "raw_idx_factor_pro_lake_readiness",
            return_value=missing,
        ) as raw_readiness,
    ):
        waiting = idx_factor_pro_sensor._evaluate_silver_sensor(
            context,
            evaluated_at=AFTER_CLOSE,
        )
        invalid_target = idx_factor_pro_sensor._evaluate_silver_sensor(
            context,
            evaluated_at=AFTER_CLOSE,
        )

    assert waiting.run_requests == []
    assert json.loads(waiting.cursor)["details"]["reason_code"] == "raw_not_ready"
    assert invalid_target.run_requests == []
    assert json.loads(invalid_target.cursor)["details"]["reason_code"] == (
        "materialized_check_failed"
    )
    assert raw_readiness.call_count == 1


def test_source_probe_requires_exact_schema_date_keys_and_code_scope() -> None:
    rows = _source_rows()
    source = FakeIdxFactorProTushare(rows=rows)

    result = probe_idx_factor_pro_source(
        tushare=source,
        trade_date=TRADE_DATE,
    )

    assert result.ready is True
    assert result.request_count == 1
    assert source.calls == [
        (
            "idx_factor_pro",
            {"trade_date": SOURCE_TRADE_DATE, "limit": 8_000, "offset": 0},
            IDX_FACTOR_PRO_SOURCE_COLUMNS,
        )
    ]

    incomplete = probe_idx_factor_pro_source(
        tushare=FakeIdxFactorProTushare(rows=rows[:-1]),
        trade_date=TRADE_DATE,
    )
    duplicate = probe_idx_factor_pro_source(
        tushare=FakeIdxFactorProTushare(rows=[*rows, dict(rows[0])]),
        trade_date=TRADE_DATE,
    )
    schema_drift = probe_idx_factor_pro_source(
        tushare=FakeIdxFactorProTushare(
            rows=rows,
            columns=IDX_FACTOR_PRO_SOURCE_COLUMNS[:-1],
        ),
        trade_date=TRADE_DATE,
    )
    assert incomplete.reason_code == "source_probe_incomplete"
    assert duplicate.reason_code == "source_probe_duplicate_key"
    assert schema_drift.reason_code == "source_probe_schema_drift"


def test_lake_readiness_audits_physical_raw_and_silver_files(
    tmp_path: Path,
) -> None:
    lake_root = tmp_path / "data_lake"
    staging_root = tmp_path / "data_lake_staging"
    duckdb = DuckDBResource()
    rows = _source_rows()
    raw_path = raw_idx_factor_pro_path(lake_root, TRADE_DATE)

    missing = raw_idx_factor_pro_lake_readiness(
        lake_root=lake_root,
        duckdb_resource=duckdb,
        trade_date=TRADE_DATE,
    )
    assert missing.materialized is False
    assert missing.ready is False

    write_idx_factor_pro_rows(path=raw_path, rows=rows, duckdb_resource=duckdb)
    raw_ready = raw_idx_factor_pro_lake_readiness(
        lake_root=lake_root,
        duckdb_resource=duckdb,
        trade_date=TRADE_DATE,
    )
    assert raw_ready.materialized is True
    assert raw_ready.ready is True

    write_idx_factor_pro_silver_partition(
        lake_root_path=lake_root,
        staging_root_path=staging_root,
        duckdb_resource=duckdb,
        partition_key=TRADE_DATE,
        run_id="readiness-test",
    )
    silver_ready = silver_idx_factor_pro_lake_readiness(
        lake_root=lake_root,
        duckdb_resource=duckdb,
        trade_date=TRADE_DATE,
    )
    assert silver_ready.materialized is True
    assert silver_ready.ready is True


def test_lake_readiness_marks_existing_invalid_raw_as_materialized_not_ready(
    tmp_path: Path,
) -> None:
    lake_root = tmp_path / "data_lake"
    duckdb = DuckDBResource()
    write_idx_factor_pro_rows(
        path=raw_idx_factor_pro_path(lake_root, TRADE_DATE),
        rows=_source_rows()[:-1],
        duckdb_resource=duckdb,
    )

    readiness = raw_idx_factor_pro_lake_readiness(
        lake_root=lake_root,
        duckdb_resource=duckdb,
        trade_date=TRADE_DATE,
    )

    assert readiness.materialized is True
    assert readiness.ready is False
    assert readiness.failed_check_names


def test_sensor_definitions_are_stopped_and_use_dedicated_partition_set() -> None:
    raw_sensor = (
        idx_factor_pro_sensor.raw_tushare_idx_factor_pro_update_job_sensor
    )
    silver_sensor = (
        idx_factor_pro_sensor.silver_index_factor_pro_update_job_sensor
    )
    partition_sensor = (
        idx_factor_pro_partition_sensor.idx_factor_pro_trade_day_sensor
    )
    assert raw_sensor.default_status.value == "STOPPED"
    assert silver_sensor.default_status.value == "STOPPED"
    assert partition_sensor.default_status.value == "STOPPED"
    assert raw_sensor.name == "raw_tushare_idx_factor_pro_update_job_sensor"
    assert silver_sensor.name == "silver_index_factor_pro_update_job_sensor"
    assert partition_sensor.name == "idx_factor_pro_trade_day_sensor"
