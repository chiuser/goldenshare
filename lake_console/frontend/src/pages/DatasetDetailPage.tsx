import { DataTableCard, type DataTableColumn } from "../components/DataTableCard";
import { DatasetDetailHeader } from "../components/DatasetDetailHeader";
import { DatasetDetailMetaPanel } from "../components/DatasetDetailMetaPanel";
import { EmptyState } from "../components/EmptyState";
import { Metric } from "../components/Metric";
import { NodeRow } from "../components/NodeRow";
import { SectionCard } from "../components/SectionCard";
import type { DatasetSummary, PartitionSummary } from "../types";
import { buildDatasetDetailViewModel } from "../utils/datasetDetailViewModel";
import { formatBytes, formatDateTime, formatRowCount } from "../utils/format";

type DatasetDetailPageProps = {
  dataset: DatasetSummary;
  partitions: PartitionSummary[];
  selectedNodeKey: string;
  onBack: () => void;
  onSelectNode: (nodeKey: string) => void;
};

export function DatasetDetailPage({ dataset, partitions, selectedNodeKey, onBack, onSelectNode }: DatasetDetailPageProps) {
  const selectedNode = dataset.node_summaries.find((node) => node.node_key === selectedNodeKey) ?? dataset.node_summaries[0] ?? null;
  const detailView = buildDatasetDetailViewModel(dataset, selectedNode, partitions);
  const partitionColumns: DataTableColumn<PartitionSummary>[] = [
    {
      key: "partition",
      header: "分区",
      render: (row) => (
        <div className="detail-partition-cell">
          <strong>{row.partition_label}</strong>
          <span>{row.partition_locator}</span>
        </div>
      ),
    },
    {
      key: "path",
      header: "路径",
      className: "detail-partition-path-col",
      render: (row) => <code>{row.path}</code>,
    },
    {
      key: "scale",
      header: "规模",
      className: "detail-partition-size-col",
      render: (row) => (
        <div className="detail-partition-cell detail-partition-number">
          <strong>{formatBytes(row.total_bytes)}</strong>
          <span>
            {row.file_count.toLocaleString("zh-CN")} 文件 / {formatRowCount(row.row_count)}
          </span>
        </div>
      ),
    },
    {
      key: "modified",
      header: "最近更新",
      render: (row) => formatDateTime(row.modified_at),
    },
  ];

  return (
    <div className="detail-page">
      <DatasetDetailHeader dataset={dataset} onBack={onBack} />

      <section className="detail-summary-rail" aria-label="数据集核心概览">
        <div className="metric-grid detail-metrics">
          {detailView.overviewMetrics.map((metric) => (
            <Metric label={metric.label} value={metric.value} hint={metric.hint} key={metric.key} />
          ))}
        </div>
      </section>

      <div className="detail-content-stack">
        <DatasetDetailMetaPanel dataset={dataset} detailView={detailView} />

        <SectionCard
          className="detail-layer-section"
          title="内容节点"
          side={dataset.node_summaries.length ? (
            <select
              aria-label="选择内容节点"
              className="detail-node-select"
              onChange={(event) => onSelectNode(event.target.value)}
              value={selectedNode?.node_key ?? ""}
            >
              {dataset.node_summaries.map((node) => (
                <option key={node.node_key} value={node.node_key}>
                  {node.node_name}
                </option>
              ))}
            </select>
          ) : null}
        >
          {dataset.node_summaries.length ? (
            <div className="layer-stack">
              {dataset.node_summaries.map((node) => (
                <NodeRow node={node} key={`${dataset.dataset_key}-${node.node_key}`} />
              ))}
            </div>
          ) : (
            <EmptyState title="暂无内容节点文件" description="当前数据集还没有扫描到已登记内容节点文件。" />
          )}
        </SectionCard>

        <SectionCard
          className="detail-partition-section"
          description={selectedNode ? `${selectedNode.node_name} / ${selectedNode.node_key}` : "请先选择内容节点。"}
          side={<span>样本 {partitions.length.toLocaleString("zh-CN")} 项</span>}
          title="当前节点分区样本"
        >
          {selectedNode ? (
            <DataTableCard
              columns={partitionColumns}
              empty={<EmptyState title="暂无分区文件" description="当前内容节点未扫描到分区文件。" />}
              getRowKey={(row) => row.partition_locator || row.path}
              label="当前内容节点分区样本"
              rows={partitions}
            />
          ) : (
            <EmptyState title="暂无内容节点" description="当前数据集没有可查看的内容节点。" />
          )}
        </SectionCard>
      </div>
    </div>
  );
}
