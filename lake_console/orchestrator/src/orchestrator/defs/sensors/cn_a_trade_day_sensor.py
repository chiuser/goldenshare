import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, time
from pathlib import Path

import dagster as dg
import duckdb

from orchestrator.defs.duckdb_sql import STOCK_DAILY_MIN_TRADE_DATE
from orchestrator.defs.partitions import cn_a_trade_days
from orchestrator.defs.paths import silver_trade_calendar_path
from orchestrator.defs.sensors.readiness import CN_A_SENSOR_TIMEZONE


MAX_PARTITION_KEYS_PER_TICK = 2
SAME_DAY_PARTITION_REGISTER_START = time(16, 0)


@dataclass(frozen=True)
class TradeDayPartitionDecision:
    latest_completed_trade_date: str | None
    today: str
    today_is_open: bool
    same_day_register_window_started: bool
    eligible_open_day_count: int
    unregistered_keys: tuple[str, ...]
    selected_keys: tuple[str, ...]


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


def build_trade_day_partition_decision(
    *,
    eligible_open_day_keys: Sequence[str],
    existing_dynamic_partition_keys: set[str],
    today: str,
    today_is_open: bool,
    same_day_register_window_started: bool,
) -> TradeDayPartitionDecision:
    unregistered_keys = tuple(
        key for key in eligible_open_day_keys if key not in existing_dynamic_partition_keys
    )
    selected_keys = unregistered_keys[:MAX_PARTITION_KEYS_PER_TICK]
    latest_completed_trade_date = eligible_open_day_keys[-1] if eligible_open_day_keys else None
    return TradeDayPartitionDecision(
        latest_completed_trade_date=latest_completed_trade_date,
        today=today,
        today_is_open=today_is_open,
        same_day_register_window_started=same_day_register_window_started,
        eligible_open_day_count=len(eligible_open_day_keys),
        unregistered_keys=unregistered_keys,
        selected_keys=selected_keys,
    )


def _cursor_payload(decision: TradeDayPartitionDecision, evaluated_at: datetime) -> str:
    payload = {
        "evaluated_at": evaluated_at.isoformat(),
        "latest_completed_trade_date": decision.latest_completed_trade_date,
        "today": decision.today,
        "today_is_open": decision.today_is_open,
        "same_day_register_window_started": decision.same_day_register_window_started,
        "eligible_open_day_count": decision.eligible_open_day_count,
        "unregistered_count": len(decision.unregistered_keys),
        "selected_keys": list(decision.selected_keys),
        "max_partition_keys_per_tick": MAX_PARTITION_KEYS_PER_TICK,
    }
    return json.dumps(payload, ensure_ascii=True, sort_keys=True)


@dg.sensor(
    default_status=dg.DefaultSensorStatus.STOPPED,
    minimum_interval_seconds=600,
    required_resource_keys={"lake_root", "duckdb"},
    description="注册已完成的A股交易日分区，不触发数据更新任务。",
)
def cn_a_trade_day_sensor(context: dg.SensorEvaluationContext) -> dg.SensorResult:
    evaluated_at = datetime.now(CN_A_SENSOR_TIMEZONE)
    lake_root = context.resources.lake_root
    duckdb_resource = context.resources.duckdb

    lake_root.ensure_available_for_run()
    calendar_path = silver_trade_calendar_path(lake_root.root())
    if not calendar_path.exists():
        raise FileNotFoundError(f"silver_trade_calendar file is missing: {calendar_path}")

    today = evaluated_at.date().isoformat()
    same_day_register_window_started = (
        evaluated_at.time() >= SAME_DAY_PARTITION_REGISTER_START
    )
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

    if today_is_open and same_day_register_window_started and today not in eligible_open_day_keys:
        eligible_open_day_keys = (*eligible_open_day_keys, today)

    existing_dynamic_partition_keys = set(
        context.instance.get_dynamic_partitions(cn_a_trade_days.name)
    )
    decision = build_trade_day_partition_decision(
        eligible_open_day_keys=eligible_open_day_keys,
        existing_dynamic_partition_keys=existing_dynamic_partition_keys,
        today=today,
        today_is_open=today_is_open,
        same_day_register_window_started=same_day_register_window_started,
    )

    if not decision.selected_keys:
        if decision.eligible_open_day_count == 0:
            skip_reason = "没有从交易日历中找到符合条件的上交所开市日。"
        elif decision.today_is_open and not decision.same_day_register_window_started:
            skip_reason = "今天是交易日，但还没到 16:00，暂不注册今天的交易日分区。"
        else:
            skip_reason = "当前所有符合条件的交易日分区都已经注册。"
        return dg.SensorResult(
            skip_reason=skip_reason,
            cursor=_cursor_payload(decision, evaluated_at),
        )

    return dg.SensorResult(
        dynamic_partitions_requests=[
            cn_a_trade_days.build_add_request(list(decision.selected_keys))
        ],
        cursor=_cursor_payload(decision, evaluated_at),
    )
