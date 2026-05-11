import type {
  CommandExampleGroup,
  DatasetSummary,
  LakeStatus,
  PartitionSummary,
  RecoveryRepositorySummary,
  RecoverySnapshotDetail,
  RecoverySnapshotSummary,
} from "../types";

type DatasetListResponse = {
  items: DatasetSummary[];
};

type PartitionListResponse = {
  items: PartitionSummary[];
};

type CommandExampleResponse = {
  groups: CommandExampleGroup[];
};

type RecoverySnapshotListResponse = {
  items: RecoverySnapshotSummary[];
  total: number;
  limit: number;
  offset: number;
};

async function fetchJson<T>(path: string, errorMessage: string): Promise<T> {
  const response = await fetch(path);
  if (!response.ok) {
    throw new Error(errorMessage);
  }
  return (await response.json()) as T;
}

export function loadLakeStatus(): Promise<LakeStatus> {
  return fetchJson<LakeStatus>("/api/lake/status", "数据湖控制台 API 请求失败。");
}

export async function loadDatasets(): Promise<DatasetSummary[]> {
  const payload = await fetchJson<DatasetListResponse>("/api/datasets", "数据湖控制台 API 请求失败。");
  return payload.items;
}

export async function loadCommandExamples(): Promise<CommandExampleGroup[]> {
  const payload = await fetchJson<CommandExampleResponse>("/api/lake/command-examples", "命令示例 API 请求失败。");
  return payload.groups;
}

export async function loadPartitions(datasetKey: string): Promise<PartitionSummary[]> {
  const payload = await fetchJson<PartitionListResponse>(
    `/api/partitions?dataset_key=${encodeURIComponent(datasetKey)}`,
    "分区 API 请求失败。",
  );
  return payload.items;
}

export function loadRecoveryRepositorySummary(): Promise<RecoveryRepositorySummary> {
  return fetchJson<RecoveryRepositorySummary>("/api/recovery/repository-summary", "Recovery Repository API 请求失败。");
}

export function loadRecoverySnapshots(params: {
  scope?: string;
  datasetKey?: string;
  pinned?: boolean;
  baselineOnly?: boolean;
  query?: string;
  limit?: number;
  offset?: number;
}): Promise<RecoverySnapshotListResponse> {
  const search = new URLSearchParams();
  if (params.scope) search.set("scope", params.scope);
  if (params.datasetKey) search.set("dataset_key", params.datasetKey);
  if (params.pinned !== undefined) search.set("pinned", String(params.pinned));
  if (params.baselineOnly !== undefined) search.set("baseline_only", String(params.baselineOnly));
  if (params.query) search.set("query", params.query);
  search.set("limit", String(params.limit ?? 100));
  search.set("offset", String(params.offset ?? 0));
  return fetchJson<RecoverySnapshotListResponse>(`/api/recovery/snapshots?${search.toString()}`, "Recovery 快照 API 请求失败。");
}

export function loadRecoverySnapshotDetail(snapshotId: string): Promise<RecoverySnapshotDetail> {
  return fetchJson<RecoverySnapshotDetail>(`/api/recovery/snapshots/${encodeURIComponent(snapshotId)}`, "Recovery 明细 API 请求失败。");
}
