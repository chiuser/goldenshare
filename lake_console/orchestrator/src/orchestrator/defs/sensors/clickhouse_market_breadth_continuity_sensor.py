from datetime import datetime

import dagster as dg

from orchestrator.defs.asset_guards.bounded_continuity import (
    ContinuityBatchReadiness,
    ContinuityDateReadiness,
    build_continuity_cursor_details,
    build_registered_gap_status,
    load_expected_trade_date_window,
    select_first_not_ready_trade_date,
)
from orchestrator.defs.asset_guards.market_breadth_lake_readiness import (
    batch_clickhouse_market_breadth_readiness,
    batch_gold_market_breadth_lake_readiness,
    batch_gold_stock_return_distribution_lake_readiness,
    batch_prod_clickhouse_market_breadth_readiness,
)
from orchestrator.defs.partitions import cn_a_stock_trade_days
from orchestrator.defs.paths import silver_trade_calendar_path
from orchestrator.defs.run_contracts.cursors import (
    SensorCursorDecision,
    build_sensor_cursor,
)
from orchestrator.defs.run_contracts.requests import build_run_request
from orchestrator.defs.run_contracts.run_keys import build_asset_update_run_key
from orchestrator.defs.run_contracts.sensor_tags import (
    SensorDomain,
    SensorRole,
    SensorTargetLayer,
    build_sensor_tags,
)
from orchestrator.defs.sensors.cn_a_trade_day_sensor import STOCK_TRADE_DAY_MIN_DATE
from orchestrator.defs.sensors.readiness import CN_A_SENSOR_TIMEZONE
from orchestrator.defs.sensors.stock_trade_day_sensor import (
    STOCK_TRADE_DAY_REGISTER_START,
)


def _status_payload(status: ContinuityDateReadiness | None) -> dict[str, object] | None:
    return status.to_cursor_details() if status is not None else None


def _batch_payload(
    batch_status: ContinuityBatchReadiness | None,
) -> dict[str, object] | None:
    return batch_status.to_cursor_details() if batch_status else None


def _cursor_payload(
    *,
    evaluated_at: datetime,
    target_trade_date: str | None,
    registered_trade_day_count: int,
    selected_trade_date: str | None,
    reason: str,
    continuity_status: dict[str, object] | None = None,
    serving_batch_status: ContinuityBatchReadiness | None = None,
    serving_status: ContinuityDateReadiness | None = None,
    upstream_batch_statuses: dict[str, ContinuityBatchReadiness] | None = None,
    upstream_statuses: dict[str, ContinuityDateReadiness | None] | None = None,
    blocked_fallback: int = 0,
) -> str:
    selected_count = 1 if selected_trade_date else 0
    upstream_status_values = tuple((upstream_statuses or {}).values())
    blocked_count = 0
    if not selected_trade_date:
        if serving_status is not None and not serving_status.ready:
            blocked_count = 1
        elif any(status is not None and not status.ready for status in upstream_status_values):
            blocked_count = 1
        else:
            blocked_count = blocked_fallback
    reason_code = "request_run" if selected_trade_date else None
    blocked_component = None
    if reason_code is None and serving_status is not None and not serving_status.ready:
        reason_code = serving_status.reason
        blocked_component = "serving"
    if reason_code is None:
        for name, status in (upstream_statuses or {}).items():
            if status is not None and not status.ready:
                reason_code = status.reason
                blocked_component = name
                break
    if reason_code is None and continuity_status is not None:
        blocked_reason = continuity_status.get("blocked_reason")
        first_not_ready_reason = continuity_status.get("first_not_ready_reason")
        first_missing_registered_date = continuity_status.get(
            "first_missing_registered_date"
        )
        if first_missing_registered_date is not None:
            reason_code = "missing_registered_partition"
            blocked_component = "cn_a_stock_trade_days"
        elif first_not_ready_reason:
            reason_code = str(first_not_ready_reason)
            blocked_component = "serving"
        elif blocked_reason:
            reason_code = str(blocked_reason)
            blocked_component = "serving"
    if reason_code is None:
        reason_code = "no_expected_trade_date" if target_trade_date is None else "all_ready"
    return build_sensor_cursor(
        evaluated_at=evaluated_at,
        decision=(
            SensorCursorDecision.REQUEST_RUNS
            if selected_trade_date
            else SensorCursorDecision.SKIP
        ),
        target_date=target_trade_date,
        selected_count=selected_count,
        blocked_count=blocked_count,
        sample_keys=[selected_trade_date] if selected_trade_date else [],
        details={
            "registered_trade_day_count": registered_trade_day_count,
            "selected_trade_date": selected_trade_date,
            "reason_code": reason_code,
            "blocked_component": blocked_component,
            "continuity_status": continuity_status,
            "serving_batch_status": _batch_payload(serving_batch_status),
            "serving_status": _status_payload(serving_status),
            "upstream_batch_statuses": {
                name: _batch_payload(status)
                for name, status in (upstream_batch_statuses or {}).items()
            },
            "upstream_statuses": {
                name: _status_payload(status)
                for name, status in (upstream_statuses or {}).items()
            },
        },
    )


def _upstream_blocks_target(
    *,
    target_trade_date: str,
    upstream_batch_statuses: dict[str, ContinuityBatchReadiness],
) -> tuple[str | None, ContinuityDateReadiness | None]:
    for name, batch_status in upstream_batch_statuses.items():
        selection = select_first_not_ready_trade_date(
            expected_trade_dates=batch_status.expected_trade_dates,
            readiness=batch_status,
        )
        first_not_ready = selection.first_not_ready_trade_date
        if first_not_ready is None or first_not_ready > target_trade_date:
            continue
        return name, batch_status.status_for_trade_date(first_not_ready)
    return None, None


def _load_expected_window_and_gap(
    context: dg.SensorEvaluationContext,
    *,
    evaluated_at: datetime,
) -> tuple[object, object, tuple[str, ...]]:
    registered_trade_days = tuple(
        sorted(context.instance.get_dynamic_partitions(cn_a_stock_trade_days.name))
    )
    lake_root_path = context.resources.lake_root.root()
    duckdb_resource = context.resources.duckdb
    with duckdb_resource.connect() as connection:
        expected_window = load_expected_trade_date_window(
            connection,
            silver_trade_calendar_path(lake_root_path),
            evaluated_at=evaluated_at,
            min_trade_date=STOCK_TRADE_DAY_MIN_DATE,
            same_day_register_start=STOCK_TRADE_DAY_REGISTER_START,
        )
    gap_status = build_registered_gap_status(
        expected_trade_dates=expected_window.expected_trade_dates,
        registered_trade_dates=registered_trade_days,
    )
    return expected_window, gap_status, registered_trade_days


@dg.sensor(
    job_name="clickhouse_share_fact_market_breadth_update_job",
    default_status=dg.DefaultSensorStatus.STOPPED,
    minimum_interval_seconds=600,
    tags=build_sensor_tags(
        sensor_domain=SensorDomain.DERIVED_METRIC,
        target_layer=SensorTargetLayer.SERVING,
        role=SensorRole.ASSET_UPDATE,
    ),
    required_resource_keys={"lake_root", "duckdb", "clickhouse"},
    description="两个市场宽度 gold 资产 ready 后，按 bounded continuity 触发本机 ClickHouse serving 更新。",
)
def clickhouse_market_breadth_continuity_sensor(
    context: dg.SensorEvaluationContext,
) -> dg.SensorResult:
    evaluated_at = datetime.now(CN_A_SENSOR_TIMEZONE)
    expected_window, gap_status, registered_trade_days = _load_expected_window_and_gap(
        context,
        evaluated_at=evaluated_at,
    )
    if not expected_window.expected_trade_dates:
        reason = "没有符合当前窗口的股票 expected trade date，暂不触发本机 ClickHouse serving。"
        cursor = _cursor_payload(
            evaluated_at=evaluated_at,
            target_trade_date=None,
            registered_trade_day_count=len(registered_trade_days),
            selected_trade_date=None,
            reason=reason,
            blocked_fallback=1,
        )
        return dg.SensorResult(skip_reason=reason, cursor=cursor)

    if not gap_status.ready:
        continuity_status = build_continuity_cursor_details(
            expected_window=expected_window,
            gap_status=gap_status,
            batch_readiness=None,
            selection=None,
        )
        reason = (
            "本机 ClickHouse 市场宽度检测到股票交易日分区存在注册缺口，等待注册 "
            f"sensor 补齐最早缺口 {gap_status.first_missing_registered_date}。"
        )
        cursor = _cursor_payload(
            evaluated_at=evaluated_at,
            target_trade_date=gap_status.first_missing_registered_date,
            registered_trade_day_count=len(registered_trade_days),
            selected_trade_date=None,
            reason=reason,
            continuity_status=continuity_status,
            blocked_fallback=1,
        )
        return dg.SensorResult(skip_reason=reason, cursor=cursor)

    lake_root_path = context.resources.lake_root.root()
    duckdb_resource = context.resources.duckdb
    with duckdb_resource.connect() as connection:
        with context.resources.clickhouse.get_connection() as client:
            serving_batch = batch_clickhouse_market_breadth_readiness(
                connection=connection,
                lake_root_path=lake_root_path,
                clickhouse_client=client,
                expected_trade_dates=expected_window.expected_trade_dates,
            )
        breadth_batch = batch_gold_market_breadth_lake_readiness(
            connection=connection,
            lake_root_path=lake_root_path,
            expected_trade_dates=expected_window.expected_trade_dates,
        )
        distribution_batch = batch_gold_stock_return_distribution_lake_readiness(
            connection=connection,
            lake_root_path=lake_root_path,
            expected_trade_dates=expected_window.expected_trade_dates,
        )

    selection = select_first_not_ready_trade_date(
        expected_trade_dates=expected_window.expected_trade_dates,
        readiness=serving_batch,
    )
    continuity_status = build_continuity_cursor_details(
        expected_window=expected_window,
        gap_status=gap_status,
        batch_readiness=serving_batch,
        selection=selection,
    )
    target_trade_date = selection.first_not_ready_trade_date
    serving_status = selection.selected_status
    upstream_batches = {
        "gold_market_breadth_daily": breadth_batch,
        "gold_stock_return_distribution": distribution_batch,
    }

    if selection.selected_trade_date is None:
        if selection.blocked_reason == "materialized_check_failed":
            reason = "本机 ClickHouse serving 已存在但 lake-derived blocking checks 未全绿，暂不自动重跑。"
        else:
            reason = "最近 10 个 expected stock dates 的本机 ClickHouse serving 都已 ready。"
        cursor = _cursor_payload(
            evaluated_at=evaluated_at,
            target_trade_date=target_trade_date,
            registered_trade_day_count=len(registered_trade_days),
            selected_trade_date=None,
            reason=reason,
            continuity_status=continuity_status,
            serving_batch_status=serving_batch,
            serving_status=serving_status,
            upstream_batch_statuses=upstream_batches,
        )
        return dg.SensorResult(skip_reason=reason, cursor=cursor)

    target_trade_date = selection.selected_trade_date
    assert target_trade_date is not None
    blocked_name, blocked_status = _upstream_blocks_target(
        target_trade_date=target_trade_date,
        upstream_batch_statuses=upstream_batches,
    )
    if blocked_name is not None:
        reason = f"本机 ClickHouse serving 等待上游 {blocked_name} 连续 ready。"
        cursor = _cursor_payload(
            evaluated_at=evaluated_at,
            target_trade_date=target_trade_date,
            registered_trade_day_count=len(registered_trade_days),
            selected_trade_date=None,
            reason=reason,
            continuity_status=continuity_status,
            serving_batch_status=serving_batch,
            serving_status=serving_status,
            upstream_batch_statuses=upstream_batches,
            upstream_statuses={blocked_name: blocked_status},
        )
        return dg.SensorResult(skip_reason=reason, cursor=cursor)

    run_request = build_run_request(
        run_key=build_asset_update_run_key(
            subject="ch_share_fact_market_breadth_daily",
            unit_id=target_trade_date,
        ),
        partition_key=target_trade_date,
    )
    reason = "本机 ClickHouse serving 上游已 ready，提交分区更新。"
    cursor = _cursor_payload(
        evaluated_at=evaluated_at,
        target_trade_date=target_trade_date,
        registered_trade_day_count=len(registered_trade_days),
        selected_trade_date=target_trade_date,
        reason=reason,
        continuity_status=continuity_status,
        serving_batch_status=serving_batch,
        serving_status=serving_status,
        upstream_batch_statuses=upstream_batches,
    )
    return dg.SensorResult(run_requests=[run_request], cursor=cursor)


@dg.sensor(
    job_name="prod_clickhouse_share_fact_market_breadth_sync_job",
    default_status=dg.DefaultSensorStatus.STOPPED,
    minimum_interval_seconds=600,
    tags=build_sensor_tags(
        sensor_domain=SensorDomain.DERIVED_METRIC,
        target_layer=SensorTargetLayer.SERVING,
        role=SensorRole.ASSET_UPDATE,
    ),
    required_resource_keys={"lake_root", "duckdb", "clickhouse", "prod_clickhouse"},
    description="本机 ClickHouse serving ready 后，按 bounded continuity 触发 prod ClickHouse 同步。",
)
def prod_clickhouse_market_breadth_continuity_sensor(
    context: dg.SensorEvaluationContext,
) -> dg.SensorResult:
    evaluated_at = datetime.now(CN_A_SENSOR_TIMEZONE)
    expected_window, gap_status, registered_trade_days = _load_expected_window_and_gap(
        context,
        evaluated_at=evaluated_at,
    )
    if not expected_window.expected_trade_dates:
        reason = "没有符合当前窗口的股票 expected trade date，暂不触发 prod ClickHouse serving。"
        cursor = _cursor_payload(
            evaluated_at=evaluated_at,
            target_trade_date=None,
            registered_trade_day_count=len(registered_trade_days),
            selected_trade_date=None,
            reason=reason,
            blocked_fallback=1,
        )
        return dg.SensorResult(skip_reason=reason, cursor=cursor)

    if not gap_status.ready:
        continuity_status = build_continuity_cursor_details(
            expected_window=expected_window,
            gap_status=gap_status,
            batch_readiness=None,
            selection=None,
        )
        reason = (
            "Prod ClickHouse 市场宽度检测到股票交易日分区存在注册缺口，等待注册 "
            f"sensor 补齐最早缺口 {gap_status.first_missing_registered_date}。"
        )
        cursor = _cursor_payload(
            evaluated_at=evaluated_at,
            target_trade_date=gap_status.first_missing_registered_date,
            registered_trade_day_count=len(registered_trade_days),
            selected_trade_date=None,
            reason=reason,
            continuity_status=continuity_status,
            blocked_fallback=1,
        )
        return dg.SensorResult(skip_reason=reason, cursor=cursor)

    lake_root_path = context.resources.lake_root.root()
    duckdb_resource = context.resources.duckdb
    with duckdb_resource.connect() as connection:
        with (
            context.resources.clickhouse.get_connection() as local_client,
            context.resources.prod_clickhouse.get_connection() as prod_client,
        ):
            prod_batch = batch_prod_clickhouse_market_breadth_readiness(
                local_clickhouse_client=local_client,
                prod_clickhouse_client=prod_client,
                expected_trade_dates=expected_window.expected_trade_dates,
            )
            local_batch = batch_clickhouse_market_breadth_readiness(
                connection=connection,
                lake_root_path=lake_root_path,
                clickhouse_client=local_client,
                expected_trade_dates=expected_window.expected_trade_dates,
            )

    selection = select_first_not_ready_trade_date(
        expected_trade_dates=expected_window.expected_trade_dates,
        readiness=prod_batch,
    )
    continuity_status = build_continuity_cursor_details(
        expected_window=expected_window,
        gap_status=gap_status,
        batch_readiness=prod_batch,
        selection=selection,
    )
    target_trade_date = selection.first_not_ready_trade_date
    serving_status = selection.selected_status
    upstream_batches = {"ch_share_fact_market_breadth_daily": local_batch}

    if selection.selected_trade_date is None:
        if selection.blocked_reason == "materialized_check_failed":
            reason = "Prod ClickHouse serving 已存在但 lake-derived blocking checks 未全绿，暂不自动重跑。"
        else:
            reason = "最近 10 个 expected stock dates 的 prod ClickHouse serving 都已 ready。"
        cursor = _cursor_payload(
            evaluated_at=evaluated_at,
            target_trade_date=target_trade_date,
            registered_trade_day_count=len(registered_trade_days),
            selected_trade_date=None,
            reason=reason,
            continuity_status=continuity_status,
            serving_batch_status=prod_batch,
            serving_status=serving_status,
            upstream_batch_statuses=upstream_batches,
        )
        return dg.SensorResult(skip_reason=reason, cursor=cursor)

    target_trade_date = selection.selected_trade_date
    assert target_trade_date is not None
    blocked_name, blocked_status = _upstream_blocks_target(
        target_trade_date=target_trade_date,
        upstream_batch_statuses=upstream_batches,
    )
    if blocked_name is not None:
        reason = "Prod ClickHouse serving 等待本机 ClickHouse serving 连续 ready。"
        cursor = _cursor_payload(
            evaluated_at=evaluated_at,
            target_trade_date=target_trade_date,
            registered_trade_day_count=len(registered_trade_days),
            selected_trade_date=None,
            reason=reason,
            continuity_status=continuity_status,
            serving_batch_status=prod_batch,
            serving_status=serving_status,
            upstream_batch_statuses=upstream_batches,
            upstream_statuses={blocked_name: blocked_status},
        )
        return dg.SensorResult(skip_reason=reason, cursor=cursor)

    run_request = build_run_request(
        run_key=build_asset_update_run_key(
            subject="prod_ch_share_fact_market_breadth_daily",
            unit_id=target_trade_date,
        ),
        partition_key=target_trade_date,
    )
    reason = "Prod ClickHouse serving 上游已 ready，提交分区同步。"
    cursor = _cursor_payload(
        evaluated_at=evaluated_at,
        target_trade_date=target_trade_date,
        registered_trade_day_count=len(registered_trade_days),
        selected_trade_date=target_trade_date,
        reason=reason,
        continuity_status=continuity_status,
        serving_batch_status=prod_batch,
        serving_status=serving_status,
        upstream_batch_statuses=upstream_batches,
    )
    return dg.SensorResult(run_requests=[run_request], cursor=cursor)
