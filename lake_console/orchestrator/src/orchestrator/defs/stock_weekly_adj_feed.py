"""Bounded adjusted feed decisions for the single retained weekly source."""

from dataclasses import dataclass

import dagster as dg

from orchestrator.defs.asset_guards.stk_mins_qfq_factor_repair import (
    asset_check_record_evaluation,
    asset_check_record_succeeded,
)
from orchestrator.defs.bootstrap.stock_weekly_capture import WeeklyCaptureError
from orchestrator.defs.partitions import cn_a_stock_week_ends
from orchestrator.defs.prod_db.stock_weekly_adj_delivery import (
    PsqlWeeklyAdjDeliveryReader,
)
from orchestrator.defs.run_contracts.stock_weekly import (
    StockWeeklySource,
    weekly_check_names,
    weekly_job_name,
)
from orchestrator.defs.run_contracts.stock_weekly_adj_delivery import (
    ADJUSTED_DELIVERY_ASSET,
    WeeklyAdjProdDeliveryBudget,
    build_adjusted_delivery_run_request,
    delivery_batch_id,
    delivery_revision,
)
from orchestrator.defs.stock_weekly_adj_run import DELIVERY_METADATA_KEY

SOURCE = StockWeeklySource.PRIMARY_ADJUSTED


@dataclass(frozen=True)
class AdjustedFeedDecision:
    reason: str
    summary: str
    week: str | None = None
    request: dg.RunRequest | None = None
    register: bool = False
    priority: bool = False


def _matching_run(run, pending):
    from orchestrator.defs.run_contracts.configs import StockWeeklyAdjProdConfig

    config = (
        run.run_config.get("ops", {}).get(ADJUSTED_DELIVERY_ASSET, {}).get("config", {})
    )
    try:
        normalized = StockWeeklyAdjProdConfig(**config).model_dump()
    except ValueError:
        return False
    return normalized == {
        "contract_version": 1,
        "delivery_batch_id": pending["batch_id"],
        "closure_revision": pending["revision"],
    }


def _completed_run(instance, run, pending):
    records = instance.get_records_for_run(
        run.run_id,
        of_type=dg.DagsterEventType.ASSET_MATERIALIZATION,
        limit=1,
        ascending=False,
    ).records
    if not records:
        return False
    record = records[0]
    materialization = record.asset_materialization
    value = materialization.metadata.get(DELIVERY_METADATA_KEY)
    summary = value.value if value is not None else None
    if (
        materialization.asset_key != dg.AssetKey(ADJUSTED_DELIVERY_ASSET)
        or materialization.partition != pending["anchor"]
        or not isinstance(summary, dict)
        or summary.get("contract_version") != 1
        or summary.get("batch_id") != pending["batch_id"]
        or summary.get("closure_revision") != pending["revision"]
        or summary.get("complete") is not True
        or summary.get("input_rows") != pending["rows_written"]
    ):
        return False
    files = summary.get("files_expected")
    if (
        type(files) is not int
        or not 1 <= files <= WeeklyAdjProdDeliveryBudget().max_target_files
        or summary.get("files_verified") != files
        or summary.get("historical_materializations") != files - 1
        or summary.get("historical_checks") != (files - 1) * 3
        or summary.get("anchor_checks_expected") != 3
    ):
        return False
    from dagster._core.event_api import PartitionKeyFilter

    checks = instance.event_log_storage.get_latest_asset_check_execution_by_key(
        [
            dg.AssetCheckKey(materialization.asset_key, n)
            for n in weekly_check_names(SOURCE)
        ],
        partition_filter=PartitionKeyFilter(key=pending["anchor"]),
    )
    if len(checks) != 3:
        return False
    for check in checks.values():
        evaluation = asset_check_record_evaluation(check)
        target = getattr(evaluation, "target_materialization_data", None)
        if (
            not asset_check_record_succeeded(check)
            or not getattr(evaluation, "blocking", False)
            or target is None
            or target.storage_id != record.storage_id
            or target.run_id != run.run_id
            or target.timestamp != record.event_log_entry.timestamp
        ):
            return False
    return True


def evaluate_adjusted_feed(context, runtime, *, reader=None):
    """At most one next-head query, one optional empty control, bounded run lookups."""
    revision = runtime.get("adjusted_delivery_revision")
    if revision is None:
        return AdjustedFeedDecision(
            "adjusted_bootstrap_required",
            "复权周线尚未设置新bootstrap交接边界B0；等待该边界，不提交任务。",
        )
    try:
        revision = delivery_revision(revision)
        pending = runtime.get("pending_adjusted")
        if pending:
            delivery_batch_id(pending["batch_id"])
            delivery_revision(pending["revision"])
            if pending["revision"] <= revision:
                raise ValueError("adjusted_delivery_pending_revision_invalid")
            runs = context.instance.get_runs(
                filters=dg.RunsFilter(job_name=weekly_job_name(SOURCE)), limit=1
            )
            run = runs[0] if runs and _matching_run(runs[0], pending) else None
            if run is None:
                from dagster._core.storage.tags import RUN_KEY_TAG

                runs = context.instance.get_runs(
                    filters=dg.RunsFilter(
                        job_name=weekly_job_name(SOURCE),
                        tags={RUN_KEY_TAG: pending["run_key"]},
                    ),
                    limit=1,
                )
                run = runs[0] if runs and _matching_run(runs[0], pending) else None
            if run is None:
                return AdjustedFeedDecision(
                    "adjusted_pending_not_found",
                    "已记录待交付复权批，尚未找到同批运行；保留该批，不重复提交。",
                    week=pending["anchor"],
                )
            if run.status is not dg.DagsterRunStatus.SUCCESS:
                return AdjustedFeedDecision(
                    "adjusted_manual_retry_required",
                    "复权批失败、取消或尚未完成；在该run页面重试同批配置，保留原批，不领取新批。",
                    week=pending["anchor"],
                )
            if not _completed_run(context.instance, run, pending):
                return AdjustedFeedDecision(
                    "adjusted_batch_summary_invalid",
                    "run成功，但完整交付摘要或anchor检查绑定未通过；保留该批，需要人工审计。",
                    week=pending["anchor"],
                )
            revision = pending["revision"]
            runtime["adjusted_delivery_revision"] = revision
            runtime.pop("pending_adjusted", None)
        reader = reader or PsqlWeeklyAdjDeliveryReader()
        header = reader.next_closed_batch(revision)
        if header is None:
            return AdjustedFeedDecision(
                "adjusted_waiting_prod", "没有新的Prod闭合复权批，等待Prod交付。"
            )
        header.validate_budget(WeeklyAdjProdDeliveryBudget())
        if header.record_kind != "batch_closed" or header.header["bootstrap"]:
            return AdjustedFeedDecision(
                "adjusted_bootstrap_requires_migration",
                "下一条交接是bootstrap边界，需要完成文件与事件阶段后迁移水位。",
            )
        if header.rows_written == 0:
            reader.verify_empty_batch(header)
            runtime["adjusted_delivery_revision"] = header.revision
            return AdjustedFeedDecision(
                "adjusted_empty_consumed",
                "本批合法空结果已核验，推进交接水位；不创建文件、物化或通过检查。",
                priority=True,
            )
        request = build_adjusted_delivery_run_request(header)
        runtime["pending_adjusted"] = {
            "batch_id": header.batch_id,
            "revision": header.revision,
            "anchor": header.anchor_partition,
            "rows_written": header.rows_written,
            "run_key": request.run_key,
        }
        register = not context.instance.has_dynamic_partition(
            cn_a_stock_week_ends.name, header.anchor_partition
        )
        return AdjustedFeedDecision(
            "request_adjusted_batch",
            f"接收Prod复权闭合批 {header.batch_id}，revision={header.revision}；包含本批历史修正。",
            week=header.anchor_partition,
            request=request,
            register=register,
            priority=True,
        )
    except (WeeklyCaptureError, ValueError, OSError, KeyError, TypeError):
        return AdjustedFeedDecision(
            "adjusted_feed_blocked",
            "Prod交接头、版本、预算或待交付批无法安全核验；查看原批并处理，不自动使用备用源。",
        )
