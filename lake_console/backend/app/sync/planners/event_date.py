from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from lake_console.backend.app.services.prod_raw_event_date_db import (
    PROD_RAW_EVENT_DATE_SOURCE,
    EventDatePartitionCount,
    fetch_event_date_null_count,
    fetch_event_date_partition_counts,
    get_event_date_dataset_spec,
)


PROD_DB_EVENT_DATE_PROFILE_KEY = "prod_db_event_date"


@dataclass(frozen=True)
class EventDatePlanResult:
    dataset_plans: list[dict[str, Any]]
    blockers: list[dict[str, Any]]
    warnings: list[dict[str, Any]]
    affected_event_dates: list[str]


class EventDateSyncPlanner:
    def __init__(self, *, lake_root: Path, database_url: str | None) -> None:
        self.lake_root = lake_root
        self.database_url = database_url

    def build_plan(
        self,
        *,
        dataset_keys: tuple[str, ...],
        target_date: date | None,
        start_date: date | None,
        end_date: date | None,
    ) -> EventDatePlanResult:
        window_start, window_end, mode = _normalize_event_date_window(
            target_date=target_date,
            start_date=start_date,
            end_date=end_date,
        )
        dataset_plans: list[dict[str, Any]] = []
        blockers: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []
        affected_event_dates: set[str] = set()
        for dataset_key in dataset_keys:
            try:
                spec = get_event_date_dataset_spec(dataset_key)
                if spec.block_on_any_null_source_date:
                    null_count = fetch_event_date_null_count(database_url=self.database_url, dataset_key=dataset_key)
                    if null_count > 0:
                        blockers.append(
                            {
                                "dataset_key": dataset_key,
                                "code": "SOURCE_DATE_NULL_ROWS",
                                "message": (
                                    f"{dataset_key} 源日期字段 {spec.source_date_field} 存在 {null_count} 行空值，"
                                    "无法安全写入 event_date 分区。"
                                ),
                                "context": {
                                    "source_date_field": spec.source_date_field,
                                    "null_date_count": null_count,
                                },
                            }
                        )
                        continue
                partitions = fetch_event_date_partition_counts(
                    database_url=self.database_url,
                    dataset_key=dataset_key,
                    start_date=window_start,
                    end_date=window_end,
                )
            except Exception as exc:
                blockers.append({"dataset_key": dataset_key, "code": "PLAN_FAILED", "message": str(exc)})
                continue

            event_dates = {item.event_date for item in partitions}
            zero_row_dates = [
                item.isoformat()
                for item in _iter_calendar_dates(start_date=window_start, end_date=window_end)
                if item not in event_dates
            ]
            if not partitions:
                dataset_plans.append(
                    {
                        "dataset_key": dataset_key,
                        "display_name": spec.display_name,
                        "source": PROD_RAW_EVENT_DATE_SOURCE,
                        "api_name": dataset_key,
                        "mode": mode,
                        "date_axis": "event_date",
                        "partition_field": "event_date",
                        "source_date_field": spec.source_date_field,
                        "request_strategy_key": "prod_db_event_date_preflight",
                        "request_count": 0,
                        "partition_count": 0,
                        "write_policy": "replace_partition",
                        "write_paths": [],
                        "required_manifests": [],
                        "parameters": _parameters(
                            window_start=window_start,
                            window_end=window_end,
                            source_date_field=spec.source_date_field,
                            event_dates=[],
                        ),
                        "event_date_partitions": [],
                        "zero_row_dates": zero_row_dates,
                        "zero_row_date_count": len(zero_row_dates),
                        "source_row_count": 0,
                        "coverage_label": (
                            f"事件日期 {window_start.isoformat()} 至 {window_end.isoformat()}，没有源端数据。"
                        ),
                        "status": "no_rows_no_write",
                        "notes": [
                            "事件日期分区不做连续日期完整性审计。",
                            "0 行日期不会创建空分区。",
                        ],
                    }
                )
                blockers.append(
                    {
                        "dataset_key": dataset_key,
                        "code": "NO_EVENT_DATE_ROWS",
                        "message": (
                            f"{dataset_key} 在事件日期 {window_start.isoformat()} 至 {window_end.isoformat()} "
                            "没有源端数据，不能启动写入任务。"
                        ),
                        "context": {"zero_row_date_count": len(zero_row_dates)},
                    }
                )
                continue

            partition_dicts = _partition_dicts(dataset_key=dataset_key, partitions=partitions)
            for partition in partition_dicts:
                affected_event_dates.add(str(partition["event_date"]))
            source_row_count = sum(item.source_row_count for item in partitions)
            dataset_plans.append(
                {
                    "dataset_key": dataset_key,
                    "display_name": spec.display_name,
                    "source": PROD_RAW_EVENT_DATE_SOURCE,
                    "api_name": dataset_key,
                    "mode": mode,
                    "date_axis": "event_date",
                    "partition_field": "event_date",
                    "source_date_field": spec.source_date_field,
                    "request_strategy_key": "prod_db_event_date_preflight",
                    "request_count": len(partitions),
                    "partition_count": len(partitions),
                    "write_policy": "replace_partition",
                    "write_paths": [str(item["write_path"]) for item in partition_dicts],
                    "required_manifests": [],
                    "parameters": _parameters(
                        window_start=window_start,
                        window_end=window_end,
                        source_date_field=spec.source_date_field,
                        event_dates=[item.event_date.isoformat() for item in partitions],
                    ),
                    "event_date_partitions": partition_dicts,
                    "zero_row_dates": zero_row_dates,
                    "zero_row_date_count": len(zero_row_dates),
                    "source_row_count": source_row_count,
                    "coverage_label": (
                        f"事件日期 {window_start.isoformat()} 至 {window_end.isoformat()}，"
                        f"{len(partitions)} 个有数据日期。"
                    ),
                    "status": "will_run",
                    "notes": [
                        "事件日期分区不做连续日期完整性审计。",
                        "0 行日期不会创建空分区。",
                    ],
                }
            )
        return EventDatePlanResult(
            dataset_plans=dataset_plans,
            blockers=blockers,
            warnings=warnings,
            affected_event_dates=sorted(affected_event_dates),
        )


def _normalize_event_date_window(
    *,
    target_date: date | None,
    start_date: date | None,
    end_date: date | None,
) -> tuple[date, date, str]:
    has_target = target_date is not None
    has_range = start_date is not None or end_date is not None
    if has_target and has_range:
        raise ValueError("prod_db_event_date 不能同时传 target_date 和 start_date/end_date。")
    if has_target:
        return target_date, target_date, "event_date_point"
    if start_date is None or end_date is None:
        raise ValueError("prod_db_event_date 必须传 target_date，或同时传 start_date/end_date。")
    if end_date < start_date:
        raise ValueError("prod_db_event_date end_date 不能早于 start_date。")
    return start_date, end_date, "event_date_range"


def _iter_calendar_dates(*, start_date: date, end_date: date) -> list[date]:
    dates: list[date] = []
    current = start_date
    while current <= end_date:
        dates.append(current)
        current += timedelta(days=1)
    return dates


def _partition_dicts(*, dataset_key: str, partitions: list[EventDatePartitionCount]) -> list[dict[str, Any]]:
    return [
        {
            "event_date": item.event_date.isoformat(),
            "source_row_count": item.source_row_count,
            "write_path": _event_date_write_path(dataset_key=dataset_key, event_date=item.event_date),
        }
        for item in partitions
    ]


def _event_date_write_path(*, dataset_key: str, event_date: date) -> str:
    return f"raw_tushare/{dataset_key}/event_date={event_date.isoformat()}"


def _parameters(
    *,
    window_start: date,
    window_end: date,
    source_date_field: str,
    event_dates: list[str],
) -> dict[str, Any]:
    return {
        "start_date": window_start.isoformat(),
        "end_date": window_end.isoformat(),
        "source_date_field": source_date_field,
        "event_dates": event_dates,
    }
