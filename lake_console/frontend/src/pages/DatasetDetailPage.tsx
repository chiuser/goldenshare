import { EmptyState } from "../components/EmptyState";
import { HealthBadge } from "../components/HealthBadge";
import { Metric } from "../components/Metric";
import { PageHeader } from "../components/PageHeader";
import { SectionCard } from "../components/SectionCard";
import type { DatasetSummary, LayerSummary, PartitionSummary } from "../types";
import { formatBytes, formatDateOrMonthRange, formatDateTime, formatLayerDateOrMonthRange, formatRowCount } from "../utils/format";

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

function DetailItem({ label, value, wide = false }: { label: string; value: string; wide?: boolean }) {
  return (
    <div className={wide ? "detail-item wide" : "detail-item"}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function LayerRow({ layer }: { layer: LayerSummary }) {
  return (
    <article className="layer-row">
      <div className="layer-row-header">
        <div className="layer-mark" aria-hidden="true">
          {layerInitial(layer)}
        </div>
        <div>
          <strong>{layerDisplayName(layer)}</strong>
          <span>{layer.layer} · {layer.layout}</span>
        </div>
      </div>
      <div className="layer-row-body">
        <div>
          <p>{humanizeLayerPurpose(layer)}</p>
          <p>{humanizeLayerUsage(layer)}</p>
        </div>
        <code>{layer.path}</code>
      </div>
      <dl className="layer-stats">
        <LayerStat label="分区" value={String(layer.partition_count)} />
        <LayerStat label="文件" value={String(layer.file_count)} />
        <LayerStat label="大小" value={formatBytes(layer.total_bytes)} />
        {layer.row_count !== null ? <LayerStat label="行数" value={formatRowCount(layer.row_count)} /> : null}
        <LayerStat label="日期/月" value={formatLayerDateOrMonthRange(layer)} />
        <LayerStat label="最近更新" value={formatDateTime(layer.latest_modified_at)} />
      </dl>
    </article>
  );
}

function LayerStat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}

function latestPartitionLabel(dataset: DatasetSummary): string {
  return dataset.latest_trade_date ?? dataset.latest_trade_month ?? "-";
}

function earliestPartitionLabel(dataset: DatasetSummary): string {
  return dataset.earliest_trade_date ?? dataset.earliest_trade_month ?? "-";
}

function layerDisplayName(layer: LayerSummary): string {
  const labels: Record<string, string> = {
    raw_tushare: "原始数据",
    manifest: "同步用清单",
    derived: "本地计算结果",
    research: "查询优化数据",
  };
  return labels[layer.layer] ?? layer.layer_name;
}

function layerInitial(layer: LayerSummary): string {
  const labels: Record<string, string> = {
    raw_tushare: "R",
    manifest: "M",
    derived: "D",
    research: "Q",
  };
  return labels[layer.layer] ?? layer.layer.slice(0, 1).toUpperCase();
}

function humanizeLayerPurpose(layer: LayerSummary): string {
  const descriptions: Record<string, string> = {
    raw_tushare: "从 Tushare 拉取后直接保存的数据。",
    manifest: "给同步任务使用的本地清单，例如股票池、指数池或交易日历。",
    derived: "由本地已有数据计算出来的结果。",
    research: "为了让本地研究和回测查询更快而重新整理的数据。",
  };
  return descriptions[layer.layer] ?? cleanTechnicalCopy(layer.purpose);
}

function humanizeLayerUsage(layer: LayerSummary): string {
  if (layer.layer === "raw_tushare") {
    return "适合查看原始落盘范围，也可以作为后续计算的数据来源。";
  }
  if (layer.layer === "manifest") {
    return "适合确认同步任务会使用哪些标的、日期或基础清单。";
  }
  if (layer.layer === "derived") {
    return "适合查看本地派生周期或计算结果是否已经生成。";
  }
  if (layer.layer === "research") {
    return "适合单标的长周期查询、回测和相似性分析。";
  }
  return cleanTechnicalCopy(layer.recommended_usage);
}

function cleanTechnicalCopy(value: string): string {
  return value
    .replaceAll("源站事实层", "原始数据")
    .replaceAll("源站事实", "原始数据")
    .replaceAll("执行辅助清单层", "同步用清单")
    .replaceAll("本地派生层", "本地计算结果")
    .replaceAll("研究查询优化层", "查询优化数据")
    .replaceAll("原始落盘层", "直接保存的数据");
}
