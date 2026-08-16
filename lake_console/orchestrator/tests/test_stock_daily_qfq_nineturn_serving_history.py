import hashlib
import json
import unittest
from contextlib import nullcontext
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

import duckdb

from orchestrator.defs.bootstrap.stock_daily_qfq_nineturn_serving_history import (
    HISTORY_DUCKDB_MEMORY_LIMIT,
    HISTORY_DUCKDB_THREADS,
    StockDailyQfqNineTurnServingHistoryError,
    _configure_history_duckdb,
    load_stock_daily_qfq_nineturn_serving_history_plan,
    plan_stock_daily_qfq_nineturn_serving_history,
    publish_stock_daily_qfq_nineturn_serving_history,
)
from orchestrator.defs.paths import (
    DEFAULT_LAKE_ROOT,
    gold_stock_daily_qfq_nineturn_path,
    gold_stock_daily_qfq_path,
)
from orchestrator.defs.resources import DuckDBResource


class _FakeConnection:
    def __init__(self) -> None:
        self.commit_count = 0
        self.rollback_count = 0

    def commit(self) -> None:
        self.commit_count += 1

    def rollback(self) -> None:
        self.rollback_count += 1


class _FakeProdResource:
    def __init__(self) -> None:
        self.write_connection = _FakeConnection()
        self.read_connection = _FakeConnection()
        self.write_connect_count = 0
        self.read_connect_count = 0

    def connect(self):
        self.write_connect_count += 1
        return nullcontext(self.write_connection)

    def connect_readonly(self):
        self.read_connect_count += 1
        return nullcontext(self.read_connection)


class _CountingDuckDBResource:
    def __init__(self) -> None:
        self.connect_count = 0
        self.delegate = DuckDBResource()

    def connect(self):
        self.connect_count += 1
        return self.delegate.connect()


class StockDailyQfqNineTurnServingHistoryTests(unittest.TestCase):
    def test_history_duckdb_is_bounded_to_single_thread_and_128mb(self) -> None:
        self.assertEqual(HISTORY_DUCKDB_MEMORY_LIMIT, "128MB")
        self.assertEqual(HISTORY_DUCKDB_THREADS, 1)
        with DuckDBResource().connect() as connection:
            _configure_history_duckdb(connection)
            settings = dict(
                connection.execute(
                    """
                    SELECT name, value
                    FROM duckdb_settings()
                    WHERE name IN (
                      'memory_limit',
                      'threads',
                      'preserve_insertion_order'
                    )
                    """
                ).fetchall()
            )

        self.assertEqual(settings["memory_limit"], "122.0 MiB")
        self.assertEqual(settings["threads"], "1")
        self.assertEqual(settings["preserve_insertion_order"], "false")

    def test_plan_is_read_only_and_freezes_source_identities(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            lake_root = base / "lake"
            staging_root = base / "staging"
            _write_partition(lake_root, "2026-08-11")
            _write_partition(lake_root, "2026-08-12", qfq_close=999.0)

            duckdb_resource = _CountingDuckDBResource()
            with patch(
                "orchestrator.defs.bootstrap."
                "stock_daily_qfq_nineturn_serving_history."
                "load_gold_stock_daily_qfq_nineturn_rows_with_connection",
                side_effect=AssertionError("plan must not materialize source rows"),
            ):
                plan = plan_stock_daily_qfq_nineturn_serving_history(
                    lake_root=lake_root,
                    staging_root=staging_root,
                    duckdb_resource=duckdb_resource,
                    batch_partition_limit=1,
                    output_dir=base / "reports",
                )

            self.assertFalse(plan.should_stop)
            self.assertEqual(duckdb_resource.connect_count, 2)
            self.assertEqual(len(plan.partitions), 2)
            self.assertEqual(plan.report["source_row_count"], 4)
            self.assertEqual(plan.report["estimated_batch_count"], 2)
            self.assertFalse(staging_root.exists())
            loaded = load_stock_daily_qfq_nineturn_serving_history_plan(
                plan.report_path
            )
            self.assertEqual(loaded.plan_fingerprint, plan.plan_fingerprint)
            summary = plan.to_summary_dict()
            self.assertNotIn("partitions", summary)
            self.assertEqual(summary["first_partition_key"], "2026-08-11")
            self.assertEqual(summary["last_partition_key"], "2026-08-12")

    def test_plan_does_not_bind_or_compare_qfq_price_values(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            lake_root = base / "lake"
            _write_partition(lake_root, "2026-08-12")

            plan = plan_stock_daily_qfq_nineturn_serving_history(
                lake_root=lake_root,
                staging_root=base / "staging",
                duckdb_resource=DuckDBResource(),
                output_dir=base / "reports",
            )

            self.assertFalse(plan.should_stop)
            partition = plan.partitions[0]
            self.assertFalse(hasattr(partition, "qfq_relative_path"))
            self.assertNotIn("close_qfq", json.dumps(plan.report))

    def test_batch_checkpoint_resumes_and_revalidates_completed_partition(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            lake_root = base / "lake"
            staging_root = base / "staging"
            _write_partition(lake_root, "2026-08-11")
            _write_partition(lake_root, "2026-08-12")
            plan = plan_stock_daily_qfq_nineturn_serving_history(
                lake_root=lake_root,
                staging_root=staging_root,
                duckdb_resource=DuckDBResource(),
                batch_partition_limit=1,
                output_dir=base / "reports",
            )
            checkpoint_path = staging_root / "serving" / "checkpoint.json"
            replaced: list[str] = []

            def replace(*, partition_key: str, **_kwargs):
                replaced.append(partition_key)
                return SimpleNamespace()

            def audit(*, partition_key: str, **_kwargs):
                return SimpleNamespace(
                    passed=True,
                    expected_content_hash=_content_hash(partition_key),
                )

            def checkpoint_audit(*, expected_content_hashes, **_kwargs):
                return SimpleNamespace(
                    passed=all(
                        content_hash == _content_hash(partition_key)
                        for partition_key, content_hash in expected_content_hashes.items()
                    ),
                    failed_partition_keys=(),
                )

            with (
                patch(
                    "orchestrator.defs.bootstrap.stock_daily_qfq_nineturn_serving_history."
                    "replace_prod_core_stock_daily_qfq_nineturn_partition",
                    side_effect=replace,
                ),
                patch(
                    "orchestrator.defs.bootstrap.stock_daily_qfq_nineturn_serving_history."
                    "audit_prod_core_stock_daily_qfq_nineturn_partition",
                    side_effect=audit,
                ) as audited,
                patch(
                    "orchestrator.defs.bootstrap.stock_daily_qfq_nineturn_serving_history."
                    "audit_prod_core_stock_daily_qfq_nineturn_checkpoint_partitions",
                    side_effect=checkpoint_audit,
                ) as checkpoint_audited,
            ):
                first = publish_stock_daily_qfq_nineturn_serving_history(
                    plan=plan,
                    expected_plan_fingerprint=plan.plan_fingerprint,
                    duckdb_resource=DuckDBResource(),
                    prod_postgres_write=_FakeProdResource(),
                    checkpoint_path=checkpoint_path,
                )
                second = publish_stock_daily_qfq_nineturn_serving_history(
                    plan=plan,
                    expected_plan_fingerprint=plan.plan_fingerprint,
                    duckdb_resource=DuckDBResource(),
                    prod_postgres_write=_FakeProdResource(),
                    checkpoint_path=checkpoint_path,
                )

            self.assertEqual(first.published_partition_keys, ("2026-08-11",))
            self.assertEqual(first.remaining_partition_count, 1)
            self.assertEqual(second.resumed_partition_keys, ("2026-08-11",))
            self.assertEqual(second.published_partition_keys, ("2026-08-12",))
            self.assertEqual(second.remaining_partition_count, 0)
            self.assertEqual(replaced, ["2026-08-11", "2026-08-12"])
            self.assertEqual(audited.call_count, 2)
            checkpoint_audited.assert_called_once()
            checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
            self.assertEqual(checkpoint["completed_partition_count"], 2)

    def test_stale_plan_stops_before_prod_write(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            lake_root = base / "lake"
            source_path = _write_partition(lake_root, "2026-08-12")
            plan = plan_stock_daily_qfq_nineturn_serving_history(
                lake_root=lake_root,
                staging_root=base / "staging",
                duckdb_resource=DuckDBResource(),
                output_dir=base / "reports",
            )
            source_path.touch()

            with self.assertRaisesRegex(
                StockDailyQfqNineTurnServingHistoryError,
                "stale",
            ):
                publish_stock_daily_qfq_nineturn_serving_history(
                    plan=plan,
                    expected_plan_fingerprint=plan.plan_fingerprint,
                    duckdb_resource=DuckDBResource(),
                    prod_postgres_write=_FakeProdResource(),
                    checkpoint_path=base / "staging" / "checkpoint.json",
                )

    def test_batch_count_limit_processes_multiple_bounded_batches(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            lake_root = base / "lake"
            staging_root = base / "staging"
            for partition_key in ("2026-08-10", "2026-08-11", "2026-08-12"):
                _write_partition(lake_root, partition_key)
            plan = plan_stock_daily_qfq_nineturn_serving_history(
                lake_root=lake_root,
                staging_root=staging_root,
                duckdb_resource=DuckDBResource(),
                batch_partition_limit=2,
                output_dir=base / "reports",
            )

            prod_resource = _FakeProdResource()
            progress_events: list[dict[str, object]] = []
            with (
                patch(
                    "orchestrator.defs.bootstrap.stock_daily_qfq_nineturn_serving_history."
                    "replace_prod_core_stock_daily_qfq_nineturn_partition"
                ),
                patch(
                    "orchestrator.defs.bootstrap.stock_daily_qfq_nineturn_serving_history."
                    "audit_prod_core_stock_daily_qfq_nineturn_partition",
                    side_effect=lambda *, partition_key, **_kwargs: SimpleNamespace(
                        passed=True,
                        expected_content_hash=_content_hash(partition_key),
                    ),
                ),
                patch(
                    "orchestrator.defs.bootstrap.stock_daily_qfq_nineturn_serving_history."
                    "plan_stock_daily_qfq_nineturn_serving_history",
                    side_effect=AssertionError("publish must not regenerate a deep plan"),
                ),
            ):
                report = publish_stock_daily_qfq_nineturn_serving_history(
                    plan=plan,
                    expected_plan_fingerprint=plan.plan_fingerprint,
                    duckdb_resource=DuckDBResource(),
                    prod_postgres_write=prod_resource,
                    checkpoint_path=staging_root / "serving" / "checkpoint.json",
                    batch_count_limit=2,
                    progress_callback=progress_events.append,
                )

            self.assertEqual(
                report.published_partition_keys,
                ("2026-08-10", "2026-08-11", "2026-08-12"),
            )
            self.assertEqual(report.processed_batch_count, 2)
            self.assertEqual(report.remaining_partition_count, 0)
            self.assertEqual(prod_resource.write_connect_count, 2)
            self.assertEqual(prod_resource.read_connect_count, 2)
            self.assertEqual(prod_resource.write_connection.commit_count, 3)
            self.assertEqual(prod_resource.read_connection.rollback_count, 3)
            self.assertEqual(
                [event["event"] for event in progress_events],
                ["batch_published", "batch_published"],
            )
            self.assertEqual(
                [event["batch_published_partition_count"] for event in progress_events],
                [2, 1],
            )
            summary = report.to_dict()
            self.assertNotIn("selected_partition_keys", summary)
            self.assertNotIn("published_partition_keys", summary)
            self.assertNotIn("resumed_partition_keys", summary)
            self.assertEqual(summary["published_partition_count"], 3)

    def test_post_commit_audit_failure_does_not_advance_checkpoint(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            lake_root = base / "lake"
            staging_root = base / "staging"
            _write_partition(lake_root, "2026-08-12")
            plan = plan_stock_daily_qfq_nineturn_serving_history(
                lake_root=lake_root,
                staging_root=staging_root,
                duckdb_resource=DuckDBResource(),
                output_dir=base / "reports",
            )
            checkpoint_path = staging_root / "serving" / "checkpoint.json"
            prod_resource = _FakeProdResource()

            with (
                patch(
                    "orchestrator.defs.bootstrap.stock_daily_qfq_nineturn_serving_history."
                    "replace_prod_core_stock_daily_qfq_nineturn_partition"
                ),
                patch(
                    "orchestrator.defs.bootstrap.stock_daily_qfq_nineturn_serving_history."
                    "audit_prod_core_stock_daily_qfq_nineturn_partition",
                    return_value=SimpleNamespace(
                        passed=False,
                        expected_content_hash="untrusted",
                    ),
                ),
                self.assertRaisesRegex(
                    StockDailyQfqNineTurnServingHistoryError,
                    "read-back failed",
                ),
            ):
                publish_stock_daily_qfq_nineturn_serving_history(
                    plan=plan,
                    expected_plan_fingerprint=plan.plan_fingerprint,
                    duckdb_resource=DuckDBResource(),
                    prod_postgres_write=prod_resource,
                    checkpoint_path=checkpoint_path,
                )

            self.assertEqual(prod_resource.write_connection.commit_count, 1)
            self.assertEqual(prod_resource.read_connection.rollback_count, 1)
            self.assertFalse(checkpoint_path.exists())

    def test_batch_limit_cannot_exceed_twenty_partitions(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            with self.assertRaisesRegex(
                StockDailyQfqNineTurnServingHistoryError,
                "between 1 and 20",
            ):
                plan_stock_daily_qfq_nineturn_serving_history(
                    lake_root=base / "lake",
                    staging_root=base / "staging",
                    duckdb_resource=DuckDBResource(),
                    batch_partition_limit=21,
                    output_dir=base / "reports",
                )

    def test_batch_count_limit_cannot_exceed_ten(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            lake_root = base / "lake"
            _write_partition(lake_root, "2026-08-12")
            plan = plan_stock_daily_qfq_nineturn_serving_history(
                lake_root=lake_root,
                staging_root=base / "staging",
                duckdb_resource=DuckDBResource(),
                output_dir=base / "reports",
            )

            with self.assertRaisesRegex(
                StockDailyQfqNineTurnServingHistoryError,
                "between 1 and 10",
            ):
                publish_stock_daily_qfq_nineturn_serving_history(
                    plan=plan,
                    expected_plan_fingerprint=plan.plan_fingerprint,
                    duckdb_resource=DuckDBResource(),
                    prod_postgres_write=_FakeProdResource(),
                    checkpoint_path=base / "staging" / "checkpoint.json",
                    batch_count_limit=11,
                )

    def test_formal_lake_rejects_noncanonical_staging_root(self) -> None:
        with self.assertRaisesRegex(
            StockDailyQfqNineTurnServingHistoryError,
            "fixed data_lake_staging root",
        ):
            plan_stock_daily_qfq_nineturn_serving_history(
                lake_root=Path(DEFAULT_LAKE_ROOT),
                staging_root=Path(DEFAULT_LAKE_ROOT) / "_staging",
                duckdb_resource=DuckDBResource(),
            )

    def test_sample_mode_rejects_more_than_three_partitions(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            lake_root = base / "lake"
            for partition_key in (
                "2026-08-07",
                "2026-08-08",
                "2026-08-11",
                "2026-08-12",
            ):
                _write_partition(lake_root, partition_key)
            plan = plan_stock_daily_qfq_nineturn_serving_history(
                lake_root=lake_root,
                staging_root=base / "staging",
                duckdb_resource=DuckDBResource(),
                output_dir=base / "reports",
            )

            with self.assertRaisesRegex(
                StockDailyQfqNineTurnServingHistoryError,
                "one to three explicit partitions",
            ):
                publish_stock_daily_qfq_nineturn_serving_history(
                    plan=plan,
                    expected_plan_fingerprint=plan.plan_fingerprint,
                    duckdb_resource=DuckDBResource(),
                    prod_postgres_write=_FakeProdResource(),
                    checkpoint_path=base / "staging" / "checkpoint.json",
                    mode="sample",
                    sample_partition_keys=tuple(
                        partition.partition_key for partition in plan.partitions
                    ),
                )


def _write_partition(
    lake_root: Path,
    partition_key: str,
    *,
    qfq_close: float = 12.5,
) -> Path:
    qfq_path = gold_stock_daily_qfq_path(lake_root, partition_key)
    target_path = gold_stock_daily_qfq_nineturn_path(lake_root, partition_key)
    qfq_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect() as connection:
        connection.execute(
            f"""
            COPY (
              SELECT * FROM (VALUES
                ('000001.SZ', DATE '{partition_key}', 10.0, 13.0, 9.0, {qfq_close},
                 12.0, 0.5, 4.2, 1000.0, 12000.0),
                ('600000.SH', DATE '{partition_key}', 8.0, 9.0, 7.5, 8.2,
                 8.0, 0.2, 2.5, 800.0, 7000.0)
              ) AS rows(ts_code, trade_date, open, high, low, close, pre_close,
                        change_amount, pct_chg, vol, amount)
            ) TO '{qfq_path.as_posix()}' (FORMAT PARQUET)
            """
        )
        connection.execute(
            f"""
            COPY (
              SELECT * FROM (VALUES
                ('000001.SZ', DATE '{partition_key}',
                 10::INTEGER, 0::INTEGER, '+9'::VARCHAR, NULL::VARCHAR),
                ('600000.SH', DATE '{partition_key}',
                 0::INTEGER, 4::INTEGER, NULL::VARCHAR, NULL::VARCHAR)
              ) AS rows(ts_code, trade_date, up_count, down_count,
                        nine_up_turn, nine_down_turn)
            ) TO '{target_path.as_posix()}' (FORMAT PARQUET)
            """
        )
    return target_path


def _content_hash(partition_key: str) -> str:
    return hashlib.sha256(partition_key.encode("utf-8")).hexdigest()


if __name__ == "__main__":
    unittest.main()
