from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from orchestrator.defs.bootstrap.gold_stock_daily_qfq_history_reset import (
    execute_gold_stock_daily_qfq_history_reset,
    gold_stock_daily_qfq_history_reset_delete_sql_statements,
    gold_stock_daily_qfq_history_reset_sql_statements,
)


class GoldStockDailyQfqHistoryResetTests(unittest.TestCase):
    def test_dry_run_sql_statements_are_read_only(self) -> None:
        forbidden = (
            " delete ",
            " update ",
            " insert ",
            " merge ",
            " drop ",
            " alter ",
            " truncate ",
            " vacuum ",
            " analyze ",
            " create ",
        )
        for sql in gold_stock_daily_qfq_history_reset_sql_statements():
            normalized = f" {' '.join(sql.lower().split())} "
            self.assertTrue(
                normalized.strip().startswith(("-- query:", "with", "select")),
                msg=sql,
            )
            for token in forbidden:
                self.assertNotIn(token, normalized, msg=sql)

    def test_delete_sql_statements_use_fixed_scoped_order(self) -> None:
        query_names = [
            _query_name(sql)
            for sql in gold_stock_daily_qfq_history_reset_delete_sql_statements()
        ]

        self.assertEqual(
            query_names,
            [
                "reset_delete_check_event_tags",
                "reset_delete_check_events",
                "reset_delete_check_executions",
                "reset_delete_materialization_event_tags",
                "reset_delete_materialization_events",
            ],
        )
        for sql in gold_stock_daily_qfq_history_reset_delete_sql_statements():
            self.assertIn("DELETE FROM", sql)
            self.assertIn("asset_scope AS", sql)
            self.assertIn("%(asset_key)s", sql)
            self.assertNotIn("DELETE FROM runs", sql)
            self.assertNotIn("DELETE FROM run_tags", sql)
            self.assertNotIn("DELETE FROM dynamic_partitions", sql)
            self.assertNotIn("gold_stock_daily_qfq_qfq_semantics_check", sql)

    def test_dry_run_reports_scoped_file_and_event_candidates(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            target_file = (
                root
                / "gold"
                / "quote"
                / "stock_daily_qfq"
                / "trade_date=2026-06-18"
                / "part-000.parquet"
            )
            target_file.parent.mkdir(parents=True)
            target_file.write_bytes(b"qfq")
            connection = _FakeConnection(_minimal_rows_by_query())

            report = execute_gold_stock_daily_qfq_history_reset(
                connection,
                lake_root=root,
            )

        payload = report.to_payload()
        self.assertFalse(payload["should_stop"])
        self.assertFalse(payload["apply"])
        self.assertFalse(payload["committed"])
        self.assertEqual(connection.readonly, True)
        self.assertEqual(payload["lake_file_candidate_count"], 1)
        self.assertEqual(payload["event_candidate_counts"]["check_candidate_count"], 2)
        self.assertEqual(payload["event_candidate_counts"]["materialization_candidate_count"], 1)

    def test_apply_requires_confirmation_and_backup(self) -> None:
        connection = _FakeConnection(_minimal_rows_by_query())

        with self.assertRaisesRegex(ValueError, "--confirm-reset"):
            execute_gold_stock_daily_qfq_history_reset(
                connection,
                apply=True,
                confirm_reset=False,
                backup_path="/private/tmp/missing.dump",
            )
        with self.assertRaisesRegex(FileNotFoundError, "backup path does not exist"):
            execute_gold_stock_daily_qfq_history_reset(
                connection,
                apply=True,
                confirm_reset=True,
                backup_path="/private/tmp/missing.dump",
            )

    def test_apply_deletes_only_scoped_lake_files(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            backup_path = root / "backup.dump"
            backup_path.write_text("backup", encoding="utf-8")
            target_file = (
                root
                / "gold"
                / "quote"
                / "stock_daily_qfq"
                / "trade_date=2026-06-18"
                / "part-000.parquet"
            )
            target_file.parent.mkdir(parents=True)
            target_file.write_bytes(b"qfq")
            unrelated_file = (
                root
                / "gold"
                / "quote"
                / "stock_daily"
                / "trade_date=2026-06-18"
                / "part-000.parquet"
            )
            unrelated_file.parent.mkdir(parents=True)
            unrelated_file.write_bytes(b"silver")
            connection = _FakeWriteConnection(
                _minimal_rows_by_query(),
                delete_rowcounts={
                    "delete_check_event_tags": 2,
                    "delete_check_events": 2,
                    "delete_check_executions": 2,
                    "delete_materialization_event_tags": 1,
                    "delete_materialization_events": 1,
                },
            )

            report = execute_gold_stock_daily_qfq_history_reset(
                connection,
                lake_root=root,
                apply=True,
                confirm_reset=True,
                backup_path=str(backup_path),
                delete_lake_files=True,
                delete_dagster_events=False,
            )

            self.assertFalse(target_file.exists())
            self.assertTrue(unrelated_file.exists())

        self.assertTrue(connection.committed)
        self.assertFalse(connection.rolled_back)
        self.assertEqual(connection.executed_delete_queries, [])
        self.assertEqual(report.deleted_lake_file_count, 1)
        self.assertTrue(report.committed)

    def test_apply_deletes_dagster_events_as_separate_approved_scope(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            backup_path = root / "backup.dump"
            backup_path.write_text("backup", encoding="utf-8")
            connection = _FakeWriteConnection(
                _minimal_rows_by_query(),
                delete_rowcounts={
                    "delete_check_event_tags": 2,
                    "delete_check_events": 2,
                    "delete_check_executions": 2,
                    "delete_materialization_event_tags": 1,
                    "delete_materialization_events": 1,
                },
            )

            report = execute_gold_stock_daily_qfq_history_reset(
                connection,
                lake_root=root,
                apply=True,
                confirm_reset=True,
                backup_path=str(backup_path),
                delete_lake_files=False,
                delete_dagster_events=True,
            )

        self.assertTrue(connection.committed)
        self.assertFalse(connection.rolled_back)
        self.assertEqual(
            connection.executed_delete_queries,
            [
                "reset_delete_check_event_tags",
                "reset_delete_check_events",
                "reset_delete_check_executions",
                "reset_delete_materialization_event_tags",
                "reset_delete_materialization_events",
            ],
        )
        self.assertEqual(report.deleted_lake_file_count, 0)
        self.assertTrue(report.committed)

    def test_apply_rejects_combined_lake_and_event_scope(self) -> None:
        with TemporaryDirectory() as temp_dir:
            backup_path = Path(temp_dir) / "backup.dump"
            backup_path.write_text("backup", encoding="utf-8")
            connection = _FakeConnection(_minimal_rows_by_query())

            with self.assertRaisesRegex(ValueError, "exactly one delete scope"):
                execute_gold_stock_daily_qfq_history_reset(
                    connection,
                    apply=True,
                    confirm_reset=True,
                    backup_path=str(backup_path),
                    delete_lake_files=True,
                    delete_dagster_events=True,
                )


def _minimal_rows_by_query() -> dict[str, list[dict[str, object]]]:
    return {
        "reset_running_or_queued_run_count": [
            {"running_or_queued_run_count": 0}
        ],
        "reset_event_candidate_counts": [
            {
                "check_candidate_count": 2,
                "check_event_candidate_count": 2,
                "check_event_tag_candidate_count": 0,
                "materialization_candidate_count": 1,
                "materialization_event_tag_candidate_count": 0,
            }
        ],
        "reset_protected_check_event_counts": [
            {
                "asset_key": '["gold_stock_daily_qfq"]',
                "check_name": "gold_stock_daily_qfq_factor_repair_plan_evaluated",
                "check_event_count": 3,
            }
        ],
        "reset_event_candidate_samples": [
            {
                "candidate_type": "asset_check_execution",
                "asset_key": '["gold_stock_daily_qfq"]',
                "check_name": "gold_stock_daily_qfq_contract_check",
                "partition": "2026-06-18",
                "run_id": "run-check",
                "event_storage_id": 10,
                "materialization_event_storage_id": 9,
                "event_timestamp": "2026-06-18T20:00:00",
            }
        ],
        "reset_safety_counts": [
            {
                "protected_check_candidate_count": 0,
                "check_event_type_mismatch_count": 0,
                "check_null_partition_candidate_count": 0,
                "materialization_null_partition_candidate_count": 0,
                "other_asset_candidate_count": 0,
            }
        ],
    }


class _FakeConnection:
    def __init__(self, rows_by_query: dict[str, list[dict[str, object]]]) -> None:
        self.rows_by_query = rows_by_query
        self.readonly = False

    def set_session(self, *, readonly: bool, autocommit: bool) -> None:
        self.readonly = readonly
        if autocommit:
            raise AssertionError("reset helper must not use autocommit")

    def cursor(self, *_, **__) -> "_FakeCursor":
        return _FakeCursor(self.rows_by_query)

    def rollback(self) -> None:
        return None


class _FakeWriteConnection(_FakeConnection):
    def __init__(
        self,
        rows_by_query: dict[str, list[dict[str, object]]],
        *,
        delete_rowcounts: dict[str, int],
    ) -> None:
        super().__init__(rows_by_query)
        self.delete_rowcounts = delete_rowcounts
        self.committed = False
        self.rolled_back = False
        self.executed_delete_queries: list[str] = []

    def set_session(self, *, readonly: bool, autocommit: bool) -> None:
        self.readonly = readonly
        if readonly:
            raise AssertionError("reset apply must not use a read-only session")
        if autocommit:
            raise AssertionError("reset apply must use an explicit transaction")

    def cursor(self, *_, **__) -> "_FakeWriteCursor":
        return _FakeWriteCursor(
            self.rows_by_query,
            delete_rowcounts=self.delete_rowcounts,
            executed_delete_queries=self.executed_delete_queries,
        )

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True


class _FakeCursor:
    def __init__(self, rows_by_query: dict[str, list[dict[str, object]]]) -> None:
        self.rows_by_query = rows_by_query
        self.current_rows: list[dict[str, object]] = []

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, *_exc) -> None:
        return None

    def execute(self, sql: str, _params=None) -> None:
        query_name = _query_name(sql)
        if query_name not in self.rows_by_query:
            raise AssertionError(f"Unexpected query: {query_name}")
        self.current_rows = self.rows_by_query[query_name]

    def fetchall(self) -> list[dict[str, object]]:
        return list(self.current_rows)


class _FakeWriteCursor(_FakeCursor):
    def __init__(
        self,
        rows_by_query: dict[str, list[dict[str, object]]],
        *,
        delete_rowcounts: dict[str, int],
        executed_delete_queries: list[str],
    ) -> None:
        super().__init__(rows_by_query)
        self.delete_rowcounts = delete_rowcounts
        self.executed_delete_queries = executed_delete_queries
        self.rowcount = 0

    def execute(self, sql: str, _params=None) -> None:
        query_name = _query_name(sql)
        if query_name.startswith("reset_delete_"):
            self.executed_delete_queries.append(query_name)
            self.rowcount = self.delete_rowcounts.get(query_name, 0)
            self.current_rows = []
            return
        super().execute(sql, _params)
        self.rowcount = len(self.current_rows)


def _query_name(sql: str) -> str:
    for line in sql.splitlines():
        stripped = line.strip()
        if stripped.startswith("-- query:"):
            return stripped.removeprefix("-- query:").strip()
    raise AssertionError(f"SQL missing query name: {sql}")


if __name__ == "__main__":
    unittest.main()
