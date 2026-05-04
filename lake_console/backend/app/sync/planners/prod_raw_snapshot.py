from __future__ import annotations

from datetime import date

from lake_console.backend.app.catalog.models import LakeDatasetDefinition
from lake_console.backend.app.services.prod_raw_db import PROD_RAW_DB_SOURCE
from lake_console.backend.app.sync.plans import LakeSyncPlan


def build_prod_raw_snapshot_plan(
    definition: LakeDatasetDefinition,
    *,
    trade_date: date | None,
    start_date: date | None,
    end_date: date | None,
    ts_code: str | None,
    market: str | None,
    name: str | None,
    publisher: str | None,
    category: str | None,
) -> LakeSyncPlan:
    _reject_unsupported_parameters(
        dataset_key=definition.dataset_key,
        trade_date=trade_date,
        start_date=start_date,
        end_date=end_date,
        ts_code=ts_code,
        market=market,
        name=name,
        publisher=publisher,
        category=category,
    )
    return LakeSyncPlan(
        dataset_key=definition.dataset_key,
        display_name=definition.display_name,
        source=PROD_RAW_DB_SOURCE,
        api_name=definition.api_name,
        mode="snapshot_refresh",
        request_strategy_key=f"{definition.dataset_key}:prod-raw-db",
        request_count=1,
        partition_count=len(definition.layers),
        write_policy=definition.write_policy,
        write_paths=tuple(layer.path for layer in definition.layers),
        required_manifests=(),
        parameters={},
        notes=(
            "current_file 快照只允许全量替换，不接受筛选子集覆盖正式文件。",
            "从生产库 raw_tushare 白名单表只读导出，按字段白名单投影，不请求 Tushare。",
            "执行完成后必须同时替换 raw current 与对应 manifest 文件。",
        ),
    )


def _reject_unsupported_parameters(
    *,
    dataset_key: str,
    trade_date: date | None,
    start_date: date | None,
    end_date: date | None,
    ts_code: str | None,
    market: str | None,
    name: str | None,
    publisher: str | None,
    category: str | None,
) -> None:
    unsupported = {
        "trade_date": trade_date,
        "start_date": start_date,
        "end_date": end_date,
        "ts_code": ts_code,
        "market": market,
        "name": name,
        "publisher": publisher,
        "category": category,
    }
    provided = [key for key, value in unsupported.items() if value not in (None, "")]
    if provided:
        joined = ", ".join(provided)
        raise ValueError(f"{dataset_key} --from prod-raw-db 第一阶段只支持全量 current 快照，不支持参数：{joined}")
