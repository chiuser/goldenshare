import type {
  CommandExampleGroup,
  DatasetSummary,
  LakeOverview,
  LakeStatus,
  PartitionSummary,
  RecoveryRepositorySummary,
  RecoverySnapshotDetail,
  RecoverySnapshotSummary,
  SyncCurrentRun,
  SyncLock,
  SyncPlanResponse,
  SyncProfileSummary,
  SyncRecommendationResponse,
  SyncRunDetail,
  SyncRunEvent,
  SyncRunResponse,
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

type SyncProfileListResponse = {
  items: SyncProfileSummary[];
};

type SyncRunEventListResponse = {
  items: SyncRunEvent[];
  next_cursor: number;
};

async function fetchJson<T>(path: string, errorMessage: string): Promise<T> {
  return requestJson<T>(path, { method: "GET" }, errorMessage);
}

async function postJson<T>(path: string, body: unknown, errorMessage: string): Promise<T> {
  return requestJson<T>(
    path,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
    errorMessage,
  );
}

async function requestJson<T>(path: string, init: RequestInit, errorMessage: string): Promise<T> {
  const response = await fetch(path, init);
  if (!response.ok) {
    throw new Error(await readApiError(response, errorMessage));
  }
  return (await response.json()) as T;
}

async function readApiError(response: Response, fallback: string): Promise<string> {
  try {
    const payload = (await response.clone().json()) as { detail?: unknown };
    if (payload.detail && typeof payload.detail === "object") {
      const detail = payload.detail as { code?: unknown; message?: unknown };
      const code = typeof detail.code === "string" ? detail.code : `HTTP_${response.status}`;
      const message = typeof detail.message === "string" ? detail.message : fallback;
      return `[${code}] ${message}`;
    }
    if (typeof payload.detail === "string" && payload.detail.trim()) {
      return payload.detail;
    }
  } catch {
    try {
      const text = await response.text();
      if (text.trim()) {
        return text.trim();
      }
    } catch {
      // Keep the fallback below when the API did not return readable text.
    }
  }
  return fallback;
}

export function loadLakeStatus(): Promise<LakeStatus> {
  return fetchJson<LakeStatus>("/api/lake/status", "数据湖控制台 API 请求失败。");
}

export function loadLakeOverview(): Promise<LakeOverview> {
  return fetchJson<LakeOverview>("/api/lake/overview", "数据湖总览 API 请求失败。");
}

export async function loadDatasets(): Promise<DatasetSummary[]> {
  const payload = await fetchJson<DatasetListResponse>("/api/lake/datasets", "数据湖数据集 API 请求失败。");
  return payload.items;
}

export async function loadCommandExamples(): Promise<CommandExampleGroup[]> {
  const payload = await fetchJson<CommandExampleResponse>("/api/lake/command-examples", "命令示例 API 请求失败。");
  return payload.groups;
}

export async function loadPartitions(datasetKey: string, nodeKey: string): Promise<PartitionSummary[]> {
  const payload = await fetchJson<PartitionListResponse>(
    `/api/lake/partitions?dataset_key=${encodeURIComponent(datasetKey)}&node_key=${encodeURIComponent(nodeKey)}`,
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

export async function loadSyncProfiles(): Promise<SyncProfileSummary[]> {
  const payload = await fetchJson<SyncProfileListResponse>("/api/lake/sync/profiles", "Sync Center Profile API 请求失败。");
  return payload.items;
}

export function loadSyncRecommendations(profileKey = "prod_db_daily"): Promise<SyncRecommendationResponse> {
  return fetchJson<SyncRecommendationResponse>(
    `/api/lake/sync/recommendations?profile_key=${encodeURIComponent(profileKey)}`,
    "Sync Center Recommendation API 请求失败。",
  );
}

export function loadSyncLock(): Promise<SyncLock> {
  return fetchJson<SyncLock>("/api/lake/sync/lock", "Sync Center Lock API 请求失败。");
}

export function loadSyncCurrentRun(): Promise<SyncCurrentRun> {
  return fetchJson<SyncCurrentRun>("/api/lake/sync/runs/current", "Sync Center 当前任务 API 请求失败。");
}

export function createSyncPlan(params: {
  profileKey: string;
  datasetKeys: string[];
  targetDate?: string | null;
  startDate?: string | null;
  endDate?: string | null;
  freqs?: number[] | null;
  scope?: string | null;
  mode?: string | null;
}): Promise<SyncPlanResponse> {
  return postJson<SyncPlanResponse>(
    `/api/lake/sync/profiles/${encodeURIComponent(params.profileKey)}/plan`,
    {
      dataset_keys: params.datasetKeys.length ? params.datasetKeys : null,
      target_date: params.targetDate || null,
      start_date: params.startDate || null,
      end_date: params.endDate || null,
      freqs: params.freqs ?? null,
      scope: params.scope ?? null,
      mode: params.mode ?? null,
      include_backup_plan: true,
    },
    "Sync Center Plan API 请求失败。",
  );
}

export function startSyncRun(planToken: string): Promise<SyncRunResponse> {
  return postJson<SyncRunResponse>(
    "/api/lake/sync/runs",
    {
      plan_token: planToken,
      confirmed_backup_required: true,
      confirmed_no_sql: true,
    },
    "Sync Center Run API 请求失败。",
  );
}

export function loadSyncRunDetail(runId: string): Promise<SyncRunDetail> {
  return fetchJson<SyncRunDetail>(`/api/lake/sync/runs/${encodeURIComponent(runId)}`, "Sync Center Run 详情 API 请求失败。");
}

export function loadSyncRunEvents(runId: string, cursor = 0): Promise<SyncRunEventListResponse> {
  return fetchJson<SyncRunEventListResponse>(
    `/api/lake/sync/runs/${encodeURIComponent(runId)}/events?cursor=${cursor}&limit=200`,
    "Sync Center Run 事件 API 请求失败。",
  );
}

export function continueSyncRun(runId: string): Promise<SyncRunDetail> {
  return postJson<SyncRunDetail>(
    `/api/lake/sync/runs/${encodeURIComponent(runId)}/continue`,
    { confirm_continue: true },
    "Sync Center Run 继续 API 请求失败。",
  );
}

export function abortSyncRun(runId: string, reason: string): Promise<SyncRunDetail> {
  return postJson<SyncRunDetail>(
    `/api/lake/sync/runs/${encodeURIComponent(runId)}/abort`,
    { reason },
    "Sync Center Run 停止 API 请求失败。",
  );
}
