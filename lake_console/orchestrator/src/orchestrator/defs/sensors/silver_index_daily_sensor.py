import json
from datetime import datetime
from pathlib import Path
from typing import Any

import dagster as dg

from orchestrator.defs.duckdb_sql import read_parquet
from orchestrator.defs.partitions import cn_a_index_trade_days, cn_a_index_ts_codes
from orchestrator.defs.paths import raw_index_daily_by_code_path
from orchestrator.defs.sensors.readiness import (
    AssetReadinessStatus,
    CN_A_SENSOR_TIMEZONE,
    raw_index_daily_by_code_ready_for_code,
    silver_index_daily_ready_for_trade_date,
)


MAX_STATUS_SAMPLE_COUNT = 20


def _asset_status_payload(status: AssetReadinessStatus) -> dict[str, object]:
    return {
        "asset_key": status.asset_key,
        "partition_key": status.partition_key,
        "ready": status.ready,
        "materialized": status.materialized,
        "checks_passed": status.checks_passed,
        "freshness_passed": status.freshness_passed,
        "materialization_storage_id": status.materialization_storage_id,
        "materialization_date": status.materialization_date,
        "missing_check_names": list(status.missing_check_names),
        "failed_check_names": list(status.failed_check_names),
        "reason": status.reason,
    }


def _latest_registered_trade_date(
    registered_trade_days: tuple[str, ...],
    evaluated_at: datetime,
) -> str | None:
    today = evaluated_at.date().isoformat()
    eligible_trade_days = tuple(
        trade_date for trade_date in registered_trade_days if trade_date <= today
    )
    return eligible_trade_days[-1] if eligible_trade_days else None


def _raw_by_code_has_trade_date(
    connection,
    raw_path: Path,
    compact_trade_date: str,
) -> bool:
    if not raw_path.exists():
        return False
    row = connection.execute(
        f"""
        SELECT count(*) > 0 AS has_trade_date
        FROM {read_parquet(raw_path, hive_partitioning=False)}
        WHERE CAST(trade_date AS VARCHAR) = ?
        """,
        [compact_trade_date],
    ).fetchone()
    return bool(row and row[0])


def _raw_file_date_presence(
    *,
    lake_root_path: Path,
    duckdb_resource,
    index_codes: tuple[str, ...],
    trade_date: str,
) -> dict[str, bool]:
    compact_trade_date = trade_date.replace("-", "")
    presence: dict[str, bool] = {}
    with duckdb_resource.connect() as connection:
        for index_code in index_codes:
            raw_path = raw_index_daily_by_code_path(lake_root_path, index_code)
            presence[index_code] = _raw_by_code_has_trade_date(
                connection,
                raw_path,
                compact_trade_date,
            )
    return presence


def _cursor_payload(
    *,
    evaluated_at: datetime,
    target_trade_date: str | None,
    registered_trade_day_count: int,
    registered_code_count: int,
    ready_code_count: int,
    missing_code_count: int,
    failed_check_code_count: int,
    selected_trade_date: str | None,
    silver_status: AssetReadinessStatus | None,
    missing_code_samples: tuple[str, ...],
    failed_check_samples: dict[str, dict[str, object]],
) -> str:
    payload = {
        "evaluated_at": evaluated_at.isoformat(),
        "target_trade_date": target_trade_date,
        "registered_trade_day_count": registered_trade_day_count,
        "registered_code_count": registered_code_count,
        "ready_code_count": ready_code_count,
        "missing_code_count": missing_code_count,
        "failed_check_code_count": failed_check_code_count,
        "selected_trade_date": selected_trade_date,
        "silver_status": _asset_status_payload(silver_status) if silver_status else None,
        "missing_code_samples": list(missing_code_samples),
        "failed_check_samples": failed_check_samples,
    }
    return json.dumps(payload, ensure_ascii=True, sort_keys=True)


@dg.sensor(
    job_name="silver_index_daily_update_job",
    default_status=dg.DefaultSensorStatus.STOPPED,
    minimum_interval_seconds=600,
    required_resource_keys={"lake_root", "duckdb"},
    description="指数日线 raw-by-code 全部 ready 后，触发 silver 分区生成任务。",
)
def silver_index_daily_sensor(context: dg.SensorEvaluationContext) -> dg.SensorResult:
    evaluated_at = datetime.now(CN_A_SENSOR_TIMEZONE)
    registered_trade_days = tuple(
        sorted(context.instance.get_dynamic_partitions(cn_a_index_trade_days.name))
    )
    registered_index_codes = tuple(
        sorted(context.instance.get_dynamic_partitions(cn_a_index_ts_codes.name))
    )

    if not registered_trade_days:
        cursor = _cursor_payload(
            evaluated_at=evaluated_at,
            target_trade_date=None,
            registered_trade_day_count=0,
            registered_code_count=len(registered_index_codes),
            ready_code_count=0,
            missing_code_count=0,
            failed_check_code_count=0,
            selected_trade_date=None,
            silver_status=None,
            missing_code_samples=(),
            failed_check_samples={},
        )
        return dg.SensorResult(
            skip_reason="没有注册指数交易日分区，无法触发指数日线 silver 生成。",
            cursor=cursor,
        )

    if not registered_index_codes:
        cursor = _cursor_payload(
            evaluated_at=evaluated_at,
            target_trade_date=None,
            registered_trade_day_count=len(registered_trade_days),
            registered_code_count=0,
            ready_code_count=0,
            missing_code_count=0,
            failed_check_code_count=0,
            selected_trade_date=None,
            silver_status=None,
            missing_code_samples=(),
            failed_check_samples={},
        )
        return dg.SensorResult(
            skip_reason="没有注册指数代码分区，无法触发指数日线 silver 生成。",
            cursor=cursor,
        )

    target_trade_date = _latest_registered_trade_date(registered_trade_days, evaluated_at)
    if target_trade_date is None:
        cursor = _cursor_payload(
            evaluated_at=evaluated_at,
            target_trade_date=None,
            registered_trade_day_count=len(registered_trade_days),
            registered_code_count=len(registered_index_codes),
            ready_code_count=0,
            missing_code_count=0,
            failed_check_code_count=0,
            selected_trade_date=None,
            silver_status=None,
            missing_code_samples=(),
            failed_check_samples={},
        )
        return dg.SensorResult(
            skip_reason="没有符合当前日期窗口的指数交易日分区。",
            cursor=cursor,
        )

    silver_status = silver_index_daily_ready_for_trade_date(
        context.instance,
        target_trade_date,
    )
    if silver_status.ready:
        cursor = _cursor_payload(
            evaluated_at=evaluated_at,
            target_trade_date=target_trade_date,
            registered_trade_day_count=len(registered_trade_days),
            registered_code_count=len(registered_index_codes),
            ready_code_count=0,
            missing_code_count=0,
            failed_check_code_count=0,
            selected_trade_date=None,
            silver_status=silver_status,
            missing_code_samples=(),
            failed_check_samples={},
        )
        return dg.SensorResult(
            skip_reason="最新指数交易日的 silver_index_daily 分区已经生成完成并通过 blocking checks。",
            cursor=cursor,
        )

    if silver_status.materialized:
        cursor = _cursor_payload(
            evaluated_at=evaluated_at,
            target_trade_date=target_trade_date,
            registered_trade_day_count=len(registered_trade_days),
            registered_code_count=len(registered_index_codes),
            ready_code_count=0,
            missing_code_count=0,
            failed_check_code_count=0,
            selected_trade_date=None,
            silver_status=silver_status,
            missing_code_samples=(),
            failed_check_samples={},
        )
        return dg.SensorResult(
            skip_reason=(
                "最新指数交易日的 silver_index_daily 已生成但 blocking checks 未全绿，"
                "暂不自动重跑，请先人工处理失败检查。"
            ),
            cursor=cursor,
        )

    lake_root = context.resources.lake_root
    lake_root.ensure_available_for_run()
    file_presence = _raw_file_date_presence(
        lake_root_path=lake_root.root(),
        duckdb_resource=context.resources.duckdb,
        index_codes=registered_index_codes,
        trade_date=target_trade_date,
    )

    ready_codes = []
    missing_codes = []
    failed_check_samples: dict[str, dict[str, object]] = {}
    for index_code in registered_index_codes:
        if not file_presence[index_code]:
            missing_codes.append(index_code)
            continue

        raw_status = raw_index_daily_by_code_ready_for_code(context.instance, index_code)
        if raw_status.ready:
            ready_codes.append(index_code)
            continue

        if len(failed_check_samples) < MAX_STATUS_SAMPLE_COUNT:
            failed_check_samples[index_code] = _asset_status_payload(raw_status)

    missing_code_samples = tuple(missing_codes[:MAX_STATUS_SAMPLE_COUNT])
    cursor = _cursor_payload(
        evaluated_at=evaluated_at,
        target_trade_date=target_trade_date,
        registered_trade_day_count=len(registered_trade_days),
        registered_code_count=len(registered_index_codes),
        ready_code_count=len(ready_codes),
        missing_code_count=len(missing_codes),
        failed_check_code_count=len(registered_index_codes) - len(ready_codes) - len(missing_codes),
        selected_trade_date=target_trade_date
        if len(ready_codes) == len(registered_index_codes)
        else None,
        silver_status=silver_status,
        missing_code_samples=missing_code_samples,
        failed_check_samples=failed_check_samples,
    )

    if missing_codes:
        return dg.SensorResult(
            skip_reason="指数日线 raw-by-code 仍有缺口，暂不生成 silver。",
            cursor=cursor,
        )

    if failed_check_samples:
        return dg.SensorResult(
            skip_reason="指数日线 raw-by-code blocking checks 未全部通过，暂不生成 silver。",
            cursor=cursor,
        )

    return dg.SensorResult(
        run_requests=[
            dg.RunRequest(
                partition_key=target_trade_date,
                run_key=f"silver_index_daily:{target_trade_date}",
                tags={
                    "triggered_by": "silver_index_daily_sensor",
                    "asset_family": "index_daily",
                    "trade_date": target_trade_date,
                },
            )
        ],
        cursor=cursor,
    )
