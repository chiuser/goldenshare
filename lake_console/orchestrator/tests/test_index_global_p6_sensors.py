from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import duckdb

from orchestrator.defs.asset_guards.index_global_lake_readiness import silver_index_global_file_status
from orchestrator.defs.partitions import cn_global_index_trade_days
from orchestrator.defs.paths import raw_index_global_path, silver_index_global_path
from orchestrator.defs.run_contracts.asset_column_schemas import (
    RAW_INDEX_GLOBAL_SCHEMA,
    SILVER_INDEX_GLOBAL_SCHEMA,
)
from orchestrator.defs.run_contracts.index_global import (
    GLOBAL_INDEX_LATE_EMPTY_RETRY_LIMIT,
    build_index_global_phase_slots,
    build_index_global_raw_run_config,
    build_index_global_silver_run_config,
)
from orchestrator.defs.sensors.global_index_partition_sensor import (
    evaluate_global_index_partition_sensor,
)
from orchestrator.defs.sensors.index_global_late_empty_sensor import (
    evaluate_index_global_late_empty_sensor,
)
from orchestrator.defs.sensors.index_global_sensor import evaluate_index_global_sensor
from orchestrator.defs.sensors.index_global_retry_sensor import raw_index_global_retry_sensor
from orchestrator.defs.sensors.silver_index_global_retry_sensor import silver_index_global_retry_sensor
from orchestrator.defs.sensors.silver_index_global_sensor import evaluate_silver_index_global_sensor


TZ = ZoneInfo("Asia/Shanghai")
NOW = datetime(2026, 7, 28, 6, 0, tzinfo=TZ)


class _Instance:
    def __init__(self, registered=()):
        self.registered = set(registered)

    def get_dynamic_partitions(self, name):
        assert name == cn_global_index_trade_days.name
        return sorted(self.registered)

    def get_event_records(self, *_args, **_kwargs):
        raise AssertionError("index_global P6 sensors must not read event history")


class _LakeRoot:
    def __init__(self, root: Path):
        self._root = root

    def root(self):
        return self._root

    def ensure_available_for_run(self):
        return None


class _DuckDB:
    def __init__(self):
        self.connection_count = 0

    def connect(self):
        connection = duckdb.connect(":memory:")
        self.connection_count += 1

        class _Context:
            def __enter__(self):
                return connection

            def __exit__(self, exc_type, exc, tb):
                connection.close()
                return False

        return _Context()


def _context(tmp_path: Path, registered=(), *, cursor=""):
    duckdb_resource = _DuckDB()
    return SimpleNamespace(
        cursor=cursor,
        instance=_Instance(registered),
        resources=SimpleNamespace(lake_root=_LakeRoot(tmp_path), duckdb=duckdb_resource),
        dagster_run=None,
    )


def _write_empty(path: Path, schema):
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = ", ".join(f'"{column.name}" {column.type}' for column in schema)
    selects = ", ".join(
        f'CAST(NULL AS {column.type}) AS "{column.name}"' for column in schema
    )
    with duckdb.connect(":memory:") as connection:
        connection.execute(f"CREATE TABLE rows ({columns})")
        connection.execute(f"COPY (SELECT {selects} FROM rows) TO '{path}' (FORMAT PARQUET)")


def test_phase_slots_are_due_in_beijing_order_and_bounded():
    slots = build_index_global_phase_slots(NOW)
    assert len(slots) <= 50
    assert slots[0][:2] == ("2026-07-19", "asia_1")
    assert ("2026-07-27", "americas", datetime(2026, 7, 28, 5, 30, tzinfo=TZ)) in slots
    assert ("2026-07-28", "asia_1", datetime(2026, 7, 28, 14, 40, tzinfo=TZ)) not in slots


def test_raw_phase_sensor_dispatches_one_oldest_registered_slot():
    context = _context(Path("/tmp/index-global-p6"), registered=("2026-07-19",))
    result = evaluate_index_global_sensor(context, evaluated_at=NOW)
    assert len(result.run_requests) == 1
    request = result.run_requests[0]
    assert request.partition_key == "2026-07-19"
    assert request.run_key == "index_global_update:2026-07-19:asia_1"
    assert request.run_config["ops"]["raw_index_global"]["config"]["probe_phase"] == "asia_1"
    assert len(result.cursor.encode("utf-8")) < 8192


def test_raw_phase_sensor_blocks_unregistered_oldest_slot():
    context = _context(Path("/tmp/index-global-p6"), registered=("2026-07-20",))
    result = evaluate_index_global_sensor(context, evaluated_at=NOW)
    assert not result.run_requests
    assert "partition_not_registered" in str(result.skip_reason)


def test_partition_sensor_uses_natural_days_and_2000_batch():
    context = _context(Path("/tmp/index-global-p6"), registered=())
    result = evaluate_global_index_partition_sensor(context, evaluated_at=NOW)
    assert len(result.dynamic_partitions_requests) == 1
    keys = result.dynamic_partitions_requests[0].partition_keys
    assert keys[0] == "2022-01-01"
    assert keys[-1] == "2026-07-28"
    assert len(keys) <= 2000
    assert result.cursor.encode("ascii")


def test_late_empty_sensor_retries_empty_file_and_caps_attempts(tmp_path: Path):
    trade_date = "2026-07-25"
    _write_empty(raw_index_global_path(tmp_path, trade_date), RAW_INDEX_GLOBAL_SCHEMA)
    registered = ("2026-07-25", "2026-07-26", "2026-07-27")
    context = _context(tmp_path, registered=registered)
    first = evaluate_index_global_late_empty_sensor(context, evaluated_at=NOW)
    assert len(first.run_requests) == 1
    assert first.run_requests[0].run_key.endswith(":late_empty:1")

    second_context = _context(tmp_path, registered=registered, cursor=first.cursor)
    second = evaluate_index_global_late_empty_sensor(second_context, evaluated_at=NOW)
    assert len(second.run_requests) == 1
    assert second.run_requests[0].run_key.endswith(":late_empty:2")

    exhausted_context = _context(tmp_path, registered=registered, cursor=second.cursor)
    exhausted = evaluate_index_global_late_empty_sensor(exhausted_context, evaluated_at=NOW)
    assert not exhausted.run_requests
    assert "late_empty_exhausted" in str(exhausted.skip_reason)
    assert GLOBAL_INDEX_LATE_EMPTY_RETRY_LIMIT == 2


def test_silver_final_sensor_only_accepts_americas_and_typed_config(tmp_path: Path):
    context = _context(tmp_path, registered=("2026-07-27",))
    context.dagster_run = SimpleNamespace(
        run_id="raw-run-1",
        run_config=build_index_global_raw_run_config(
            trade_date="2026-07-27", probe_phase="americas"
        ),
    )
    result = evaluate_silver_index_global_sensor(context)
    assert result.run_key == "silver_index_global_update:2026-07-27"
    assert result.run_config == build_index_global_silver_run_config(trade_date="2026-07-27")
    assert context.resources.duckdb.connection_count == 1

    context.dagster_run.run_config = build_index_global_raw_run_config(
        trade_date="2026-07-27", probe_phase="asia_1"
    )
    skipped = evaluate_silver_index_global_sensor(context)
    assert "phase_not_final" in str(skipped)


def test_silver_final_sensor_does_not_overwrite_existing_invalid_file(tmp_path: Path):
    path = silver_index_global_path(tmp_path, "2026-07-27")
    path.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(":memory:") as connection:
        connection.execute(f"COPY (SELECT 1 AS broken) TO '{path}' (FORMAT PARQUET)")
    context = _context(tmp_path, registered=("2026-07-27",))
    context.dagster_run = SimpleNamespace(
        run_id="raw-run-1",
        run_config=build_index_global_raw_run_config(
            trade_date="2026-07-27", probe_phase="americas"
        ),
    )
    result = evaluate_silver_index_global_sensor(context)
    assert "silver_existing_check_failed" in str(result)


def test_failed_run_sensors_retry_only_typed_config():
    raw_context = SimpleNamespace(
        dagster_run=SimpleNamespace(
            run_config=build_index_global_raw_run_config(
                trade_date="2026-07-27", probe_phase="americas"
            )
        )
    )
    raw_result = raw_index_global_retry_sensor._run_status_sensor_fn(raw_context)
    assert raw_result.run_key == "index_global_update:2026-07-27:americas:retry:1"
    silver_context = SimpleNamespace(
        dagster_run=SimpleNamespace(
            run_config=build_index_global_silver_run_config(trade_date="2026-07-27")
        )
    )
    silver_result = silver_index_global_retry_sensor._run_status_sensor_fn(silver_context)
    assert silver_result.run_key == "silver_index_global_update:2026-07-27:retry:1"


def test_silver_file_gate_accepts_valid_empty_natural_day(tmp_path: Path):
    path = silver_index_global_path(tmp_path, "2026-07-27")
    _write_empty(path, SILVER_INDEX_GLOBAL_SCHEMA)
    with duckdb.connect(":memory:") as connection:
        status = silver_index_global_file_status(
            connection,
            path,
            partition_key="2026-07-27",
        )
    assert status.ready is True
    assert status.row_count == 0
