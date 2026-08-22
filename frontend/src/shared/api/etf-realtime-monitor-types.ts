export interface EtfRealtimeMonitorActiveEtfItem {
  ts_code: string;
  csname: string | null;
  extname: string | null;
  cname: string | null;
  exchange: string | null;
  etf_type: string | null;
  list_date: string | null;
  list_status: string | null;
  latest_fund_daily_date: string | null;
  in_monitor_pool: boolean;
}

export interface EtfRealtimeMonitorActiveEtfListResponse {
  items: EtfRealtimeMonitorActiveEtfItem[];
  page: number;
  page_size: number;
  total: number;
}

export interface EtfRealtimeMonitorPoolItem {
  id: number;
  ts_code: string;
  etf_name: string | null;
  group_key: string;
  group_name: string;
  enabled: boolean;
  display_order: number;
  note: string | null;
  has_etf_rule_override: boolean;
  latest_alert_at: string | null;
  latest_alert_severity: string | null;
  created_at: string;
  updated_at: string;
}

export interface EtfRealtimeMonitorPoolListResponse {
  items: EtfRealtimeMonitorPoolItem[];
  page: number;
  page_size: number;
  total: number;
}

export interface EtfRealtimeMonitorRuleItem {
  id: number;
  scope_type: string;
  scope_key: string;
  scope_display_name: string | null;
  window_minutes: number;
  observe_ratio: string;
  alert_ratio: string;
  strong_ratio: string;
  cooldown_minutes: number;
  feishu_enabled: boolean;
  enabled: boolean;
  created_at: string;
  updated_at: string;
}

export interface EtfRealtimeMonitorRuleListResponse {
  items: EtfRealtimeMonitorRuleItem[];
  total: number;
}

export interface EtfRealtimeMonitorAlertItem {
  id: number;
  trade_date: string;
  triggered_at: string;
  bucket_end_time: string;
  window_minutes: number;
  ts_code: string;
  etf_name: string | null;
  group_key: string;
  group_name: string;
  severity: string;
  current_amount_yuan: string;
  baseline_amount_yuan: string;
  ratio: string;
  feishu_status: string;
}

export interface EtfRealtimeMonitorAlertListResponse {
  items: EtfRealtimeMonitorAlertItem[];
  page: number;
  page_size: number;
  total: number;
}

export interface EtfRealtimeMonitorSummaryResponse {
  monitor_total: number;
  monitor_enabled: number;
  observe_count: number;
  alert_count: number;
  strong_count: number;
  feishu_success_count: number;
  feishu_failed_count: number;
  latest_archive_date: string | null;
}
