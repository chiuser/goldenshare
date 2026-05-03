export interface DateCompletenessRuleItem {
  dataset_key: string;
  display_name: string;
  group_key: string;
  group_label: string;
  group_order: number;
  item_order: number;
  domain_key: string;
  domain_display_name: string;
  target_table: string;
  date_axis: string;
  bucket_rule: string;
  window_mode: string;
  input_shape: string;
  observed_field: string | null;
  bucket_window_rule: string | null;
  bucket_applicability_rule: string;
  audit_applicable: boolean;
  not_applicable_reason: string | null;
  rule_label: string;
}

export interface DateCompletenessRuleGroup {
  group_key: "supported" | "unsupported";
  group_label: string;
  items: DateCompletenessRuleItem[];
}

export interface DateCompletenessRuleListResponse {
  summary: {
    total: number;
    supported: number;
    unsupported: number;
  };
  groups: DateCompletenessRuleGroup[];
}

export interface DateCompletenessRunItem {
  id: number;
  dataset_key: string;
  display_name: string;
  target_table: string;
  run_mode: "manual" | "scheduled";
  run_status: "queued" | "running" | "succeeded" | "failed" | "canceled";
  result_status: "passed" | "failed" | "error" | null;
  start_date: string;
  end_date: string;
  date_axis: string;
  bucket_rule: string;
  window_mode: string;
  input_shape: string;
  observed_field: string;
  bucket_window_rule: string;
  bucket_applicability_rule: string;
  expected_bucket_count: number;
  actual_bucket_count: number;
  missing_bucket_count: number;
  excluded_bucket_count: number;
  gap_range_count: number;
  current_stage: string | null;
  operator_message: string | null;
  technical_message: string | null;
  requested_by_user_id: number | null;
  schedule_id: number | null;
  requested_at: string;
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface DateCompletenessRunCreateResponse {
  id: number;
  run_status: string;
  dataset_key: string;
  display_name: string;
  start_date: string;
  end_date: string;
  requested_at: string;
}

export interface DateCompletenessRunListResponse {
  total: number;
  items: DateCompletenessRunItem[];
}

export interface DateCompletenessGapItem {
  id: number;
  run_id: number;
  dataset_key: string;
  bucket_kind: string;
  range_start: string;
  range_end: string;
  missing_count: number;
  sample_values: string[];
  created_at: string;
}

export interface DateCompletenessGapListResponse {
  total: number;
  items: DateCompletenessGapItem[];
}

export interface DateCompletenessExclusionItem {
  id: number;
  run_id: number;
  dataset_key: string;
  bucket_kind: string;
  bucket_value: string;
  window_start: string;
  window_end: string;
  reason_code: string;
  reason_message: string;
  created_at: string;
}

export interface DateCompletenessExclusionListResponse {
  total: number;
  items: DateCompletenessExclusionItem[];
}

export interface DateCompletenessScheduleItem {
  id: number;
  dataset_key: string;
  display_name: string;
  status: "active" | "paused";
  window_mode: "fixed_range" | "rolling";
  start_date: string | null;
  end_date: string | null;
  lookback_count: number | null;
  lookback_unit: "calendar_day" | "open_day" | "month" | null;
  calendar_scope: "default_cn_market" | "cn_a_share" | "hk_market" | "custom_exchange";
  calendar_exchange: string | null;
  cron_expr: string;
  timezone: string;
  next_run_at: string | null;
  last_run_id: number | null;
  last_run_status: DateCompletenessRunItem["run_status"] | null;
  last_result_status: DateCompletenessRunItem["result_status"];
  last_run_finished_at: string | null;
  created_by_user_id: number | null;
  updated_by_user_id: number | null;
  created_at: string;
  updated_at: string;
}

export interface DateCompletenessScheduleListResponse {
  total: number;
  items: DateCompletenessScheduleItem[];
}

export interface DateCompletenessScheduleCreateRequest {
  dataset_key: string;
  display_name?: string | null;
  status: "active" | "paused";
  window_mode: "fixed_range" | "rolling";
  start_date?: string | null;
  end_date?: string | null;
  lookback_count?: number | null;
  lookback_unit?: "calendar_day" | "open_day" | "month" | null;
  calendar_scope: "default_cn_market";
  calendar_exchange?: string | null;
  cron_expr: string;
  timezone: string;
}
