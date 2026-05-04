import { DetailItem } from "../components/DetailItem";
import { EmptyState } from "../components/EmptyState";
import { HealthBadge } from "../components/HealthBadge";
import { LayerRow } from "../components/LayerRow";
import { Metric } from "../components/Metric";
import { PageHeader } from "../components/PageHeader";
import { SectionCard } from "../components/SectionCard";
import type { DatasetSummary, PartitionSummary } from "../types";
import { formatBytes, formatDateOrMonthRange, formatDateTime, formatRowCount } from "../utils/format";

type DatasetDetailPageProps = {
  dataset: DatasetSummary;
  partitions: PartitionSummary[];
  onBack: () => void;
};

export function DatasetDetailPage({ dataset, partitions, onBack }: DatasetDetailPageProps) {
  const latestPartition = latestPartitionLabel(dataset);
  const earliestPartition = earliestPartitionLabel(dataset);
  const averageFileSize = dataset.file_count > 0 ? Math.round(dataset.total_bytes / dataset.file_count) : 0;
  const layerRisks = dataset.layer_summaries.flatMap((layer) => layer.risks);
  const riskTotal = dataset.risks.length + layerRisks.length;
  const latestFile = partitions[0] ?? null;
  const overviewMetrics = [
    <Metric label="文件数" value={String(dataset.file_count)} hint="全部层级合计" key="files" />,
    <Metric label="总大小" value={formatBytes(dataset.total_bytes)} hint="按本地文件大小汇总" key="bytes" />,
    <Metric label="层级数" value={String(dataset.layers.length)} hint={dataset.layers.join(", ") || "-"} key="layers" />,
    <Metric label="分区数" value={String(dataset.partition_count)} hint="全部层级合计" key="partitions" />,
    dataset.row_count !== null ? <Metric label="行数" value={formatRowCount(dataset.row_count)} hint="来自 Parquet metadata 或显式统计" key="rows" /> : null,
    <Metric label="日期范围" value={formatDateOrMonthRange(dataset)} hint="按文件分区事实汇总" key="range" />,
    <Metric label="最近更新" value={formatDateTime(dataset.latest_modified_at)} hint="本地文件修改时间" key="updated" />,
    <Metric label="风险" value={riskTotal ? String(riskTotal) : "无"} hint="数据集与层级风险合计" key="risks" />,
  ].filter(Boolean);

  return (
    <div className="detail-page">
      <div className="detail-toolbar">
        <button className="back-button" onClick={onBack} type="button">
          ← 返回数据集总览
        </button>
      </div>

      <PageHeader
        eyebrow="Dataset detail"
        title={dataset.display_name}
        description={dataset.description ?? "查看该数据集在本地数据湖中承载的层级、分区、文件路径和风险。"}
        right={(
          <div className="detail-header-side">
            <HealthBadge status={dataset.health_status} />
            <code>{dataset.dataset_key}</code>
          </div>
        )}
      />

      <SectionCard title="核心概览">
        <div className="metric-grid detail-metrics">
          {overviewMetrics}
        </div>
      </SectionCard>

      <SectionCard title="基础信息">
        <div className="detail-grid">
          <DetailItem label="数据源" value={dataset.source} />
          <DetailItem label="数据集 key" value={dataset.dataset_key} />
          <DetailItem label="分组" value={dataset.group_label ?? "-"} />
          <DetailItem label="角色" value={dataset.dataset_role} />
          <DetailItem label="存储根" value={dataset.storage_root ?? "-"} wide />
          <DetailItem label="主布局" value={dataset.primary_layout ?? "-"} />
          <DetailItem label="写入策略" value={dataset.write_policy ?? "-"} />
          <DetailItem label="更新方式" value={dataset.update_mode ?? "-"} />
          <DetailItem label="可用布局" value={dataset.available_layouts.join(", ") || "-"} wide />
          <DetailItem label="支持频度" value={dataset.supported_freqs.join(", ") || "-"} wide />
        </div>
      </SectionCard>

      <SectionCard title="数据层级">
        {dataset.layer_summaries.length ? (
          <div className="layer-stack">
            {dataset.layer_summaries.map((layer) => (
              <LayerRow layer={layer} key={`${dataset.dataset_key}-${layer.layer}-${layer.layout}`} />
            ))}
          </div>
        ) : (
          <EmptyState title="暂无层级文件" description="当前数据集还没有扫描到 raw、manifest、derived 或 research 文件。" />
        )}
      </SectionCard>

      <SectionCard title="分区概况">
        <div className="partition-summary-grid">
          <DetailItem label="最新分区" value={latestPartition} />
          <DetailItem label="最早分区" value={earliestPartition} />
          <DetailItem label="分区数量" value={String(dataset.partition_count)} />
          <DetailItem label="平均文件大小" value={dataset.file_count ? formatBytes(averageFileSize) : "-"} />
          <DetailItem label="最近文件样本" value={latestFile?.path ?? "暂无文件"} wide />
          <DetailItem label="风险提示" value={riskTotal ? `${riskTotal} 项风险` : "无"} wide />
        </div>
      </SectionCard>
    </div>
  );
}

function latestPartitionLabel(dataset: DatasetSummary): string {
  return dataset.latest_trade_date ?? dataset.latest_trade_month ?? "-";
}

function earliestPartitionLabel(dataset: DatasetSummary): string {
  return dataset.earliest_trade_date ?? dataset.earliest_trade_month ?? "-";
}
