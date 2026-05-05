import { HealthBadge } from "./HealthBadge";
import { PageHeader } from "./PageHeader";
import type { DatasetSummary } from "../types";

type DatasetDetailHeaderProps = {
  dataset: DatasetSummary;
  onBack: () => void;
};

export function DatasetDetailHeader({ dataset, onBack }: DatasetDetailHeaderProps) {
  return (
    <div className="detail-hero">
      <div className="detail-toolbar">
        <button className="back-button" onClick={onBack} type="button">
          ← 返回数据集总览
        </button>
        <span className="detail-hero-context">本地文件事实 / {dataset.source}</span>
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
    </div>
  );
}
