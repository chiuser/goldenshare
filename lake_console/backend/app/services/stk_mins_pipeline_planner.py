from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from lake_console.backend.app.services.security_universe_filter import SecurityUniverseError, load_security_universe_for_range
from lake_console.backend.app.services.sync_center_profiles import SyncProfileCatalog
from lake_console.backend.app.sync.helpers.dates import load_open_trade_dates
from lake_console.backend.app.sync.planner import LakeSyncPlanner


STK_MINS_PIPELINE_PROFILE_KEY = "stk_mins_sync"
STK_MINS_PIPELINE_DATASET_KEY = "stk_mins"
STK_MINS_PIPELINE_DEFAULT_FREQS = (1, 5, 15, 30, 60)
STK_MINS_PIPELINE_ALLOWED_FREQS = set(STK_MINS_PIPELINE_DEFAULT_FREQS)
STK_MINS_PIPELINE_DEFAULT_SCOPE = "all_market"
STK_MINS_PIPELINE_DEFAULT_MODE = "manual_gate"


class StkMinsPipelinePlanner:
    """Build the read-only Sync Center plan for the staged stk_mins pipeline."""

    def __init__(self, *, lake_root: Path, catalog: SyncProfileCatalog | None = None) -> None:
        self.lake_root = lake_root
        self.catalog = catalog or SyncProfileCatalog()

    def build_plan(
        self,
        *,
        dataset_keys: list[str] | None,
        start_date: date | None,
        end_date: date | None,
        freqs: list[int] | None,
        scope: str | None,
        mode: str | None,
    ) -> dict[str, Any]:
        profile = self.catalog.get_profile(STK_MINS_PIPELINE_PROFILE_KEY)
        selected_dataset_keys = tuple(dataset_keys or profile.datasets)
        self._validate_dataset_keys(selected_dataset_keys)
        if start_date is None or end_date is None:
            raise ValueError("stk_mins_sync 计划必须传 start_date 和 end_date。")
        if end_date < start_date:
            raise ValueError("end_date 不能早于 start_date。")

        normalized_scope = scope or STK_MINS_PIPELINE_DEFAULT_SCOPE
        if normalized_scope != STK_MINS_PIPELINE_DEFAULT_SCOPE:
            raise ValueError("stk_mins_sync 第一期只支持 scope=all_market。")
        normalized_mode = mode or STK_MINS_PIPELINE_DEFAULT_MODE
        if normalized_mode != STK_MINS_PIPELINE_DEFAULT_MODE:
            raise ValueError("stk_mins_sync 第一期只支持 mode=manual_gate。")
        selected_freqs = _resolve_freqs(freqs)

        blockers: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = [
            {
                "code": "PIPELINE_REQUIRES_MANUAL_CONFIRMATIONS",
                "message": "当前按分阶段方式执行：clean_next 和 derived 完成后都会停下等待人工确认，确认后再继续扩大写入范围。",
            }
        ]
        trade_dates: list[date] = []
        security_universe: dict[str, Any] | None = None
        sync_estimate: dict[str, Any] | None = None
        request_count = 0

        try:
            trade_dates = load_open_trade_dates(lake_root=self.lake_root, start_date=start_date, end_date=end_date)
            if not trade_dates:
                blockers.append(
                    {
                        "dataset_key": STK_MINS_PIPELINE_DATASET_KEY,
                        "code": "NO_OPEN_TRADE_DATES",
                        "message": f"本地交易日历中 {start_date.isoformat()} ~ {end_date.isoformat()} 没有开市日。",
                    }
                )
        except Exception as exc:
            blockers.append(
                {
                    "dataset_key": STK_MINS_PIPELINE_DATASET_KEY,
                    "code": "TRADE_CALENDAR_UNAVAILABLE",
                    "message": str(exc),
                }
            )

        if trade_dates:
            try:
                universe = load_security_universe_for_range(lake_root=self.lake_root, start_date=start_date, end_date=end_date)
                security_universe = universe.to_dict()
            except SecurityUniverseError as exc:
                blockers.append(
                    {
                        "dataset_key": STK_MINS_PIPELINE_DATASET_KEY,
                        "code": "SECURITY_UNIVERSE_UNAVAILABLE",
                        "message": str(exc),
                    }
                )
            except Exception as exc:
                blockers.append(
                    {
                        "dataset_key": STK_MINS_PIPELINE_DATASET_KEY,
                        "code": "SECURITY_UNIVERSE_PLAN_FAILED",
                        "message": str(exc),
                    }
                )

        if trade_dates and not blockers:
            try:
                lake_plan = LakeSyncPlanner(lake_root=self.lake_root).plan(
                    dataset_key=STK_MINS_PIPELINE_DATASET_KEY,
                    source="tushare",
                    start_date=start_date,
                    end_date=end_date,
                    all_market=True,
                    freqs=selected_freqs,
                )
                request_count = lake_plan.request_count
                sync_estimate = lake_plan.estimate
            except Exception as exc:
                blockers.append(
                    {
                        "dataset_key": STK_MINS_PIPELINE_DATASET_KEY,
                        "code": "STK_MINS_SYNC_PLAN_FAILED",
                        "message": str(exc),
                    }
                )

        affected_trade_dates = [item.isoformat() for item in trade_dates]
        affected_months = _months_from_trade_dates(trade_dates)
        derived_freqs = _derived_freqs_for(selected_freqs)
        research_freqs = sorted(set(selected_freqs) | set(derived_freqs))
        write_paths = _build_write_paths(
            trade_dates=trade_dates,
            raw_freqs=selected_freqs,
            derived_freqs=derived_freqs,
            research_freqs=research_freqs,
            trade_months=affected_months,
        )
        backup_plan = _build_backup_plan(lake_root=self.lake_root, write_paths=write_paths)
        pipeline_stages = _build_pipeline_stages(
            blocker_count=len(blockers),
            trade_date_count=len(trade_dates),
            raw_freqs=selected_freqs,
            derived_freqs=derived_freqs,
            research_freqs=research_freqs,
            affected_months=affected_months,
            backup_plan=backup_plan,
        )

        dataset_plan = {
            "dataset_key": STK_MINS_PIPELINE_DATASET_KEY,
            "display_name": "股票历史分钟行情",
            "source": "tushare",
            "api_name": "stk_mins",
            "mode": "staged_pipeline_plan",
            "request_strategy_key": "stk_mins_sync_center_pipeline",
            "request_count": request_count,
            "partition_count": len(trade_dates) * len(selected_freqs),
            "write_policy": "replace_partition",
            "write_paths": write_paths,
            "required_manifests": [
                "manifest/security_universe/tushare_stock_basic.parquet",
                "manifest/trading_calendar/tushare_trade_cal.parquet",
            ],
            "parameters": {
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "scope": normalized_scope,
                "mode": normalized_mode,
                "freqs": selected_freqs,
                "affected_trade_dates": affected_trade_dates,
                "affected_months": affected_months,
                "derived_freqs": derived_freqs,
                "research_freqs": research_freqs,
            },
            "status": "plan_only",
            "notes": [
                "计划生成阶段只读，不请求 Tushare，不写 Lake，不创建 Kopia snapshot。",
                "启动 run 后会先创建 Kopia 写前备份，再执行 raw + clean_next/gate，并停在 clean_next_review；人工确认后生成 90/120 并停在 derived_review；再次确认后重排 research by month 并执行最终校验。",
            ],
            "estimate": sync_estimate,
        }
        return {
            "profile": profile.to_summary(),
            "request": {
                "profile_key": STK_MINS_PIPELINE_PROFILE_KEY,
                "dataset_keys": list(selected_dataset_keys),
                "target_date": None,
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "freqs": selected_freqs,
                "scope": normalized_scope,
                "mode": normalized_mode,
            },
            "normalized_parameters": {
                "dataset_keys": list(selected_dataset_keys),
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "freqs": selected_freqs,
                "scope": normalized_scope,
                "mode": normalized_mode,
                "affected_trade_dates": affected_trade_dates,
                "affected_months": affected_months,
                "derived_freqs": derived_freqs,
                "research_freqs": research_freqs,
                "security_universe": security_universe,
            },
            "dataset_plans": [dataset_plan],
            "pipeline_stages": pipeline_stages,
            "affected_trade_dates": affected_trade_dates,
            "affected_months": affected_months,
            "backup_plan": backup_plan,
            "blockers": blockers,
            "warnings": warnings,
            "summary": {
                "dataset_count": 1,
                "blocked_count": len(blockers),
                "stage_count": len(pipeline_stages),
                "trade_date_count": len(trade_dates),
                "affected_month_count": len(affected_months),
                "raw_freq_count": len(selected_freqs),
                "derived_freq_count": len(derived_freqs),
                "research_freq_count": len(research_freqs),
                "request_count": request_count,
                "write_path_count": len(write_paths),
                "backup_path_count": len(backup_plan["backup_paths"]),
                "snapshot_path_count": len(backup_plan["snapshot_paths"]),
                "path_missing_before_write_count": len(backup_plan["path_missing_before_write"]),
            },
        }

    def _validate_dataset_keys(self, dataset_keys: tuple[str, ...]) -> None:
        illegal = sorted(set(dataset_keys) - {STK_MINS_PIPELINE_DATASET_KEY})
        if illegal:
            raise ValueError(f"数据集不在 stk_mins_sync 白名单：{', '.join(illegal)}")


def _resolve_freqs(freqs: list[int] | None) -> list[int]:
    if freqs is None:
        return list(STK_MINS_PIPELINE_DEFAULT_FREQS)
    if not freqs:
        raise ValueError("stk_mins_sync freqs 不能为空。")
    selected = sorted(set(int(item) for item in freqs))
    invalid = sorted(set(selected) - STK_MINS_PIPELINE_ALLOWED_FREQS)
    if invalid:
        allowed = ", ".join(str(item) for item in STK_MINS_PIPELINE_DEFAULT_FREQS)
        raise ValueError(f"stk_mins_sync 不支持 freqs={invalid}，允许值：{allowed}")
    return selected


def _derived_freqs_for(raw_freqs: list[int]) -> list[int]:
    derived: list[int] = []
    if 30 in raw_freqs:
        derived.append(90)
    if 60 in raw_freqs:
        derived.append(120)
    return derived


def _months_from_trade_dates(trade_dates: list[date]) -> list[str]:
    return sorted({item.strftime("%Y-%m") for item in trade_dates})


def _build_write_paths(
    *,
    trade_dates: list[date],
    raw_freqs: list[int],
    derived_freqs: list[int],
    research_freqs: list[int],
    trade_months: list[str],
) -> list[str]:
    paths: list[str] = []
    for freq in raw_freqs:
        for trade_date in trade_dates:
            date_text = trade_date.isoformat()
            paths.append(f"raw_tushare/stk_mins_by_date/freq={freq}/trade_date={date_text}")
            paths.append(f"research/stk_mins_by_date_clean_next/freq={freq}/trade_date={date_text}")
    for freq in derived_freqs:
        for trade_date in trade_dates:
            paths.append(f"derived/stk_mins_by_date/freq={freq}/trade_date={trade_date.isoformat()}")
    for freq in research_freqs:
        for trade_month in trade_months:
            paths.append(f"research/stk_mins_by_symbol_month/freq={freq}/trade_month={trade_month}")
    return sorted(set(paths))


def _build_backup_plan(*, lake_root: Path, write_paths: list[str]) -> dict[str, Any]:
    backup_paths: list[str] = []
    snapshot_paths: list[str] = []
    missing_paths: list[str] = []
    for relative_path in write_paths:
        path = lake_root / relative_path
        if path.exists():
            backup_paths.append(relative_path)
            snapshot_paths.append(_snapshot_root_for_backup_path(relative_path))
        else:
            missing_paths.append(relative_path)
    lake_jobs = lake_root / "manifest" / "lake_jobs"
    if lake_jobs.exists():
        backup_paths.append("manifest/lake_jobs")
        snapshot_paths.append("manifest/lake_jobs")
    return {
        "required": True,
        "provider": "kopia",
        "snapshot_strategy": "prewrite_stk_mins_pipeline_scope",
        "pin_policy": "none",
        "pinned": False,
        "backup_paths": sorted(set(backup_paths)),
        "snapshot_paths": sorted(set(snapshot_paths)),
        "path_missing_before_write": sorted(set(missing_paths)),
    }


def _snapshot_root_for_backup_path(relative_path: str) -> str:
    parts = [part for part in relative_path.split("/") if part]
    if not parts:
        raise ValueError("Kopia snapshot 聚合路径不能为空。")
    first = parts[0]
    if first in {"raw_tushare", "derived", "research"} and len(parts) >= 2:
        return "/".join(parts[:2])
    if first == "manifest":
        if len(parts) >= 2 and parts[1] == "lake_jobs":
            return "manifest/lake_jobs"
        if len(parts) >= 2:
            return "/".join(parts[:2])
        return "manifest"
    return first


def _build_pipeline_stages(
    *,
    blocker_count: int,
    trade_date_count: int,
    raw_freqs: list[int],
    derived_freqs: list[int],
    research_freqs: list[int],
    affected_months: list[str],
    backup_plan: dict[str, Any],
) -> list[dict[str, Any]]:
    plan_passed = blocker_count == 0
    return [
        _stage(
            order=1,
            key="plan_preflight",
            title="计划检查",
            status="passed" if plan_passed else "failed",
            summary=(
                f"计划检查通过：{trade_date_count} 个交易日、{len(raw_freqs)} 个 raw 频率、影响 {len(affected_months)} 个月。"
                if plan_passed
                else f"计划检查未通过：{blocker_count} 个阻断项。"
            ),
            metrics={
                "trade_date_count": trade_date_count,
                "raw_freq_count": len(raw_freqs),
                "affected_month_count": len(affected_months),
                "blocker_count": blocker_count,
            },
        ),
        _stage(
            order=2,
            key="prewrite_backup",
            title="写前备份",
            status="pending",
            summary=(
                "待创建 Kopia 写前备份："
                f"{len(backup_plan['backup_paths'])} 个已存在路径，"
                f"{len(backup_plan['path_missing_before_write'])} 个新建路径。"
            ),
            metrics={
                "backup_path_count": len(backup_plan["backup_paths"]),
                "snapshot_path_count": len(backup_plan["snapshot_paths"]),
                "path_missing_before_write_count": len(backup_plan["path_missing_before_write"]),
            },
        ),
        _stage(
            order=3,
            key="raw_sync",
            title="同步 raw 分钟线",
            status="pending",
            summary=f"待同步 raw：{len(raw_freqs)} 个频率、{trade_date_count} 个交易日。",
            metrics={"raw_freqs": raw_freqs, "trade_date_count": trade_date_count},
        ),
        _stage(
            order=4,
            key="clean_next_refresh",
            title="刷新 clean_next/gate",
            status="pending",
            summary=f"待刷新 clean_next 与 gate：{len(raw_freqs)} 个频率、{trade_date_count} 个交易日。",
            metrics={"raw_freqs": raw_freqs, "trade_date_count": trade_date_count},
        ),
        _stage(
            order=5,
            key="clean_next_review",
            title="clean_next 结果确认",
            status="pending",
            summary="待 clean_next/gate 完成后确认是否继续生成 90/120。",
            metrics={"requires_confirmation": True},
            requires_confirmation=True,
            confirmation_prompt="确认继续生成 90/120 分钟线。",
            next_action={"action": "continue", "label": "继续生成 90/120"},
        ),
        _stage(
            order=6,
            key="derived_90_120_build",
            title="生成 90/120 分钟线",
            status="pending" if derived_freqs else "skipped",
            summary=(
                f"待生成 derived：目标频率 {','.join(str(item) for item in derived_freqs)}。"
                if derived_freqs
                else "未选择 30/60 raw 频率，本轮不生成 90/120。"
            ),
            metrics={"derived_freqs": derived_freqs, "trade_date_count": trade_date_count},
        ),
        _stage(
            order=7,
            key="derived_review",
            title="derived 结果确认",
            status="pending" if derived_freqs else "skipped",
            summary="待 derived 完成后确认是否继续重排 research by month。" if derived_freqs else "本轮没有 derived 输出，不需要确认。",
            metrics={"requires_confirmation": bool(derived_freqs)},
            requires_confirmation=bool(derived_freqs),
            confirmation_prompt="确认继续重排 research by month。" if derived_freqs else None,
            next_action={"action": "continue", "label": "继续重排 research by month"} if derived_freqs else None,
        ),
        _stage(
            order=8,
            key="research_month_rebuild",
            title="重排 research by month",
            status="pending",
            summary=f"待重排 research：{len(research_freqs)} 个频率、{len(affected_months)} 个月。",
            metrics={"research_freqs": research_freqs, "affected_month_count": len(affected_months)},
        ),
        _stage(
            order=9,
            key="final_validation",
            title="最终校验",
            status="pending",
            summary="待校验 raw、clean_next、derived、research 是否对齐。",
            metrics={},
        ),
    ]


def _stage(
    *,
    order: int,
    key: str,
    title: str,
    status: str,
    summary: str,
    metrics: dict[str, Any],
    requires_confirmation: bool = False,
    confirmation_prompt: str | None = None,
    next_action: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "stage_key": key,
        "stage_title": title,
        "stage_order": order,
        "stage_status": status,
        "stage_status_label": _STATUS_LABELS[status],
        "display_summary": summary,
        "input_summary": {},
        "output_summary": {},
        "metrics": metrics,
        "artifacts": [],
        "issues": [],
        "requires_confirmation": requires_confirmation,
        "confirmation_prompt": confirmation_prompt,
        "confirmed_by": None,
        "confirmed_at": None,
        "next_action": next_action,
    }


_STATUS_LABELS = {
    "pending": "待执行",
    "running": "执行中",
    "passed": "已通过",
    "failed": "失败",
    "waiting_confirmation": "等待确认",
    "skipped": "已跳过",
    "cancelled": "已停止",
}
