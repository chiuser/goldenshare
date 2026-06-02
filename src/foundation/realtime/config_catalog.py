from __future__ import annotations

from dataclasses import dataclass

from src.foundation.realtime.constants import (
    STOCK_RT_DAILY_DISPLAY_NAME,
    STOCK_RT_DAILY_FEED_KEY,
    STOCK_RT_DAILY_SOURCE_API_NAME,
    STOCK_RT_MIN_DISPLAY_NAME,
    STOCK_RT_MIN_SOURCE_API_NAME,
)


STOCK_RT_DAILY_OBJECT_KEY = "stock_rt_daily"
STOCK_RT_MIN_OBJECT_KEY = "stock_rt_min"
STOCK_RT_COLLECTION_SESSIONS = "09:30-11:30,13:00-15:00"
STOCK_RT_EXCHANGE = "SSE"
STOCK_RT_TS_CODE_PATTERN = "3*.SZ,6*.SH,0*.SZ,9*.BJ"
STOCK_RT_MIN_FEED_KEY_PREFIX = "tushare_stock_rt_min"


@dataclass(frozen=True, slots=True)
class RealtimeConfigCatalogEntry:
    object_key: str
    object_kind: str
    display_name: str
    source_api_name: str
    exchange: str
    collection_sessions: str
    ts_code_pattern: str
    feed_key: str | None = None
    feed_key_prefix: str | None = None


STOCK_RT_DAILY_CATALOG = RealtimeConfigCatalogEntry(
    object_key=STOCK_RT_DAILY_OBJECT_KEY,
    object_kind="collector_feed",
    display_name=STOCK_RT_DAILY_DISPLAY_NAME,
    source_api_name=STOCK_RT_DAILY_SOURCE_API_NAME,
    exchange=STOCK_RT_EXCHANGE,
    collection_sessions=STOCK_RT_COLLECTION_SESSIONS,
    ts_code_pattern=STOCK_RT_TS_CODE_PATTERN,
    feed_key=STOCK_RT_DAILY_FEED_KEY,
)


STOCK_RT_MIN_CATALOG = RealtimeConfigCatalogEntry(
    object_key=STOCK_RT_MIN_OBJECT_KEY,
    object_kind="feed_group",
    display_name=STOCK_RT_MIN_DISPLAY_NAME,
    source_api_name=STOCK_RT_MIN_SOURCE_API_NAME,
    exchange=STOCK_RT_EXCHANGE,
    collection_sessions=STOCK_RT_COLLECTION_SESSIONS,
    ts_code_pattern=STOCK_RT_TS_CODE_PATTERN,
    feed_key_prefix=STOCK_RT_MIN_FEED_KEY_PREFIX,
)
