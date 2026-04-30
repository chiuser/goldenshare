from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from lake_console.backend.app.schemas import LakeDatasetSummary, LakePartitionSummary, LakeRiskItem


class FilesystemScanner:
    def __init__(self, lake_root: Path) -> None:
        self.lake_root = lake_root

    def list_datasets(self, *, dataset_key: str | None = None, layer: str | None = None) -> list[LakeDatasetSummary]:
        result: list[LakeDatasetSummary] = []
        if dataset_key in {None, "stock_basic"} and layer in {None, "raw_tushare"}:
            stock_basic = self._stock_basic_summary()
            if stock_basic is not None:
                result.append(stock_basic)
        if dataset_key in {None, "trade_cal"} and layer in {None, "raw_tushare"}:
            trade_cal = self._trade_cal_summary()
            if trade_cal is not None:
                result.append(trade_cal)
        if dataset_key not in {None, "stk_mins"}:
            return result
        partitions = self.list_partitions(dataset_key="stk_mins", layer=layer)
        if not partitions:
            return result
        freqs = sorted({partition.freq for partition in partitions if partition.freq is not None})
        layers = sorted({partition.layer for partition in partitions})
        dates = [partition.trade_date for partition in partitions if partition.trade_date]
        modified = [partition.modified_at for partition in partitions if partition.modified_at]
        result.append(
            LakeDatasetSummary(
                dataset_key="stk_mins",
                display_name="股票历史分钟行情",
                layers=layers,
                freqs=freqs,
                partition_count=len(partitions),
                file_count=sum(partition.file_count for partition in partitions),
                total_bytes=sum(partition.total_bytes for partition in partitions),
                earliest_trade_date=min(dates) if dates else None,
                latest_trade_date=max(dates) if dates else None,
                latest_modified_at=max(modified) if modified else None,
                risks=self._dataset_risks(partitions),
            )
        )
        return result

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
        if dataset_key not in {None, "stk_mins"}:
            return []
        candidates: list[LakePartitionSummary] = []
        candidates.extend(self._scan_by_date("raw_tushare", self.lake_root / "raw_tushare" / "stk_mins_by_date"))
        candidates.extend(self._scan_by_date("derived", self.lake_root / "derived" / "stk_mins_by_date"))
        candidates.extend(self._scan_research(self.lake_root / "research" / "stk_mins_by_symbol_month"))
        result = []
        for item in candidates:
            if layer and item.layer != layer:
                continue
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
        return sorted(result, key=lambda item: (item.layer, item.layout, item.freq or 0, item.trade_date or item.trade_month or "", item.bucket or -1))

    def _scan_by_date(self, layer: str, root: Path) -> list[LakePartitionSummary]:
        if not root.exists():
            return []
        result: list[LakePartitionSummary] = []
        for freq_dir in root.glob("freq=*"):
            freq = _parse_int_partition(freq_dir.name, "freq")
            if freq is None:
                continue
            for date_dir in freq_dir.glob("trade_date=*"):
                trade_date = _parse_str_partition(date_dir.name, "trade_date")
                files = list(date_dir.glob("*.parquet"))
                result.append(self._partition_summary(layer=layer, layout="by_date", freq=freq, trade_date=trade_date, path=date_dir, files=files))
        return result

    def _scan_research(self, root: Path) -> list[LakePartitionSummary]:
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
                            layer="research",
                            layout="by_symbol_month",
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
        layer: str,
        layout: str,
        freq: int | None,
        path: Path,
        files: list[Path],
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
            dataset_key="stk_mins",
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
    def _dataset_risks(partitions: list[LakePartitionSummary]) -> list[LakeRiskItem]:
        risks: list[LakeRiskItem] = []
        if any(partition.risks for partition in partitions):
            risks.append(LakeRiskItem(severity="warning", code="partition_risks", message="部分分区存在风险，请查看分区详情。"))
        return risks

    def _stock_basic_summary(self) -> LakeDatasetSummary | None:
        file = self.lake_root / "raw_tushare" / "stock_basic" / "current" / "part-000.parquet"
        if not file.exists():
            return None
        risks: list[LakeRiskItem] = []
        if file.stat().st_size == 0:
            risks.append(LakeRiskItem(severity="warning", code="empty_file", message="stock_basic 正式 Parquet 文件为空。", path=str(file)))
        modified_at = datetime.fromtimestamp(file.stat().st_mtime, tz=timezone.utc)
        return LakeDatasetSummary(
            dataset_key="stock_basic",
            display_name="股票基础信息",
            layers=["raw_tushare"],
            freqs=[],
            partition_count=1,
            file_count=1,
            total_bytes=file.stat().st_size,
            earliest_trade_date=None,
            latest_trade_date=None,
            latest_modified_at=modified_at,
            risks=risks,
        )

    def _trade_cal_summary(self) -> LakeDatasetSummary | None:
        file = self.lake_root / "raw_tushare" / "trade_cal" / "current" / "part-000.parquet"
        if not file.exists():
            return None
        risks: list[LakeRiskItem] = []
        if file.stat().st_size == 0:
            risks.append(LakeRiskItem(severity="warning", code="empty_file", message="trade_cal 正式 Parquet 文件为空。", path=str(file)))
        modified_at = datetime.fromtimestamp(file.stat().st_mtime, tz=timezone.utc)
        return LakeDatasetSummary(
            dataset_key="trade_cal",
            display_name="交易日历",
            layers=["raw_tushare"],
            freqs=[],
            partition_count=1,
            file_count=1,
            total_bytes=file.stat().st_size,
            earliest_trade_date=None,
            latest_trade_date=None,
            latest_modified_at=modified_at,
            risks=risks,
        )


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
