from __future__ import annotations

import json
import unittest
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

from orchestrator.defs.asset_guards.bounded_continuity import (
    ContinuityBatchReadiness,
    ContinuityDateReadiness,
    ContinuityExpectedDateWindow,
)
from orchestrator.defs.partitions import cn_a_stock_trade_days
from orchestrator.defs.sensors.clickhouse_market_breadth_continuity_sensor import (
    clickhouse_market_breadth_continuity_sensor,
    prod_clickhouse_market_breadth_continuity_sensor,
)
from orchestrator.defs.sensors.market_breadth_continuity_sensor import (
    market_breadth_continuity_sensor,
)
from orchestrator.defs.sensors.readiness import DatasetReadinessStatus
from orchestrator.defs.sensors.stock_return_distribution_continuity_sensor import (
    stock_return_distribution_continuity_sensor,
)


CN_TZ = ZoneInfo("Asia/Shanghai")


class _FakeDuckDB:
    @contextmanager
    def connect(self):
        yield object()


class _FakeConnectionResource:
    def __init__(self) -> None:
        self.connection_count = 0

    @contextmanager
    def get_connection(self):
        self.connection_count += 1
        yield object()


class _FakeLakeRoot:
    def root(self):
        return Path("/fake/lake")


class _FakeInstance:
    def __init__(self, trade_days: tuple[str, ...]) -> None:
        self._trade_days = list(trade_days)

    def get_dynamic_partitions(self, name: str) -> list[str]:
        if name == cn_a_stock_trade_days.name:
            return list(self._trade_days)
        raise KeyError(name)


class _FakeContext:
    def __init__(self, trade_days: tuple[str, ...]) -> None:
        self.instance = _FakeInstance(trade_days)
        self.resources = SimpleNamespace(
            lake_root=_FakeLakeRoot(),
            duckdb=_FakeDuckDB(),
            clickhouse=_FakeConnectionResource(),
            prod_clickhouse=_FakeConnectionResource(),
        )
        self.cursor = None


def _expected_window(
    expected_trade_dates: tuple[str, ...],
) -> ContinuityExpectedDateWindow:
    return ContinuityExpectedDateWindow(
        expected_trade_dates=expected_trade_dates,
        min_trade_date="2014-01-01",
        max_trade_date=expected_trade_dates[-1] if expected_trade_dates else None,
        evaluated_at=datetime(2026, 6, 17, 16, 30, tzinfo=CN_TZ),
        window_limit=10,
    )


def _date_status(
    trade_date: str,
    *,
    ready: bool,
    materialized: bool,
    reason: str,
    failed_check_names: tuple[str, ...] = (),
) -> ContinuityDateReadiness:
    return ContinuityDateReadiness(
        trade_date=trade_date,
        ready=ready,
        materialized=materialized,
        checks_passed=ready,
        reason=reason,
        failed_check_names=failed_check_names,
    )


def _batch_status(
    statuses: tuple[ContinuityDateReadiness, ...],
) -> ContinuityBatchReadiness:
    return ContinuityBatchReadiness(
        expected_trade_dates=tuple(status.trade_date for status in statuses),
        statuses_by_trade_date={status.trade_date: status for status in statuses},
        elapsed_ms=4,
        scanned_file_count=sum(1 for status in statuses if status.materialized),
    )


def _ready_dataset_status() -> DatasetReadinessStatus:
    return DatasetReadinessStatus(ready=True, statuses=())


def _run_sensor(sensor, context: _FakeContext):
    return sensor._raw_fn(context)


class MarketBreadthContinuitySensorTests(unittest.TestCase):
    def test_market_breadth_registered_gap_skips_before_batch_readiness(self) -> None:
        context = _FakeContext(("2026-06-13", "2026-06-16"))
        with (
            patch(
                "orchestrator.defs.sensors.market_breadth_continuity_sensor."
                "load_expected_trade_date_window",
                return_value=_expected_window(
                    ("2026-06-13", "2026-06-15", "2026-06-16")
                ),
            ),
            patch(
                "orchestrator.defs.sensors.market_breadth_continuity_sensor."
                "batch_gold_market_breadth_lake_readiness"
            ) as batch_readiness,
        ):
            result = _run_sensor(market_breadth_continuity_sensor, context)

        self.assertEqual(result.run_requests, [])
        self.assertIn("注册缺口", result.skip_reason.skip_message)
        batch_readiness.assert_not_called()
        cursor = json.loads(result.cursor)
        self.assertEqual(
            cursor["details"]["continuity_status"][
                "first_missing_registered_date"
            ],
            "2026-06-15",
        )

    def test_market_breadth_first_missing_gold_submits_that_partition(self) -> None:
        context = _FakeContext(("2026-06-15", "2026-06-16"))
        batch_status = _batch_status(
            (
                _date_status(
                    "2026-06-15",
                    ready=False,
                    materialized=False,
                    reason="missing_gold_market_breadth_file",
                ),
                _date_status(
                    "2026-06-16",
                    ready=False,
                    materialized=False,
                    reason="missing_gold_market_breadth_file",
                ),
            )
        )
        with (
            patch(
                "orchestrator.defs.sensors.market_breadth_continuity_sensor."
                "load_expected_trade_date_window",
                return_value=_expected_window(("2026-06-15", "2026-06-16")),
            ),
            patch(
                "orchestrator.defs.sensors.market_breadth_continuity_sensor."
                "batch_gold_market_breadth_lake_readiness",
                return_value=batch_status,
            ),
            patch(
                "orchestrator.defs.sensors.market_breadth_continuity_sensor."
                "stock_daily_ready_for_trade_date",
                return_value=_ready_dataset_status(),
            ),
        ):
            result = _run_sensor(market_breadth_continuity_sensor, context)

        self.assertEqual(len(result.run_requests), 1)
        self.assertEqual(result.run_requests[0].partition_key, "2026-06-15")
        self.assertEqual(
            result.run_requests[0].run_key,
            "gold_market_breadth_daily:2026-06-15",
        )

    def test_market_breadth_materialized_check_failure_blocks_later_date(self) -> None:
        context = _FakeContext(("2026-06-15", "2026-06-16"))
        batch_status = _batch_status(
            (
                _date_status(
                    "2026-06-15",
                    ready=False,
                    materialized=True,
                    reason="blocking_checks_failed",
                    failed_check_names=("gold_market_breadth_counts_add_up",),
                ),
                _date_status(
                    "2026-06-16",
                    ready=False,
                    materialized=False,
                    reason="missing_gold_market_breadth_file",
                ),
            )
        )
        with (
            patch(
                "orchestrator.defs.sensors.market_breadth_continuity_sensor."
                "load_expected_trade_date_window",
                return_value=_expected_window(("2026-06-15", "2026-06-16")),
            ),
            patch(
                "orchestrator.defs.sensors.market_breadth_continuity_sensor."
                "batch_gold_market_breadth_lake_readiness",
                return_value=batch_status,
            ),
            patch(
                "orchestrator.defs.sensors.market_breadth_continuity_sensor."
                "stock_daily_ready_for_trade_date"
            ) as stock_daily_status,
        ):
            result = _run_sensor(market_breadth_continuity_sensor, context)

        self.assertEqual(result.run_requests, [])
        self.assertIn("暂不自动重跑", result.skip_reason.skip_message)
        stock_daily_status.assert_not_called()

    def test_stock_return_distribution_submits_first_missing_partition(self) -> None:
        context = _FakeContext(("2026-06-15", "2026-06-16"))
        batch_status = _batch_status(
            (
                _date_status(
                    "2026-06-15",
                    ready=False,
                    materialized=False,
                    reason="missing_gold_stock_return_distribution_file",
                ),
            )
        )
        with (
            patch(
                "orchestrator.defs.sensors.stock_return_distribution_continuity_sensor."
                "load_expected_trade_date_window",
                return_value=_expected_window(("2026-06-15",)),
            ),
            patch(
                "orchestrator.defs.sensors.stock_return_distribution_continuity_sensor."
                "batch_gold_stock_return_distribution_lake_readiness",
                return_value=batch_status,
            ),
            patch(
                "orchestrator.defs.sensors.stock_return_distribution_continuity_sensor."
                "stock_daily_ready_for_trade_date",
                return_value=_ready_dataset_status(),
            ),
        ):
            result = _run_sensor(stock_return_distribution_continuity_sensor, context)

        self.assertEqual(result.run_requests[0].partition_key, "2026-06-15")
        self.assertEqual(
            result.run_requests[0].run_key,
            "gold_stock_return_distribution:2026-06-15",
        )

    def test_local_clickhouse_waits_for_earlier_gold_frontier(self) -> None:
        context = _FakeContext(("2026-06-15", "2026-06-16"))
        serving_batch = _batch_status(
            (
                _date_status("2026-06-15", ready=True, materialized=True, reason="ready"),
                _date_status(
                    "2026-06-16",
                    ready=False,
                    materialized=False,
                    reason="missing_clickhouse_row",
                ),
            )
        )
        breadth_batch = _batch_status(
            (
                _date_status(
                    "2026-06-15",
                    ready=False,
                    materialized=False,
                    reason="missing_gold_market_breadth_file",
                ),
                _date_status(
                    "2026-06-16",
                    ready=False,
                    materialized=False,
                    reason="missing_gold_market_breadth_file",
                ),
            )
        )
        distribution_batch = _batch_status(
            (
                _date_status("2026-06-15", ready=True, materialized=True, reason="ready"),
                _date_status("2026-06-16", ready=True, materialized=True, reason="ready"),
            )
        )
        with (
            patch(
                "orchestrator.defs.sensors.clickhouse_market_breadth_continuity_sensor."
                "load_expected_trade_date_window",
                return_value=_expected_window(("2026-06-15", "2026-06-16")),
            ),
            patch(
                "orchestrator.defs.sensors.clickhouse_market_breadth_continuity_sensor."
                "batch_clickhouse_market_breadth_readiness",
                return_value=serving_batch,
            ),
            patch(
                "orchestrator.defs.sensors.clickhouse_market_breadth_continuity_sensor."
                "batch_gold_market_breadth_lake_readiness",
                return_value=breadth_batch,
            ),
            patch(
                "orchestrator.defs.sensors.clickhouse_market_breadth_continuity_sensor."
                "batch_gold_stock_return_distribution_lake_readiness",
                return_value=distribution_batch,
            ),
        ):
            result = _run_sensor(clickhouse_market_breadth_continuity_sensor, context)

        self.assertEqual(result.run_requests, [])
        self.assertIn("等待上游 gold_market_breadth_daily", result.skip_reason.skip_message)

    def test_prod_clickhouse_waits_for_local_frontier(self) -> None:
        context = _FakeContext(("2026-06-15", "2026-06-16"))
        prod_batch = _batch_status(
            (
                _date_status("2026-06-15", ready=True, materialized=True, reason="ready"),
                _date_status(
                    "2026-06-16",
                    ready=False,
                    materialized=False,
                    reason="missing_prod_clickhouse_row",
                ),
            )
        )
        local_batch = _batch_status(
            (
                _date_status(
                    "2026-06-15",
                    ready=False,
                    materialized=False,
                    reason="missing_clickhouse_row",
                ),
                _date_status(
                    "2026-06-16",
                    ready=False,
                    materialized=False,
                    reason="missing_clickhouse_row",
                ),
            )
        )
        with (
            patch(
                "orchestrator.defs.sensors.clickhouse_market_breadth_continuity_sensor."
                "load_expected_trade_date_window",
                return_value=_expected_window(("2026-06-15", "2026-06-16")),
            ),
            patch(
                "orchestrator.defs.sensors.clickhouse_market_breadth_continuity_sensor."
                "batch_prod_clickhouse_market_breadth_readiness",
                return_value=prod_batch,
            ),
            patch(
                "orchestrator.defs.sensors.clickhouse_market_breadth_continuity_sensor."
                "batch_clickhouse_market_breadth_readiness",
                return_value=local_batch,
            ),
        ):
            result = _run_sensor(prod_clickhouse_market_breadth_continuity_sensor, context)

        self.assertEqual(result.run_requests, [])
        self.assertIn("等待本机 ClickHouse", result.skip_reason.skip_message)


if __name__ == "__main__":
    unittest.main()
