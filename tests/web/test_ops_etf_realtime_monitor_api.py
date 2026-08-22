from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from src.foundation.models.core.etf_basic import EtfBasic
from src.foundation.models.raw.raw_etf_share_size import RawEtfShareSize
from src.ops.models.ops.etf_realtime_alert import EtfRealtimeAlert
from src.ops.models.ops.etf_realtime_monitor_pool import EtfRealtimeMonitorPool
from src.ops.models.ops.etf_series_active import EtfSeriesActive


def _login_headers(app_client, user_factory, *, username: str = "admin", is_admin: bool = True) -> dict[str, str]:
    user_factory(username=username, password="secret", is_admin=is_admin)
    login = app_client.post("/api/v1/auth/login", json={"username": username, "password": "secret"})
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['token']}"}


def _seed_active_etf(
    db_session,
    ts_code: str = "510300.SH",
    *,
    csname: str = "沪深300ETF",
) -> None:
    db_session.add(
        EtfSeriesActive(
            resource="etf_rt_daily",
            ts_code=ts_code,
            first_seen_date=date(2026, 6, 17),
            last_seen_date=date(2026, 6, 17),
            last_checked_at=datetime(2026, 6, 17, tzinfo=timezone.utc),
        )
    )
    db_session.add(
        EtfBasic(
            ts_code=ts_code,
            csname=csname,
            extname="华泰柏瑞沪深300ETF",
            exchange="SH",
            etf_type="宽基",
            list_date=date(2012, 5, 28),
            list_status="L",
        )
    )
    db_session.commit()


def _seed_etf_share_size(
    db_session,
    *,
    trade_date: date,
    ts_code: str,
    total_share: Decimal | None,
    total_size: Decimal | None,
) -> None:
    db_session.add(
        RawEtfShareSize(
            trade_date=trade_date,
            ts_code=ts_code,
            etf_name=ts_code,
            total_share=total_share,
            total_size=total_size,
            nav=Decimal("1"),
        close=Decimal("1"),
        exchange=ts_code.split(".")[-1],
        api_name="etf_share_size",
        fetched_at=datetime.now(timezone.utc),
    )
    )


def test_etf_realtime_monitor_api_rejects_non_admin(app_client, user_factory) -> None:
    headers = _login_headers(app_client, user_factory, username="user", is_admin=False)

    response = app_client.get("/api/v1/ops/realtime/etf-monitor/pool", headers=headers)

    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"


def test_etf_realtime_monitor_active_etfs_and_pool_crud(app_client, user_factory, db_session) -> None:
    _seed_active_etf(db_session)
    headers = _login_headers(app_client, user_factory)

    active_response = app_client.get("/api/v1/ops/realtime/etf-monitor/active-etfs?keyword=沪深&page=1&page_size=50", headers=headers)
    assert active_response.status_code == 200
    assert active_response.json()["total"] == 1
    assert active_response.json()["items"][0]["in_monitor_pool"] is False
    assert active_response.json()["items"][0]["size_trade_date"] is None
    assert active_response.json()["items"][0]["total_share_wan"] is None
    assert active_response.json()["items"][0]["total_size_wan"] is None

    create_response = app_client.post(
        "/api/v1/ops/realtime/etf-monitor/pool",
        headers=headers,
        json={
            "ts_code": "510300.SH",
            "group_key": "broad_base",
            "group_name": "宽基ETF",
            "enabled": True,
            "note": "沪深300代表",
        },
    )
    assert create_response.status_code == 200
    item_id = create_response.json()["id"]

    pool_response = app_client.get("/api/v1/ops/realtime/etf-monitor/pool", headers=headers)
    assert pool_response.status_code == 200
    assert pool_response.json()["total"] == 1
    assert pool_response.json()["items"][0]["etf_name"] == "沪深300ETF"
    assert pool_response.json()["items"][0]["size_trade_date"] is None
    assert pool_response.json()["items"][0]["total_share_wan"] is None
    assert pool_response.json()["items"][0]["total_size_wan"] is None

    update_response = app_client.put(
        f"/api/v1/ops/realtime/etf-monitor/pool/{item_id}",
        headers=headers,
        json={"group_key": "theme", "group_name": "主题ETF", "enabled": False, "note": None},
    )
    assert update_response.status_code == 200

    delete_response = app_client.delete(f"/api/v1/ops/realtime/etf-monitor/pool/{item_id}", headers=headers)
    assert delete_response.status_code == 200


def test_etf_realtime_monitor_pool_rejects_retired_display_order(app_client, user_factory, db_session) -> None:
    _seed_active_etf(db_session)
    headers = _login_headers(app_client, user_factory)

    response = app_client.post(
        "/api/v1/ops/realtime/etf-monitor/pool",
        headers=headers,
        json={
            "ts_code": "510300.SH",
            "group_key": "broad_base",
            "group_name": "宽基ETF",
            "enabled": True,
            "display_order": 0,
        },
    )

    assert response.status_code == 422
    assert db_session.query(EtfRealtimeMonitorPool).count() == 0


def test_etf_realtime_monitor_lists_use_global_latest_share_size_snapshot_and_sorting(
    app_client,
    user_factory,
    db_session,
) -> None:
    _seed_active_etf(db_session, "510300.SH", csname="沪深300ETF")
    _seed_active_etf(db_session, "510500.SH", csname="中证500ETF")
    _seed_active_etf(db_session, "159915.SZ", csname="创业板ETF")
    _seed_active_etf(db_session, "159916.SZ", csname="新能源ETF")

    latest_trade_date = date(2026, 8, 21)
    _seed_etf_share_size(
        db_session,
        trade_date=date(2026, 8, 20),
        ts_code="510300.SH",
        total_share=Decimal("99999"),
        total_size=Decimal("99999"),
    )
    _seed_etf_share_size(
        db_session,
        trade_date=latest_trade_date,
        ts_code="510300.SH",
        total_share=Decimal("300"),
        total_size=Decimal("300"),
    )
    _seed_etf_share_size(
        db_session,
        trade_date=latest_trade_date,
        ts_code="510500.SH",
        total_share=Decimal("300"),
        total_size=Decimal("300"),
    )
    _seed_etf_share_size(
        db_session,
        trade_date=latest_trade_date,
        ts_code="159915.SZ",
        total_share=Decimal("9000000"),
        total_size=Decimal("9000000"),
    )
    _seed_etf_share_size(
        db_session,
        trade_date=latest_trade_date,
        ts_code="159916.SZ",
        total_share=Decimal("400"),
        total_size=None,
    )
    db_session.add_all(
        [
            EtfRealtimeMonitorPool(
                ts_code="510300.SH",
                group_key="broad_base",
                group_name="宽基ETF",
                enabled=True,
            ),
            EtfRealtimeMonitorPool(
                ts_code="510500.SH",
                group_key="broad_base",
                group_name="宽基ETF",
                enabled=True,
            ),
            EtfRealtimeMonitorPool(
                ts_code="159915.SZ",
                group_key="theme",
                group_name="主题ETF",
                enabled=True,
            ),
        ]
    )
    db_session.commit()
    headers = _login_headers(app_client, user_factory)

    active_page_one = app_client.get(
        "/api/v1/ops/realtime/etf-monitor/active-etfs?page=1&page_size=2",
        headers=headers,
    )
    active_page_two = app_client.get(
        "/api/v1/ops/realtime/etf-monitor/active-etfs?page=2&page_size=2",
        headers=headers,
    )
    assert active_page_one.status_code == 200
    assert active_page_two.status_code == 200
    assert active_page_one.json()["total"] == 4
    assert [item["ts_code"] for item in active_page_one.json()["items"]] == ["159915.SZ", "510300.SH"]
    assert [item["ts_code"] for item in active_page_two.json()["items"]] == ["510500.SH", "159916.SZ"]
    latest_item = active_page_one.json()["items"][1]
    assert latest_item["size_trade_date"] == "2026-08-21"
    assert Decimal(latest_item["total_share_wan"]) == Decimal("300")
    assert Decimal(latest_item["total_size_wan"]) == Decimal("300")
    assert active_page_two.json()["items"][1]["total_size_wan"] is None

    pool_response = app_client.get("/api/v1/ops/realtime/etf-monitor/pool", headers=headers)
    assert pool_response.status_code == 200
    assert [item["ts_code"] for item in pool_response.json()["items"]] == [
        "510300.SH",
        "510500.SH",
        "159915.SZ",
    ]


def test_etf_realtime_monitor_pool_rejects_non_active_etf(app_client, user_factory) -> None:
    headers = _login_headers(app_client, user_factory)

    response = app_client.post(
        "/api/v1/ops/realtime/etf-monitor/pool",
        headers=headers,
        json={
            "ts_code": "510300.SH",
            "group_key": "broad_base",
            "group_name": "宽基ETF",
            "enabled": True,
            "note": None,
        },
    )

    assert response.status_code == 422
    assert response.json()["code"] == "invalid_etf"


def test_etf_realtime_monitor_default_rules_are_explicit_action(app_client, user_factory) -> None:
    headers = _login_headers(app_client, user_factory)

    rules_before = app_client.get("/api/v1/ops/realtime/etf-monitor/rules", headers=headers)
    assert rules_before.status_code == 200
    assert rules_before.json()["total"] == 0

    create_response = app_client.post("/api/v1/ops/realtime/etf-monitor/rules/default-global", headers=headers)
    assert create_response.status_code == 200
    assert create_response.json() == {"created": 3, "skipped": 0}

    rules_after = app_client.get("/api/v1/ops/realtime/etf-monitor/rules", headers=headers)
    assert rules_after.status_code == 200
    assert sorted(item["window_minutes"] for item in rules_after.json()["items"]) == [1, 5, 15]


def test_etf_realtime_monitor_alerts_summary_and_invalid_window(app_client, user_factory, db_session) -> None:
    _seed_active_etf(db_session)
    db_session.add(
        EtfRealtimeMonitorPool(
            ts_code="510300.SH",
            group_key="broad_base",
            group_name="宽基ETF",
            enabled=True,
        )
    )
    db_session.add(
        EtfRealtimeAlert(
            trade_date=date(2026, 8, 22),
            triggered_at=datetime(2026, 8, 22, 10, 0, tzinfo=timezone.utc),
            bucket_end_time=datetime.strptime("10:00", "%H:%M").time(),
            window_minutes=1,
            ts_code="510300.SH",
            etf_name="沪深300ETF",
            group_key="broad_base",
            group_name="宽基ETF",
            severity="alert",
            current_amount_yuan=300,
            baseline_amount_yuan=100,
            ratio=3,
            baseline_trade_dates_json=["2026-08-21"],
            cooldown_key="etf_realtime:510300.SH:1:1",
            feishu_status="failed",
            feishu_error="test failure",
        )
    )
    db_session.commit()
    headers = _login_headers(app_client, user_factory)

    alerts = app_client.get(
        "/api/v1/ops/realtime/etf-monitor/alerts?trade_date=2026-08-22&severity=alert&page=1&page_size=50",
        headers=headers,
    )
    assert alerts.status_code == 200
    assert alerts.json()["total"] == 1
    assert alerts.json()["items"][0]["feishu_status"] == "failed"

    summary = app_client.get("/api/v1/ops/realtime/etf-monitor/summary?trade_date=2026-08-22", headers=headers)
    assert summary.status_code == 200
    assert summary.json()["monitor_total"] == 1
    assert summary.json()["alert_count"] == 1
    assert summary.json()["feishu_failed_count"] == 1

    invalid_window = app_client.post(
        "/api/v1/ops/realtime/etf-monitor/rules",
        headers=headers,
        json={
            "scope_type": "global",
            "scope_key": "__GLOBAL__",
            "window_minutes": 2,
            "observe_ratio": 2,
            "alert_ratio": 3,
            "strong_ratio": 5,
            "cooldown_minutes": 15,
            "feishu_enabled": True,
            "enabled": True,
        },
    )
    assert invalid_window.status_code == 422
    assert invalid_window.json()["code"] == "invalid_window"
