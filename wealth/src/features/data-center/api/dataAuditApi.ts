import { request } from "./dataCenterApi";

export const DATA_AUDIT_PATH = "/wealth/data-center/data-audit";
const ROOT = "/api/v1/wealth/data-center/data-audit/days";

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
};

export const dataAuditApi = {
  day: (day: string, signal: AbortSignal) => request<AuditDay>(`${ROOT}/${day}`, {}, signal),
  detail: (day: string, key: string, run: string, signal: AbortSignal) =>
    request<AuditDetail>(`${ROOT}/${day}/assets/${encodeURIComponent(key)}?summary_run_id=${encodeURIComponent(run)}`, {}, signal),
};
