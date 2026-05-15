from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from lake_console.backend.app.sync.planner import LakeSyncPlanner
from lake_console.backend.app.services.prod_core_db import PROD_CORE_DB_SOURCE
from lake_console.backend.app.services.prod_raw_db import PROD_RAW_DB_SOURCE


STALE_AFTER_SECONDS = 6 * 60 * 60

PROD_DB_DAILY_DATASETS: tuple[str, ...] = (
    "daily",
    "adj_factor",
    "daily_basic",
    "fund_daily",
    "fund_adj",
    "index_daily_basic",
    "index_daily",
    "index_weekly",
    "index_monthly",
    "margin",
    "stk_limit",
    "stock_st",
    "suspend_d",
    "moneyflow",
    "moneyflow_ths",
    "moneyflow_dc",
    "moneyflow_cnt_ths",
    "moneyflow_ind_ths",
    "moneyflow_ind_dc",
    "moneyflow_mkt_dc",
    "dc_daily",
    "dc_hot",
    "dc_index",
    "dc_member",
    "ths_daily",
    "ths_hot",
    "kpl_list",
    "kpl_concept_cons",
    "limit_list_d",
    "limit_list_ths",
    "limit_step",
    "limit_cpt_list",
    "top_list",
    "cyq_perf",
    "stk_factor_pro",
    "stk_nineturn",
    "stk_period_bar_week",
    "stk_period_bar_month",
    "stk_period_bar_adj_week",
    "stk_period_bar_adj_month",
)

PROD_DB_SNAPSHOT_DATASETS: tuple[str, ...] = (
    "etf_basic",
    "etf_index",
    "bse_mapping",
    "hk_basic",
    "namechange",
    "stock_company",
    "st",
    "ths_index",
    "ths_member",
)

LAKE_REFERENCE_DATASETS: tuple[str, ...] = (
    "stock_basic",
    "trade_cal",
    "index_basic",
)

PROD_CORE_DAILY_DATASETS = {"index_daily", "index_weekly", "index_monthly"}


@dataclass(frozen=True)
class SyncProfile:
    profile_key: str
    display_name: str
    description: str
    profile_status: str
    default_lookback_days: int | None
    requires_kopia_backup: bool
    stale_after_seconds: int
    datasets: tuple[str, ...]
    disabled_reason: str | None = None

    def to_summary(self) -> dict[str, Any]:
        return {
            "profile_key": self.profile_key,
            "display_name": self.display_name,
            "description": self.description,
            "profile_status": self.profile_status,
            "default_lookback_days": self.default_lookback_days,
            "requires_kopia_backup": self.requires_kopia_backup,
            "stale_after_seconds": self.stale_after_seconds,
            "disabled_reason": self.disabled_reason,
            "datasets": [{"dataset_key": key} for key in self.datasets],
        }


class SyncProfileCatalog:
    def __init__(self) -> None:
        self._profiles = {
            profile.profile_key: profile
            for profile in (
                SyncProfile(
                    profile_key="prod_db_daily",
                    display_name="远程 DB 每日同步",
                    description="从生产 DB 只读导出按交易日或周/月锚点更新的数据集。",
                    profile_status="enabled",
                    default_lookback_days=1,
                    requires_kopia_backup=True,
                    stale_after_seconds=STALE_AFTER_SECONDS,
                    datasets=PROD_DB_DAILY_DATASETS,
                ),
                SyncProfile(
                    profile_key="prod_db_snapshot_refresh",
                    display_name="远程 DB 快照刷新",
                    description="刷新基础资料、current/snapshot 类数据集，不伪造 trade_date。",
                    profile_status="enabled",
                    default_lookback_days=None,
                    requires_kopia_backup=True,
                    stale_after_seconds=STALE_AFTER_SECONDS,
                    datasets=PROD_DB_SNAPSHOT_DATASETS,
                ),
                SyncProfile(
                    profile_key="prod_db_manual_backfill",
                    display_name="远程 DB 手动补数",
                    description="人工选择白名单数据集和日期范围补数。",
                    profile_status="enabled",
                    default_lookback_days=None,
                    requires_kopia_backup=True,
                    stale_after_seconds=STALE_AFTER_SECONDS,
                    datasets=PROD_DB_DAILY_DATASETS + PROD_DB_SNAPSHOT_DATASETS,
                ),
                SyncProfile(
                    profile_key="lake_reference_refresh",
                    display_name="本地参考数据刷新",
                    description="刷新股票池、交易日历、指数清单等本地参考数据。",
                    profile_status="enabled",
                    default_lookback_days=None,
                    requires_kopia_backup=True,
                    stale_after_seconds=STALE_AFTER_SECONDS,
                    datasets=LAKE_REFERENCE_DATASETS,
                ),
                SyncProfile(
                    profile_key="stk_mins_sync",
                    display_name="股票分钟线专项",
                    description="股票历史分钟线 raw -> clean_next -> derived/research/indicator 独立链路。",
                    profile_status="planned",
                    default_lookback_days=None,
                    requires_kopia_backup=True,
                    stale_after_seconds=STALE_AFTER_SECONDS,
                    datasets=("stk_mins",),
                    disabled_reason="已支持执行到 raw + clean_next/gate，人工确认后生成 90/120；research by month 待后续阶段接入。",
                ),
                SyncProfile(
                    profile_key="index_mins_sync",
                    display_name="指数分钟线专项",
                    description="指数历史分钟线专项，不与股票分钟线合并。",
                    profile_status="planned",
                    default_lookback_days=None,
                    requires_kopia_backup=True,
                    stale_after_seconds=STALE_AFTER_SECONDS,
                    datasets=("index_mins",),
                    disabled_reason="后续专项，本期不提供启动 API。",
                ),
                SyncProfile(
                    profile_key="indicator_compute",
                    display_name="技术指标计算",
                    description="指标计算入口，不属于远程 DB 同步。",
                    profile_status="planned",
                    default_lookback_days=None,
                    requires_kopia_backup=True,
                    stale_after_seconds=STALE_AFTER_SECONDS,
                    datasets=(),
                    disabled_reason="后续专项，本期不提供启动 API。",
                ),
            )
        }

    def list_profiles(self) -> list[SyncProfile]:
        return list(self._profiles.values())

    def get_profile(self, profile_key: str) -> SyncProfile:
        profile = self._profiles.get(profile_key)
        if profile is None:
            allowed = ", ".join(sorted(self._profiles))
            raise ValueError(f"未知 sync profile：{profile_key}；允许值：{allowed}")
        return profile

    def ensure_enabled(self, profile_key: str) -> SyncProfile:
        profile = self.get_profile(profile_key)
        if profile.profile_status != "enabled":
            raise ProfileDisabledError(profile.disabled_reason or f"{profile_key} 当前不可启动。")
        return profile


class ProfileDisabledError(RuntimeError):
    pass


class SyncProfilePlanner:
    def __init__(self, *, lake_root: Path, catalog: SyncProfileCatalog | None = None) -> None:
        self.lake_root = lake_root
        self.catalog = catalog or SyncProfileCatalog()

    def build_plan(
        self,
        *,
        profile_key: str,
        dataset_keys: list[str] | None,
        target_date: date | None,
        start_date: date | None,
        end_date: date | None,
    ) -> dict[str, Any]:
        profile = self.catalog.ensure_enabled(profile_key)
        selected_dataset_keys = tuple(dataset_keys or profile.datasets)
        self._validate_dataset_keys(profile=profile, dataset_keys=selected_dataset_keys)

        planner = LakeSyncPlanner(lake_root=self.lake_root)
        dataset_plans: list[dict[str, Any]] = []
        blockers: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []
        for dataset_key in selected_dataset_keys:
            try:
                lake_plan = planner.plan(
                    dataset_key=dataset_key,
                    source=self._source_for(profile_key=profile_key, dataset_key=dataset_key),
                    trade_date=target_date if profile_key in {"prod_db_daily", "prod_db_manual_backfill"} and start_date is None else None,
                    start_date=start_date,
                    end_date=end_date,
                )
            except Exception as exc:  # plan 阶段必须聚合阻断，不要偷偷跳过数据集。
                blockers.append(
                    {
                        "dataset_key": dataset_key,
                        "code": "PLAN_FAILED",
                        "message": str(exc),
                    }
                )
                continue
            dataset_plans.append(
                {
                    "dataset_key": lake_plan.dataset_key,
                    "display_name": lake_plan.display_name,
                    "source": lake_plan.source,
                    "api_name": lake_plan.api_name,
                    "mode": lake_plan.mode,
                    "request_strategy_key": lake_plan.request_strategy_key,
                    "request_count": lake_plan.request_count,
                    "partition_count": lake_plan.partition_count,
                    "write_policy": lake_plan.write_policy,
                    "write_paths": list(lake_plan.write_paths),
                    "required_manifests": list(lake_plan.required_manifests),
                    "parameters": lake_plan.parameters,
                    "status": "will_run",
                    "notes": list(lake_plan.notes),
                }
            )

        backup_plan = self._build_backup_plan(dataset_plans=dataset_plans)
        return {
            "profile": profile.to_summary(),
            "request": {
                "profile_key": profile_key,
                "dataset_keys": list(selected_dataset_keys),
                "target_date": target_date.isoformat() if target_date else None,
                "start_date": start_date.isoformat() if start_date else None,
                "end_date": end_date.isoformat() if end_date else None,
            },
            "normalized_parameters": {
                "dataset_keys": list(selected_dataset_keys),
                "target_date": target_date.isoformat() if target_date else None,
                "start_date": start_date.isoformat() if start_date else None,
                "end_date": end_date.isoformat() if end_date else None,
            },
            "dataset_plans": dataset_plans,
            "backup_plan": backup_plan,
            "blockers": blockers,
            "warnings": warnings,
            "summary": {
                "dataset_count": len(dataset_plans),
                "blocked_count": len(blockers),
                "write_path_count": sum(len(item["write_paths"]) for item in dataset_plans),
                "backup_path_count": len(backup_plan["backup_paths"]),
                "snapshot_path_count": len(backup_plan["snapshot_paths"]),
                "path_missing_before_write_count": len(backup_plan["path_missing_before_write"]),
            },
        }

    def _validate_dataset_keys(self, *, profile: SyncProfile, dataset_keys: tuple[str, ...]) -> None:
        allowed = set(profile.datasets)
        illegal = sorted(set(dataset_keys) - allowed)
        if illegal:
            raise ValueError(f"数据集不在 profile 白名单：{', '.join(illegal)}")

    def _source_for(self, *, profile_key: str, dataset_key: str) -> str:
        if profile_key in {"prod_db_daily", "prod_db_manual_backfill"}:
            return PROD_CORE_DB_SOURCE if dataset_key in PROD_CORE_DAILY_DATASETS else PROD_RAW_DB_SOURCE
        if profile_key == "prod_db_snapshot_refresh":
            return PROD_RAW_DB_SOURCE
        return "tushare"

    def _build_backup_plan(self, *, dataset_plans: list[dict[str, Any]]) -> dict[str, Any]:
        backup_paths: list[str] = []
        snapshot_paths: list[str] = []
        missing_paths: list[str] = []
        for dataset_plan in dataset_plans:
            for relative_path in dataset_plan["write_paths"]:
                path = self.lake_root / relative_path
                if path.exists():
                    backup_paths.append(relative_path)
                    snapshot_paths.append(self._snapshot_root_for_backup_path(relative_path))
                else:
                    missing_paths.append(relative_path)
        lake_jobs = self.lake_root / "manifest" / "lake_jobs"
        if lake_jobs.exists():
            backup_paths.append("manifest/lake_jobs")
            snapshot_paths.append("manifest/lake_jobs")
        return {
            "required": True,
            "provider": "kopia",
            "snapshot_strategy": "prewrite_dataset_root_scope",
            "pin_policy": "none",
            "pinned": False,
            "backup_paths": sorted(set(backup_paths)),
            "snapshot_paths": sorted(set(snapshot_paths)),
            "path_missing_before_write": sorted(set(missing_paths)),
        }

    def _snapshot_root_for_backup_path(self, relative_path: str) -> str:
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
