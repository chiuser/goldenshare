from dataclasses import dataclass
from datetime import datetime, time

import dagster as dg

from orchestrator.defs.asset_guards.stk_mins_continuity import (
    StockMinsContinuityStatus,
    build_registered_gap_status,
    load_stock_mins_expected_trade_dates,
    select_first_not_ready_trade_date,
)
from orchestrator.defs.asset_guards.stk_mins_lake_readiness import (
    StkMinsBatchReadiness,
    StkMinsDateReadiness,
    batch_raw_stk_mins_lake_readiness,
)
from orchestrator.defs.partitions import (
    cn_a_stock_mins_silver_trade_days,
    cn_a_stock_mins_trade_days,
)
from orchestrator.defs.paths import silver_trade_calendar_path
from orchestrator.defs.run_contracts.cursors import (
    SensorCursorDecision,
    build_sensor_cursor,
)
from orchestrator.defs.run_contracts.stk_mins import (
    STK_MINS_CONTINUITY_WINDOW_LIMIT,
    STK_MINS_SILVER_HISTORY_START_DATE,
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
    silver_stock_identity_map_ready_for_trade_date,
    status_payload,
    stock_daily_ready_for_trade_date,
    suspend_d_ready_for_trade_date,
)


STOCK_MINS_SILVER_TRADE_DAY_REGISTER_START = time(19, 45)


@dataclass(frozen=True)
class StockMinsSilverTradeDayRegistrationDecision:
    target_trade_date: str | None
    register_window_started: bool
    already_registered: bool
    selected_keys: tuple[str, ...]
    reason: str


def _load_stock_mins_silver_expected_trade_dates(
    context: dg.SensorEvaluationContext,
    evaluated_at: datetime,
) -> tuple[str, ...]:
    lake_root = context.resources.lake_root
    duckdb_resource = context.resources.duckdb

    lake_root.ensure_available_for_run()
    calendar_path = silver_trade_calendar_path(lake_root.root())
    if not calendar_path.exists():
        raise FileNotFoundError(f"silver_trade_calendar file is missing: {calendar_path}")

    with duckdb_resource.connect() as connection:
        return load_stock_mins_expected_trade_dates(
            connection,
            calendar_path,
            min_trade_date=STK_MINS_SILVER_HISTORY_START_DATE,
            evaluated_at=evaluated_at,
            same_day_register_start=STOCK_MINS_SILVER_TRADE_DAY_REGISTER_START,
        )


def _continuity_window(expected_trade_dates: tuple[str, ...]) -> tuple[str, ...]:
    return expected_trade_dates[-STK_MINS_CONTINUITY_WINDOW_LIMIT:]


def _target_trade_date_from_continuity_status(
    status: StockMinsContinuityStatus,
) -> str | None:
    return (
        status.next_actionable_trade_date
        or status.first_missing_registered_date
        or status.ready_through_trade_date
        or status.expected_end_date
    )


def build_stock_mins_silver_trade_day_registration_decision(
    *,
    target_trade_date: str | None,
    register_window_started: bool,
    already_registered: bool,
    raw_ready: bool = False,
    stock_daily_ready: bool = False,
    suspend_ready: bool = False,
    identity_map_ready: bool = False,
) -> StockMinsSilverTradeDayRegistrationDecision:
    if target_trade_date is None:
        return StockMinsSilverTradeDayRegistrationDecision(
            target_trade_date=None,
            register_window_started=register_window_started,
            already_registered=False,
            selected_keys=(),
            reason=(
                "没有 "
                f"{STK_MINS_SILVER_HISTORY_START_DATE} 之后的股票分钟线 expected 交易日。"
            ),
        )
    if not register_window_started:
        return StockMinsSilverTradeDayRegistrationDecision(
            target_trade_date=target_trade_date,
            register_window_started=False,
            already_registered=already_registered,
            selected_keys=(),
            reason="股票分钟线 silver 分区注册窗口尚未到 19:45，暂不注册。",
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


def _lake_status_has_materialized_check_problem(
    status: StkMinsDateReadiness,
) -> bool:
    return status.materialized and not status.checks_passed


def _lake_status_payload(status: StkMinsDateReadiness | None) -> dict[str, object] | None:
    if status is None:
        return None
    return status.to_cursor_details()


def _batch_status_payload(
    status: StkMinsBatchReadiness | None,
) -> dict[str, object] | None:
    if status is None:
        return None
    return {
        "dataset": status.dataset,
        "expected_start_date": status.expected_start_date,
        "expected_end_date": status.expected_end_date,
        "expected_count": status.expected_count,
        "freq_count": status.freq_count,
        "elapsed_ms": status.elapsed_ms,
    }


def _cursor_payload(
    *,
    decision: StockMinsSilverTradeDayRegistrationDecision,
    evaluated_at: datetime,
    raw_registered_trade_day_count: int,
    silver_registered_trade_day_count: int,
    raw_status: StkMinsDateReadiness | None = None,
    stock_daily_status: DatasetReadinessStatus | None = None,
    suspend_status: DatasetReadinessStatus | None = None,
    identity_map_status: AssetReadinessStatus | None = None,
    raw_continuity_status: StockMinsContinuityStatus | None = None,
    silver_continuity_status: StockMinsContinuityStatus | None = None,
    raw_batch_status: StkMinsBatchReadiness | None = None,
) -> str:
    cursor_decision = (
        SensorCursorDecision.REGISTER_PARTITIONS
        if decision.selected_keys
        else SensorCursorDecision.SKIP
    )
    blocked_count = 0
    if not decision.selected_keys and not decision.already_registered:
        for status in (stock_daily_status, suspend_status):
            if status is not None and not status.ready:
                blocked_count += len(
                    [
                        asset_status
                        for asset_status in status.statuses
                        if not asset_status.ready
                    ]
                )
        if raw_status is not None and not raw_status.ready:
            blocked_count += max(1, len(raw_status.failed_check_names))
        if identity_map_status is not None and not identity_map_status.ready:
            blocked_count += 1
        if raw_continuity_status is not None and raw_continuity_status.blocked:
            blocked_count += 1
        if (
            silver_continuity_status is not None
            and silver_continuity_status.blocked
            and not decision.selected_keys
            and raw_continuity_status is not None
            and not raw_continuity_status.blocked
        ):
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
            "raw_status": _lake_status_payload(raw_status),
            "raw_batch_status": _batch_status_payload(raw_batch_status),
            "stock_daily_status": (
                status_payload(stock_daily_status) if stock_daily_status else None
            ),
            "suspend_status": status_payload(suspend_status) if suspend_status else None,
            "identity_map_status": _asset_status_payload(identity_map_status),
            "raw_continuity_status": (
                raw_continuity_status.to_cursor_details()
                if raw_continuity_status is not None
                else None
            ),
            "silver_continuity_status": (
                silver_continuity_status.to_cursor_details()
                if silver_continuity_status is not None
                else None
            ),
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
    required_resource_keys={"lake_root", "duckdb"},
    description=(
        "每天 19:45 后，在分钟线 raw、日线、停复牌和身份映射门禁满足后，"
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
    expected_trade_dates = _continuity_window(
        _load_stock_mins_silver_expected_trade_dates(context, evaluated_at)
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
    raw_continuity_status = build_registered_gap_status(
        partition_set_name=cn_a_stock_mins_trade_days.name,
        expected_trade_dates=expected_trade_dates,
        registered_trade_days=raw_registered_trade_days,
    )
    raw_batch_status: StkMinsBatchReadiness | None = None

    def _batch_raw_status_for_trade_date(trade_date: str) -> StkMinsDateReadiness:
        nonlocal raw_batch_status
        if raw_batch_status is None:
            lake_root = context.resources.lake_root
            duckdb_resource = context.resources.duckdb
            with duckdb_resource.connect() as connection:
                raw_batch_status = batch_raw_stk_mins_lake_readiness(
                    connection=connection,
                    lake_root=lake_root.root(),
                    expected_trade_dates=expected_trade_dates,
                    registered_trade_days=raw_registered_trade_days,
                    full_semantics=True,
                )
        return raw_batch_status.status_for_trade_date(trade_date)

    raw_readiness_selection = (
        select_first_not_ready_trade_date(
            partition_set_name=cn_a_stock_mins_trade_days.name,
            expected_trade_dates=expected_trade_dates,
            registered_trade_days=raw_registered_trade_days,
            readiness_for_trade_date=_batch_raw_status_for_trade_date,
            has_materialized_check_problem=_lake_status_has_materialized_check_problem,
        )
        if raw_continuity_status.first_missing_registered_date is None
        else None
    )
    silver_continuity_status = (
        build_registered_gap_status(
            partition_set_name=cn_a_stock_mins_silver_trade_days.name,
            expected_trade_dates=expected_trade_dates,
            registered_trade_days=tuple(sorted(silver_registered_trade_days)),
        )
        if raw_continuity_status.first_missing_registered_date is None
        else None
    )

    raw_status = None
    stock_daily_status = None
    suspend_status = None
    identity_map_status = None
    if not expected_trade_dates:
        decision = StockMinsSilverTradeDayRegistrationDecision(
            target_trade_date=None,
            register_window_started=register_window_started,
            already_registered=False,
            selected_keys=(),
            reason=(
                "没有 "
                f"{STK_MINS_SILVER_HISTORY_START_DATE} 之后的股票分钟线 expected 交易日。"
            ),
        )
    elif raw_continuity_status.first_missing_registered_date is not None:
        decision = StockMinsSilverTradeDayRegistrationDecision(
            target_trade_date=raw_continuity_status.first_missing_registered_date,
            register_window_started=register_window_started,
            already_registered=False,
            selected_keys=(),
            reason=(
                "股票分钟线 raw 交易日分区存在缺口，"
                f"最早缺失日期为 {raw_continuity_status.first_missing_registered_date}，"
                "暂不注册 silver 交易日分区。"
            ),
        )
    elif silver_continuity_status is None:
        raise RuntimeError("silver_continuity_status must be set when raw partitions are continuous.")
    elif silver_continuity_status.first_missing_registered_date is None:
        decision = StockMinsSilverTradeDayRegistrationDecision(
            target_trade_date=_target_trade_date_from_continuity_status(
                silver_continuity_status
            ),
            register_window_started=register_window_started,
            already_registered=True,
            selected_keys=(),
            reason="股票分钟线 silver continuity 窗口内交易日分区已经注册。",
        )
    else:
        target_trade_date = silver_continuity_status.first_missing_registered_date
        raw_first_not_ready_trade_date = (
            raw_readiness_selection.status.first_not_ready_trade_date
            if raw_readiness_selection is not None
            else None
        )
        raw_status = (
            raw_readiness_selection.selected_status
            if isinstance(raw_readiness_selection.selected_status, StkMinsDateReadiness)
            else None
        ) if raw_readiness_selection is not None else None
        if (
            raw_first_not_ready_trade_date is not None
            and raw_first_not_ready_trade_date <= target_trade_date
        ):
            if raw_status is None:
                raw_status = _batch_raw_status_for_trade_date(
                    raw_first_not_ready_trade_date
                )
            decision = StockMinsSilverTradeDayRegistrationDecision(
                target_trade_date=raw_first_not_ready_trade_date,
                register_window_started=register_window_started,
                already_registered=False,
                selected_keys=(),
                reason=(
                    "股票分钟线 raw continuity 窗口存在未 ready 日期，"
                    f"最早日期为 {raw_first_not_ready_trade_date}，"
                    "暂不注册后续 silver 交易日分区。"
                ),
            )
        else:
            if register_window_started:
                raw_status = _batch_raw_status_for_trade_date(target_trade_date)
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

            decision = build_stock_mins_silver_trade_day_registration_decision(
                target_trade_date=target_trade_date,
                register_window_started=register_window_started,
                already_registered=False,
                raw_ready=raw_status.ready if raw_status else False,
                stock_daily_ready=stock_daily_status.ready if stock_daily_status else False,
                suspend_ready=suspend_status.ready if suspend_status else False,
                identity_map_ready=identity_map_status.ready if identity_map_status else False,
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
        raw_continuity_status=raw_continuity_status,
        silver_continuity_status=silver_continuity_status,
        raw_batch_status=raw_batch_status,
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
