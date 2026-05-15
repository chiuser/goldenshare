from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from lake_console.backend.app.services.stk_mins_pipeline_planner import STK_MINS_PIPELINE_PROFILE_KEY


FINISHED_RUN_STATUSES = {"success", "failed", "backup_failed", "cancelled", "stopped_after_stage"}
CONFIRMATION_OPERATOR_FALLBACK = "local_operator"


class StkMinsPipelineRunStateError(RuntimeError):
    pass


class StkMinsPipelineRunNotWaitingConfirmationError(StkMinsPipelineRunStateError):
    pass


class StkMinsPipelineRunAlreadyFinishedError(StkMinsPipelineRunStateError):
    pass


def build_initial_pipeline_run(*, plan: dict[str, Any], plan_token: str, run_id: str, started_at: str) -> dict[str, Any]:
    stages = deepcopy(list(plan.get("pipeline_stages") or []))
    current_stage = _current_stage(stages)
    return _with_runtime_fields(
        {
            "run_id": run_id,
            "profile_key": STK_MINS_PIPELINE_PROFILE_KEY,
            "plan_token": plan_token,
            "status": "planned",
            "run_status": "planned",
            "started_at": started_at,
            "finished_at": None,
            "backup": None,
            "normalized_parameters": dict(plan.get("normalized_parameters") or {}),
            "affected_trade_dates": list(plan.get("affected_trade_dates") or []),
            "affected_months": list(plan.get("affected_months") or []),
            "progress": {
                "summary": "stk_mins_sync 阶段化 run 已创建；当前只登记状态，不执行 Kopia、不写入 Lake。",
                "current_dataset_key": "stk_mins",
                "current_partition": None,
            },
            "pipeline_stages": stages,
            "dataset_results": [],
            "errors": [],
        },
        current_stage=current_stage,
    )


def start_prewrite_backup_stage(*, run: dict[str, Any]) -> dict[str, Any]:
    stages = deepcopy(list(run.get("pipeline_stages") or []))
    stage = _stage_by_key(stages, "prewrite_backup")
    if stage is not None:
        stage["stage_status"] = "running"
        stage["stage_status_label"] = "执行中"
        stage["display_summary"] = "正在创建 Kopia 写前备份。"
    return _with_runtime_fields(
        {
            **run,
            "status": "backup_running",
            "run_status": "backup_running",
            "pipeline_stages": stages,
            "progress": {
                **dict(run.get("progress") or {}),
                "summary": "正在创建 Kopia 写前备份；尚未执行任何 Lake 分区写入。",
            },
        },
        current_stage=stage,
    )


def complete_prewrite_backup_stage(*, run: dict[str, Any], backup: dict[str, Any]) -> dict[str, Any]:
    stages = deepcopy(list(run.get("pipeline_stages") or []))
    stage = _stage_by_key(stages, "prewrite_backup")
    if stage is not None:
        stage["stage_status"] = "passed"
        stage["stage_status_label"] = "已通过"
        stage["display_summary"] = (
            f"Kopia 写前备份完成：{len(backup.get('snapshot_ids') or [])} 个 snapshot，"
            f"{len(backup.get('path_missing_before_write') or [])} 个写前不存在路径。"
        )
        stage["output_summary"] = {
            "provider": backup.get("provider"),
            "status": backup.get("status"),
            "snapshot_ids": backup.get("snapshot_ids") or [],
            "snapshot_paths": backup.get("snapshot_paths") or [],
            "backup_paths": backup.get("backup_paths") or [],
            "path_missing_before_write": backup.get("path_missing_before_write") or [],
        }
        stage["metrics"] = {
            **dict(stage.get("metrics") or {}),
            "snapshot_count": len(backup.get("snapshot_ids") or []),
            "snapshot_path_count": len(backup.get("snapshot_paths") or []),
            "backup_path_count": len(backup.get("backup_paths") or []),
            "path_missing_before_write_count": len(backup.get("path_missing_before_write") or []),
        }
        stage["artifacts"] = backup.get("snapshots") or []
    next_stage = _current_stage(stages)
    return _with_runtime_fields(
        {
            **run,
            "status": "backup_completed",
            "run_status": "backup_completed",
            "backup": backup,
            "pipeline_stages": stages,
            "progress": {
                **dict(run.get("progress") or {}),
                "summary": "Kopia 写前备份已完成；本阶段不会继续执行 raw/clean/derived/research 写入。",
            },
        },
        current_stage=next_stage,
    )


def start_raw_sync_stage(*, run: dict[str, Any]) -> dict[str, Any]:
    stages = deepcopy(list(run.get("pipeline_stages") or []))
    stage = _stage_by_key(stages, "raw_sync")
    if stage is not None:
        stage["stage_status"] = "running"
        stage["stage_status_label"] = "执行中"
        stage["display_summary"] = "正在同步 raw 分钟线；clean_next/gate 会在 raw 完成后刷新。"
    return _with_runtime_fields(
        {
            **run,
            "status": "running",
            "run_status": "running",
            "pipeline_stages": stages,
            "progress": {
                **dict(run.get("progress") or {}),
                "summary": "正在同步 raw 分钟线。",
            },
        },
        current_stage=stage,
    )


def complete_raw_and_clean_next_stages(*, run: dict[str, Any], summary: dict[str, Any]) -> dict[str, Any]:
    if str(summary.get("status") or "success") != "success":
        return fail_pipeline_stage(
            run=run,
            stage_key="raw_sync",
            error={
                "code": "STK_MINS_RAW_SYNC_NOT_COMPLETE",
                "message": f"raw 同步未完整完成：status={summary.get('status')}",
                "context": summary,
            },
        )

    clean_next_refresh = dict(summary.get("clean_next_refresh") or {})
    if str(clean_next_refresh.get("status") or "") != "passed":
        return fail_pipeline_stage(
            run=run,
            stage_key="clean_next_refresh",
            error={
                "code": "STK_MINS_CLEAN_NEXT_REFRESH_FAILED",
                "message": f"clean_next refresh 未通过：status={clean_next_refresh.get('status')}",
                "context": clean_next_refresh,
            },
        )

    stages = deepcopy(list(run.get("pipeline_stages") or []))
    raw_stage = _stage_by_key(stages, "raw_sync")
    if raw_stage is not None:
        raw_stage["stage_status"] = "passed"
        raw_stage["stage_status_label"] = "已通过"
        raw_stage["display_summary"] = (
            f"raw 同步完成：{int(summary.get('trade_date_count') or 0)} 个交易日，"
            f"{len(summary.get('freqs') or [])} 个频率，"
            f"写入 {int(summary.get('written_rows') or 0):,} 行。"
        )
        raw_stage["output_summary"] = {
            "run_id": summary.get("run_id"),
            "mode": summary.get("mode"),
            "start_date": summary.get("start_date"),
            "end_date": summary.get("end_date"),
            "trade_dates": summary.get("trade_dates") or [],
            "freqs": summary.get("freqs") or [],
            "affected_partitions": summary.get("affected_partitions") or [],
        }
        raw_stage["metrics"] = {
            **dict(raw_stage.get("metrics") or {}),
            "trade_date_count": int(summary.get("trade_date_count") or 0),
            "freq_count": len(summary.get("freqs") or []),
            "fetched_rows": int(summary.get("fetched_rows") or 0),
            "written_rows": int(summary.get("written_rows") or 0),
            "affected_partition_count": len(summary.get("affected_partitions") or []),
            "elapsed_seconds": summary.get("elapsed_seconds"),
        }

    clean_stage = _stage_by_key(stages, "clean_next_refresh")
    if clean_stage is not None:
        clean_stage["stage_status"] = "passed"
        clean_stage["stage_status_label"] = "已通过"
        clean_stage["display_summary"] = (
            f"clean_next/gate 刷新完成：{int(clean_next_refresh.get('affected_partitions') or 0)} 个分区已通过。"
        )
        clean_stage["output_summary"] = clean_next_refresh
        clean_stage["metrics"] = {
            **dict(clean_stage.get("metrics") or {}),
            "affected_partition_count": int(clean_next_refresh.get("affected_partitions") or 0),
        }

    review_stage = _stage_by_key(stages, "clean_next_review")
    if review_stage is not None:
        review_stage["stage_status"] = "waiting_confirmation"
        review_stage["stage_status_label"] = "等待确认"
        review_stage["display_summary"] = "raw 与 clean_next/gate 已完成，请确认是否继续生成 90/120 分钟线。"
        review_stage["metrics"] = {
            **dict(review_stage.get("metrics") or {}),
            "raw_written_rows": int(summary.get("written_rows") or 0),
            "clean_next_affected_partition_count": int(clean_next_refresh.get("affected_partitions") or 0),
        }

    return _with_runtime_fields(
        {
            **run,
            "status": "waiting_confirmation",
            "run_status": "waiting_confirmation",
            "pipeline_stages": stages,
            "dataset_results": [_dataset_result_from_stk_mins_summary(summary)],
            "errors": [],
            "progress": {
                **dict(run.get("progress") or {}),
                "summary": "raw 与 clean_next/gate 已完成，等待人工确认是否继续生成 90/120。",
            },
        },
        current_stage=review_stage,
    )


def start_derived_90_120_stage(*, run: dict[str, Any]) -> dict[str, Any]:
    stages = deepcopy(list(run.get("pipeline_stages") or []))
    stage = _stage_by_key(stages, "derived_90_120_build")
    if stage is not None:
        stage["stage_status"] = "running"
        stage["stage_status_label"] = "执行中"
        stage["display_summary"] = "正在从 clean_next 生成 90/120 分钟线。"
    return _with_runtime_fields(
        {
            **run,
            "status": "running",
            "run_status": "running",
            "pipeline_stages": stages,
            "progress": {
                **dict(run.get("progress") or {}),
                "summary": "正在生成 derived 90/120 分钟线。",
            },
        },
        current_stage=stage,
    )


def complete_derived_90_120_stage(*, run: dict[str, Any], summary: dict[str, Any]) -> dict[str, Any]:
    stages = deepcopy(list(run.get("pipeline_stages") or []))
    derived_stage = _stage_by_key(stages, "derived_90_120_build")
    if derived_stage is not None:
        derived_stage["stage_status"] = "passed"
        derived_stage["stage_status_label"] = "已通过"
        derived_stage["display_summary"] = (
            f"derived 90/120 生成完成：{int(summary.get('trade_date_count') or 0)} 个交易日，"
            f"{len(summary.get('targets') or [])} 个目标频率，"
            f"写入 {int(summary.get('written_rows') or 0):,} 行。"
        )
        derived_stage["output_summary"] = {
            "run_id": summary.get("run_id"),
            "operation": summary.get("operation"),
            "start_date": summary.get("start_date"),
            "end_date": summary.get("end_date"),
            "trade_dates": summary.get("trade_dates") or [],
            "targets": summary.get("targets") or [],
        }
        derived_stage["metrics"] = {
            **dict(derived_stage.get("metrics") or {}),
            "trade_date_count": int(summary.get("trade_date_count") or 0),
            "target_count": len(summary.get("targets") or []),
            "source_rows": int(summary.get("source_rows") or 0),
            "written_rows": int(summary.get("written_rows") or 0),
            "elapsed_seconds": summary.get("elapsed_seconds"),
        }

    review_stage = _stage_by_key(stages, "derived_review")
    if review_stage is not None:
        review_stage["stage_status"] = "waiting_confirmation"
        review_stage["stage_status_label"] = "等待确认"
        review_stage["display_summary"] = "derived 90/120 已完成，请确认是否继续重排 research by month。"
        review_stage["metrics"] = {
            **dict(review_stage.get("metrics") or {}),
            "derived_written_rows": int(summary.get("written_rows") or 0),
        }

    dataset_results = list(run.get("dataset_results") or [])
    dataset_results.append(_dataset_result_from_stk_mins_derived_summary(summary))
    return _with_runtime_fields(
        {
            **run,
            "status": "waiting_confirmation",
            "run_status": "waiting_confirmation",
            "pipeline_stages": stages,
            "dataset_results": dataset_results,
            "errors": [],
            "progress": {
                **dict(run.get("progress") or {}),
                "summary": "derived 90/120 已完成，等待人工确认是否继续重排 research by month。",
            },
        },
        current_stage=review_stage,
    )


def fail_prewrite_backup_stage(*, run: dict[str, Any], error: dict[str, Any]) -> dict[str, Any]:
    stages = deepcopy(list(run.get("pipeline_stages") or []))
    stage = _stage_by_key(stages, "prewrite_backup")
    if stage is not None:
        stage["stage_status"] = "failed"
        stage["stage_status_label"] = "失败"
        stage["display_summary"] = f"Kopia 写前备份失败：{error.get('message') or '未知错误'}"
        stage["issues"] = [error]
    return _with_runtime_fields(
        {
            **run,
            "status": "backup_failed",
            "run_status": "backup_failed",
            "finished_at": _utc_now_iso(),
            "pipeline_stages": stages,
            "errors": [error],
            "progress": {
                **dict(run.get("progress") or {}),
                "summary": "Kopia 写前备份失败，未执行任何 Lake 分区写入。",
            },
        },
        current_stage=stage,
    )


def fail_pipeline_stage(*, run: dict[str, Any], stage_key: str, error: dict[str, Any]) -> dict[str, Any]:
    stages = deepcopy(list(run.get("pipeline_stages") or []))
    stage = _stage_by_key(stages, stage_key)
    if stage is not None:
        stage["stage_status"] = "failed"
        stage["stage_status_label"] = "失败"
        stage["display_summary"] = f"{stage.get('stage_title')} 失败：{error.get('message') or '未知错误'}"
        stage["issues"] = [error]
    return _with_runtime_fields(
        {
            **run,
            "status": "failed",
            "run_status": "failed",
            "finished_at": _utc_now_iso(),
            "pipeline_stages": stages,
            "errors": [error],
            "progress": {
                **dict(run.get("progress") or {}),
                "summary": f"{stage.get('stage_title') if stage else stage_key} 失败，后续阶段不会继续。",
            },
        },
        current_stage=stage,
    )


def continue_pipeline_run(*, run: dict[str, Any], operator: str | None = None) -> dict[str, Any]:
    _ensure_not_finished(run)
    stages = deepcopy(list(run.get("pipeline_stages") or []))
    current_stage = _stage_by_key(stages, str(run.get("current_stage_key") or ""))
    if current_stage is None or current_stage.get("stage_status") != "waiting_confirmation" or not current_stage.get("requires_confirmation"):
        raise StkMinsPipelineRunNotWaitingConfirmationError("当前 run 没有停在人工确认阶段，不能继续。")

    now = _utc_now_iso()
    current_stage["stage_status"] = "passed"
    current_stage["stage_status_label"] = "已通过"
    current_stage["confirmed_by"] = operator or CONFIRMATION_OPERATOR_FALLBACK
    current_stage["confirmed_at"] = now
    current_stage["display_summary"] = f"{current_stage.get('display_summary') or current_stage.get('stage_title')} 已确认继续。"

    next_stage = _current_stage(stages)
    run_status = "planned" if next_stage is not None else "success"
    finished_at = now if next_stage is None else None
    return _with_runtime_fields(
        {
            **run,
            "status": run_status,
            "run_status": run_status,
            "finished_at": finished_at,
            "pipeline_stages": stages,
            "progress": {
                **dict(run.get("progress") or {}),
                "summary": (
                    f"已确认 {current_stage.get('stage_title')}，等待进入 {next_stage.get('stage_title')}。"
                    if next_stage is not None
                    else "所有阶段已确认完成。"
                ),
            },
        },
        current_stage=next_stage,
    )


def abort_pipeline_run(*, run: dict[str, Any], reason: str) -> dict[str, Any]:
    _ensure_not_finished(run)
    stages = deepcopy(list(run.get("pipeline_stages") or []))
    current_key = str(run.get("current_stage_key") or "")
    current_stage = _stage_by_key(stages, current_key) or _current_stage(stages)
    current_order = int(current_stage.get("stage_order") or 0) if current_stage else 0
    for stage in stages:
        stage_status = str(stage.get("stage_status") or "")
        stage_order = int(stage.get("stage_order") or 0)
        if stage_order >= current_order and stage_status in {"pending", "running", "waiting_confirmation"}:
            stage["stage_status"] = "cancelled"
            stage["stage_status_label"] = "已停止"
            stage["next_action"] = None
            stage["display_summary"] = f"{stage.get('stage_title')} 已停止：{reason}"

    return _with_runtime_fields(
        {
            **run,
            "status": "cancelled",
            "run_status": "cancelled",
            "finished_at": _utc_now_iso(),
            "pipeline_stages": stages,
            "progress": {
                **dict(run.get("progress") or {}),
                "summary": f"stk_mins_sync 已停止：{reason}",
            },
        },
        current_stage=current_stage,
        force_requires_confirmation=False,
    )


def normalize_run_detail(payload: dict[str, Any]) -> dict[str, Any]:
    stages = list(payload.get("pipeline_stages") or [])
    current_stage = _stage_by_key(stages, str(payload.get("current_stage_key") or "")) or _current_stage(stages)
    normalized = {
        **payload,
        "run_status": str(payload.get("run_status") or payload.get("status") or "unknown"),
        "pipeline_stages": stages,
        "current_stage_key": payload.get("current_stage_key"),
        "requires_confirmation": bool(payload.get("requires_confirmation") or False),
        "next_action": payload.get("next_action"),
    }
    if stages:
        normalized = _with_runtime_fields(normalized, current_stage=current_stage)
    return normalized


def _with_runtime_fields(
    payload: dict[str, Any],
    *,
    current_stage: dict[str, Any] | None,
    force_requires_confirmation: bool | None = None,
) -> dict[str, Any]:
    requires_confirmation = bool(
        force_requires_confirmation
        if force_requires_confirmation is not None
        else current_stage
        and current_stage.get("stage_status") == "waiting_confirmation"
        and current_stage.get("requires_confirmation")
    )
    return {
        **payload,
        "current_stage_key": current_stage.get("stage_key") if current_stage else None,
        "requires_confirmation": requires_confirmation,
        "next_action": current_stage.get("next_action") if requires_confirmation and current_stage else None,
    }


def _current_stage(stages: list[dict[str, Any]]) -> dict[str, Any] | None:
    for stage in sorted(stages, key=lambda item: int(item.get("stage_order") or 0)):
        if str(stage.get("stage_status") or "") in {"pending", "running", "waiting_confirmation"}:
            return stage
    return None


def _stage_by_key(stages: list[dict[str, Any]], stage_key: str) -> dict[str, Any] | None:
    if not stage_key:
        return None
    for stage in stages:
        if stage.get("stage_key") == stage_key:
            return stage
    return None


def _ensure_not_finished(run: dict[str, Any]) -> None:
    status = str(run.get("run_status") or run.get("status") or "")
    if status in FINISHED_RUN_STATUSES:
        raise StkMinsPipelineRunAlreadyFinishedError(f"run 已结束，不能继续操作：{status}")


def _dataset_result_from_stk_mins_summary(summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "dataset_key": "stk_mins",
        "status": str(summary.get("status") or "success"),
        "mode": summary.get("mode"),
        "run_id": summary.get("run_id"),
        "start_date": summary.get("start_date"),
        "end_date": summary.get("end_date"),
        "trade_date_count": summary.get("trade_date_count"),
        "freqs": summary.get("freqs"),
        "fetched_rows": summary.get("fetched_rows"),
        "written_rows": summary.get("written_rows"),
        "affected_partition_count": len(summary.get("affected_partitions") or []),
        "clean_next_refresh": summary.get("clean_next_refresh"),
        "elapsed_seconds": summary.get("elapsed_seconds"),
    }


def _dataset_result_from_stk_mins_derived_summary(summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "dataset_key": "stk_mins",
        "status": str(summary.get("status") or "success"),
        "operation": summary.get("operation"),
        "run_id": summary.get("run_id"),
        "start_date": summary.get("start_date"),
        "end_date": summary.get("end_date"),
        "trade_date_count": summary.get("trade_date_count"),
        "targets": summary.get("targets"),
        "source_rows": summary.get("source_rows"),
        "written_rows": summary.get("written_rows"),
        "elapsed_seconds": summary.get("elapsed_seconds"),
    }


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
