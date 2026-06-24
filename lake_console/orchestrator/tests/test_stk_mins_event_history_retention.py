from __future__ import annotations

import inspect
import unittest

from orchestrator.defs.bootstrap import stk_mins_event_history_retention as retention
from orchestrator.defs.bootstrap import stk_mins_event_history_retention_cli
from orchestrator.defs.bootstrap import (
    stk_mins_event_history_retention_sample_delete as sample_delete,
)
from orchestrator.defs.bootstrap import (
    stk_mins_event_history_retention_sample_delete_cli,
)
from orchestrator.defs.bootstrap.stk_mins_event_history_retention import (
    STK_MINS_RETENTION_ASSET_KEYS,
    STK_MINS_RETENTION_KEEP_PARTITION_SET_NAME,
    STK_MINS_RETENTION_PROTECTED_CHECK_NAMES,
    collect_stk_mins_event_history_retention_dry_run,
    stk_mins_event_history_retention_sql_statements,
)
from orchestrator.defs.bootstrap.stk_mins_event_history_retention_sample_delete import (
    STK_MINS_RETENTION_DEFAULT_SAMPLE_DELETE_ASSET,
    execute_stk_mins_event_history_retention_sample_delete,
    stk_mins_event_history_retention_sample_delete_sql_statements,
)


class StkMinsEventHistoryRetentionTests(unittest.TestCase):
    def test_sql_statements_are_read_only(self) -> None:
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
        for sql in stk_mins_event_history_retention_sql_statements():
            normalized = f" {' '.join(sql.lower().split())} "
            self.assertTrue(
                normalized.strip().startswith(("-- query:", "with", "select")),
                msg=sql,
            )
            for token in forbidden:
                self.assertNotIn(token, normalized, msg=sql)

    def test_asset_scope_and_protected_checks_are_fixed_to_stock_mins(self) -> None:
        self.assertEqual(len(STK_MINS_RETENTION_ASSET_KEYS), 31)
        self.assertIn('["raw_stk_mins_1m"]', STK_MINS_RETENTION_ASSET_KEYS)
        self.assertIn('["silver_stk_mins_60m"]', STK_MINS_RETENTION_ASSET_KEYS)
        self.assertIn('["gold_stk_mins_qfq_120m"]', STK_MINS_RETENTION_ASSET_KEYS)
        self.assertIn(
            '["gold_stk_mins_qfq_macd_kdj_90m"]',
            STK_MINS_RETENTION_ASSET_KEYS,
        )
        self.assertIn(
            '["gold_stk_mins_qfq_macd_kdj_state_120m"]',
            STK_MINS_RETENTION_ASSET_KEYS,
        )
        self.assertNotIn(
            '["prod_ch_share_fact_market_breadth_daily"]',
            STK_MINS_RETENTION_ASSET_KEYS,
        )
        self.assertEqual(
            STK_MINS_RETENTION_KEEP_PARTITION_SET_NAME,
            "cn_a_stock_mins_trade_days",
        )
        self.assertIn(
            "gold_stk_mins_qfq_factor_repair_plan_evaluated",
            STK_MINS_RETENTION_PROTECTED_CHECK_NAMES,
        )
        self.assertIn(
            "gold_stk_mins_qfq_macd_kdj_repair_completed_check",
            STK_MINS_RETENTION_PROTECTED_CHECK_NAMES,
        )

    def test_module_and_cli_do_not_expose_write_or_delete_paths(self) -> None:
        module_source = inspect.getsource(retention)
        cli_source = inspect.getsource(stk_mins_event_history_retention_cli)
        combined = f"{module_source}\n{cli_source}".lower()
        for token in (
            "delete from",
            "insert into",
            "update event_logs",
            "update asset_check_executions",
            "vacuum (",
            "analyze event_logs",
            "report_runless_asset_event",
            "dagsterinstance.get",
        ):
            self.assertNotIn(token, combined)
        self.assertNotIn("--apply", combined)
        self.assertIn('"dry-run"', cli_source)

    def test_sample_delete_cli_is_separate_and_requires_confirmation(self) -> None:
        cli_source = inspect.getsource(stk_mins_event_history_retention_sample_delete_cli)
        helper_source = inspect.getsource(sample_delete)

        self.assertIn('"sample-delete"', cli_source)
        self.assertIn("--confirm-sample-delete", cli_source)
        self.assertIn(
            "STK_MINS_RETENTION_DEFAULT_SAMPLE_DELETE_ASSET",
            cli_source,
        )
        self.assertNotIn("asset_key::text LIKE", helper_source)
        self.assertNotIn("TRUNCATE", helper_source.upper())
        self.assertNotIn("DROP TABLE", helper_source.upper())
        self.assertNotIn("VACUUM", helper_source.upper())

    def test_sample_delete_sql_statements_use_fixed_delete_order(self) -> None:
        query_names = [
            _query_name(sql)
            for sql in stk_mins_event_history_retention_sample_delete_sql_statements()
        ]

        self.assertEqual(
            query_names,
            [
                "delete_check_event_tags",
                "delete_check_events",
                "delete_check_executions",
                "delete_materialization_event_tags",
                "delete_materialization_events",
            ],
        )
        for sql in stk_mins_event_history_retention_sample_delete_sql_statements():
            self.assertIn("DELETE FROM", sql)
            self.assertNotIn("runs", sql.lower())
            self.assertNotIn("run_tags", sql.lower())
            self.assertNotIn("dynamic_partitions", sql.split("DELETE FROM", 1)[-1].lower())

    def test_collect_report_uses_keep_window_and_latest_protection(self) -> None:
        asset_keys = (
            "raw_stk_mins_1m",
            "gold_stk_mins_qfq_macd_kdj_state_120m",
        )
        connection = _FakeConnection(
            {
                "table_counts": [{"table_name": "event_logs", "row_count": 100}],
                "table_sizes": [
                    {
                        "table_name": "event_logs",
                        "total_bytes": 1024,
                        "total_size": "1024 bytes",
                    }
                ],
                "run_status_counts": [{"status": "SUCCESS", "run_count": 10}],
                "running_or_queued_run_count": [
                    {"running_or_queued_run_count": 0}
                ],
                "keep_partitions": [
                    {"partition": "2026-06-22"},
                    {"partition": "2026-06-23"},
                ],
                "candidate_check_counts_by_asset": [
                    {
                        "asset_key": '["raw_stk_mins_1m"]',
                        "check_candidate_count": 3,
                        "check_event_candidate_count": 3,
                        "check_event_tag_candidate_count": 0,
                    }
                ],
                "candidate_materialization_counts_by_asset": [
                    {
                        "asset_key": '["gold_stk_mins_qfq_macd_kdj_state_120m"]',
                        "materialization_candidate_count": 1,
                        "materialization_event_tag_candidate_count": 1,
                    }
                ],
                "candidate_check_counts_by_check": [
                    {
                        "asset_key": '["raw_stk_mins_1m"]',
                        "check_name": "raw_stk_mins_contract_check",
                        "check_candidate_count": 3,
                    }
                ],
                "latest_state_summary_by_asset": [
                    {
                        "asset_key": '["raw_stk_mins_1m"]',
                        "latest_materialization_id": 100,
                        "latest_partition": "2026-06-23",
                        "latest_run_id": "run-latest",
                        "latest_timestamp": "2026-06-23T20:00:00",
                        "latest_check_count": 1,
                        "latest_succeeded_check_count": 1,
                        "latest_non_succeeded_check_count": 0,
                    },
                    {
                        "asset_key": '["gold_stk_mins_qfq_macd_kdj_state_120m"]',
                        "latest_materialization_id": 200,
                        "latest_partition": "2026-06-23",
                        "latest_run_id": "run-latest",
                        "latest_timestamp": "2026-06-23T20:00:00",
                        "latest_check_count": 1,
                        "latest_succeeded_check_count": 1,
                        "latest_non_succeeded_check_count": 0,
                    },
                ],
                "protected_check_event_counts": [
                    {
                        "asset_key": '["gold_stk_mins_qfq_1m"]',
                        "check_name": "gold_stk_mins_qfq_factor_repair_plan_evaluated",
                        "check_event_count": 188,
                    }
                ],
                "candidate_check_samples": [
                    {
                        "asset_key": '["raw_stk_mins_1m"]',
                        "check_name": "raw_stk_mins_contract_check",
                        "partition": "2026-06-18",
                        "run_id": "run-1",
                        "execution_status": "SUCCEEDED",
                        "evaluation_event_storage_id": 11,
                        "materialization_event_storage_id": 10,
                    }
                ],
                "candidate_materialization_samples": [
                    {
                        "asset_key": '["gold_stk_mins_qfq_macd_kdj_state_120m"]',
                        "partition": "2026-06-18",
                        "run_id": "run-1",
                        "event_storage_id": 10,
                        "timestamp": "2026-06-18T20:00:00",
                    }
                ],
                "safety_counts": [_zero_safety_counts()],
            }
        )

        report = collect_stk_mins_event_history_retention_dry_run(
            connection,
            asset_keys=asset_keys,
            keep_trade_day_count=2,
        )

        self.assertFalse(report.should_stop)
        self.assertTrue(connection.readonly)
        self.assertEqual(report.keep_partition_set_name, "cn_a_stock_mins_trade_days")
        self.assertEqual(report.candidate_totals["check_candidate_count"], 3)
        self.assertEqual(
            report.candidate_totals["materialization_candidate_count"],
            1,
        )
        self.assertTrue(
            all(assertion["passed"] for assertion in report.safety_assertions)
        )
        payload = report.to_payload()
        self.assertEqual(
            payload["mode"],
            "stk_mins_event_history_retention_dry_run_only",
        )

    def test_running_run_marks_report_as_stop(self) -> None:
        rows_by_query = _minimal_rows_by_query()
        rows_by_query["running_or_queued_run_count"] = [
            {"running_or_queued_run_count": 1}
        ]
        rows_by_query["run_status_counts"] = [
            {"status": "QUEUED", "run_count": 1}
        ]

        report = collect_stk_mins_event_history_retention_dry_run(
            _FakeConnection(rows_by_query),
            asset_keys=("raw_stk_mins_1m",),
            keep_trade_day_count=2,
        )

        assertion_by_name = {
            assertion["name"]: assertion for assertion in report.safety_assertions
        }
        self.assertTrue(report.should_stop)
        self.assertFalse(assertion_by_name["no_running_or_queued_runs"]["passed"])

    def test_short_keep_window_marks_report_as_stop(self) -> None:
        rows_by_query = _minimal_rows_by_query()
        rows_by_query["keep_partitions"] = [{"partition": "2026-06-23"}]

        report = collect_stk_mins_event_history_retention_dry_run(
            _FakeConnection(rows_by_query),
            asset_keys=("raw_stk_mins_1m",),
            keep_trade_day_count=2,
        )

        assertion_by_name = {
            assertion["name"]: assertion for assertion in report.safety_assertions
        }
        self.assertTrue(report.should_stop)
        self.assertFalse(
            assertion_by_name["keep_window_has_expected_trade_day_count"]["passed"]
        )

    def test_sample_delete_requires_confirmation(self) -> None:
        with self.assertRaisesRegex(ValueError, "--confirm-sample-delete"):
            execute_stk_mins_event_history_retention_sample_delete(
                _FakeWriteConnection(_sample_delete_rows_by_query()),
                confirm_sample_delete=False,
            )

    def test_sample_delete_rejects_non_whitelist_asset(self) -> None:
        with self.assertRaisesRegex(ValueError, "not in stock-mins retention whitelist"):
            execute_stk_mins_event_history_retention_sample_delete(
                _FakeWriteConnection(_sample_delete_rows_by_query()),
                sample_asset="prod_ch_share_fact_market_breadth_daily",
                confirm_sample_delete=True,
            )

    def test_sample_delete_rejects_multiple_assets(self) -> None:
        with self.assertRaisesRegex(ValueError, "exactly one sample asset"):
            execute_stk_mins_event_history_retention_sample_delete(
                _FakeWriteConnection(_sample_delete_rows_by_query()),
                sample_asset=("raw_stk_mins_1m", "raw_stk_mins_5m"),
                confirm_sample_delete=True,
            )

    def test_sample_delete_commits_fixed_delete_order(self) -> None:
        connection = _FakeWriteConnection(
            _sample_delete_rows_by_query(),
            delete_rowcounts={
                "delete_check_event_tags": 0,
                "delete_check_events": 6020,
                "delete_check_executions": 6020,
                "delete_materialization_event_tags": 3,
                "delete_materialization_events": 3010,
            },
        )

        report = execute_stk_mins_event_history_retention_sample_delete(
            connection,
            sample_asset=STK_MINS_RETENTION_DEFAULT_SAMPLE_DELETE_ASSET,
            confirm_sample_delete=True,
            keep_trade_day_count=2,
        )

        self.assertTrue(connection.committed)
        self.assertFalse(connection.rolled_back)
        self.assertFalse(report.should_stop)
        self.assertTrue(report.committed)
        self.assertEqual(
            [row["step"] for row in report.delete_counts],
            [
                "delete_check_event_tags",
                "delete_check_events",
                "delete_check_executions",
                "delete_materialization_event_tags",
                "delete_materialization_events",
            ],
        )
        self.assertEqual(
            connection.executed_delete_queries,
            [
                "delete_check_event_tags",
                "delete_check_events",
                "delete_check_executions",
                "delete_materialization_event_tags",
                "delete_materialization_events",
            ],
        )
        self.assertEqual(report.candidate_totals["check_candidate_count"], 6020)
        self.assertEqual(
            report.candidate_totals["materialization_candidate_count"],
            3010,
        )

    def test_sample_delete_rolls_back_when_safety_assertion_fails(self) -> None:
        rows_by_query = _sample_delete_rows_by_query()
        rows_by_query["sample_delete_safety_counts"] = [
            {
                **_zero_safety_counts(),
                "protected_check_candidate_count": 1,
            }
        ]
        connection = _FakeWriteConnection(rows_by_query)

        with self.assertRaisesRegex(RuntimeError, "safety assertions failed"):
            execute_stk_mins_event_history_retention_sample_delete(
                connection,
                sample_asset=STK_MINS_RETENTION_DEFAULT_SAMPLE_DELETE_ASSET,
                confirm_sample_delete=True,
                keep_trade_day_count=2,
            )

        self.assertFalse(connection.committed)
        self.assertTrue(connection.rolled_back)
        self.assertEqual(connection.executed_delete_queries, [])


def _minimal_rows_by_query() -> dict[str, list[dict[str, object]]]:
    return {
        "table_counts": [],
        "table_sizes": [],
        "run_status_counts": [],
        "running_or_queued_run_count": [{"running_or_queued_run_count": 0}],
        "keep_partitions": [
            {"partition": "2026-06-22"},
            {"partition": "2026-06-23"},
        ],
        "candidate_check_counts_by_asset": [],
        "candidate_materialization_counts_by_asset": [],
        "candidate_check_counts_by_check": [],
        "latest_state_summary_by_asset": [
            {
                "asset_key": '["raw_stk_mins_1m"]',
                "latest_materialization_id": 100,
                "latest_partition": "2026-06-23",
                "latest_run_id": "run-latest",
                "latest_timestamp": "2026-06-23T20:00:00",
                "latest_check_count": 1,
                "latest_succeeded_check_count": 1,
                "latest_non_succeeded_check_count": 0,
            }
        ],
        "protected_check_event_counts": [],
        "candidate_check_samples": [],
        "candidate_materialization_samples": [],
        "safety_counts": [_zero_safety_counts()],
    }


def _sample_delete_rows_by_query() -> dict[str, list[dict[str, object]]]:
    sample_asset_key = '["gold_stk_mins_qfq_macd_kdj_state_120m"]'
    return {
        "sample_delete_running_or_queued_run_count": [
            {"running_or_queued_run_count": 0}
        ],
        "sample_delete_keep_partitions": [
            {"partition": "2026-06-22"},
            {"partition": "2026-06-23"},
        ],
        "sample_delete_candidate_check_counts_by_asset": [
            {
                "asset_key": sample_asset_key,
                "check_candidate_count": 6020,
                "check_event_candidate_count": 6020,
                "check_event_tag_candidate_count": 0,
            }
        ],
        "sample_delete_candidate_materialization_counts_by_asset": [
            {
                "asset_key": sample_asset_key,
                "materialization_candidate_count": 3010,
                "materialization_event_tag_candidate_count": 3,
            }
        ],
        "sample_delete_latest_state_summary_by_asset": [
            {
                "asset_key": sample_asset_key,
                "latest_materialization_id": 6533625,
                "latest_partition": "2026-06-18",
                "latest_run_id": "run-latest",
                "latest_timestamp": "2026-06-18T20:00:00",
                "latest_check_count": 2,
                "latest_succeeded_check_count": 2,
                "latest_non_succeeded_check_count": 0,
            }
        ],
        "sample_delete_safety_counts": [_zero_safety_counts()],
    }


def _zero_safety_counts() -> dict[str, int]:
    return {
        "check_keep_partition_collision_count": 0,
        "materialization_keep_partition_collision_count": 0,
        "check_latest_state_collision_count": 0,
        "materialization_latest_state_collision_count": 0,
        "protected_check_candidate_count": 0,
        "check_null_partition_candidate_count": 0,
        "materialization_null_partition_candidate_count": 0,
        "check_event_type_mismatch_count": 0,
    }


class _FakeConnection:
    def __init__(self, rows_by_query: dict[str, list[dict[str, object]]]) -> None:
        self.rows_by_query = rows_by_query
        self.readonly = False

    def set_session(self, *, readonly: bool, autocommit: bool) -> None:
        self.readonly = readonly
        if autocommit:
            raise AssertionError("dry-run should not use autocommit")

    def cursor(self, *_, **__) -> "_FakeCursor":
        return _FakeCursor(self.rows_by_query)


class _FakeWriteConnection(_FakeConnection):
    def __init__(
        self,
        rows_by_query: dict[str, list[dict[str, object]]],
        *,
        delete_rowcounts: dict[str, int] | None = None,
    ) -> None:
        super().__init__(rows_by_query)
        self.delete_rowcounts = delete_rowcounts or {}
        self.committed = False
        self.rolled_back = False
        self.autocommit = False
        self.executed_delete_queries: list[str] = []

    def set_session(self, *, readonly: bool, autocommit: bool) -> None:
        self.readonly = readonly
        self.autocommit = autocommit
        if readonly:
            raise AssertionError("sample-delete must not open a read-only session")
        if autocommit:
            raise AssertionError("sample-delete must use an explicit transaction")

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
        if query_name.startswith("delete_"):
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
