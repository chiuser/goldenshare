from __future__ import annotations

from datetime import UTC, date, datetime
from unittest.mock import patch

import dagster as dg
import pytest

from orchestrator.defs.assets.index_daily_nineturn_prod_core import (
    prod_core_index_daily_nineturn,
)
from orchestrator.defs.catalog.lake_assets import get_lake_asset_catalog_entry
from orchestrator.defs.checks.index_daily_nineturn_prod_core_checks import (
    prod_core_index_daily_nineturn_partition_check,
)
from orchestrator.defs.jobs.index_daily_nineturn_prod_core_sync import (
    prod_core_index_daily_nineturn_sync_job,
)
from orchestrator.defs.prod_db.index_daily_nineturn import (
    PROD_CORE_INDEX_DAILY_NINETURN_COLUMNS,
    audit_prod_core_index_daily_nineturn_checkpoint_partitions,
    audit_prod_core_index_daily_nineturn_partition,
    replace_prod_core_index_daily_nineturn_partition,
)
from orchestrator.defs.sensors.index_daily_nineturn_prod_core_sensor import (
    prod_core_index_daily_nineturn_sync_job_sensor,
)


def test_serving_asset_catalog_check_job_and_sensor_contract() -> None:
    entry = get_lake_asset_catalog_entry("prod_core_index_daily_nineturn")
    assert entry.data_contract == "core_serving.index_nineturn_daily"
    assert entry.blocking_check_names == (
        "prod_core_index_daily_nineturn_partition_check",
    )
    spec = next(iter(prod_core_index_daily_nineturn_partition_check.check_specs))
    assert spec.blocking is True
    assert prod_core_index_daily_nineturn_sync_job.selection.resolve(
        [prod_core_index_daily_nineturn]
    ) == {prod_core_index_daily_nineturn.key}
    assert (
        prod_core_index_daily_nineturn_sync_job_sensor.default_status
        is dg.DefaultSensorStatus.STOPPED
    )


def test_publisher_bulk_replaces_and_readback_hashes() -> None:
    published_at = datetime(2026, 8, 14, tzinfo=UTC)
    rows = _rows()
    cursor = _FakeCursor(_read_back_rows(rows, published_at))
    connection = _FakeConnection(cursor)

    with patch(
        "orchestrator.defs.prod_db.index_daily_nineturn.execute_values"
    ) as execute_values:
        audit = replace_prod_core_index_daily_nineturn_partition(
            connection=connection,
            rows=rows,
            partition_key="2026-08-14",
            published_at=published_at,
        )

    assert audit.row_count == 2
    assert audit.read_back_row_count == 2
    assert len(audit.content_hash) == 64
    assert execute_values.call_count == 1
    assert connection.rollback_count == 0
    assert cursor.close_count == 1


def test_publisher_rolls_back_on_readback_drift() -> None:
    published_at = datetime(2026, 8, 14, tzinfo=UTC)
    rows = _rows()
    read_back = _read_back_rows(rows, published_at)
    read_back[0] = (*read_back[0][:2], 9999.0, *read_back[0][3:])
    cursor = _FakeCursor(read_back)
    connection = _FakeConnection(cursor)

    with (
        patch("orchestrator.defs.prod_db.index_daily_nineturn.execute_values"),
        pytest.raises(RuntimeError, match="read-back"),
    ):
        replace_prod_core_index_daily_nineturn_partition(
            connection=connection,
            rows=rows,
            partition_key="2026-08-14",
            published_at=published_at,
        )

    assert connection.rollback_count == 1
    assert cursor.close_count == 1


def test_readonly_audit_detects_content_drift() -> None:
    published_at = datetime(2026, 8, 14, tzinfo=UTC)
    rows = _rows()
    read_back = _read_back_rows(rows, published_at)
    read_back[1] = (*read_back[1][:2], 9999.0, *read_back[1][3:])

    audit = audit_prod_core_index_daily_nineturn_partition(
        connection=_FakeConnection(_FakeCursor(read_back)),
        rows=rows,
        partition_key="2026-08-14",
    )

    assert audit.passed is False
    assert "content" in audit.failed_rule_names


def test_publisher_rejects_invalid_signal_before_database_write() -> None:
    rows = _rows()
    rows[0]["up_count"] = 1
    rows[0]["nine_up_turn"] = "+9"
    cursor = _FakeCursor([])

    with pytest.raises(ValueError, match="signal/count"):
        replace_prod_core_index_daily_nineturn_partition(
            connection=_FakeConnection(cursor),
            rows=rows,
            partition_key="2026-08-14",
        )

    assert cursor.execute_calls == []


def test_checkpoint_audit_streams_and_matches_partition_hash() -> None:
    published_at = datetime(2026, 8, 14, tzinfo=UTC)
    rows = _rows()
    expected = audit_prod_core_index_daily_nineturn_partition(
        connection=_FakeConnection(_FakeCursor(_read_back_rows(rows, published_at))),
        rows=rows,
        partition_key="2026-08-14",
    )
    audit = audit_prod_core_index_daily_nineturn_checkpoint_partitions(
        connection=_FakeConnection(
            _FakeCursor(_read_back_rows(rows, published_at))
        ),
        expected_content_hashes={"2026-08-14": expected.expected_content_hash},
    )

    assert audit.passed is True
    assert audit.expected_partition_count == 1
    assert audit.observed_partition_count == 1
    assert audit.read_back_row_count == 2


class _FakeConnection:
    def __init__(self, cursor: _FakeCursor) -> None:
        self._cursor = cursor
        self.rollback_count = 0

    def cursor(self, *_args, **_kwargs):
        return self._cursor

    def rollback(self) -> None:
        self.rollback_count += 1


class _FakeCursor:
    def __init__(self, rows: list[tuple[object, ...]]) -> None:
        self.rows = rows
        self.execute_calls: list[tuple[str, tuple[object, ...]]] = []
        self.rowcount = -1
        self.close_count = 0
        self._fetch_index = 0
        self.itersize = 0

    def execute(self, sql: str, params: tuple[object, ...]) -> None:
        self.execute_calls.append((sql, params))
        self.rowcount = 2 if sql.strip().startswith("DELETE") else -1

    def fetchall(self) -> list[tuple[object, ...]]:
        return self.rows

    def fetchmany(self, size: int) -> list[tuple[object, ...]]:
        selected = self.rows[self._fetch_index : self._fetch_index + size]
        self._fetch_index += len(selected)
        return selected

    def close(self) -> None:
        self.close_count += 1


def _rows() -> list[dict[str, object]]:
    return [
        {
            "ts_code": "000001.SH",
            "trade_date": date(2026, 8, 14),
            "close": 3200.0,
            "up_count": 9,
            "down_count": 0,
            "nine_up_turn": "+9",
            "nine_down_turn": None,
        },
        {
            "ts_code": "899050.BJ",
            "trade_date": date(2026, 8, 14),
            "close": 1400.0,
            "up_count": 0,
            "down_count": 3,
            "nine_up_turn": None,
            "nine_down_turn": None,
        },
    ]


def _read_back_rows(
    rows: list[dict[str, object]],
    published_at: datetime,
) -> list[tuple[object, ...]]:
    return [
        tuple(
            {
                **row,
                "formula_version": 1,
                "published_at": published_at,
            }[column]
            for column in PROD_CORE_INDEX_DAILY_NINETURN_COLUMNS
        )
        for row in rows
    ]
