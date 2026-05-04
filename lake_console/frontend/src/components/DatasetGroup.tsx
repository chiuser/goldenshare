import { DatasetCard } from "./DatasetCard";
import type { DatasetGroupView } from "../utils/datasetGrouping";

type DatasetGroupProps = {
  group: DatasetGroupView;
  onOpenDetail: (datasetKey: string) => void;
};

export function DatasetGroup({ group, onOpenDetail }: DatasetGroupProps) {
  return (
    <section className="dataset-group">
      <div className="dataset-group-header">
        <div>
          <strong>{group.groupLabel}</strong>
        </div>
        <em>{group.items.length} 个数据集</em>
      </div>
      <div className="dataset-list">
        {group.items.map((dataset) => (
          <DatasetCard dataset={dataset} key={dataset.dataset_key} onOpenDetail={() => onOpenDetail(dataset.dataset_key)} />
        ))}
      </div>
    </section>
  );
}
