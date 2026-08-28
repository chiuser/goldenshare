from __future__ import annotations

from pydantic import BaseModel


class OpsRealtimeStockRtDailyHealthResponse(BaseModel):
    feed_key: str
    display_name: str
    status: str
    enabled: bool
    redis_connected: bool
    collector_running: bool
    collector_id: str | None = None
    last_request_at: str | None = None
    last_success_at: str | None = None
    last_error_at: str | None = None
    last_error_message: str | None = None
    current_batch_id: str | None = None
    current_batch_age_seconds: float | None = None
    current_batch_received_at: str | None = None
    current_batch_published_at: str | None = None
    snapshot_count: int
    source_row_count: int
    source_elapsed_ms: float | None = None
    write_elapsed_ms: float | None = None
    request_count_last_minute: int
    max_calls_per_minute: int
    poll_interval_seconds: int
    is_trading_day: bool
    collection_sessions: list[str]
    collection_status: str
    stale_after_seconds: int
    snapshot_ttl_seconds: int
    keep_recent_batches: int
    batch_stream_maxlen: int
    delta_stream_maxlen: int
    last_batch_event_id: str | None = None
    last_delta_event_id: str | None = None
    delta_count_last_batch: int
    page_polling_enabled: bool
    recommended_poll_interval_seconds: int


class OpsRealtimeStockRtMinHealthItem(BaseModel):
    freq: str
    feed_key: str
    status: str
    enabled: bool
    redis_connected: bool
    collector_running: bool
    collector_id: str | None = None
    last_request_at: str | None = None
    last_success_at: str | None = None
    last_error_at: str | None = None
    last_error_message: str | None = None
    current_batch_id: str | None = None
    current_batch_age_seconds: float | None = None
    current_batch_received_at: str | None = None
    current_batch_published_at: str | None = None
    snapshot_count: int
    source_row_count: int
    source_elapsed_ms: float | None = None
    write_elapsed_ms: float | None = None
    request_count_last_minute: int
    max_calls_per_minute: int
    poll_interval_seconds: int
    is_trading_day: bool
    collection_sessions: list[str]
    collection_status: str
    stale_after_seconds: int
    snapshot_ttl_seconds: int
    keep_recent_batches: int
    batch_stream_maxlen: int
    delta_stream_maxlen: int
    last_batch_event_id: str | None = None
    last_delta_event_id: str | None = None
    delta_count_last_batch: int
    invalid_count: int
    invalid_reason_counts: dict[str, int]


class OpsRealtimeStockRtMinHealthResponse(BaseModel):
    display_name: str
    status: str
    enabled: bool
    configured_freqs: list[str]
    supported_freqs: list[str]
    page_polling_enabled: bool
    recommended_poll_interval_seconds: int
    items: list[OpsRealtimeStockRtMinHealthItem]


class OpsRealtimeEtfRtDailyHealthResponse(BaseModel):
    feed_key: str
    display_name: str
    status: str
    enabled: bool
    redis_connected: bool
    collector_running: bool
    collector_id: str | None = None
    last_request_at: str | None = None
    last_success_at: str | None = None
    last_error_at: str | None = None
    last_error_message: str | None = None
    current_batch_id: str | None = None
    current_batch_age_seconds: float | None = None
    current_batch_received_at: str | None = None
    current_batch_published_at: str | None = None
    source_snapshot_count: int
    eligible_etf_count: int
    eligible_snapshot_count: int
    snapshot_count: int
    source_row_count: int
    source_elapsed_ms: float | None = None
    write_elapsed_ms: float | None = None
    request_count_last_minute: int
    max_calls_per_minute: int
    poll_interval_seconds: int
    is_trading_day: bool
    collection_sessions: list[str]
    collection_status: str
    stale_after_seconds: int
    snapshot_ttl_seconds: int
    keep_recent_batches: int
    batch_stream_maxlen: int
    delta_stream_maxlen: int
    last_batch_event_id: str | None = None
    last_delta_event_id: str | None = None
    delta_count_last_batch: int
    invalid_count: int
    invalid_reason_counts: dict[str, int]
    segment_counts: dict[str, int]
    page_polling_enabled: bool
    recommended_poll_interval_seconds: int
