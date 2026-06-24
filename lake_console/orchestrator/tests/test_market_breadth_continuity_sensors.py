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
    missing_check_names: tuple[str, ...] = (),
    summary: dict[str, object] | None = None,
) -> ContinuityDateReadiness:
    return ContinuityDateReadiness(
        trade_date=trade_date,
        ready=ready,
        materialized=materialized,
        checks_passed=ready,
        reason=reason,
        failed_check_names=failed_check_names,
        missing_check_names=missing_check_names,
        summary=summary or {},
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


def _heavy_clickhouse_summary(
    trade_dates: tuple[str, ...],
    *,
    row_count: int = 1,
) -> dict[str, object]:
    return {
        "clickhouse_row_count": row_count,
        "clickhouse_row_counts_by_partition": {
            trade_date: row_count for trade_date in trade_dates
        },
        "gold_market_breadth_daily_path": (
            "/fake/lake/gold/breadth/market_breadth_daily/"
            f"trade_date={trade_dates[0]}/part-000.parquet"
        ),
        "gold_stock_return_distribution_path": (
            "/fake/lake/gold/breadth/stock_return_distribution/"
            f"trade_date={trade_dates[0]}/part-000.parquet"
        ),
        "gold_market_breadth_row": {
            "trade_date": trade_dates[0],
            "up_count": 1,
            "down_count": 2,
            "flat_count": 0,
            "total_count": 3,
            "red_rate": 33.33,
        },
        "gold_stock_return_distribution_row": {
            "trade_date": trade_dates[0],
            "flat_count": 0,
            "total_count": 3,
        },
    }


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
                    failed_check_names=("gold_market_breadth_value_domain_check",),
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
        cursor = json.loads(result.cursor)
        details = cursor["details"]
        self.assertEqual(details["blocked_component"], "gold_market_breadth_daily")
        self.assertEqual(details["reason_code"], "missing_gold_market_breadth_file")
        self.assertNotIn("serving_batch_status", details)
        self.assertNotIn("upstream_batch_statuses", details)
        self.assertEqual(
            details["upstream_frontiers"]["gold_market_breadth_daily"][
                "first_not_ready_trade_date"
            ],
            "2026-06-15",
        )
        self.assertEqual(
            details["upstream_statuses"]["gold_market_breadth_daily"]["reason"],
            "missing_gold_market_breadth_file",
        )

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
        cursor = json.loads(result.cursor)
        details = cursor["details"]
        self.assertEqual(details["blocked_component"], "ch_share_fact_market_breadth_daily")
        self.assertEqual(details["reason_code"], "missing_clickhouse_row")
        self.assertEqual(
            details["upstream_frontiers"]["ch_share_fact_market_breadth_daily"][
                "first_not_ready_trade_date"
            ],
            "2026-06-15",
        )
        self.assertNotIn("serving_batch_status", details)
        self.assertNotIn("upstream_batch_statuses", details)

    def test_prod_clickhouse_request_run_cursor_is_compact(self) -> None:
        trade_dates = ("2026-06-23", "2026-06-24")
        context = _FakeContext(trade_dates)
        prod_batch = _batch_status(
            (
                _date_status(
                    "2026-06-23",
                    ready=True,
                    materialized=True,
                    reason="ready",
                    summary={
                        "local_clickhouse_row_count": 1,
                        "prod_clickhouse_row_count": 1,
                    },
                ),
                _date_status(
                    "2026-06-24",
                    ready=False,
                    materialized=False,
                    reason="missing_prod_clickhouse_row",
                    missing_check_names=(
                        "prod_ch_share_fact_market_breadth_row_count_is_one",
                    ),
                    summary={
                        "local_clickhouse_row_count": 1,
                        "prod_clickhouse_row_count": 0,
                    },
                ),
            )
        )
        local_batch = _batch_status(
            (
                _date_status(
                    "2026-06-23",
                    ready=True,
                    materialized=True,
                    reason="ready",
                    summary=_heavy_clickhouse_summary(trade_dates),
                ),
                _date_status(
                    "2026-06-24",
                    ready=True,
                    materialized=True,
                    reason="ready",
                    summary=_heavy_clickhouse_summary(trade_dates),
                ),
            )
        )
        with (
            patch(
                "orchestrator.defs.sensors.clickhouse_market_breadth_continuity_sensor."
                "load_expected_trade_date_window",
                return_value=_expected_window(trade_dates),
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

        self.assertEqual(len(result.run_requests), 1)
        self.assertEqual(result.run_requests[0].partition_key, "2026-06-24")
        self.assertLess(len(result.cursor), 3000)

        cursor = json.loads(result.cursor)
        details = cursor["details"]
        cursor_text = json.dumps(cursor, sort_keys=True)
        self.assertEqual(cursor["target_date"], "2026-06-24")
        self.assertEqual(details["selected_trade_date"], "2026-06-24")
        self.assertEqual(details["reason_code"], "request_run")
        self.assertEqual(details["blocked_component"], "none")
        self.assertNotIn("serving_batch_status", details)
        self.assertNotIn("upstream_batch_statuses", details)
        self.assertNotIn("status_samples", cursor_text)
        self.assertNotIn("gold_market_breadth_daily_path", cursor_text)
        self.assertNotIn("gold_market_breadth_row", cursor_text)
        self.assertNotIn("clickhouse_row_counts_by_partition", cursor_text)

        self.assertEqual(
            details["continuity_status"]["ready_through_trade_date"],
            "2026-06-23",
        )
        serving_status = details["serving_status"]
        self.assertEqual(serving_status["trade_date"], "2026-06-24")
        self.assertEqual(serving_status["reason"], "missing_prod_clickhouse_row")
        self.assertEqual(serving_status["local_clickhouse_row_count"], 1)
        self.assertEqual(serving_status["prod_clickhouse_row_count"], 0)
        self.assertEqual(
            serving_status["missing_check_names"],
            ["prod_ch_share_fact_market_breadth_row_count_is_one"],
        )
        upstream_frontier = details["upstream_frontiers"][
            "ch_share_fact_market_breadth_daily"
        ]
        self.assertEqual(upstream_frontier["ready_through_trade_date"], "2026-06-24")
        self.assertIsNone(upstream_frontier["first_not_ready_trade_date"])


if __name__ == "__main__":
    unittest.main()
