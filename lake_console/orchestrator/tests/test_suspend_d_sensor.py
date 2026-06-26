import ast
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from orchestrator.defs.assets.suspend_d import (
    _human_materialization_metadata,
    raw_tushare_suspend_d,
    silver_stock_suspend_daily,
)
from orchestrator.defs.asset_guards.bounded_continuity import (
    ContinuityExpectedDateWindow,
    build_registered_gap_status,
)
from orchestrator.defs.jobs import suspend_update as suspend_jobs
from orchestrator.defs.run_contracts.cursors import load_sensor_cursor
from orchestrator.defs.run_contracts.sensor_tags import (
    SENSOR_DOMAIN_TAG,
    SENSOR_ROLE_TAG,
    SENSOR_TARGET_LAYER_TAG,
)
from orchestrator.defs.sensors import suspend_d_sensor as suspend_sensor_module
from orchestrator.defs.sensors.readiness import (
    AssetReadinessStatus,
    RAW_SUSPEND_D_CHECKS,
    SILVER_SUSPEND_D_CHECKS,
)
from orchestrator.defs.sensors.suspend_d_sensor import (
    raw_suspend_d_update_job_sensor,
    silver_suspend_d_update_job_sensor,
)


ASSET_PATH = Path("src/orchestrator/defs/assets/suspend_d.py")


def _asset_description(asset_definition) -> str:  # noqa: ANN001
    descriptions = tuple(asset_definition.descriptions_by_key.values())
    return descriptions[0] if descriptions else ""


def _stdout_calls() -> list[ast.Call]:
    tree = ast.parse(ASSET_PATH.read_text(), filename=str(ASSET_PATH))
    calls: list[ast.Call] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Attribute) and node.func.attr == "stdout":
            calls.append(node)
    return calls


class _FakeInstance:
    def __init__(self, partitions: tuple[str, ...]) -> None:
        self._partitions = partitions

    def get_dynamic_partitions(self, _name: str) -> list[str]:
        return list(self._partitions)


class _FakeContext:
    def __init__(self, *, partitions: tuple[str, ...]) -> None:
        self.instance = _FakeInstance(partitions)


class _FixedDateTime(datetime):
    @classmethod
    def now(cls, tz=None):  # noqa: ANN001
        return datetime(2026, 6, 7, 10, 0, tzinfo=tz or UTC)


class _FixedDateTimeAfterGap(datetime):
    @classmethod
    def now(cls, tz=None):  # noqa: ANN001
        return datetime(2026, 6, 17, 10, 0, tzinfo=tz or UTC)


def _registered_gap(
    *,
    expected_trade_dates: tuple[str, ...],
    registered_trade_dates: tuple[str, ...],
    evaluated_at: datetime | None = None,
):
    expected_window = ContinuityExpectedDateWindow(
        expected_trade_dates=expected_trade_dates,
        min_trade_date="2014-01-01",
        max_trade_date=expected_trade_dates[-1] if expected_trade_dates else None,
        evaluated_at=evaluated_at or _FixedDateTime.now(UTC),
        window_limit=10,
    )
    return expected_window, build_registered_gap_status(
        expected_trade_dates=expected_trade_dates,
        registered_trade_dates=registered_trade_dates,
    )


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
        asset_key="raw_tushare_suspend_d",
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


def _raw_sensor_result(context: _FakeContext):
    return raw_suspend_d_update_job_sensor._raw_fn(context)


def _silver_sensor_result(context: _FakeContext):
    return silver_suspend_d_update_job_sensor._raw_fn(context)


class SuspendDSensorTests(unittest.TestCase):
    def setUp(self) -> None:
        self._registered_gap_patcher = patch(
            "orchestrator.defs.sensors.suspend_d_sensor._stock_trade_day_registered_gap",
            side_effect=lambda _context, evaluated_at, registered_keys: _registered_gap(
                expected_trade_dates=tuple(registered_keys),
                registered_trade_dates=tuple(registered_keys),
                evaluated_at=evaluated_at,
            ),
        )
        self.registered_gap_mock = self._registered_gap_patcher.start()

    def tearDown(self) -> None:
        self._registered_gap_patcher.stop()

    def test_job_and_sensor_names_follow_split_rule(self) -> None:
        self.assertTrue(hasattr(suspend_jobs, "raw_suspend_d_update_job"))
        self.assertTrue(hasattr(suspend_jobs, "silver_suspend_d_update_job"))
        self.assertFalse(hasattr(suspend_jobs, "suspend_update_job"))
        self.assertFalse(hasattr(suspend_sensor_module, "suspend_d_sensor"))
        self.assertEqual(
            suspend_jobs.raw_suspend_d_update_job.name,
            "raw_suspend_d_update_job",
        )
        self.assertEqual(
            suspend_jobs.silver_suspend_d_update_job.name,
            "silver_suspend_d_update_job",
        )
        self.assertEqual(
            raw_suspend_d_update_job_sensor.name,
            "raw_suspend_d_update_job_sensor",
        )
        self.assertEqual(
            silver_suspend_d_update_job_sensor.name,
            "silver_suspend_d_update_job_sensor",
        )
        self.assertEqual(
            raw_suspend_d_update_job_sensor.job_name,
            "raw_suspend_d_update_job",
        )
        self.assertEqual(
            silver_suspend_d_update_job_sensor.job_name,
            "silver_suspend_d_update_job",
        )
        raw_selection = repr(suspend_jobs.raw_suspend_d_update_job.selection)
        silver_selection = repr(suspend_jobs.silver_suspend_d_update_job.selection)
        self.assertIn("raw_tushare_suspend_d", raw_selection)
        self.assertNotIn("silver_stock_suspend_daily", raw_selection)
        self.assertIn("silver_stock_suspend_daily", silver_selection)
        self.assertNotIn("raw_tushare_suspend_d", silver_selection)

    def test_sensor_tags_are_layer_specific(self) -> None:
        self.assertEqual(
            raw_suspend_d_update_job_sensor.tags,
            {
                SENSOR_DOMAIN_TAG: "quote_data",
                SENSOR_TARGET_LAYER_TAG: "raw",
                SENSOR_ROLE_TAG: "asset_update",
            },
        )
        self.assertEqual(
            silver_suspend_d_update_job_sensor.tags,
            {
                SENSOR_DOMAIN_TAG: "quote_data",
                SENSOR_TARGET_LAYER_TAG: "silver",
                SENSOR_ROLE_TAG: "asset_update",
            },
        )

    def test_asset_descriptions_explain_business_purpose(self) -> None:
        descriptions = (
            _asset_description(raw_tushare_suspend_d),
            _asset_description(silver_stock_suspend_daily),
        )

        for description in descriptions:
            with self.subTest(description=description):
                self.assertRegex(description, r"[\u4e00-\u9fff]")
                self.assertNotIn("selection", description.lower())

        self.assertIn("源镜像", descriptions[0])
        self.assertIn("标准事实", descriptions[1])

    def test_suspend_d_stdout_events_are_small_and_named(self) -> None:
        calls = _stdout_calls()
        events = {
            call.args[0].value
            for call in calls
            if call.args
            and isinstance(call.args[0], ast.Constant)
            and isinstance(call.args[0].value, str)
        }

        self.assertEqual(
            {
                "raw_suspend_d_started",
                "raw_suspend_d_completed",
                "silver_suspend_d_started",
                "silver_suspend_d_validation_failed",
                "silver_suspend_d_completed",
            }
            - events,
            set(),
        )

        forbidden_stdout_fields = {
            "sql",
            "query",
            "dataframe",
            "df",
            "ts_codes",
            "sample_rows",
            "conflict_sample_rows",
            "duplicate_sample_rows",
        }
        issues = []
        for call in calls:
            keyword_names = {keyword.arg for keyword in call.keywords if keyword.arg}
            forbidden = keyword_names & forbidden_stdout_fields
            if forbidden:
                issues.append(f"stdout call writes forbidden fields {sorted(forbidden)}")

        self.assertEqual(issues, [])

    def test_human_materialization_metadata_uses_namespaced_operator_fields(
        self,
    ) -> None:
        metadata = _human_materialization_metadata(
            summary="已写入停复牌测试产物。",
            next_action="等待 checks。",
            result_status="written",
            input_summary={"source": "test"},
            filter_summary={"output_row_count": 1},
            diagnostic_ref="看 run stdout。",
        )

        self.assertEqual(metadata["goldenshare/summary"], "已写入停复牌测试产物。")
        self.assertEqual(metadata["goldenshare/next_action"], "等待 checks。")
        self.assertEqual(metadata["goldenshare/result_status"], "written")
        self.assertEqual(metadata["goldenshare/input_summary"], {"source": "test"})
        self.assertEqual(
            metadata["goldenshare/filter_summary"],
            {"output_row_count": 1},
        )
        self.assertEqual(metadata["goldenshare/diagnostic_ref"], "看 run stdout。")

    def test_existing_suspend_d_check_names_are_not_renamed(self) -> None:
        self.assertEqual(
            RAW_SUSPEND_D_CHECKS,
            (
                "raw_suspend_d_contract_check",
                "raw_suspend_d_partition_allowed_check",
            ),
        )
        self.assertEqual(
            SILVER_SUSPEND_D_CHECKS,
            (
                "silver_suspend_d_key_integrity_check",
                "silver_suspend_d_suspend_type_domain_check",
                "silver_suspend_d_partition_allowed_check",
            ),
        )
        self.assertNotIn("raw_suspend_d_required_columns", RAW_SUSPEND_D_CHECKS)
        self.assertNotIn("raw_suspend_d_row_count_positive", RAW_SUSPEND_D_CHECKS)

    def test_raw_sensor_submits_run_when_raw_missing(self) -> None:
        context = _FakeContext(partitions=("2026-06-05",))
        with patch(
            "orchestrator.defs.sensors.suspend_d_sensor.datetime",
            _FixedDateTime,
        ), patch(
            "orchestrator.defs.sensors.suspend_d_sensor.materialized_partition_keys",
            return_value=set(),
        ):
            result = _raw_sensor_result(context)

        self.assertEqual(len(result.run_requests), 1)
        request = result.run_requests[0]
        self.assertEqual(request.partition_key, "2026-06-05")
        self.assertEqual(request.run_key, "raw_suspend_d_update:2026-06-05")
        self.assertEqual(request.run_config, {})
        self.assertLess(len(result.cursor), 2000)
        cursor_payload = load_sensor_cursor(result.cursor)
        details = cursor_payload["details"]
        self.assertEqual(details["reason_code"], "request_run")
        self.assertEqual(details["blocked_component"], "none")
        self.assertIn("已触发", details["summary"])
        self.assertIn("raw_suspend_d_contract_check", details["next_action"])
        self.assertNotIn("status_samples", result.cursor)
        self.assertNotIn("raw_batch_status", result.cursor)

    def test_raw_sensor_skips_registered_gap_before_materialization_scan(self) -> None:
        context = _FakeContext(partitions=("2026-06-13", "2026-06-16"))
        self.registered_gap_mock.side_effect = (
            lambda _context, evaluated_at, registered_keys: _registered_gap(
                expected_trade_dates=("2026-06-13", "2026-06-15", "2026-06-16"),
                registered_trade_dates=tuple(registered_keys),
                evaluated_at=evaluated_at,
            )
        )
        with patch(
            "orchestrator.defs.sensors.suspend_d_sensor.datetime",
            _FixedDateTimeAfterGap,
        ), patch(
            "orchestrator.defs.sensors.suspend_d_sensor.materialized_partition_keys",
        ) as materialized_mock:
            result = _raw_sensor_result(context)

        self.assertEqual(result.run_requests, [])
        self.assertIn("最早缺失日期为 2026-06-15", result.skip_reason.skip_message)
        materialized_mock.assert_not_called()
        cursor_payload = load_sensor_cursor(result.cursor)
        self.assertEqual(cursor_payload["target_date"], "2026-06-15")
        details = cursor_payload["details"]
        self.assertEqual(details["blocked_component"], "cn_a_stock_trade_days")
        self.assertIn("分区存在缺口", details["summary"])
        self.assertIn("cn_a_stock_trade_days", details["next_action"])
        continuity = cursor_payload["details"]["frontier"]
        self.assertEqual(continuity["first_missing_registered_date"], "2026-06-15")

    def test_raw_sensor_does_not_rerun_materialized_partition(self) -> None:
        context = _FakeContext(partitions=("2026-06-05",))
        with patch(
            "orchestrator.defs.sensors.suspend_d_sensor.datetime",
            _FixedDateTime,
        ), patch(
            "orchestrator.defs.sensors.suspend_d_sensor.materialized_partition_keys",
            return_value={"2026-06-05"},
        ):
            result = _raw_sensor_result(context)

        self.assertEqual(result.run_requests, [])
        self.assertIn("raw 分区都已经生成完成", result.skip_reason.skip_message)
        self.assertLess(len(result.cursor), 2000)
        cursor_payload = load_sensor_cursor(result.cursor)
        details = cursor_payload["details"]
        self.assertEqual(details["reason_code"], "all_ready")
        self.assertEqual(details["blocked_component"], "none")
        self.assertIn("都已生成", details["summary"])
        self.assertIn("无需处理", details["next_action"])

    def test_silver_sensor_submits_only_when_raw_ready_and_silver_missing(
        self,
    ) -> None:
        context = _FakeContext(partitions=("2026-06-05",))
        with patch(
            "orchestrator.defs.sensors.suspend_d_sensor.datetime",
            _FixedDateTime,
        ), patch(
            "orchestrator.defs.sensors.suspend_d_sensor.materialized_partition_keys",
            return_value=set(),
        ), patch(
            "orchestrator.defs.sensors.suspend_d_sensor.raw_tushare_suspend_d_ready_for_trade_date",
            return_value=_raw_status(ready=True),
        ):
            result = _silver_sensor_result(context)

        self.assertEqual(len(result.run_requests), 1)
        request = result.run_requests[0]
        self.assertEqual(request.partition_key, "2026-06-05")
        self.assertEqual(request.run_key, "silver_suspend_d_update:2026-06-05")
        self.assertLess(len(result.cursor), 2000)
        cursor_payload = load_sensor_cursor(result.cursor)
        details = cursor_payload["details"]
        self.assertEqual(details["reason_code"], "request_run")
        self.assertEqual(details["blocked_component"], "none")
        self.assertIn("已触发", details["summary"])
        self.assertIn("silver suspend_d blocking checks", details["next_action"])
        self.assertNotIn("gate_statuses_by_trade_date", result.cursor)

    def test_silver_sensor_skips_registered_gap_before_readiness_scan(self) -> None:
        context = _FakeContext(partitions=("2026-06-13", "2026-06-16"))
        self.registered_gap_mock.side_effect = (
            lambda _context, evaluated_at, registered_keys: _registered_gap(
                expected_trade_dates=("2026-06-13", "2026-06-15", "2026-06-16"),
                registered_trade_dates=tuple(registered_keys),
                evaluated_at=evaluated_at,
            )
        )
        with patch(
            "orchestrator.defs.sensors.suspend_d_sensor.datetime",
            _FixedDateTimeAfterGap,
        ), patch(
            "orchestrator.defs.sensors.suspend_d_sensor.materialized_partition_keys",
        ) as materialized_mock, patch(
            "orchestrator.defs.sensors.suspend_d_sensor.raw_tushare_suspend_d_ready_for_trade_date",
        ) as raw_readiness_mock:
            result = _silver_sensor_result(context)

        self.assertEqual(result.run_requests, [])
        self.assertIn("最早缺失日期为 2026-06-15", result.skip_reason.skip_message)
        materialized_mock.assert_not_called()
        raw_readiness_mock.assert_not_called()
        cursor_payload = load_sensor_cursor(result.cursor)
        self.assertEqual(cursor_payload["target_date"], "2026-06-15")
        details = cursor_payload["details"]
        self.assertEqual(details["blocked_component"], "cn_a_stock_trade_days")
        self.assertIn("分区存在缺口", details["summary"])
        continuity = cursor_payload["details"]["frontier"]
        self.assertEqual(continuity["first_missing_registered_date"], "2026-06-15")

    def test_silver_sensor_skips_when_raw_missing_or_checks_not_ready(self) -> None:
        cases = (
            _raw_status(
                ready=False,
                materialized=False,
                missing_check_names=RAW_SUSPEND_D_CHECKS,
                reason="raw_tushare_suspend_d has no materialization",
            ),
            _raw_status(
                ready=False,
                missing_check_names=("raw_suspend_d_contract_check",),
                reason="raw_tushare_suspend_d missing blocking checks",
            ),
            _raw_status(
                ready=False,
                failed_check_names=("raw_suspend_d_contract_check",),
                reason="raw_tushare_suspend_d failed blocking checks",
            ),
        )
        for raw_status in cases:
            with self.subTest(reason=raw_status.reason):
                context = _FakeContext(partitions=("2026-06-05",))
                with patch(
                    "orchestrator.defs.sensors.suspend_d_sensor.datetime",
                    _FixedDateTime,
                ), patch(
                    "orchestrator.defs.sensors.suspend_d_sensor.materialized_partition_keys",
                    return_value=set(),
                ), patch(
                    "orchestrator.defs.sensors.suspend_d_sensor.raw_tushare_suspend_d_ready_for_trade_date",
                    return_value=raw_status,
                ):
                    result = _silver_sensor_result(context)

                self.assertEqual(result.run_requests, [])
                self.assertIn("raw readiness 门禁未满足", result.skip_reason.skip_message)
                cursor_payload = load_sensor_cursor(result.cursor)
                details = cursor_payload["details"]
                self.assertLess(len(result.cursor), 2000)
                self.assertEqual(details["reason_code"], "raw_not_ready")
                self.assertEqual(details["blocked_component"], "raw_tushare_suspend_d")
                self.assertIn("还没有 ready", details["summary"])
                self.assertIn("blocking checks", details["next_action"])
                self.assertFalse(
                    details["gate_statuses"]["raw_tushare_suspend_d"]["ready"]
                )

    def test_silver_sensor_does_not_rerun_materialized_partition(self) -> None:
        context = _FakeContext(partitions=("2026-06-05",))
        with patch(
            "orchestrator.defs.sensors.suspend_d_sensor.datetime",
            _FixedDateTime,
        ), patch(
            "orchestrator.defs.sensors.suspend_d_sensor.materialized_partition_keys",
            return_value={"2026-06-05"},
        ), patch(
            "orchestrator.defs.sensors.suspend_d_sensor.raw_tushare_suspend_d_ready_for_trade_date",
        ) as raw_readiness:
            result = _silver_sensor_result(context)

        self.assertEqual(result.run_requests, [])
        self.assertIn("silver 分区都已经生成完成", result.skip_reason.skip_message)
        raw_readiness.assert_not_called()
        cursor_payload = load_sensor_cursor(result.cursor)
        details = cursor_payload["details"]
        self.assertEqual(details["reason_code"], "all_ready")
        self.assertEqual(details["blocked_component"], "none")
        self.assertIn("silver 分区都已生成", details["summary"])


if __name__ == "__main__":
    unittest.main()
