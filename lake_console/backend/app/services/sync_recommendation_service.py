from __future__ import annotations

from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from lake_console.backend.app.catalog.datasets import get_dataset_definition
from lake_console.backend.app.services.filesystem_scanner import FilesystemScanner
from lake_console.backend.app.services.parquet_writer import read_parquet_rows
from lake_console.backend.app.services.prod_core_db import PROD_CORE_DB_SOURCE
from lake_console.backend.app.services.prod_raw_db import PROD_RAW_DB_SOURCE
from lake_console.backend.app.services.sync_center_profiles import (
    PROD_CORE_DAILY_DATASETS,
    PROD_DB_DAILY_DATASETS,
)
from lake_console.backend.app.sync.helpers.dates import load_expected_partition_dates
from lake_console.backend.app.sync.helpers.params import parse_date


LOCAL_TZ = ZoneInfo("Asia/Shanghai")
DEFAULT_CUTOFF_TIME = time(hour=20, minute=0)


class CalendarUnavailableError(RuntimeError):
    pass


class SyncRecommendationService:
    """Build read-only Sync Center date-window recommendations."""

    def __init__(self, *, lake_root: Path, now: datetime | None = None, cutoff_time: time = DEFAULT_CUTOFF_TIME) -> None:
        self.lake_root = lake_root
        self.now = _normalize_now(now)
        self.cutoff_time = cutoff_time
        self.scanner = FilesystemScanner(lake_root)

    def build(self, *, profile_key: str = "prod_db_daily") -> dict[str, Any]:
        if profile_key != "prod_db_daily":
            raise ValueError("建议同步窗口第一版只支持 profile_key=prod_db_daily。")

        try:
            open_dates = self._load_calendar_open_dates()
            expected_reference_date = self._expected_reference_date(open_dates)
        except CalendarUnavailableError as exc:
            return {
                "generated_at": self.now.isoformat(),
                "profile_key": profile_key,
                "cutoff_time": _format_cutoff_time(self.cutoff_time),
                "expected_reference_date": None,
                "items": self._blocked_items(reason=str(exc)),
            }

        items = [
            self._recommend_dataset(
                dataset_key=dataset_key,
                open_dates=open_dates,
                expected_reference_date=expected_reference_date,
            )
            for dataset_key in PROD_DB_DAILY_DATASETS
        ]
        return {
            "generated_at": self.now.isoformat(),
            "profile_key": profile_key,
            "cutoff_time": _format_cutoff_time(self.cutoff_time),
            "expected_reference_date": expected_reference_date.isoformat(),
            "aggregate_plan_hint": self._aggregate_lagging_plan_hint(items),
            "items": items,
        }

    def _recommend_dataset(
        self,
        *,
        dataset_key: str,
        open_dates: list[date],
        expected_reference_date: date,
    ) -> dict[str, Any]:
        definition = get_dataset_definition(dataset_key)
        source = PROD_CORE_DB_SOURCE if dataset_key in PROD_CORE_DAILY_DATASETS else PROD_RAW_DB_SOURCE
        local_latest = self._local_latest_trade_date(dataset_key)

        try:
            expected_dates = load_expected_partition_dates(
                lake_root=self.lake_root,
                dataset_key=dataset_key,
                start_date=open_dates[0],
                end_date=expected_reference_date,
            )
        except Exception as exc:
            return self._item(
                dataset_key=dataset_key,
                display_name=definition.display_name,
                source=source,
                status="not_applicable",
                local_latest_trade_date=local_latest,
                reason=f"该数据集暂不能生成连续日期建议：{exc}",
            )

        if not expected_dates:
            return self._item(
                dataset_key=dataset_key,
                display_name=definition.display_name,
                source=source,
                status="not_applicable",
                local_latest_trade_date=local_latest,
                reason="交易日历内没有可用于该数据集的日期锚点。",
            )

        expected_latest = max(expected_dates)
        if local_latest is None:
            return self._item(
                dataset_key=dataset_key,
                display_name=definition.display_name,
                source=source,
                status="empty",
                expected_latest_trade_date=expected_latest,
                reason="本地未发现日期分区，需要人工确认首次同步起点。",
            )

        if local_latest >= expected_latest:
            return self._item(
                dataset_key=dataset_key,
                display_name=definition.display_name,
                source=source,
                status="up_to_date",
                local_latest_trade_date=local_latest,
                expected_latest_trade_date=expected_latest,
                reason="本地最新分区已经达到交易日历理论应到日期。",
            )

        missing_dates = load_expected_partition_dates(
            lake_root=self.lake_root,
            dataset_key=dataset_key,
            start_date=local_latest + timedelta(days=1),
            end_date=expected_latest,
        )
        suggested_start_date = min(missing_dates) if missing_dates else local_latest + timedelta(days=1)
        return self._item(
            dataset_key=dataset_key,
            display_name=definition.display_name,
            source=source,
            status="lagging",
            local_latest_trade_date=local_latest,
            expected_latest_trade_date=expected_latest,
            suggested_start_date=suggested_start_date,
            suggested_end_date=expected_latest,
            lag_anchor_count=len(missing_dates),
            lag_calendar_days=(expected_latest - local_latest).days,
            reason="本地最新分区早于交易日历理论应到日期。",
            plan_hint={
                "profile_key": "prod_db_manual_backfill",
                "dataset_keys": [dataset_key],
                "target_date": None,
                "start_date": suggested_start_date.isoformat(),
                "end_date": expected_latest.isoformat(),
            },
        )

    def _local_latest_trade_date(self, dataset_key: str) -> date | None:
        definition = get_dataset_definition(dataset_key)
        try:
            node = definition.require_node(layer="raw_tushare")
        except RuntimeError:
            return None
        if "trade_date" not in node.partition_dimensions:
            return None
        dates: list[date] = []
        for partition in self.scanner.list_partitions(dataset_key=dataset_key, node_key=node.node_key or ""):
            value = partition.partition_values.get("trade_date")
            if value is None:
                continue
            try:
                dates.append(parse_date(value))
            except ValueError:
                continue
        return max(dates) if dates else None

    def _blocked_items(self, *, reason: str) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for dataset_key in PROD_DB_DAILY_DATASETS:
            definition = get_dataset_definition(dataset_key)
            source = PROD_CORE_DB_SOURCE if dataset_key in PROD_CORE_DAILY_DATASETS else PROD_RAW_DB_SOURCE
            items.append(
                self._item(
                    dataset_key=dataset_key,
                    display_name=definition.display_name,
                    source=source,
                    status="blocked_missing_calendar",
                    local_latest_trade_date=self._local_latest_trade_date(dataset_key),
                    reason=reason,
                )
            )
        return items

    def _load_calendar_open_dates(self) -> list[date]:
        calendar_file = self.lake_root / "manifest" / "trading_calendar" / "tushare_trade_cal.parquet"
        if not calendar_file.exists():
            raise CalendarUnavailableError(
                "缺少本地交易日历 manifest/trading_calendar/tushare_trade_cal.parquet，请先刷新 trade_cal。"
            )
        rows = read_parquet_rows(calendar_file)
        open_dates = sorted({parse_date(row.get("cal_date")) for row in rows if _is_open(row.get("is_open"))})
        if not open_dates:
            raise CalendarUnavailableError("本地交易日历没有任何开市日期，请先刷新 trade_cal。")
        return open_dates

    def _expected_reference_date(self, open_dates: list[date]) -> date:
        today = self.now.date()
        if today in set(open_dates) and self.now.timetz().replace(tzinfo=None) < self.cutoff_time:
            candidates = [item for item in open_dates if item < today]
        else:
            candidates = [item for item in open_dates if item <= today]
        if not candidates:
            raise CalendarUnavailableError("交易日历中没有可用于生成建议的历史开市日期。")
        return max(candidates)

    @staticmethod
    def _item(
        *,
        dataset_key: str,
        display_name: str,
        source: str,
        status: str,
        reason: str,
        local_latest_trade_date: date | None = None,
        expected_latest_trade_date: date | None = None,
        suggested_start_date: date | None = None,
        suggested_end_date: date | None = None,
        lag_anchor_count: int = 0,
        lag_calendar_days: int = 0,
        plan_hint: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "dataset_key": dataset_key,
            "display_name": display_name,
            "source": source,
            "status": status,
            "local_latest_trade_date": local_latest_trade_date.isoformat() if local_latest_trade_date else None,
            "expected_latest_trade_date": expected_latest_trade_date.isoformat() if expected_latest_trade_date else None,
            "suggested_start_date": suggested_start_date.isoformat() if suggested_start_date else None,
            "suggested_end_date": suggested_end_date.isoformat() if suggested_end_date else None,
            "lag_anchor_count": lag_anchor_count,
            "lag_calendar_days": lag_calendar_days,
            "reason": reason,
            "plan_hint": plan_hint,
        }

    @staticmethod
    def _aggregate_lagging_plan_hint(items: list[dict[str, Any]]) -> dict[str, Any] | None:
        lagging_items = [
            item
            for item in items
            if item.get("status") == "lagging"
            and item.get("plan_hint")
            and item.get("suggested_start_date")
            and item.get("suggested_end_date")
        ]
        if not lagging_items:
            return None
        start_date = min(str(item["suggested_start_date"]) for item in lagging_items)
        end_date = max(str(item["suggested_end_date"]) for item in lagging_items)
        return {
            "profile_key": "prod_db_manual_backfill",
            "dataset_keys": [str(item["dataset_key"]) for item in lagging_items],
            "target_date": None,
            "start_date": start_date,
            "end_date": end_date,
        }


def _normalize_now(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(LOCAL_TZ)
    if value.tzinfo is None:
        return value.replace(tzinfo=LOCAL_TZ)
    return value.astimezone(LOCAL_TZ)


def _format_cutoff_time(value: time) -> str:
    return value.strftime("%H:%M")


def _is_open(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value == 1
    raw = str(value).strip().lower()
    return raw in {"1", "true", "t", "yes", "y", "open"}
