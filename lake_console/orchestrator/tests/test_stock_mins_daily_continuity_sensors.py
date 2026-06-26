import json
import unittest
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import duckdb

from orchestrator.defs.asset_guards.stk_mins_lake_readiness import (
    StkMinsBatchReadiness,
    StkMinsDateReadiness,
)
from orchestrator.defs.partitions import (
    cn_a_stock_mins_silver_trade_days,
    cn_a_stock_mins_trade_days,
)
from orchestrator.defs.asset_guards.stk_mins_qfq_factor_repair import (
    GoldStkMinsQfqFactorRepairStatus,
)
from orchestrator.defs.sensors import readiness
from orchestrator.defs.sensors import stock_mins_qfq_daily_sensor as qfq_daily_module
from orchestrator.defs.sensors import (
    stock_mins_qfq_factor_repair_sensor as qfq_factor_repair_module,
)
from orchestrator.defs.sensors.stock_mins_raw_sensor import stock_mins_raw_sensor
from orchestrator.defs.sensors.stock_mins_qfq_daily_sensor import (
    stock_mins_qfq_daily_sensor,
)
from orchestrator.defs.sensors.stock_mins_qfq_factor_repair_sensor import (
    stock_mins_qfq_factor_repair_sensor,
)
from orchestrator.defs.sensors.stock_mins_silver_sensor import stock_mins_silver_sensor
from orchestrator.defs.sensors.stock_mins_silver_trade_day_sensor import (
    stock_mins_silver_trade_day_sensor,
)


class _AfterRawWindowDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 6, 16, 19, 35, tzinfo=tz)


class _BeforeRawWindowDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 6, 16, 19, 20, tzinfo=tz)


class _AfterSilverPartitionWindowDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 6, 16, 19, 46, tzinfo=tz)


class _BeforeSilverPartitionWindowDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 6, 16, 19, 44, tzinfo=tz)


class _AfterSilverRunWindowDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 6, 16, 19, 55, tzinfo=tz)


class _BeforeSilverRunWindowDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 6, 16, 19, 49, tzinfo=tz)


class _AfterQfqDailyWindowDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 6, 16, 20, 15, tzinfo=tz)


class _BeforeQfqDailyWindowDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 6, 16, 20, 5, tzinfo=tz)


class _AfterQfqFactorRepairWindowDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 6, 16, 20, 45, tzinfo=tz)


class _BeforeQfqFactorRepairWindowDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 6, 16, 20, 35, tzinfo=tz)


class _Instance:
    def __init__(
        self,
        partitions: tuple[str, ...],
        *,
        partitions_by_name: dict[str, tuple[str, ...]] | None = None,
    ) -> None:
        self._partitions = partitions
        self._partitions_by_name = partitions_by_name or {}

    def get_dynamic_partitions(self, name: str) -> list[str]:
        return list(self._partitions_by_name.get(name, self._partitions))


class _LakeRoot:
    def root(self) -> Path:
        return Path("/tmp/goldenshare-test-lake-root")


class _DuckDBResource:
    @contextmanager
    def connect(self):
        with duckdb.connect(":memory:") as connection:
            yield connection


class _Context:
    def __init__(
        self,
        partitions: tuple[str, ...] = (),
        *,
        cursor: str | None = None,
        partitions_by_name: dict[str, tuple[str, ...]] | None = None,
    ) -> None:
        self.cursor = cursor
        self.instance = _Instance(partitions, partitions_by_name=partitions_by_name)
        self.resources = SimpleNamespace(
            lake_root=_LakeRoot(),
            duckdb=_DuckDBResource(),
        )


def _asset_status(
    *,
    asset_key: str,
    ready: bool,
    materialized: bool,
    checks_passed: bool,
    reason: str,
) -> readiness.AssetReadinessStatus:
    return readiness.AssetReadinessStatus(
        asset_key=asset_key,
        partition_key=None,
        ready=ready,
        materialized=materialized,
        checks_passed=checks_passed,
        freshness_passed=ready,
        materialization_storage_id=1 if materialized else None,
        materialization_date="2026-06-16" if ready else None,
        missing_check_names=() if checks_passed else (f"{asset_key}_file_exists",),
        failed_check_names=(),
        reason=reason,
    )


def _dataset_status(
    *,
    ready: bool,
    materialized: bool = False,
    checks_passed: bool = False,
    reason: str = "not ready",
    asset_key: str = "raw_stk_mins_1m",
) -> readiness.DatasetReadinessStatus:
    return readiness.DatasetReadinessStatus(
        ready=ready,
        statuses=(
            _asset_status(
                asset_key=asset_key,
                ready=ready,
                materialized=materialized,
                checks_passed=checks_passed,
                reason=reason,
            ),
        ),
    )


def _raw_date_status(
    *,
    trade_date: str,
    ready: bool,
    materialized: bool = False,
    checks_passed: bool = False,
    reason: str = "not ready",
) -> StkMinsDateReadiness:
    failed_check_names = () if ready else ("raw_stk_mins_contract_check",)
    return StkMinsDateReadiness(
        trade_date=trade_date,
        ready=ready,
        materialized=materialized,
        checks_passed=checks_passed,
        reason=reason,
        failed_check_names=failed_check_names,
        missing_file_paths=(),
        expected_file_count=5,
        existing_file_count=5 if materialized else 0,
        checked_row_count=5 if materialized else 0,
        failed_row_count=0 if ready else 1,
    )


def _raw_batch_status(
    statuses_by_trade_date: dict[str, StkMinsDateReadiness],
) -> StkMinsBatchReadiness:
    trade_dates = tuple(sorted(statuses_by_trade_date))
    return StkMinsBatchReadiness(
        dataset="raw_stk_mins",
        expected_start_date=trade_dates[0] if trade_dates else None,
        expected_end_date=trade_dates[-1] if trade_dates else None,
        expected_count=len(trade_dates),
        freq_count=5,
        elapsed_ms=1.0,
        statuses_by_trade_date=statuses_by_trade_date,
    )


def _silver_date_status(
    *,
    trade_date: str,
    ready: bool,
    materialized: bool = False,
    checks_passed: bool = False,
    reason: str = "not ready",
) -> StkMinsDateReadiness:
    failed_check_names = () if ready else ("silver_stk_mins_contract_check",)
    return StkMinsDateReadiness(
        trade_date=trade_date,
        ready=ready,
        materialized=materialized,
        checks_passed=checks_passed,
        reason=reason,
        failed_check_names=failed_check_names,
        missing_file_paths=(),
        expected_file_count=5,
        existing_file_count=5 if materialized else 0,
        checked_row_count=5 if materialized else 0,
        failed_row_count=0 if ready else 1,
    )


def _silver_batch_status(
    statuses_by_trade_date: dict[str, StkMinsDateReadiness],
) -> StkMinsBatchReadiness:
    trade_dates = tuple(sorted(statuses_by_trade_date))
    return StkMinsBatchReadiness(
        dataset="silver_stk_mins",
        expected_start_date=trade_dates[0] if trade_dates else None,
        expected_end_date=trade_dates[-1] if trade_dates else None,
        expected_count=len(trade_dates),
        freq_count=5,
        elapsed_ms=1.0,
        statuses_by_trade_date=statuses_by_trade_date,
    )


def _lake_date_status(
    *,
    dataset: str,
    trade_date: str,
    ready: bool,
    materialized: bool = False,
    checks_passed: bool = False,
    reason: str = "not ready",
    expected_file_count: int = 1,
) -> StkMinsDateReadiness:
    return StkMinsDateReadiness(
        trade_date=trade_date,
        ready=ready,
        materialized=materialized,
        checks_passed=checks_passed,
        reason=reason,
        failed_check_names=() if ready else (f"{dataset}_file_exists",),
        missing_file_paths=(),
        expected_file_count=expected_file_count,
        existing_file_count=expected_file_count if materialized else 0,
        checked_row_count=expected_file_count if materialized else 0,
        failed_row_count=0 if ready else 1,
    )


def _adj_factor_date_status(
    *,
    trade_date: str,
    ready: bool,
    materialized: bool = False,
    checks_passed: bool = False,
    reason: str = "not ready",
) -> StkMinsDateReadiness:
    return _lake_date_status(
        dataset="adj_factor",
        trade_date=trade_date,
        ready=ready,
        materialized=materialized,
        checks_passed=checks_passed,
        reason=reason,
        expected_file_count=2,
    )


def _gold_qfq_date_status(
    *,
    trade_date: str,
    ready: bool,
    materialized: bool = False,
    checks_passed: bool = False,
    reason: str = "not ready",
) -> StkMinsDateReadiness:
    return _lake_date_status(
        dataset="gold_stk_mins_qfq",
        trade_date=trade_date,
        ready=ready,
        materialized=materialized,
        checks_passed=checks_passed,
        reason=reason,
        expected_file_count=7,
    )


def _batch_status(
    *,
    dataset: str,
    freq_count: int,
    statuses_by_trade_date: dict[str, StkMinsDateReadiness],
) -> StkMinsBatchReadiness:
    trade_dates = tuple(sorted(statuses_by_trade_date))
    return StkMinsBatchReadiness(
        dataset=dataset,
        expected_start_date=trade_dates[0] if trade_dates else None,
        expected_end_date=trade_dates[-1] if trade_dates else None,
        expected_count=len(trade_dates),
        freq_count=freq_count,
        elapsed_ms=1.0,
        statuses_by_trade_date=statuses_by_trade_date,
    )


def _adj_factor_batch_status(
    statuses_by_trade_date: dict[str, StkMinsDateReadiness],
) -> StkMinsBatchReadiness:
    return _batch_status(
        dataset="adj_factor",
        freq_count=1,
        statuses_by_trade_date=statuses_by_trade_date,
    )


def _gold_qfq_batch_status(
    statuses_by_trade_date: dict[str, StkMinsDateReadiness],
) -> StkMinsBatchReadiness:
    return _batch_status(
        dataset="gold_stk_mins_qfq",
        freq_count=7,
        statuses_by_trade_date=statuses_by_trade_date,
    )


def _asset_readiness_status(
    *,
    ready: bool,
    reason: str = "ready",
    asset_key: str = "silver_stock_identity_map",
) -> readiness.AssetReadinessStatus:
    return _asset_status(
        asset_key=asset_key,
        ready=ready,
        materialized=True,
        checks_passed=True,
        reason=reason,
    )


def _stock_basic_status(*, ready: bool) -> readiness.DatasetReadinessStatus:
    return readiness.DatasetReadinessStatus(
        ready=ready,
        statuses=(
            _asset_status(
                asset_key="silver_stock_basic",
                ready=ready,
                materialized=True,
                checks_passed=True,
                reason="ready" if ready else "stock basic not fresh",
            ),
        ),
    )


def _qfq_factor_repair_status(
    *,
    trade_date: str,
    ready: bool,
    reason: str = "ready",
) -> GoldStkMinsQfqFactorRepairStatus:
    return GoldStkMinsQfqFactorRepairStatus(
        ready=ready,
        trade_date=trade_date,
        reason=reason,
        upstream_batch_id=f"qfq_factor_repair:{trade_date}:digest",
    )


def _skip_message(result) -> str:
    return getattr(result.skip_reason, "skip_message", str(result.skip_reason))


class StockMinsDailyContinuitySensorTests(unittest.TestCase):
    def test_raw_sensor_skips_missing_registered_gap_before_readiness_scan(
        self,
    ) -> None:
        context = _Context(("2026-06-13", "2026-06-16"))
        with patch(
            "orchestrator.defs.sensors.stock_mins_raw_sensor.datetime",
            _AfterRawWindowDateTime,
        ), patch(
            "orchestrator.defs.sensors.stock_mins_raw_sensor."
            "_load_stock_mins_raw_expected_trade_dates",
            return_value=("2026-06-13", "2026-06-15", "2026-06-16"),
        ), patch(
            "orchestrator.defs.sensors.stock_mins_raw_sensor."
            "batch_raw_stk_mins_lake_readiness",
        ) as raw_batch_mock:
            result = stock_mins_raw_sensor._raw_fn(context)

        self.assertEqual(result.run_requests, [])
        raw_batch_mock.assert_not_called()
        self.assertIn("交易日分区存在缺口", _skip_message(result))

        cursor = json.loads(result.cursor)
        continuity = cursor["details"]["frontier"]["continuity"]
        self.assertEqual(cursor["target_date"], "2026-06-15")
        self.assertEqual(continuity["first_missing_registered_date"], "2026-06-15")
        self.assertEqual(continuity["blocked_reason"], "missing_registered_partition")

    def test_raw_sensor_submits_first_not_ready_date_not_latest_registered(
        self,
    ) -> None:
        context = _Context(("2026-06-13", "2026-06-15", "2026-06-16"))
        raw_statuses = {
            "2026-06-13": _raw_date_status(
                trade_date="2026-06-13",
                ready=True,
                materialized=True,
                checks_passed=True,
                reason="ready",
            ),
            "2026-06-15": _raw_date_status(
                trade_date="2026-06-15",
                ready=False,
                reason="missing raw",
            ),
            "2026-06-16": _raw_date_status(
                trade_date="2026-06-16",
                ready=False,
                reason="should not scan",
            ),
        }

        with patch(
            "orchestrator.defs.sensors.stock_mins_raw_sensor.datetime",
            _AfterRawWindowDateTime,
        ), patch(
            "orchestrator.defs.sensors.stock_mins_raw_sensor."
            "_load_stock_mins_raw_expected_trade_dates",
            return_value=("2026-06-13", "2026-06-15", "2026-06-16"),
        ), patch(
            "orchestrator.defs.sensors.stock_mins_raw_sensor."
            "batch_raw_stk_mins_lake_readiness",
            return_value=_raw_batch_status(raw_statuses),
        ) as raw_batch_mock, patch(
            "orchestrator.defs.sensors.stock_mins_raw_sensor."
            "stock_basic_ready_for_trade_date",
            return_value=_stock_basic_status(ready=True),
        ) as stock_basic_ready_mock:
            result = stock_mins_raw_sensor._raw_fn(context)

        self.assertEqual(len(result.run_requests), 1)
        request = result.run_requests[0]
        self.assertEqual(request.partition_key, "2026-06-15")
        self.assertEqual(
            request.run_key,
            "stock_mins_raw_update_from_prod:2026-06-15",
        )
        raw_batch_mock.assert_called_once()
        stock_basic_ready_mock.assert_called_once_with(context.instance, "2026-06-15")

        cursor = json.loads(result.cursor)
        continuity = cursor["details"]["frontier"]["continuity"]
        self.assertEqual(cursor["target_date"], "2026-06-15")
        self.assertEqual(cursor["sample_keys"], ["2026-06-15"])
        self.assertEqual(continuity["ready_through_date"], "2026-06-13")
        self.assertEqual(continuity["next_actionable_date"], "2026-06-15")

    def test_raw_sensor_blocks_materialized_check_problem_without_later_date(
        self,
    ) -> None:
        context = _Context(("2026-06-13", "2026-06-15", "2026-06-16"))
        raw_statuses = {
            "2026-06-13": _raw_date_status(
                trade_date="2026-06-13",
                ready=True,
                materialized=True,
                checks_passed=True,
                reason="ready",
            ),
            "2026-06-15": _raw_date_status(
                trade_date="2026-06-15",
                ready=False,
                materialized=True,
                checks_passed=False,
                reason="blocking checks failed",
            ),
            "2026-06-16": _raw_date_status(
                trade_date="2026-06-16",
                ready=False,
                reason="should not scan",
            ),
        }

        with patch(
            "orchestrator.defs.sensors.stock_mins_raw_sensor.datetime",
            _AfterRawWindowDateTime,
        ), patch(
            "orchestrator.defs.sensors.stock_mins_raw_sensor."
            "_load_stock_mins_raw_expected_trade_dates",
            return_value=("2026-06-13", "2026-06-15", "2026-06-16"),
        ), patch(
            "orchestrator.defs.sensors.stock_mins_raw_sensor."
            "batch_raw_stk_mins_lake_readiness",
            return_value=_raw_batch_status(raw_statuses),
        ) as raw_batch_mock, patch(
            "orchestrator.defs.sensors.stock_mins_raw_sensor."
            "stock_basic_ready_for_trade_date",
        ) as stock_basic_ready_mock:
            result = stock_mins_raw_sensor._raw_fn(context)

        self.assertEqual(result.run_requests, [])
        self.assertIn("暂不自动重跑", _skip_message(result))
        raw_batch_mock.assert_called_once()
        stock_basic_ready_mock.assert_not_called()

        cursor = json.loads(result.cursor)
        continuity = cursor["details"]["frontier"]["continuity"]
        self.assertEqual(cursor["target_date"], "2026-06-15")
        self.assertEqual(continuity["blocked_reason"], "materialized_check_problem")

    def test_raw_sensor_records_continuity_before_source_window(self) -> None:
        context = _Context(("2026-06-13", "2026-06-15"))
        raw_statuses = {
            "2026-06-13": _raw_date_status(
                trade_date="2026-06-13",
                ready=True,
                materialized=True,
                checks_passed=True,
                reason="ready",
            ),
            "2026-06-15": _raw_date_status(
                trade_date="2026-06-15",
                ready=False,
                reason="missing raw",
            ),
        }

        with patch(
            "orchestrator.defs.sensors.stock_mins_raw_sensor.datetime",
            _BeforeRawWindowDateTime,
        ), patch(
            "orchestrator.defs.sensors.stock_mins_raw_sensor."
            "_load_stock_mins_raw_expected_trade_dates",
            return_value=("2026-06-13", "2026-06-15"),
        ), patch(
            "orchestrator.defs.sensors.stock_mins_raw_sensor."
            "batch_raw_stk_mins_lake_readiness",
            return_value=_raw_batch_status(raw_statuses),
        ), patch(
            "orchestrator.defs.sensors.stock_mins_raw_sensor."
            "stock_basic_ready_for_trade_date",
        ) as stock_basic_ready_mock:
            result = stock_mins_raw_sensor._raw_fn(context)

        self.assertEqual(result.run_requests, [])
        self.assertIn("19:30", _skip_message(result))
        stock_basic_ready_mock.assert_not_called()

        cursor = json.loads(result.cursor)
        continuity = cursor["details"]["frontier"]["continuity"]
        self.assertFalse(cursor["details"]["evidence"]["source_window_started"])
        self.assertEqual(continuity["first_not_ready_date"], "2026-06-15")

    def test_raw_sensor_skips_when_stock_basic_not_ready_for_selected_date(
        self,
    ) -> None:
        context = _Context(("2026-06-15",))

        with patch(
            "orchestrator.defs.sensors.stock_mins_raw_sensor.datetime",
            _AfterRawWindowDateTime,
        ), patch(
            "orchestrator.defs.sensors.stock_mins_raw_sensor."
            "_load_stock_mins_raw_expected_trade_dates",
            return_value=("2026-06-15",),
        ), patch(
            "orchestrator.defs.sensors.stock_mins_raw_sensor."
            "batch_raw_stk_mins_lake_readiness",
            return_value=_raw_batch_status(
                {
                    "2026-06-15": _raw_date_status(
                        trade_date="2026-06-15",
                        ready=False,
                        reason="missing raw",
                    )
                }
            ),
        ), patch(
            "orchestrator.defs.sensors.stock_mins_raw_sensor."
            "stock_basic_ready_for_trade_date",
            return_value=_stock_basic_status(ready=False),
        ) as stock_basic_ready_mock:
            result = stock_mins_raw_sensor._raw_fn(context)

        self.assertEqual(result.run_requests, [])
        self.assertIn("股票基础信息", _skip_message(result))
        stock_basic_ready_mock.assert_called_once_with(context.instance, "2026-06-15")

    def test_raw_sensor_skips_when_continuity_window_is_all_ready(self) -> None:
        context = _Context(("2026-06-13", "2026-06-15", "2026-06-16"))

        with patch(
            "orchestrator.defs.sensors.stock_mins_raw_sensor.datetime",
            _AfterRawWindowDateTime,
        ), patch(
            "orchestrator.defs.sensors.stock_mins_raw_sensor."
            "_load_stock_mins_raw_expected_trade_dates",
            return_value=("2026-06-13", "2026-06-15", "2026-06-16"),
        ), patch(
            "orchestrator.defs.sensors.stock_mins_raw_sensor."
            "batch_raw_stk_mins_lake_readiness",
            return_value=_raw_batch_status(
                {
                    trade_date: _raw_date_status(
                        trade_date=trade_date,
                        ready=True,
                        materialized=True,
                        checks_passed=True,
                        reason="ready",
                    )
                    for trade_date in ("2026-06-13", "2026-06-15", "2026-06-16")
                }
            ),
        ), patch(
            "orchestrator.defs.sensors.stock_mins_raw_sensor."
            "stock_basic_ready_for_trade_date",
        ) as stock_basic_ready_mock:
            result = stock_mins_raw_sensor._raw_fn(context)

        self.assertEqual(result.run_requests, [])
        self.assertIn("continuity 窗口内分区已经生成完成", _skip_message(result))
        stock_basic_ready_mock.assert_not_called()

        cursor = json.loads(result.cursor)
        continuity = cursor["details"]["frontier"]["continuity"]
        self.assertEqual(cursor["target_date"], "2026-06-16")
        self.assertEqual(continuity["ready_through_date"], "2026-06-16")

    def test_silver_trade_day_sensor_skips_raw_partition_gap_before_readiness_scan(
        self,
    ) -> None:
        context = _Context(
            partitions_by_name={
                cn_a_stock_mins_trade_days.name: ("2026-06-13", "2026-06-16"),
                cn_a_stock_mins_silver_trade_days.name: ("2026-06-13",),
            }
        )
        with patch(
            "orchestrator.defs.sensors.stock_mins_silver_trade_day_sensor.datetime",
            _AfterSilverPartitionWindowDateTime,
        ), patch(
            "orchestrator.defs.sensors.stock_mins_silver_trade_day_sensor."
            "_load_stock_mins_silver_expected_trade_dates",
            return_value=("2026-06-13", "2026-06-15", "2026-06-16"),
        ), patch(
            "orchestrator.defs.sensors.stock_mins_silver_trade_day_sensor."
            "batch_raw_stk_mins_lake_readiness",
        ) as raw_batch_mock, patch(
            "orchestrator.defs.sensors.stock_mins_silver_trade_day_sensor."
            "stock_daily_ready_for_trade_date",
        ) as stock_daily_ready_mock:
            result = stock_mins_silver_trade_day_sensor._raw_fn(context)

        self.assertEqual(result.dynamic_partitions_requests, [])
        self.assertIn("raw 交易日分区存在缺口", _skip_message(result))
        raw_batch_mock.assert_not_called()
        stock_daily_ready_mock.assert_not_called()

        cursor = json.loads(result.cursor)
        raw_continuity = cursor["details"]["frontier"]["raw"]
        self.assertEqual(cursor["target_date"], "2026-06-15")
        self.assertEqual(raw_continuity["first_missing_registered_date"], "2026-06-15")

    def test_silver_trade_day_sensor_registers_first_missing_silver_partition(
        self,
    ) -> None:
        context = _Context(
            partitions_by_name={
                cn_a_stock_mins_trade_days.name: (
                    "2026-06-13",
                    "2026-06-15",
                    "2026-06-16",
                ),
                cn_a_stock_mins_silver_trade_days.name: (
                    "2026-06-13",
                    "2026-06-16",
                ),
            }
        )
        with patch(
            "orchestrator.defs.sensors.stock_mins_silver_trade_day_sensor.datetime",
            _AfterSilverPartitionWindowDateTime,
        ), patch(
            "orchestrator.defs.sensors.stock_mins_silver_trade_day_sensor."
            "_load_stock_mins_silver_expected_trade_dates",
            return_value=("2026-06-13", "2026-06-15", "2026-06-16"),
        ), patch(
            "orchestrator.defs.sensors.stock_mins_silver_trade_day_sensor."
            "batch_raw_stk_mins_lake_readiness",
            return_value=_raw_batch_status(
                {
                    "2026-06-13": _raw_date_status(
                        trade_date="2026-06-13",
                        ready=True,
                        materialized=True,
                        checks_passed=True,
                        reason="ready",
                    ),
                    "2026-06-15": _raw_date_status(
                        trade_date="2026-06-15",
                        ready=True,
                        materialized=True,
                        checks_passed=True,
                        reason="ready",
                    ),
                    "2026-06-16": _raw_date_status(
                        trade_date="2026-06-16",
                        ready=True,
                        materialized=True,
                        checks_passed=True,
                        reason="ready",
                    ),
                }
            ),
        ) as raw_batch_mock, patch(
            "orchestrator.defs.sensors.stock_mins_silver_trade_day_sensor."
            "stock_daily_ready_for_trade_date",
            return_value=_dataset_status(
                ready=True,
                materialized=True,
                checks_passed=True,
                reason="ready",
                asset_key="silver_stock_daily",
            ),
        ), patch(
            "orchestrator.defs.sensors.stock_mins_silver_trade_day_sensor."
            "suspend_d_ready_for_trade_date",
            return_value=_dataset_status(
                ready=True,
                materialized=True,
                checks_passed=True,
                reason="ready",
                asset_key="silver_stock_suspend_daily",
            ),
        ), patch(
            "orchestrator.defs.sensors.stock_mins_silver_trade_day_sensor."
            "silver_stock_identity_map_ready_for_trade_date",
            return_value=_asset_readiness_status(ready=True),
        ), patch(
            "orchestrator.defs.sensors.stock_mins_silver_trade_day_sensor."
            "silver_namechange_ready_for_trade_date",
            side_effect=AssertionError("namechange readiness must not be queried"),
            create=True,
        ) as namechange_ready_mock:
            result = stock_mins_silver_trade_day_sensor._raw_fn(context)

        self.assertEqual(len(result.dynamic_partitions_requests), 1)
        raw_batch_mock.assert_called_once()
        namechange_ready_mock.assert_not_called()

        cursor = json.loads(result.cursor)
        silver_continuity = cursor["details"]["frontier"]["silver"]
        self.assertEqual(cursor["sample_keys"], ["2026-06-15"])
        self.assertEqual(
            cursor["details"]["frontier"]["raw_lake"]["dataset"],
            "raw_stk_mins",
        )
        self.assertEqual(
            silver_continuity["first_missing_registered_date"],
            "2026-06-15",
        )

    def test_silver_trade_day_sensor_blocks_when_raw_batch_not_ready_before_silver_gap(
        self,
    ) -> None:
        context = _Context(
            partitions_by_name={
                cn_a_stock_mins_trade_days.name: (
                    "2026-06-13",
                    "2026-06-15",
                    "2026-06-16",
                ),
                cn_a_stock_mins_silver_trade_days.name: (
                    "2026-06-13",
                    "2026-06-15",
                ),
            }
        )
        with patch(
            "orchestrator.defs.sensors.stock_mins_silver_trade_day_sensor.datetime",
            _AfterSilverPartitionWindowDateTime,
        ), patch(
            "orchestrator.defs.sensors.stock_mins_silver_trade_day_sensor."
            "_load_stock_mins_silver_expected_trade_dates",
            return_value=("2026-06-13", "2026-06-15", "2026-06-16"),
        ), patch(
            "orchestrator.defs.sensors.stock_mins_silver_trade_day_sensor."
            "batch_raw_stk_mins_lake_readiness",
            return_value=_raw_batch_status(
                {
                    "2026-06-13": _raw_date_status(
                        trade_date="2026-06-13",
                        ready=True,
                        materialized=True,
                        checks_passed=True,
                        reason="ready",
                    ),
                    "2026-06-15": _raw_date_status(
                        trade_date="2026-06-15",
                        ready=False,
                        materialized=False,
                        checks_passed=False,
                        reason="raw missing",
                    ),
                    "2026-06-16": _raw_date_status(
                        trade_date="2026-06-16",
                        ready=False,
                        materialized=False,
                        checks_passed=False,
                        reason="should not advance",
                    ),
                }
            ),
        ), patch(
            "orchestrator.defs.sensors.stock_mins_silver_trade_day_sensor."
            "stock_daily_ready_for_trade_date",
        ) as stock_daily_ready_mock:
            result = stock_mins_silver_trade_day_sensor._raw_fn(context)

        self.assertEqual(result.dynamic_partitions_requests, [])
        self.assertIn("raw continuity", _skip_message(result))
        stock_daily_ready_mock.assert_not_called()

        cursor = json.loads(result.cursor)
        self.assertEqual(cursor["target_date"], "2026-06-15")
        self.assertEqual(
            cursor["details"]["gate_statuses"]["raw_stk_mins"]["trade_date"],
            "2026-06-15",
        )

    def test_silver_trade_day_sensor_records_continuity_before_window(self) -> None:
        context = _Context(
            partitions_by_name={
                cn_a_stock_mins_trade_days.name: ("2026-06-13", "2026-06-15"),
                cn_a_stock_mins_silver_trade_days.name: ("2026-06-13",),
            }
        )
        with patch(
            "orchestrator.defs.sensors.stock_mins_silver_trade_day_sensor.datetime",
            _BeforeSilverPartitionWindowDateTime,
        ), patch(
            "orchestrator.defs.sensors.stock_mins_silver_trade_day_sensor."
            "_load_stock_mins_silver_expected_trade_dates",
            return_value=("2026-06-13", "2026-06-15"),
        ), patch(
            "orchestrator.defs.sensors.stock_mins_silver_trade_day_sensor."
            "batch_raw_stk_mins_lake_readiness",
            return_value=_raw_batch_status(
                {
                    "2026-06-13": _raw_date_status(
                        trade_date="2026-06-13",
                        ready=True,
                        materialized=True,
                        checks_passed=True,
                        reason="ready",
                    ),
                    "2026-06-15": _raw_date_status(
                        trade_date="2026-06-15",
                        ready=True,
                        materialized=True,
                        checks_passed=True,
                        reason="ready",
                    ),
                }
            ),
        ) as raw_batch_mock:
            result = stock_mins_silver_trade_day_sensor._raw_fn(context)

        self.assertEqual(result.dynamic_partitions_requests, [])
        self.assertIn("19:45", _skip_message(result))
        raw_batch_mock.assert_called_once()

        cursor = json.loads(result.cursor)
        silver_continuity = cursor["details"]["frontier"]["silver"]
        self.assertFalse(cursor["details"]["evidence"]["register_window_started"])
        self.assertEqual(
            cursor["details"]["frontier"]["raw_lake"]["dataset"],
            "raw_stk_mins",
        )
        self.assertEqual(
            silver_continuity["first_missing_registered_date"],
            "2026-06-15",
        )

    def test_silver_sensor_submits_first_not_ready_date_not_latest_registered(
        self,
    ) -> None:
        context = _Context(("2026-06-13", "2026-06-15", "2026-06-16"))
        silver_statuses = {
            "2026-06-13": _silver_date_status(
                trade_date="2026-06-13",
                ready=True,
                materialized=True,
                checks_passed=True,
                reason="ready",
            ),
            "2026-06-15": _silver_date_status(
                trade_date="2026-06-15",
                ready=False,
                reason="missing silver",
            ),
            "2026-06-16": _silver_date_status(
                trade_date="2026-06-16",
                ready=False,
                reason="should not scan",
            ),
        }
        raw_statuses = {
            trade_date: _raw_date_status(
                trade_date=trade_date,
                ready=True,
                materialized=True,
                checks_passed=True,
                reason="ready",
            )
            for trade_date in ("2026-06-13", "2026-06-15", "2026-06-16")
        }

        with patch(
            "orchestrator.defs.sensors.stock_mins_silver_sensor.datetime",
            _AfterSilverRunWindowDateTime,
        ), patch(
            "orchestrator.defs.sensors.stock_mins_silver_sensor."
            "_load_stock_mins_silver_expected_trade_dates",
            return_value=("2026-06-13", "2026-06-15", "2026-06-16"),
        ), patch(
            "orchestrator.defs.sensors.stock_mins_silver_sensor."
            "batch_silver_stk_mins_lake_readiness",
            return_value=_silver_batch_status(silver_statuses),
        ) as silver_batch_mock, patch(
            "orchestrator.defs.sensors.stock_mins_silver_sensor."
            "batch_raw_stk_mins_lake_readiness",
            return_value=_raw_batch_status(raw_statuses),
        ) as raw_batch_mock, patch(
            "orchestrator.defs.sensors.stock_mins_silver_sensor."
            "stock_daily_ready_for_trade_date",
            return_value=_dataset_status(
                ready=True,
                materialized=True,
                checks_passed=True,
                reason="ready",
                asset_key="silver_stock_daily",
            ),
        ), patch(
            "orchestrator.defs.sensors.stock_mins_silver_sensor."
            "suspend_d_ready_for_trade_date",
            return_value=_dataset_status(
                ready=True,
                materialized=True,
                checks_passed=True,
                reason="ready",
                asset_key="silver_stock_suspend_daily",
            ),
        ), patch(
            "orchestrator.defs.sensors.stock_mins_silver_sensor."
            "silver_stock_identity_map_ready_for_trade_date",
            return_value=_asset_readiness_status(ready=True),
        ), patch(
            "orchestrator.defs.sensors.stock_mins_silver_sensor."
            "silver_namechange_ready_for_trade_date",
            side_effect=AssertionError("namechange readiness must not be queried"),
            create=True,
        ) as namechange_ready_mock:
            result = stock_mins_silver_sensor._raw_fn(context)

        self.assertEqual(len(result.run_requests), 1)
        namechange_ready_mock.assert_not_called()
        request = result.run_requests[0]
        self.assertEqual(request.partition_key, "2026-06-15")
        self.assertEqual(request.run_key, "stock_mins_silver_update:2026-06-15")
        silver_batch_mock.assert_called_once()
        raw_batch_mock.assert_called_once()

        cursor = json.loads(result.cursor)
        continuity = cursor["details"]["frontier"]["silver"]
        self.assertEqual(cursor["target_date"], "2026-06-15")
        self.assertEqual(continuity["next_actionable_date"], "2026-06-15")
        self.assertEqual(
            cursor["details"]["frontier"]["silver_lake"]["dataset"],
            "silver_stk_mins",
        )
        self.assertEqual(
            cursor["details"]["frontier"]["raw_lake"]["dataset"],
            "raw_stk_mins",
        )

    def test_silver_sensor_skips_missing_silver_partition_without_readiness_scan(
        self,
    ) -> None:
        context = _Context(("2026-06-13", "2026-06-16"))
        with patch(
            "orchestrator.defs.sensors.stock_mins_silver_sensor.datetime",
            _AfterSilverRunWindowDateTime,
        ), patch(
            "orchestrator.defs.sensors.stock_mins_silver_sensor."
            "_load_stock_mins_silver_expected_trade_dates",
            return_value=("2026-06-13", "2026-06-15", "2026-06-16"),
        ), patch(
            "orchestrator.defs.sensors.stock_mins_silver_sensor."
            "batch_silver_stk_mins_lake_readiness",
        ) as silver_batch_mock:
            result = stock_mins_silver_sensor._raw_fn(context)

        self.assertEqual(result.run_requests, [])
        self.assertIn("silver 交易日分区存在缺口", _skip_message(result))
        silver_batch_mock.assert_not_called()

        cursor = json.loads(result.cursor)
        continuity = cursor["details"]["frontier"]["silver"]
        self.assertEqual(continuity["first_missing_registered_date"], "2026-06-15")

    def test_silver_sensor_blocks_materialized_check_problem_without_later_date(
        self,
    ) -> None:
        context = _Context(("2026-06-13", "2026-06-15", "2026-06-16"))
        silver_statuses = {
            "2026-06-13": _silver_date_status(
                trade_date="2026-06-13",
                ready=True,
                materialized=True,
                checks_passed=True,
                reason="ready",
            ),
            "2026-06-15": _silver_date_status(
                trade_date="2026-06-15",
                ready=False,
                materialized=True,
                checks_passed=False,
                reason="blocking checks failed",
            ),
            "2026-06-16": _silver_date_status(
                trade_date="2026-06-16",
                ready=False,
                reason="should not scan",
            ),
        }
        raw_statuses = {
            trade_date: _raw_date_status(
                trade_date=trade_date,
                ready=True,
                materialized=True,
                checks_passed=True,
                reason="ready",
            )
            for trade_date in ("2026-06-13", "2026-06-15", "2026-06-16")
        }

        with patch(
            "orchestrator.defs.sensors.stock_mins_silver_sensor.datetime",
            _AfterSilverRunWindowDateTime,
        ), patch(
            "orchestrator.defs.sensors.stock_mins_silver_sensor."
            "_load_stock_mins_silver_expected_trade_dates",
            return_value=("2026-06-13", "2026-06-15", "2026-06-16"),
        ), patch(
            "orchestrator.defs.sensors.stock_mins_silver_sensor."
            "batch_silver_stk_mins_lake_readiness",
            return_value=_silver_batch_status(silver_statuses),
        ) as silver_batch_mock, patch(
            "orchestrator.defs.sensors.stock_mins_silver_sensor."
            "batch_raw_stk_mins_lake_readiness",
            return_value=_raw_batch_status(raw_statuses),
        ) as raw_batch_mock:
            result = stock_mins_silver_sensor._raw_fn(context)

        self.assertEqual(result.run_requests, [])
        self.assertIn("暂不自动重跑", _skip_message(result))
        silver_batch_mock.assert_called_once()
        raw_batch_mock.assert_called_once()

        cursor = json.loads(result.cursor)
        continuity = cursor["details"]["frontier"]["silver"]
        self.assertEqual(continuity["blocked_reason"], "materialized_check_problem")

    def test_silver_sensor_skips_when_selected_date_upstream_not_ready(self) -> None:
        context = _Context(("2026-06-15",))
        with patch(
            "orchestrator.defs.sensors.stock_mins_silver_sensor.datetime",
            _AfterSilverRunWindowDateTime,
        ), patch(
            "orchestrator.defs.sensors.stock_mins_silver_sensor."
            "_load_stock_mins_silver_expected_trade_dates",
            return_value=("2026-06-15",),
        ), patch(
            "orchestrator.defs.sensors.stock_mins_silver_sensor."
            "batch_silver_stk_mins_lake_readiness",
            return_value=_silver_batch_status(
                {
                    "2026-06-15": _silver_date_status(
                        trade_date="2026-06-15",
                        ready=False,
                        reason="missing silver",
                    )
                }
            ),
        ), patch(
            "orchestrator.defs.sensors.stock_mins_silver_sensor."
            "batch_raw_stk_mins_lake_readiness",
            return_value=_raw_batch_status(
                {
                    "2026-06-15": _raw_date_status(
                        trade_date="2026-06-15",
                        ready=False,
                        materialized=False,
                        checks_passed=False,
                        reason="raw missing",
                    )
                }
            ),
        ), patch(
            "orchestrator.defs.sensors.stock_mins_silver_sensor."
            "stock_daily_ready_for_trade_date",
            return_value=_dataset_status(
                ready=True,
                materialized=True,
                checks_passed=True,
                reason="ready",
                asset_key="silver_stock_daily",
            ),
        ), patch(
            "orchestrator.defs.sensors.stock_mins_silver_sensor."
            "suspend_d_ready_for_trade_date",
            return_value=_dataset_status(
                ready=True,
                materialized=True,
                checks_passed=True,
                reason="ready",
                asset_key="silver_stock_suspend_daily",
            ),
        ), patch(
            "orchestrator.defs.sensors.stock_mins_silver_sensor."
            "silver_stock_identity_map_ready_for_trade_date",
            return_value=_asset_readiness_status(ready=True),
        ), patch(
            "orchestrator.defs.sensors.stock_mins_silver_sensor."
            "silver_namechange_ready_for_trade_date",
            side_effect=AssertionError("namechange readiness must not be queried"),
            create=True,
        ) as namechange_ready_mock:
            result = stock_mins_silver_sensor._raw_fn(context)

        self.assertEqual(result.run_requests, [])
        namechange_ready_mock.assert_not_called()
        self.assertIn("raw continuity", _skip_message(result))

    def test_silver_sensor_blocks_later_run_when_raw_batch_not_ready_first(self) -> None:
        context = _Context(
            partitions_by_name={
                cn_a_stock_mins_silver_trade_days.name: (
                    "2026-06-13",
                    "2026-06-15",
                    "2026-06-16",
                ),
                cn_a_stock_mins_trade_days.name: (
                    "2026-06-13",
                    "2026-06-15",
                    "2026-06-16",
                ),
            }
        )
        with patch(
            "orchestrator.defs.sensors.stock_mins_silver_sensor.datetime",
            _AfterSilverRunWindowDateTime,
        ), patch(
            "orchestrator.defs.sensors.stock_mins_silver_sensor."
            "_load_stock_mins_silver_expected_trade_dates",
            return_value=("2026-06-13", "2026-06-15", "2026-06-16"),
        ), patch(
            "orchestrator.defs.sensors.stock_mins_silver_sensor."
            "batch_silver_stk_mins_lake_readiness",
            return_value=_silver_batch_status(
                {
                    "2026-06-13": _silver_date_status(
                        trade_date="2026-06-13",
                        ready=True,
                        materialized=True,
                        checks_passed=True,
                        reason="ready",
                    ),
                    "2026-06-15": _silver_date_status(
                        trade_date="2026-06-15",
                        ready=True,
                        materialized=True,
                        checks_passed=True,
                        reason="ready",
                    ),
                    "2026-06-16": _silver_date_status(
                        trade_date="2026-06-16",
                        ready=False,
                        reason="missing silver",
                    ),
                }
            ),
        ), patch(
            "orchestrator.defs.sensors.stock_mins_silver_sensor."
            "batch_raw_stk_mins_lake_readiness",
            return_value=_raw_batch_status(
                {
                    "2026-06-13": _raw_date_status(
                        trade_date="2026-06-13",
                        ready=True,
                        materialized=True,
                        checks_passed=True,
                        reason="ready",
                    ),
                    "2026-06-15": _raw_date_status(
                        trade_date="2026-06-15",
                        ready=False,
                        materialized=False,
                        checks_passed=False,
                        reason="raw missing",
                    ),
                    "2026-06-16": _raw_date_status(
                        trade_date="2026-06-16",
                        ready=False,
                        materialized=False,
                        checks_passed=False,
                        reason="should not advance",
                    ),
                }
            ),
        ), patch(
            "orchestrator.defs.sensors.stock_mins_silver_sensor."
            "stock_daily_ready_for_trade_date",
        ) as stock_daily_ready_mock:
            result = stock_mins_silver_sensor._raw_fn(context)

        self.assertEqual(result.run_requests, [])
        self.assertIn("raw continuity", _skip_message(result))
        stock_daily_ready_mock.assert_not_called()

        cursor = json.loads(result.cursor)
        self.assertEqual(cursor["target_date"], "2026-06-15")
        self.assertEqual(
            cursor["details"]["gate_statuses"]["raw_stk_mins"]["trade_date"],
            "2026-06-15",
        )

    def test_silver_sensor_records_continuity_before_window(self) -> None:
        context = _Context(("2026-06-13", "2026-06-15"))
        silver_statuses = {
            "2026-06-13": _silver_date_status(
                trade_date="2026-06-13",
                ready=True,
                materialized=True,
                checks_passed=True,
                reason="ready",
            ),
            "2026-06-15": _silver_date_status(
                trade_date="2026-06-15",
                ready=False,
                reason="missing silver",
            ),
        }
        raw_statuses = {
            trade_date: _raw_date_status(
                trade_date=trade_date,
                ready=True,
                materialized=True,
                checks_passed=True,
                reason="ready",
            )
            for trade_date in ("2026-06-13", "2026-06-15")
        }

        with patch(
            "orchestrator.defs.sensors.stock_mins_silver_sensor.datetime",
            _BeforeSilverRunWindowDateTime,
        ), patch(
            "orchestrator.defs.sensors.stock_mins_silver_sensor."
            "_load_stock_mins_silver_expected_trade_dates",
            return_value=("2026-06-13", "2026-06-15"),
        ), patch(
            "orchestrator.defs.sensors.stock_mins_silver_sensor."
            "batch_silver_stk_mins_lake_readiness",
            return_value=_silver_batch_status(silver_statuses),
        ) as silver_batch_mock, patch(
            "orchestrator.defs.sensors.stock_mins_silver_sensor."
            "batch_raw_stk_mins_lake_readiness",
            return_value=_raw_batch_status(raw_statuses),
        ) as raw_batch_mock:
            result = stock_mins_silver_sensor._raw_fn(context)

        self.assertEqual(result.run_requests, [])
        self.assertIn("19:50", _skip_message(result))
        silver_batch_mock.assert_called_once()
        raw_batch_mock.assert_called_once()

        cursor = json.loads(result.cursor)
        continuity = cursor["details"]["frontier"]["silver"]
        self.assertFalse(cursor["details"]["evidence"]["run_window_started"])
        self.assertEqual(continuity["first_not_ready_date"], "2026-06-15")
        self.assertEqual(
            cursor["details"]["frontier"]["silver_lake"]["dataset"],
            "silver_stk_mins",
        )
        self.assertEqual(
            cursor["details"]["frontier"]["raw_lake"]["dataset"],
            "raw_stk_mins",
        )

    def test_silver_sensor_skips_when_continuity_window_is_all_ready(self) -> None:
        context = _Context(("2026-06-13", "2026-06-15", "2026-06-16"))
        with patch(
            "orchestrator.defs.sensors.stock_mins_silver_sensor.datetime",
            _AfterSilverRunWindowDateTime,
        ), patch(
            "orchestrator.defs.sensors.stock_mins_silver_sensor."
            "_load_stock_mins_silver_expected_trade_dates",
            return_value=("2026-06-13", "2026-06-15", "2026-06-16"),
        ), patch(
            "orchestrator.defs.sensors.stock_mins_silver_sensor."
            "batch_silver_stk_mins_lake_readiness",
            return_value=_silver_batch_status(
                {
                    trade_date: _silver_date_status(
                        trade_date=trade_date,
                        ready=True,
                        materialized=True,
                        checks_passed=True,
                        reason="ready",
                    )
                    for trade_date in ("2026-06-13", "2026-06-15", "2026-06-16")
                }
            ),
        ) as silver_batch_mock, patch(
            "orchestrator.defs.sensors.stock_mins_silver_sensor."
            "batch_raw_stk_mins_lake_readiness",
            return_value=_raw_batch_status(
                {
                    trade_date: _raw_date_status(
                        trade_date=trade_date,
                        ready=True,
                        materialized=True,
                        checks_passed=True,
                        reason="ready",
                    )
                    for trade_date in ("2026-06-13", "2026-06-15", "2026-06-16")
                }
            ),
        ) as raw_batch_mock:
            result = stock_mins_silver_sensor._raw_fn(context)

        self.assertEqual(result.run_requests, [])
        self.assertIn("continuity 窗口内分区已经 ready", _skip_message(result))
        silver_batch_mock.assert_called_once()
        raw_batch_mock.assert_called_once()

        cursor = json.loads(result.cursor)
        continuity = cursor["details"]["frontier"]["silver"]
        self.assertEqual(continuity["ready_through_date"], "2026-06-16")

    def test_qfq_daily_sensor_skips_missing_silver_partition_without_readiness_scan(
        self,
    ) -> None:
        context = _Context(("2026-06-13", "2026-06-16"))
        with patch.object(
            qfq_daily_module,
            "datetime",
            _AfterQfqDailyWindowDateTime,
        ), patch.object(
            qfq_daily_module,
            "_load_stock_mins_qfq_expected_trade_dates",
            return_value=("2026-06-13", "2026-06-15", "2026-06-16"),
        ), patch.object(
            qfq_daily_module,
            "batch_silver_stk_mins_lake_readiness",
        ) as silver_batch_mock:
            result = stock_mins_qfq_daily_sensor._raw_fn(context)

        self.assertEqual(result.run_requests, [])
        self.assertIn("silver 交易日分区存在缺口", _skip_message(result))
        silver_batch_mock.assert_not_called()

        cursor = json.loads(result.cursor)
        continuity = cursor["details"]["frontier"]["continuity"]
        self.assertEqual(cursor["target_date"], "2026-06-15")
        self.assertEqual(continuity["first_missing_registered_date"], "2026-06-15")

    def test_qfq_daily_sensor_submits_first_not_ready_date_not_latest_registered(
        self,
    ) -> None:
        context = _Context(("2026-06-13", "2026-06-15", "2026-06-16"))
        trade_dates = ("2026-06-13", "2026-06-15", "2026-06-16")

        with patch.object(
            qfq_daily_module,
            "datetime",
            _AfterQfqDailyWindowDateTime,
        ), patch.object(
            qfq_daily_module,
            "_load_stock_mins_qfq_expected_trade_dates",
            return_value=trade_dates,
        ), patch.object(
            qfq_daily_module,
            "batch_silver_stk_mins_lake_readiness",
            return_value=_silver_batch_status(
                {
                    trade_date: _silver_date_status(
                        trade_date=trade_date,
                        ready=True,
                        materialized=True,
                        checks_passed=True,
                        reason="ready",
                    )
                    for trade_date in trade_dates
                }
            ),
        ), patch.object(
            qfq_daily_module,
            "batch_adj_factor_lake_readiness",
            return_value=_adj_factor_batch_status(
                {
                    trade_date: _adj_factor_date_status(
                        trade_date=trade_date,
                        ready=True,
                        materialized=True,
                        checks_passed=True,
                        reason="ready",
                    )
                    for trade_date in trade_dates
                }
            ),
        ), patch.object(
            qfq_daily_module,
            "batch_gold_stk_mins_qfq_lake_readiness",
            return_value=_gold_qfq_batch_status(
                {
                    "2026-06-13": _gold_qfq_date_status(
                        trade_date="2026-06-13",
                        ready=True,
                        materialized=True,
                        checks_passed=True,
                        reason="ready",
                    ),
                    "2026-06-15": _gold_qfq_date_status(
                        trade_date="2026-06-15",
                        ready=False,
                        materialized=False,
                        checks_passed=False,
                        reason="gold missing",
                    ),
                    "2026-06-16": _gold_qfq_date_status(
                        trade_date="2026-06-16",
                        ready=False,
                        materialized=False,
                        checks_passed=False,
                        reason="should not advance",
                    ),
                }
            ),
        ) as gold_batch_mock:
            result = stock_mins_qfq_daily_sensor._raw_fn(context)

        self.assertEqual(len(result.run_requests), 1)
        request = result.run_requests[0]
        self.assertEqual(request.partition_key, "2026-06-15")
        self.assertEqual(request.run_key, "stock_mins_qfq_daily_update:2026-06-15")
        gold_batch_mock.assert_called_once()

        cursor = json.loads(result.cursor)
        continuity = cursor["details"]["frontier"]["continuity"]
        self.assertEqual(cursor["target_date"], "2026-06-15")
        self.assertEqual(continuity["next_actionable_date"], "2026-06-15")

    def test_qfq_daily_sensor_submits_target_date_when_gold_rows_are_missing(
        self,
    ) -> None:
        context = _Context(("2026-06-15", "2026-06-16", "2026-06-17"))
        trade_dates = ("2026-06-15", "2026-06-16", "2026-06-17")

        with patch.object(
            qfq_daily_module,
            "datetime",
            _AfterQfqDailyWindowDateTime,
        ), patch.object(
            qfq_daily_module,
            "_load_stock_mins_qfq_expected_trade_dates",
            return_value=trade_dates,
        ), patch.object(
            qfq_daily_module,
            "batch_silver_stk_mins_lake_readiness",
            return_value=_silver_batch_status(
                {
                    trade_date: _silver_date_status(
                        trade_date=trade_date,
                        ready=True,
                        materialized=True,
                        checks_passed=True,
                        reason="ready",
                    )
                    for trade_date in trade_dates
                }
            ),
        ), patch.object(
            qfq_daily_module,
            "batch_adj_factor_lake_readiness",
            return_value=_adj_factor_batch_status(
                {
                    trade_date: _adj_factor_date_status(
                        trade_date=trade_date,
                        ready=True,
                        materialized=True,
                        checks_passed=True,
                        reason="ready",
                    )
                    for trade_date in trade_dates
                }
            ),
        ), patch.object(
            qfq_daily_module,
            "batch_gold_stk_mins_qfq_lake_readiness",
            return_value=_gold_qfq_batch_status(
                {
                    "2026-06-15": _gold_qfq_date_status(
                        trade_date="2026-06-15",
                        ready=True,
                        materialized=True,
                        checks_passed=True,
                        reason="ready",
                    ),
                    "2026-06-16": _gold_qfq_date_status(
                        trade_date="2026-06-16",
                        ready=True,
                        materialized=True,
                        checks_passed=True,
                        reason="ready",
                    ),
                    "2026-06-17": _gold_qfq_date_status(
                        trade_date="2026-06-17",
                        ready=False,
                        materialized=False,
                        checks_passed=False,
                        reason="gold qfq rows are missing for 2026-06-17",
                    ),
                }
            ),
        ) as gold_batch_mock:
            result = stock_mins_qfq_daily_sensor._raw_fn(context)

        self.assertEqual(len(result.run_requests), 1)
        request = result.run_requests[0]
        self.assertEqual(request.partition_key, "2026-06-17")
        self.assertEqual(request.run_key, "stock_mins_qfq_daily_update:2026-06-17")
        gold_batch_mock.assert_called_once()

        cursor = json.loads(result.cursor)
        continuity = cursor["details"]["frontier"]["continuity"]
        self.assertEqual(cursor["target_date"], "2026-06-17")
        self.assertEqual(continuity["next_actionable_date"], "2026-06-17")
        self.assertIsNone(continuity.get("blocked_reason"))

    def test_qfq_daily_sensor_blocks_materialized_check_problem_without_later_date(
        self,
    ) -> None:
        context = _Context(("2026-06-13", "2026-06-15", "2026-06-16"))
        trade_dates = ("2026-06-13", "2026-06-15", "2026-06-16")

        with patch.object(
            qfq_daily_module,
            "datetime",
            _AfterQfqDailyWindowDateTime,
        ), patch.object(
            qfq_daily_module,
            "_load_stock_mins_qfq_expected_trade_dates",
            return_value=trade_dates,
        ), patch.object(
            qfq_daily_module,
            "batch_silver_stk_mins_lake_readiness",
            return_value=_silver_batch_status(
                {
                    trade_date: _silver_date_status(
                        trade_date=trade_date,
                        ready=True,
                        materialized=True,
                        checks_passed=True,
                        reason="ready",
                    )
                    for trade_date in trade_dates
                }
            ),
        ), patch.object(
            qfq_daily_module,
            "batch_adj_factor_lake_readiness",
            return_value=_adj_factor_batch_status(
                {
                    trade_date: _adj_factor_date_status(
                        trade_date=trade_date,
                        ready=True,
                        materialized=True,
                        checks_passed=True,
                        reason="ready",
                    )
                    for trade_date in trade_dates
                }
            ),
        ), patch.object(
            qfq_daily_module,
            "batch_gold_stk_mins_qfq_lake_readiness",
            return_value=_gold_qfq_batch_status(
                {
                    "2026-06-13": _gold_qfq_date_status(
                        trade_date="2026-06-13",
                        ready=True,
                        materialized=True,
                        checks_passed=True,
                        reason="ready",
                    ),
                    "2026-06-15": _gold_qfq_date_status(
                        trade_date="2026-06-15",
                        ready=False,
                        materialized=True,
                        checks_passed=False,
                        reason="gold failed",
                    ),
                    "2026-06-16": _gold_qfq_date_status(
                        trade_date="2026-06-16",
                        ready=False,
                        materialized=False,
                        checks_passed=False,
                        reason="should not advance",
                    ),
                }
            ),
        ) as gold_batch_mock:
            result = stock_mins_qfq_daily_sensor._raw_fn(context)

        self.assertEqual(result.run_requests, [])
        self.assertIn("暂不自动重跑", _skip_message(result))
        gold_batch_mock.assert_called_once()

        cursor = json.loads(result.cursor)
        continuity = cursor["details"]["frontier"]["continuity"]
        self.assertEqual(continuity["blocked_reason"], "materialized_check_problem")
        self.assertEqual(cursor["details"]["reason_code"], "gold_failed")
        self.assertEqual(cursor["details"]["blocked_component"], "gold_stk_mins_qfq")

    def test_qfq_factor_repair_sensor_skips_when_gold_not_ready_without_later_date(
        self,
    ) -> None:
        context = _Context(("2026-06-13", "2026-06-15", "2026-06-16"))

        with patch.object(
            qfq_factor_repair_module,
            "datetime",
            _AfterQfqFactorRepairWindowDateTime,
        ), patch.object(
            qfq_factor_repair_module,
            "_load_stock_mins_qfq_expected_trade_dates",
            return_value=("2026-06-13", "2026-06-15", "2026-06-16"),
        ), patch.object(
            qfq_factor_repair_module,
            "batch_gold_stk_mins_qfq_lake_readiness",
            return_value=_gold_qfq_batch_status(
                {
                    "2026-06-13": _gold_qfq_date_status(
                        trade_date="2026-06-13",
                        ready=True,
                        materialized=True,
                        checks_passed=True,
                        reason="ready",
                    ),
                    "2026-06-15": _gold_qfq_date_status(
                        trade_date="2026-06-15",
                        ready=False,
                        materialized=False,
                        checks_passed=False,
                        reason="gold missing",
                    ),
                    "2026-06-16": _gold_qfq_date_status(
                        trade_date="2026-06-16",
                        ready=False,
                        materialized=False,
                        checks_passed=False,
                        reason="should not advance",
                    ),
                }
            ),
        ) as gold_batch_mock, patch.object(
            qfq_factor_repair_module,
            "gold_stk_mins_qfq_factor_repair_status",
            return_value=_qfq_factor_repair_status(
                trade_date="2026-06-13",
                ready=True,
            ),
        ) as repair_status_mock:
            result = stock_mins_qfq_factor_repair_sensor._raw_fn(context)

        self.assertEqual(result.run_requests, [])
        self.assertIn("尚未全部 ready", _skip_message(result))
        gold_batch_mock.assert_called_once()
        repair_status_mock.assert_called_once_with(
            context.instance,
            "2026-06-13",
            include_event_storage_ids=False,
        )

    def test_qfq_factor_repair_sensor_submits_first_not_completed_date(self) -> None:
        context = _Context(("2026-06-13", "2026-06-15", "2026-06-16"))

        with patch.object(
            qfq_factor_repair_module,
            "datetime",
            _AfterQfqFactorRepairWindowDateTime,
        ), patch.object(
            qfq_factor_repair_module,
            "_load_stock_mins_qfq_expected_trade_dates",
            return_value=("2026-06-13", "2026-06-15", "2026-06-16"),
        ), patch.object(
            qfq_factor_repair_module,
            "batch_gold_stk_mins_qfq_lake_readiness",
            return_value=_gold_qfq_batch_status(
                {
                    trade_date: _gold_qfq_date_status(
                        trade_date=trade_date,
                        ready=True,
                        materialized=True,
                        checks_passed=True,
                        reason="ready",
                    )
                    for trade_date in ("2026-06-13", "2026-06-15", "2026-06-16")
                }
            ),
        ), patch.object(
            qfq_factor_repair_module,
            "gold_stk_mins_qfq_factor_repair_status",
            side_effect=lambda _instance, trade_date, **_kwargs: _qfq_factor_repair_status(
                trade_date=trade_date,
                ready=trade_date == "2026-06-13",
                reason="ready" if trade_date == "2026-06-13" else "repair missing",
            ),
        ) as repair_status_mock:
            result = stock_mins_qfq_factor_repair_sensor._raw_fn(context)

        self.assertEqual(len(result.run_requests), 1)
        request = result.run_requests[0]
        self.assertEqual(request.run_key, "stock_mins_qfq_factor_repair:2026-06-15")
        self.assertEqual(
            request.run_config["ops"]["stock_mins_qfq_factor_repair_op"]["config"],
            {"trade_date": "2026-06-15"},
        )
        self.assertEqual(
            [call.args[1] for call in repair_status_mock.call_args_list],
            ["2026-06-13", "2026-06-15"],
        )
        self.assertTrue(
            all(
                call.kwargs == {"include_event_storage_ids": False}
                for call in repair_status_mock.call_args_list
            )
        )

        cursor = json.loads(result.cursor)
        continuity = cursor["details"]["frontier"]["continuity"]
        self.assertEqual(cursor["target_date"], "2026-06-15")
        self.assertEqual(continuity["next_actionable_date"], "2026-06-15")

    def test_qfq_factor_repair_sensor_advances_after_completed_repair(self) -> None:
        context = _Context(("2026-06-13", "2026-06-15", "2026-06-16"))

        with patch.object(
            qfq_factor_repair_module,
            "datetime",
            _AfterQfqFactorRepairWindowDateTime,
        ), patch.object(
            qfq_factor_repair_module,
            "_load_stock_mins_qfq_expected_trade_dates",
            return_value=("2026-06-13", "2026-06-15", "2026-06-16"),
        ), patch.object(
            qfq_factor_repair_module,
            "batch_gold_stk_mins_qfq_lake_readiness",
            return_value=_gold_qfq_batch_status(
                {
                    trade_date: _gold_qfq_date_status(
                        trade_date=trade_date,
                        ready=True,
                        materialized=True,
                        checks_passed=True,
                        reason="ready",
                    )
                    for trade_date in ("2026-06-13", "2026-06-15", "2026-06-16")
                }
            ),
        ), patch.object(
            qfq_factor_repair_module,
            "gold_stk_mins_qfq_factor_repair_status",
            side_effect=lambda _instance, trade_date, **_kwargs: _qfq_factor_repair_status(
                trade_date=trade_date,
                ready=trade_date != "2026-06-16",
                reason="ready" if trade_date != "2026-06-16" else "repair missing",
            ),
        ):
            result = stock_mins_qfq_factor_repair_sensor._raw_fn(context)

        self.assertEqual(len(result.run_requests), 1)
        self.assertEqual(
            result.run_requests[0].run_key,
            "stock_mins_qfq_factor_repair:2026-06-16",
        )

    def test_qfq_daily_sensor_skips_before_window_without_readiness_scan(self) -> None:
        context = _Context(("2026-06-13", "2026-06-15"))

        with patch.object(
            qfq_daily_module,
            "datetime",
            _BeforeQfqDailyWindowDateTime,
        ), patch.object(
            qfq_daily_module,
            "_load_stock_mins_qfq_expected_trade_dates",
            side_effect=AssertionError("calendar must not be loaded before window"),
        ), patch.object(
            qfq_daily_module,
            "batch_silver_stk_mins_lake_readiness",
            side_effect=AssertionError("silver batch must not run before window"),
        ), patch.object(
            qfq_daily_module,
            "batch_adj_factor_lake_readiness",
            side_effect=AssertionError("adj factor batch must not run before window"),
        ), patch.object(
            qfq_daily_module,
            "batch_gold_stk_mins_qfq_lake_readiness",
            side_effect=AssertionError("gold qfq batch must not run before window"),
        ):
            result = stock_mins_qfq_daily_sensor._raw_fn(context)

        self.assertEqual(result.run_requests, [])
        self.assertIn("20:10", _skip_message(result))

        cursor = json.loads(result.cursor)
        self.assertIsNone(cursor["target_date"])
        self.assertFalse(cursor["details"]["evidence"]["run_window_started"])
        self.assertNotIn("continuity", cursor["details"].get("frontier", {}))
        self.assertNotIn("silver", cursor["details"].get("frontier", {}))
        self.assertNotIn("adj_factor", cursor["details"].get("frontier", {}))
        self.assertNotIn("gold", cursor["details"].get("frontier", {}))

    def test_qfq_factor_repair_sensor_skips_before_window_without_readiness_scan(self) -> None:
        context = _Context(("2026-06-13", "2026-06-15"))

        with patch.object(
            qfq_factor_repair_module,
            "datetime",
            _BeforeQfqFactorRepairWindowDateTime,
        ), patch.object(
            qfq_factor_repair_module,
            "_load_stock_mins_qfq_expected_trade_dates",
            side_effect=AssertionError("calendar must not be loaded before window"),
        ), patch.object(
            qfq_factor_repair_module,
            "batch_gold_stk_mins_qfq_lake_readiness",
            side_effect=AssertionError("gold qfq batch must not run before window"),
        ), patch.object(
            qfq_factor_repair_module,
            "gold_stk_mins_qfq_factor_repair_status",
            side_effect=AssertionError("repair status must not be read before window"),
        ):
            result = stock_mins_qfq_factor_repair_sensor._raw_fn(context)

        self.assertEqual(result.run_requests, [])
        self.assertIn("20:40", _skip_message(result))

        cursor = json.loads(result.cursor)
        self.assertIsNone(cursor["target_date"])
        self.assertFalse(cursor["details"]["evidence"]["run_window_started"])
        self.assertNotIn("continuity", cursor["details"].get("frontier", {}))
        self.assertNotIn("gold_batch_status", cursor["details"])
        self.assertNotIn("qfq_factor_repair_status", cursor["details"])


if __name__ == "__main__":
    unittest.main()
