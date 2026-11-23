import { request } from "./dataCenterApi";

export const DATA_AUDIT_PATH = "/wealth/data-center/data-audit";
const ROOT = "/api/v1/wealth/data-center/data-audit";
const assetPath = (day: string, key: string) => `${ROOT}/days/${day}/assets/${encodeURIComponent(key)}`;

export const DC_CLASSIFICATION_RAW = "raw_tushare_dc_index";
export const DC_CLASSIFICATION_SILVER = "silver_dc_index";

export const completenessLabels = {
  complete: "已确认齐备",
  gap: "已确认缺口",
  pending: "待确认",
  not_applicable: "不适用",
} as const;

export const updateLabels = {
  updated: "已更新",
  overdue: "超期未更新",
  not_due: "尚未到期",
  unknown: "无法确认",
  not_required: "无需更新",
} as const;

export type CompletenessStatus = keyof typeof completenessLabels;
export type UpdateStatus = keyof typeof updateLabels;
type Reason = { code: string; message: string };
type Scope = {
  asset_key: string;
  business_date: string;
  partition_key: string | null;
  as_of_date: string | null;
  frequency: string | null;
  coverage_scope: string;
};
type Component = { name: string; status: CompletenessStatus; reason: Reason };
type Completeness = {
  status: CompletenessStatus;
  reason: Reason;
  checked_at: string | null;
  components: Component[];
};

export type AuditRow = {
  dataset_name: string;
  layer: string;
  scope: Scope;
  update: { status: UpdateStatus; published_at: string | null; expected_date: string | null; deadline_at: string | null; reason: Reason };
  completeness: Completeness;
};

export type AuditDetail = AuditRow & {
  version: {
    target_version: string | null;
    rule_version: string;
    inputs: { asset_key: string; target_version: string; scope: Scope }[];
  };
  completeness: Completeness & {
    expected_count: number | null;
    actual_count: number | null;
    missing_count: number | null;
    extra_count: number | null;
    evidence: { type: string; check_name?: string; run_id: string; record_id: number; passed?: boolean; message?: string | null }[];
    samples: Record<string, unknown>[];
    exceptions: Record<string, unknown>[];
  };
};

export type AuditDay = {
  state: "ready" | "not_generated" | "unavailable";
  business_date: string;
  summary_run_id: string | null;
  observed_at: string | null;
  generated_at: string | null;
  summary: Record<CompletenessStatus, number> | null;
  rows: AuditRow[];
  can_operate?: boolean;
};

export type AuditBoard = { category: string; code: string; name: string };
export type AuditBoardStandard = { business_date: string; version: string; boards: AuditBoard[] };
export type AuditBoardSourceResult = {
  status: "success" | "not_returned" | "failed";
  count?: number | null;
  message?: string | null;
  checked_at?: string;
  board?: { name: string };
};
export type AuditBoardRecheck = {
  business_date: string;
  review_version: string;
  run_id?: string;
  checked_at?: string | null;
  has_confirmed_gap: boolean;
  results: {
    code: string;
    classification: AuditBoardSourceResult;
    member: AuditBoardSourceResult;
    confirmed_gap?: boolean;
  }[];
};
export type AuditBoardReview = {
  business_date: string;
  review_version: string | null;
  raw_run_id: string | null;
  state: string;
  reason?: string | null;
  can_confirm: boolean;
  can_operate?: boolean;
  reference: AuditBoardStandard | null;
  current: AuditBoard[];
  added: AuditBoard[];
  removed: AuditBoard[];
  standard: AuditBoardStandard | null;
  recheck: AuditBoardRecheck | null;
};
export type AuditBoardRun = {
  run_id: string;
  status: string;
  deadline?: string | null;
  result?: AuditBoardRecheck | AuditBoardStandard | null;
  error?: Reason | null;
};

function submitBoard(path: string, body: Record<string, string>, signal: AbortSignal) {
  return request<AuditBoardRun>(path, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  }, signal);
}

export const dataAuditApi = {
  day: (day: string, signal: AbortSignal) => request<AuditDay>(`${ROOT}/days/${day}`, {}, signal),
  detail: (day: string, key: string, run: string, signal: AbortSignal) =>
    request<AuditDetail>(`${assetPath(day, key)}?summary_run_id=${encodeURIComponent(run)}`, {}, signal),
  boardStandard: (day: string, key: string, signal: AbortSignal) =>
    request<AuditBoardReview>(`${assetPath(day, key)}/board-standard`, {}, signal),
  boardRecheck: (day: string, version: string, retryRunId: string | undefined, signal: AbortSignal) =>
    submitBoard(`${assetPath(day, DC_CLASSIFICATION_RAW)}/board-recheck`, {
      review_version: version, ...(retryRunId ? { retry_run_id: retryRunId } : {}),
    }, signal),
  boardConfirm: (day: string, version: string, signal: AbortSignal) =>
    submitBoard(`${assetPath(day, DC_CLASSIFICATION_RAW)}/board-confirm`, { review_version: version }, signal),
  boardRun: (run: string, signal: AbortSignal) =>
    request<AuditBoardRun>(`${ROOT}/runs/${encodeURIComponent(run)}`, {}, signal),
};
