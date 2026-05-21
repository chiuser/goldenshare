import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import dagster as dg
import duckdb

from orchestrator.defs.duckdb_sql import STOCK_DAILY_MIN_TRADE_DATE
from orchestrator.defs.jobs.quote_daily import quote_daily_job
from orchestrator.defs.partitions import cn_a_trade_days
from orchestrator.defs.paths import silver_trade_calendar_path

CN_A_SENSOR_TIMEZONE = ZoneInfo("Asia/Shanghai")
MAX_RUN_REQUESTS_PER_TICK = 2
QUOTE_ASSET_KEYS = (
    dg.AssetKey("raw_tushare_stock_daily"),
    dg.AssetKey("raw_tushare_suspend_d"),
    dg.AssetKey("silver_stock_daily"),
    dg.AssetKey("silver_stock_suspend_daily"),
)


@dataclass(frozen=True)
class TradeDaySensorDecision:
    latest_completed_trade_date: str | None
    eligible_open_day_count: int
    pending_keys: tuple[str, ...]
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


def load_quote_materialized_keys(instance: dg.DagsterInstance) -> set[str]:
    materialized_sets = [instance.get_materialized_partitions(asset_key) for asset_key in QUOTE_ASSET_KEYS]
    if not materialized_sets:
        return set()
    return set.intersection(*materialized_sets)


def build_trade_day_sensor_decision(
    *,
    eligible_open_day_keys: Sequence[str],
    existing_dynamic_partition_keys: set[str],
    quote_materialized_keys: set[str],
) -> TradeDaySensorDecision:
    pending_keys = tuple(key for key in eligible_open_day_keys if key not in quote_materialized_keys)
    selected_keys = pending_keys[:MAX_RUN_REQUESTS_PER_TICK]
    keys_to_add = tuple(key for key in selected_keys if key not in existing_dynamic_partition_keys)
    latest_completed_trade_date = eligible_open_day_keys[-1] if eligible_open_day_keys else None
    return TradeDaySensorDecision(
        latest_completed_trade_date=latest_completed_trade_date,
        eligible_open_day_count=len(eligible_open_day_keys),
        pending_keys=pending_keys,
        selected_keys=selected_keys,
        keys_to_add=keys_to_add,
    )


def _cursor_payload(decision: TradeDaySensorDecision, evaluated_at: datetime) -> str:
    payload = {
        "evaluated_at": evaluated_at.isoformat(),
        "latest_completed_trade_date": decision.latest_completed_trade_date,
        "eligible_open_day_count": decision.eligible_open_day_count,
        "pending_count": len(decision.pending_keys),
        "selected_keys": list(decision.selected_keys),
        "keys_to_add": list(decision.keys_to_add),
        "max_run_requests_per_tick": MAX_RUN_REQUESTS_PER_TICK,
    }
    return json.dumps(payload, ensure_ascii=True, sort_keys=True)


@dg.sensor(
    job=quote_daily_job,
    default_status=dg.DefaultSensorStatus.STOPPED,
    minimum_interval_seconds=300,
    required_resource_keys={"lake_root", "duckdb"},
    description=(
        "Registers completed China A-share trading day partitions and triggers "
        "quote_daily_job for missing quote daily partitions."
    ),
)
def cn_a_trade_day_sensor(context: dg.SensorEvaluationContext) -> dg.SensorResult:
    evaluated_at = datetime.now(CN_A_SENSOR_TIMEZONE)
    lake_root = context.resources.lake_root
    duckdb_resource = context.resources.duckdb

    lake_root.ensure_available_for_run()
    calendar_path = silver_trade_calendar_path(lake_root.root())
    if not calendar_path.exists():
        raise FileNotFoundError(f"silver_trade_calendar file is missing: {calendar_path}")

    with duckdb_resource.connect() as connection:
        latest_completed_trade_date = resolve_latest_completed_trade_date(
            connection,
            calendar_path,
            evaluated_at,
        )
        if latest_completed_trade_date is None:
            decision = TradeDaySensorDecision(
                latest_completed_trade_date=None,
                eligible_open_day_count=0,
                pending_keys=(),
                selected_keys=(),
                keys_to_add=(),
            )
            return dg.SensorResult(
                skip_reason=(
                    "No completed SSE trading day found in silver_trade_calendar "
                    f"on or after {STOCK_DAILY_MIN_TRADE_DATE}."
                ),
                cursor=_cursor_payload(decision, evaluated_at),
            )

        eligible_open_day_keys = load_completed_open_day_keys(
            connection,
            calendar_path,
            latest_completed_trade_date,
        )

    existing_dynamic_partition_keys = set(context.instance.get_dynamic_partitions(cn_a_trade_days.name))
    quote_materialized_keys = load_quote_materialized_keys(context.instance)
    decision = build_trade_day_sensor_decision(
        eligible_open_day_keys=eligible_open_day_keys,
        existing_dynamic_partition_keys=existing_dynamic_partition_keys,
        quote_materialized_keys=quote_materialized_keys,
    )

    if not decision.selected_keys:
        return dg.SensorResult(
            skip_reason=(
                "No completed SSE trading day quote partitions are pending. "
                f"latest_completed_trade_date={decision.latest_completed_trade_date}."
            ),
            cursor=_cursor_payload(decision, evaluated_at),
        )

    dynamic_partitions_requests = (
        [cn_a_trade_days.build_add_request(list(decision.keys_to_add))] if decision.keys_to_add else []
    )
    run_requests = [
        dg.RunRequest(
            partition_key=key,
            run_key=f"quote_daily:{key}",
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
