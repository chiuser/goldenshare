import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

import dagster as dg
import duckdb

from orchestrator.defs.duckdb_sql import STOCK_DAILY_MIN_TRADE_DATE
from orchestrator.defs.jobs.stock_daily_update import stock_daily_update_job
from orchestrator.defs.partitions import cn_a_trade_days
from orchestrator.defs.paths import (
    silver_stock_basic_path,
    silver_stock_suspend_daily_path,
    silver_trade_calendar_path,
)
from orchestrator.source_readiness.tushare.stock_daily import (
    StockDailySourceReadiness,
    check_stock_daily_source_readiness,
)

CN_A_SENSOR_TIMEZONE = ZoneInfo("Asia/Shanghai")
MAX_RUN_REQUESTS_PER_TICK = 2
SAME_DAY_SOURCE_PROBE_START = time(16, 0)
STOCK_DAILY_ASSET_KEYS = (
    dg.AssetKey("raw_tushare_stock_daily"),
    dg.AssetKey("silver_stock_daily"),
)
SILVER_STOCK_BASIC_ASSET_KEY = dg.AssetKey("silver_stock_basic")
SILVER_STOCK_SUSPEND_DAILY_ASSET_KEY = dg.AssetKey("silver_stock_suspend_daily")


@dataclass(frozen=True)
class TradeDaySensorDecision:
    latest_completed_trade_date: str | None
    today: str
    today_is_open: bool
    probe_window_started: bool
    source_ready: bool | None
    source_row_count: int | None
    source_reason: str | None
    stock_basic_ready: bool
    eligible_open_day_count: int
    pending_keys: tuple[str, ...]
    candidate_keys: tuple[str, ...]
    upstream_blocked_keys: tuple[str, ...]
    missing_suspend_keys: tuple[str, ...]
    selected_keys: tuple[str, ...]
    keys_to_add: tuple[str, ...]


def resolve_latest_completed_trade_date(
    connection: duckdb.DuckDBPyConnection,
    calendar_path: Path,
    today: datetime,
) -> str | None:
    row = connection.execute(
        """
        SELECT CAST(max(trade_date) AS VARCHAR) AS latest_completed_trade_date
        FROM read_parquet(?)
        WHERE exchange = 'SSE'
          AND is_open = true
          AND trade_date >= CAST(? AS DATE)
          AND trade_date < CAST(? AS DATE)
        """,
        [str(calendar_path), STOCK_DAILY_MIN_TRADE_DATE, today.date().isoformat()],
    ).fetchone()
    return row[0] if row and row[0] else None


def load_completed_open_day_keys(
    connection: duckdb.DuckDBPyConnection,
    calendar_path: Path,
    latest_completed_trade_date: str,
) -> tuple[str, ...]:
    rows = connection.execute(
        """
        SELECT CAST(trade_date AS VARCHAR) AS trade_date
        FROM read_parquet(?)
        WHERE exchange = 'SSE'
          AND is_open = true
          AND trade_date >= CAST(? AS DATE)
          AND trade_date <= CAST(? AS DATE)
        ORDER BY trade_date
        """,
        [str(calendar_path), STOCK_DAILY_MIN_TRADE_DATE, latest_completed_trade_date],
    ).fetchall()
    return tuple(row[0] for row in rows)


def is_sse_open_day(
    connection: duckdb.DuckDBPyConnection,
    calendar_path: Path,
    trade_date: str,
) -> bool:
    row = connection.execute(
        """
        SELECT count(*) > 0 AS is_open_day
        FROM read_parquet(?)
        WHERE exchange = 'SSE'
          AND is_open = true
          AND trade_date = CAST(? AS DATE)
        """,
        [str(calendar_path), trade_date],
    ).fetchone()
    return bool(row and row[0])


def load_stock_daily_materialized_keys(instance: dg.DagsterInstance) -> set[str]:
    materialized_sets = [
        instance.get_materialized_partitions(asset_key) for asset_key in STOCK_DAILY_ASSET_KEYS
    ]
    if not materialized_sets:
        return set()
    return set.intersection(*materialized_sets)


def is_stock_basic_ready(instance: dg.DagsterInstance, lake_root_path: Path) -> bool:
    return (
        silver_stock_basic_path(lake_root_path).exists()
        and instance.get_latest_materialization_event(SILVER_STOCK_BASIC_ASSET_KEY) is not None
    )


def load_stock_suspend_materialized_keys(instance: dg.DagsterInstance) -> set[str]:
    return instance.get_materialized_partitions(SILVER_STOCK_SUSPEND_DAILY_ASSET_KEY)


def build_trade_day_sensor_decision(
    *,
    eligible_open_day_keys: Sequence[str],
    existing_dynamic_partition_keys: set[str],
    stock_daily_materialized_keys: set[str],
    stock_basic_ready: bool,
    stock_suspend_materialized_keys: set[str],
    today: str,
    today_is_open: bool,
    probe_window_started: bool,
    source_readiness: StockDailySourceReadiness | None,
) -> TradeDaySensorDecision:
    pending_keys = tuple(
        key for key in eligible_open_day_keys if key not in stock_daily_materialized_keys
    )
    candidate_keys = pending_keys[:MAX_RUN_REQUESTS_PER_TICK]
    missing_suspend_keys = tuple(
        key for key in candidate_keys if key not in stock_suspend_materialized_keys
    )
    if stock_basic_ready:
        selected_keys = tuple(
            key for key in candidate_keys if key in stock_suspend_materialized_keys
        )
    else:
        selected_keys = ()
    upstream_blocked_keys = tuple(key for key in candidate_keys if key not in selected_keys)
    keys_to_add = tuple(key for key in candidate_keys if key not in existing_dynamic_partition_keys)
    latest_completed_trade_date = eligible_open_day_keys[-1] if eligible_open_day_keys else None
    return TradeDaySensorDecision(
        latest_completed_trade_date=latest_completed_trade_date,
        today=today,
        today_is_open=today_is_open,
        probe_window_started=probe_window_started,
        source_ready=source_readiness.is_ready if source_readiness else None,
        source_row_count=source_readiness.row_count if source_readiness else None,
        source_reason=source_readiness.reason if source_readiness else None,
        stock_basic_ready=stock_basic_ready,
        eligible_open_day_count=len(eligible_open_day_keys),
        pending_keys=pending_keys,
        candidate_keys=candidate_keys,
        upstream_blocked_keys=upstream_blocked_keys,
        missing_suspend_keys=missing_suspend_keys,
        selected_keys=selected_keys,
        keys_to_add=keys_to_add,
    )


def _cursor_payload(decision: TradeDaySensorDecision, evaluated_at: datetime) -> str:
    payload = {
        "evaluated_at": evaluated_at.isoformat(),
        "latest_completed_trade_date": decision.latest_completed_trade_date,
        "today": decision.today,
        "today_is_open": decision.today_is_open,
        "probe_window_started": decision.probe_window_started,
        "source_ready": decision.source_ready,
        "source_row_count": decision.source_row_count,
        "source_reason": decision.source_reason,
        "stock_basic_ready": decision.stock_basic_ready,
        "eligible_open_day_count": decision.eligible_open_day_count,
        "pending_count": len(decision.pending_keys),
        "candidate_keys": list(decision.candidate_keys),
        "upstream_blocked_keys": list(decision.upstream_blocked_keys),
        "missing_suspend_keys": list(decision.missing_suspend_keys),
        "selected_keys": list(decision.selected_keys),
        "keys_to_add": list(decision.keys_to_add),
        "max_run_requests_per_tick": MAX_RUN_REQUESTS_PER_TICK,
    }
    return json.dumps(payload, ensure_ascii=True, sort_keys=True)


@dg.sensor(
    job=stock_daily_update_job,
    default_status=dg.DefaultSensorStatus.STOPPED,
    minimum_interval_seconds=600,
    required_resource_keys={"lake_root", "duckdb", "tushare"},
    description=(
        "Registers completed China A-share trading day partitions and triggers "
        "stock_daily_update_job for missing stock daily partitions after upstream "
        "stock_basic and suspend_d assets are ready."
    ),
)
def cn_a_trade_day_sensor(context: dg.SensorEvaluationContext) -> dg.SensorResult:
    evaluated_at = datetime.now(CN_A_SENSOR_TIMEZONE)
    lake_root = context.resources.lake_root
    duckdb_resource = context.resources.duckdb
    tushare = context.resources.tushare

    lake_root.ensure_available_for_run()
    calendar_path = silver_trade_calendar_path(lake_root.root())
    if not calendar_path.exists():
        raise FileNotFoundError(f"silver_trade_calendar file is missing: {calendar_path}")

    today = evaluated_at.date().isoformat()
    probe_window_started = evaluated_at.time() >= SAME_DAY_SOURCE_PROBE_START
    with duckdb_resource.connect() as connection:
        latest_completed_trade_date = resolve_latest_completed_trade_date(
            connection,
            calendar_path,
            evaluated_at,
        )
        if latest_completed_trade_date is None:
            eligible_open_day_keys = ()
        else:
            eligible_open_day_keys = load_completed_open_day_keys(
                connection,
                calendar_path,
                latest_completed_trade_date,
            )
        today_is_open = is_sse_open_day(connection, calendar_path, today)

    source_readiness = None
    if today_is_open and probe_window_started:
        source_readiness = check_stock_daily_source_readiness(
            tushare=tushare,
            trade_date=today,
            checked_at=evaluated_at,
        )
        if source_readiness.is_ready and today not in eligible_open_day_keys:
            eligible_open_day_keys = (*eligible_open_day_keys, today)

    existing_dynamic_partition_keys = set(context.instance.get_dynamic_partitions(cn_a_trade_days.name))
    stock_daily_materialized_keys = load_stock_daily_materialized_keys(context.instance)
    stock_basic_ready = is_stock_basic_ready(context.instance, lake_root.root())
    stock_suspend_materialized_keys = load_stock_suspend_materialized_keys(context.instance)
    decision = build_trade_day_sensor_decision(
        eligible_open_day_keys=eligible_open_day_keys,
        existing_dynamic_partition_keys=existing_dynamic_partition_keys,
        stock_daily_materialized_keys=stock_daily_materialized_keys,
        stock_basic_ready=stock_basic_ready,
        stock_suspend_materialized_keys=stock_suspend_materialized_keys,
        today=today,
        today_is_open=today_is_open,
        probe_window_started=probe_window_started,
        source_readiness=source_readiness,
    )

    dynamic_partitions_requests = (
        [cn_a_trade_days.build_add_request(list(decision.keys_to_add))] if decision.keys_to_add else []
    )
    if not decision.selected_keys:
        if decision.today_is_open and not decision.probe_window_started:
            skip_reason = "今天是交易日，但还没到 16:00，不开始探测 Tushare 日线。"
        elif (
            decision.today_is_open
            and decision.probe_window_started
            and decision.source_ready is False
        ):
            skip_reason = (
                "今天是交易日，也已经进入探测窗口，但 Tushare 日线还没有返回有效数据。"
            )
        elif decision.eligible_open_day_count == 0:
            skip_reason = (
                "没有从交易日历中找到符合条件的已完成上交所开市日。"
            )
        elif decision.candidate_keys and not decision.stock_basic_ready:
            skip_reason = (
                "股票基础信息还没有生成完成，先等待 basic_update_job 成功后再触发股票日线。"
            )
        elif decision.missing_suspend_keys:
            skip_reason = (
                "停复牌分区还没有生成完成，先等待 suspend_update_job 成功后再触发股票日线。"
            )
        else:
            skip_reason = (
                "当前所有符合条件的行情日频分区都已经生成完成，没有待补数据。"
            )
        return dg.SensorResult(
            skip_reason=skip_reason,
            dynamic_partitions_requests=dynamic_partitions_requests,
            cursor=_cursor_payload(decision, evaluated_at),
        )

    run_requests = [
        dg.RunRequest(
            partition_key=key,
            run_key=f"stock_daily_update:{key}",
            tags={
                "triggered_by": "cn_a_trade_day_sensor",
                "latest_completed_trade_date": decision.latest_completed_trade_date or "",
            },
        )
        for key in decision.selected_keys
    ]
    return dg.SensorResult(
        run_requests=run_requests,
        dynamic_partitions_requests=dynamic_partitions_requests,
        cursor=_cursor_payload(decision, evaluated_at),
    )
