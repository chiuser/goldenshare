from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from src.foundation.dao.etf_basic_dao import EtfBasicDAO
from src.foundation.models.core.etf_basic import EtfBasic
from src.foundation.models.raw.raw_etf_share_size import RawEtfShareSize
from src.ops.models.ops.etf_realtime_alert import EtfRealtimeAlert
from src.ops.models.ops.etf_realtime_monitor_pool import EtfRealtimeMonitorPool
from src.ops.models.ops.etf_realtime_monitor_rule import EtfRealtimeMonitorRule
from src.ops.models.ops.etf_series_active import EtfSeriesActive


def _login_headers(
    app_client, user_factory, *, username: str = "admin", is_admin: bool = True
) -> dict[str, str]:
    user_factory(username=username, password="secret", is_admin=is_admin)
    login = app_client.post(
        "/api/v1/auth/login", json={"username": username, "password": "secret"}
    )
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['token']}"}


CN_TIMEZONE = ZoneInfo("Asia/Shanghai")


def _seed_requestable_etf(
    db_session,
    ts_code: str = "510300.SH",
    *,
    csname: str = "沪深300ETF",
) -> None:
    db_session.add(
        EtfBasic(
            ts_code=ts_code,
            csname=csname,
            extname="华泰柏瑞沪深300ETF",
            exchange=ts_code.rsplit(".", maxsplit=1)[-1],
            etf_type="宽基",
            list_date=date(2012, 5, 28),
            list_status="L",
        )
    )
    db_session.commit()


def _seed_legacy_active_etf(db_session, ts_code: str) -> None:
    db_session.add(
        EtfSeriesActive(
            resource="etf_rt_daily",
            ts_code=ts_code,
            first_seen_date=date(2026, 6, 17),
            last_seen_date=date(2026, 6, 17),
            last_checked_at=datetime(2026, 6, 17, tzinfo=timezone.utc),
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


def test_etf_realtime_monitor_eligible_etfs_and_pool_crud(
    app_client, user_factory, db_session
) -> None:
    _seed_requestable_etf(db_session)
    headers = _login_headers(app_client, user_factory)

    eligible_response = app_client.get(
        "/api/v1/ops/realtime/etf-monitor/eligible-etfs?keyword=沪深&page=1&page_size=50",
        headers=headers,
    )
    assert eligible_response.status_code == 200
    assert eligible_response.json()["total"] == 1
    assert eligible_response.json()["items"][0]["in_monitor_pool"] is False
    assert eligible_response.json()["items"][0]["size_trade_date"] is None
    assert eligible_response.json()["items"][0]["total_share_wan"] is None
    assert eligible_response.json()["items"][0]["total_size_wan"] is None

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

    pool_response = app_client.get(
        "/api/v1/ops/realtime/etf-monitor/pool", headers=headers
    )
    assert pool_response.status_code == 200
    assert pool_response.json()["total"] == 1
    assert pool_response.json()["items"][0]["etf_name"] == "沪深300ETF"
    assert pool_response.json()["items"][0]["size_trade_date"] is None
    assert pool_response.json()["items"][0]["total_share_wan"] is None
    assert pool_response.json()["items"][0]["total_size_wan"] is None

    update_response = app_client.put(
        f"/api/v1/ops/realtime/etf-monitor/pool/{item_id}",
        headers=headers,
        json={
            "group_key": "theme",
            "group_name": "主题ETF",
            "enabled": False,
            "note": None,
        },
    )
    assert update_response.status_code == 200

    delete_response = app_client.delete(
        f"/api/v1/ops/realtime/etf-monitor/pool/{item_id}", headers=headers
    )
    assert delete_response.status_code == 200


def test_etf_realtime_monitor_pool_rejects_retired_display_order(
    app_client, user_factory, db_session
) -> None:
    _seed_requestable_etf(db_session)
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
    _seed_requestable_etf(db_session, "510300.SH", csname="沪深300ETF")
    _seed_requestable_etf(db_session, "510500.SH", csname="中证500ETF")
    _seed_requestable_etf(db_session, "159915.SZ", csname="创业板ETF")
    _seed_requestable_etf(db_session, "159916.SZ", csname="新能源ETF")

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

    eligible_page_one = app_client.get(
        "/api/v1/ops/realtime/etf-monitor/eligible-etfs?page=1&page_size=2",
        headers=headers,
    )
    eligible_page_two = app_client.get(
        "/api/v1/ops/realtime/etf-monitor/eligible-etfs?page=2&page_size=2",
        headers=headers,
    )
    assert eligible_page_one.status_code == 200
    assert eligible_page_two.status_code == 200
    assert eligible_page_one.json()["total"] == 4
    assert [item["ts_code"] for item in eligible_page_one.json()["items"]] == [
        "159915.SZ",
        "510300.SH",
    ]
    assert [item["ts_code"] for item in eligible_page_two.json()["items"]] == [
        "510500.SH",
        "159916.SZ",
    ]
    latest_item = eligible_page_one.json()["items"][1]
    assert latest_item["size_trade_date"] == "2026-08-21"
    assert Decimal(latest_item["total_share_wan"]) == Decimal("300")
    assert Decimal(latest_item["total_size_wan"]) == Decimal("300")
    assert eligible_page_two.json()["items"][1]["total_size_wan"] is None

    pool_response = app_client.get(
        "/api/v1/ops/realtime/etf-monitor/pool", headers=headers
    )
    assert pool_response.status_code == 200
    assert [item["ts_code"] for item in pool_response.json()["items"]] == [
        "510300.SH",
        "510500.SH",
        "159915.SZ",
    ]


def test_etf_realtime_monitor_pool_rejects_non_requestable_etf_even_when_disabled(
    app_client,
    user_factory,
    db_session,
) -> None:
    headers = _login_headers(app_client, user_factory)

    response = app_client.post(
        "/api/v1/ops/realtime/etf-monitor/pool",
        headers=headers,
        json={
            "ts_code": "510300.SH",
            "group_key": "broad_base",
            "group_name": "宽基ETF",
            "enabled": False,
            "note": None,
        },
    )

    assert response.status_code == 422
    assert response.json()["code"] == "invalid_etf"
    assert response.json()["message"] == "ETF 当前不满足可请求条件"
    assert db_session.query(EtfRealtimeMonitorPool).count() == 0


def test_etf_realtime_monitor_eligible_candidates_apply_basic_contract_once_and_do_not_fallback(
    app_client,
    user_factory,
    db_session,
    mocker,
) -> None:
    today = datetime.now(CN_TIMEZONE).date()
    rows = [
        EtfBasic(
            ts_code="510300.SH",
            csname="沪深300ETF",
            list_date=date(2012, 5, 28),
            list_status="L",
            exchange="SH",
        ),
        EtfBasic(
            ts_code="159915.SZ",
            csname="创业板ETF",
            list_date=date(2011, 12, 9),
            list_status="L",
            exchange="SZ",
        ),
        EtfBasic(
            ts_code="510001.SH",
            csname="待上市",
            list_date=date(2020, 1, 1),
            list_status="P",
            exchange="SH",
        ),
        EtfBasic(
            ts_code="510002.SH",
            csname="已退市",
            list_date=date(2020, 1, 1),
            list_status="D",
            exchange="SH",
        ),
        EtfBasic(
            ts_code="510003.SH",
            csname="缺上市日",
            list_date=None,
            list_status="L",
            exchange="SH",
        ),
        EtfBasic(
            ts_code="510004.SH",
            csname="未来上市",
            list_date=today + timedelta(days=1),
            list_status="L",
            exchange="SH",
        ),
        EtfBasic(
            ts_code="100000.OF",
            csname="场外份额",
            list_date=date(2020, 1, 1),
            list_status="L",
            exchange="OF",
        ),
        EtfBasic(
            ts_code="510005.SH",
            csname="交易所冲突",
            list_date=date(2020, 1, 1),
            list_status="L",
            exchange="SZ",
        ),
    ]
    db_session.add_all(rows)
    db_session.commit()
    _seed_legacy_active_etf(db_session, "510001.SH")
    _seed_legacy_active_etf(db_session, "588888.SH")
    calls: list[tuple[date, str | None]] = []
    original_subquery = EtfBasicDAO.requestable_targets_subquery

    def tracked_subquery(
        self: EtfBasicDAO, *, as_of_date: date, exchange: str | None = None
    ):
        calls.append((as_of_date, exchange))
        return original_subquery(self, as_of_date=as_of_date, exchange=exchange)

    mocker.patch.object(EtfBasicDAO, "requestable_targets_subquery", tracked_subquery)
    headers = _login_headers(app_client, user_factory)

    response = app_client.get(
        "/api/v1/ops/realtime/etf-monitor/eligible-etfs?page=1&page_size=50",
        headers=headers,
    )
    retired_response = app_client.get(
        "/api/v1/ops/realtime/etf-monitor/active-etfs?page=1&page_size=50",
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["total"] == 2
    assert [item["ts_code"] for item in response.json()["items"]] == [
        "159915.SZ",
        "510300.SH",
    ]
    assert calls == [(today, None)]
    assert retired_response.status_code == 404


def test_etf_realtime_monitor_eligible_candidates_return_empty_page_without_legacy_fallback(
    app_client,
    user_factory,
    db_session,
) -> None:
    _seed_legacy_active_etf(db_session, "588888.SH")
    headers = _login_headers(app_client, user_factory)

    response = app_client.get(
        "/api/v1/ops/realtime/etf-monitor/eligible-etfs?page=1&page_size=50",
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json() == {"items": [], "page": 1, "page_size": 50, "total": 0}


def test_etf_realtime_monitor_eligible_candidates_selector_failure_does_not_fallback(
    app_client,
    user_factory,
    db_session,
    mocker,
) -> None:
    _seed_legacy_active_etf(db_session, "588888.SH")
    mocker.patch.object(
        EtfBasicDAO,
        "requestable_targets_subquery",
        side_effect=RuntimeError("selector failed"),
    )
    headers = _login_headers(app_client, user_factory)

    with pytest.raises(RuntimeError, match="selector failed"):
        app_client.get(
            "/api/v1/ops/realtime/etf-monitor/eligible-etfs?page=1&page_size=50",
            headers=headers,
        )


def test_etf_realtime_monitor_pool_revalidates_only_when_reenabling(
    app_client,
    user_factory,
    db_session,
) -> None:
    _seed_requestable_etf(db_session)
    _seed_requestable_etf(db_session, "510500.SH", csname="中证500ETF")
    headers = _login_headers(app_client, user_factory)
    disabled_id = app_client.post(
        "/api/v1/ops/realtime/etf-monitor/pool",
        headers=headers,
        json={
            "ts_code": "510300.SH",
            "group_key": "broad_base",
            "group_name": "宽基ETF",
            "enabled": False,
            "note": None,
        },
    ).json()["id"]
    enabled_id = app_client.post(
        "/api/v1/ops/realtime/etf-monitor/pool",
        headers=headers,
        json={
            "ts_code": "510500.SH",
            "group_key": "broad_base",
            "group_name": "宽基ETF",
            "enabled": True,
            "note": None,
        },
    ).json()["id"]
    disabled_basic = db_session.get(EtfBasic, "510300.SH")
    enabled_basic = db_session.get(EtfBasic, "510500.SH")
    assert disabled_basic is not None
    assert enabled_basic is not None
    disabled_basic.list_status = "P"
    enabled_basic.list_status = "P"
    db_session.commit()

    disabled_edit = app_client.put(
        f"/api/v1/ops/realtime/etf-monitor/pool/{disabled_id}",
        headers=headers,
        json={
            "group_key": "theme",
            "group_name": "主题ETF",
            "enabled": False,
            "note": "继续停用",
        },
    )
    rejected_reenable = app_client.put(
        f"/api/v1/ops/realtime/etf-monitor/pool/{disabled_id}",
        headers=headers,
        json={
            "group_key": "theme",
            "group_name": "主题ETF",
            "enabled": True,
            "note": "尝试启用",
        },
    )
    enabled_edit = app_client.put(
        f"/api/v1/ops/realtime/etf-monitor/pool/{enabled_id}",
        headers=headers,
        json={
            "group_key": "theme",
            "group_name": "主题ETF",
            "enabled": True,
            "note": "保持启用",
        },
    )

    assert disabled_edit.status_code == 200
    assert rejected_reenable.status_code == 422
    assert rejected_reenable.json()["code"] == "invalid_etf"
    assert enabled_edit.status_code == 200
    db_session.expire_all()
    disabled_item = db_session.get(EtfRealtimeMonitorPool, disabled_id)
    enabled_item = db_session.get(EtfRealtimeMonitorPool, enabled_id)
    assert (
        disabled_item is not None
        and disabled_item.enabled is False
        and disabled_item.note == "继续停用"
    )
    assert (
        enabled_item is not None
        and enabled_item.enabled is True
        and enabled_item.note == "保持启用"
    )


def test_etf_realtime_monitor_default_rules_are_explicit_action(
    app_client, user_factory
) -> None:
    headers = _login_headers(app_client, user_factory)

    rules_before = app_client.get(
        "/api/v1/ops/realtime/etf-monitor/rules", headers=headers
    )
    assert rules_before.status_code == 200
    assert rules_before.json()["total"] == 0

    create_response = app_client.post(
        "/api/v1/ops/realtime/etf-monitor/rules/default-global", headers=headers
    )
    assert create_response.status_code == 200
    assert create_response.json() == {"created": 3, "skipped": 0}

    rules_after = app_client.get(
        "/api/v1/ops/realtime/etf-monitor/rules", headers=headers
    )
    assert rules_after.status_code == 200
    assert sorted(item["window_minutes"] for item in rules_after.json()["items"]) == [
        1,
        5,
        15,
    ]


def test_etf_realtime_monitor_etf_rules_require_pool_membership_and_current_requestability(
    app_client,
    user_factory,
    db_session,
) -> None:
    _seed_requestable_etf(db_session)
    _seed_requestable_etf(db_session, "159915.SZ", csname="创业板ETF")
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
                group_key="theme",
                group_name="主题ETF",
                enabled=True,
            ),
        ]
    )
    db_session.commit()
    headers = _login_headers(app_client, user_factory)

    def rule_payload(
        scope_type: str,
        scope_key: str,
        *,
        observe_ratio: int = 2,
        enabled: bool = True,
    ) -> dict[str, object]:
        return {
            "scope_type": scope_type,
            "scope_key": scope_key,
            "window_minutes": 1,
            "observe_ratio": observe_ratio,
            "alert_ratio": 3,
            "strong_ratio": 5,
            "cooldown_minutes": 15,
            "feishu_enabled": True,
            "enabled": enabled,
        }

    created = app_client.post(
        "/api/v1/ops/realtime/etf-monitor/rules",
        headers=headers,
        json=rule_payload("etf", "510300.SH"),
    )
    not_in_pool = app_client.post(
        "/api/v1/ops/realtime/etf-monitor/rules",
        headers=headers,
        json=rule_payload("etf", "159915.SZ"),
    )
    ineligible_pool_member = app_client.post(
        "/api/v1/ops/realtime/etf-monitor/rules",
        headers=headers,
        json=rule_payload("etf", "510500.SH", enabled=False),
    )
    group_rule = app_client.post(
        "/api/v1/ops/realtime/etf-monitor/rules",
        headers=headers,
        json=rule_payload("group", "theme"),
    )

    assert created.status_code == 200
    assert not_in_pool.status_code == 422
    assert not_in_pool.json()["code"] == "invalid_scope"
    assert ineligible_pool_member.status_code == 422
    assert ineligible_pool_member.json()["code"] == "invalid_scope"
    assert group_rule.status_code == 200

    etf_basic = db_session.get(EtfBasic, "510300.SH")
    assert etf_basic is not None
    etf_basic.list_status = "P"
    db_session.commit()
    update = app_client.put(
        f"/api/v1/ops/realtime/etf-monitor/rules/{created.json()['id']}",
        headers=headers,
        json=rule_payload("etf", "510300.SH", observe_ratio=1),
    )

    assert update.status_code == 422
    assert update.json()["code"] == "invalid_scope"
    db_session.expire_all()
    persisted_rule = db_session.get(EtfRealtimeMonitorRule, created.json()["id"])
    assert persisted_rule is not None
    assert persisted_rule.observe_ratio == Decimal("2")


def test_etf_realtime_monitor_alerts_summary_and_invalid_window(
    app_client, user_factory, db_session
) -> None:
    _seed_requestable_etf(db_session)
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

    summary = app_client.get(
        "/api/v1/ops/realtime/etf-monitor/summary?trade_date=2026-08-22",
        headers=headers,
    )
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
