import json
from datetime import datetime, time
from pathlib import Path
from typing import Any

import dagster as dg

from orchestrator.defs.duckdb_sql import read_parquet
from orchestrator.defs.partitions import cn_a_index_trade_days, cn_a_index_ts_codes
from orchestrator.defs.paths import raw_index_daily_by_code_path
from orchestrator.defs.run_contracts.configs import build_index_daily_update_job_run_config
from orchestrator.defs.run_contracts.requests import build_run_request
from orchestrator.defs.sensors.readiness import CN_A_SENSOR_TIMEZONE
from orchestrator.source_readiness.tushare.index_daily import (
    check_index_daily_source_readiness,
)


INDEX_DAILY_SOURCE_PROBE_START = time(16, 0)
MAX_RUN_REQUESTS_PER_TICK = 500


def _load_cursor(cursor: str | None) -> dict[str, Any]:
    if not cursor:
        return {}
    try:
        payload = json.loads(cursor)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _latest_runnable_trade_date(
    registered_trade_days: tuple[str, ...],
    evaluated_at: datetime,
) -> str | None:
    today = evaluated_at.date().isoformat()
    probe_window_started = evaluated_at.time() >= INDEX_DAILY_SOURCE_PROBE_START
    eligible_trade_days = tuple(
        trade_date
        for trade_date in registered_trade_days
        if trade_date < today or (trade_date == today and probe_window_started)
    )
    return eligible_trade_days[-1] if eligible_trade_days else None


def _raw_by_code_has_trade_date(
    connection,
    raw_path: Path,
    compact_trade_date: str,
) -> bool:
    if not raw_path.exists():
        return False
    query = read_parquet(raw_path, hive_partitioning=False)
    row = connection.execute(
        f"""
        SELECT count(*) > 0 AS has_trade_date
        FROM {query}
        WHERE CAST(trade_date AS VARCHAR) = ?
        """,
        [compact_trade_date],
    ).fetchone()
    return bool(row and row[0])


def _pending_index_codes_for_trade_date(
    *,
    lake_root_path: Path,
    duckdb_resource,
    index_codes: tuple[str, ...],
    trade_date: str,
) -> tuple[str, ...]:
    compact_trade_date = trade_date.replace("-", "")
    pending_codes = []
    with duckdb_resource.connect() as connection:
        for index_code in index_codes:
            raw_path = raw_index_daily_by_code_path(lake_root_path, index_code)
            if not _raw_by_code_has_trade_date(connection, raw_path, compact_trade_date):
                pending_codes.append(index_code)
    return tuple(pending_codes)


def _select_pending_codes(
    *,
    cursor_payload: dict[str, Any],
    target_trade_date: str,
    pending_codes: tuple[str, ...],
) -> tuple[tuple[str, ...], int]:
    if not pending_codes:
        return (), 0

    cursor_trade_date = cursor_payload.get("target_trade_date")
    raw_offset = cursor_payload.get("next_pending_offset", 0)
    start_offset = raw_offset if cursor_trade_date == target_trade_date else 0
    if not isinstance(start_offset, int) or start_offset < 0:
        start_offset = 0
    start_offset = start_offset % len(pending_codes)

    rotated_pending_codes = pending_codes[start_offset:] + pending_codes[:start_offset]
    selected_codes = rotated_pending_codes[:MAX_RUN_REQUESTS_PER_TICK]
    next_offset = (start_offset + len(selected_codes)) % len(pending_codes)
    return selected_codes, next_offset


def _cursor_payload(
    *,
    evaluated_at: datetime,
    today: str,
    registered_trade_day_count: int,
    registered_code_count: int,
    target_trade_date: str | None,
    source_ready: bool | None,
    source_row_count: int | None,
    pending_count: int,
    selected_codes: tuple[str, ...],
    next_pending_offset: int,
) -> str:
    payload = {
        "evaluated_at": evaluated_at.isoformat(),
        "today": today,
        "registered_trade_day_count": registered_trade_day_count,
        "registered_code_count": registered_code_count,
        "target_trade_date": target_trade_date,
        "source_ready": source_ready,
        "source_row_count": source_row_count,
        "pending_count": pending_count,
        "selected_count": len(selected_codes),
        "selected_codes": list(selected_codes),
        "next_pending_offset": next_pending_offset,
        "max_run_requests_per_tick": MAX_RUN_REQUESTS_PER_TICK,
    }
    return json.dumps(payload, ensure_ascii=True, sort_keys=True)


@dg.sensor(
    job_name="index_daily_update_job",
    default_status=dg.DefaultSensorStatus.STOPPED,
    minimum_interval_seconds=600,
    required_resource_keys={"lake_root", "duckdb", "tushare"},
    description="Tushare 指数日线源站 ready 后，触发 raw-by-code 更新任务。",
)
def index_daily_sensor(context: dg.SensorEvaluationContext) -> dg.SensorResult:
    evaluated_at = datetime.now(CN_A_SENSOR_TIMEZONE)
    today = evaluated_at.date().isoformat()

    registered_trade_days = tuple(
        sorted(context.instance.get_dynamic_partitions(cn_a_index_trade_days.name))
    )
    registered_index_codes = tuple(
        sorted(context.instance.get_dynamic_partitions(cn_a_index_ts_codes.name))
    )
    if not registered_trade_days:
        return dg.SensorResult(
            skip_reason="没有注册指数交易日分区，无法触发指数日线更新。",
            cursor=_cursor_payload(
                evaluated_at=evaluated_at,
                today=today,
                registered_trade_day_count=0,
                registered_code_count=len(registered_index_codes),
                target_trade_date=None,
                source_ready=None,
                source_row_count=None,
                pending_count=0,
                selected_codes=(),
                next_pending_offset=0,
            ),
        )
    if not registered_index_codes:
        return dg.SensorResult(
            skip_reason="没有注册指数代码分区，无法触发指数日线更新。",
            cursor=_cursor_payload(
                evaluated_at=evaluated_at,
                today=today,
                registered_trade_day_count=len(registered_trade_days),
                registered_code_count=0,
                target_trade_date=None,
                source_ready=None,
                source_row_count=None,
                pending_count=0,
                selected_codes=(),
                next_pending_offset=0,
            ),
        )

    target_trade_date = _latest_runnable_trade_date(registered_trade_days, evaluated_at)
    if target_trade_date is None:
        return dg.SensorResult(
            skip_reason="没有符合当前时间窗口的指数交易日分区。",
            cursor=_cursor_payload(
                evaluated_at=evaluated_at,
                today=today,
                registered_trade_day_count=len(registered_trade_days),
                registered_code_count=len(registered_index_codes),
                target_trade_date=None,
                source_ready=None,
                source_row_count=None,
                pending_count=0,
                selected_codes=(),
                next_pending_offset=0,
            ),
        )

    source_readiness = check_index_daily_source_readiness(
        tushare=context.resources.tushare,
        trade_date=target_trade_date,
        checked_at=evaluated_at,
    )
    if not source_readiness.is_ready:
        return dg.SensorResult(
            skip_reason="Tushare 指数日线源站还没有返回有效数据。",
            cursor=_cursor_payload(
                evaluated_at=evaluated_at,
                today=today,
                registered_trade_day_count=len(registered_trade_days),
                registered_code_count=len(registered_index_codes),
                target_trade_date=target_trade_date,
                source_ready=False,
                source_row_count=source_readiness.row_count,
                pending_count=0,
                selected_codes=(),
                next_pending_offset=0,
            ),
        )

    lake_root = context.resources.lake_root
    lake_root.ensure_available_for_run()
    pending_codes = _pending_index_codes_for_trade_date(
        lake_root_path=lake_root.root(),
        duckdb_resource=context.resources.duckdb,
        index_codes=registered_index_codes,
        trade_date=target_trade_date,
    )
    selected_codes, next_pending_offset = _select_pending_codes(
        cursor_payload=_load_cursor(context.cursor),
        target_trade_date=target_trade_date,
        pending_codes=pending_codes,
    )
    cursor = _cursor_payload(
        evaluated_at=evaluated_at,
        today=today,
        registered_trade_day_count=len(registered_trade_days),
        registered_code_count=len(registered_index_codes),
        target_trade_date=target_trade_date,
        source_ready=True,
        source_row_count=source_readiness.row_count,
        pending_count=len(pending_codes),
        selected_codes=selected_codes,
        next_pending_offset=next_pending_offset,
    )
    if not selected_codes:
        return dg.SensorResult(
            skip_reason="当前最新指数交易日的 raw-by-code 分区都已经生成完成。",
            cursor=cursor,
        )

    return dg.SensorResult(
        run_requests=[
            build_run_request(
                partition_key=index_code,
                run_key=f"index_daily:{target_trade_date}:{index_code}",
                run_config=build_index_daily_update_job_run_config(
                    trade_date=target_trade_date,
                    write_mode="replace",
                ),
            )
            for index_code in selected_codes
        ],
        cursor=cursor,
    )
