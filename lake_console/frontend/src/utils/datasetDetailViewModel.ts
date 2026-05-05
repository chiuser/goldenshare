import type { DatasetSummary, PartitionSummary } from "../types";
import { formatBytes, formatDateOrMonthRange, formatDateTime, formatRowCount } from "./format";

export type DatasetDetailMetricView = {
  key: string;
  label: string;
  value: string;
  hint: string;
};

export type DatasetDetailViewModel = {
  averageFileSize: string;
  earliestPartition: string;
  latestFilePath: string;
  latestPartition: string;
  overviewMetrics: DatasetDetailMetricView[];
  riskTotal: number;
};

export function buildDatasetDetailViewModel(dataset: DatasetSummary, partitions: PartitionSummary[]): DatasetDetailViewModel {
  const latestFile = partitions[0] ?? null;
  const layerRisks = dataset.layer_summaries.flatMap((layer) => layer.risks);
  const riskTotal = dataset.risks.length + layerRisks.length;
  const overviewMetrics = buildOverviewMetrics(dataset, riskTotal);

  return {
    averageFileSize: dataset.file_count ? formatBytes(Math.round(dataset.total_bytes / dataset.file_count)) : "-",
    earliestPartition: earliestPartitionLabel(dataset),
    latestFilePath: latestFile?.path ?? "暂无文件",
    latestPartition: latestPartitionLabel(dataset),
    overviewMetrics,
    riskTotal,
  };
}

function buildOverviewMetrics(dataset: DatasetSummary, riskTotal: number): DatasetDetailMetricView[] {
  const metrics: Array<DatasetDetailMetricView | null> = [
    { key: "files", label: "文件数", value: String(dataset.file_count), hint: "全部层级合计" },
    { key: "bytes", label: "总大小", value: formatBytes(dataset.total_bytes), hint: "按本地文件大小汇总" },
    { key: "layers", label: "层级数", value: String(dataset.layers.length), hint: dataset.layers.join(", ") || "-" },
    { key: "partitions", label: "分区数", value: String(dataset.partition_count), hint: "全部层级合计" },
    dataset.row_count !== null
      ? { key: "rows", label: "行数", value: formatRowCount(dataset.row_count), hint: "来自 Parquet metadata 或显式统计" }
      : null,
    { key: "range", label: "日期范围", value: formatDateOrMonthRange(dataset), hint: "按文件分区事实汇总" },
    { key: "updated", label: "最近更新", value: formatDateTime(dataset.latest_modified_at), hint: "本地文件修改时间" },
    { key: "risks", label: "风险", value: riskTotal ? String(riskTotal) : "无", hint: "数据集与层级风险合计" },
  ];
  return metrics.filter((metric): metric is DatasetDetailMetricView => metric !== null);
}

function latestPartitionLabel(dataset: DatasetSummary): string {
  return dataset.latest_trade_date ?? dataset.latest_trade_month ?? "-";
}

function earliestPartitionLabel(dataset: DatasetSummary): string {
  return dataset.earliest_trade_date ?? dataset.earliest_trade_month ?? "-";
}
