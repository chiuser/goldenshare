from dataclasses import dataclass
from datetime import datetime, time

import dagster as dg

from orchestrator.defs.partitions import (
    cn_a_stock_mins_silver_trade_days,
    cn_a_stock_mins_trade_days,
)
from orchestrator.defs.run_contracts.cursors import (
    SensorCursorDecision,
    build_sensor_cursor,
)
from orchestrator.defs.run_contracts.sensor_tags import (
    SensorDomain,
    SensorRole,
    SensorTargetLayer,
    build_sensor_tags,
)
from orchestrator.defs.sensors.readiness import (
    CN_A_SENSOR_TIMEZONE,
    AssetReadinessStatus,
    DatasetReadinessStatus,
    raw_stk_mins_ready_for_trade_date,
    silver_namechange_ready_for_trade_date,
    silver_stock_identity_map_ready_for_trade_date,
    status_payload,
    stock_daily_ready_for_trade_date,
    suspend_d_ready_for_trade_date,
)


STOCK_MINS_SILVER_TRADE_DAY_REGISTER_START = time(22, 30)
STOCK_MINS_SILVER_HISTORY_START_DATE = "2014-01-01"


@dataclass(frozen=True)
class StockMinsSilverTradeDayRegistrationDecision:
    target_trade_date: str | None
    register_window_started: bool
    already_registered: bool
    selected_keys: tuple[str, ...]
    reason: str


def _latest_registered_raw_trade_date(
    raw_registered_trade_days: tuple[str, ...],
    evaluated_at: datetime,
) -> str | None:
    today = evaluated_at.date().isoformat()
    eligible_trade_days = tuple(
        trade_date
        for trade_date in raw_registered_trade_days
        if STOCK_MINS_SILVER_HISTORY_START_DATE <= trade_date <= today
    )
    return eligible_trade_days[-1] if eligible_trade_days else None


def build_stock_mins_silver_trade_day_registration_decision(
    *,
    target_trade_date: str | None,
    register_window_started: bool,
    already_registered: bool,
    raw_ready: bool = False,
    stock_daily_ready: bool = False,
    suspend_ready: bool = False,
    identity_map_ready: bool = False,
    namechange_ready: bool = False,
) -> StockMinsSilverTradeDayRegistrationDecision:
    if target_trade_date is None:
        return StockMinsSilverTradeDayRegistrationDecision(
            target_trade_date=None,
            register_window_started=register_window_started,
            already_registered=False,
            selected_keys=(),
            reason="没有 2014-01-01 之后的股票分钟线 raw 交易日分区。",
        )
    if not register_window_started:
        return StockMinsSilverTradeDayRegistrationDecision(
            target_trade_date=target_trade_date,
            register_window_started=False,
            already_registered=already_registered,
            selected_keys=(),
            reason="股票分钟线 silver 分区注册窗口尚未到 22:30，暂不注册。",
        )
    if already_registered:
        return StockMinsSilverTradeDayRegistrationDecision(
            target_trade_date=target_trade_date,
            register_window_started=True,
            already_registered=True,
            selected_keys=(),
            reason="最新股票分钟线 silver 交易日分区已经注册。",
        )
    if not raw_ready:
        reason = "股票分钟线 raw 五频度尚未全部 ready，暂不注册 silver 交易日分区。"
    elif not stock_daily_ready:
        reason = "股票日线尚未 ready，暂不注册股票分钟线 silver 交易日分区。"
    elif not suspend_ready:
        reason = "停复牌数据尚未 ready，暂不注册股票分钟线 silver 交易日分区。"
    elif not identity_map_ready:
        reason = "股票身份映射尚未满足当日 freshness，暂不注册股票分钟线 silver 交易日分区。"
    elif not namechange_ready:
        reason = "股票曾用名尚未满足当日 freshness，暂不注册股票分钟线 silver 交易日分区。"
    else:
        return StockMinsSilverTradeDayRegistrationDecision(
            target_trade_date=target_trade_date,
            register_window_started=True,
            already_registered=False,
            selected_keys=(target_trade_date,),
            reason="股票分钟线 silver 前置门禁已满足，注册 silver 交易日分区。",
        )

    return StockMinsSilverTradeDayRegistrationDecision(
        target_trade_date=target_trade_date,
        register_window_started=True,
        already_registered=False,
        selected_keys=(),
        reason=reason,
    )


def _asset_status_payload(status: AssetReadinessStatus | None) -> dict[str, object] | None:
    if status is None:
        return None
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


def _cursor_payload(
    *,
    decision: StockMinsSilverTradeDayRegistrationDecision,
    evaluated_at: datetime,
    raw_registered_trade_day_count: int,
    silver_registered_trade_day_count: int,
    raw_status: DatasetReadinessStatus | None = None,
    stock_daily_status: DatasetReadinessStatus | None = None,
    suspend_status: DatasetReadinessStatus | None = None,
    identity_map_status: AssetReadinessStatus | None = None,
    namechange_status: AssetReadinessStatus | None = None,
) -> str:
    cursor_decision = (
        SensorCursorDecision.REGISTER_PARTITIONS
        if decision.selected_keys
        else SensorCursorDecision.SKIP
    )
    blocked_count = 0
    if not decision.selected_keys and not decision.already_registered:
        for status in (raw_status, stock_daily_status, suspend_status):
            if status is not None and not status.ready:
                blocked_count += len(
                    [
                        asset_status
                        for asset_status in status.statuses
                        if not asset_status.ready
                    ]
                )
        for status in (identity_map_status, namechange_status):
            if status is not None and not status.ready:
                blocked_count += 1
        if blocked_count == 0 and decision.target_trade_date is not None:
            blocked_count = 1

    return build_sensor_cursor(
        evaluated_at=evaluated_at,
        decision=cursor_decision,
        target_date=decision.target_trade_date,
        selected_count=len(decision.selected_keys),
        blocked_count=blocked_count,
        sample_keys=decision.selected_keys,
        details={
            "raw_partition_set": cn_a_stock_mins_trade_days.name,
            "partition_set": cn_a_stock_mins_silver_trade_days.name,
            "raw_registered_trade_day_count": raw_registered_trade_day_count,
            "silver_registered_trade_day_count": silver_registered_trade_day_count,
            "register_window_started": decision.register_window_started,
            "already_registered": decision.already_registered,
            "selected_keys": list(decision.selected_keys),
            "reason": decision.reason,
            "raw_status": status_payload(raw_status) if raw_status else None,
            "stock_daily_status": (
                status_payload(stock_daily_status) if stock_daily_status else None
            ),
            "suspend_status": status_payload(suspend_status) if suspend_status else None,
            "identity_map_status": _asset_status_payload(identity_map_status),
            "namechange_status": _asset_status_payload(namechange_status),
        },
    )


@dg.sensor(
    default_status=dg.DefaultSensorStatus.STOPPED,
    minimum_interval_seconds=600,
    tags=build_sensor_tags(
        sensor_domain=SensorDomain.QUOTE_DATA,
        target_layer=SensorTargetLayer.PARTITION,
        role=SensorRole.PARTITION_REGISTRATION,
    ),
    description=(
        "每天 22:30 后，在分钟线 raw、日线、停复牌、身份映射和曾用名门禁满足后，"
        "注册股票分钟线 silver 交易日分区；不触发 silver job。"
    ),
)
def stock_mins_silver_trade_day_sensor(
    context: dg.SensorEvaluationContext,
) -> dg.SensorResult:
    evaluated_at = datetime.now(CN_A_SENSOR_TIMEZONE)
    register_window_started = (
        evaluated_at.time() >= STOCK_MINS_SILVER_TRADE_DAY_REGISTER_START
    )
    raw_registered_trade_days = tuple(
        sorted(
            context.instance.get_dynamic_partitions(
                cn_a_stock_mins_trade_days.name
            )
        )
    )
    silver_registered_trade_days = set(
        context.instance.get_dynamic_partitions(cn_a_stock_mins_silver_trade_days.name)
    )
    target_trade_date = _latest_registered_raw_trade_date(
        raw_registered_trade_days,
        evaluated_at,
    )
    already_registered = (
        target_trade_date is not None and target_trade_date in silver_registered_trade_days
    )

    raw_status = None
    stock_daily_status = None
    suspend_status = None
    identity_map_status = None
    namechange_status = None
    if target_trade_date is not None and register_window_started and not already_registered:
        raw_status = raw_stk_mins_ready_for_trade_date(
            context.instance,
            target_trade_date,
        )
        stock_daily_status = stock_daily_ready_for_trade_date(
            context.instance,
            target_trade_date,
        )
        suspend_status = suspend_d_ready_for_trade_date(
            context.instance,
            target_trade_date,
        )
        identity_map_status = silver_stock_identity_map_ready_for_trade_date(
            context.instance,
            target_trade_date,
        )
        namechange_status = silver_namechange_ready_for_trade_date(
            context.instance,
            target_trade_date,
        )

    decision = build_stock_mins_silver_trade_day_registration_decision(
        target_trade_date=target_trade_date,
        register_window_started=register_window_started,
        already_registered=already_registered,
        raw_ready=raw_status.ready if raw_status else False,
        stock_daily_ready=stock_daily_status.ready if stock_daily_status else False,
        suspend_ready=suspend_status.ready if suspend_status else False,
        identity_map_ready=identity_map_status.ready if identity_map_status else False,
        namechange_ready=namechange_status.ready if namechange_status else False,
    )
    cursor = _cursor_payload(
        decision=decision,
        evaluated_at=evaluated_at,
        raw_registered_trade_day_count=len(raw_registered_trade_days),
        silver_registered_trade_day_count=len(silver_registered_trade_days),
        raw_status=raw_status,
        stock_daily_status=stock_daily_status,
        suspend_status=suspend_status,
        identity_map_status=identity_map_status,
        namechange_status=namechange_status,
    )

    if not decision.selected_keys:
        return dg.SensorResult(skip_reason=decision.reason, cursor=cursor)

    return dg.SensorResult(
        dynamic_partitions_requests=[
            cn_a_stock_mins_silver_trade_days.build_add_request(
                list(decision.selected_keys)
            )
        ],
        cursor=cursor,
    )
