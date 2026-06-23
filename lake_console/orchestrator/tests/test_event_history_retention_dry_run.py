from __future__ import annotations

import inspect
import unittest

from orchestrator.defs.bootstrap import event_history_retention_dry_run as dry_run
from orchestrator.defs.bootstrap.event_history_retention_dry_run import (
    collect_event_history_retention_dry_run,
    collect_event_history_retention_sample_dry_run,
    dry_run_sql_statements,
    sample_dry_run_sql_statements,
)
from orchestrator.defs.bootstrap import event_history_retention_dry_run_cli


class EventHistoryRetentionDryRunTests(unittest.TestCase):
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
        for sql in dry_run_sql_statements() + sample_dry_run_sql_statements():
            normalized = f" {' '.join(sql.lower().split())} "
            self.assertTrue(
                normalized.strip().startswith(("-- query:", "with", "select")),
                msg=sql,
            )
            for token in forbidden:
                self.assertNotIn(token, normalized, msg=sql)

    def test_module_and_cli_do_not_expose_write_or_delete_paths(self) -> None:
        module_source = inspect.getsource(dry_run)
        cli_source = inspect.getsource(event_history_retention_dry_run_cli)
        combined = f"{module_source}\n{cli_source}".lower()
        for token in (
            "delete from",
            "insert into",
            "report_runless_asset_event",
            "dagsterinstance.get",
        ):
            self.assertNotIn(token, combined)
        self.assertNotIn("--apply", combined)

    def test_collect_report_and_safety_assertions(self) -> None:
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
                "old_check_candidates_by_asset": [
                    {
                        "asset_key": '["asset_a"]',
                        "old_check_count": 3,
                        "old_check_event_log_count": 3,
                        "old_check_event_tag_count": 0,
                    }
                ],
                "old_materialization_candidates_by_asset": [
                    {
                        "asset_key": '["asset_a"]',
                        "old_materialization_count": 1,
                        "old_materialization_event_tag_count": 1,
                    }
                ],
                "no_target_check_counts_by_asset": [
                    {"asset_key": '["asset_b"]', "no_target_check_count": 2}
                ],
                "retired_check_name_candidates": [
                    {
                        "check_name": "silver_stock_daily_current_listed_only",
                        "asset_key": '["silver_stock_daily"]',
                        "check_event_count": 5,
                    }
                ],
                "protected_check_event_counts": [
                    {
                        "check_name": "gold_stk_mins_qfq_factor_repair_plan_evaluated",
                        "asset_key": '["gold_stk_mins_qfq_1m"]',
                        "check_event_count": 1,
                    }
                ],
                "old_check_samples": [
                    {
                        "asset_key": '["asset_a"]',
                        "check_name": "asset_a_contract_check",
                        "partition": "2026-06-18",
                        "run_id": "run-1",
                        "execution_status": "SUCCEEDED",
                        "evaluation_event_storage_id": 11,
                        "materialization_event_storage_id": 10,
                    }
                ],
                "old_materialization_samples": [
                    {
                        "asset_key": '["asset_a"]',
                        "partition": "2026-06-18",
                        "run_id": "run-1",
                        "event_storage_id": 10,
                    }
                ],
                "old_check_latest_state_collision_count": [
                    {"collision_count": 0}
                ],
                "old_materialization_latest_state_collision_count": [
                    {"collision_count": 0}
                ],
                "protected_check_candidate_count": [
                    {"protected_check_candidate_count": 0}
                ],
                "no_target_check_selected_count": [
                    {"no_target_selected_count": 0}
                ],
            }
        )

        report = collect_event_history_retention_dry_run(connection)

        self.assertFalse(report.should_stop)
        self.assertTrue(connection.readonly)
        self.assertEqual(report.old_check_candidates_by_asset[0]["old_check_count"], 3)
        self.assertEqual(
            report.retired_check_name_candidates[0]["check_name"],
            "silver_stock_daily_current_listed_only",
        )
        self.assertTrue(
            all(assertion["passed"] for assertion in report.safety_assertions)
        )

    def test_running_run_marks_report_as_stop(self) -> None:
        rows_by_query = _minimal_rows_by_query()
        rows_by_query["running_or_queued_run_count"] = [
            {"running_or_queued_run_count": 1}
        ]
        rows_by_query["run_status_counts"] = [
            {"status": "STARTED", "run_count": 1}
        ]

        report = collect_event_history_retention_dry_run(
            _FakeConnection(rows_by_query)
        )

        self.assertTrue(report.should_stop)
        self.assertEqual(
            report.safety_assertions[0]["name"],
            "no_running_or_queued_runs",
        )
        self.assertFalse(report.safety_assertions[0]["passed"])

    def test_collect_sample_report_and_safety_assertions(self) -> None:
        connection = _FakeConnection(
            {
                "running_or_queued_run_count": [
                    {"running_or_queued_run_count": 0}
                ],
                "sample_candidate_counts_by_asset": [
                    {
                        "asset_key": '["asset_a"]',
                        "old_check_count": 3,
                        "old_check_event_log_count": 3,
                        "old_check_event_tag_count": 1,
                        "old_materialization_count": 1,
                        "old_materialization_event_tag_count": 1,
                    },
                    {
                        "asset_key": '["asset_b"]',
                        "old_check_count": 0,
                        "old_check_event_log_count": 0,
                        "old_check_event_tag_count": 0,
                        "old_materialization_count": 0,
                        "old_materialization_event_tag_count": 0,
                    },
                ],
                "sample_latest_materialization_samples": [
                    {
                        "asset_key": '["asset_a"]',
                        "partition": "2026-06-18",
                        "latest_materialization_id": 100,
                        "run_id": "run-latest",
                    }
                ],
                "sample_latest_check_samples": [
                    {
                        "asset_key": '["asset_a"]',
                        "check_name": "asset_a_contract_check",
                        "partition": "2026-06-18",
                        "execution_status": "SUCCEEDED",
                        "evaluation_event_storage_id": 101,
                        "materialization_event_storage_id": 100,
                    }
                ],
                "sample_latest_state_summary_by_asset": [
                    {
                        "asset_key": '["asset_a"]',
                        "latest_materialization_count": 10,
                        "latest_check_count": 10,
                        "latest_succeeded_check_count": 10,
                        "latest_non_succeeded_check_count": 0,
                    }
                ],
                "sample_no_target_check_counts_by_asset": [],
                "sample_protected_check_event_counts": [],
                "sample_old_check_latest_state_collision_count": [
                    {"collision_count": 0}
                ],
                "sample_old_materialization_latest_state_collision_count": [
                    {"collision_count": 0}
                ],
                "sample_protected_check_candidate_count": [
                    {"protected_check_candidate_count": 0}
                ],
                "sample_no_target_check_selected_count": [
                    {"no_target_selected_count": 0}
                ],
                "sample_scoped_candidate_count": [
                    {"scoped_candidate_count": 3}
                ],
                "sample_unscoped_candidate_count": [
                    {"unscoped_candidate_count": 3}
                ],
                "sample_assets_with_latest_materialization_count": [
                    {"assets_with_latest_materialization_count": 2}
                ],
                "sample_assets_with_latest_check_count": [
                    {"assets_with_latest_check_count": 2}
                ],
                "sample_latest_materialization_without_check_count": [
                    {"latest_materialization_without_check_count": 0}
                ],
            }
        )

        report = collect_event_history_retention_sample_dry_run(
            connection,
            asset_keys=("asset_a", '["asset_b"]'),
        )

        self.assertFalse(report.should_stop)
        self.assertTrue(connection.readonly)
        self.assertEqual(report.asset_keys, ('["asset_a"]', '["asset_b"]'))
        self.assertEqual(report.candidate_counts_by_asset[0]["old_check_count"], 3)
        self.assertEqual(
            report.latest_materialization_samples[0]["latest_materialization_id"],
            100,
        )
        self.assertTrue(
            all(assertion["passed"] for assertion in report.safety_assertions)
        )

    def test_sample_report_stops_without_latest_check_state(self) -> None:
        rows_by_query = _minimal_sample_rows_by_query()
        rows_by_query["sample_assets_with_latest_check_count"] = [
            {"assets_with_latest_check_count": 1}
        ]

        report = collect_event_history_retention_sample_dry_run(
            _FakeConnection(rows_by_query),
            asset_keys=("asset_a", "asset_b"),
        )

        self.assertTrue(report.should_stop)
        assertion_by_name = {
            assertion["name"]: assertion for assertion in report.safety_assertions
        }
        self.assertFalse(
            assertion_by_name["sample_assets_have_latest_check_state"]["passed"]
        )

    def test_sample_report_stops_when_latest_materialization_lacks_check(self) -> None:
        rows_by_query = _minimal_sample_rows_by_query()
        rows_by_query["sample_latest_materialization_without_check_count"] = [
            {"latest_materialization_without_check_count": 1}
        ]

        report = collect_event_history_retention_sample_dry_run(
            _FakeConnection(rows_by_query),
            asset_keys=("asset_a", "asset_b"),
        )

        assertion_by_name = {
            assertion["name"]: assertion for assertion in report.safety_assertions
        }
        self.assertTrue(report.should_stop)
        self.assertFalse(
            assertion_by_name[
                "sample_latest_materializations_all_have_latest_check_state"
            ]["passed"]
        )

    def test_sample_dry_run_cli_sample_asset_overrides_default_assets(self) -> None:
        selected = event_history_retention_dry_run_cli._selected_sample_assets(
            [
                "ch_share_fact_market_breadth_daily",
                "gold_stock_return_distribution",
            ]
        )

        self.assertEqual(
            selected,
            (
                "ch_share_fact_market_breadth_daily",
                "gold_stock_return_distribution",
            ),
        )
        self.assertNotIn("prod_ch_share_fact_market_breadth_daily", selected)

    def test_sample_dry_run_cli_uses_default_assets_when_unspecified(self) -> None:
        selected = event_history_retention_dry_run_cli._selected_sample_assets(None)

        self.assertIn("prod_ch_share_fact_market_breadth_daily", selected)


def _minimal_rows_by_query() -> dict[str, list[dict[str, object]]]:
    return {
        "table_counts": [],
        "table_sizes": [],
        "run_status_counts": [],
        "running_or_queued_run_count": [{"running_or_queued_run_count": 0}],
        "old_check_candidates_by_asset": [],
        "old_materialization_candidates_by_asset": [],
        "no_target_check_counts_by_asset": [],
        "retired_check_name_candidates": [],
        "protected_check_event_counts": [],
        "old_check_samples": [],
        "old_materialization_samples": [],
        "old_check_latest_state_collision_count": [{"collision_count": 0}],
        "old_materialization_latest_state_collision_count": [{"collision_count": 0}],
        "protected_check_candidate_count": [{"protected_check_candidate_count": 0}],
        "no_target_check_selected_count": [{"no_target_selected_count": 0}],
    }


def _minimal_sample_rows_by_query() -> dict[str, list[dict[str, object]]]:
    return {
        "running_or_queued_run_count": [{"running_or_queued_run_count": 0}],
        "sample_candidate_counts_by_asset": [],
        "sample_latest_materialization_samples": [],
        "sample_latest_check_samples": [],
        "sample_latest_state_summary_by_asset": [],
        "sample_no_target_check_counts_by_asset": [],
        "sample_protected_check_event_counts": [],
        "sample_old_check_latest_state_collision_count": [{"collision_count": 0}],
        "sample_old_materialization_latest_state_collision_count": [
            {"collision_count": 0}
        ],
        "sample_protected_check_candidate_count": [
            {"protected_check_candidate_count": 0}
        ],
        "sample_no_target_check_selected_count": [
            {"no_target_selected_count": 0}
        ],
        "sample_scoped_candidate_count": [{"scoped_candidate_count": 0}],
        "sample_unscoped_candidate_count": [{"unscoped_candidate_count": 0}],
        "sample_assets_with_latest_materialization_count": [
            {"assets_with_latest_materialization_count": 2}
        ],
        "sample_assets_with_latest_check_count": [
            {"assets_with_latest_check_count": 2}
        ],
        "sample_latest_materialization_without_check_count": [
            {"latest_materialization_without_check_count": 0}
        ],
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


def _query_name(sql: str) -> str:
    for line in sql.splitlines():
        stripped = line.strip()
        if stripped.startswith("-- query:"):
            return stripped.removeprefix("-- query:").strip()
    raise AssertionError(f"SQL missing query name: {sql}")
