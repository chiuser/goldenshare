from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from src.foundation.models.core.etf_basic import EtfBasic
from src.foundation.realtime import InMemoryRealtimeStateStore
from src.ops.models.ops.etf_realtime_alert import EtfRealtimeAlert
from src.ops.models.ops.etf_realtime_minute_stat import EtfRealtimeMinuteStat
from src.ops.models.ops.etf_realtime_monitor_pool import EtfRealtimeMonitorPool
from src.ops.models.ops.etf_realtime_monitor_rule import EtfRealtimeMonitorRule
from src.ops.services.etf_realtime_monitor_service import EtfRealtimeMonitorService


CN_TIMEZONE = ZoneInfo("Asia/Shanghai")
TARGET_DATE = date(2026, 8, 21)
FEED_KEY = "tushare_etf_rt_k"


class RecordingFeishuService:
    def __init__(self, *, error_message: str | None = None, on_send=None) -> None:
        self.error_message = error_message
        self.on_send = on_send
        self.calls: list[int] = []

    def send_alert(self, alert: EtfRealtimeAlert) -> tuple[str | None, str | None]:
        self.calls.append(alert.id)
        if self.on_send is not None:
            self.on_send(alert)
        return (None, self.error_message) if self.error_message else ("message-1", None)


def _seed_monitor_inputs(db_session, *, alert_ratio: str = "3.0", observe_ratio: str = "2.0") -> None:
    db_session.add(
        EtfBasic(
            ts_code="510300.SH",
            csname="沪深300ETF",
            extname="华泰柏瑞沪深300ETF",
            list_status="L",
        )
    )
    db_session.add(
        EtfRealtimeMonitorPool(
            ts_code="510300.SH",
            group_key="broad_base",
            group_name="宽基ETF",
            enabled=True,
        )
    )
    db_session.add(
        EtfRealtimeMonitorRule(
            scope_type="etf",
            scope_key="510300.SH",
            window_minutes=1,
            observe_ratio=Decimal(observe_ratio),
            alert_ratio=Decimal(alert_ratio),
            strong_ratio=Decimal("5.0"),
            cooldown_minutes=15,
            feishu_enabled=True,
            enabled=True,
        )
    )
    for offset in range(1, 6):
        db_session.add(
            EtfRealtimeMinuteStat(
                trade_date=date(2026, 8, 21 - offset),
                minute_bucket=datetime.strptime("09:32", "%H:%M").time(),
                ts_code="510300.SH",
                cumulative_amount_yuan=Decimal("1000"),
                amount_delta_yuan=Decimal("100"),
                cumulative_vol=Decimal("10"),
                vol_delta=Decimal("1"),
                data_quality="ok",
            )
        )
    db_session.commit()


def _seed_current_batches(store: InMemoryRealtimeStateStore, *, ts_codes: tuple[str, ...] = ("510300.SH",)) -> None:
    for batch_id, trade_time, amount in (
        ("b1", "2026-08-21T09:30:00+08:00", "100"),
        ("b2", "2026-08-21T09:31:00+08:00", "400"),
    ):
        store.publish_batch(
            feed_key=FEED_KEY,
            batch_id=batch_id,
            snapshots=[{"ts_code": ts_code, "trade_time": trade_time, "amount": amount, "vol": "10"} for ts_code in ts_codes],
            meta={"published_at": trade_time},
            ttl_seconds=259200,
            keep_recent_batches=260,
            batch_stream_maxlen=5000,
            delta_stream_maxlen=200000,
        )


def test_monitor_commits_alert_before_sending_and_keeps_name_snapshot(db_session) -> None:
    _seed_monitor_inputs(db_session)
    store = InMemoryRealtimeStateStore()
    _seed_current_batches(store)
    def assert_committed_before_send(alert: EtfRealtimeAlert) -> None:
        assert db_session.get(EtfRealtimeAlert, alert.id) is not None

    sender = RecordingFeishuService(on_send=assert_committed_before_send)

    result = EtfRealtimeMonitorService(feishu_service=sender).run_after_etf_batch(
        db_session,
        store=store,
        feed_key=FEED_KEY,
        trade_date=datetime(2026, 8, 21, 9, 32, tzinfo=CN_TIMEZONE),
    )

    assert result.alert_count == 1
    assert result.failed_count == 0
    alert = db_session.query(EtfRealtimeAlert).one()
    assert alert.etf_name == "沪深300ETF"
    assert alert.feishu_status == "success"
    assert sender.calls == [alert.id]


def test_monitor_feishu_failure_is_recorded_without_aborting(db_session) -> None:
    _seed_monitor_inputs(db_session)
    store = InMemoryRealtimeStateStore()
    _seed_current_batches(store)
    sender = RecordingFeishuService(error_message="network down")

    result = EtfRealtimeMonitorService(feishu_service=sender).run_after_etf_batch(
        db_session,
        store=store,
        feed_key=FEED_KEY,
        trade_date=datetime(2026, 8, 21, 9, 32, tzinfo=CN_TIMEZONE),
    )

    assert result.alert_count == 1
    alert = db_session.query(EtfRealtimeAlert).one()
    assert alert.feishu_status == "failed"
    assert alert.feishu_error == "network down"


def test_observe_is_persisted_without_feishu_send(db_session) -> None:
    _seed_monitor_inputs(db_session, alert_ratio="4.0")
    store = InMemoryRealtimeStateStore()
    _seed_current_batches(store)
    sender = RecordingFeishuService()

    result = EtfRealtimeMonitorService(feishu_service=sender).run_after_etf_batch(
        db_session,
        store=store,
        feed_key=FEED_KEY,
        trade_date=datetime(2026, 8, 21, 9, 32, tzinfo=CN_TIMEZONE),
    )

    assert result.alert_count == 1
    alert = db_session.query(EtfRealtimeAlert).one()
    assert alert.severity == "observe"
    assert alert.feishu_status == "skipped"
    assert sender.calls == []


def test_single_metric_failure_does_not_stop_other_metrics(db_session, monkeypatch) -> None:
    _seed_monitor_inputs(db_session)
    db_session.add(
        EtfRealtimeMonitorPool(
            ts_code="159919.SZ",
            group_key="broad_base",
            group_name="宽基ETF",
            enabled=True,
        )
    )
    db_session.add(
        EtfRealtimeMonitorRule(
            scope_type="etf",
            scope_key="159919.SZ",
            window_minutes=1,
            observe_ratio=Decimal("2.0"),
            alert_ratio=Decimal("3.0"),
            strong_ratio=Decimal("5.0"),
            cooldown_minutes=15,
            feishu_enabled=False,
            enabled=True,
        )
    )
    db_session.commit()
    store = InMemoryRealtimeStateStore()
    _seed_current_batches(store, ts_codes=("510300.SH", "159919.SZ"))
    from src.ops.services import etf_realtime_monitor_service as monitor_module

    original_baseline = monitor_module._baseline_amount

    def failing_baseline(session, **kwargs):
        if kwargs["ts_code"] == "159919.SZ":
            raise RuntimeError("synthetic metric failure")
        return original_baseline(session, **kwargs)

    monkeypatch.setattr(monitor_module, "_baseline_amount", failing_baseline)
    result = EtfRealtimeMonitorService(feishu_service=RecordingFeishuService()).run_after_etf_batch(
        db_session,
        store=store,
        feed_key=FEED_KEY,
        trade_date=datetime(2026, 8, 21, 9, 32, tzinfo=CN_TIMEZONE),
    )

    assert result.alert_count == 1
    assert result.failed_count == 1
    assert db_session.query(EtfRealtimeAlert).count() == 1


def test_alert_cooldown_allows_only_severity_upgrade(db_session) -> None:
    _seed_monitor_inputs(db_session)
    for offset in range(1, 6):
        db_session.add(
            EtfRealtimeMinuteStat(
                trade_date=date(2026, 8, 21 - offset),
                minute_bucket=datetime.strptime("09:35", "%H:%M").time(),
                ts_code="510300.SH",
                cumulative_amount_yuan=Decimal("1000"),
                amount_delta_yuan=Decimal("100"),
                cumulative_vol=Decimal("10"),
                vol_delta=Decimal("1"),
                data_quality="ok",
            )
        )
    db_session.commit()
    store = InMemoryRealtimeStateStore()
    _seed_current_batches(store)
    sender = RecordingFeishuService()
    service = EtfRealtimeMonitorService(feishu_service=sender)

    first = service.run_after_etf_batch(
        db_session,
        store=store,
        feed_key=FEED_KEY,
        trade_date=datetime(2026, 8, 21, 9, 32, tzinfo=CN_TIMEZONE),
    )
    assert first.alert_count == 1
    assert db_session.query(EtfRealtimeAlert).one().severity == "alert"

    _publish_upgrade_batches(store)
    second = service.run_after_etf_batch(
        db_session,
        store=store,
        feed_key=FEED_KEY,
        trade_date=datetime(2026, 8, 21, 9, 35, tzinfo=CN_TIMEZONE),
    )
    assert second.alert_count == 1
    assert [item.severity for item in db_session.query(EtfRealtimeAlert).order_by(EtfRealtimeAlert.id).all()] == ["alert", "strong"]
    assert len(sender.calls) == 2


def _publish_upgrade_batches(store: InMemoryRealtimeStateStore) -> None:
    for batch_id, trade_time, amount in (
        ("b3", "2026-08-21T09:33:00+08:00", "100"),
        ("b4", "2026-08-21T09:34:00+08:00", "700"),
    ):
        store.publish_batch(
            feed_key=FEED_KEY,
            batch_id=batch_id,
            snapshots=[{"ts_code": "510300.SH", "trade_time": trade_time, "amount": amount, "vol": "10"}],
            meta={"published_at": trade_time},
            ttl_seconds=259200,
            keep_recent_batches=260,
            batch_stream_maxlen=5000,
            delta_stream_maxlen=200000,
        )
