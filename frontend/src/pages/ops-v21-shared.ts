import type { LayerSnapshotLatestResponse, OpsFreshnessResponse } from "../shared/api/types";

export type LayerSnapshotItem = LayerSnapshotLatestResponse["items"][number];

export interface DatasetStageSummary {
  datasetKey: string;
  displayName: string;
  sourceKeys: string[];
  status: "healthy" | "warning" | "failed" | "unknown";
  stageMap: Partial<Record<"raw" | "std" | "resolution" | "serving", LayerSnapshotItem>>;
  lastCalculatedAt: string | null;
}

const statusRank: Record<string, number> = {
  failed: 4,
  stale: 3,
  lagging: 2,
  healthy: 1,
  fresh: 1,
  success: 1,
};

function normalizeStatus(status: string | null | undefined): "healthy" | "warning" | "failed" | "unknown" {
  const key = (status || "").toLowerCase();
  if (key === "failed") return "failed";
  if (key === "stale" || key === "lagging") return "warning";
  if (key === "healthy" || key === "fresh" || key === "success") return "healthy";
  return "unknown";
}

function pickWorse(a: "healthy" | "warning" | "failed" | "unknown", b: "healthy" | "warning" | "failed" | "unknown") {
  const order = { unknown: 0, healthy: 1, warning: 2, failed: 3 } as const;
  return order[a] >= order[b] ? a : b;
}

export function buildFreshnessDisplayNameMap(freshness?: OpsFreshnessResponse): Record<string, string> {
  const map: Record<string, string> = {};
  for (const group of freshness?.groups || []) {
    for (const item of group.items || []) {
      map[item.dataset_key] = item.display_name;
    }
  }
  return map;
}

function inferSourceFromTargetTable(
  targetTable: string | null | undefined,
  datasetKey: string,
): "tushare" | "biying" {
  if (datasetKey.startsWith("biying_")) return "biying";
  const table = (targetTable || "").toLowerCase();
  if (table.startsWith("raw_biying.")) return "biying";
  return "tushare";
}

function toSyntheticSnapshotFromFreshness(
  item: OpsFreshnessResponse["groups"][number]["items"][number],
  stage: "raw" | "serving",
): LayerSnapshotItem {
  const status =
    item.freshness_status === "stale"
      ? "failed"
      : item.freshness_status === "lagging"
        ? "warning"
        : item.freshness_status === "fresh"
          ? "healthy"
          : "unknown";
  const ts = item.last_sync_date || item.recent_failure_at || item.expected_business_date || "1970-01-01T00:00:00Z";
  return {
    snapshot_date: (item.state_business_date || item.latest_business_date || item.last_sync_date || "1970-01-01").slice(0, 10),
    dataset_key: item.dataset_key,
    source_key: inferSourceFromTargetTable(item.target_table, item.dataset_key),
    stage,
    status,
    rows_in: null,
    rows_out: null,
    error_count: item.recent_failure_at ? 1 : 0,
    lag_seconds: item.lag_days != null ? item.lag_days * 86400 : null,
    message: item.freshness_note || item.recent_failure_summary || null,
    calculated_at: ts,
    last_success_at: item.last_sync_date || null,
    last_failure_at: item.recent_failure_at || null,
  };
}

export function groupDatasetSummaries(
  items: LayerSnapshotLatestResponse["items"],
  displayNameMap: Record<string, string>,
): DatasetStageSummary[] {
  const grouped = new Map<string, DatasetStageSummary>();
  for (const item of items) {
    const key = item.dataset_key;
    const current = grouped.get(key) || {
      datasetKey: key,
      displayName: displayNameMap[key] || key,
      sourceKeys: [],
      status: "unknown" as const,
      stageMap: {},
      lastCalculatedAt: null,
    };
    const stageKey = item.stage as "raw" | "std" | "resolution" | "serving";
    if (stageKey === "raw" || stageKey === "std" || stageKey === "resolution" || stageKey === "serving") {
      current.stageMap[stageKey] = item;
    }
    if (item.source_key && !current.sourceKeys.includes(item.source_key)) {
      current.sourceKeys.push(item.source_key);
    }
    current.status = pickWorse(current.status, normalizeStatus(item.status));
    if (!current.lastCalculatedAt || new Date(item.calculated_at).getTime() > new Date(current.lastCalculatedAt).getTime()) {
      current.lastCalculatedAt = item.calculated_at;
    }
    grouped.set(key, current);
  }
  return Array.from(grouped.values()).sort((a, b) => {
    const aScore = statusRank[a.status] || 0;
    const bScore = statusRank[b.status] || 0;
    if (aScore !== bScore) return bScore - aScore;
    return a.datasetKey.localeCompare(b.datasetKey);
  });
}

export function groupDatasetSummariesWithFreshnessFallback(
  snapshots: LayerSnapshotLatestResponse["items"],
  freshness?: OpsFreshnessResponse,
): DatasetStageSummary[] {
  const displayNameMap = buildFreshnessDisplayNameMap(freshness);
  const snapshotItems = [...snapshots];
  const existing = new Set(snapshotItems.map((item) => item.dataset_key));

  for (const group of freshness?.groups || []) {
    for (const item of group.items || []) {
      if (existing.has(item.dataset_key)) continue;
      snapshotItems.push(toSyntheticSnapshotFromFreshness(item, "raw"));
      snapshotItems.push(toSyntheticSnapshotFromFreshness(item, "serving"));
      existing.add(item.dataset_key);
    }
  }

  return groupDatasetSummaries(snapshotItems, displayNameMap);
}
