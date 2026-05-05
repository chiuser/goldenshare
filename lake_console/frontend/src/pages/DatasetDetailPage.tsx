import { DatasetDetailHeader } from "../components/DatasetDetailHeader";
import { DatasetDetailMetaPanel } from "../components/DatasetDetailMetaPanel";
import { EmptyState } from "../components/EmptyState";
import { LayerRow } from "../components/LayerRow";
import { Metric } from "../components/Metric";
import { SectionCard } from "../components/SectionCard";
import type { DatasetSummary, PartitionSummary } from "../types";
import { buildDatasetDetailViewModel } from "../utils/datasetDetailViewModel";

type DatasetDetailPageProps = {
  dataset: DatasetSummary;
  partitions: PartitionSummary[];
  onBack: () => void;
};

export function DatasetDetailPage({ dataset, partitions, onBack }: DatasetDetailPageProps) {
  const detailView = buildDatasetDetailViewModel(dataset, partitions);

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

        <SectionCard className="detail-layer-section" title="数据层级">
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
      </div>
    </div>
  );
}
