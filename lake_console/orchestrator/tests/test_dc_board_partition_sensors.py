from pathlib import Path
from types import SimpleNamespace

import duckdb
import dagster as dg

from orchestrator.defs.partitions import cn_a_dc_index_trade_days
from orchestrator.defs.sensors.cn_a_trade_day_sensor import (
    build_calendar_only_partition_registration_result,
)
from orchestrator.defs.sensors.dc_board_partition_sensor import (
    dc_daily_trade_day_partition_sensor,
    dc_index_trade_day_partition_sensor,
    dc_member_trade_day_partition_sensor,
)


def _write_calendar(root: Path) -> None:
    path = root / "silver/calendar/trade_calendar/full/part-000.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(":memory:") as connection:
        connection.execute(
            f"""
            COPY (
                SELECT * FROM (VALUES
                    ('SSE', DATE '2024-12-20', TRUE),
                    ('SSE', DATE '2026-07-14', TRUE)
                ) AS t(exchange, trade_date, is_open)
            ) TO '{path}' (FORMAT PARQUET)
            """
        )


class _FakeInstance:
    def __init__(self, registered=()):
        self.registered = tuple(registered)

    def get_dynamic_partitions(self, name):
        assert name == cn_a_dc_index_trade_days.name
        return list(self.registered)


class _FakeDuckDB:
    def connect(self):
        connection = duckdb.connect(":memory:")

        class _Context:
            def __enter__(self):
                return connection

            def __exit__(self, exc_type, exc, tb):
                connection.close()
                return False

        return _Context()


def _context(root: Path, registered=()):
    _write_calendar(root)
    return SimpleNamespace(
        instance=_FakeInstance(registered),
        resources=SimpleNamespace(
            lake_root=SimpleNamespace(
                ensure_available_for_run=lambda: None,
                root=lambda: root,
            ),
            duckdb=_FakeDuckDB(),
        ),
        log=SimpleNamespace(info=lambda _message: None),
    )


def test_calendar_only_registration_does_not_use_source_gate(tmp_path):
    result = build_calendar_only_partition_registration_result(
        _context(Path(tmp_path)),
        dynamic_partitions=cn_a_dc_index_trade_days,
        min_trade_date="2024-12-20",
        partition_set_label="dc_index",
        sensor_name="dc_index_trade_day_partition_sensor",
        asset_family="dc_board_partition_registration",
    )
    assert len(result.dynamic_partitions_requests) == 1
    assert result.dynamic_partitions_requests[0].partition_keys == [
        "2024-12-20",
        "2026-07-14",
    ]
    assert result.cursor.encode("ascii")


def test_board_partition_registration_sensors_are_stopped():
    for sensor in (
        dc_index_trade_day_partition_sensor,
        dc_member_trade_day_partition_sensor,
        dc_daily_trade_day_partition_sensor,
    ):
        assert sensor.default_status == dg.DefaultSensorStatus.STOPPED
