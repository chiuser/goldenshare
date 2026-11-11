from datetime import datetime
from zoneinfo import ZoneInfo

import dagster as dg
from duckdb import Error as DuckDBError

from orchestrator.defs.duckdb_sql import read_parquet
from orchestrator.defs.partitions import cn_a_stock_factor_pro_trade_days
from orchestrator.defs.paths import silver_trade_calendar_path
from orchestrator.defs.run_contracts.sensor_tags import (
    SensorDomain,
    SensorRole,
    SensorTargetLayer,
    build_sensor_tags,
)
from orchestrator.defs.run_contracts.stk_factor_pro import (
    STK_FACTOR_PRO_PARTITION_SENSOR_INTERVAL_SECONDS,
    STK_FACTOR_PRO_PARTITION_SENSOR_NAME,
    STK_FACTOR_PRO_TIMEZONE,
)


@dg.sensor(
    name=STK_FACTOR_PRO_PARTITION_SENSOR_NAME,
    default_status=dg.DefaultSensorStatus.STOPPED,
    minimum_interval_seconds=STK_FACTOR_PRO_PARTITION_SENSOR_INTERVAL_SECONDS,
    tags=build_sensor_tags(
        sensor_domain=SensorDomain.QUOTE_DATA,
        target_layer=SensorTargetLayer.PARTITION,
        role=SensorRole.PARTITION_REGISTRATION,
    ),
    required_resource_keys={"lake_root", "duckdb"},
    description="按上交所日历登记技术因子当天开市日和上一交易日，不提交日更任务。",
)
def stock_factor_pro_trade_day_sensor(
    context: dg.SensorEvaluationContext,
) -> dg.SensorResult:
    today = datetime.now(ZoneInfo(STK_FACTOR_PRO_TIMEZONE)).date()
    calendar = silver_trade_calendar_path(context.resources.lake_root.root())
    try:
        with context.resources.duckdb.connect() as connection:
            calendar_day = connection.execute(
                f"""
                WITH sse_calendar AS NOT MATERIALIZED (
                    SELECT trade_date, is_open, pretrade_date
                    FROM {read_parquet(calendar)}
                    WHERE exchange = 'SSE'
                )
                SELECT current_day.is_open, previous_day.trade_date
                FROM sse_calendar AS current_day
                LEFT JOIN sse_calendar AS previous_day
                  ON previous_day.trade_date = current_day.pretrade_date
                 AND previous_day.trade_date < current_day.trade_date
                 AND previous_day.is_open
                WHERE current_day.trade_date = ?
                """,
                [today],
            ).fetchone()
    except DuckDBError:
        return dg.SensorResult(skip_reason="无法读取上交所交易日历，请检查日历文件。")
    if calendar_day is None or calendar_day[0] is None:
        return dg.SensorResult(skip_reason=f"上交所日历无法确认 {today} 是否开市。")

    today_open, previous = calendar_day
    partitions = cn_a_stock_factor_pro_trade_days
    candidates = [
        day.isoformat()
        for day in (previous, today if today_open else None)
        if day is not None
    ]
    keys = [
        key
        for key in candidates
        if not partitions.has_partition_key(
            key, dynamic_partitions_store=context.instance
        )
    ]
    if not keys:
        return dg.SensorResult(skip_reason="已确认的交易日没有待注册分区。")
    return dg.SensorResult(
        dynamic_partitions_requests=[partitions.build_add_request(keys)]
    )
