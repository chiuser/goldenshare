export interface LoginResponse {
  token: string;
  refresh_token: string | null;
  access_token_expires_at: string | null;
  username: string;
  is_admin: boolean;
  display_name: string | null;
}

export interface CurrentUserResponse {
  id: number;
  username: string;
  display_name: string | null;
  email: string | null;
  account_state: string;
  is_admin: boolean;
  is_active: boolean;
  roles: string[];
  permissions: string[];
}

export interface RegisterRequestBody {
  username: string;
  password: string;
  display_name?: string;
  email?: string;
  invite_code?: string;
}

export interface RegisterResponse {
  user_id: number;
  username: string;
  account_state: string;
  requires_email_verification: boolean;
  token: string | null;
  refresh_token: string | null;
  verification_token_debug: string | null;
}

export interface LookupAccountResponse {
  ok: boolean;
  message: string;
  token_debug: string | null;
}

export interface AdminUserListItem {
  id: number;
  username: string;
  display_name: string | null;
  email: string | null;
  account_state: string;
  is_admin: boolean;
  is_active: boolean;
  roles: string[];
  email_verified_at: string | null;
  last_login_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface AdminUserListResponse {
  total: number;
  items: AdminUserListItem[];
}

export interface AdminInviteItem {
  id: number;
  code_hint: string;
  role_key: string;
  assigned_email: string | null;
  max_uses: number;
  used_count: number;
  expires_at: string | null;
  disabled_at: string | null;
  last_used_at: string | null;
  created_by_user_id: number | null;
  note: string | null;
  created_at: string;
  updated_at: string;
}

export interface AdminInviteListResponse {
  total: number;
  items: AdminInviteItem[];
}

export interface AdminInviteCreateResponse {
  id: number;
  code: string;
  role_key: string;
  assigned_email: string | null;
  max_uses: number;
  used_count: number;
  expires_at: string | null;
  disabled_at: string | null;
  note: string | null;
  created_at: string;
}

export interface HealthResponse {
  status: string;
  service: string;
  env: string;
}

export interface ShareMarketOverviewResponse {
  available: boolean;
  unavailable_reason: string | null;
  summary: {
    as_of_date: string | null;
    total_symbols: number;
    up_count: number | null;
    down_count: number | null;
    flat_count: number | null;
    avg_pct_change: string | null;
    total_amount: string | null;
  } | null;
  top_by_amount: Array<{
    ts_code: string;
    name: string | null;
    trade_date: string | null;
    close: string | null;
    pct_change: string | null;
    amount: string | null;
  }>;
  top_gainers: Array<{
    ts_code: string;
    name: string | null;
    trade_date: string | null;
    close: string | null;
    pct_change: string | null;
    amount: string | null;
  }>;
  top_losers: Array<{
    ts_code: string;
    name: string | null;
    trade_date: string | null;
    close: string | null;
    pct_change: string | null;
    amount: string | null;
  }>;
}

export interface OpsOverviewResponse {
  today_kpis: {
    business_date: string;
    total_requests: number;
    completed_requests: number;
    running_requests: number;
    failed_requests: number;
    queued_requests: number;
    attention_dataset_count: number;
  };
  kpis: {
    total_executions: number;
    queued_executions: number;
    running_executions: number;
    success_executions: number;
    failed_executions: number;
    canceled_executions: number;
    partial_success_executions: number;
  };
  freshness_summary: {
    total_datasets: number;
    fresh_datasets: number;
    lagging_datasets: number;
    stale_datasets: number;
    unknown_datasets: number;
    disabled_datasets: number;
  };
  lagging_datasets: Array<{
    dataset_key: string;
    display_name: string;
    freshness_status: string;
    lag_days: number | null;
    earliest_business_date: string | null;
    expected_business_date: string | null;
    latest_business_date: string | null;
    last_sync_date: string | null;
    primary_action_key: string | null;
    recent_failure_message?: string | null;
    recent_failure_summary?: string | null;
    recent_failure_at?: string | null;
  }>;
  recent_executions: TaskRunListResponse["items"];
  recent_failures: TaskRunListResponse["items"];
}

export interface OpsOverviewSummaryResponse {
  freshness_summary: OpsOverviewResponse["freshness_summary"];
}

export interface OpsFreshnessResponse {
  summary: {
    total_datasets: number;
    fresh_datasets: number;
    lagging_datasets: number;
    stale_datasets: number;
    unknown_datasets: number;
    disabled_datasets: number;
  };
  groups: Array<{
    domain_key: string;
    domain_display_name: string;
    items: Array<{
      dataset_key: string;
      resource_key: string;
      display_name: string;
      cadence: string;
      target_table: string;
      raw_table: string | null;
      earliest_business_date: string | null;
      observed_business_date: string | null;
      latest_business_date: string | null;
      freshness_note: string | null;
      latest_success_at: string | null;
      last_sync_date: string | null;
      expected_business_date: string | null;
      lag_days: number | null;
      freshness_status: string;
      recent_failure_message: string | null;
      recent_failure_summary: string | null;
      recent_failure_at: string | null;
      primary_action_key: string | null;
      auto_schedule_status: string;
      auto_schedule_total: number;
      auto_schedule_active: number;
      auto_schedule_next_run_at: string | null;
      active_execution_status: string | null;
      active_execution_started_at: string | null;
    }>;
  }>;
}

export interface ScheduleListResponse {
  items: Array<{
    id: number;
    spec_key: string;
    spec_display_name: string | null;
    target_display_name: string | null;
    display_name: string;
    status: string;
    schedule_type: string;
    trigger_mode: string;
    cron_expr: string | null;
    timezone: string;
    next_run_at: string | null;
    updated_at: string;
  }>;
  total: number;
}

export interface ScheduleDetailResponse {
  id: number;
  spec_type: string;
  spec_key: string;
  spec_display_name: string | null;
  target_display_name: string | null;
  display_name: string;
  status: string;
  schedule_type: string;
  trigger_mode: string;
  cron_expr: string | null;
  timezone: string;
  calendar_policy: string | null;
  probe_config: {
    source_key: string | null;
    window_start: string | null;
    window_end: string | null;
    probe_interval_seconds: number;
    max_triggers_per_day: number;
    condition_kind: string;
    min_rows_in: number | null;
    workflow_dataset_keys: string[];
  } | null;
  params_json: Record<string, unknown>;
  retry_policy_json: Record<string, unknown>;
  concurrency_policy_json: Record<string, unknown>;
  next_run_at: string | null;
  last_triggered_at: string | null;
  created_by_username: string | null;
  updated_by_username: string | null;
  created_at: string;
  updated_at: string;
}

export interface ScheduleRevisionListResponse {
  items: Array<{
    id: number;
    action: string;
    before_json: Record<string, unknown> | null;
    after_json: Record<string, unknown> | null;
    changed_by_username: string | null;
    changed_at: string;
  }>;
  total: number;
}

export interface SchedulePreviewResponse {
  schedule_type: string;
  timezone: string;
  preview_times: string[];
}

export interface TaskRunListResponse {
  items: Array<{
    id: number;
    task_type: string;
    resource_key: string | null;
    action_key: string | null;
    action: string;
    title: string;
    time_scope: TaskRunTimeScope | null;
    time_scope_label: string | null;
    schedule_display_name: string | null;
    trigger_source: string;
    status: string;
    status_reason_code: string | null;
    requested_by_username: string | null;
    requested_at: string;
    started_at: string | null;
    ended_at: string | null;
    unit_total: number;
    unit_done: number;
    unit_failed: number;
    rows_fetched: number;
    rows_saved: number;
    rows_rejected: number;
    progress_percent: number | null;
    primary_issue_id: number | null;
    primary_issue_title: string | null;
  }>;
  total: number;
}

export interface TaskRunSummaryResponse {
  total: number;
  queued: number;
  running: number;
  success: number;
  failed: number;
  canceled: number;
}

export interface TaskRunTimeScope {
  kind: string;
  start: string | null;
  end: string | null;
  label: string;
}

export interface TaskRunDisplayObject {
  title: string;
  description: string | null;
  fields: Array<{
    label: string;
    value: string;
  }>;
}

export interface TaskRunViewResponse {
  run: {
    id: number;
    task_type: string;
    resource_key: string | null;
    action_key: string | null;
    action: string;
    title: string;
    trigger_source: string;
    status: string;
    status_reason_code: string | null;
    requested_by_username: string | null;
    schedule_display_name: string | null;
    time_input: Record<string, unknown>;
    filters: Record<string, unknown>;
    time_scope: TaskRunTimeScope | null;
    time_scope_label: string | null;
    requested_at: string;
    queued_at: string | null;
    started_at: string | null;
    ended_at: string | null;
    cancel_requested_at: string | null;
    canceled_at: string | null;
  };
  progress: {
    unit_total: number;
    unit_done: number;
    unit_failed: number;
    progress_percent: number | null;
    rows_fetched: number;
    rows_saved: number;
    rows_rejected: number;
    current_object: TaskRunDisplayObject | null;
  };
  primary_issue: {
    id: number;
    severity: string;
    code: string;
    title: string;
    operator_message: string | null;
    suggested_action: string | null;
    object: TaskRunDisplayObject | null;
    has_technical_detail: boolean;
    occurred_at: string;
  } | null;
  nodes: Array<{
    id: number;
    parent_node_id: number | null;
    node_key: string;
    node_type: string;
    sequence_no: number;
    title: string;
    resource_key: string | null;
    status: string;
    time_input: Record<string, unknown>;
    context: Record<string, unknown>;
    rows_fetched: number;
    rows_saved: number;
    rows_rejected: number;
    issue_id: number | null;
    started_at: string | null;
    ended_at: string | null;
    duration_ms: number | null;
  }>;
  node_total: number;
  nodes_truncated: boolean;
  actions: {
    can_retry: boolean;
    can_cancel: boolean;
    can_copy_params: boolean;
  };
}

export interface TaskRunCreateResponse {
  id: number;
  resource_key: string | null;
  status: string;
  title: string;
  created_at: string;
}

export interface TaskRunIssueDetailResponse {
  id: number;
  task_run_id: number;
  node_id: number | null;
  severity: string;
  code: string;
  title: string;
  operator_message: string | null;
  suggested_action: string | null;
  object: TaskRunDisplayObject | null;
  technical_message: string | null;
  technical_payload: Record<string, unknown>;
  source_phase: string | null;
  occurred_at: string;
}

export interface OpsCatalogResponse {
  job_specs: Array<{
    key: string;
    spec_type?: string;
    display_name: string;
    resource_key?: string | null;
    resource_display_name?: string | null;
    domain_key?: string | null;
    domain_display_name?: string | null;
    date_selection_rule?: string | null;
    category: string;
    description: string;
    strategy_type: string;
    executor_kind: string;
    target_tables: string[];
    schedule_binding_count: number;
    active_schedule_count: number;
    supports_manual_run?: boolean;
    supports_schedule?: boolean;
    supports_retry?: boolean;
    supported_params?: Array<{
      key: string;
      display_name: string;
      param_type: string;
      description: string;
      required: boolean;
      options: string[];
      multi_value: boolean;
    }>;
  }>;
  workflow_specs: Array<{
    key: string;
    display_name: string;
    description: string;
    domain_key: string;
    domain_display_name: string;
    parallel_policy: string;
    schedule_binding_count: number;
    active_schedule_count: number;
    supports_manual_run?: boolean;
    supports_schedule?: boolean;
    supported_params?: Array<{
      key: string;
      display_name: string;
      param_type: string;
      description: string;
      required: boolean;
      options: string[];
      multi_value: boolean;
    }>;
    steps?: Array<{
      step_key: string;
      job_key: string;
      display_name: string;
      depends_on: string[];
      default_params: Record<string, unknown>;
    }>;
  }>;
}

export interface OpsManualActionsResponse {
  groups: Array<{
    group_key: string;
    group_label: string;
    group_order: number;
    actions: Array<{
      action_key: string;
      action_type: "dataset_action" | "job" | "workflow";
      display_name: string;
      description: string;
      resource_key: string | null;
      resource_display_name: string | null;
      date_model: {
        date_axis: string;
        bucket_rule: string;
        window_mode: string;
        input_shape: string;
        observed_field: string | null;
        audit_applicable: boolean;
        not_applicable_reason: string | null;
      } | null;
      time_form: {
        control: "trade_date_or_range" | "calendar_date_or_range" | "month_or_range" | "month_window_range" | "none";
        default_mode: "point" | "range" | "none";
        allowed_modes: Array<"point" | "range" | "none">;
        selection_rule: "trading_day_only" | "week_last_trading_day" | "month_last_trading_day" | "calendar_day" | "month_key" | "month_window" | "none";
        point_label: string;
        range_label: string;
      };
      filters: Array<{
        key: string;
        display_name: string;
        param_type: string;
        description: string;
        required: boolean;
        options: string[];
        multi_value: boolean;
      }>;
      search_keywords: string[];
      action_order: number;
      route_keys: string[];
    }>;
  }>;
}

export interface OpsManualActionTaskRunRequest {
  time_input: {
    mode: "point" | "range" | "none";
    trade_date?: string;
    start_date?: string;
    end_date?: string;
    month?: string;
    start_month?: string;
    end_month?: string;
    ann_date?: string;
    date_field?: string;
  };
  filters: Record<string, unknown>;
}

export interface IngestionCodebookItem {
  code: string;
  label: string;
  phase: string | null;
  suggested_action: string | null;
}

export interface IngestionCodebookResponse {
  version: string;
  updated_at: string;
  error_codes: IngestionCodebookItem[];
  reason_codes: IngestionCodebookItem[];
}

export interface RuntimeTickResponse {
  scheduled_count?: number;
  processed_count?: number;
  items: Array<{
    id: number;
    schedule_id: number | null;
    task_type: string;
    resource_key: string | null;
    title: string;
    trigger_source: string;
    status: string;
    requested_at: string;
    rows_fetched: number;
    rows_saved: number;
    primary_issue_title: string | null;
  }>;
}

export interface ProbeRuleListResponse {
  items: Array<{
    id: number;
    name: string;
    dataset_key: string;
    source_key: string | null;
    status: string;
    probe_interval_seconds: number;
    window_start: string | null;
    window_end: string | null;
    last_probed_at: string | null;
    last_triggered_at: string | null;
    updated_at: string;
  }>;
  total: number;
}

export interface ResolutionReleaseListResponse {
  items: Array<{
    id: number;
    dataset_key: string;
    target_policy_version: number;
    status: string;
    triggered_by_username: string | null;
    triggered_at: string;
    finished_at: string | null;
    updated_at: string;
  }>;
  total: number;
}

export interface StdMappingRuleListResponse {
  items: Array<{
    id: number;
    dataset_key: string;
    source_key: string;
    src_field: string;
    std_field: string;
    transform_fn: string | null;
    status: string;
    rule_set_version: number;
    updated_at: string;
  }>;
  total: number;
}

export interface StdCleansingRuleListResponse {
  items: Array<{
    id: number;
    dataset_key: string;
    source_key: string;
    rule_type: string;
    action: string;
    status: string;
    rule_set_version: number;
    updated_at: string;
  }>;
  total: number;
}

export interface LayerSnapshotLatestResponse {
  items: Array<{
    snapshot_date: string;
    dataset_key: string;
    source_key: string | null;
    stage: string;
    status: string;
    rows_in: number | null;
    rows_out: number | null;
    error_count: number | null;
    lag_seconds: number | null;
    message: string | null;
    calculated_at: string;
    last_success_at: string | null;
    last_failure_at: string | null;
  }>;
  total: number;
}

export interface LayerSnapshotHistoryResponse {
  items: Array<{
    snapshot_date: string;
    dataset_key: string;
    source_key: string | null;
    stage: string;
    status: string;
    rows_in: number | null;
    rows_out: number | null;
    error_count: number | null;
    lag_seconds: number | null;
    message: string | null;
    calculated_at: string;
  }>;
  total: number;
}

export interface SourceManagementBridgeResponse {
  summary: {
    probe_total: number;
    probe_active: number;
    release_total: number;
    release_running: number;
    std_mapping_total: number;
    std_mapping_active: number;
    std_cleansing_total: number;
    std_cleansing_active: number;
    layer_latest_total: number;
    layer_latest_failed: number;
  };
  probe_rules: ProbeRuleListResponse["items"];
  releases: ResolutionReleaseListResponse["items"];
  std_mapping_rules: StdMappingRuleListResponse["items"];
  std_cleansing_rules: StdCleansingRuleListResponse["items"];
  layer_latest: LayerSnapshotLatestResponse["items"];
}

export interface DatasetPipelineModeListResponse {
  total: number;
  items: Array<{
    dataset_key: string;
    display_name: string;
    domain_key: string;
    domain_display_name: string;
    mode: string;
    source_scope: string;
    layer_plan: string;
    raw_table: string | null;
    std_table_hint: string | null;
    serving_table: string | null;
    freshness_status: string;
    latest_business_date: string | null;
    std_mapping_configured: boolean;
    std_cleansing_configured: boolean;
    resolution_policy_configured: boolean;
  }>;
}

export interface DatasetCardListResponse {
  total: number;
  groups: Array<{
    domain_key: string;
    domain_display_name: string;
    items: Array<{
      card_key: string;
      dataset_key: string;
      detail_dataset_key: string;
      resource_key: string;
      display_name: string;
      domain_key: string;
      domain_display_name: string;
      status: string;
      freshness_status: string;
      mode: string;
      mode_label: string;
      mode_tone: string;
      layer_plan: string;
      cadence: string;
      raw_table: string | null;
      raw_table_label: string | null;
      target_table: string | null;
      latest_business_date: string | null;
      earliest_business_date: string | null;
      last_sync_date: string | null;
      latest_success_at: string | null;
      expected_business_date: string | null;
      lag_days: number | null;
      freshness_note: string | null;
      primary_action_key: string | null;
      active_execution_status: string | null;
      active_execution_started_at: string | null;
      auto_schedule_status: string;
      auto_schedule_total: number;
      auto_schedule_active: number;
      auto_schedule_next_run_at: string | null;
      probe_total: number;
      probe_active: number;
      std_mapping_configured: boolean;
      std_cleansing_configured: boolean;
      resolution_policy_configured: boolean;
      status_updated_at: string | null;
      stage_statuses: Array<{
        stage: string;
        stage_label: string;
        table_name: string | null;
        source_key: string | null;
        status: string;
        rows_in: number | null;
        rows_out: number | null;
        error_count: number | null;
        lag_seconds: number | null;
        message: string | null;
        calculated_at: string | null;
        last_success_at: string | null;
        last_failure_at: string | null;
      }>;
      raw_sources: Array<{
        source_key: string;
        table_name: string | null;
        status: string;
        calculated_at: string | null;
      }>;
    }>;
  }>;
}

export interface OpsReviewActiveIndexResponse {
  total: number;
  items: Array<{
    resource: string;
    ts_code: string;
    index_name: string | null;
    first_seen_date: string;
    last_seen_date: string;
    last_checked_at: string;
  }>;
}

export interface OpsReviewThsBoardsResponse {
  total: number;
  items: Array<{
    board_code: string;
    board_name: string | null;
    exchange: string | null;
    board_type: string | null;
    constituent_count: number;
    members: Array<{
      ts_code: string;
      name: string | null;
      in_date: string | null;
      out_date: string | null;
    }>;
  }>;
}

export interface OpsReviewDcBoardsResponse {
  trade_date: string | null;
  idx_type_options: string[];
  total: number;
  items: Array<{
    board_code: string;
    board_name: string | null;
    idx_type: string | null;
    constituent_count: number;
    members: Array<{
      ts_code: string;
      name: string | null;
      in_date: string | null;
      out_date: string | null;
    }>;
  }>;
}

export interface OpsReviewEquityMembershipResponse {
  dc_trade_date: string | null;
  total: number;
  items: Array<{
    ts_code: string;
    equity_name: string | null;
    board_count: number;
    boards: Array<{
      provider: string;
      board_code: string;
      board_name: string | null;
    }>;
  }>;
}

export interface OpsReviewEquitySuggestResponse {
  items: Array<{
    ts_code: string;
    name: string | null;
  }>;
}
