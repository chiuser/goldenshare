"""No real instance, Lake or source is used in scheduling tests."""

import json
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock, patch

import dagster as dg
import pytest

from orchestrator.defs.asset_guards.daily_basic_readiness import DailyBasicReadiness
from orchestrator.defs.daily_basic_contract import (
    DAILY_BASIC_PARTITIONS,
    DailyBasicValidationError,
)
from orchestrator.defs.run_contracts.cursor_payloads import build_cursor_details
from orchestrator.defs.run_contracts.cursors import build_sensor_cursor
from orchestrator.defs.sensors.daily_basic_sensor import (
    evaluate_daily_basic,
    raw_tushare_daily_basic_update_job_sensor,
)
from orchestrator.defs.sensors.daily_basic_trade_day_sensor import (
    daily_basic_trade_day_sensor,
)
from orchestrator.defs.sensors.readiness import CN_A_SENSOR_TIMEZONE
from orchestrator.defs.source_readiness.daily_basic import DailyBasicSourceStatus
from tests.test_daily_basic_raw_io import DB

MODULE = "orchestrator.defs.sensors.daily_basic_sensor"
DAY = "2026-09-14"


def evaluate(
    tmp_path,
    *,
    hour=19,
    day=DAY,
    registered=True,
    reason="missing_materialization",
    runs=(),
    source_ready=True,
    upstream=True,
    truncated=False,
):
    context = SimpleNamespace(
        instance=Mock(),
        resources=SimpleNamespace(
            lake_root=SimpleNamespace(
                root=lambda: tmp_path, ensure_available_for_run=lambda: None
            ),
            duckdb=DB(),
            tushare=Mock(),
        ),
    )
    context.instance.get_dynamic_partitions.return_value = [day] if registered else []
    context.instance.get_runs.return_value = runs
    with (
        patch(
            MODULE + ".load_expected_trade_date_window",
            return_value=SimpleNamespace(expected_trade_dates=(day,)),
        ),
        patch(
            MODULE + ".batch_daily_basic_readiness",
            side_effect=DailyBasicValidationError("materialization_query_truncated")
            if truncated
            else None,
            return_value={
                day: DailyBasicReadiness(
                    reason == "ready", reason != "missing_materialization", reason
                )
            },
        ),
        patch(
            MODULE + ".load_daily_basic_input_codes",
            return_value=["000001.SZ"],
            side_effect=None if upstream else OSError("missing"),
        ),
        patch(
            MODULE + ".probe_daily_basic_for_trade_date",
            return_value=DailyBasicSourceStatus(
                source_ready,
                "ready" if source_ready else "source_missing_codes",
                missing_count=1,
            ),
        ) as probe,
    ):
        result = evaluate_daily_basic(
            context, datetime(2026, 9, 14, hour, 0, tzinfo=CN_A_SENSOR_TIMEZONE)
        )
    assert len(result.cursor.encode()) < 2048
    return result, probe


def test_request_once_stable_key(tmp_path):
    result, probe = evaluate(tmp_path)
    assert len(result.run_requests) == 1
    assert result.run_requests[0].run_key == "daily_basic:2026-09-14"
    assert result.run_requests[0].run_config["ops"]["raw_tushare_daily_basic"][
        "config"
    ] == {"write_mode": "write_new"}
    probe.assert_called_once()


@pytest.mark.parametrize(
    "kwargs,reason",
    [
        ({"hour": 18}, "before_update_window"),
        ({"registered": False}, "missing_registered_partition"),
        ({"reason": "check_failed_or_stale"}, "check_failed_or_stale"),
        ({"reason": "ready"}, "all_ready"),
        ({"runs": [object()]}, "existing_run"),
        ({"upstream": False}, "upstream_not_ready"),
        ({"truncated": True}, "readiness_query_incomplete"),
    ],
)
def test_skips_do_not_probe(tmp_path, kwargs, reason):
    result, probe = evaluate(tmp_path, **kwargs)
    assert not result.run_requests
    assert json.loads(result.cursor)["details"]["reason_code"] == reason
    probe.assert_not_called()


def test_source_gap_rechecks_same_key_and_historical_window(tmp_path):
    result, probe = evaluate(tmp_path, source_ready=False)
    assert not result.run_requests
    assert (
        json.loads(result.cursor)["details"]["blocked_component"]
        == "tushare_daily_basic_source"
    )
    probe.assert_called_once()
    assert evaluate(tmp_path, hour=18, day="2026-09-11")[0].run_requests


def test_registration_delegates_approved_contract():
    with (
        patch(
            "orchestrator.defs.sensors.daily_basic_trade_day_sensor.build_trade_day_partition_registration_result",
            return_value=dg.SensorResult(
                skip_reason="当前日期已注册。",
                cursor=build_sensor_cursor(
                    evaluated_at=datetime(2026, 9, 14, 19, tzinfo=CN_A_SENSOR_TIMEZONE),
                    decision="skip",
                    details=build_cursor_details(
                        sensor_name="daily_basic_trade_day_sensor",
                        job_name=None,
                        asset_family="daily_basic",
                        partition_set=DAILY_BASIC_PARTITIONS,
                        reason_code="all_registered",
                        blocked_component="none",
                        summary="all registered",
                        next_action="wait",
                    ),
                ),
            ),
        ) as helper,
        dg.build_sensor_context(
            resources={"lake_root": object(), "duckdb": object()}
        ) as context,
    ):
        daily_basic_trade_day_sensor.evaluate_tick(context)
    kwargs = helper.call_args.kwargs
    assert kwargs["min_trade_date"] == "2010-01-04"
    assert kwargs["dynamic_partitions"].name == DAILY_BASIC_PARTITIONS
    assert kwargs["same_day_register_start"].hour == 17
    assert (
        raw_tushare_daily_basic_update_job_sensor.default_status
        == dg.DefaultSensorStatus.STOPPED
    )
    assert daily_basic_trade_day_sensor.default_status == dg.DefaultSensorStatus.STOPPED
    assert raw_tushare_daily_basic_update_job_sensor.minimum_interval_seconds == 900


def test_registration_real_calendar_bounds_and_two_keys(tmp_path):
    from orchestrator.defs.paths import silver_trade_calendar_path

    calendar = silver_trade_calendar_path(tmp_path)
    calendar.parent.mkdir(parents=True)
    with DB().connect() as connection:
        connection.execute(
            "COPY (SELECT * FROM (VALUES ('SSE',DATE '2009-12-31',true),('SSE',DATE '2010-01-04',true),('SSE',DATE '2026-09-11',true),('SSE',DATE '2026-09-14',true),('SSE',DATE '2026-09-13',false),('SZSE',DATE '2026-09-12',true)) t(exchange,trade_date,is_open)) TO ? (FORMAT PARQUET)",
            [str(calendar)],
        )
    context = SimpleNamespace(
        instance=Mock(),
        log=Mock(),
        resources=SimpleNamespace(
            lake_root=SimpleNamespace(
                root=lambda: tmp_path, ensure_available_for_run=lambda: None
            ),
            duckdb=DB(),
        ),
    )
    context.instance.get_dynamic_partitions.return_value = []
    with patch(
        "orchestrator.defs.sensors.cn_a_trade_day_sensor.datetime", wraps=datetime
    ) as clock:
        clock.now.return_value = datetime(2026, 9, 14, 18, tzinfo=CN_A_SENSOR_TIMEZONE)
        result = daily_basic_trade_day_sensor._raw_fn(context)
    assert not result.run_requests
    keys = result.dynamic_partitions_requests[0].partition_keys
    assert len(keys) == 2
    assert "2009-12-31" not in keys and "2026-09-13" not in keys
    assert "注册2个" in json.loads(result.cursor)["details"]["summary"]
    context.instance.get_dynamic_partitions.return_value = ["2010-01-04", "2026-09-11"]
    with patch(
        "orchestrator.defs.sensors.cn_a_trade_day_sensor.datetime", wraps=datetime
    ) as clock:
        clock.now.return_value = datetime(2026, 9, 14, 16, tzinfo=CN_A_SENSOR_TIMEZONE)
        result = daily_basic_trade_day_sensor._raw_fn(context)
    assert not result.dynamic_partitions_requests
    assert "17:00" in json.loads(result.cursor)["details"]["summary"]
