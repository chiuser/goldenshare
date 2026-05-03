from __future__ import annotations

from datetime import date
from typing import Any

from lake_console.backend.app.catalog.models import LakeDatasetDefinition
from lake_console.backend.app.sync.helpers.params import parse_csv
from lake_console.backend.app.sync.plans import LakeSyncPlan


def build_snapshot_plan(
    definition: LakeDatasetDefinition,
    *,
    start_date: date | None,
    end_date: date | None,
    market: str | None,
) -> LakeSyncPlan:
    notes = ["快照类数据集以 current 文件为替换范围。"]
    parameters: dict[str, Any] = {}
    if definition.dataset_key == "trade_cal":
        if start_date is None or end_date is None:
            raise ValueError("trade_cal 计划预览必须传 --start-date 和 --end-date。")
        if end_date < start_date:
            raise ValueError("--end-date 不能早于 --start-date。")
        parameters = {"start_date": start_date.isoformat(), "end_date": end_date.isoformat()}
        notes = ["trade_cal 会双落盘 raw current 与交易日历 manifest。"]
    if market:
        parameters["market"] = parse_csv(market)
    return LakeSyncPlan(
        dataset_key=definition.dataset_key,
        display_name=definition.display_name,
        source=definition.source,
        api_name=definition.api_name,
        mode="snapshot_refresh",
        request_strategy_key=definition.dataset_key,
        request_count=len(parse_csv(market)) if market else 1,
        partition_count=len(definition.layers),
        write_policy=definition.write_policy,
        write_paths=tuple(layer.path for layer in definition.layers),
        required_manifests=(),
        parameters=parameters,
        notes=tuple(notes),
    )
