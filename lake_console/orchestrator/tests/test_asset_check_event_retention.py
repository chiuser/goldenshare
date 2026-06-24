from __future__ import annotations

import inspect
import unittest

from orchestrator.defs.bootstrap import asset_check_event_retention as retention
from orchestrator.defs.bootstrap import asset_check_event_retention_cli
from orchestrator.defs.bootstrap import (
    asset_check_event_retention_sample_delete as sample_delete,
)
from orchestrator.defs.bootstrap import asset_check_event_retention_sample_delete_cli
from orchestrator.defs.bootstrap.asset_check_event_retention import (
    ASSET_CHECK_RETENTION_ASSET_KEYS,
    ASSET_CHECK_RETENTION_EXCLUDED_ASSETS,
    ASSET_CHECK_RETENTION_KEEP_PARTITION_SET_BY_KEY,
    ASSET_CHECK_RETENTION_PROTECTED_CHECK_NAMES,
    asset_check_event_retention_sql_statements,
    collect_asset_check_event_retention_dry_run,
)
from orchestrator.defs.bootstrap.asset_check_event_retention_sample_delete import (
    asset_check_event_retention_sample_delete_sql_statements,
    execute_asset_check_event_retention_sample_delete,
)


class AssetCheckEventRetentionTests(unittest.TestCase):
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
        for sql in asset_check_event_retention_sql_statements():
            normalized = f" {' '.join(sql.lower().split())} "
            self.assertTrue(
                normalized.strip().startswith(("-- query:", "with", "select")),
                msg=sql,
            )
            for token in forbidden:
                self.assertNotIn(token, normalized, msg=sql)

    def test_asset_scope_excludes_minutes_and_high_risk_assets(self) -> None:
        self.assertIn('["raw_index_daily"]', ASSET_CHECK_RETENTION_ASSET_KEYS)
        self.assertIn(
            '["gold_wealth_market_turnover"]',
            ASSET_CHECK_RETENTION_ASSET_KEYS,
        )
        self.assertNotIn('["raw_stk_mins_1m"]', ASSET_CHECK_RETENTION_ASSET_KEYS)
        self.assertNotIn(
            '["prod_ch_share_fact_market_breadth_daily"]',
            ASSET_CHECK_RETENTION_ASSET_KEYS,
        )
        self.assertNotIn('["lake_root_health"]', ASSET_CHECK_RETENTION_ASSET_KEYS)
        self.assertIn(
            '["prod_ch_share_fact_market_breadth_daily"]',
            {str(row["asset_key"]) for row in ASSET_CHECK_RETENTION_EXCLUDED_ASSETS},
        )
        self.assertEqual(
            ASSET_CHECK_RETENTION_KEEP_PARTITION_SET_BY_KEY[
                '["raw_index_daily"]'
            ],
            "cn_a_index_trade_days",
        )
        self.assertEqual(
            ASSET_CHECK_RETENTION_KEEP_PARTITION_SET_BY_KEY[
                '["raw_tushare_stock_daily"]'
            ],
            "cn_a_stock_trade_days",
        )
        self.assertIn(
            "gold_stk_mins_qfq_factor_repair_plan_evaluated",
            ASSET_CHECK_RETENTION_PROTECTED_CHECK_NAMES,
        )

    def test_module_and_cli_do_not_expose_write_or_delete_paths(self) -> None:
        module_source = inspect.getsource(retention)
        cli_source = inspect.getsource(asset_check_event_retention_cli)
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
            "--apply",
            "--confirm",
        ):
            self.assertNotIn(token, combined)
        self.assertIn('"dry-run"', cli_source)

    def test_sample_delete_cli_is_separate_and_requires_confirmation(self) -> None:
        cli_source = inspect.getsource(asset_check_event_retention_sample_delete_cli)
        helper_source = inspect.getsource(sample_delete)

        self.assertIn('"sample-delete"', cli_source)
        self.assertIn("--sample-asset", cli_source)
        self.assertIn("required=True", cli_source)
        self.assertIn("--confirm-sample-delete", cli_source)
        self.assertIn(
            "sample-delete requires --confirm-sample-delete",
            helper_source,
        )
        self.assertIn(
            "sample-delete requires exactly one sample asset",
            helper_source,
        )
        self.assertNotIn("asset_key::text LIKE", helper_source)
        self.assertNotIn("TRUNCATE", helper_source.upper())
        self.assertNotIn("DROP TABLE", helper_source.upper())
        self.assertNotIn("VACUUM", helper_source.upper())

    def test_sample_delete_sql_statements_use_fixed_delete_order(self) -> None:
        query_names = [
            _query_name(sql)
            for sql in asset_check_event_retention_sample_delete_sql_statements()
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
        for sql in asset_check_event_retention_sample_delete_sql_statements():
            self.assertIn("DELETE FROM", sql)
            delete_fragment = sql.split("DELETE FROM", 1)[-1].lower()
            self.assertNotIn("runs", delete_fragment)
            self.assertNotIn("run_tags", delete_fragment)
            self.assertNotIn("dynamic_partitions", delete_fragment)

    def test_collect_report_and_safety_assertions(self) -> None:
        asset_keys = (
            "raw_index_daily",
            "gold_market_breadth_daily",
            "raw_tushare_stock_basic",
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
                "keep_windows": [
                    {
                        "keep_partition_set_name": "cn_a_index_trade_days",
                        "keep_start_partition": "2026-05-26",
                        "keep_end_partition": "2026-06-23",
                        "keep_partition_count": 2,
                    },
                    {
                        "keep_partition_set_name": "cn_a_stock_trade_days",
                        "keep_start_partition": "2026-05-26",
                        "keep_end_partition": "2026-06-23",
                        "keep_partition_count": 2,
                    },
                ],
                "candidate_event_count_by_asset": [
                    {
                        "asset_key": '["raw_index_daily"]',
                        "asset_family": "index_daily",
                        "check_candidate_count": 3,
                        "check_event_candidate_count": 3,
                        "check_event_tag_candidate_count": 0,
                        "materialization_candidate_count": 1,
                        "materialization_event_tag_candidate_count": 1,
                    },
                    {
                        "asset_key": '["raw_tushare_stock_basic"]',
                        "asset_family": "stock_basic",
                        "check_candidate_count": 0,
                        "check_event_candidate_count": 0,
                        "check_event_tag_candidate_count": 0,
                        "materialization_candidate_count": 0,
                        "materialization_event_tag_candidate_count": 0,
                    },
                ],
                "candidate_event_count_by_check": [
                    {
                        "asset_key": '["raw_index_daily"]',
                        "asset_family": "index_daily",
                        "check_name": "raw_index_daily_file_contract_check",
                        "check_candidate_count": 3,
                    }
                ],
                "latest_state_summary_by_asset": [
                    {
                        "asset_key": '["raw_index_daily"]',
                        "asset_family": "index_daily",
                        "keep_partition_set_name": "cn_a_index_trade_days",
                        "latest_materialization_id": 100,
                        "latest_partition": "2026-06-23",
                        "latest_run_id": "run-latest",
                        "latest_timestamp": "2026-06-23T20:00:00",
                        "latest_check_count": 2,
                        "latest_succeeded_check_count": 2,
                        "latest_non_succeeded_check_count": 0,
                    }
                ],
                "protected_check_event_counts": [],
                "candidate_check_samples": [
                    {
                        "asset_key": '["raw_index_daily"]',
                        "asset_family": "index_daily",
                        "check_name": "raw_index_daily_file_contract_check",
                        "partition": "2026-06-18",
                        "run_id": "run-1",
                        "execution_status": "SUCCEEDED",
                        "evaluation_event_storage_id": 11,
                        "materialization_event_storage_id": 10,
                    }
                ],
                "candidate_materialization_samples": [
                    {
                        "asset_key": '["raw_index_daily"]',
                        "asset_family": "index_daily",
                        "partition": "2026-06-18",
                        "run_id": "run-1",
                        "event_storage_id": 10,
                        "timestamp": "2026-06-18T20:00:00",
                    }
                ],
                "safety_counts": [_zero_safety_counts()],
            }
        )

        report = collect_asset_check_event_retention_dry_run(
            connection,
            asset_keys=asset_keys,
            keep_trade_day_count=2,
        )

        self.assertFalse(report.should_stop)
        self.assertTrue(connection.readonly)
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
            "asset_check_event_retention_dry_run_only",
        )
        self.assertTrue(payload["excluded_asset_samples"])

    def test_running_run_marks_report_as_stop(self) -> None:
        rows_by_query = _minimal_rows_by_query()
        rows_by_query["running_or_queued_run_count"] = [
            {"running_or_queued_run_count": 1}
        ]
        rows_by_query["run_status_counts"] = [
            {"status": "STARTED", "run_count": 1}
        ]

        report = collect_asset_check_event_retention_dry_run(
            _FakeConnection(rows_by_query),
            asset_keys=("raw_index_daily",),
            keep_trade_day_count=2,
        )

        assertion_by_name = {
            assertion["name"]: assertion for assertion in report.safety_assertions
        }
        self.assertTrue(report.should_stop)
        self.assertFalse(assertion_by_name["no_running_or_queued_runs"]["passed"])

    def test_short_keep_window_marks_report_as_stop(self) -> None:
        rows_by_query = _minimal_rows_by_query()
        rows_by_query["keep_windows"] = [
            {
                "keep_partition_set_name": "cn_a_index_trade_days",
                "keep_start_partition": "2026-06-23",
                "keep_end_partition": "2026-06-23",
                "keep_partition_count": 1,
            }
        ]

        report = collect_asset_check_event_retention_dry_run(
            _FakeConnection(rows_by_query),
            asset_keys=("raw_index_daily",),
            keep_trade_day_count=2,
        )

        assertion_by_name = {
            assertion["name"]: assertion for assertion in report.safety_assertions
        }
        self.assertTrue(report.should_stop)
        self.assertFalse(
            assertion_by_name["all_keep_windows_have_expected_trade_day_count"][
                "passed"
            ]
        )

    def test_unknown_asset_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unexpected asset keys"):
            collect_asset_check_event_retention_dry_run(
                _FakeConnection(_minimal_rows_by_query()),
                asset_keys=("raw_stk_mins_1m",),
            )

    def test_sample_delete_requires_confirmation(self) -> None:
        with self.assertRaisesRegex(ValueError, "--confirm-sample-delete"):
            execute_asset_check_event_retention_sample_delete(
                _FakeWriteConnection(_sample_delete_rows_by_query()),
                sample_asset="silver_adj_factor",
                confirm_sample_delete=False,
            )

    def test_sample_delete_rejects_non_whitelist_asset(self) -> None:
        with self.assertRaisesRegex(ValueError, "not in non-stock-mins"):
            execute_asset_check_event_retention_sample_delete(
                _FakeWriteConnection(_sample_delete_rows_by_query()),
                sample_asset="raw_stk_mins_1m",
                confirm_sample_delete=True,
            )

    def test_sample_delete_rejects_multiple_assets(self) -> None:
        with self.assertRaisesRegex(ValueError, "exactly one sample asset"):
            execute_asset_check_event_retention_sample_delete(
                _FakeWriteConnection(_sample_delete_rows_by_query()),
                sample_asset=("silver_adj_factor", "raw_tushare_adj_factor"),
                confirm_sample_delete=True,
            )

    def test_sample_delete_rejects_snapshot_asset_without_keep_set(self) -> None:
        with self.assertRaisesRegex(ValueError, "requires a partitioned"):
            execute_asset_check_event_retention_sample_delete(
                _FakeWriteConnection(_sample_delete_rows_by_query()),
                sample_asset="raw_tushare_stock_basic",
                confirm_sample_delete=True,
            )

    def test_sample_delete_commits_fixed_delete_order(self) -> None:
        connection = _FakeWriteConnection(
            _sample_delete_rows_by_query(),
            delete_rowcounts={
                "delete_check_event_tags": 0,
                "delete_check_events": 42150,
                "delete_check_executions": 42150,
                "delete_materialization_event_tags": 7,
                "delete_materialization_events": 4222,
            },
        )

        report = execute_asset_check_event_retention_sample_delete(
            connection,
            sample_asset="silver_adj_factor",
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
        self.assertEqual(
            report.keep_partition_set_name,
            "cn_a_stock_current_trade_days",
        )
        self.assertEqual(report.candidate_totals["check_candidate_count"], 42150)
        self.assertEqual(
            report.candidate_totals["materialization_candidate_count"],
            4222,
        )

    def test_sample_delete_rolls_back_when_safety_assertion_fails(self) -> None:
        rows_by_query = _sample_delete_rows_by_query()
        rows_by_query["safety_counts"] = [
            {
                **_zero_safety_counts(),
                "protected_check_candidate_count": 1,
            }
        ]
        connection = _FakeWriteConnection(rows_by_query)

        with self.assertRaisesRegex(RuntimeError, "safety assertions failed"):
            execute_asset_check_event_retention_sample_delete(
                connection,
                sample_asset="silver_adj_factor",
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
        "keep_windows": [
            {
                "keep_partition_set_name": "cn_a_index_trade_days",
                "keep_start_partition": "2026-05-26",
                "keep_end_partition": "2026-06-23",
                "keep_partition_count": 2,
            }
        ],
        "candidate_event_count_by_asset": [],
        "candidate_event_count_by_check": [],
        "latest_state_summary_by_asset": [],
        "protected_check_event_counts": [],
        "candidate_check_samples": [],
        "candidate_materialization_samples": [],
        "safety_counts": [_zero_safety_counts()],
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


def _sample_delete_rows_by_query() -> dict[str, list[dict[str, object]]]:
    sample_asset_key = '["silver_adj_factor"]'
    return {
        "running_or_queued_run_count": [{"running_or_queued_run_count": 0}],
        "keep_windows": [
            {
                "keep_partition_set_name": "cn_a_stock_current_trade_days",
                "keep_start_partition": "2026-06-23",
                "keep_end_partition": "2026-06-24",
                "keep_partition_count": 2,
            }
        ],
        "candidate_event_count_by_asset": [
            {
                "asset_key": sample_asset_key,
                "asset_family": "adj_factor",
                "check_candidate_count": 42150,
                "check_event_candidate_count": 42150,
                "check_event_tag_candidate_count": 0,
                "materialization_candidate_count": 4222,
                "materialization_event_tag_candidate_count": 7,
            }
        ],
        "latest_state_summary_by_asset": [
            {
                "asset_key": sample_asset_key,
                "asset_family": "adj_factor",
                "keep_partition_set_name": "cn_a_stock_current_trade_days",
                "latest_materialization_id": 6626719,
                "latest_partition": "2026-06-24",
                "latest_run_id": "run-latest",
                "latest_timestamp": "2026-06-24T01:42:45",
                "latest_check_count": 4,
                "latest_succeeded_check_count": 4,
                "latest_non_succeeded_check_count": 0,
            }
        ],
        "safety_counts": [_zero_safety_counts()],
    }


class _FakeConnection:
    def __init__(self, rows_by_query: dict[str, list[dict[str, object]]]) -> None:
        self.rows_by_query = rows_by_query
        self.readonly = False

    def set_session(self, *, readonly: bool, autocommit: bool) -> None:
        del autocommit
        self.readonly = readonly

    def cursor(self, cursor_factory=None):
        del cursor_factory
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

    def cursor(self, cursor_factory=None):
        del cursor_factory
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
        self.rows: list[dict[str, object]] = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        del exc_type, exc, tb
        return False

    def execute(self, sql: str, params=None) -> None:
        del params
        self.rows = list(self.rows_by_query[_query_name(sql)])

    def fetchall(self) -> list[dict[str, object]]:
        return self.rows


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

    def execute(self, sql: str, params=None) -> None:
        query_name = _query_name(sql)
        if query_name.startswith("delete_"):
            self.executed_delete_queries.append(query_name)
            self.rowcount = self.delete_rowcounts.get(query_name, 0)
            self.rows = []
            return
        super().execute(sql, params)
        self.rowcount = len(self.rows)


def _query_name(sql: str) -> str:
    for line in sql.splitlines():
        line = line.strip()
        if line.startswith("-- query:"):
            return line.split(":", 1)[1].strip()
    raise AssertionError(f"Missing query name in SQL: {sql}")


if __name__ == "__main__":
    unittest.main()
