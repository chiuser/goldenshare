export interface DateCompletenessRuleItem {
  dataset_key: string;
  display_name: string;
  domain_key: string;
  domain_display_name: string;
  target_table: string;
  date_axis: string;
  bucket_rule: string;
  window_mode: string;
  input_shape: string;
  observed_field: string | null;
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
  expected_bucket_count: number;
  actual_bucket_count: number;
  missing_bucket_count: number;
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
