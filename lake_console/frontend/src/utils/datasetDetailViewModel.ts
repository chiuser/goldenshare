import type { DatasetSummary, NodeSummary, PartitionSummary } from "../types";
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
  partitionCount: number;
  riskTotal: number;
  selectedNodeLabel: string;
};

export function buildDatasetDetailViewModel(
  dataset: DatasetSummary,
  selectedNode: NodeSummary | null,
  partitions: PartitionSummary[],
): DatasetDetailViewModel {
  const latestFile = partitions[0] ?? null;
  const nodeRisks = dataset.node_summaries.flatMap((node) => node.risks);
  const riskTotal = dataset.risks.length + nodeRisks.length;
  const overviewMetrics = buildOverviewMetrics(dataset, riskTotal);
  const partitionTarget = selectedNode ?? dataset;
  const selectedNodeLabel = selectedNode ? `${selectedNode.node_name} / ${selectedNode.node_key}` : "-";

  return {
    averageFileSize: partitionTarget.file_count ? formatBytes(Math.round(partitionTarget.total_bytes / partitionTarget.file_count)) : "-",
    earliestPartition: earliestPartitionLabel(partitionTarget),
    latestFilePath: latestFile?.path ?? selectedNode?.path ?? "暂无文件",
    latestPartition: latestFile?.partition_label ?? latestPartitionLabel(partitionTarget),
    overviewMetrics,
    partitionCount: partitionTarget.partition_count,
    riskTotal,
    selectedNodeLabel,
  };
}

function buildOverviewMetrics(dataset: DatasetSummary, riskTotal: number): DatasetDetailMetricView[] {
  const metrics: Array<DatasetDetailMetricView | null> = [
    { key: "files", label: "文件数", value: String(dataset.file_count), hint: "全部内容节点合计" },
    { key: "bytes", label: "总大小", value: formatBytes(dataset.total_bytes), hint: "按本地文件大小汇总" },
    { key: "nodes", label: "节点数", value: String(dataset.node_summaries.length), hint: dataset.node_summaries.map((node) => node.node_key).join(", ") || "-" },
    { key: "partitions", label: "分区数", value: String(dataset.partition_count), hint: "全部内容节点合计" },
    dataset.row_count !== null
      ? { key: "rows", label: "行数", value: formatRowCount(dataset.row_count), hint: "来自 Parquet metadata 或显式统计" }
      : null,
    { key: "range", label: "日期范围", value: dataset.coverage_label || formatDateOrMonthRange(dataset), hint: "后端覆盖范围字段" },
    { key: "updated", label: "最近更新", value: formatDateTime(dataset.latest_modified_at), hint: "本地文件修改时间" },
    { key: "risks", label: "风险", value: riskTotal ? String(riskTotal) : "无", hint: "数据集与内容节点风险合计" },
  ];
  return metrics.filter((metric): metric is DatasetDetailMetricView => metric !== null);
}

function latestPartitionLabel(summary: DatasetSummary | NodeSummary): string {
  return summary.latest_trade_date ?? summary.latest_trade_month ?? "-";
}

function earliestPartitionLabel(summary: DatasetSummary | NodeSummary): string {
  return summary.earliest_trade_date ?? summary.earliest_trade_month ?? "-";
}
