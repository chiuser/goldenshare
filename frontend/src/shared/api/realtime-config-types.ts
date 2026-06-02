export type RealtimeConfigValue =
  | string
  | number
  | boolean
  | string[]
  | null
  | Record<string, unknown>;

export interface RealtimeConfigFieldOption {
  label: string;
  value: string;
}

export interface RealtimeConfigField {
  key: string;
  label: string;
  editable: boolean;
  control: "switch" | "number_input" | "checkbox_group" | "locked_text" | string;
  value_type: string;
  options: RealtimeConfigFieldOption[];
}

export interface RealtimeConfigObjectSummary {
  object_key: string;
  object_kind: string;
  display_name: string;
  enabled: boolean;
  version: number;
  requires_collector_restart: boolean;
}

export interface RealtimeConfigObjectListResponse {
  items: RealtimeConfigObjectSummary[];
}

export interface RealtimeConfigObjectDetailResponse {
  object_key: string;
  display_name: string;
  object_kind: string;
  mode: string;
  version: number;
  requires_collector_restart: boolean;
  effective_config: Record<string, RealtimeConfigValue>;
  locked_config: Record<string, RealtimeConfigValue>;
  fields: RealtimeConfigField[];
}

export interface RealtimeConfigValidationErrorItem {
  field: string | null;
  code: string;
  message: string;
}

export interface RealtimeConfigWarningItem {
  field: string | null;
  message: string;
}

export interface RealtimeConfigDiffItem {
  field: string;
  before: unknown;
  after: unknown;
}

export interface RealtimeConfigImpact {
  requires_collector_restart: boolean;
  affected_feeds: string[];
}

export interface RealtimeConfigValidateResponse {
  valid: boolean;
  errors: RealtimeConfigValidationErrorItem[];
  warnings: RealtimeConfigWarningItem[];
  diff: RealtimeConfigDiffItem[];
  impact: RealtimeConfigImpact;
}

export interface RealtimeConfigPublishResponse extends RealtimeConfigObjectDetailResponse {
  warnings: RealtimeConfigWarningItem[];
  impact: RealtimeConfigImpact;
  revision_id: number | null;
}

export interface RealtimeConfigRevisionItem {
  id: number;
  object_type: string;
  object_id: string;
  action: string;
  before_json: Record<string, unknown> | null;
  after_json: Record<string, unknown> | null;
  changed_by_username: string | null;
  changed_at: string;
}

export interface RealtimeConfigRevisionListResponse {
  items: RealtimeConfigRevisionItem[];
  total: number;
}
