import json
import unittest
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

import duckdb

from orchestrator.defs.asset_guards.bounded_continuity import (
    ContinuityBatchReadiness,
    ContinuityDateReadiness,
)
from orchestrator.defs.checks import adj_factor_checks
from orchestrator.defs.duckdb_sql import duckdb_string
from orchestrator.defs.jobs import stock_adj_factor_update as adj_factor_jobs
from orchestrator.defs.paths import silver_trade_calendar_path
from orchestrator.defs.run_contracts.cursors import load_sensor_cursor
from orchestrator.defs.run_contracts.sensor_tags import (
    SENSOR_DOMAIN_TAG,
    SENSOR_ROLE_TAG,
    SENSOR_TARGET_LAYER_TAG,
)
from orchestrator.defs.sensors import readiness
from orchestrator.defs.sensors import stock_adj_factor_sensor as adj_factor_sensor_module
from orchestrator.defs.sensors.readiness import (
    AssetReadinessStatus,
    DatasetReadinessStatus,
)
from orchestrator.defs.sensors.stock_adj_factor_sensor import (
    _raw_run_request_for_trade_date,
    _silver_run_request_for_trade_date,
    raw_adj_factor_update_job_sensor,
    silver_adj_factor_update_job_sensor,
)
from orchestrator.defs.sensors.stock_current_trade_day_sensor import (
    STOCK_CURRENT_TRADE_DAY_REGISTER_START,
    stock_current_trade_day_sensor,
)


EVALUATED_AT = datetime(2026, 5, 29, 9, 30, tzinfo=ZoneInfo("Asia/Shanghai"))
ADJ_FACTOR_REGISTERED_DAYS = ("2026-06-03", "2026-06-04", "2026-06-05")


class _FakeInstance:
    def __init__(self, partitions: tuple[str, ...]) -> None:
        self._partitions = partitions

    def get_dynamic_partitions(self, _name: str) -> list[str]:
        return list(self._partitions)


class _FakeContext:
    def __init__(
        self,
        *,
        partitions: tuple[str, ...],
        lake_root: Path | None = None,
    ) -> None:
        self._temporary_directory = None
        if lake_root is None:
            self._temporary_directory = TemporaryDirectory()
            lake_root = Path(self._temporary_directory.name)
        _write_adj_factor_sensor_calendar(lake_root)
        self.instance = _FakeInstance(partitions)
        self.resources = SimpleNamespace(
            lake_root=_CurrentTradeDayLakeRoot(lake_root),
            duckdb=_CurrentTradeDayDuckDBResource(),
        )


class _CurrentTradeDayLakeRoot:
    def __init__(self, root: Path) -> None:
        self._root = root

    def root(self) -> Path:
        return self._root

    def ensure_available_for_run(self) -> None:
        return None


class _CurrentTradeDayDuckDBResource:
    @contextmanager
    def connect(self):
        with duckdb.connect(database=":memory:") as connection:
            yield connection


class _CurrentTradeDayContext:
    def __init__(
        self,
        *,
        lake_root: Path,
        partitions: tuple[str, ...],
    ) -> None:
        self.instance = _FakeInstance(partitions)
        self.resources = SimpleNamespace(
            lake_root=_CurrentTradeDayLakeRoot(lake_root),
            duckdb=_CurrentTradeDayDuckDBResource(),
        )


class _FixedDateTime(datetime):
    @classmethod
    def now(cls, tz=None):  # noqa: ANN001
        return datetime(2026, 6, 5, 10, 0, tzinfo=tz or UTC)


class _EarlyDateTime(datetime):
    @classmethod
    def now(cls, tz=None):  # noqa: ANN001
        return datetime(2026, 6, 5, 9, 0, tzinfo=tz or UTC)


class _AfterCurrentTradeDayRegisterWindowDateTime(datetime):
    @classmethod
    def now(cls, tz=None):  # noqa: ANN001
        return datetime(2026, 6, 17, 6, 30, tzinfo=tz or UTC)


class _BeforeCurrentTradeDayRegisterWindowDateTime(datetime):
    @classmethod
    def now(cls, tz=None):  # noqa: ANN001
        return datetime(2026, 6, 17, 5, 59, tzinfo=tz or UTC)


def _check_names(check_definitions) -> tuple[str, ...]:
    names = []
    for check_definition in check_definitions:
        check_key = next(iter(check_definition.check_keys))
        names.append(check_key.name)
    return tuple(sorted(names))


def _raw_status(
    *,
    ready: bool,
    materialized: bool = True,
    partition_key: str = "2026-06-05",
    missing_check_names: tuple[str, ...] = (),
    failed_check_names: tuple[str, ...] = (),
    reason: str = "ready",
) -> AssetReadinessStatus:
    checks_passed = ready or (not missing_check_names and not failed_check_names)
    return AssetReadinessStatus(
        asset_key="raw_tushare_adj_factor",
        partition_key=partition_key,
        ready=ready,
        materialized=materialized,
        checks_passed=checks_passed,
        freshness_passed=ready,
        materialization_storage_id=1 if materialized else None,
        materialization_date=partition_key if materialized else None,
        missing_check_names=missing_check_names,
        failed_check_names=failed_check_names,
        reason=reason,
    )


def _stock_basic_status(*, ready: bool) -> DatasetReadinessStatus:
    statuses = tuple(
        AssetReadinessStatus(
            asset_key=asset_key,
            partition_key=None,
            ready=ready,
            materialized=ready,
            checks_passed=ready,
            freshness_passed=ready,
            materialization_storage_id=1 if ready else None,
            materialization_date="2026-06-04" if ready else None,
            missing_check_names=() if ready else ("check_missing",),
            failed_check_names=(),
            reason="ready" if ready else f"{asset_key} not ready",
        )
        for asset_key in ("raw_tushare_stock_basic", "silver_stock_basic")
    )
    return DatasetReadinessStatus(ready=ready, statuses=statuses)


def _batch_status(
    *,
    ready_dates: tuple[str, ...] = (),
    missing_dates: tuple[str, ...] = (),
    failed_dates: tuple[str, ...] = (),
) -> ContinuityBatchReadiness:
    statuses: dict[str, ContinuityDateReadiness] = {}
    for trade_date in (*ready_dates, *missing_dates, *failed_dates):
        if trade_date in ready_dates:
            statuses[trade_date] = ContinuityDateReadiness(
                trade_date=trade_date,
                ready=True,
                materialized=True,
                checks_passed=True,
                reason="ready",
                failed_check_names=(),
                missing_file_paths=(),
            )
        elif trade_date in failed_dates:
            statuses[trade_date] = ContinuityDateReadiness(
                trade_date=trade_date,
                ready=False,
                materialized=True,
                checks_passed=False,
                reason="blocking checks failed",
                failed_check_names=("adj_factor_partition_date_matches",),
                missing_file_paths=(),
            )
        else:
            statuses[trade_date] = ContinuityDateReadiness(
                trade_date=trade_date,
                ready=False,
                materialized=False,
                checks_passed=False,
                reason="missing file",
                failed_check_names=("adj_factor_file_exists",),
                missing_file_paths=(f"/tmp/{trade_date}.parquet",),
            )
    return ContinuityBatchReadiness(
        expected_trade_dates=tuple(statuses),
        statuses_by_trade_date=statuses,
        elapsed_ms=1,
        scanned_file_count=len(statuses),
    )


def _raw_sensor_result(context: _FakeContext):
    return raw_adj_factor_update_job_sensor._raw_fn(context)


def _silver_sensor_result(context: _FakeContext):
    return silver_adj_factor_update_job_sensor._raw_fn(context)


def _write_current_trade_day_calendar(lake_root: Path) -> None:
    calendar_path = silver_trade_calendar_path(lake_root)
    calendar_path.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(database=":memory:") as connection:
        connection.execute(
            f"""
            COPY (
              SELECT * FROM (
                VALUES
                  ('SSE', true, DATE '2026-06-12'),
                  ('SSE', true, DATE '2026-06-15'),
                  ('SSE', true, DATE '2026-06-16'),
                  ('SSE', true, DATE '2026-06-17')
              ) AS calendar(exchange, is_open, trade_date)
            ) TO {duckdb_string(calendar_path)} (FORMAT PARQUET)
            """
        )


def _write_adj_factor_sensor_calendar(lake_root: Path) -> None:
    calendar_path = silver_trade_calendar_path(lake_root)
    calendar_path.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(database=":memory:") as connection:
        connection.execute(
            f"""
            COPY (
              SELECT * FROM (
                VALUES
                  ('SSE', true, DATE '2026-06-03'),
                  ('SSE', true, DATE '2026-06-04'),
                  ('SSE', true, DATE '2026-06-05')
              ) AS calendar(exchange, is_open, trade_date)
            ) TO {duckdb_string(calendar_path)} (FORMAT PARQUET)
            """
        )


class AdjFactorM4ContractTests(unittest.TestCase):
    def test_job_and_sensor_names_follow_split_rule(self) -> None:
        self.assertTrue(hasattr(adj_factor_jobs, "raw_adj_factor_update_job"))
        self.assertTrue(hasattr(adj_factor_jobs, "silver_adj_factor_update_job"))
        self.assertFalse(hasattr(adj_factor_jobs, "stock_adj_factor_update_job"))
        self.assertFalse(hasattr(adj_factor_sensor_module, "stock_adj_factor_sensor"))
        self.assertEqual(
            adj_factor_jobs.raw_adj_factor_update_job.name,
            "raw_adj_factor_update_job",
        )
        self.assertEqual(
            adj_factor_jobs.silver_adj_factor_update_job.name,
            "silver_adj_factor_update_job",
        )
        self.assertEqual(
            raw_adj_factor_update_job_sensor.name,
            "raw_adj_factor_update_job_sensor",
        )
        self.assertEqual(
            silver_adj_factor_update_job_sensor.name,
            "silver_adj_factor_update_job_sensor",
        )
        self.assertEqual(
            raw_adj_factor_update_job_sensor.job_name,
            "raw_adj_factor_update_job",
        )
        self.assertEqual(
            silver_adj_factor_update_job_sensor.job_name,
            "silver_adj_factor_update_job",
        )
        raw_selection = repr(adj_factor_jobs.raw_adj_factor_update_job.selection)
        silver_selection = repr(adj_factor_jobs.silver_adj_factor_update_job.selection)
        self.assertIn("raw_tushare_adj_factor", raw_selection)
        self.assertNotIn("silver_adj_factor", raw_selection)
        self.assertNotIn("silver_stock_basic", raw_selection)
        self.assertIn("silver_adj_factor", silver_selection)
        self.assertNotIn("raw_tushare_adj_factor", silver_selection)
        self.assertNotIn("silver_stock_basic", silver_selection)

    def test_sensor_tags_are_layer_specific(self) -> None:
        self.assertEqual(
            raw_adj_factor_update_job_sensor.tags,
            {
                SENSOR_DOMAIN_TAG: "quote_data",
                SENSOR_TARGET_LAYER_TAG: "raw",
                SENSOR_ROLE_TAG: "asset_update",
            },
        )
        self.assertEqual(
            silver_adj_factor_update_job_sensor.tags,
            {
                SENSOR_DOMAIN_TAG: "quote_data",
                SENSOR_TARGET_LAYER_TAG: "silver",
                SENSOR_ROLE_TAG: "asset_update",
            },
        )

    def test_readiness_check_names_match_adj_factor_check_definitions(self) -> None:
        raw_check_definitions = (
            adj_factor_checks.raw_adj_factor_contract_check,
            adj_factor_checks.raw_adj_factor_key_value_integrity_check,
            adj_factor_checks.raw_adj_factor_partition_allowed_check,
        )
        silver_check_definitions = (
            adj_factor_checks.silver_adj_factor_contract_check,
            adj_factor_checks.silver_adj_factor_key_value_integrity_check,
            adj_factor_checks.silver_adj_factor_lifecycle_coverage_check,
            adj_factor_checks.silver_adj_factor_partition_allowed_check,
        )

        self.assertEqual(
            tuple(sorted(readiness.RAW_ADJ_FACTOR_CHECKS)),
            _check_names(raw_check_definitions),
        )
        self.assertEqual(
            tuple(sorted(readiness.SILVER_ADJ_FACTOR_BLOCKING_CHECKS)),
            _check_names(silver_check_definitions),
        )
        self.assertEqual(
            readiness.ADJ_FACTOR_READINESS_SPECS[0],
            readiness.RAW_ADJ_FACTOR_READINESS_SPEC,
        )

    def test_current_trade_day_sensor_catches_up_two_oldest_missing_partitions(
        self,
    ) -> None:
        with TemporaryDirectory() as temp_dir:
            lake_root = Path(temp_dir)
            _write_current_trade_day_calendar(lake_root)
            context = _CurrentTradeDayContext(
                lake_root=lake_root,
                partitions=("2026-06-12",),
            )

            with patch(
                "orchestrator.defs.sensors.stock_current_trade_day_sensor.datetime",
                _AfterCurrentTradeDayRegisterWindowDateTime,
            ):
                result = stock_current_trade_day_sensor._raw_fn(context)

        payload = json.loads(result.cursor)

        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(payload["decision"], "register_partitions")
        self.assertEqual(payload["target_date"], "2026-06-15")
        self.assertEqual(payload["selected_count"], 2)
        self.assertEqual(payload["blocked_count"], 1)
        self.assertEqual(payload["sample_keys"], ["2026-06-15", "2026-06-16"])
        self.assertEqual(len(result.dynamic_partitions_requests), 1)
        self.assertEqual(
            payload["details"]["partition_set"],
            "cn_a_stock_current_trade_days",
        )
        self.assertEqual(payload["details"]["expected_count"], 4)
        self.assertEqual(payload["details"]["registered_count"], 1)
        self.assertEqual(
            payload["details"]["first_missing_registered_date"],
            "2026-06-15",
        )
        self.assertEqual(
            payload["details"]["selected_keys"],
            ["2026-06-15", "2026-06-16"],
        )
        self.assertEqual(payload["details"]["max_partition_keys_per_tick"], 2)
        self.assertEqual(payload["details"]["window_limit"], 10)
        self.assertEqual(STOCK_CURRENT_TRADE_DAY_REGISTER_START.hour, 6)

    def test_current_trade_day_sensor_before_window_still_catches_up_history(
        self,
    ) -> None:
        with TemporaryDirectory() as temp_dir:
            lake_root = Path(temp_dir)
            _write_current_trade_day_calendar(lake_root)
            context = _CurrentTradeDayContext(
                lake_root=lake_root,
                partitions=("2026-06-12",),
            )

            with patch(
                "orchestrator.defs.sensors.stock_current_trade_day_sensor.datetime",
                _BeforeCurrentTradeDayRegisterWindowDateTime,
            ):
                result = stock_current_trade_day_sensor._raw_fn(context)

        payload = json.loads(result.cursor)

        self.assertEqual(payload["decision"], "register_partitions")
        self.assertEqual(payload["sample_keys"], ["2026-06-15", "2026-06-16"])
        self.assertEqual(payload["details"]["expected_count"], 3)
        self.assertNotIn("2026-06-17", payload["details"]["selected_keys"])

    def test_current_trade_day_sensor_keeps_0600_same_day_window(self) -> None:
        with TemporaryDirectory() as temp_dir:
            lake_root = Path(temp_dir)
            _write_current_trade_day_calendar(lake_root)
            context = _CurrentTradeDayContext(
                lake_root=lake_root,
                partitions=("2026-06-12", "2026-06-15", "2026-06-16"),
            )

            with patch(
                "orchestrator.defs.sensors.stock_current_trade_day_sensor.datetime",
                _BeforeCurrentTradeDayRegisterWindowDateTime,
            ):
                result = stock_current_trade_day_sensor._raw_fn(context)

        payload = json.loads(result.cursor)

        self.assertEqual(result.dynamic_partitions_requests, [])
        self.assertEqual(payload["decision"], "skip")
        self.assertEqual(payload["details"]["selected_keys"], [])
        self.assertIn("06:00", result.skip_reason.skip_message)

    def test_raw_sensor_skips_when_registered_trade_days_have_gap(self) -> None:
        context = _FakeContext(partitions=("2026-06-03", "2026-06-05"))
        with patch(
            "orchestrator.defs.sensors.stock_adj_factor_sensor.datetime",
            _FixedDateTime,
        ), patch(
            "orchestrator.defs.sensors.stock_adj_factor_sensor.batch_raw_adj_factor_lake_readiness"
        ) as batch_readiness:
            result = _raw_sensor_result(context)

        self.assertEqual(result.run_requests, [])
        self.assertIn("分区存在缺口", result.skip_reason.skip_message)
        batch_readiness.assert_not_called()
        cursor_payload = load_sensor_cursor(result.cursor)
        self.assertEqual(cursor_payload["target_date"], "2026-06-04")

    def test_raw_sensor_waits_until_source_window(self) -> None:
        context = _FakeContext(partitions=ADJ_FACTOR_REGISTERED_DAYS)
        with patch(
            "orchestrator.defs.sensors.stock_adj_factor_sensor.datetime",
            _EarlyDateTime,
        ), patch(
            "orchestrator.defs.sensors.stock_adj_factor_sensor.batch_raw_adj_factor_lake_readiness"
        ) as batch_readiness:
            result = _raw_sensor_result(context)

        self.assertEqual(result.run_requests, [])
        self.assertIn("09:30", result.skip_reason.skip_message)
        batch_readiness.assert_not_called()

    def test_raw_sensor_submits_run_when_raw_missing(self) -> None:
        context = _FakeContext(partitions=ADJ_FACTOR_REGISTERED_DAYS)
        with patch(
            "orchestrator.defs.sensors.stock_adj_factor_sensor.datetime",
            _FixedDateTime,
        ), patch(
            "orchestrator.defs.sensors.stock_adj_factor_sensor.batch_raw_adj_factor_lake_readiness",
            return_value=_batch_status(
                ready_dates=("2026-06-03", "2026-06-04"),
                missing_dates=("2026-06-05",),
            ),
        ):
            result = _raw_sensor_result(context)

        self.assertEqual(len(result.run_requests), 1)
        request = result.run_requests[0]
        self.assertEqual(request.partition_key, "2026-06-05")
        self.assertEqual(request.run_key, "raw_adj_factor_update:2026-06-05")
        self.assertEqual(request.run_config, {})

    def test_raw_sensor_does_not_rerun_materialized_partition(self) -> None:
        context = _FakeContext(partitions=ADJ_FACTOR_REGISTERED_DAYS)
        with patch(
            "orchestrator.defs.sensors.stock_adj_factor_sensor.datetime",
            _FixedDateTime,
        ), patch(
            "orchestrator.defs.sensors.stock_adj_factor_sensor.batch_raw_adj_factor_lake_readiness",
            return_value=_batch_status(
                ready_dates=("2026-06-03", "2026-06-04"),
                failed_dates=("2026-06-05",),
            ),
        ):
            result = _raw_sensor_result(context)

        self.assertEqual(result.run_requests, [])
        self.assertIn("不自动重跑", result.skip_reason.skip_message)

    def test_raw_and_silver_run_request_contracts(self) -> None:
        raw_request = _raw_run_request_for_trade_date("2026-06-05")
        self.assertEqual(raw_request.partition_key, "2026-06-05")
        self.assertEqual(raw_request.run_key, "raw_adj_factor_update:2026-06-05")
        self.assertEqual(raw_request.tags, {})
        self.assertEqual(raw_request.run_config, {})

        silver_request = _silver_run_request_for_trade_date("2026-06-05")
        self.assertEqual(silver_request.partition_key, "2026-06-05")
        self.assertEqual(silver_request.run_key, "silver_adj_factor_update:2026-06-05")
        self.assertEqual(silver_request.tags, {})
        self.assertEqual(silver_request.run_config, {})

    def test_silver_sensor_skips_when_raw_missing_or_checks_not_ready(self) -> None:
        cases = (
            _batch_status(
                ready_dates=("2026-06-03", "2026-06-04"),
                missing_dates=("2026-06-05",),
            ),
            _batch_status(
                ready_dates=("2026-06-03", "2026-06-04"),
                failed_dates=("2026-06-05",),
            ),
        )
        for raw_batch_status in cases:
            raw_target_status = raw_batch_status.status_for_trade_date("2026-06-05")
            with self.subTest(reason=raw_target_status.reason):
                context = _FakeContext(partitions=ADJ_FACTOR_REGISTERED_DAYS)
                with patch(
                    "orchestrator.defs.sensors.stock_adj_factor_sensor.datetime",
                    _FixedDateTime,
                ), patch(
                    "orchestrator.defs.sensors.stock_adj_factor_sensor.batch_raw_adj_factor_lake_readiness",
                    return_value=raw_batch_status,
                ), patch(
                    "orchestrator.defs.sensors.stock_adj_factor_sensor.batch_silver_adj_factor_lake_readiness",
                    return_value=_batch_status(
                        ready_dates=("2026-06-03", "2026-06-04"),
                        missing_dates=("2026-06-05",),
                    ),
                ):
                    result = _silver_sensor_result(context)

                self.assertEqual(result.run_requests, [])
                if raw_target_status.materialized:
                    self.assertIn("不自动推进 silver", result.skip_reason.skip_message)
                else:
                    self.assertIn(
                        "raw readiness 门禁未满足",
                        result.skip_reason.skip_message,
                    )
                cursor_payload = load_sensor_cursor(result.cursor)
                details = cursor_payload["details"]["readiness_details"]
                self.assertFalse(details["raw_tushare_adj_factor"]["ready"])

    def test_silver_sensor_skips_when_stock_basic_not_ready(self) -> None:
        context = _FakeContext(partitions=ADJ_FACTOR_REGISTERED_DAYS)
        with patch(
            "orchestrator.defs.sensors.stock_adj_factor_sensor.datetime",
            _FixedDateTime,
        ), patch(
            "orchestrator.defs.sensors.stock_adj_factor_sensor.batch_raw_adj_factor_lake_readiness",
            return_value=_batch_status(ready_dates=ADJ_FACTOR_REGISTERED_DAYS),
        ), patch(
            "orchestrator.defs.sensors.stock_adj_factor_sensor.batch_silver_adj_factor_lake_readiness",
            return_value=_batch_status(
                ready_dates=("2026-06-03", "2026-06-04"),
                missing_dates=("2026-06-05",),
            ),
        ), patch(
            "orchestrator.defs.sensors.stock_adj_factor_sensor.stock_basic_ready_without_freshness",
            return_value=_stock_basic_status(ready=False),
        ):
            result = _silver_sensor_result(context)

        self.assertEqual(result.run_requests, [])
        self.assertIn("股票基础信息尚未通过", result.skip_reason.skip_message)
        cursor_payload = load_sensor_cursor(result.cursor)
        self.assertFalse(
            cursor_payload["details"]["stock_basic_freshness_required"]
        )
        self.assertIn("stock_basic", cursor_payload["details"]["readiness_details"])

    def test_silver_sensor_skips_when_stock_lifecycle_not_ready(self) -> None:
        context = _FakeContext(partitions=ADJ_FACTOR_REGISTERED_DAYS)
        with patch(
            "orchestrator.defs.sensors.stock_adj_factor_sensor.datetime",
            _FixedDateTime,
        ), patch(
            "orchestrator.defs.sensors.stock_adj_factor_sensor.batch_raw_adj_factor_lake_readiness",
            return_value=_batch_status(ready_dates=ADJ_FACTOR_REGISTERED_DAYS),
        ), patch(
            "orchestrator.defs.sensors.stock_adj_factor_sensor.batch_silver_adj_factor_lake_readiness",
            return_value=_batch_status(
                ready_dates=("2026-06-03", "2026-06-04"),
                missing_dates=("2026-06-05",),
            ),
        ), patch(
            "orchestrator.defs.sensors.stock_adj_factor_sensor.stock_basic_ready_without_freshness",
            return_value=_stock_basic_status(ready=True),
        ), patch(
            "orchestrator.defs.sensors.stock_adj_factor_sensor.silver_stock_lifecycle_ready_without_freshness",
            return_value=_stock_basic_status(ready=False),
        ):
            result = _silver_sensor_result(context)

        self.assertEqual(result.run_requests, [])
        self.assertIn("股票生命周期事实尚未通过", result.skip_reason.skip_message)

    def test_silver_sensor_submits_only_when_raw_stock_basic_and_lifecycle_ready(
        self,
    ) -> None:
        context = _FakeContext(partitions=ADJ_FACTOR_REGISTERED_DAYS)
        with patch(
            "orchestrator.defs.sensors.stock_adj_factor_sensor.datetime",
            _FixedDateTime,
        ), patch(
            "orchestrator.defs.sensors.stock_adj_factor_sensor.batch_raw_adj_factor_lake_readiness",
            return_value=_batch_status(ready_dates=ADJ_FACTOR_REGISTERED_DAYS),
        ), patch(
            "orchestrator.defs.sensors.stock_adj_factor_sensor.batch_silver_adj_factor_lake_readiness",
            return_value=_batch_status(
                ready_dates=("2026-06-03", "2026-06-04"),
                missing_dates=("2026-06-05",),
            ),
        ), patch(
            "orchestrator.defs.sensors.stock_adj_factor_sensor.stock_basic_ready_without_freshness",
            return_value=_stock_basic_status(ready=True),
        ), patch(
            "orchestrator.defs.sensors.stock_adj_factor_sensor.silver_stock_lifecycle_ready_without_freshness",
            return_value=_stock_basic_status(ready=True),
        ):
            result = _silver_sensor_result(context)

        self.assertEqual(len(result.run_requests), 1)
        request = result.run_requests[0]
        self.assertEqual(request.partition_key, "2026-06-05")
        self.assertEqual(request.run_key, "silver_adj_factor_update:2026-06-05")
        cursor_payload = load_sensor_cursor(result.cursor)
        self.assertFalse(
            cursor_payload["details"]["stock_basic_freshness_required"]
        )

    def test_silver_sensor_does_not_rerun_materialized_partition(self) -> None:
        context = _FakeContext(partitions=ADJ_FACTOR_REGISTERED_DAYS)
        with patch(
            "orchestrator.defs.sensors.stock_adj_factor_sensor.datetime",
            _FixedDateTime,
        ), patch(
            "orchestrator.defs.sensors.stock_adj_factor_sensor.batch_raw_adj_factor_lake_readiness",
            return_value=_batch_status(ready_dates=ADJ_FACTOR_REGISTERED_DAYS),
        ), patch(
            "orchestrator.defs.sensors.stock_adj_factor_sensor.batch_silver_adj_factor_lake_readiness",
            return_value=_batch_status(
                ready_dates=("2026-06-03", "2026-06-04"),
                failed_dates=("2026-06-05",),
            ),
        ):
            result = _silver_sensor_result(context)

        self.assertEqual(result.run_requests, [])
        self.assertIn("不自动重跑", result.skip_reason.skip_message)

    def test_legacy_silver_sensor_cases_removed(self) -> None:
        self.assertNotIn(
            "raw_tushare_adj_factor_ready_for_trade_date",
            Path(adj_factor_sensor_module.__file__).read_text(),
        )
        self.assertNotIn(
            "materialized_partition_keys",
            Path(adj_factor_sensor_module.__file__).read_text(),
        )

if __name__ == "__main__":
    unittest.main()
