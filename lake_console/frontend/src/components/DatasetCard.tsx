import { HealthBadge } from "./HealthBadge";
import type { DatasetSummary } from "../types";
import { formatBytes, formatDateOrMonthRange } from "../utils/format";

type DatasetCardProps = {
  dataset: DatasetSummary;
  onOpenDetail: () => void;
};

export function DatasetCard({ dataset, onOpenDetail }: DatasetCardProps) {
  return (
    <article className="dataset-card">
      <div className="dataset-card-top">
        <div>
          <span className="dataset-source">{dataset.source}</span>
          <strong>{dataset.display_name}</strong>
        </div>
        <HealthBadge status={dataset.health_status} />
      </div>
      <code>{dataset.dataset_key}</code>
      <p>{dataset.description ?? "本地数据湖数据集"}</p>
      <div className="dataset-primary-fact">
        <span>覆盖范围</span>
        <strong>{formatDateOrMonthRange(dataset)}</strong>
      </div>
      <dl className="dataset-facts">
        <DatasetFact label="文件" value={String(dataset.file_count)} />
        <DatasetFact label="大小" value={formatBytes(dataset.total_bytes)} />
        <DatasetFact label="层级" value={String(dataset.layers.length)} />
        <DatasetFact label="分区" value={String(dataset.partition_count)} />
      </dl>
      <div className="dataset-card-actions">
        <button onClick={onOpenDetail} type="button">
          查看详情
        </button>
      </div>
    </article>
  );
}

function DatasetFact({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}
