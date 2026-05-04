export type RiskItem = {
  severity: string;
  code: string;
  message: string;
  path?: string | null;
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

export type LayerSummary = {
  layer: string;
  layer_name: string;
  purpose: string;
  layout: string;
  path: string;
  partition_count: number;
  file_count: number;
  total_bytes: number;
  row_count: number | null;
  latest_modified_at: string | null;
  freqs: number[];
  earliest_trade_date: string | null;
  latest_trade_date: string | null;
  earliest_trade_month: string | null;
  latest_trade_month: string | null;
  recommended_usage: string;
  risks: RiskItem[];
};

export type DatasetSummary = {
  dataset_key: string;
  display_name: string;
  source: string;
  category: string | null;
  group_key: string | null;
  group_label: string | null;
  group_order: number | null;
  description: string | null;
  dataset_role: string;
  storage_root: string | null;
  layers: string[];
  layer_summaries: LayerSummary[];
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
  earliest_trade_month: string | null;
  latest_trade_month: string | null;
  primary_layout: string | null;
  available_layouts: string[];
  write_policy: string | null;
  update_mode: string | null;
  health_status: "ok" | "warning" | "error" | "empty" | string;
  risks: RiskItem[];
};

export type PartitionSummary = {
  dataset_key: string;
  layer: string;
  layout: string;
  freq: number | null;
  trade_date: string | null;
  trade_month: string | null;
  bucket: number | null;
  path: string;
  file_count: number;
  total_bytes: number;
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
