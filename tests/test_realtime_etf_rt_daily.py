from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from src.foundation.realtime import InMemoryRealtimeStateStore
from src.foundation.realtime.constants import ETF_RT_DAILY_SOURCE_API_NAME
from src.foundation.realtime.etf_rt_daily import (
    ETF_RT_DAILY_FIELDS,
    EtfRtDailyCollector,
    EtfRtDailyFetchResult,
    TushareEtfRtDailyProvider,
    normalize_etf_rt_daily_rows,
)
from tests.realtime_runtime_config_helpers import make_realtime_runtime_config


CN_TIMEZONE = ZoneInfo("Asia/Shanghai")


class RecordingTushareClient:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def call(self, api_name: str, *, params: dict, fields: tuple[str, ...]) -> list[dict]:
        self.calls.append({"api_name": api_name, "params": params, "fields": fields})
        return [
            {
                "ts_code": "510300.SH" if params["ts_code"] == "5*.SH" else "159915.SZ",
                "trade_time": "2026-06-18 10:15:00",
                "close": 1.23,
            }
        ]


class FakeClock:
    def __init__(self, collection_status: str = "open") -> None:
        self.collection_status = collection_status

    def resolve(self, *_args, **_kwargs):
        return SimpleNamespace(
            collection_status=self.collection_status,
            is_trading_day=True,
            collection_sessions=["09:30-11:30", "13:00-15:00"],
        )


class FakeEtfProvider:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail

    def fetch_all_market(self) -> EtfRtDailyFetchResult:
        if self.fail:
            raise RuntimeError("SZ segment failed")
        return EtfRtDailyFetchResult(
            rows=[
                {"ts_code": "510300.SH", "trade_time": "2026-06-18 10:15:00", "close": 1.23, "request_segment": "SH"},
                {"ts_code": "159915.SZ", "trade_time": "2026-06-18 10:15:00", "close": 2.34, "request_segment": "SZ"},
            ],
            source_elapsed_ms=12.5,
            request_segments=(
                {"market": "SH", "topic": "HQ_FND_TICK", "ts_code": "5*.SH"},
                {"market": "SZ", "topic": "", "ts_code": "1*.SZ"},
            ),
            segment_counts={"SH": 1, "SZ": 1},
        )


def test_etf_rt_daily_provider_requests_two_segments_with_explicit_fields() -> None:
    config = make_realtime_runtime_config().etf_rt_daily
    client = RecordingTushareClient()
    provider = TushareEtfRtDailyProvider(client=client, config=config)  # type: ignore[arg-type]

    result = provider.fetch_all_market()

    assert result.segment_counts == {"SH": 1, "SZ": 1}
    assert [row["request_segment"] for row in result.rows] == ["SH", "SZ"]
    assert client.calls == [
        {
            "api_name": ETF_RT_DAILY_SOURCE_API_NAME,
            "params": {"ts_code": "5*.SH", "topic": "HQ_FND_TICK"},
            "fields": ETF_RT_DAILY_FIELDS,
        },
        {
            "api_name": ETF_RT_DAILY_SOURCE_API_NAME,
            "params": {"ts_code": "1*.SZ", "topic": ""},
            "fields": ETF_RT_DAILY_FIELDS,
        },
    ]


def test_normalize_etf_rt_daily_rows_keeps_source_trade_time_and_counts_missing_ts_code() -> None:
    result = normalize_etf_rt_daily_rows(
        [
            {"ts_code": "510300.SH", "trade_time": "2026-06-16 15:00:00", "close": 1.23, "request_segment": "SH"},
            {"ts_code": "", "trade_time": "2026-06-18 10:15:00", "request_segment": "SZ"},
        ],
        received_at=datetime(2026, 6, 18, 10, 15, tzinfo=CN_TIMEZONE),
    )

    assert result.invalid_count == 1
    assert result.invalid_reason_counts == {"missing_ts_code": 1}
    assert len(result.snapshots) == 1
    snapshot = result.snapshots[0]
    assert snapshot["ts_code"] == "510300.SH"
    assert snapshot["trade_time"] == "2026-06-16 15:00:00"
    assert snapshot["request_segment"] == "SH"
    assert snapshot["source"] == "tushare"
    assert snapshot["source_api_name"] == "rt_etf_k"
    assert snapshot["raw_payload_hash"]


def test_etf_rt_daily_collector_publishes_one_batch_after_all_segments_succeed() -> None:
    config = make_realtime_runtime_config(etf={"enabled": True}).etf_rt_daily
    store = InMemoryRealtimeStateStore()
    now_values = iter(
        [
            datetime(2026, 6, 18, 10, 15, tzinfo=CN_TIMEZONE) + timedelta(seconds=index)
            for index in range(10)
        ]
    )
    collector = EtfRtDailyCollector(
        store=store,
        provider=FakeEtfProvider(),  # type: ignore[arg-type]
        config=config,
        clock=FakeClock(),  # type: ignore[arg-type]
        now_provider=lambda: next(now_values),
        collector_id="collector-a",
    )

    result = collector.run_cycle(None)  # type: ignore[arg-type]

    assert result.status == "ok"
    assert result.snapshot_count == 2
    assert result.segment_counts == {"SH": 1, "SZ": 1}
    assert store.get_current_batch_id(config.feed_key) == result.batch_id
    assert store.get_batch_meta(config.feed_key, result.batch_id or "")["segment_counts"] == {"SH": 1, "SZ": 1}
    health = store.get_health(config.feed_key) or {}
    assert health["status"] == "ok"
    assert health["request_count_last_minute"] == 2


def test_etf_rt_daily_collector_does_not_publish_when_any_segment_fails() -> None:
    config = make_realtime_runtime_config(etf={"enabled": True}).etf_rt_daily
    store = InMemoryRealtimeStateStore()
    collector = EtfRtDailyCollector(
        store=store,
        provider=FakeEtfProvider(fail=True),  # type: ignore[arg-type]
        config=config,
        clock=FakeClock(),  # type: ignore[arg-type]
        now_provider=lambda: datetime(2026, 6, 18, 10, 15, tzinfo=CN_TIMEZONE),
        collector_id="collector-a",
    )

    result = collector.run_cycle(None)  # type: ignore[arg-type]

    assert result.status == "degraded"
    assert store.get_current_batch_id(config.feed_key) is None
    health = store.get_health(config.feed_key) or {}
    assert health["status"] == "degraded"
    assert "SZ segment failed" in health["last_error_message"]
