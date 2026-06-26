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
from orchestrator.defs.partitions import cn_a_index_trade_days, cn_a_index_ts_codes
from orchestrator.defs.sensors.market_major_indices_daily_sensor import (
    _cursor_payload,
    market_major_indices_daily_sensor,
)
from orchestrator.defs.sensors.market_major_indices_input_readiness import (
    MarketMajorIndicesInputReadiness,
)


CN_TZ = ZoneInfo("Asia/Shanghai")


class _FakeDuckDB:
    @contextmanager
    def connect(self):
        yield object()


class _FakeLakeRoot:
    def root(self):
        return Path("/fake/lake")


class _FakeInstance:
    def __init__(
        self,
        *,
        trade_days: tuple[str, ...],
        index_codes: tuple[str, ...] = ("000001.SH", "399001.SZ"),
    ) -> None:
        self._partitions = {
            cn_a_index_trade_days.name: list(trade_days),
            cn_a_index_ts_codes.name: list(index_codes),
        }

    def get_dynamic_partitions(self, name: str) -> list[str]:
        return list(self._partitions[name])


class _FakeContext:
    def __init__(
        self,
        *,
        trade_days: tuple[str, ...],
        index_codes: tuple[str, ...] = ("000001.SH", "399001.SZ"),
    ) -> None:
        self.instance = _FakeInstance(trade_days=trade_days, index_codes=index_codes)
        self.resources = SimpleNamespace(
            lake_root=_FakeLakeRoot(),
            duckdb=_FakeDuckDB(),
        )
        self.cursor = None


def _expected_window(
    expected_trade_dates: tuple[str, ...],
) -> ContinuityExpectedDateWindow:
    return ContinuityExpectedDateWindow(
        expected_trade_dates=expected_trade_dates,
        min_trade_date="2000-01-01",
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
        elapsed_ms=3,
        scanned_file_count=len(statuses),
    )


def _input_ready(trade_date: str) -> MarketMajorIndicesInputReadiness:
    return MarketMajorIndicesInputReadiness(
        trade_date=trade_date,
        seed_row_count=2,
        active_seed_code_count=2,
        registered_code_count=2,
        missing_registered_seed_codes=(),
        missing_index_basic_file=False,
        missing_index_basic_seed_codes=(),
        missing_silver_daily_file=False,
        missing_silver_daily_seed_codes=(),
    )


def _run_sensor(context: _FakeContext):
    return market_major_indices_daily_sensor._raw_fn(context)


class MarketMajorIndicesDailySensorTests(unittest.TestCase):
    def test_registered_gap_skips_before_batch_readiness(self) -> None:
        context = _FakeContext(trade_days=("2026-06-13", "2026-06-16"))
        with (
            patch(
                "orchestrator.defs.sensors.market_major_indices_daily_sensor."
                "load_expected_trade_date_window",
                return_value=_expected_window(
                    ("2026-06-13", "2026-06-15", "2026-06-16")
                ),
            ),
            patch(
                "orchestrator.defs.sensors.market_major_indices_daily_sensor."
                "batch_market_major_indices_lake_readiness"
            ) as batch_readiness,
        ):
            result = _run_sensor(context)

        self.assertIsNotNone(result.skip_reason)
        self.assertIn("注册缺口", result.skip_reason.skip_message)
        batch_readiness.assert_not_called()
        cursor = json.loads(result.cursor)
        self.assertEqual(
            cursor["details"]["frontier"]["continuity"][
                "first_missing_registered_date"
            ],
            "2026-06-15",
        )

    def test_first_missing_gold_date_submits_that_partition(self) -> None:
        context = _FakeContext(trade_days=("2026-06-15", "2026-06-16"))
        gold_batch = _batch_status(
            (
                _date_status(
                    "2026-06-15",
                    ready=False,
                    materialized=False,
                    reason="missing_gold_file",
                ),
                _date_status(
                    "2026-06-16",
                    ready=False,
                    materialized=False,
                    reason="missing_gold_file",
                ),
            )
        )
        ready_status = _date_status(
            "2026-06-15",
            ready=True,
            materialized=True,
            reason="ready",
        )
        with (
            patch(
                "orchestrator.defs.sensors.market_major_indices_daily_sensor."
                "load_expected_trade_date_window",
                return_value=_expected_window(("2026-06-15", "2026-06-16")),
            ),
            patch(
                "orchestrator.defs.sensors.market_major_indices_daily_sensor."
                "batch_market_major_indices_lake_readiness",
                return_value=gold_batch,
            ),
            patch(
                "orchestrator.defs.sensors.market_major_indices_daily_sensor."
                "silver_index_daily_lake_readiness_for_trade_date",
                return_value=ready_status,
            ),
            patch(
                "orchestrator.defs.sensors.market_major_indices_daily_sensor."
                "silver_index_basic_lake_readiness",
                return_value=ready_status,
            ),
            patch(
                "orchestrator.defs.sensors.market_major_indices_daily_sensor."
                "check_market_major_indices_inputs_for_trade_date",
                return_value=_input_ready("2026-06-15"),
            ),
        ):
            result = _run_sensor(context)

        self.assertEqual(len(result.run_requests), 1)
        run_request = result.run_requests[0]
        self.assertEqual(run_request.partition_key, "2026-06-15")
        self.assertEqual(
            run_request.run_key,
            "market_major_indices_daily:2026-06-15",
        )
        cursor = json.loads(result.cursor)
        self.assertEqual(cursor["details"]["blocked_component"], "none")
        self.assertIn("触发 2026-06-15", cursor["details"]["summary"])
        self.assertIn("blocking checks", cursor["details"]["next_action"])
        self.assertLess(len(result.cursor.encode("utf-8")), 3072)

    def test_materialized_gold_check_failure_blocks_later_date(self) -> None:
        context = _FakeContext(trade_days=("2026-06-15", "2026-06-16"))
        gold_batch = _batch_status(
            (
                _date_status(
                    "2026-06-15",
                    ready=False,
                    materialized=True,
                    reason="blocking_checks_failed",
                    failed_check_names=(
                        "gold_market_major_indices_daily_value_domain_check",
                    ),
                ),
                _date_status(
                    "2026-06-16",
                    ready=False,
                    materialized=False,
                    reason="missing_gold_file",
                ),
            )
        )
        with (
            patch(
                "orchestrator.defs.sensors.market_major_indices_daily_sensor."
                "load_expected_trade_date_window",
                return_value=_expected_window(("2026-06-15", "2026-06-16")),
            ),
            patch(
                "orchestrator.defs.sensors.market_major_indices_daily_sensor."
                "batch_market_major_indices_lake_readiness",
                return_value=gold_batch,
            ),
            patch(
                "orchestrator.defs.sensors.market_major_indices_daily_sensor."
                "silver_index_daily_lake_readiness_for_trade_date"
            ) as silver_readiness,
        ):
            result = _run_sensor(context)

        self.assertEqual(result.run_requests, [])
        self.assertIsNotNone(result.skip_reason)
        self.assertIn("暂不自动重跑", result.skip_reason.skip_message)
        silver_readiness.assert_not_called()
        cursor = json.loads(result.cursor)
        self.assertEqual(
            cursor["details"]["blocked_component"],
            "gold_market_major_indices_daily",
        )
        self.assertIn("主要指数 gold", cursor["details"]["summary"])
        self.assertIn("checks", cursor["details"]["next_action"])

    def test_cursor_payload_uses_standard_sensor_cursor_contract(self) -> None:
        evaluated_at = datetime(2026, 5, 26, 16, 5, tzinfo=CN_TZ)
        payload = json.loads(
            _cursor_payload(
                evaluated_at=evaluated_at,
                target_trade_date="2026-05-26",
                registered_trade_day_count=1,
                registered_code_count=10,
                selected_trade_date="2026-05-26",
                reason="ready",
            )
        )

        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(payload["decision"], "request_runs")
        self.assertEqual(payload["target_date"], "2026-05-26")
        self.assertEqual(payload["selected_count"], 1)
        self.assertEqual(payload["blocked_count"], 0)
        self.assertEqual(payload["sample_keys"], ["2026-05-26"])
        self.assertEqual(
            payload["details"]["evidence"]["selected_trade_date"],
            "2026-05-26",
        )
        self.assertIn("summary", payload["details"])
        self.assertIn("next_action", payload["details"])

    def test_input_gate_cursor_points_to_silver_index_daily(self) -> None:
        evaluated_at = datetime(2026, 6, 15, 16, 5, tzinfo=CN_TZ)
        payload = json.loads(
            _cursor_payload(
                evaluated_at=evaluated_at,
                target_trade_date="2026-06-15",
                registered_trade_day_count=10,
                registered_code_count=2,
                selected_trade_date=None,
                reason="主要指数日线 seed/input 门禁未满足，暂不触发 gold。",
                input_status=MarketMajorIndicesInputReadiness(
                    trade_date="2026-06-15",
                    seed_row_count=2,
                    active_seed_code_count=2,
                    registered_code_count=2,
                    missing_registered_seed_codes=(),
                    missing_index_basic_file=False,
                    missing_index_basic_seed_codes=(),
                    missing_silver_daily_file=False,
                    missing_silver_daily_seed_codes=("000001.SH",),
                ),
            )
        )

        self.assertEqual(payload["decision"], "skip")
        self.assertEqual(payload["details"]["blocked_component"], "silver_index_daily")
        self.assertIn("silver_index_daily 还没有 ready", payload["details"]["summary"])
        self.assertIn("先修复同日 silver_index_daily", payload["details"]["next_action"])


if __name__ == "__main__":
    unittest.main()
