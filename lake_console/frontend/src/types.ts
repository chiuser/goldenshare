export type RiskItem = {
  severity: string;
  code: string;
  message: string;
  path?: string | null;
};

export type DatasetRiskItem = RiskItem & {
  datasetKey: string;
  datasetName: string;
};

export type LakeStatus = {
  path: {
    lake_root: string;
    exists: boolean;
    readable: boolean;
    writable: boolean;
    initialized: boolean;
    layout_version: number | null;
  };
  disk: {
    total_bytes: number;
    used_bytes: number;
    free_bytes: number;
    usage_percent: number;
  } | null;
  risks: RiskItem[];
};

export type NodeSummary = {
  dataset_key: string;
  node_key: string;
  node_name: string;
  layer: string;
  layer_name: string;
  path: string;
  scan_profile: string;
  asset_role: string;
  asset_role_label: string;
  source_node_keys: string[];
  partition_dimensions: string[];
  partition_count: number;
  file_count: number;
  total_bytes: number;
  row_count: number | null;
  latest_modified_at: string | null;
  freqs: number[];
  earliest_trade_date: string | null;
  latest_trade_date: string | null;
  earliest_event_date: string | null;
  latest_event_date: string | null;
  earliest_trade_month: string | null;
  latest_trade_month: string | null;
  coverage_label: string;
  recommended_usage: string;
  registered_state: string;
  risks: RiskItem[];
};

export type DatasetSummary = {
  dataset_key: string;
  display_name: string;
  source: string;
  source_label: string;
  category: string | null;
  group_key: string | null;
  group_label: string | null;
  group_order: number | null;
  description: string | null;
  dataset_role: string;
  dataset_role_label: string;
  node_summaries: NodeSummary[];
  freqs: number[];
  supported_freqs: number[];
  raw_freqs: number[];
  derived_freqs: number[];
  partition_count: number;
  file_count: number;
  total_bytes: number;
  row_count: number | null;
  latest_modified_at: string | null;
  earliest_trade_date: string | null;
  latest_trade_date: string | null;
  earliest_event_date: string | null;
  latest_event_date: string | null;
  earliest_trade_month: string | null;
  latest_trade_month: string | null;
  coverage_label: string;
  health_status: "ok" | "warning" | "error" | "empty" | string;
  health_label: string;
  risks: RiskItem[];
  sort_order: number;
};

export type PartitionSummary = {
  dataset_key: string;
  node_key: string;
  partition_values: Record<string, string | number>;
  partition_locator: string;
  partition_label: string;
  path: string;
  file_count: number;
  total_bytes: number;
  row_count: number | null;
  modified_at: string | null;
  risks: RiskItem[];
};

export type LakePhysicalAssetSummary = {
  path: string;
  asset_type: string;
  registered_state: string;
  dataset_key: string | null;
  node_key: string | null;
  display_name: string;
  total_bytes: number;
  file_count: number;
  dir_count: number;
  latest_modified_at: string | null;
  risk_level: string;
  risk_label: string;
};

export type LakeOverviewMetric = {
  key: string;
  label: string;
  value: string;
  hint: string;
  tone: "subtle" | "success" | "warning" | "error" | string;
  sort_order: number;
};

export type LakeOverviewLayerGroup = {
  layer: string;
  layer_name: string;
  dataset_count: number;
  node_count: number;
  partition_count: number;
  file_count: number;
  total_bytes: number;
  coverage_label: string;
  freqs: number[];
  sample_path: string | null;
  sort_order: number;
};

export type LakeOverviewSyncMethodGroup = {
  key: string;
  label: string;
  count: number;
  sort_order: number;
};

export type LakeOverviewDatasetRow = {
  dataset_key: string;
  display_name: string;
  group_label: string;
  source_label: string;
  node_count: number;
  partition_count: number;
  file_count: number;
  total_bytes: number;
  coverage_label: string;
  health_status: string;
  health_label: string;
  primary_path: string | null;
  sort_order: number;
};

export type LakeOverview = {
  generated_at: string;
  lake_root: string;
  summary_metrics: LakeOverviewMetric[];
  layer_groups: LakeOverviewLayerGroup[];
  sync_method_groups: LakeOverviewSyncMethodGroup[];
  dataset_rows: LakeOverviewDatasetRow[];
  physical_assets: LakePhysicalAssetSummary[];
  risks: RiskItem[];
};

export type CommandExample = {
  example_key: string;
  title: string;
  scenario: string;
  description: string;
  command: string;
  argv: string[];
  prerequisites: string[];
  notes: string[];
};

export type CommandExampleItem = {
  item_key: string;
  item_type: "dataset" | "command_set" | string;
  display_name: string;
  description: string | null;
  examples: CommandExample[];
};

export type CommandExampleGroup = {
  group_key: string;
  group_label: string;
  group_order: number;
  items: CommandExampleItem[];
};

export type RecoveryRepositorySummary = {
  connected: boolean;
  repository_type: string | null;
  repository_path: string | null;
  lake_root: string;
  snapshot_count: number;
  pinned_snapshot_count: number;
  latest_snapshot_at: string | null;
  latest_baseline_at: string | null;
  repository_error: string | null;
};

export type RecoveryCommandHint = {
  command_key: string;
  title: string;
  command: string;
  scenario: string;
};

export type RecoverySnapshotSummary = {
  snapshot_id: string;
  manifest_id: string | null;
  description: string | null;
  scope: string;
  dataset_key: string | null;
  source_path: string;
  display_path: string;
  is_baseline: boolean;
  pins: string[];
  retention_reasons: string[];
  total_size: number;
  file_count: number;
  dir_count: number;
  started_at: string | null;
  finished_at: string | null;
};

export type RecoverySnapshotDetail = RecoverySnapshotSummary & {
  repository_path: string | null;
  host: string | null;
  user_name: string | null;
  command_hints: RecoveryCommandHint[];
};

export type SyncProfileDatasetSummary = {
  dataset_key: string;
};

export type SyncProfileSummary = {
  profile_key: string;
  display_name: string;
  description: string;
  profile_status: string;
  default_lookback_days: number | null;
  requires_kopia_backup: boolean;
  stale_after_seconds: number;
  disabled_reason: string | null;
  datasets: SyncProfileDatasetSummary[];
};

export type SyncRecommendationPlanHint = {
  profile_key: string;
  dataset_keys: string[];
  target_date: string | null;
  start_date: string | null;
  end_date: string | null;
};

export type SyncRecommendationItem = {
  dataset_key: string;
  display_name: string;
  source: string;
  status: string;
  local_latest_trade_date: string | null;
  expected_latest_trade_date: string | null;
  suggested_start_date: string | null;
  suggested_end_date: string | null;
  lag_anchor_count: number;
  lag_calendar_days: number;
  reason: string;
  plan_hint: SyncRecommendationPlanHint | null;
};

export type SyncRecommendationResponse = {
  generated_at: string;
  profile_key: string;
  cutoff_time: string;
  expected_reference_date: string | null;
  aggregate_plan_hint: SyncRecommendationPlanHint | null;
  items: SyncRecommendationItem[];
};

export type SyncLock = {
  status: string;
  run_id: string | null;
  profile_key: string | null;
  owner_pid: number | null;
  owner_host: string | null;
  acquired_at: string | null;
  last_heartbeat_at: string | null;
  stale_after_seconds: number;
  can_release_stale: boolean;
};

export type SyncPlanDatasetPlan = {
  dataset_key: string;
  display_name: string;
  source: string;
  api_name: string;
  mode: string;
  request_strategy_key: string;
  request_count: number;
  partition_count: number;
  write_policy: string;
  write_paths: string[];
  required_manifests: string[];
  parameters: Record<string, unknown>;
  status: string;
  notes: string[];
  date_axis?: string;
  partition_field?: string;
  source_date_field?: string;
  event_date_partitions?: Array<Record<string, unknown>>;
  zero_row_date_count?: number;
  source_row_count?: number;
  coverage_label?: string;
};

export type SyncPipelineStage = {
  stage_key: string;
  stage_title: string;
  stage_order: number;
  stage_status: string;
  stage_status_label: string;
  display_summary: string;
  input_summary: Record<string, unknown>;
  output_summary: Record<string, unknown>;
  metrics: Record<string, unknown>;
  artifacts: unknown[];
  issues: SyncPlanIssue[];
  requires_confirmation: boolean;
  confirmation_prompt: string | null;
  confirmed_by: string | null;
  confirmed_at: string | null;
  next_action: {
    action: string;
    label: string;
    [key: string]: unknown;
  } | null;
};

export type SyncPlanIssue = {
  dataset_key?: string;
  code?: string;
  message?: string;
  [key: string]: unknown;
};

export type SyncBackupPlan = {
  required: boolean;
  provider: string;
  snapshot_strategy: string;
  pin_policy: string;
  pinned: boolean;
  backup_paths: string[];
  snapshot_paths?: string[];
  path_missing_before_write: string[];
};

export type SyncPlanResponse = {
  plan_token: string;
  plan_token_expires_at: string;
  profile_key: string;
  profile: SyncProfileSummary;
  request: Record<string, unknown>;
  normalized_parameters: Record<string, unknown>;
  lock: SyncLock;
  dataset_plans: SyncPlanDatasetPlan[];
  pipeline_stages: SyncPipelineStage[];
  affected_trade_dates: string[];
  affected_months: string[];
  affected_event_dates: string[];
  backup_plan: SyncBackupPlan;
  blockers: SyncPlanIssue[];
  warnings: SyncPlanIssue[];
  summary: {
    dataset_count?: number;
    blocked_count?: number;
    write_path_count?: number;
    backup_path_count?: number;
    snapshot_path_count?: number;
    path_missing_before_write_count?: number;
    [key: string]: unknown;
  };
};

export type SyncRunResponse = {
  run_id: string;
  profile_key: string;
  status: string;
  run_status: string | null;
  lock: SyncLock;
  detail_url: string;
  events_url: string;
};

export type SyncCurrentRun = {
  active_run_id: string | null;
  status: string;
  profile_key: string | null;
  started_at: string | null;
  updated_at: string;
  progress_summary: string;
  current_dataset_key: string | null;
  current_partition: string | null;
  current_stage_key: string | null;
  requires_confirmation: boolean;
  next_action: Record<string, unknown> | null;
};

export type SyncRunDetail = {
  run_id: string;
  profile_key: string;
  plan_token: string;
  status: string;
  run_status: string;
  started_at: string;
  finished_at: string | null;
  backup: Record<string, unknown> | null;
  pipeline_stages: SyncPipelineStage[];
  current_stage_key: string | null;
  requires_confirmation: boolean;
  next_action: {
    action: string;
    label: string;
    [key: string]: unknown;
  } | null;
  progress: Record<string, unknown>;
  dataset_results: Record<string, unknown>[];
  errors: SyncPlanIssue[];
};

export type SyncRunEvent = {
  seq: number;
  event_id: string;
  created_at: string;
  level: string;
  stage_key: string | null;
  event_type: string;
  message: string;
  dataset_key: string | null;
  partition_locator: string | null;
  metrics: Record<string, unknown>;
  error: SyncPlanIssue | null;
};
