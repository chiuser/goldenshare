import type { DatasetSummary } from "../types";

export type DatasetGroupView = {
  groupKey: string;
  groupLabel: string;
  groupOrder: number;
  items: DatasetSummary[];
};

export function groupDatasets(datasets: DatasetSummary[]): DatasetGroupView[] {
  const grouped = new Map<string, DatasetGroupView>();
  for (const dataset of datasets) {
    const groupKey = dataset.group_key ?? "unknown";
    const group = grouped.get(groupKey) ?? {
      groupKey,
      groupLabel: dataset.group_label ?? "未分组",
      groupOrder: dataset.group_order ?? 999,
      items: [],
    };
    group.items.push(dataset);
    grouped.set(groupKey, group);
  }
  return [...grouped.values()]
    .map((group) => ({ ...group, items: group.items.sort((a, b) => a.dataset_key.localeCompare(b.dataset_key)) }))
    .sort((a, b) => a.groupOrder - b.groupOrder || a.groupKey.localeCompare(b.groupKey));
}
