from contextlib import contextmanager
from datetime import date
import unittest

import dagster as dg

from orchestrator.defs.assets.clickhouse_serving import (
    CLICKHOUSE_MARKET_BREADTH_COLUMNS,
    PROD_MARKET_BREADTH_SYNC_MAX_PARTITIONS_PER_RUN,
    _fetch_clickhouse_market_breadth_row_tuples_by_partition,
    _replace_clickhouse_partition,
    _replace_clickhouse_partitions,
    prod_ch_share_fact_market_breadth_daily,
)
from orchestrator.defs.checks import prod_clickhouse_serving_checks as checks
from orchestrator.defs.jobs.prod_clickhouse_share_fact_market_breadth_sync import (
    prod_clickhouse_share_fact_market_breadth_sync_job,
)
from orchestrator.defs.sensors.clickhouse_market_breadth_continuity_sensor import (
    prod_clickhouse_market_breadth_continuity_sensor,
)


DATE_1 = "2026-06-04"
DATE_2 = "2026-06-05"


class _PartitionContext:
    def __init__(self, *partition_keys: str) -> None:
        self.partition_keys = partition_keys


class _FakeClickHouseResource:
    def __init__(self, client: "_FakeClickHouseClient") -> None:
        self.client = client
        self.connection_count = 0

    @contextmanager
    def get_connection(self):
        self.connection_count += 1
        yield self.client


class _FakeClickHouseClient:
    def __init__(
        self,
        rows: list[tuple],
        *,
        delete_residual_dates: set[str] | None = None,
        skip_insert_dates: set[str] | None = None,
    ) -> None:
        self.rows = list(rows)
        self.delete_residual_dates = delete_residual_dates or set()
        self.skip_insert_dates = skip_insert_dates or set()
        self.operations: list[str] = []
        self.insert_batches: list[list[tuple]] = []

    def execute(self, query: str, params=None, data=None):
        normalised_query = " ".join(query.split()).upper()
        if normalised_query.startswith("SET LIGHTWEIGHT_DELETES_SYNC"):
            self.operations.append("set")
            return []
        if normalised_query.startswith("DELETE FROM"):
            self.operations.append("delete")
            selected_dates = self._selected_dates(params)
            self.rows = [
                row
                for row in self.rows
                if self._row_date(row) not in selected_dates
                or self._row_date(row) in self.delete_residual_dates
            ]
            return []
        if normalised_query.startswith("SELECT TRADE_DATE, COUNT()"):
            self.operations.append("count")
            selected_dates = self._selected_dates(params)
            return [
                (date.fromisoformat(partition_key), row_count)
                for partition_key, row_count in self._row_counts(selected_dates).items()
                if row_count > 0
            ]
        if normalised_query.startswith("SELECT"):
            self.operations.append("select")
            selected_dates = self._selected_dates(params)
            return [
                row
                for row in sorted(self.rows, key=lambda item: item[0])
                if self._row_date(row) in selected_dates
            ]
        if normalised_query.startswith("INSERT INTO"):
            self.operations.append("insert")
            insert_rows = data if data is not None else params
            batch = list(insert_rows)
            self.insert_batches.append(batch)
            self.rows.extend(
                row for row in batch if self._row_date(row) not in self.skip_insert_dates
            )
            return []
        raise AssertionError(f"Unexpected query: {query}")

    @staticmethod
    def _row_date(row: tuple) -> str:
        value = row[0]
        return value.isoformat() if hasattr(value, "isoformat") else str(value)

    @staticmethod
    def _selected_dates(params) -> set[str]:
        if not isinstance(params, dict):
            return set()
        return {
            value.isoformat() if hasattr(value, "isoformat") else str(value)
            for key, value in params.items()
            if key.startswith("trade_date_")
        }

    def _row_counts(self, selected_dates: set[str]) -> dict[str, int]:
        return {
            partition_key: sum(
                1 for row in self.rows if self._row_date(row) == partition_key
            )
            for partition_key in selected_dates
        }


def _check_function(check_definition):
    return check_definition.node_def.compute_fn.decorated_fn


def _row(
    partition_key: str,
    *,
    up_count: int = 1,
    updated_at: str = "2026-06-05 15:00:00",
) -> tuple:
    values = {
        "trade_date": date.fromisoformat(partition_key),
        "up_count": up_count,
        "down_count": 2,
        "flat_count": 3,
        "total_count": 6,
        "red_rate": 50.0,
        "down_gt_10_count": 1,
        "down_7_10_count": 2,
        "down_5_7_count": 3,
        "down_3_5_count": 4,
        "down_0_3_count": 5,
        "up_0_3_count": 6,
        "up_3_5_count": 7,
        "up_5_7_count": 8,
        "up_7_10_count": 9,
        "up_gt_10_count": 10,
        "updated_at": updated_at,
    }
    return tuple(values[column] for column in CLICKHOUSE_MARKET_BREADTH_COLUMNS)


class ProdClickHouseMarketBreadthBatchSyncTests(unittest.TestCase):
    def test_prod_asset_backfill_policy_batches_250_partitions(self) -> None:
        self.assertEqual(PROD_MARKET_BREADTH_SYNC_MAX_PARTITIONS_PER_RUN, 250)
        self.assertEqual(
            prod_ch_share_fact_market_breadth_daily.backfill_policy.max_partitions_per_run,
            250,
        )

    def test_batch_fetch_reads_selected_dates_once(self) -> None:
        row_1 = _row(DATE_1)
        row_2 = _row(DATE_2)
        client = _FakeClickHouseClient([row_2, row_1])

        rows_by_partition = _fetch_clickhouse_market_breadth_row_tuples_by_partition(
            client,
            (DATE_1, DATE_2),
        )

        self.assertEqual(rows_by_partition, {DATE_1: [row_1], DATE_2: [row_2]})
        self.assertEqual(client.operations, ["select"])

    def test_batch_replace_deletes_and_inserts_selected_dates_once(self) -> None:
        old_row_1 = _row(DATE_1, up_count=0)
        old_row_2 = _row(DATE_2, up_count=0)
        new_row_1 = _row(DATE_1, up_count=10)
        new_row_2 = _row(DATE_2, up_count=20)
        client = _FakeClickHouseClient([old_row_1, old_row_2])

        _replace_clickhouse_partitions(
            client,
            {DATE_1: [new_row_1], DATE_2: [new_row_2]},
            (DATE_1, DATE_2),
        )

        self.assertEqual(client.rows, [new_row_1, new_row_2])
        self.assertEqual(client.operations, ["set", "delete", "count", "insert", "count"])
        self.assertEqual(client.insert_batches, [[new_row_1, new_row_2]])

    def test_batch_replace_fails_before_delete_when_local_rows_are_missing(self) -> None:
        client = _FakeClickHouseClient([])

        with self.assertRaisesRegex(RuntimeError, "missing_partitions"):
            _replace_clickhouse_partitions(
                client,
                {DATE_1: [], DATE_2: [_row(DATE_2)]},
                (DATE_1, DATE_2),
            )

        self.assertEqual(client.operations, [])

    def test_batch_replace_fails_before_delete_when_local_rows_are_duplicate(self) -> None:
        row_1 = _row(DATE_1)
        client = _FakeClickHouseClient([])

        with self.assertRaisesRegex(RuntimeError, "duplicate_partitions"):
            _replace_clickhouse_partitions(
                client,
                {DATE_1: [row_1, row_1], DATE_2: [_row(DATE_2)]},
                (DATE_1, DATE_2),
            )

        self.assertEqual(client.operations, [])

    def test_batch_replace_fails_when_prod_delete_leaves_rows(self) -> None:
        old_row_1 = _row(DATE_1, up_count=0)
        client = _FakeClickHouseClient(
            [old_row_1],
            delete_residual_dates={DATE_1},
        )

        with self.assertRaisesRegex(RuntimeError, "target partitions empty"):
            _replace_clickhouse_partitions(
                client,
                {DATE_1: [_row(DATE_1)], DATE_2: [_row(DATE_2)]},
                (DATE_1, DATE_2),
            )

        self.assertEqual(client.operations, ["set", "delete", "count"])
        self.assertEqual(client.insert_batches, [])

    def test_batch_replace_fails_when_prod_insert_leaves_missing_partition(self) -> None:
        client = _FakeClickHouseClient([], skip_insert_dates={DATE_2})

        with self.assertRaisesRegex(RuntimeError, "exactly one row per partition"):
            _replace_clickhouse_partitions(
                client,
                {DATE_1: [_row(DATE_1)], DATE_2: [_row(DATE_2)]},
                (DATE_1, DATE_2),
            )

        self.assertEqual(client.operations, ["set", "delete", "count", "insert", "count"])
        self.assertEqual(client.insert_batches, [[_row(DATE_1), _row(DATE_2)]])

    def test_single_partition_wrapper_preserves_replace_semantics(self) -> None:
        old_row = _row(DATE_1, up_count=0)
        new_row = _row(DATE_1, up_count=10)
        client = _FakeClickHouseClient([old_row])

        _replace_clickhouse_partition(client, new_row)

        self.assertEqual(client.rows, [new_row])
        self.assertEqual(client.operations, ["set", "delete", "count", "insert", "count"])

    def test_prod_row_count_check_batches_selected_partitions(self) -> None:
        client = _FakeClickHouseClient([_row(DATE_1), _row(DATE_2)])
        prod_resource = _FakeClickHouseResource(client)
        check_fn = _check_function(checks.prod_ch_share_fact_market_breadth_row_count_is_one)

        result = check_fn(_PartitionContext(DATE_1, DATE_2), prod_resource)

        self.assertTrue(result.passed)
        self.assertEqual(prod_resource.connection_count, 1)
        self.assertEqual(client.operations, ["select"])

    def test_prod_row_count_check_detects_missing_and_duplicate_partitions(self) -> None:
        duplicate_row = _row(DATE_1)
        client = _FakeClickHouseClient([duplicate_row, duplicate_row])
        prod_resource = _FakeClickHouseResource(client)
        check_fn = _check_function(checks.prod_ch_share_fact_market_breadth_row_count_is_one)

        result = check_fn(_PartitionContext(DATE_1, DATE_2), prod_resource)

        self.assertFalse(result.passed)
        self.assertEqual(client.operations, ["select"])

    def test_prod_date_alignment_check_detects_missing_partition(self) -> None:
        client = _FakeClickHouseClient([_row(DATE_1)])
        prod_resource = _FakeClickHouseResource(client)
        check_fn = _check_function(
            checks.prod_ch_share_fact_market_breadth_date_matches_partition
        )

        result = check_fn(_PartitionContext(DATE_1, DATE_2), prod_resource)

        self.assertFalse(result.passed)
        self.assertEqual(client.operations, ["select"])

    def test_prod_row_matches_local_batches_and_detects_field_mismatch(self) -> None:
        local_client = _FakeClickHouseClient([_row(DATE_1), _row(DATE_2, up_count=20)])
        prod_client = _FakeClickHouseClient([_row(DATE_1), _row(DATE_2, up_count=21)])
        local_resource = _FakeClickHouseResource(local_client)
        prod_resource = _FakeClickHouseResource(prod_client)
        check_fn = _check_function(checks.prod_ch_share_fact_market_breadth_row_matches_local)

        result = check_fn(
            _PartitionContext(DATE_1, DATE_2),
            local_resource,
            prod_resource,
        )

        self.assertFalse(result.passed)
        self.assertEqual(local_resource.connection_count, 1)
        self.assertEqual(prod_resource.connection_count, 1)
        self.assertEqual(local_client.operations, ["select"])
        self.assertEqual(prod_client.operations, ["select"])

    def test_prod_updated_at_check_detects_older_prod_row(self) -> None:
        local_client = _FakeClickHouseClient(
            [_row(DATE_1), _row(DATE_2, updated_at="2026-06-05 15:00:00")]
        )
        prod_client = _FakeClickHouseClient(
            [_row(DATE_1), _row(DATE_2, updated_at="2026-06-05 14:59:59")]
        )
        local_resource = _FakeClickHouseResource(local_client)
        prod_resource = _FakeClickHouseResource(prod_client)
        check_fn = _check_function(
            checks.prod_ch_share_fact_market_breadth_updated_at_not_older_than_local
        )

        result = check_fn(
            _PartitionContext(DATE_1, DATE_2),
            local_resource,
            prod_resource,
        )

        self.assertFalse(result.passed)
        self.assertEqual(local_resource.connection_count, 1)
        self.assertEqual(prod_resource.connection_count, 1)
        self.assertEqual(local_client.operations, ["select"])
        self.assertEqual(prod_client.operations, ["select"])

    def test_job_and_sensor_contracts_do_not_change(self) -> None:
        self.assertEqual(
            prod_clickhouse_share_fact_market_breadth_sync_job.name,
            "prod_clickhouse_share_fact_market_breadth_sync_job",
        )
        self.assertIn(
            "prod_ch_share_fact_market_breadth_daily",
            str(prod_clickhouse_share_fact_market_breadth_sync_job.selection),
        )
        self.assertEqual(
            prod_clickhouse_market_breadth_continuity_sensor.name,
            "prod_clickhouse_market_breadth_continuity_sensor",
        )
        self.assertEqual(
            prod_clickhouse_market_breadth_continuity_sensor.default_status,
            dg.DefaultSensorStatus.STOPPED,
        )
        self.assertEqual(
            prod_clickhouse_market_breadth_continuity_sensor.minimum_interval_seconds,
            600,
        )


if __name__ == "__main__":
    unittest.main()
