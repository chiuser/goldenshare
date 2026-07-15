import json
import unittest
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from orchestrator.defs.asset_guards.bounded_continuity import (
    ContinuityBatchReadiness,
    ContinuityDateReadiness,
)
from orchestrator.defs.paths import (
    silver_stock_identity_map_path,
    silver_trade_calendar_path,
)
from orchestrator.defs.resources import DuckDBResource, LakeRootResource
from orchestrator.defs.run_contracts.sensor_tags import (
    SENSOR_DOMAIN_TAG,
    SENSOR_ROLE_TAG,
    SENSOR_TARGET_LAYER_TAG,
)
from orchestrator.defs.sensors import stk_nineturn_sensor as sensor_module
from orchestrator.defs.sensors.stk_nineturn_sensor import (
    raw_stk_nineturn_update_job_sensor,
    silver_stock_nineturn_daily_update_job_sensor,
)
from orchestrator.defs.partitions import cn_a_stk_nineturn_trade_days


TRADE_DATES = ("2026-07-07", "2026-07-08", "2026-07-09")


class _FakeInstance:
    def __init__(self, partitions: tuple[str, ...]) -> None:
        self._partitions = partitions

    def get_dynamic_partitions(self, _name: str) -> list[str]:
        return list(self._partitions)


class _Context:
    def __init__(self, root: Path, partitions: tuple[str, ...]) -> None:
        self.instance = _FakeInstance(partitions)
        self.resources = SimpleNamespace(
            lake_root=LakeRootResource(root_path=str(root)),
            duckdb=DuckDBResource(),
        )


class _BeforeWindowDateTime(datetime):
    @classmethod
    def now(cls, tz=None):  # noqa: ANN001
        return datetime(2026, 7, 9, 21, 0, tzinfo=tz or UTC)


class _AfterWindowDateTime(datetime):
    @classmethod
    def now(cls, tz=None):  # noqa: ANN001
        return datetime(2026, 7, 9, 21, 30, tzinfo=tz or UTC)


def _write_calendar(root: Path) -> None:
    path = silver_trade_calendar_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with DuckDBResource().connect() as connection:
        connection.execute(
            """
            CREATE TEMP TABLE calendar_rows (
              exchange VARCHAR,
              trade_date DATE,
              is_open BOOLEAN
            )
            """
        )
        connection.executemany(
            "INSERT INTO calendar_rows VALUES ('SSE', ?, true)",
            [(trade_date,) for trade_date in TRADE_DATES],
        )
        connection.execute(
            f"COPY calendar_rows TO '{path.as_posix()}' (FORMAT PARQUET)"
        )


def _write_identity_placeholder(root: Path) -> None:
    path = silver_stock_identity_map_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with DuckDBResource().connect() as connection:
        connection.execute(
            """
            COPY (
              SELECT
                '600030.SH'::VARCHAR AS latest_ts_code,
                '600030.SH'::VARCHAR AS source_ts_code,
                DATE '1990-01-01' AS valid_from,
                NULL::DATE AS valid_to
            ) TO ? (FORMAT PARQUET)
            """,
            [str(path)],
        )


def _status(
    trade_date: str,
    *,
    ready: bool,
    materialized: bool,
    reason: str,
) -> ContinuityDateReadiness:
    return ContinuityDateReadiness(
        trade_date=trade_date,
        ready=ready,
        materialized=materialized,
        checks_passed=ready,
        reason=reason,
        failed_check_names=("blocking_check",)
        if materialized and not ready
        else (),
        missing_check_names=("blocking_check",)
        if not materialized and not ready
        else (),
    )


def _batch(
    statuses: tuple[ContinuityDateReadiness, ...],
) -> ContinuityBatchReadiness:
    return ContinuityBatchReadiness(
        expected_trade_dates=tuple(status.trade_date for status in statuses),
        statuses_by_trade_date={status.trade_date: status for status in statuses},
        elapsed_ms=5,
        scanned_file_count=len(statuses),
    )


def _ready_batch(trade_dates: tuple[str, ...] = TRADE_DATES) -> ContinuityBatchReadiness:
    return _batch(
        tuple(
            _status(
                trade_date,
                ready=True,
                materialized=True,
                reason="ready",
            )
            for trade_date in trade_dates
        )
    )


class StkNineturnSensorTests(unittest.TestCase):
    def _root_and_context(
        self,
        temporary_dir: str,
        partitions: tuple[str, ...] = TRADE_DATES,
    ) -> tuple[Path, _Context]:
        root = Path(temporary_dir)
        for layer in ("raw", "silver", "gold"):
            (root / layer).mkdir(parents=True, exist_ok=True)
        _write_calendar(root)
        return root, _Context(root, partitions)

    def test_sensor_definitions_keep_stable_jobs_windows_and_tags(self) -> None:
        self.assertEqual(
            raw_stk_nineturn_update_job_sensor.job_name,
            "raw_stk_nineturn_update_job",
        )
        self.assertEqual(
            silver_stock_nineturn_daily_update_job_sensor.job_name,
            "silver_stock_nineturn_daily_update_job",
        )
        for sensor, target_layer in (
            (raw_stk_nineturn_update_job_sensor, "raw"),
            (silver_stock_nineturn_daily_update_job_sensor, "silver"),
        ):
            self.assertEqual(sensor.default_status.value, "STOPPED")
            self.assertEqual(sensor.minimum_interval_seconds, 600)
            self.assertEqual(sensor.tags[SENSOR_DOMAIN_TAG], "quote_data")
            self.assertEqual(sensor.tags[SENSOR_TARGET_LAYER_TAG], target_layer)
            self.assertEqual(sensor.tags[SENSOR_ROLE_TAG], "asset_update")

    def test_raw_registered_gap_skips_without_batch_scan(self) -> None:
        with TemporaryDirectory() as temporary_dir:
            _root, context = self._root_and_context(
                temporary_dir,
                partitions=(TRADE_DATES[0], TRADE_DATES[2]),
            )
            with (
                patch.object(sensor_module, "datetime", _AfterWindowDateTime),
                patch.object(
                    sensor_module,
                    "batch_raw_stk_nineturn_lake_readiness",
                ) as batch_helper,
            ):
                result = raw_stk_nineturn_update_job_sensor._raw_fn(context)

            batch_helper.assert_not_called()
            self.assertEqual(result.run_requests, [])
            details = json.loads(result.cursor)["details"]
            self.assertEqual(details["reason_code"], "missing_registered_partition")
            self.assertEqual(
                details["partition_set"],
                cn_a_stk_nineturn_trade_days.name,
            )
            self.assertEqual(
                details["blocked_component"],
                cn_a_stk_nineturn_trade_days.name,
            )
            self.assertEqual(details["frontier"]["first_missing_registered_date"], TRADE_DATES[1])

    def test_raw_before_window_skips_without_batch_scan(self) -> None:
        with TemporaryDirectory() as temporary_dir:
            _root, context = self._root_and_context(temporary_dir)
            with (
                patch.object(sensor_module, "datetime", _BeforeWindowDateTime),
                patch.object(
                    sensor_module,
                    "batch_raw_stk_nineturn_lake_readiness",
                ) as batch_helper,
            ):
                result = raw_stk_nineturn_update_job_sensor._raw_fn(context)

            batch_helper.assert_not_called()
            self.assertEqual(result.run_requests, [])
            self.assertEqual(
                json.loads(result.cursor)["details"]["reason_code"],
                "run_window_not_started",
            )

    def test_raw_submits_first_missing_file_only(self) -> None:
        batch = _batch(
            (
                _status(TRADE_DATES[0], ready=True, materialized=True, reason="ready"),
                _status(
                    TRADE_DATES[1],
                    ready=False,
                    materialized=False,
                    reason="raw_stk_nineturn_file_missing",
                ),
                _status(
                    TRADE_DATES[2],
                    ready=False,
                    materialized=False,
                    reason="raw_stk_nineturn_file_missing",
                ),
            )
        )
        with TemporaryDirectory() as temporary_dir:
            _root, context = self._root_and_context(temporary_dir)
            with (
                patch.object(sensor_module, "datetime", _AfterWindowDateTime),
                patch.object(
                    sensor_module,
                    "batch_raw_stk_nineturn_lake_readiness",
                    return_value=batch,
                ),
            ):
                result = raw_stk_nineturn_update_job_sensor._raw_fn(context)

            self.assertEqual(len(result.run_requests), 1)
            request = result.run_requests[0]
            self.assertEqual(request.partition_key, TRADE_DATES[1])
            self.assertEqual(
                request.run_key,
                f"raw_stk_nineturn_update:{TRADE_DATES[1]}",
            )
            self.assertLess(len(result.cursor.encode("utf-8")), 2048)

    def test_raw_materialized_check_failure_does_not_rerun(self) -> None:
        batch = _batch(
            (
                _status(
                    TRADE_DATES[0],
                    ready=False,
                    materialized=True,
                    reason="raw_stk_nineturn_checks_failed",
                ),
                *_ready_batch(TRADE_DATES[1:]).statuses_by_trade_date.values(),
            )
        )
        with TemporaryDirectory() as temporary_dir:
            _root, context = self._root_and_context(temporary_dir)
            with (
                patch.object(sensor_module, "datetime", _AfterWindowDateTime),
                patch.object(
                    sensor_module,
                    "batch_raw_stk_nineturn_lake_readiness",
                    return_value=batch,
                ),
            ):
                result = raw_stk_nineturn_update_job_sensor._raw_fn(context)

            self.assertEqual(result.run_requests, [])
            self.assertEqual(
                json.loads(result.cursor)["details"]["reason_code"],
                "materialized_check_failed",
            )

    def test_raw_all_ready_skips_with_ready_frontier(self) -> None:
        with TemporaryDirectory() as temporary_dir:
            _root, context = self._root_and_context(temporary_dir)
            with (
                patch.object(sensor_module, "datetime", _AfterWindowDateTime),
                patch.object(
                    sensor_module,
                    "batch_raw_stk_nineturn_lake_readiness",
                    return_value=_ready_batch(),
                ),
            ):
                result = raw_stk_nineturn_update_job_sensor._raw_fn(context)

            self.assertEqual(result.run_requests, [])
            details = json.loads(result.cursor)["details"]
            self.assertEqual(details["reason_code"], "all_ready")
            self.assertEqual(
                details["frontier"]["ready_through_date"],
                TRADE_DATES[-1],
            )

    def test_silver_identity_missing_skips_before_silver_batch(self) -> None:
        with TemporaryDirectory() as temporary_dir:
            _root, context = self._root_and_context(temporary_dir)
            with (
                patch.object(sensor_module, "datetime", _AfterWindowDateTime),
                patch.object(
                    sensor_module,
                    "batch_raw_stk_nineturn_lake_readiness",
                    return_value=_ready_batch(),
                ),
                patch.object(
                    sensor_module,
                    "batch_silver_stock_nineturn_daily_lake_readiness",
                ) as silver_helper,
            ):
                result = silver_stock_nineturn_daily_update_job_sensor._raw_fn(context)

            silver_helper.assert_not_called()
            self.assertEqual(result.run_requests, [])
            self.assertEqual(
                json.loads(result.cursor)["details"]["reason_code"],
                "identity_mapping_missing",
            )

    def test_silver_raw_first_date_not_ready_skips_without_silver_batch(self) -> None:
        raw_batch = _batch(
            (
                _status(
                    TRADE_DATES[0],
                    ready=False,
                    materialized=False,
                    reason="raw_stk_nineturn_file_missing",
                ),
                *_ready_batch(TRADE_DATES[1:]).statuses_by_trade_date.values(),
            )
        )
        with TemporaryDirectory() as temporary_dir:
            root, context = self._root_and_context(temporary_dir)
            _write_identity_placeholder(root)
            with (
                patch.object(sensor_module, "datetime", _AfterWindowDateTime),
                patch.object(
                    sensor_module,
                    "batch_raw_stk_nineturn_lake_readiness",
                    return_value=raw_batch,
                ),
                patch.object(
                    sensor_module,
                    "batch_silver_stock_nineturn_daily_lake_readiness",
                ) as silver_helper,
            ):
                result = silver_stock_nineturn_daily_update_job_sensor._raw_fn(context)

            silver_helper.assert_not_called()
            self.assertEqual(result.run_requests, [])

    def test_silver_can_fill_gap_before_later_raw_frontier(self) -> None:
        raw_batch = _batch(
            (
                *_ready_batch(TRADE_DATES[:2]).statuses_by_trade_date.values(),
                _status(
                    TRADE_DATES[2],
                    ready=False,
                    materialized=False,
                    reason="raw_stk_nineturn_file_missing",
                ),
            )
        )
        silver_batch = _batch(
            (
                _status(TRADE_DATES[0], ready=True, materialized=True, reason="ready"),
                _status(
                    TRADE_DATES[1],
                    ready=False,
                    materialized=False,
                    reason="silver_stock_nineturn_daily_file_missing",
                ),
            )
        )
        with TemporaryDirectory() as temporary_dir:
            root, context = self._root_and_context(temporary_dir)
            _write_identity_placeholder(root)
            with (
                patch.object(sensor_module, "datetime", _AfterWindowDateTime),
                patch.object(
                    sensor_module,
                    "batch_raw_stk_nineturn_lake_readiness",
                    return_value=raw_batch,
                ),
                patch.object(
                    sensor_module,
                    "batch_silver_stock_nineturn_daily_lake_readiness",
                    return_value=silver_batch,
                ) as silver_helper,
            ):
                result = silver_stock_nineturn_daily_update_job_sensor._raw_fn(context)

            self.assertEqual(
                silver_helper.call_args.kwargs["expected_trade_dates"],
                TRADE_DATES[:2],
            )
            self.assertEqual(len(result.run_requests), 1)
            self.assertEqual(result.run_requests[0].partition_key, TRADE_DATES[1])
            self.assertEqual(
                result.run_requests[0].run_key,
                f"silver_stock_nineturn_daily_update:{TRADE_DATES[1]}",
            )

    def test_silver_mapping_problem_is_not_submitted(self) -> None:
        silver_batch = _batch(
            (
                _status(
                    TRADE_DATES[0],
                    ready=False,
                    materialized=False,
                    reason="identity_mapping_not_ready",
                ),
                *_ready_batch(TRADE_DATES[1:]).statuses_by_trade_date.values(),
            )
        )
        with TemporaryDirectory() as temporary_dir:
            root, context = self._root_and_context(temporary_dir)
            _write_identity_placeholder(root)
            with (
                patch.object(sensor_module, "datetime", _AfterWindowDateTime),
                patch.object(
                    sensor_module,
                    "batch_raw_stk_nineturn_lake_readiness",
                    return_value=_ready_batch(),
                ),
                patch.object(
                    sensor_module,
                    "batch_silver_stock_nineturn_daily_lake_readiness",
                    return_value=silver_batch,
                ),
            ):
                result = silver_stock_nineturn_daily_update_job_sensor._raw_fn(context)

            self.assertEqual(result.run_requests, [])
            self.assertEqual(
                json.loads(result.cursor)["details"]["reason_code"],
                "identity_mapping_not_ready",
            )

    def test_silver_materialized_check_failure_does_not_rerun(self) -> None:
        silver_batch = _batch(
            (
                _status(
                    TRADE_DATES[0],
                    ready=False,
                    materialized=True,
                    reason="silver_stock_nineturn_daily_checks_failed",
                ),
                *_ready_batch(TRADE_DATES[1:]).statuses_by_trade_date.values(),
            )
        )
        with TemporaryDirectory() as temporary_dir:
            root, context = self._root_and_context(temporary_dir)
            _write_identity_placeholder(root)
            with (
                patch.object(sensor_module, "datetime", _AfterWindowDateTime),
                patch.object(
                    sensor_module,
                    "batch_raw_stk_nineturn_lake_readiness",
                    return_value=_ready_batch(),
                ),
                patch.object(
                    sensor_module,
                    "batch_silver_stock_nineturn_daily_lake_readiness",
                    return_value=silver_batch,
                ),
            ):
                result = silver_stock_nineturn_daily_update_job_sensor._raw_fn(context)

            self.assertEqual(result.run_requests, [])
            self.assertEqual(
                json.loads(result.cursor)["details"]["reason_code"],
                "materialized_check_failed",
            )
            self.assertLess(len(result.cursor.encode("utf-8")), 3072)


if __name__ == "__main__":
    unittest.main()
