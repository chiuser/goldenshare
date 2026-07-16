from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, time
from pathlib import Path

import dagster as dg
import duckdb

from orchestrator.defs.partitions import cn_a_trade_days
from orchestrator.defs.paths import silver_trade_calendar_path
from orchestrator.defs.run_contracts.cursors import (
    SensorCursorDecision,
    build_sensor_cursor,
)
from orchestrator.defs.run_contracts.cursor_payloads import build_cursor_details
from orchestrator.defs.run_contracts.sensor_tags import (
    SensorDomain,
    SensorRole,
    SensorTargetLayer,
    build_sensor_tags,
)
from orchestrator.defs.sensors.readiness import CN_A_SENSOR_TIMEZONE


MAX_PARTITION_KEYS_PER_TICK = 2
SAME_DAY_PARTITION_REGISTER_START = time(16, 0)
FULL_TRADE_DAY_MIN_DATE = "1990-01-01"
STOCK_TRADE_DAY_MIN_DATE = "2014-01-01"
INDEX_TRADE_DAY_MIN_DATE = "2000-01-01"


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
    min_trade_date: str,
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
        [str(calendar_path), min_trade_date, today.date().isoformat()],
    ).fetchone()
    return row[0] if row and row[0] else None


def load_completed_open_day_keys(
    connection: duckdb.DuckDBPyConnection,
    calendar_path: Path,
    latest_completed_trade_date: str,
    min_trade_date: str,
) -> tuple[str, ...]:
    rows = connection.execute(
        """
        SELECT CAST(CAST(trade_date AS DATE) AS VARCHAR) AS trade_date
        FROM read_parquet(?)
        WHERE exchange = 'SSE'
          AND is_open = true
          AND trade_date >= CAST(? AS DATE)
          AND trade_date <= CAST(? AS DATE)
        ORDER BY trade_date
        """,
        [str(calendar_path), min_trade_date, latest_completed_trade_date],
    ).fetchall()
    return tuple(row[0] for row in rows)


def load_open_day_keys_through_today(
    connection: duckdb.DuckDBPyConnection,
    calendar_path: Path,
    today: str,
    min_trade_date: str,
) -> tuple[str, ...]:
    """Load calendar facts without applying a source-time registration gate."""

    rows = connection.execute(
        """
        SELECT CAST(CAST(trade_date AS DATE) AS VARCHAR) AS trade_date
        FROM read_parquet(?)
        WHERE exchange = 'SSE'
          AND is_open = true
          AND trade_date >= CAST(? AS DATE)
          AND trade_date <= CAST(? AS DATE)
        GROUP BY CAST(trade_date AS DATE)
        ORDER BY CAST(trade_date AS DATE)
        """,
        [str(calendar_path), min_trade_date, today],
    ).fetchall()
    return tuple(str(row[0]) for row in rows)


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


def _cursor_payload(
    decision: TradeDayPartitionDecision,
    evaluated_at: datetime,
    *,
    sensor_name: str,
    asset_family: str,
    partition_set: str,
    summary: str | None = None,
    next_action: str | None = None,
) -> str:
    cursor_decision = (
        SensorCursorDecision.REGISTER_PARTITIONS
        if decision.selected_keys
        else SensorCursorDecision.SKIP
    )
    return build_sensor_cursor(
        evaluated_at=evaluated_at,
        decision=cursor_decision,
        target_date=decision.latest_completed_trade_date,
        selected_count=len(decision.selected_keys),
        blocked_count=max(
            0,
            len(decision.unregistered_keys) - len(decision.selected_keys),
        ),
        sample_keys=decision.selected_keys,
        details=build_cursor_details(
            sensor_name=sensor_name,
            job_name=None,
            asset_family=asset_family,
            partition_set=partition_set,
            reason_code=(
                "register_partitions"
                if decision.selected_keys
                else "all_registered"
                if decision.latest_completed_trade_date
                else "no_completed_trade_day"
            ),
            blocked_component="none",
            summary=summary
            or (
                f"register {len(decision.selected_keys)} trade-date partitions"
                if decision.selected_keys
                else "all eligible trade-date partitions are registered"
            ),
            next_action=next_action
            or (
                "wait for dynamic partition registration"
                if decision.selected_keys
                else "wait for the next sensor tick"
            ),
            frontier={
                "latest_completed_trade_date": decision.latest_completed_trade_date,
                "today": decision.today,
                "today_is_open": decision.today_is_open,
                "same_day_register_window_started": (
                    decision.same_day_register_window_started
                ),
            },
            evidence={
                "eligible_open_day_count": decision.eligible_open_day_count,
                "unregistered_count": len(decision.unregistered_keys),
                "max_partition_keys_per_tick": MAX_PARTITION_KEYS_PER_TICK,
            },
        ),
    )


def _format_register_start(register_start: time) -> str:
    return register_start.strftime("%H:%M")


def _log_trade_day_partition_decision(
    context: dg.SensorEvaluationContext,
    *,
    decision: TradeDayPartitionDecision,
    dynamic_partitions: dg.DynamicPartitionsDefinition,
    min_trade_date: str,
    partition_set_label: str,
    same_day_register_start: time,
) -> None:
    context.log.info(
        "event=trade_day_partition_registration "
        f"partition_set_label={partition_set_label} "
        f"dynamic_partitions={dynamic_partitions.name} "
        f"min_trade_date={min_trade_date} "
        f"same_day_register_start={_format_register_start(same_day_register_start)} "
        f"today={decision.today} "
        f"today_is_open={decision.today_is_open} "
        f"same_day_register_window_started={decision.same_day_register_window_started} "
        f"latest_completed_trade_date={decision.latest_completed_trade_date or '-'} "
        f"eligible_open_day_count={decision.eligible_open_day_count} "
        f"unregistered_count={len(decision.unregistered_keys)} "
        f"selected_keys={list(decision.selected_keys)}"
    )


def build_trade_day_partition_registration_result(
    context: dg.SensorEvaluationContext,
    *,
    dynamic_partitions: dg.DynamicPartitionsDefinition,
    min_trade_date: str,
    partition_set_label: str,
    same_day_register_start: time = SAME_DAY_PARTITION_REGISTER_START,
    sensor_name: str = "cn_a_trade_day_sensor",
    asset_family: str = "trade_day_partitions",
    cursor_partition_set: str = "cn_a_trade_days",
) -> dg.SensorResult:
    evaluated_at = datetime.now(CN_A_SENSOR_TIMEZONE)
    lake_root = context.resources.lake_root
    duckdb_resource = context.resources.duckdb

    lake_root.ensure_available_for_run()
    calendar_path = silver_trade_calendar_path(lake_root.root())
    if not calendar_path.exists():
        raise FileNotFoundError(f"silver_trade_calendar file is missing: {calendar_path}")

    today = evaluated_at.date().isoformat()
    same_day_register_window_started = (
        evaluated_at.time() >= same_day_register_start
    )
    with duckdb_resource.connect() as connection:
        latest_completed_trade_date = resolve_latest_completed_trade_date(
            connection,
            calendar_path,
            evaluated_at,
            min_trade_date,
        )
        if latest_completed_trade_date is None:
            eligible_open_day_keys = ()
        else:
            eligible_open_day_keys = load_completed_open_day_keys(
                connection,
                calendar_path,
                latest_completed_trade_date,
                min_trade_date,
            )
        today_is_open = is_sse_open_day(connection, calendar_path, today)

    if (
        today >= min_trade_date
        and today_is_open
        and same_day_register_window_started
        and today not in eligible_open_day_keys
    ):
        eligible_open_day_keys = (*eligible_open_day_keys, today)

    existing_dynamic_partition_keys = set(
        context.instance.get_dynamic_partitions(dynamic_partitions.name)
    )
    decision = build_trade_day_partition_decision(
        eligible_open_day_keys=eligible_open_day_keys,
        existing_dynamic_partition_keys=existing_dynamic_partition_keys,
        today=today,
        today_is_open=today_is_open,
        same_day_register_window_started=same_day_register_window_started,
    )
    _log_trade_day_partition_decision(
        context,
        decision=decision,
        dynamic_partitions=dynamic_partitions,
        min_trade_date=min_trade_date,
        partition_set_label=partition_set_label,
        same_day_register_start=same_day_register_start,
    )

    if not decision.selected_keys:
        if decision.eligible_open_day_count == 0:
            skip_reason = "没有从交易日历中找到符合条件的上交所开市日。"
        elif decision.today_is_open and not decision.same_day_register_window_started:
            skip_reason = (
                "今天是交易日，但还没到 "
                f"{_format_register_start(same_day_register_start)}，"
                "暂不注册今天的交易日分区。"
            )
        else:
            skip_reason = f"当前所有符合条件的{partition_set_label}交易日分区都已经注册。"
        return dg.SensorResult(
            skip_reason=skip_reason,
            cursor=_cursor_payload(
                decision,
                evaluated_at,
                sensor_name=sensor_name,
                asset_family=asset_family,
                partition_set=cursor_partition_set,
            ),
        )

    return dg.SensorResult(
        dynamic_partitions_requests=[
            dynamic_partitions.build_add_request(list(decision.selected_keys))
        ],
        cursor=_cursor_payload(
            decision,
            evaluated_at,
            sensor_name=sensor_name,
            asset_family=asset_family,
            partition_set=cursor_partition_set,
        ),
    )


def build_calendar_only_partition_registration_result(
    context: dg.SensorEvaluationContext,
    *,
    dynamic_partitions: dg.DynamicPartitionsDefinition,
    min_trade_date: str,
    partition_set_label: str,
    sensor_name: str,
    asset_family: str,
) -> dg.SensorResult:
    """Register calendar-domain partitions without a wall-clock source gate."""

    evaluated_at = datetime.now(CN_A_SENSOR_TIMEZONE)
    lake_root = context.resources.lake_root
    lake_root.ensure_available_for_run()
    calendar_path = silver_trade_calendar_path(lake_root.root())
    if not calendar_path.exists():
        raise FileNotFoundError(f"silver_trade_calendar file is missing: {calendar_path}")

    today = evaluated_at.date().isoformat()
    duckdb_resource = context.resources.duckdb
    with duckdb_resource.connect() as connection:
        eligible_open_day_keys = load_open_day_keys_through_today(
            connection,
            calendar_path,
            today,
            min_trade_date,
        )
        today_is_open = is_sse_open_day(connection, calendar_path, today)

    existing_dynamic_partition_keys = set(
        context.instance.get_dynamic_partitions(dynamic_partitions.name)
    )
    decision = build_trade_day_partition_decision(
        eligible_open_day_keys=eligible_open_day_keys,
        existing_dynamic_partition_keys=existing_dynamic_partition_keys,
        today=today,
        today_is_open=today_is_open,
        same_day_register_window_started=True,
    )
    _log_trade_day_partition_decision(
        context,
        decision=decision,
        dynamic_partitions=dynamic_partitions,
        min_trade_date=min_trade_date,
        partition_set_label=partition_set_label,
        same_day_register_start=time.min,
    )
    return dg.SensorResult(
        dynamic_partitions_requests=(
            [dynamic_partitions.build_add_request(list(decision.selected_keys))]
            if decision.selected_keys
            else []
        ),
        skip_reason=(
            None
            if decision.selected_keys
            else (
                f"当前所有符合条件的{partition_set_label}交易日分区都已经注册。"
                if decision.eligible_open_day_count
                else "交易日历中没有找到符合条件的上交所开市日。"
            )
        ),
        cursor=_cursor_payload(
            decision,
            evaluated_at,
            sensor_name=sensor_name,
            asset_family=asset_family,
            partition_set=dynamic_partitions.name,
            summary=(
                f"register {len(decision.selected_keys)} board trade-date partitions"
                if decision.selected_keys
                else "all eligible board trade-date partitions are registered"
            ),
            next_action=(
                "wait for board dynamic partition registration"
                if decision.selected_keys
                else "wait for the next board partition sensor tick"
            ),
        ),
    )


@dg.sensor(
    default_status=dg.DefaultSensorStatus.STOPPED,
    minimum_interval_seconds=600,
    tags=build_sensor_tags(
        sensor_domain=SensorDomain.BASIC_DATA,
        target_layer=SensorTargetLayer.PARTITION,
        role=SensorRole.PARTITION_REGISTRATION,
    ),
    required_resource_keys={"lake_root", "duckdb"},
    description="注册全量A股交易日备份分区，不触发数据更新任务。",
)
def cn_a_trade_day_sensor(context: dg.SensorEvaluationContext) -> dg.SensorResult:
    return build_trade_day_partition_registration_result(
        context,
        dynamic_partitions=cn_a_trade_days,
        min_trade_date=FULL_TRADE_DAY_MIN_DATE,
        partition_set_label="全量备份",
    )
