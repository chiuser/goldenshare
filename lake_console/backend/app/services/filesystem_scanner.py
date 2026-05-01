from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from lake_console.backend.app.catalog.datasets import list_dataset_definitions
from lake_console.backend.app.catalog.models import LakeDatasetDefinition, LakeLayerDefinition
from lake_console.backend.app.catalog.view_groups import get_view_group
from lake_console.backend.app.schemas import LakeDatasetSummary, LakeLayerSummary, LakePartitionSummary, LakeRiskItem


class FilesystemScanner:
    def __init__(self, lake_root: Path) -> None:
        self.lake_root = lake_root

    def list_datasets(self, *, dataset_key: str | None = None, layer: str | None = None) -> list[LakeDatasetSummary]:
        result: list[LakeDatasetSummary] = []
        for definition in list_dataset_definitions():
            if dataset_key and definition.dataset_key != dataset_key:
                continue
            summary = self._dataset_summary(definition, layer=layer)
            if summary is not None:
                result.append(summary)
        return sorted(result, key=lambda item: (item.group_order or 999, item.dataset_key))

    def list_partitions(
        self,
        *,
        dataset_key: str | None = None,
        layer: str | None = None,
        layout: str | None = None,
        freq: int | None = None,
        trade_date_from: str | None = None,
        trade_date_to: str | None = None,
        trade_month: str | None = None,
        bucket: int | None = None,
    ) -> list[LakePartitionSummary]:
        candidates: list[LakePartitionSummary] = []
        for definition in list_dataset_definitions():
            if dataset_key and definition.dataset_key != dataset_key:
                continue
            for layer_definition in definition.layers:
                if layer and layer_definition.layer != layer:
                    continue
                candidates.extend(self._scan_partitions(definition, layer_definition))

        result = []
        for item in candidates:
            if layout and item.layout != layout:
                continue
            if freq is not None and item.freq != freq:
                continue
            if trade_date_from and item.trade_date and item.trade_date < trade_date_from:
                continue
            if trade_date_to and item.trade_date and item.trade_date > trade_date_to:
                continue
            if trade_month and item.trade_month != trade_month:
                continue
            if bucket is not None and item.bucket != bucket:
                continue
            result.append(item)
        return sorted(
            result,
            key=lambda item: (
                item.dataset_key,
                item.layer,
                item.layout,
                item.freq or 0,
                item.trade_date or item.trade_month or "",
                item.bucket or -1,
            ),
        )

    def _dataset_summary(self, definition: LakeDatasetDefinition, *, layer: str | None) -> LakeDatasetSummary | None:
        layer_definitions = [item for item in definition.layers if layer in {None, item.layer}]
        if not layer_definitions:
            return None

        layer_summaries = [self._layer_summary(definition, layer_definition) for layer_definition in layer_definitions]
        risks = [risk for layer_summary in layer_summaries for risk in layer_summary.risks]
        file_count = sum(layer_summary.file_count for layer_summary in layer_summaries)
        partition_count = sum(layer_summary.partition_count for layer_summary in layer_summaries)
        total_bytes = sum(layer_summary.total_bytes for layer_summary in layer_summaries)
        modified_values = [item.latest_modified_at for item in layer_summaries if item.latest_modified_at]
        trade_dates = [
            date
            for layer_summary in layer_summaries
            for date in (layer_summary.earliest_trade_date, layer_summary.latest_trade_date)
            if date
        ]
        trade_months = [
            month
            for layer_summary in layer_summaries
            for month in (layer_summary.earliest_trade_month, layer_summary.latest_trade_month)
            if month
        ]
        freqs = sorted({freq for layer_summary in layer_summaries for freq in layer_summary.freqs})
        group = get_view_group(definition.group_key)
        health_status = "empty"
        if file_count > 0:
            health_status = "warning" if risks else "ok"

        return LakeDatasetSummary(
            dataset_key=definition.dataset_key,
            display_name=definition.display_name,
            source=definition.source,
            category=group.group_label,
            group_key=group.group_key,
            group_label=group.group_label,
            group_order=group.group_order,
            description=definition.description,
            dataset_role=definition.dataset_role,
            storage_root=definition.storage_root,
            layers=[item.layer for item in layer_definitions],
            layer_summaries=layer_summaries,
            freqs=freqs,
            supported_freqs=list(definition.supported_freqs),
            raw_freqs=list(definition.raw_freqs),
            derived_freqs=list(definition.derived_freqs),
            partition_count=partition_count,
            file_count=file_count,
            total_bytes=total_bytes,
            earliest_trade_date=min(trade_dates) if trade_dates else None,
            latest_trade_date=max(trade_dates) if trade_dates else None,
            earliest_trade_month=min(trade_months) if trade_months else None,
            latest_trade_month=max(trade_months) if trade_months else None,
            latest_modified_at=max(modified_values) if modified_values else None,
            primary_layout=definition.primary_layout,
            available_layouts=list(definition.available_layouts),
            write_policy=definition.write_policy,
            update_mode=definition.update_mode,
            health_status=health_status,
            risks=self._dataset_risks(risks),
        )

    def _layer_summary(self, definition: LakeDatasetDefinition, layer_definition: LakeLayerDefinition) -> LakeLayerSummary:
        partitions = self._scan_partitions(definition, layer_definition)
        risks = [risk for partition in partitions for risk in partition.risks]
        modified_values = [item.modified_at for item in partitions if item.modified_at]
        trade_dates = [partition.trade_date for partition in partitions if partition.trade_date]
        trade_months = [partition.trade_month for partition in partitions if partition.trade_month]
        return LakeLayerSummary(
            layer=layer_definition.layer,
            layer_name=layer_definition.layer_name,
            purpose=layer_definition.purpose,
            layout=layer_definition.layout,
            path=layer_definition.path,
            partition_count=len(partitions),
            file_count=sum(partition.file_count for partition in partitions),
            total_bytes=sum(partition.total_bytes for partition in partitions),
            freqs=sorted({partition.freq for partition in partitions if partition.freq is not None}),
            earliest_trade_date=min(trade_dates) if trade_dates else None,
            latest_trade_date=max(trade_dates) if trade_dates else None,
            earliest_trade_month=min(trade_months) if trade_months else None,
            latest_trade_month=max(trade_months) if trade_months else None,
            latest_modified_at=max(modified_values) if modified_values else None,
            recommended_usage=layer_definition.recommended_usage,
            risks=risks,
        )

    def _scan_partitions(self, definition: LakeDatasetDefinition, layer_definition: LakeLayerDefinition) -> list[LakePartitionSummary]:
        root = self.lake_root / layer_definition.path
        if layer_definition.layout in {"current_file", "manifest_file"}:
            return self._scan_single_file(definition, layer_definition, root)
        if layer_definition.layout == "by_date":
            return self._scan_by_date(definition, layer_definition, root)
        if layer_definition.layout == "by_symbol_month":
            return self._scan_research(definition, layer_definition, root)
        return []

    def _scan_single_file(
        self,
        definition: LakeDatasetDefinition,
        layer_definition: LakeLayerDefinition,
        file_path: Path,
    ) -> list[LakePartitionSummary]:
        if not file_path.exists():
            return []
        return [
            self._partition_summary(
                dataset_key=definition.dataset_key,
                layer=layer_definition.layer,
                layout=layer_definition.layout,
                path=file_path,
                files=[file_path],
            )
        ]

    def _scan_by_date(
        self,
        definition: LakeDatasetDefinition,
        layer_definition: LakeLayerDefinition,
        root: Path,
    ) -> list[LakePartitionSummary]:
        if not root.exists():
            return []
        result: list[LakePartitionSummary] = []
        freq_dirs = list(root.glob("freq=*"))
        if freq_dirs:
            for freq_dir in freq_dirs:
                freq = _parse_int_partition(freq_dir.name, "freq")
                if freq is None:
                    continue
                result.extend(self._scan_trade_date_dirs(definition, layer_definition, freq_dir, freq=freq))
            return result
        return self._scan_trade_date_dirs(definition, layer_definition, root, freq=None)

    def _scan_trade_date_dirs(
        self,
        definition: LakeDatasetDefinition,
        layer_definition: LakeLayerDefinition,
        root: Path,
        *,
        freq: int | None,
    ) -> list[LakePartitionSummary]:
        result: list[LakePartitionSummary] = []
        for date_dir in root.glob("trade_date=*"):
            trade_date = _parse_str_partition(date_dir.name, "trade_date")
            files = list(date_dir.glob("*.parquet"))
            result.append(
                self._partition_summary(
                    dataset_key=definition.dataset_key,
                    layer=layer_definition.layer,
                    layout=layer_definition.layout,
                    freq=freq,
                    trade_date=trade_date,
                    path=date_dir,
                    files=files,
                )
            )
        return result

    def _scan_research(
        self,
        definition: LakeDatasetDefinition,
        layer_definition: LakeLayerDefinition,
        root: Path,
    ) -> list[LakePartitionSummary]:
        if not root.exists():
            return []
        result: list[LakePartitionSummary] = []
        for freq_dir in root.glob("freq=*"):
            freq = _parse_int_partition(freq_dir.name, "freq")
            if freq is None:
                continue
            for month_dir in freq_dir.glob("trade_month=*"):
                trade_month = _parse_str_partition(month_dir.name, "trade_month")
                for bucket_dir in month_dir.glob("bucket=*"):
                    bucket = _parse_int_partition(bucket_dir.name, "bucket")
                    files = list(bucket_dir.glob("*.parquet"))
                    result.append(
                        self._partition_summary(
                            dataset_key=definition.dataset_key,
                            layer=layer_definition.layer,
                            layout=layer_definition.layout,
                            freq=freq,
                            trade_month=trade_month,
                            bucket=bucket,
                            path=bucket_dir,
                            files=files,
                        )
                    )
        return result

    @staticmethod
    def _partition_summary(
        *,
        dataset_key: str,
        layer: str,
        layout: str,
        path: Path,
        files: list[Path],
        freq: int | None = None,
        trade_date: str | None = None,
        trade_month: str | None = None,
        bucket: int | None = None,
    ) -> LakePartitionSummary:
        total_bytes = sum(file.stat().st_size for file in files if file.exists())
        modified_timestamps = [file.stat().st_mtime for file in files if file.exists()]
        risks: list[LakeRiskItem] = []
        if any(file.stat().st_size == 0 for file in files if file.exists()):
            risks.append(LakeRiskItem(severity="warning", code="empty_file", message="分区中存在空 Parquet 文件。", path=str(path)))
        return LakePartitionSummary(
            dataset_key=dataset_key,
            layer=layer,
            layout=layout,
            freq=freq,
            trade_date=trade_date,
            trade_month=trade_month,
            bucket=bucket,
            path=str(path),
            file_count=len(files),
            total_bytes=total_bytes,
            modified_at=datetime.fromtimestamp(max(modified_timestamps), tz=timezone.utc) if modified_timestamps else None,
            risks=risks,
        )

    @staticmethod
    def _dataset_risks(layer_risks: list[LakeRiskItem]) -> list[LakeRiskItem]:
        if not layer_risks:
            return []
        return [LakeRiskItem(severity="warning", code="layer_risks", message="部分层级或分区存在风险，请查看详情。")]


def _parse_int_partition(name: str, key: str) -> int | None:
    value = _parse_str_partition(name, key)
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _parse_str_partition(name: str, key: str) -> str | None:
    prefix = f"{key}="
    if not name.startswith(prefix):
        return None
    return name[len(prefix) :]
