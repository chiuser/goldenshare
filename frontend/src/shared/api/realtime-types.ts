export interface OpsRealtimeStockRtDailyHealthResponse {
  feed_key: string;
  display_name: string;
  status: string;
  enabled: boolean;
  redis_connected: boolean;
  collector_running: boolean;
  collector_id: string | null;
  last_request_at: string | null;
  last_success_at: string | null;
  last_error_at: string | null;
  last_error_message: string | null;
  current_batch_id: string | null;
  current_batch_age_seconds: number | null;
  current_batch_received_at: string | null;
  current_batch_published_at: string | null;
  snapshot_count: number;
  source_row_count: number;
  source_elapsed_ms: number | null;
  write_elapsed_ms: number | null;
  request_count_last_minute: number;
  max_calls_per_minute: number;
  poll_interval_seconds: number;
  is_trading_day: boolean;
  collection_sessions: string[];
  collection_status: string;
  stale_after_seconds: number;
  snapshot_ttl_seconds: number;
  keep_recent_batches: number;
  batch_stream_maxlen: number;
  delta_stream_maxlen: number;
  last_batch_event_id: string | null;
  last_delta_event_id: string | null;
  delta_count_last_batch: number;
  page_polling_enabled: boolean;
  recommended_poll_interval_seconds: number;
}

export interface OpsRealtimeStockRtMinHealthItem {
  freq: string;
  feed_key: string;
  status: string;
  enabled: boolean;
  redis_connected: boolean;
  collector_running: boolean;
  collector_id: string | null;
  last_request_at: string | null;
  last_success_at: string | null;
  last_error_at: string | null;
  last_error_message: string | null;
  current_batch_id: string | null;
  current_batch_age_seconds: number | null;
  current_batch_received_at: string | null;
  current_batch_published_at: string | null;
  snapshot_count: number;
  source_row_count: number;
  source_elapsed_ms: number | null;
  write_elapsed_ms: number | null;
  request_count_last_minute: number;
  max_calls_per_minute: number;
  poll_interval_seconds: number;
  is_trading_day: boolean;
  collection_sessions: string[];
  collection_status: string;
  stale_after_seconds: number;
  snapshot_ttl_seconds: number;
  keep_recent_batches: number;
  batch_stream_maxlen: number;
  delta_stream_maxlen: number;
  last_batch_event_id: string | null;
  last_delta_event_id: string | null;
  delta_count_last_batch: number;
  invalid_count: number;
  invalid_reason_counts: Record<string, number>;
}

export interface OpsRealtimeStockRtMinHealthResponse {
  display_name: string;
  status: string;
  enabled: boolean;
  configured_freqs: string[];
  supported_freqs: string[];
  page_polling_enabled: boolean;
  recommended_poll_interval_seconds: number;
  items: OpsRealtimeStockRtMinHealthItem[];
}
