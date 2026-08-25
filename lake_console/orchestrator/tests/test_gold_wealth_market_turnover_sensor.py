import json
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

import dagster as dg

from orchestrator.defs.asset_guards.stk_mins_lake_readiness import (
    StkMinsBatchReadiness,
    StkMinsDateReadiness,
)
from orchestrator.defs.asset_guards.wealth_market_turnover_lake_readiness import (
    WealthMarketTurnoverBatchReadiness,
    WealthMarketTurnoverDateReadiness,
)
from orchestrator.defs.partitions import (
    cn_a_stock_mins_silver_trade_days,
    cn_a_stock_trade_days,
)
from orchestrator.defs.sensors.gold_wealth_market_turnover_sensor import (
    GOLD_WEALTH_MARKET_TURNOVER_RUN_START,
    GOLD_WEALTH_MARKET_TURNOVER_SENSOR_JOB_NAME,
    _cursor_payload,
    _run_key_for_trade_date,
    _run_request_for_trade_date,
    build_gold_wealth_market_turnover_update_decision,
    gold_wealth_market_turnover_update_job_sensor,
)
from orchestrator.defs.sensors.readiness import AssetReadinessStatus

PARTITION_KEY = "2026-06-22"
NEXT_PARTITION_KEY = "2026-06-23"
AFTER_WINDOW = datetime(2026, 6, 23, 20, 5, tzinfo=ZoneInfo("Asia/Shanghai"))
BEFORE_WINDOW = datetime(2026, 6, 23, 19, 45, tzinfo=ZoneInfo("Asia/Shanghai"))


def _datetime_with_now(value: datetime):
    class _FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return value.replace(tzinfo=None)
            return value.astimezone(tz)

    return _FrozenDateTime


def _silver_status(
    trade_date: str,
    *,
    ready: bool,
    materialized: bool = True,
    checks_passed: bool | None = None,
    reason: str | None = None,
) -> StkMinsDateReadiness:
    checks_passed = ready if checks_passed is None else checks_passed
    return StkMinsDateReadiness(
        trade_date=trade_date,
        ready=ready,
        materialized=materialized,
        checks_passed=checks_passed,
        reason=reason or ("ready" if ready else "missing_silver_stk_mins_file"),
        failed_check_names=() if checks_passed else ("silver_stk_mins_integrity",),
        missing_file_paths=() if materialized else ("/lake/silver/stk_mins/missing",),
        expected_file_count=5,
        existing_file_count=5 if materialized else 0,
        checked_row_count=500 if materialized else 0,
        failed_row_count=0 if checks_passed else 1,
    )


def _silver_batch_status(
    trade_dates: tuple[str, ...],
    *,
    ready_dates: tuple[str, ...],
    failed_dates: tuple[str, ...] = (),
) -> StkMinsBatchReadiness:
    ready_set = set(ready_dates)
    failed_set = set(failed_dates)
    statuses = {}
    for trade_date in trade_dates:
        if trade_date in ready_set:
            statuses[trade_date] = _silver_status(trade_date, ready=True)
        elif trade_date in failed_set:
            statuses[trade_date] = _silver_status(
                trade_date,
                ready=False,
                materialized=True,
                checks_passed=False,
                reason="silver_check_failed",
            )
        else:
            statuses[trade_date] = _silver_status(
                trade_date,
                ready=False,
                materialized=False,
            )
    return StkMinsBatchReadiness(
        dataset="silver_stk_mins",
        expected_start_date=trade_dates[0] if trade_dates else None,
        expected_end_date=trade_dates[-1] if trade_dates else None,
        expected_count=len(trade_dates),
        freq_count=5,
        elapsed_ms=1,
        statuses_by_trade_date=statuses,
    )


def _gold_status(
    trade_date: str,
    *,
    ready: bool,
    materialized: bool = True,
    checks_passed: bool | None = None,
    reason: str | None = None,
) -> WealthMarketTurnoverDateReadiness:
    checks_passed = ready if checks_passed is None else checks_passed
    return WealthMarketTurnoverDateReadiness(
        trade_date=trade_date,
        ready=ready,
        materialized=materialized,
        checks_passed=checks_passed,
        reason=reason or (
            "ready" if ready else "missing_gold_wealth_market_turnover_file"
        ),
        failed_check_names=() if checks_passed else ("gold_wealth_market_turnover_integrity_check",),
        missing_file_paths=() if materialized else ("/lake/gold/wealth/missing",),
        checked_row_count=5 if materialized else 0,
        failed_row_count=0 if checks_passed else 1,
    )


def _gold_batch_status(
    trade_dates: tuple[str, ...],
    *,
    ready_dates: tuple[str, ...],
    failed_dates: tuple[str, ...] = (),
) -> WealthMarketTurnoverBatchReadiness:
    ready_set = set(ready_dates)
    failed_set = set(failed_dates)
    statuses = {}
    for trade_date in trade_dates:
        if trade_date in ready_set:
            statuses[trade_date] = _gold_status(trade_date, ready=True)
        elif trade_date in failed_set:
            statuses[trade_date] = _gold_status(
                trade_date,
                ready=False,
                materialized=True,
                checks_passed=False,
                reason="gold_check_failed",
            )
        else:
            statuses[trade_date] = _gold_status(
                trade_date,
                ready=False,
                materialized=False,
            )
    return WealthMarketTurnoverBatchReadiness(
        dataset="gold_wealth_market_turnover",
        expected_start_date=trade_dates[0] if trade_dates else None,
        expected_end_date=trade_dates[-1] if trade_dates else None,
        expected_count=len(trade_dates),
        elapsed_ms=1,
        statuses_by_trade_date=statuses,
    )


def _stock_daily_status(trade_date: str, *, ready: bool) -> AssetReadinessStatus:
    return AssetReadinessStatus(
        asset_key="silver_stock_daily",
        partition_key=trade_date,
        ready=ready,
        materialized=ready,
        checks_passed=ready,
        freshness_passed=True,
        materialization_storage_id=1 if ready else None,
        materialization_date=trade_date if ready else None,
        missing_check_names=() if ready else ("silver_stock_daily_contract_check",),
        failed_check_names=(),
        reason="ready" if ready else "missing blocking checks",
    )


class _FakeLakeRoot:
    def root(self):
        return Path("/fake/lake")

    def ensure_available_for_run(self):
        return None


class _FakeConnection:
    def __enter__(self):
        return object()

    def __exit__(self, *_args):
        return None


class _FakeDuckDB:
    def connect(self):
        return _FakeConnection()


class _FakeInstance:
    def __init__(
        self,
        *,
        trade_days: tuple[str, ...],
        stock_daily_trade_days: tuple[str, ...] | None = None,
        prod_core_materialized_trade_dates: tuple[str, ...] = (),
        failed_run_keys: tuple[str, ...] = (),
    ):
        self.dynamic_partitions = {
            cn_a_stock_mins_silver_trade_days.name: set(trade_days),
            cn_a_stock_trade_days.name: set(stock_daily_trade_days or trade_days),
        }
        self.prod_core_materialized_trade_dates = set(prod_core_materialized_trade_dates)
        self.failed_run_keys = set(failed_run_keys)
        self.run_record_filters = []

    def get_dynamic_partitions(self, name):
        return self.dynamic_partitions[name]

    def fetch_materializations(self, records_filter, limit):
        asset_partitions = tuple(getattr(records_filter, "asset_partitions", ()) or ())
        materialized = any(
            partition in self.prod_core_materialized_trade_dates
            for partition in asset_partitions
        )
        return SimpleNamespace(records=[object()] if materialized else [])

    def get_run_records(self, *, filters, limit=None):
        self.run_record_filters.append((filters, limit))
        tags = getattr(filters, "tags", {}) or {}
        run_key = tags.get("dagster/run_key")
        if run_key in self.failed_run_keys:
            return [SimpleNamespace(dagster_run=SimpleNamespace(run_key=run_key))]
        return []


class _FakeContext:
    def __init__(
        self,
        *,
        trade_days: tuple[str, ...] = (PARTITION_KEY, NEXT_PARTITION_KEY),
        stock_daily_trade_days: tuple[str, ...] | None = None,
        prod_core_materialized_trade_dates: tuple[str, ...] = (),
        failed_run_keys: tuple[str, ...] = (),
    ):
        self.instance = _FakeInstance(
            trade_days=trade_days,
            stock_daily_trade_days=stock_daily_trade_days,
            prod_core_materialized_trade_dates=prod_core_materialized_trade_dates,
            failed_run_keys=failed_run_keys,
        )
        self.resources = SimpleNamespace(lake_root=_FakeLakeRoot(), duckdb=_FakeDuckDB())


class GoldWealthMarketTurnoverSensorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.stock_daily_readiness = patch(
            "orchestrator.defs.sensors.gold_wealth_market_turnover_sensor."
            "silver_stock_daily_ready_for_trade_date",
            side_effect=lambda _instance, trade_date: _stock_daily_status(
                trade_date,
                ready=True,
            ),
        )
        self.stock_daily_readiness.start()

    def tearDown(self) -> None:
        self.stock_daily_readiness.stop()

    def test_sensor_definition_targets_job_and_stays_stopped(self) -> None:
        self.assertEqual(
            gold_wealth_market_turnover_update_job_sensor.name,
            "gold_wealth_market_turnover_update_job_sensor",
        )
        self.assertEqual(
            gold_wealth_market_turnover_update_job_sensor.job_name,
            GOLD_WEALTH_MARKET_TURNOVER_SENSOR_JOB_NAME,
        )
        self.assertEqual(
            gold_wealth_market_turnover_update_job_sensor.default_status,
            dg.DefaultSensorStatus.STOPPED,
        )
        self.assertEqual(GOLD_WEALTH_MARKET_TURNOVER_RUN_START.isoformat(), "19:50:00")

    def test_decision_contracts(self) -> None:
        before_window = build_gold_wealth_market_turnover_update_decision(
            target_trade_date=PARTITION_KEY,
            run_window_started=False,
            silver_ready=True,
            gold_ready=False,
        )
        silver_blocked = build_gold_wealth_market_turnover_update_decision(
            target_trade_date=PARTITION_KEY,
            run_window_started=True,
            silver_ready=False,
        )
        ready = build_gold_wealth_market_turnover_update_decision(
            target_trade_date=PARTITION_KEY,
            run_window_started=True,
            silver_ready=True,
            gold_ready=True,
            prod_sync_ready=True,
        )
        request = build_gold_wealth_market_turnover_update_decision(
            target_trade_date=PARTITION_KEY,
            run_window_started=True,
            silver_ready=True,
            gold_ready=False,
        )

        self.assertIsNone(before_window.selected_trade_date)
        self.assertEqual(before_window.reason_code, "run_window_not_started")
        self.assertIsNone(silver_blocked.selected_trade_date)
        self.assertEqual(silver_blocked.blocked_component, "silver_stk_mins")
        self.assertIsNone(ready.selected_trade_date)
        self.assertEqual(ready.reason_code, "wealth_market_turnover_chain_ready")
        self.assertEqual(request.selected_trade_date, PARTITION_KEY)
        self.assertEqual(request.reason_code, "request_run")

    def test_stock_daily_decision_blocks_request(self) -> None:
        decision = build_gold_wealth_market_turnover_update_decision(
            target_trade_date=PARTITION_KEY,
            run_window_started=True,
            silver_ready=True,
            stock_daily_ready=False,
            gold_ready=False,
        )

        self.assertIsNone(decision.selected_trade_date)
        self.assertEqual(decision.reason_code, "stock_daily_not_ready")
        self.assertEqual(decision.blocked_component, "silver_stock_daily")

    def test_run_request_contract(self) -> None:
        request = _run_request_for_trade_date(PARTITION_KEY)

        self.assertEqual(request.partition_key, PARTITION_KEY)
        self.assertEqual(
            request.run_key,
            f"gold_wealth_market_turnover:{PARTITION_KEY}",
        )
        self.assertEqual(request.tags, {})
        self.assertEqual(request.run_config, {})

    def test_ready_skip_cursor_is_not_blocked(self) -> None:
        decision = build_gold_wealth_market_turnover_update_decision(
            target_trade_date=PARTITION_KEY,
            run_window_started=True,
            silver_ready=True,
            gold_ready=True,
            prod_sync_ready=True,
        )
        cursor = json.loads(
            _cursor_payload(
                decision=decision,
                evaluated_at=AFTER_WINDOW,
                registered_trade_day_count=2,
                silver_status=_silver_status(PARTITION_KEY, ready=True),
                gold_status=_gold_status(PARTITION_KEY, ready=True),
            )
        )

        self.assertEqual(cursor["decision"], "skip")
        self.assertEqual(cursor["blocked_count"], 0)
        self.assertEqual(cursor["details"]["job_name"], GOLD_WEALTH_MARKET_TURNOVER_SENSOR_JOB_NAME)

    def test_before_window_skips_before_loading_trade_dates(self) -> None:
        with (
            patch(
                "orchestrator.defs.sensors.gold_wealth_market_turnover_sensor.datetime",
                _datetime_with_now(BEFORE_WINDOW),
            ),
            patch(
                "orchestrator.defs.sensors.gold_wealth_market_turnover_sensor."
                "_load_stock_mins_silver_expected_trade_dates",
            ) as load_trade_dates,
        ):
            result = gold_wealth_market_turnover_update_job_sensor._raw_fn(
                _FakeContext()
            )

        self.assertEqual(result.run_requests, [])
        self.assertIn("19:50", result.skip_reason.skip_message)
        load_trade_dates.assert_not_called()
        cursor = json.loads(result.cursor)
        self.assertIn("日更窗口还没到", cursor["details"]["summary"])
        self.assertIn("延后 10 分钟", cursor["details"]["next_action"])

    def test_silver_not_ready_skips_without_gold_readiness_scan(self) -> None:
        trade_dates = (PARTITION_KEY, NEXT_PARTITION_KEY)
        with (
            patch(
                "orchestrator.defs.sensors.gold_wealth_market_turnover_sensor.datetime",
                _datetime_with_now(AFTER_WINDOW),
            ),
            patch(
                "orchestrator.defs.sensors.gold_wealth_market_turnover_sensor."
                "_load_stock_mins_silver_expected_trade_dates",
                return_value=trade_dates,
            ),
            patch(
                "orchestrator.defs.sensors.gold_wealth_market_turnover_sensor."
                "batch_silver_stk_mins_lake_readiness",
                return_value=_silver_batch_status(
                    trade_dates,
                    ready_dates=(PARTITION_KEY,),
                ),
            ),
            patch(
                "orchestrator.defs.sensors.gold_wealth_market_turnover_sensor."
                "batch_gold_wealth_market_turnover_lake_readiness",
            ) as gold_readiness,
        ):
            result = gold_wealth_market_turnover_update_job_sensor._raw_fn(
                _FakeContext()
            )

        self.assertEqual(result.run_requests, [])
        self.assertIn("股票分钟线 silver", result.skip_reason.skip_message)
        gold_readiness.assert_not_called()

    def test_gold_missing_submits_one_partition_run_after_silver_ready(self) -> None:
        trade_dates = (PARTITION_KEY, NEXT_PARTITION_KEY)
        with (
            patch(
                "orchestrator.defs.sensors.gold_wealth_market_turnover_sensor.datetime",
                _datetime_with_now(AFTER_WINDOW),
            ),
            patch(
                "orchestrator.defs.sensors.gold_wealth_market_turnover_sensor."
                "_load_stock_mins_silver_expected_trade_dates",
                return_value=trade_dates,
            ),
            patch(
                "orchestrator.defs.sensors.gold_wealth_market_turnover_sensor."
                "batch_silver_stk_mins_lake_readiness",
                return_value=_silver_batch_status(
                    trade_dates,
                    ready_dates=trade_dates,
                ),
            ),
            patch(
                "orchestrator.defs.sensors.gold_wealth_market_turnover_sensor."
                "batch_gold_wealth_market_turnover_lake_readiness",
                return_value=_gold_batch_status(
                    trade_dates,
                    ready_dates=(PARTITION_KEY,),
                ),
            ),
        ):
            result = gold_wealth_market_turnover_update_job_sensor._raw_fn(
                _FakeContext()
            )

        self.assertEqual(len(result.run_requests), 1)
        request = result.run_requests[0]
        self.assertEqual(request.partition_key, NEXT_PARTITION_KEY)
        self.assertEqual(
            request.run_key,
            f"gold_wealth_market_turnover:{NEXT_PARTITION_KEY}",
        )
        cursor = json.loads(result.cursor)
        self.assertEqual(cursor["decision"], "request_runs")
        self.assertEqual(cursor["selected_count"], 1)
        self.assertEqual(cursor["sample_keys"], [NEXT_PARTITION_KEY])
        self.assertIn(
            f"触发 {NEXT_PARTITION_KEY} 财富成交额",
            cursor["details"]["summary"],
        )
        self.assertIn("prod core", cursor["details"]["next_action"])

    def test_gold_missing_skips_when_stock_daily_partition_is_not_registered(self) -> None:
        trade_dates = (PARTITION_KEY, NEXT_PARTITION_KEY)
        with (
            patch(
                "orchestrator.defs.sensors.gold_wealth_market_turnover_sensor.datetime",
                _datetime_with_now(AFTER_WINDOW),
            ),
            patch(
                "orchestrator.defs.sensors.gold_wealth_market_turnover_sensor."
                "_load_stock_mins_silver_expected_trade_dates",
                return_value=trade_dates,
            ),
            patch(
                "orchestrator.defs.sensors.gold_wealth_market_turnover_sensor."
                "batch_silver_stk_mins_lake_readiness",
                return_value=_silver_batch_status(
                    trade_dates,
                    ready_dates=trade_dates,
                ),
            ),
            patch(
                "orchestrator.defs.sensors.gold_wealth_market_turnover_sensor."
                "batch_gold_wealth_market_turnover_lake_readiness",
                return_value=_gold_batch_status(
                    trade_dates,
                    ready_dates=(PARTITION_KEY,),
                ),
            ),
        ):
            result = gold_wealth_market_turnover_update_job_sensor._raw_fn(
                _FakeContext(stock_daily_trade_days=(PARTITION_KEY,))
            )

        self.assertEqual(result.run_requests, [])
        cursor = json.loads(result.cursor)
        self.assertEqual(
            cursor["details"]["reason_code"],
            "missing_stock_daily_registered_partition",
        )
        self.assertEqual(
            cursor["details"]["blocked_component"],
            "cn_a_stock_trade_days",
        )

    def test_gold_missing_skips_when_stock_daily_is_not_ready(self) -> None:
        trade_dates = (PARTITION_KEY, NEXT_PARTITION_KEY)
        with (
            patch(
                "orchestrator.defs.sensors.gold_wealth_market_turnover_sensor.datetime",
                _datetime_with_now(AFTER_WINDOW),
            ),
            patch(
                "orchestrator.defs.sensors.gold_wealth_market_turnover_sensor."
                "_load_stock_mins_silver_expected_trade_dates",
                return_value=trade_dates,
            ),
            patch(
                "orchestrator.defs.sensors.gold_wealth_market_turnover_sensor."
                "batch_silver_stk_mins_lake_readiness",
                return_value=_silver_batch_status(
                    trade_dates,
                    ready_dates=trade_dates,
                ),
            ),
            patch(
                "orchestrator.defs.sensors.gold_wealth_market_turnover_sensor."
                "batch_gold_wealth_market_turnover_lake_readiness",
                return_value=_gold_batch_status(
                    trade_dates,
                    ready_dates=(PARTITION_KEY,),
                ),
            ),
            patch(
                "orchestrator.defs.sensors.gold_wealth_market_turnover_sensor."
                "silver_stock_daily_ready_for_trade_date",
                return_value=_stock_daily_status(NEXT_PARTITION_KEY, ready=False),
            ) as stock_daily_readiness,
        ):
            result = gold_wealth_market_turnover_update_job_sensor._raw_fn(
                _FakeContext()
            )

        self.assertEqual(result.run_requests, [])
        stock_daily_readiness.assert_called_once()
        cursor = json.loads(result.cursor)
        self.assertEqual(cursor["details"]["reason_code"], "stock_daily_not_ready")
        self.assertEqual(
            cursor["details"]["blocked_component"],
            "silver_stock_daily",
        )

    def test_gold_ready_prod_missing_submits_same_job(self) -> None:
        trade_dates = (PARTITION_KEY, NEXT_PARTITION_KEY)
        with (
            patch(
                "orchestrator.defs.sensors.gold_wealth_market_turnover_sensor.datetime",
                _datetime_with_now(AFTER_WINDOW),
            ),
            patch(
                "orchestrator.defs.sensors.gold_wealth_market_turnover_sensor."
                "_load_stock_mins_silver_expected_trade_dates",
                return_value=trade_dates,
            ),
            patch(
                "orchestrator.defs.sensors.gold_wealth_market_turnover_sensor."
                "batch_silver_stk_mins_lake_readiness",
                return_value=_silver_batch_status(
                    trade_dates,
                    ready_dates=trade_dates,
                ),
            ),
            patch(
                "orchestrator.defs.sensors.gold_wealth_market_turnover_sensor."
                "batch_gold_wealth_market_turnover_lake_readiness",
                return_value=_gold_batch_status(
                    trade_dates,
                    ready_dates=trade_dates,
                ),
            ),
        ):
            result = gold_wealth_market_turnover_update_job_sensor._raw_fn(
                _FakeContext(
                    prod_core_materialized_trade_dates=(PARTITION_KEY,),
                )
            )

        self.assertEqual(len(result.run_requests), 1)
        request = result.run_requests[0]
        self.assertEqual(request.partition_key, NEXT_PARTITION_KEY)
        self.assertEqual(
            request.run_key,
            f"gold_wealth_market_turnover:{NEXT_PARTITION_KEY}",
        )
        cursor = json.loads(result.cursor)
        self.assertEqual(cursor["decision"], "request_runs")
        self.assertEqual(cursor["details"]["reason_code"], "prod_sync_missing")
        self.assertEqual(cursor["details"]["blocked_component"], "prod_core_db")
        self.assertEqual(
            cursor["details"]["gate_statuses"]["prod_core_wealth_market_turnover"][
                "materialized"
            ],
            False,
        )

    def test_gold_ready_prod_failed_does_not_auto_retry(self) -> None:
        trade_dates = (PARTITION_KEY, NEXT_PARTITION_KEY)
        with (
            patch(
                "orchestrator.defs.sensors.gold_wealth_market_turnover_sensor.datetime",
                _datetime_with_now(AFTER_WINDOW),
            ),
            patch(
                "orchestrator.defs.sensors.gold_wealth_market_turnover_sensor."
                "_load_stock_mins_silver_expected_trade_dates",
                return_value=trade_dates,
            ),
            patch(
                "orchestrator.defs.sensors.gold_wealth_market_turnover_sensor."
                "batch_silver_stk_mins_lake_readiness",
                return_value=_silver_batch_status(
                    trade_dates,
                    ready_dates=trade_dates,
                ),
            ),
            patch(
                "orchestrator.defs.sensors.gold_wealth_market_turnover_sensor."
                "batch_gold_wealth_market_turnover_lake_readiness",
                return_value=_gold_batch_status(
                    trade_dates,
                    ready_dates=trade_dates,
                ),
            ),
        ):
            result = gold_wealth_market_turnover_update_job_sensor._raw_fn(
                _FakeContext(
                    prod_core_materialized_trade_dates=(PARTITION_KEY,),
                    failed_run_keys=(_run_key_for_trade_date(NEXT_PARTITION_KEY),),
                )
            )

        self.assertEqual(result.run_requests, [])
        self.assertIn("prod core serving", result.skip_reason.skip_message)
        cursor = json.loads(result.cursor)
        self.assertEqual(cursor["decision"], "skip")
        self.assertEqual(
            cursor["details"]["reason_code"],
            "prod_sync_failed_requires_manual_retry",
        )
        self.assertEqual(cursor["details"]["blocked_component"], "prod_core_db")
        self.assertTrue(
            cursor["details"]["gate_statuses"]["prod_core_wealth_market_turnover"][
                "failed"
            ]
        )

    def test_gold_and_prod_ready_skips_chain_ready(self) -> None:
        trade_dates = (PARTITION_KEY, NEXT_PARTITION_KEY)
        with (
            patch(
                "orchestrator.defs.sensors.gold_wealth_market_turnover_sensor.datetime",
                _datetime_with_now(AFTER_WINDOW),
            ),
            patch(
                "orchestrator.defs.sensors.gold_wealth_market_turnover_sensor."
                "_load_stock_mins_silver_expected_trade_dates",
                return_value=trade_dates,
            ),
            patch(
                "orchestrator.defs.sensors.gold_wealth_market_turnover_sensor."
                "batch_silver_stk_mins_lake_readiness",
                return_value=_silver_batch_status(
                    trade_dates,
                    ready_dates=trade_dates,
                ),
            ),
            patch(
                "orchestrator.defs.sensors.gold_wealth_market_turnover_sensor."
                "batch_gold_wealth_market_turnover_lake_readiness",
                return_value=_gold_batch_status(
                    trade_dates,
                    ready_dates=trade_dates,
                ),
            ),
        ):
            result = gold_wealth_market_turnover_update_job_sensor._raw_fn(
                _FakeContext(
                    prod_core_materialized_trade_dates=trade_dates,
                )
            )

        self.assertEqual(result.run_requests, [])
        cursor = json.loads(result.cursor)
        self.assertEqual(cursor["blocked_count"], 0)
        self.assertEqual(
            cursor["details"]["reason_code"],
            "wealth_market_turnover_chain_ready",
        )


if __name__ == "__main__":
    unittest.main()
