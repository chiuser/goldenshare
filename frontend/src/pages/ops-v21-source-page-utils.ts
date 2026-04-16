import type { DatasetPipelineModeListResponse } from "../shared/api/types";

export type SourceKey = "tushare" | "biying";
export type PipelineModeItem = DatasetPipelineModeListResponse["items"][number];

export function canonicalDatasetKey(datasetKey: string): string {
  const lower = datasetKey.toLowerCase();
  if (lower.startsWith("biying_")) return datasetKey.slice("biying_".length);
  if (lower.startsWith("tushare_")) return datasetKey.slice("tushare_".length);
  return datasetKey;
}

function sourcePreference(item: PipelineModeItem, sourceKey: SourceKey): number {
  const datasetKey = item.dataset_key.toLowerCase();
  const rawTable = (item.raw_table || "").toLowerCase();
  const sourceScope = (item.source_scope || "").toLowerCase();

  if (sourceKey === "biying") {
    if (datasetKey.startsWith("biying_")) return 300;
    if (rawTable.startsWith("raw_biying.")) return 200;
    if (sourceScope.includes("biying")) return 100;
    return 0;
  }

  if (datasetKey.startsWith("biying_")) return 0;
  if (rawTable.startsWith("raw_tushare.") && !datasetKey.startsWith("tushare_")) return 300;
  if (datasetKey.startsWith("tushare_")) return 200;
  if (sourceScope.includes("tushare")) return 100;
  return 50;
}

export function dedupeModeItemsForSource(items: PipelineModeItem[], sourceKey: SourceKey): PipelineModeItem[] {
  const deduped = new Map<string, PipelineModeItem>();
  for (const item of items) {
    const key = canonicalDatasetKey(item.dataset_key);
    const existing = deduped.get(key);
    if (!existing) {
      deduped.set(key, item);
      continue;
    }
    const currentScore = sourcePreference(item, sourceKey);
    const existingScore = sourcePreference(existing, sourceKey);
    if (currentScore > existingScore) {
      deduped.set(key, item);
      continue;
    }
    if (currentScore === existingScore && item.dataset_key.localeCompare(existing.dataset_key, "zh-CN") < 0) {
      deduped.set(key, item);
    }
  }
  return Array.from(deduped.values());
}

