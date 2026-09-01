from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import dagster as dg

from orchestrator.defs.asset_guards.stock_daily_qfq_factor_repair import (
    GoldStockDailyQfqFactorRepairStatus,
    gold_stock_daily_qfq_factor_repair_status,
)
from orchestrator.defs.duckdb_connection import connect_configured_duckdb
from orchestrator.defs.duckdb_sql import duckdb_string, read_parquet
from orchestrator.defs.health.lake_root import assert_lake_root_available_for_run
from orchestrator.defs.jobs.gold_stock_daily_qfq_factor_repair import (
    gold_stock_daily_qfq_factor_repair_job,
)
from orchestrator.defs.jobs.stock_daily_qfq_update import (
    gold_stock_daily_qfq_update_job,
)
from orchestrator.defs.paths import (
    DEFAULT_LAKE_ROOT,
    silver_adj_factor_path,
    silver_trade_calendar_path,
)
from orchestrator.defs.run_contracts.configs import (
    build_gold_stock_daily_qfq_factor_repair_run_config,
)
from orchestrator.defs.run_contracts.requests import build_run_request
from orchestrator.defs.run_contracts.run_keys import (
    build_batch_id,
    build_upstream_triggered_run_key,
)
from orchestrator.defs.run_contracts.sensor_tags import (
    SensorDomain,
    SensorRole,
    SensorTargetLayer,
    build_sensor_tags,
)
from orchestrator.defs.sensors.readiness import (
    GOLD_STOCK_DAILY_QFQ_READINESS_SPECS,
    partition_dataset_readiness_status_from_latest_checks,
)
from orchestrator.defs.stock_daily_qfq import (
    GOLD_STOCK_DAILY_QFQ_FACTOR_REPAIR_AUTO_CODE_LIMIT,
    GoldStockDailyQfqFactorRepairPlan,
    build_gold_stock_daily_qfq_factor_repair_plan,
)


DAGSTER_PARTITION_TAG = "dagster/partition"
GOLD_STOCK_DAILY_QFQ_FACTOR_REPAIR_SENSOR_NAME = (
    "gold_stock_daily_qfq_factor_repair_job_sensor"
)
GOLD_STOCK_DAILY_QFQ_FACTOR_REPAIR_CONSUMER = (
    "gold_stock_daily_qfq_factor_repair"
)
GOLD_STOCK_DAILY_QFQ_UPDATE_PRODUCER = "gold_stock_daily_qfq_update"


@dataclass(frozen=True)
class GoldStockDailyQfqFactorRepairRunStatusDecision:
    target_trade_date: str | None
    selected_trade_date: str | None
    reason_code: str
    reason: str
    next_action: str
    repair_required_codes_hash: str | None = None
    upstream_batch_id: str | None = None
    repair_required_code_count: int = 0


def build_gold_stock_daily_qfq_factor_repair_run_status_decision(
    *,
    target_trade_date: str | None,
    gold_stock_daily_qfq_ready: bool,
    repair_plan: GoldStockDailyQfqFactorRepairPlan | None,
    repair_status: GoldStockDailyQfqFactorRepairStatus | None,
    upstream_batch_id: str | None,
) -> GoldStockDailyQfqFactorRepairRunStatusDecision:
    if target_trade_date is None:
        return GoldStockDailyQfqFactorRepairRunStatusDecision(
            target_trade_date=None,
            selected_trade_date=None,
            reason_code="missing_target_trade_date",
            reason="Could not parse target trade date from triggering run.",
            next_action="Confirm the upstream daily qfq run has a dagster/partition tag.",
        )
    if not gold_stock_daily_qfq_ready:
        return GoldStockDailyQfqFactorRepairRunStatusDecision(
            target_trade_date=target_trade_date,
            selected_trade_date=None,
            reason_code="daily_qfq_not_ready",
            reason="Gold stock daily qfq ordinary readiness is not ready.",
            next_action="Fix target partition ordinary checks before factor repair.",
        )
    if repair_plan is None:
        return GoldStockDailyQfqFactorRepairRunStatusDecision(
            target_trade_date=target_trade_date,
            selected_trade_date=None,
            reason_code="repair_plan_unavailable",
            reason="Gold stock daily qfq factor repair plan is unavailable.",
            next_action="Check silver_adj_factor files for target and previous trade date.",
        )
    if (
        repair_plan.repair_required_code_count
        > GOLD_STOCK_DAILY_QFQ_FACTOR_REPAIR_AUTO_CODE_LIMIT
    ):
        return GoldStockDailyQfqFactorRepairRunStatusDecision(
            target_trade_date=target_trade_date,
            selected_trade_date=None,
            reason_code="repair_scope_exceeds_auto_limit",
            reason="Affected code count exceeds automatic repair limit.",
            next_action="Run a separate approved dry-run before manual repair.",
            repair_required_codes_hash=repair_plan.repair_required_codes_hash,
            repair_required_code_count=repair_plan.repair_required_code_count,
        )
    if upstream_batch_id is None:
        return GoldStockDailyQfqFactorRepairRunStatusDecision(
            target_trade_date=target_trade_date,
            selected_trade_date=None,
            reason_code="missing_upstream_batch_id",
            reason="Could not build upstream batch id for factor repair.",
            next_action="Check triggering run id and repair code hash.",
            repair_required_codes_hash=repair_plan.repair_required_codes_hash,
            repair_required_code_count=repair_plan.repair_required_code_count,
        )
    if repair_status is not None and repair_status.ready:
        return GoldStockDailyQfqFactorRepairRunStatusDecision(
            target_trade_date=target_trade_date,
            selected_trade_date=None,
            reason_code="repair_status_ready",
            reason=repair_status.reason,
            next_action="No duplicate repair run is needed.",
            repair_required_codes_hash=repair_plan.repair_required_codes_hash,
            upstream_batch_id=upstream_batch_id,
            repair_required_code_count=repair_plan.repair_required_code_count,
        )
    if repair_plan.repair_required:
        reason_code = "selected_for_repair"
        reason = "Gold stock daily qfq factor repair is required."
        next_action = "Submit scoped repair run and wait for repair status check."
    else:
        reason_code = "selected_for_reconciliation"
        reason = "No adjacent silver_adj_factor changes were found."
        next_action = "Submit no-op reconciliation and wait for durable status check."
    return GoldStockDailyQfqFactorRepairRunStatusDecision(
        target_trade_date=target_trade_date,
        selected_trade_date=target_trade_date,
        reason_code=reason_code,
        reason=reason,
        next_action=next_action,
        repair_required_codes_hash=repair_plan.repair_required_codes_hash,
        upstream_batch_id=upstream_batch_id,
        repair_required_code_count=repair_plan.repair_required_code_count,
    )


def _normalize_trade_date(value: object) -> str | None:
    raw_value = str(value or "").strip()
    if not raw_value:
        return None
    try:
        return date.fromisoformat(raw_value).isoformat()
    except ValueError:
        return None


def _trade_date_from_dagster_run(dagster_run: dg.DagsterRun) -> str | None:
    return _normalize_trade_date(dagster_run.tags.get(DAGSTER_PARTITION_TAG))


def _previous_trade_date_from_expected_dates(
    expected_trade_dates: tuple[str, ...],
    target_trade_date: str,
) -> str | None:
    previous_trade_date = None
    for expected_trade_date in expected_trade_dates:
        if expected_trade_date == target_trade_date:
            return previous_trade_date
        previous_trade_date = expected_trade_date
    return None


def _load_expected_stock_trade_dates() -> tuple[str, ...]:
    lake_root = Path(DEFAULT_LAKE_ROOT)
    assert_lake_root_available_for_run(lake_root)
    calendar_path = silver_trade_calendar_path(lake_root)
    if not calendar_path.exists():
        raise FileNotFoundError(
            f"silver_trade_calendar file is missing: {calendar_path}"
        )
    with connect_configured_duckdb() as connection:
        rows = connection.execute(
            f"""
            SELECT strftime(CAST(trade_date AS DATE), '%Y-%m-%d') AS trade_date
            FROM {read_parquet(calendar_path, hive_partitioning=False)}
            WHERE CAST(exchange AS VARCHAR) = 'SSE'
              AND CAST(is_open AS BOOLEAN)
              AND CAST(trade_date AS DATE) <= DATE {duckdb_string(date.today().isoformat())}
            ORDER BY CAST(trade_date AS DATE)
            """
        ).fetchall()
    return tuple(str(row[0]) for row in rows)


def build_gold_stock_daily_qfq_factor_repair_upstream_batch_id(
    *,
    producer_run_id: str,
    target_trade_date: str,
    repair_required_codes_hash: str,
) -> str:
    return build_batch_id(
        producer=GOLD_STOCK_DAILY_QFQ_UPDATE_PRODUCER,
        scope=target_trade_date,
        payload={
            "producer_run_id": producer_run_id,
            "qfq_factor_trade_date": target_trade_date,
            "repair_required_codes_hash": repair_required_codes_hash,
        },
    )


def _run_request_for_repair_decision(
    decision: GoldStockDailyQfqFactorRepairRunStatusDecision,
) -> dg.RunRequest:
    if decision.selected_trade_date is None:
        raise ValueError("repair decision is not selected.")
    if decision.repair_required_codes_hash is None:
        raise ValueError("repair decision is missing repair_required_codes_hash.")
    if decision.upstream_batch_id is None:
        raise ValueError("repair decision is missing upstream_batch_id.")
    return build_run_request(
        run_key=build_upstream_triggered_run_key(
            consumer=GOLD_STOCK_DAILY_QFQ_FACTOR_REPAIR_CONSUMER,
            upstream_batch_id=decision.upstream_batch_id,
        ),
        run_config=build_gold_stock_daily_qfq_factor_repair_run_config(
            qfq_factor_trade_date=decision.selected_trade_date,
            repair_required_codes_hash=decision.repair_required_codes_hash,
            upstream_batch_id=decision.upstream_batch_id,
        ),
    )


def _skip_reason(
    decision: GoldStockDailyQfqFactorRepairRunStatusDecision,
) -> dg.SkipReason:
    return dg.SkipReason(
        f"{decision.reason_code}: {decision.reason} next_action={decision.next_action}"
    )


def _evaluate_gold_stock_daily_qfq_factor_repair_job_sensor(
    context: dg.RunStatusSensorContext,
) -> dg.RunRequest | dg.SkipReason:
    target_trade_date = _trade_date_from_dagster_run(context.dagster_run)
    gold_qfq_ready = False
    repair_plan = None
    repair_status = None
    upstream_batch_id = None
    if target_trade_date is not None:
        gold_qfq_status = partition_dataset_readiness_status_from_latest_checks(
            context.instance,
            GOLD_STOCK_DAILY_QFQ_READINESS_SPECS,
            partition_key=target_trade_date,
        )
        gold_qfq_ready = gold_qfq_status.ready
        if gold_qfq_ready:
            lake_root = Path(DEFAULT_LAKE_ROOT)
            expected_trade_dates = _load_expected_stock_trade_dates()
            previous_trade_date = _previous_trade_date_from_expected_dates(
                expected_trade_dates,
                target_trade_date,
            )
            with connect_configured_duckdb() as connection:
                repair_plan = build_gold_stock_daily_qfq_factor_repair_plan(
                    connection=connection,
                    current_adj_factor_path=silver_adj_factor_path(
                        lake_root,
                        target_trade_date,
                    ),
                    previous_adj_factor_path=(
                        silver_adj_factor_path(lake_root, previous_trade_date)
                        if previous_trade_date is not None
                        else None
                    ),
                    qfq_factor_trade_date=target_trade_date,
                    previous_trade_date=previous_trade_date,
                )
            upstream_batch_id = (
                build_gold_stock_daily_qfq_factor_repair_upstream_batch_id(
                    producer_run_id=context.dagster_run.run_id,
                    target_trade_date=target_trade_date,
                    repair_required_codes_hash=repair_plan.repair_required_codes_hash,
                )
            )
            repair_status = gold_stock_daily_qfq_factor_repair_status(
                context.instance,
                target_trade_date,
                upstream_batch_id=upstream_batch_id,
            )

    decision = build_gold_stock_daily_qfq_factor_repair_run_status_decision(
        target_trade_date=target_trade_date,
        gold_stock_daily_qfq_ready=gold_qfq_ready,
        repair_plan=repair_plan,
        repair_status=repair_status,
        upstream_batch_id=upstream_batch_id,
    )
    if decision.selected_trade_date is None:
        return _skip_reason(decision)
    return _run_request_for_repair_decision(decision)


@dg.run_status_sensor(
    run_status=dg.DagsterRunStatus.SUCCESS,
    request_job=gold_stock_daily_qfq_factor_repair_job,
    monitored_jobs=[gold_stock_daily_qfq_update_job],
    default_status=dg.DefaultSensorStatus.STOPPED,
    tags=build_sensor_tags(
        sensor_domain=SensorDomain.QUOTE_DATA,
        target_layer=SensorTargetLayer.GOLD,
        role=SensorRole.ASSET_UPDATE,
    ),
    description=(
        "股票日线前复权 daily 成功后，自动提交相邻复权因子 reconciliation；"
        "无变化时写 durable no-op check，超过自动上限时只 skip。"
    ),
)
def gold_stock_daily_qfq_factor_repair_job_sensor(
    context: dg.RunStatusSensorContext,
) -> dg.RunRequest | dg.SkipReason:
    return _evaluate_gold_stock_daily_qfq_factor_repair_job_sensor(context)
