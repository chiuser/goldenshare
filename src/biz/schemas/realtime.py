from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class StockRtDailySnapshotItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    ts_code: str
    name: str | None = None
    trade_time: str | None = None
    close: str | None = None
    open: str | None = None
    high: str | None = None
    low: str | None = None
    pre_close: str | None = None
    vol: str | None = None
    amount: str | None = None
    num: str | None = None
    bid_price1: str | None = None
    bid_volume1: str | None = None
    ask_price1: str | None = None
    ask_volume1: str | None = None
    received_at: str | None = None


class StockRtDailySnapshotResponse(BaseModel):
    feed_key: str
    batch_id: str
    received_at: str | None = None
    published_at: str | None = None
    stale: bool
    stale_after_seconds: int
    collection_status: str
    items: list[StockRtDailySnapshotItem]
    missing_ts_codes: list[str]


class StockRtMinSnapshotItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    ts_code: str
    freq: str
    time: str
    open: str | None = None
    close: str | None = None
    high: str | None = None
    low: str | None = None
    vol: str | None = None
    amount: str | None = None
    source: str | None = None
    source_api_name: str | None = None
    received_at: str | None = None


class StockRtMinSnapshotResponse(BaseModel):
    feed_key: str
    freq: str
    batch_id: str
    received_at: str | None = None
    published_at: str | None = None
    stale: bool
    stale_after_seconds: int
    collection_status: str
    items: list[StockRtMinSnapshotItem]
    missing_ts_codes: list[str]
