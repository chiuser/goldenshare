from __future__ import annotations

import inspect
import unittest

from orchestrator.defs.bootstrap import asset_check_event_retention as retention
from orchestrator.defs.bootstrap import asset_check_event_retention_cli
from orchestrator.defs.bootstrap.asset_check_event_retention import (
    ASSET_CHECK_RETENTION_ASSET_KEYS,
    ASSET_CHECK_RETENTION_EXCLUDED_ASSETS,
    ASSET_CHECK_RETENTION_KEEP_PARTITION_SET_BY_KEY,
    ASSET_CHECK_RETENTION_PROTECTED_CHECK_NAMES,
    asset_check_event_retention_sql_statements,
    collect_asset_check_event_retention_dry_run,
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


def _query_name(sql: str) -> str:
    for line in sql.splitlines():
        line = line.strip()
        if line.startswith("-- query:"):
            return line.split(":", 1)[1].strip()
    raise AssertionError(f"Missing query name in SQL: {sql}")


if __name__ == "__main__":
    unittest.main()
