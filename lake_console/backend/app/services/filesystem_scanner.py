from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from lake_console.backend.app.catalog.datasets import list_dataset_definitions
from lake_console.backend.app.catalog.models import LakeDatasetDefinition, LakeNodeDefinition, get_layer_definition
from lake_console.backend.app.catalog.view_groups import get_view_group
from lake_console.backend.app.schemas import (
    LakeDatasetSummary,
    LakeNodeSummary,
    LakeOverviewDatasetRow,
    LakeOverviewLayerGroup,
    LakeOverviewMetric,
    LakeOverviewResponse,
    LakeOverviewSyncMethodGroup,
    LakePartitionSummary,
    LakePhysicalAssetSummary,
    LakeRiskItem,
)

LAKE_ASSET_ROOTS = ("raw_tushare", "manifest", "derived", "research")
GOVERNANCE_ASSET_ROOTS = ("_tmp", "_recovery")
IGNORED_SYSTEM_FILE_NAMES = {".DS_Store"}


class FilesystemScanner:
    def __init__(self, lake_root: Path) -> None:
        self.lake_root = lake_root

    def list_datasets(
        self,
        *,
        dataset_key: str | None = None,
        node_key: str | None = None,
        layer: str | None = None,
        registered_state: str | None = None,
    ) -> list[LakeDatasetSummary]:
        result: list[LakeDatasetSummary] = []
        for definition in list_dataset_definitions():
            if dataset_key and definition.dataset_key != dataset_key:
                continue
            summary = self._dataset_summary(
                definition,
                node_key=node_key,
                layer=layer,
                registered_state=registered_state,
            )
            if summary is not None:
                result.append(summary)
        return sorted(result, key=lambda item: (item.sort_order, item.group_order or 999, item.dataset_key))

    def list_partitions(
        self,
        *,
        dataset_key: str,
        node_key: str,
        freq: int | None = None,
        trade_date_from: str | None = None,
        trade_date_to: str | None = None,
        event_date_from: str | None = None,
        event_date_to: str | None = None,
        trade_month: str | None = None,
        bucket: int | None = None,
        indicator: str | None = None,
        params_key: str | None = None,
    ) -> list[LakePartitionSummary]:
        definition = _require_dataset(dataset_key)
        node = definition.require_node(node_key=node_key)
        result = []
        for item in self._scan_partitions(definition, node):
            values = item.partition_values
            if freq is not None and values.get("freq") != freq:
                continue
            if trade_date_from and isinstance(values.get("trade_date"), str) and values["trade_date"] < trade_date_from:
                continue
            if trade_date_to and isinstance(values.get("trade_date"), str) and values["trade_date"] > trade_date_to:
                continue
            if event_date_from and isinstance(values.get("event_date"), str) and values["event_date"] < event_date_from:
                continue
            if event_date_to and isinstance(values.get("event_date"), str) and values["event_date"] > event_date_to:
                continue
            if trade_month and values.get("trade_month") != trade_month:
                continue
            if bucket is not None and values.get("bucket") != bucket:
                continue
            if indicator and values.get("indicator") != indicator:
                continue
            if params_key and values.get("params_key") != params_key:
                continue
            result.append(item)
        return sorted(result, key=lambda item: (item.dataset_key, item.node_key, item.partition_locator))

    def list_physical_assets(
        self,
        *,
        registered_state: str | None = None,
        path_prefix: str | None = None,
        asset_type: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[LakePhysicalAssetSummary]:
        items = self._physical_assets(include_ignored=registered_state == "ignored")
        if registered_state:
            items = [item for item in items if item.registered_state == registered_state]
        if path_prefix:
            items = [item for item in items if item.path.startswith(path_prefix)]
        if asset_type:
            items = [item for item in items if item.asset_type == asset_type]
        return items[offset : offset + limit]

    def physical_asset_total(
        self,
        *,
        registered_state: str | None = None,
        path_prefix: str | None = None,
        asset_type: str | None = None,
    ) -> int:
        return len(
            self.list_physical_assets(
                registered_state=registered_state,
                path_prefix=path_prefix,
                asset_type=asset_type,
                limit=10**9,
                offset=0,
            )
        )

    def overview(self) -> LakeOverviewResponse:
        datasets = self.list_datasets()
        physical_assets = self._physical_assets()
        total_bytes = sum(dataset.total_bytes for dataset in datasets)
        total_files = sum(dataset.file_count for dataset in datasets)
        total_partitions = sum(dataset.partition_count for dataset in datasets)
        ready_count = sum(1 for dataset in datasets if dataset.file_count > 0)
        risks = [risk for dataset in datasets for risk in dataset.risks]
        unregistered_count = sum(1 for item in physical_assets if item.registered_state == "unregistered")
        return LakeOverviewResponse(
            generated_at=datetime.now(timezone.utc),
            lake_root=str(self.lake_root),
            summary_metrics=[
                LakeOverviewMetric(key="datasets", label="数据集", value=_format_count(len(datasets)), hint=f"{_format_count(ready_count)} 个已有文件落盘", sort_order=10),
                LakeOverviewMetric(key="registered_bytes", label="已登记容量", value=_format_bytes(total_bytes), hint="按后端 Catalog 节点扫描聚合", sort_order=20),
                LakeOverviewMetric(key="files_partitions", label="文件 / 分区", value=f"{_format_count(total_files)} / {_format_count(total_partitions)}", hint="所有已登记节点合计", sort_order=30),
                LakeOverviewMetric(
                    key="unregistered_assets",
                    label="未登记资产",
                    value=_format_count(unregistered_count),
                    hint="不含已登记节点父目录和系统文件",
                    tone="warning" if unregistered_count else "success",
                    sort_order=40,
                ),
            ],
            layer_groups=self._overview_layer_groups(datasets),
            sync_method_groups=self._overview_sync_groups(),
            dataset_rows=[
                LakeOverviewDatasetRow(
                    dataset_key=dataset.dataset_key,
                    display_name=dataset.display_name,
                    group_label=dataset.group_label or "-",
                    source_label=dataset.source_label,
                    node_count=len(dataset.node_summaries),
                    partition_count=dataset.partition_count,
                    file_count=dataset.file_count,
                    total_bytes=dataset.total_bytes,
                    coverage_label=dataset.coverage_label,
                    health_status=dataset.health_status,
                    health_label=dataset.health_label,
                    primary_path=dataset.node_summaries[0].path if dataset.node_summaries else None,
                    sort_order=dataset.sort_order,
                )
                for dataset in datasets
            ],
            physical_assets=physical_assets[:200],
            risks=risks,
        )

    def _dataset_summary(
        self,
        definition: LakeDatasetDefinition,
        *,
        node_key: str | None,
        layer: str | None,
        registered_state: str | None,
    ) -> LakeDatasetSummary | None:
        nodes = [item for item in definition.nodes if node_key in {None, item.node_key} and layer in {None, item.layer}]
        if not nodes:
            return None
        node_summaries = [self._node_summary(definition, node) for node in nodes]
        if registered_state:
            node_summaries = [item for item in node_summaries if item.registered_state == registered_state]
        if not node_summaries:
            return None

        risks = [risk for node_summary in node_summaries for risk in node_summary.risks]
        file_count = sum(node_summary.file_count for node_summary in node_summaries)
        partition_count = sum(node_summary.partition_count for node_summary in node_summaries)
        total_bytes = sum(node_summary.total_bytes for node_summary in node_summaries)
        modified_values = [item.latest_modified_at for item in node_summaries if item.latest_modified_at]
        freqs = sorted({freq for node_summary in node_summaries for freq in node_summary.freqs})
        coverage_label = _coverage_label(node_summaries)
        group = get_view_group(definition.group_key)
        health_status = "empty"
        if file_count > 0:
            health_status = "warning" if risks else "ok"

        return LakeDatasetSummary(
            dataset_key=definition.dataset_key,
            display_name=definition.display_name,
            source=definition.source,
            source_label=_source_label(definition.source),
            category=group.group_label,
            group_key=group.group_key,
            group_label=group.group_label,
            group_order=group.group_order,
            description=definition.description,
            dataset_role=definition.dataset_role,
            dataset_role_label=_dataset_role_label(definition.dataset_role),
            node_summaries=node_summaries,
            freqs=freqs,
            supported_freqs=list(definition.supported_freqs),
            raw_freqs=list(definition.raw_freqs),
            derived_freqs=list(definition.derived_freqs),
            partition_count=partition_count,
            file_count=file_count,
            total_bytes=total_bytes,
            row_count=None,
            earliest_trade_date=_min_node_field(node_summaries, "earliest_trade_date"),
            latest_trade_date=_max_node_field(node_summaries, "latest_trade_date"),
            earliest_event_date=_min_node_field(node_summaries, "earliest_event_date"),
            latest_event_date=_max_node_field(node_summaries, "latest_event_date"),
            earliest_trade_month=_min_node_field(node_summaries, "earliest_trade_month"),
            latest_trade_month=_max_node_field(node_summaries, "latest_trade_month"),
            latest_modified_at=max(modified_values) if modified_values else None,
            coverage_label=coverage_label,
            health_status=health_status,
            health_label=_health_label(health_status),
            risks=self._dataset_risks(risks),
            sort_order=(group.group_order * 1000),
        )

    def _node_summary(self, definition: LakeDatasetDefinition, node: LakeNodeDefinition) -> LakeNodeSummary:
        partitions = self._scan_partitions(definition, node)
        risks = [risk for partition in partitions for risk in partition.risks]
        modified_values = [item.modified_at for item in partitions if item.modified_at]
        freqs = sorted({value for partition in partitions for value in [_partition_int(partition, "freq")] if value is not None})
        trade_dates = [_partition_str(partition, "trade_date") for partition in partitions if _partition_str(partition, "trade_date")]
        event_dates = [_partition_str(partition, "event_date") for partition in partitions if _partition_str(partition, "event_date")]
        trade_months = [_partition_str(partition, "trade_month") for partition in partitions if _partition_str(partition, "trade_month")]
        layer_definition = get_layer_definition(node.layer)
        registered_state = "registered" if (self.lake_root / node.path).exists() else "missing_on_disk"
        return LakeNodeSummary(
            dataset_key=definition.dataset_key,
            node_key=node.node_key or "",
            node_name=node.node_name,
            layer=node.layer,
            layer_name=layer_definition.layer_name,
            path=node.path,
            scan_profile=node.scan_profile,
            asset_role=node.asset_role or "lake_asset",
            asset_role_label=_asset_role_label(node.asset_role or "lake_asset"),
            source_node_keys=list(node.source_node_keys),
            partition_dimensions=list(node.partition_dimensions),
            partition_count=len(partitions),
            file_count=sum(partition.file_count for partition in partitions),
            total_bytes=sum(partition.total_bytes for partition in partitions),
            freqs=freqs,
            earliest_trade_date=min(trade_dates) if trade_dates else None,
            latest_trade_date=max(trade_dates) if trade_dates else None,
            earliest_event_date=min(event_dates) if event_dates else None,
            latest_event_date=max(event_dates) if event_dates else None,
            earliest_trade_month=min(trade_months) if trade_months else None,
            latest_trade_month=max(trade_months) if trade_months else None,
            latest_modified_at=max(modified_values) if modified_values else None,
            coverage_label=_partition_coverage_label(partitions),
            recommended_usage=node.recommended_usage,
            registered_state=registered_state,
            risks=risks,
        )

    def _scan_partitions(self, definition: LakeDatasetDefinition, node: LakeNodeDefinition) -> list[LakePartitionSummary]:
        root = self.lake_root / node.path
        if node.scan_profile in {"current_file", "manifest_file"}:
            return self._scan_single_file(definition, node, root)
        if node.scan_profile == "trade_date":
            return self._scan_trade_date_dirs(definition, node, root, base_values={})
        if node.scan_profile == "event_date":
            return self._scan_event_date_dirs(definition, node, root, base_values={})
        if node.scan_profile == "freq_trade_date":
            return self._scan_freq_trade_date(definition, node, root, base_values={})
        if node.scan_profile == "freq_trade_month_bucket":
            return self._scan_freq_trade_month_bucket(definition, node, root, base_values={})
        if node.scan_profile == "indicator_params_freq_trade_date":
            return self._scan_indicator_profile(definition, node, root, by_month=False)
        if node.scan_profile == "indicator_params_freq_trade_month_bucket":
            return self._scan_indicator_profile(definition, node, root, by_month=True)
        return []

    def _scan_single_file(self, definition: LakeDatasetDefinition, node: LakeNodeDefinition, file_path: Path) -> list[LakePartitionSummary]:
        if not file_path.exists():
            return []
        return [self._partition_summary(definition=definition, node=node, path=file_path, files=[file_path], values={})]

    def _scan_freq_trade_date(
        self,
        definition: LakeDatasetDefinition,
        node: LakeNodeDefinition,
        root: Path,
        *,
        base_values: dict[str, Any],
    ) -> list[LakePartitionSummary]:
        if not root.exists():
            return []
        result: list[LakePartitionSummary] = []
        for freq_dir in root.glob("freq=*"):
            freq = _parse_freq_partition(freq_dir.name)
            if freq is None:
                continue
            result.extend(self._scan_trade_date_dirs(definition, node, freq_dir, base_values={**base_values, "freq": freq}))
        return result

    def _scan_trade_date_dirs(
        self,
        definition: LakeDatasetDefinition,
        node: LakeNodeDefinition,
        root: Path,
        *,
        base_values: dict[str, Any],
    ) -> list[LakePartitionSummary]:
        if not root.exists():
            return []
        result: list[LakePartitionSummary] = []
        for date_dir in root.glob("trade_date=*"):
            trade_date = _parse_str_partition(date_dir.name, "trade_date")
            if trade_date is None:
                continue
            files = list(date_dir.glob("*.parquet"))
            result.append(self._partition_summary(definition=definition, node=node, path=date_dir, files=files, values={**base_values, "trade_date": trade_date}))
        return result

    def _scan_event_date_dirs(
        self,
        definition: LakeDatasetDefinition,
        node: LakeNodeDefinition,
        root: Path,
        *,
        base_values: dict[str, Any],
    ) -> list[LakePartitionSummary]:
        if not root.exists():
            return []
        result: list[LakePartitionSummary] = []
        for date_dir in root.glob("event_date=*"):
            event_date = _parse_str_partition(date_dir.name, "event_date")
            if event_date is None:
                continue
            files = list(date_dir.glob("*.parquet"))
            result.append(self._partition_summary(definition=definition, node=node, path=date_dir, files=files, values={**base_values, "event_date": event_date}))
        return result

    def _scan_freq_trade_month_bucket(
        self,
        definition: LakeDatasetDefinition,
        node: LakeNodeDefinition,
        root: Path,
        *,
        base_values: dict[str, Any],
    ) -> list[LakePartitionSummary]:
        if not root.exists():
            return []
        result: list[LakePartitionSummary] = []
        for freq_dir in root.glob("freq=*"):
            freq = _parse_freq_partition(freq_dir.name)
            if freq is None:
                continue
            for month_dir in freq_dir.glob("trade_month=*"):
                trade_month = _parse_str_partition(month_dir.name, "trade_month")
                if trade_month is None:
                    continue
                for bucket_dir in month_dir.glob("bucket=*"):
                    bucket = _parse_int_partition(bucket_dir.name, "bucket")
                    if bucket is None:
                        continue
                    files = list(bucket_dir.glob("*.parquet"))
                    values = {**base_values, "freq": freq, "trade_month": trade_month, "bucket": bucket}
                    result.append(self._partition_summary(definition=definition, node=node, path=bucket_dir, files=files, values=values))
        return result

    def _scan_indicator_profile(
        self,
        definition: LakeDatasetDefinition,
        node: LakeNodeDefinition,
        root: Path,
        *,
        by_month: bool,
    ) -> list[LakePartitionSummary]:
        if not root.exists():
            return []
        result: list[LakePartitionSummary] = []
        for indicator_dir in root.glob("indicator=*"):
            indicator = _parse_str_partition(indicator_dir.name, "indicator")
            if indicator is None:
                continue
            for params_dir in indicator_dir.glob("params_key=*"):
                params_key = _parse_str_partition(params_dir.name, "params_key")
                if params_key is None:
                    continue
                base_values = {"indicator": indicator, "params_key": params_key}
                if by_month:
                    result.extend(self._scan_freq_trade_month_bucket(definition, node, params_dir, base_values=base_values))
                else:
                    result.extend(self._scan_freq_trade_date(definition, node, params_dir, base_values=base_values))
        return result

    def _partition_summary(
        self,
        *,
        definition: LakeDatasetDefinition,
        node: LakeNodeDefinition,
        path: Path,
        files: list[Path],
        values: dict[str, Any],
    ) -> LakePartitionSummary:
        total_bytes = sum(file.stat().st_size for file in files if file.exists())
        modified_timestamps = [file.stat().st_mtime for file in files if file.exists()]
        risks: list[LakeRiskItem] = []
        if any(file.stat().st_size == 0 for file in files if file.exists()):
            risks.append(LakeRiskItem(severity="warning", code="empty_file", message="分区中存在空 Parquet 文件。", path=_relative_path(self.lake_root, path)))
        return LakePartitionSummary(
            dataset_key=definition.dataset_key,
            node_key=node.node_key or "",
            partition_values=values,
            partition_locator=_partition_locator(values),
            partition_label=_partition_label(values),
            path=_relative_path(self.lake_root, path),
            file_count=len(files),
            total_bytes=total_bytes,
            modified_at=datetime.fromtimestamp(max(modified_timestamps), tz=timezone.utc) if modified_timestamps else None,
            risks=risks,
        )

    def _physical_assets(self, *, include_ignored: bool = False) -> list[LakePhysicalAssetSummary]:
        registered_nodes: dict[str, tuple[str, str]] = {}
        for definition in list_dataset_definitions():
            for node in definition.nodes:
                registered_nodes[node.path] = (definition.dataset_key, node.node_key)

        registered_containers = _registered_container_paths(registered_nodes)
        candidates = set(registered_nodes)
        for root_name in LAKE_ASSET_ROOTS:
            root = self.lake_root / root_name
            if not root.exists():
                continue
            for child in root.iterdir():
                candidates.add(_relative_path(self.lake_root, child))
        for governance in GOVERNANCE_ASSET_ROOTS:
            path = self.lake_root / governance
            if path.exists():
                candidates.add(governance)

        items: list[LakePhysicalAssetSummary] = []
        for relative in candidates:
            path = self.lake_root / relative
            if not path.exists():
                continue
            registered_node = registered_nodes.get(relative)
            registered_state = _physical_asset_state(
                relative,
                is_registered_node=registered_node is not None,
                is_registered_container=relative in registered_containers,
            )
            if registered_state == "ignored" and not include_ignored:
                continue

            dataset_key = registered_node[0] if registered_node else _single_or_none(registered_containers.get(relative, set()))
            node_key = registered_node[1] if registered_node else None
            stats = _path_stats(path)
            risk_level, risk_label = _physical_asset_risk(registered_state)
            items.append(
                LakePhysicalAssetSummary(
                    path=relative,
                    asset_type="directory" if path.is_dir() else "file",
                    registered_state=registered_state,
                    dataset_key=dataset_key,
                    node_key=node_key,
                    display_name=_physical_asset_name(relative, registered_state=registered_state, dataset_key=dataset_key, node_key=node_key),
                    total_bytes=stats["total_bytes"],
                    file_count=stats["file_count"],
                    dir_count=stats["dir_count"],
                    latest_modified_at=stats["latest_modified_at"],
                    risk_level=risk_level,
                    risk_label=risk_label,
                )
            )
        return sorted(items, key=_physical_asset_sort_key)

    def _overview_layer_groups(self, datasets: list[LakeDatasetSummary]) -> list[LakeOverviewLayerGroup]:
        drafts: dict[str, dict[str, Any]] = {}
        for dataset in datasets:
            for node in dataset.node_summaries:
                draft = drafts.setdefault(
                    node.layer,
                    {
                        "datasets": set(),
                        "node_count": 0,
                        "partition_count": 0,
                        "file_count": 0,
                        "total_bytes": 0,
                        "freqs": set(),
                        "paths": [],
                        "nodes": [],
                    },
                )
                draft["datasets"].add(dataset.dataset_key)
                draft["node_count"] += 1
                draft["partition_count"] += node.partition_count
                draft["file_count"] += node.file_count
                draft["total_bytes"] += node.total_bytes
                draft["freqs"].update(node.freqs)
                draft["paths"].append(node.path)
                draft["nodes"].append(node)
        result = []
        for layer, draft in drafts.items():
            layer_definition = get_layer_definition(layer)
            result.append(
                LakeOverviewLayerGroup(
                    layer=layer,
                    layer_name=layer_definition.layer_name,
                    dataset_count=len(draft["datasets"]),
                    node_count=draft["node_count"],
                    partition_count=draft["partition_count"],
                    file_count=draft["file_count"],
                    total_bytes=draft["total_bytes"],
                    coverage_label=_coverage_label(draft["nodes"]),
                    freqs=sorted(draft["freqs"]),
                    sample_path=draft["paths"][0] if draft["paths"] else None,
                    sort_order=layer_definition.layer_order,
                )
            )
        return sorted(result, key=lambda item: item.sort_order)

    @staticmethod
    def _overview_sync_groups() -> list[LakeOverviewSyncMethodGroup]:
        counts: dict[str, int] = {}
        for definition in list_dataset_definitions():
            counts[definition.source] = counts.get(definition.source, 0) + 1
        return [
            LakeOverviewSyncMethodGroup(key=key, label=_source_label(key), count=count, sort_order=index * 10)
            for index, (key, count) in enumerate(sorted(counts.items()), start=1)
        ]

    @staticmethod
    def _dataset_risks(node_risks: list[LakeRiskItem]) -> list[LakeRiskItem]:
        if not node_risks:
            return []
        return [LakeRiskItem(severity="warning", code="node_risks", message="部分内容节点或分区存在风险，请查看详情。")]


def _require_dataset(dataset_key: str) -> LakeDatasetDefinition:
    for definition in list_dataset_definitions():
        if definition.dataset_key == dataset_key:
            return definition
    raise ValueError(f"Unknown Lake dataset: {dataset_key}")


def _path_stats(path: Path) -> dict[str, Any]:
    file_count = 0
    dir_count = 0
    total_bytes = 0
    latest_mtime: float | None = None
    paths = [path] if path.is_file() else path.rglob("*")
    for item in paths:
        if item.is_dir():
            dir_count += 1
            continue
        if not item.is_file():
            continue
        stat = item.stat()
        file_count += 1
        total_bytes += stat.st_size
        latest_mtime = stat.st_mtime if latest_mtime is None else max(latest_mtime, stat.st_mtime)
    return {
        "file_count": file_count,
        "dir_count": dir_count,
        "total_bytes": total_bytes,
        "latest_modified_at": datetime.fromtimestamp(latest_mtime, tz=timezone.utc) if latest_mtime is not None else None,
    }


def _partition_locator(values: dict[str, Any]) -> str:
    if not values:
        return "current"
    return "/".join(f"{key}={values[key]}" for key in values)


def _partition_label(values: dict[str, Any]) -> str:
    if not values:
        return "当前版本"
    parts = []
    if "indicator" in values:
        parts.append(str(values["indicator"]))
    if "params_key" in values:
        parts.append(str(values["params_key"]))
    if "freq" in values:
        parts.append(f"{values['freq']}min")
    if "trade_date" in values:
        parts.append(str(values["trade_date"]))
    if "event_date" in values:
        parts.append(str(values["event_date"]))
    if "trade_month" in values:
        parts.append(str(values["trade_month"]))
    if "bucket" in values:
        parts.append(f"bucket {values['bucket']}")
    return " · ".join(parts)


def _partition_coverage_label(partitions: list[LakePartitionSummary]) -> str:
    dates = [_partition_str(item, "trade_date") for item in partitions if _partition_str(item, "trade_date")]
    if dates:
        return _range_label(min(dates), max(dates))
    event_dates = [_partition_str(item, "event_date") for item in partitions if _partition_str(item, "event_date")]
    if event_dates:
        return _range_label(min(event_dates), max(event_dates))
    months = [_partition_str(item, "trade_month") for item in partitions if _partition_str(item, "trade_month")]
    if months:
        return _range_label(min(months), max(months))
    return "当前版本" if partitions else "-"


def _coverage_label(nodes: list[LakeNodeSummary]) -> str:
    dates = [value for node in nodes for value in (node.earliest_trade_date, node.latest_trade_date) if value]
    if dates:
        return _range_label(min(dates), max(dates))
    event_dates = [value for node in nodes for value in (node.earliest_event_date, node.latest_event_date) if value]
    if event_dates:
        return _range_label(min(event_dates), max(event_dates))
    months = [value for node in nodes for value in (node.earliest_trade_month, node.latest_trade_month) if value]
    if months:
        return _range_label(min(months), max(months))
    return "当前版本" if any(node.file_count for node in nodes) else "-"


def _range_label(start: str | None, end: str | None) -> str:
    if start and end and start != end:
        return f"{start} 至 {end}"
    return start or end or "-"


def _min_node_field(nodes: list[LakeNodeSummary], field: str) -> str | None:
    values = [getattr(node, field) for node in nodes if getattr(node, field)]
    return min(values) if values else None


def _max_node_field(nodes: list[LakeNodeSummary], field: str) -> str | None:
    values = [getattr(node, field) for node in nodes if getattr(node, field)]
    return max(values) if values else None


def _partition_str(partition: LakePartitionSummary, key: str) -> str | None:
    value = partition.partition_values.get(key)
    return value if isinstance(value, str) else None


def _partition_int(partition: LakePartitionSummary, key: str) -> int | None:
    value = partition.partition_values.get(key)
    return value if isinstance(value, int) else None


def _registered_container_paths(registered_nodes: dict[str, tuple[str, str]]) -> dict[str, set[str]]:
    containers: dict[str, set[str]] = {}
    for node_path, (dataset_key, _node_key) in registered_nodes.items():
        for parent in Path(node_path).parents:
            relative = parent.as_posix()
            if relative == "." or "/" not in relative:
                continue
            containers.setdefault(relative, set()).add(dataset_key)
    return containers


def _physical_asset_state(relative: str, *, is_registered_node: bool, is_registered_container: bool) -> str:
    if is_registered_node:
        return "registered"
    if _is_ignored_system_path(relative):
        return "ignored"
    if is_registered_container:
        return "registered_container"
    if relative.startswith("_") or relative.startswith("manifest/"):
        return "governance"
    return "unregistered"


def _physical_asset_risk(registered_state: str) -> tuple[str, str]:
    return {
        "registered": ("none", "正常"),
        "registered_container": ("none", "已登记节点容器"),
        "governance": ("none", "治理资产"),
        "ignored": ("none", "系统文件"),
        "unregistered": ("warning", "未登记资产"),
    }.get(registered_state, ("none", registered_state))


def _physical_asset_sort_key(item: LakePhysicalAssetSummary) -> tuple[int, str]:
    order = {
        "registered": 10,
        "registered_container": 20,
        "governance": 30,
        "unregistered": 40,
        "ignored": 90,
    }
    return (order.get(item.registered_state, 80), item.path)


def _is_ignored_system_path(relative: str) -> bool:
    return Path(relative).name in IGNORED_SYSTEM_FILE_NAMES


def _single_or_none(values: set[str]) -> str | None:
    if len(values) != 1:
        return None
    return next(iter(values))


def _physical_asset_name(path: str, *, registered_state: str, dataset_key: str | None, node_key: str | None) -> str:
    if dataset_key and node_key:
        return f"{dataset_key} / {node_key}"
    if registered_state == "registered_container" and dataset_key:
        return f"{dataset_key} / 节点容器"
    return path.rstrip("/").split("/")[-1] or path


def _source_label(source: str) -> str:
    return {"tushare": "Tushare", "prod-raw-db": "生产 raw 只读导出", "prod-core-db": "生产 core 只读导出"}.get(source, source)


def _dataset_role_label(role: str) -> str:
    return {"raw_dataset": "原始数据集", "derived_dataset": "派生数据集"}.get(role, role)


def _asset_role_label(role: str) -> str:
    return {
        "source_raw": "原始来源",
        "clean_baseline": "清洗基准",
        "local_derived": "本地派生",
        "query_projection": "查询投影",
        "governance_manifest": "治理清单",
    }.get(role, role)


def _health_label(status: str) -> str:
    return {"ok": "正常", "warning": "有风险", "error": "异常", "empty": "未落盘"}.get(status, status)


def _format_count(value: int) -> str:
    return f"{value:,}"


def _format_bytes(value: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    amount = float(value)
    for unit in units:
        if amount < 1024 or unit == units[-1]:
            return f"{amount:.1f} {unit}" if unit != "B" else f"{int(amount)} B"
        amount /= 1024
    return f"{value} B"


def _relative_path(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _parse_int_partition(name: str, key: str) -> int | None:
    value = _parse_str_partition(name, key)
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _parse_freq_partition(name: str) -> int | None:
    value = _parse_str_partition(name, "freq")
    if value is None:
        return None
    if value.endswith("min"):
        value = value.removesuffix("min")
    try:
        return int(value)
    except ValueError:
        return None


def _parse_str_partition(name: str, key: str) -> str | None:
    prefix = f"{key}="
    if not name.startswith(prefix):
        return None
    return name[len(prefix) :]
