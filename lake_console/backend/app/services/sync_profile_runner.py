from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any

from lake_console.backend.app.catalog.datasets.moneyflow import MONEYFLOW_KNOWN_SOURCE_GAPS_BY_DATASET
from lake_console.backend.app.catalog.datasets import get_dataset_definition
from lake_console.backend.app.services.db_trade_date_export_service import DbTradeDateExportService
from lake_console.backend.app.services.prod_raw_current_export_service import ProdRawCurrentExportService
from lake_console.backend.app.services.prod_core_db import (
    PROD_CORE_DB_SOURCE,
    build_prod_core_trade_date_query,
    build_prod_core_trade_date_range_query,
    fetch_prod_core_rows,
    iter_prod_core_rows,
)
from lake_console.backend.app.services.prod_raw_db import (
    PROD_RAW_DB_SOURCE,
    build_prod_raw_trade_date_query,
    build_prod_raw_trade_date_range_query,
    fetch_prod_raw_rows,
    iter_prod_raw_rows,
)
from lake_console.backend.app.services.tushare_client import TushareLakeClient
from lake_console.backend.app.services.tushare_index_basic_sync_service import TushareIndexBasicSyncService
from lake_console.backend.app.services.tushare_stock_basic_sync_service import TushareStockBasicSyncService
from lake_console.backend.app.services.tushare_trade_cal_sync_service import TushareTradeCalSyncService
from lake_console.backend.app.services.sync_center_profiles import (
    LAKE_REFERENCE_DATASETS,
    PROD_CORE_DAILY_DATASETS,
    PROD_DB_DAILY_DATASETS,
    PROD_DB_SNAPSHOT_DATASETS,
)
from lake_console.backend.app.settings import LakeConsoleSettings


class SyncProfileRunnerError(RuntimeError):
    pass


ProgressSink = Callable[[dict[str, Any]], None]


class SyncProfileRunner:
    """Run a planned Sync Center job.

    M6 supports the four reviewed Sync Center profiles only. Minute-line sync,
    index-minute sync, and indicator compute remain separate future workflows.
    """

    def __init__(self, *, settings: LakeConsoleSettings, progress: ProgressSink | None = None) -> None:
        self.settings = settings
        self.progress = progress or (lambda _: None)
        self._tushare_client: TushareLakeClient | None = None

    @classmethod
    def validate_plan(cls, *, plan: dict[str, Any]) -> None:
        cls._validate_m6_scope(
            profile_key=str(plan.get("profile_key") or ""),
            dataset_plans=list(plan.get("dataset_plans") or []),
        )

    def run(self, *, plan: dict[str, Any]) -> dict[str, Any]:
        dataset_plans = list(plan.get("dataset_plans") or [])
        profile_key = str(plan.get("profile_key") or "")
        self.validate_plan(plan=plan)
        self._validate_required_settings(profile_key=profile_key, dataset_plans=dataset_plans)

        results: list[dict[str, Any]] = []
        total = len(dataset_plans)
        for index, dataset_plan in enumerate(dataset_plans, start=1):
            dataset_key = str(dataset_plan["dataset_key"])
            self.progress(
                {
                    "event_type": "dataset_started",
                    "dataset_key": dataset_key,
                    "message": f"开始执行 {dataset_key}（{index}/{total}）。",
                    "metrics": {"dataset_index": index, "dataset_total": total},
                }
            )
            try:
                summary = self._run_dataset(profile_key=profile_key, dataset_plan=dataset_plan)
            except Exception as exc:
                self.progress(
                    {
                        "event_type": "dataset_failed",
                        "level": "error",
                        "dataset_key": dataset_key,
                        "message": str(exc),
                        "error": {"code": "DATASET_SYNC_FAILED", "message": str(exc)},
                    }
                )
                raise SyncProfileRunnerError(f"{dataset_key} 执行失败：{exc}") from exc
            result = _result_from_summary(dataset_key=dataset_key, summary=summary)
            results.append(result)
            self.progress(
                {
                    "event_type": "dataset_completed",
                    "dataset_key": dataset_key,
                    "message": f"{dataset_key} 执行完成。",
                    "metrics": _metrics_from_result(result),
                }
            )

        written_total = sum(_safe_int(item.get("written_rows")) for item in results)
        fetched_total = sum(_safe_int(item.get("fetched_rows")) for item in results)
        return {
            "status": "success",
            "dataset_results": results,
            "progress": {
                "summary": f"Sync Profile 执行完成：datasets={len(results)} fetched={fetched_total} written={written_total}",
                "current_dataset_key": results[-1]["dataset_key"] if results else None,
                "current_partition": None,
            },
        }

    @staticmethod
    def _validate_m6_scope(*, profile_key: str, dataset_plans: list[dict[str, Any]]) -> None:
        if profile_key not in {"prod_db_daily", "prod_db_snapshot_refresh", "prod_db_manual_backfill", "lake_reference_refresh"}:
            raise SyncProfileRunnerError(f"{profile_key} 不在 M6 可执行 profile 范围内。")
        if not dataset_plans:
            raise SyncProfileRunnerError("Sync Profile Runner 至少需要一个 dataset plan。")
        for dataset_plan in dataset_plans:
            dataset_key = str(dataset_plan.get("dataset_key") or "")
            source = str(dataset_plan.get("source") or "")
            mode = str(dataset_plan.get("mode") or "")
            if profile_key == "prod_db_daily":
                _require_dataset(dataset_key, PROD_DB_DAILY_DATASETS, profile_key)
                if source not in {PROD_RAW_DB_SOURCE, PROD_CORE_DB_SOURCE}:
                    raise SyncProfileRunnerError(f"{dataset_key} 必须从 prod-db 只读导出。")
                if mode not in {"point_incremental", "range_rebuild"}:
                    raise SyncProfileRunnerError(f"{dataset_key} 在 prod_db_daily 下必须是日期分区计划。")
            elif profile_key == "prod_db_snapshot_refresh":
                _require_dataset(dataset_key, PROD_DB_SNAPSHOT_DATASETS, profile_key)
                if source != PROD_RAW_DB_SOURCE or mode != "snapshot_refresh":
                    raise SyncProfileRunnerError(f"{dataset_key} 在 prod_db_snapshot_refresh 下必须是 prod-raw-db snapshot_refresh。")
            elif profile_key == "prod_db_manual_backfill":
                _require_dataset(dataset_key, PROD_DB_DAILY_DATASETS + PROD_DB_SNAPSHOT_DATASETS, profile_key)
                if source not in {PROD_RAW_DB_SOURCE, PROD_CORE_DB_SOURCE}:
                    raise SyncProfileRunnerError(f"{dataset_key} 必须从 prod-db 只读导出。")
                if mode not in {"point_incremental", "range_rebuild", "snapshot_refresh"}:
                    raise SyncProfileRunnerError(f"{dataset_key} 的执行模式不在手动补数白名单内：{mode}")
            elif profile_key == "lake_reference_refresh":
                _require_dataset(dataset_key, LAKE_REFERENCE_DATASETS, profile_key)
                if source != "tushare" or mode != "snapshot_refresh":
                    raise SyncProfileRunnerError(f"{dataset_key} 在 lake_reference_refresh 下必须是 tushare snapshot_refresh。")

    def _validate_required_settings(self, *, profile_key: str, dataset_plans: list[dict[str, Any]]) -> None:
        if any(str(item.get("source") or "") == PROD_RAW_DB_SOURCE for item in dataset_plans) and not self.settings.prod_raw_db_url:
            raise SyncProfileRunnerError("缺少 GOLDENSHARE_PROD_RAW_DB_URL，不能执行 prod-raw-db profile。")
        if any(str(item.get("source") or "") == PROD_CORE_DB_SOURCE for item in dataset_plans) and not self.settings.prod_core_db_url:
            raise SyncProfileRunnerError("缺少 GOLDENSHARE_PROD_CORE_DB_URL，不能执行 prod-core-db profile。")
        if profile_key == "lake_reference_refresh" and not self.settings.tushare_token:
            raise SyncProfileRunnerError("缺少 TUSHARE_TOKEN，不能执行 lake_reference_refresh。")

    def _run_dataset(self, *, profile_key: str, dataset_plan: dict[str, Any]) -> dict[str, Any]:
        dataset_key = str(dataset_plan["dataset_key"])
        source = str(dataset_plan["source"])
        mode = str(dataset_plan["mode"])
        parameters = dict(dataset_plan.get("parameters") or {})
        if profile_key == "lake_reference_refresh":
            return self._run_lake_reference_dataset(dataset_key=dataset_key, parameters=parameters)
        if mode == "snapshot_refresh":
            return ProdRawCurrentExportService(
                lake_root=self.settings.lake_root,
                database_url=self.settings.prod_raw_db_url,
                progress=self._dataset_progress(dataset_key),
            ).export(dataset_key=dataset_key)
        return self._run_trade_date_dataset(dataset_key=dataset_key, source=source, parameters=parameters)

    def _run_trade_date_dataset(self, *, dataset_key: str, source: str, parameters: dict[str, Any]) -> dict[str, Any]:
        api_name = get_dataset_definition(dataset_key).api_name or dataset_key
        if source == PROD_CORE_DB_SOURCE:
            return DbTradeDateExportService(
                lake_root=self.settings.lake_root,
                dataset_key=dataset_key,
                api_name=api_name,
                source=source,
                database_url=self.settings.prod_core_db_url,
                build_point_query=build_prod_core_trade_date_query,
                build_range_query=build_prod_core_trade_date_range_query,
                fetch_rows=fetch_prod_core_rows,
                iter_rows=iter_prod_core_rows,
                progress=self._dataset_progress(dataset_key),
            ).export(
                trade_date=_parse_date(parameters.get("trade_date")),
                start_date=_parse_date(parameters.get("start_date")),
                end_date=_parse_date(parameters.get("end_date")),
                ts_code=_optional_text(parameters.get("ts_code")),
            )
        return DbTradeDateExportService(
            lake_root=self.settings.lake_root,
            dataset_key=dataset_key,
            api_name=api_name,
            source=source,
            database_url=self.settings.prod_raw_db_url,
            build_point_query=build_prod_raw_trade_date_query,
            build_range_query=build_prod_raw_trade_date_range_query,
            fetch_rows=fetch_prod_raw_rows,
            iter_rows=iter_prod_raw_rows,
            known_source_gap_dates=MONEYFLOW_KNOWN_SOURCE_GAPS_BY_DATASET.get(dataset_key, ()),
            progress=self._dataset_progress(dataset_key),
        ).export(
            trade_date=_parse_date(parameters.get("trade_date")),
            start_date=_parse_date(parameters.get("start_date")),
            end_date=_parse_date(parameters.get("end_date")),
            ts_code=_optional_text(parameters.get("ts_code")),
        )

    def _run_lake_reference_dataset(self, *, dataset_key: str, parameters: dict[str, Any]) -> dict[str, Any]:
        client = self._get_tushare_client()
        if dataset_key == "stock_basic":
            return TushareStockBasicSyncService(
                lake_root=self.settings.lake_root,
                client=client,
                progress=self._dataset_progress(dataset_key),
            ).sync()
        if dataset_key == "trade_cal":
            return TushareTradeCalSyncService(
                lake_root=self.settings.lake_root,
                client=client,
                progress=self._dataset_progress(dataset_key),
            ).sync(
                start_date=_parse_date(parameters.get("start_date")),
                end_date=_parse_date(parameters.get("end_date")),
            )
        if dataset_key == "index_basic":
            return TushareIndexBasicSyncService(
                lake_root=self.settings.lake_root,
                client=client,
                progress=self._dataset_progress(dataset_key),
            ).sync(markets=_optional_string_list(parameters.get("market")))
        raise SyncProfileRunnerError(f"lake_reference_refresh 暂不支持数据集：{dataset_key}")

    def _get_tushare_client(self) -> TushareLakeClient:
        if self._tushare_client is None:
            self._tushare_client = TushareLakeClient(
                self.settings.tushare_token,
                request_limit_per_minute=self.settings.tushare_request_limit_per_minute,
            )
        return self._tushare_client

    def _dataset_progress(self, dataset_key: str) -> Callable[[str], None]:
        return lambda message: self.progress(
            {
                "event_type": "dataset_progress",
                "dataset_key": dataset_key,
                "message": message,
            }
        )


def _require_dataset(dataset_key: str, allowed: tuple[str, ...], profile_key: str) -> None:
    if dataset_key not in allowed:
        raise SyncProfileRunnerError(f"{dataset_key} 不在 {profile_key} 数据集白名单内。")


def _parse_date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _optional_text(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def _optional_string_list(value: Any) -> list[str] | None:
    if value in (None, "", [], ()):
        return None
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    return [str(value)]


def _result_from_summary(*, dataset_key: str, summary: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "source",
        "mode",
        "run_id",
        "fetched_rows",
        "written_rows",
        "manifest_written_rows",
        "calendar_written_rows",
        "universe_written_rows",
        "raw_output",
        "manifest_output",
        "calendar_output",
        "universe_output",
        "trade_date",
        "start_date",
        "end_date",
        "trade_date_count",
        "skipped_partitions",
        "source_gap_partitions",
        "no_data_partitions",
        "elapsed_seconds",
    )
    result = {"dataset_key": dataset_key, "status": "success"}
    for key in keys:
        if key in summary:
            result[key] = summary.get(key)
    return result


def _metrics_from_result(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "fetched_rows": result.get("fetched_rows"),
        "written_rows": result.get("written_rows"),
        "manifest_written_rows": result.get("manifest_written_rows")
        or result.get("calendar_written_rows")
        or result.get("universe_written_rows"),
    }


def _safe_int(value: Any) -> int:
    if value is None:
        return 0
    return int(value)
