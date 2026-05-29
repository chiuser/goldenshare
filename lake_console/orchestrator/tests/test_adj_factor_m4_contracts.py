import json
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from orchestrator.defs.checks import adj_factor_checks
from orchestrator.defs.jobs.stock_adj_factor_update import stock_adj_factor_update_job
from orchestrator.defs.sensors import readiness
from orchestrator.defs.sensors.stock_adj_factor_sensor import (
    _cursor_payload as build_adj_factor_sensor_cursor,
)
from orchestrator.defs.sensors.stock_adj_factor_sensor import (
    _has_materialized_check_problem,
    _latest_registered_trade_date,
    _run_request_for_trade_date,
)
from orchestrator.defs.sensors.stock_current_trade_day_sensor import (
    _cursor_payload as build_current_trade_day_cursor,
)
from orchestrator.defs.sensors.stock_current_trade_day_sensor import (
    build_stock_current_trade_day_registration_decision,
)


EVALUATED_AT = datetime(2026, 5, 29, 9, 30, tzinfo=ZoneInfo("Asia/Shanghai"))


class _AssetStatus:
    def __init__(self, *, materialized: bool, checks_passed: bool) -> None:
        self.materialized = materialized
        self.checks_passed = checks_passed


class _DatasetStatus:
    def __init__(self, statuses) -> None:
        self.statuses = tuple(statuses)


def _check_names(check_definitions) -> tuple[str, ...]:
    names = []
    for check_definition in check_definitions:
        check_key = next(iter(check_definition.check_keys))
        names.append(check_key.name)
    return tuple(sorted(names))


class AdjFactorM4ContractTests(unittest.TestCase):
    def test_stock_adj_factor_update_job_selection_is_adj_factor_only(self) -> None:
        selection_text = repr(stock_adj_factor_update_job.selection)

        self.assertIn("raw_tushare_adj_factor", selection_text)
        self.assertIn("silver_adj_factor", selection_text)
        self.assertNotIn("raw_tushare_stock_basic", selection_text)
        self.assertNotIn("silver_stock_basic", selection_text)

    def test_readiness_check_names_match_adj_factor_check_definitions(self) -> None:
        raw_check_definitions = (
            adj_factor_checks.raw_adj_factor_file_exists,
            adj_factor_checks.raw_adj_factor_row_count_positive,
            adj_factor_checks.raw_adj_factor_schema_matches_tushare_contract,
            adj_factor_checks.raw_adj_factor_required_columns,
            adj_factor_checks.raw_adj_factor_partition_date_matches,
            adj_factor_checks.raw_adj_factor_unique_ts_code_trade_date,
            adj_factor_checks.raw_adj_factor_positive_factor,
            adj_factor_checks.raw_adj_factor_stock_current_partition_key_allowed,
        )
        silver_check_definitions = (
            adj_factor_checks.silver_adj_factor_file_exists,
            adj_factor_checks.silver_adj_factor_row_count_positive,
            adj_factor_checks.silver_adj_factor_schema_matches_contract,
            adj_factor_checks.silver_adj_factor_required_columns,
            adj_factor_checks.silver_adj_factor_partition_date_matches,
            adj_factor_checks.silver_adj_factor_unique_ts_code_trade_date,
            adj_factor_checks.silver_adj_factor_positive_factor,
            adj_factor_checks.silver_adj_factor_listed_stock_only,
            adj_factor_checks.silver_adj_factor_coverage_complete,
            adj_factor_checks.silver_adj_factor_stock_current_partition_key_allowed,
        )

        self.assertEqual(
            tuple(sorted(readiness.RAW_ADJ_FACTOR_CHECKS)),
            _check_names(raw_check_definitions),
        )
        self.assertEqual(
            tuple(sorted(readiness.SILVER_ADJ_FACTOR_BLOCKING_CHECKS)),
            _check_names(silver_check_definitions),
        )

    def test_current_trade_day_decision_registers_only_open_day_after_six(self) -> None:
        self.assertEqual(
            build_stock_current_trade_day_registration_decision(
                today="2026-05-29",
                today_is_open=True,
                register_window_started=True,
                already_registered=False,
            ).selected_keys,
            ("2026-05-29",),
        )
        self.assertEqual(
            build_stock_current_trade_day_registration_decision(
                today="2026-05-29",
                today_is_open=True,
                register_window_started=False,
                already_registered=False,
            ).selected_keys,
            (),
        )
        self.assertEqual(
            build_stock_current_trade_day_registration_decision(
                today="2026-05-29",
                today_is_open=False,
                register_window_started=True,
                already_registered=False,
            ).selected_keys,
            (),
        )
        self.assertEqual(
            build_stock_current_trade_day_registration_decision(
                today="2026-05-29",
                today_is_open=True,
                register_window_started=True,
                already_registered=True,
            ).selected_keys,
            (),
        )

    def test_current_trade_day_cursor_uses_standard_contract(self) -> None:
        decision = build_stock_current_trade_day_registration_decision(
            today="2026-05-29",
            today_is_open=True,
            register_window_started=True,
            already_registered=False,
        )
        payload = json.loads(
            build_current_trade_day_cursor(
                decision=decision,
                evaluated_at=EVALUATED_AT,
            )
        )

        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(payload["decision"], "register_partitions")
        self.assertEqual(payload["target_date"], "2026-05-29")
        self.assertEqual(payload["selected_count"], 1)
        self.assertEqual(payload["sample_keys"], ["2026-05-29"])
        self.assertEqual(
            payload["details"]["partition_set"],
            "cn_a_stock_current_trade_days",
        )

    def test_latest_registered_trade_date_uses_latest_not_after_today(self) -> None:
        self.assertEqual(
            _latest_registered_trade_date(
                ("2026-05-28", "2026-05-29", "2026-05-30"),
                EVALUATED_AT,
            ),
            "2026-05-29",
        )
        self.assertIsNone(_latest_registered_trade_date(("2026-05-30",), EVALUATED_AT))

    def test_adj_factor_sensor_cursor_and_run_request_contract(self) -> None:
        payload = json.loads(
            build_adj_factor_sensor_cursor(
                evaluated_at=EVALUATED_AT,
                registered_trade_day_count=1,
                target_trade_date="2026-05-29",
                selected_trade_date="2026-05-29",
                reason="ready",
                source_window_started=True,
            )
        )

        self.assertEqual(payload["decision"], "request_runs")
        self.assertEqual(payload["target_date"], "2026-05-29")
        self.assertEqual(payload["selected_count"], 1)
        self.assertEqual(payload["sample_keys"], ["2026-05-29"])
        self.assertFalse(payload["details"]["stock_basic_freshness_required"])

        request = _run_request_for_trade_date("2026-05-29")
        self.assertEqual(request.partition_key, "2026-05-29")
        self.assertEqual(request.run_key, "stock_adj_factor_update:2026-05-29")
        self.assertEqual(request.tags, {})
        self.assertEqual(request.run_config, {})

    def test_adj_factor_sensor_detects_materialized_check_problem(self) -> None:
        self.assertTrue(
            _has_materialized_check_problem(
                _DatasetStatus([_AssetStatus(materialized=True, checks_passed=False)])
            )
        )
        self.assertFalse(
            _has_materialized_check_problem(
                _DatasetStatus([_AssetStatus(materialized=False, checks_passed=False)])
            )
        )
        self.assertFalse(
            _has_materialized_check_problem(
                _DatasetStatus([_AssetStatus(materialized=True, checks_passed=True)])
            )
        )


if __name__ == "__main__":
    unittest.main()
