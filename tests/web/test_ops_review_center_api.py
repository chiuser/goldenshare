from __future__ import annotations

from datetime import date, datetime, timedelta, timezone


def _seed_index_daily_raw_eligibility(
    db_session,
    *,
    ts_code: str,
    trade_dates: list[date],
    include_calendar: bool = True,
) -> None:
    from src.foundation.models.core.trade_calendar import TradeCalendar
    from src.foundation.models.raw.raw_index_daily import RawIndexDaily

    if include_calendar:
        db_session.add_all(
            [
                TradeCalendar(
                    exchange="SSE",
                    trade_date=trade_date,
                    is_open=True,
                    pretrade_date=None,
                )
                for trade_date in trade_dates
            ]
        )
    db_session.add_all(
        [
            RawIndexDaily(
                ts_code=ts_code,
                trade_date=trade_date,
                api_name="index_daily",
                fetched_at=datetime.now(timezone.utc),
            )
            for trade_date in trade_dates
        ]
    )


def test_ops_review_center_requires_admin(app_client, user_factory) -> None:
    user_factory(username="user", password="secret", is_admin=False)
    login = app_client.post("/api/v1/auth/login", json={"username": "user", "password": "secret"})
    token = login.json()["token"]

    response = app_client.get("/api/v1/ops/review/index/active", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"

    etf_response = app_client.get("/api/v1/ops/review/etf/active", headers={"Authorization": f"Bearer {token}"})
    assert etf_response.status_code == 403
    assert etf_response.json()["code"] == "forbidden"


def test_ops_review_index_active_list_supports_keyword_and_page(app_client, user_factory, db_session) -> None:
    from src.ops.models.ops.index_series_active import IndexSeriesActive

    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    db_session.add_all(
        [
            IndexSeriesActive(
                resource="index_daily",
                ts_code="000001.SH",
                first_seen_date=date(2026, 4, 1),
                last_seen_date=date(2026, 4, 15),
                last_checked_at=datetime(2026, 4, 15, 10, 0, tzinfo=timezone.utc),
            ),
            IndexSeriesActive(
                resource="index_daily",
                ts_code="399001.SZ",
                first_seen_date=date(2026, 4, 1),
                last_seen_date=date(2026, 4, 15),
                last_checked_at=datetime(2026, 4, 15, 10, 0, tzinfo=timezone.utc),
            ),
            IndexSeriesActive(
                resource="index_weekly",
                ts_code="000300.SH",
                first_seen_date=date(2026, 4, 1),
                last_seen_date=date(2026, 4, 15),
                last_checked_at=datetime(2026, 4, 15, 10, 0, tzinfo=timezone.utc),
            ),
        ]
    )
    db_session.commit()

    response = app_client.get(
        "/api/v1/ops/review/index/active?resource=index_daily&keyword=399&page=1&page_size=10",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["items"][0]["ts_code"] == "399001.SZ"


def test_ops_review_index_active_list_returns_serving_coverage(app_client, user_factory, db_session) -> None:
    from src.foundation.models.core.index_basic import IndexBasic
    from src.foundation.models.core_serving.index_daily_serving import IndexDailyServing
    from src.foundation.models.core_serving.index_weekly_serving import IndexWeeklyServing
    from src.ops.models.ops.index_series_active import IndexSeriesActive

    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    db_session.add_all(
        [
            IndexBasic(ts_code="000300.SH", name="沪深300", market="SSE", publisher="中证指数"),
            IndexSeriesActive(
                resource="index_daily",
                ts_code="000300.SH",
                first_seen_date=date(2026, 4, 1),
                last_seen_date=date(2026, 4, 15),
                last_checked_at=datetime(2026, 4, 15, 10, 0, tzinfo=timezone.utc),
            ),
            IndexDailyServing(ts_code="000300.SH", trade_date=date(2026, 4, 24), source="api"),
            IndexWeeklyServing(
                ts_code="000300.SH",
                period_start_date=date(2026, 4, 20),
                trade_date=date(2026, 4, 24),
                source="derived_daily",
            ),
        ]
    )
    db_session.commit()

    response = app_client.get(
        "/api/v1/ops/review/index/active?resource=index_daily&page=1&page_size=10",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["index_name"] == "沪深300"
    assert item["market"] == "SSE"
    assert item["publisher"] == "中证指数"
    assert item["data_status"] == "missing_monthly"
    assert item["missing_layers"] == ["monthly"]
    assert item["latest_daily_date"] == "2026-04-24"
    assert item["latest_weekly_date"] == "2026-04-24"
    assert item["latest_monthly_date"] is None


def test_ops_review_index_active_exposes_and_filters_source_serviceability(
    app_client,
    user_factory,
    db_session,
) -> None:
    from src.foundation.models.core.trade_calendar import TradeCalendar
    from src.foundation.models.raw.raw_index_daily import RawIndexDaily
    from src.ops.models.ops.index_series_active import IndexSeriesActive

    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]
    reference_date = date.today() - timedelta(days=1)
    previous_date = reference_date - timedelta(days=1)
    db_session.add_all(
        [
            TradeCalendar(exchange="SSE", trade_date=reference_date, is_open=True, pretrade_date=None),
            TradeCalendar(exchange="SSE", trade_date=previous_date, is_open=True, pretrade_date=None),
            IndexSeriesActive(
                resource="index_daily",
                ts_code="READY.SH",
                first_seen_date=previous_date,
                last_seen_date=reference_date,
                last_checked_at=datetime.now(timezone.utc),
            ),
            IndexSeriesActive(
                resource="index_daily",
                ts_code="DELAY.SH",
                first_seen_date=previous_date,
                last_seen_date=reference_date,
                last_checked_at=datetime.now(timezone.utc),
            ),
            RawIndexDaily(
                ts_code="READY.SH",
                trade_date=reference_date,
                api_name="index_daily",
                fetched_at=datetime.now(timezone.utc),
            ),
            RawIndexDaily(
                ts_code="DELAY.SH",
                trade_date=previous_date,
                api_name="index_daily",
                fetched_at=datetime.now(timezone.utc),
            ),
        ]
    )
    db_session.commit()

    response = app_client.get(
        "/api/v1/ops/review/index/active?resource=index_daily&page=1&page_size=10",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    items_by_code = {item["ts_code"]: item for item in response.json()["items"]}
    assert items_by_code["READY.SH"]["source_serviceability_status"] == "ready"
    assert items_by_code["READY.SH"]["source_serviceability_label"] == "正常"
    assert items_by_code["READY.SH"]["latest_raw_trade_date"] == reference_date.isoformat()
    assert items_by_code["DELAY.SH"]["source_serviceability_status"] == "source_delayed"
    assert items_by_code["DELAY.SH"]["source_serviceability_action"] == "系统将在受控窗口继续补漏"

    filtered_response = app_client.get(
        "/api/v1/ops/review/index/active?resource=index_daily&source_serviceability_status=source_delayed",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert filtered_response.status_code == 200
    assert [item["ts_code"] for item in filtered_response.json()["items"]] == ["DELAY.SH"]


def test_ops_review_index_active_summary_counts_available_layers(app_client, user_factory, db_session) -> None:
    from src.foundation.models.core_serving.index_daily_serving import IndexDailyServing
    from src.foundation.models.core_serving.index_monthly_serving import IndexMonthlyServing
    from src.foundation.models.core_serving.index_weekly_serving import IndexWeeklyServing
    from src.ops.models.ops.index_series_active import IndexSeriesActive

    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    db_session.add_all(
        [
            IndexSeriesActive(
                resource="index_daily",
                ts_code="000300.SH",
                first_seen_date=date(2026, 4, 1),
                last_seen_date=date(2026, 4, 15),
                last_checked_at=datetime(2026, 4, 15, 10, 0, tzinfo=timezone.utc),
            ),
            IndexSeriesActive(
                resource="index_daily",
                ts_code="000905.SH",
                first_seen_date=date(2026, 4, 1),
                last_seen_date=date(2026, 4, 15),
                last_checked_at=datetime(2026, 4, 15, 10, 0, tzinfo=timezone.utc),
            ),
            IndexDailyServing(ts_code="000300.SH", trade_date=date(2026, 4, 24), source="api"),
            IndexWeeklyServing(
                ts_code="000300.SH",
                period_start_date=date(2026, 4, 20),
                trade_date=date(2026, 4, 24),
                source="api",
            ),
            IndexMonthlyServing(
                ts_code="000300.SH",
                period_start_date=date(2026, 4, 1),
                trade_date=date(2026, 4, 30),
                source="derived_daily",
            ),
        ]
    )
    db_session.commit()

    response = app_client.get(
        "/api/v1/ops/review/index/active/summary?resource=index_daily",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert response.json() == {
        "active_count": 2,
        "daily_available_count": 1,
        "weekly_available_count": 1,
        "monthly_available_count": 1,
        "pending_count": 1,
    }


def test_ops_review_index_active_candidates_excludes_active_codes(app_client, user_factory, db_session) -> None:
    from src.foundation.models.core.index_basic import IndexBasic
    from src.ops.models.ops.index_series_active import IndexSeriesActive

    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    db_session.add_all(
        [
            IndexBasic(ts_code="000300.SH", name="沪深300", market="SSE", publisher="中证指数"),
            IndexBasic(ts_code="000905.SH", name="中证500", market="SSE", publisher="中证指数"),
            IndexSeriesActive(
                resource="index_daily",
                ts_code="000300.SH",
                first_seen_date=date(2026, 4, 1),
                last_seen_date=date(2026, 4, 15),
                last_checked_at=datetime(2026, 4, 15, 10, 0, tzinfo=timezone.utc),
            ),
        ]
    )
    db_session.commit()

    response = app_client.get(
        "/api/v1/ops/review/index/active/candidates?resource=index_daily&keyword=中证",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    items = response.json()["items"]
    assert [item["ts_code"] for item in items] == ["000905.SH"]


def test_ops_review_index_candidates_and_add_enforce_source_serviceability(
    app_client,
    user_factory,
    db_session,
) -> None:
    from src.foundation.models.core.index_basic import IndexBasic

    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]
    reference_date = date.today() - timedelta(days=1)
    required_dates = [
        reference_date,
        reference_date - timedelta(days=1),
        reference_date - timedelta(days=2),
    ]
    _seed_index_daily_raw_eligibility(db_session, ts_code="READY.SH", trade_dates=required_dates)
    _seed_index_daily_raw_eligibility(
        db_session,
        ts_code="WAIT.SH",
        trade_dates=[required_dates[0]],
        include_calendar=False,
    )
    db_session.add_all(
        [
            IndexBasic(ts_code="READY.SH", name="可加入指数", market="SSE", publisher="测试"),
            IndexBasic(ts_code="WAIT.SH", name="待观察指数", market="SSE", publisher="测试"),
        ]
    )
    db_session.commit()

    candidates_response = app_client.get(
        "/api/v1/ops/review/index/active/candidates?resource=index_daily&keyword=指数",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert candidates_response.status_code == 200
    candidates_by_code = {item["ts_code"]: item for item in candidates_response.json()["items"]}
    assert candidates_by_code["READY.SH"]["eligible_for_activation"] is True
    assert candidates_by_code["WAIT.SH"]["eligible_for_activation"] is False
    assert "连续 3 个已结束开市日" in candidates_by_code["WAIT.SH"]["eligibility_message"]

    rejected_response = app_client.post(
        "/api/v1/ops/review/index/active",
        json={"resource": "index_daily", "ts_code": "WAIT.SH"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert rejected_response.status_code == 422
    assert rejected_response.json()["code"] == "source_serviceability_not_ready"

    accepted_response = app_client.post(
        "/api/v1/ops/review/index/active",
        json={"resource": "index_daily", "ts_code": "READY.SH"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert accepted_response.status_code == 200


def test_ops_review_index_active_add_and_remove_only_change_active_pool(app_client, user_factory, db_session) -> None:
    from src.foundation.models.core.index_basic import IndexBasic
    from src.foundation.models.core_serving.index_daily_serving import IndexDailyServing
    from src.foundation.models.raw.raw_index_daily import RawIndexDaily
    from src.ops.models.ops.index_series_active import IndexSeriesActive

    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    reference_date = date.today() - timedelta(days=1)
    _seed_index_daily_raw_eligibility(
        db_session,
        ts_code="000300.SH",
        trade_dates=[reference_date, reference_date - timedelta(days=1), reference_date - timedelta(days=2)],
    )
    db_session.add_all(
        [
            IndexBasic(ts_code="000300.SH", name="沪深300", market="SSE", publisher="中证指数"),
            IndexDailyServing(ts_code="000300.SH", trade_date=date(2026, 4, 24), source="api"),
        ]
    )
    db_session.commit()

    add_response = app_client.post(
        "/api/v1/ops/review/index/active",
        json={"resource": "index_daily", "ts_code": "000300.SH"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert add_response.status_code == 200
    assert add_response.json() == {"resource": "index_daily", "ts_code": "000300.SH"}
    assert db_session.get(IndexSeriesActive, ("index_daily", "000300.SH")) is not None

    duplicate_response = app_client.post(
        "/api/v1/ops/review/index/active",
        json={"resource": "index_daily", "ts_code": "000300.SH"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert duplicate_response.status_code == 409

    remove_response = app_client.delete(
        "/api/v1/ops/review/index/active/000300.SH?resource=index_daily",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert remove_response.status_code == 200
    assert remove_response.json() == {"resource": "index_daily", "ts_code": "000300.SH"}
    assert db_session.get(IndexSeriesActive, ("index_daily", "000300.SH")) is None
    assert db_session.get(IndexDailyServing, ("000300.SH", date(2026, 4, 24))) is not None
    assert db_session.get(RawIndexDaily, ("000300.SH", reference_date)) is not None


def test_ops_review_index_active_add_rejects_unknown_index(app_client, user_factory) -> None:
    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    response = app_client.post(
        "/api/v1/ops/review/index/active",
        json={"resource": "index_daily", "ts_code": "NOPE.SH"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


def test_ops_review_etf_active_list_joins_basic_and_latest_fund_daily(app_client, user_factory, db_session) -> None:
    from src.foundation.models.core.etf_basic import EtfBasic
    from src.foundation.models.core.fund_daily_bar import FundDailyBar
    from src.ops.models.ops.etf_series_active import EtfSeriesActive

    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    db_session.add_all(
        [
            EtfBasic(
                ts_code="510300.SH",
                csname="沪深300ETF",
                extname="华泰柏瑞沪深300ETF",
                cname="沪深300交易型开放式指数证券投资基金",
                exchange="SSE",
                etf_type="股票型",
                list_date=date(2012, 5, 28),
                list_status="L",
            ),
            EtfSeriesActive(
                resource="fund_daily",
                ts_code="510300.SH",
                first_seen_date=date(2026, 6, 16),
                last_seen_date=date(2026, 6, 16),
                last_checked_at=datetime(2026, 6, 17, 1, 0, tzinfo=timezone.utc),
            ),
            EtfSeriesActive(
                resource="fund_daily",
                ts_code="159919.SZ",
                first_seen_date=date(2026, 6, 16),
                last_seen_date=date(2026, 6, 16),
                last_checked_at=datetime(2026, 6, 17, 1, 0, tzinfo=timezone.utc),
            ),
            FundDailyBar(ts_code="510300.SH", trade_date=date(2026, 6, 16)),
            FundDailyBar(ts_code="510300.SH", trade_date=date(2026, 6, 17)),
        ]
    )
    db_session.commit()

    response = app_client.get(
        "/api/v1/ops/review/etf/active?resource=fund_daily&keyword=沪深300&page=1&page_size=10",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    item = payload["items"][0]
    assert item["resource"] == "fund_daily"
    assert item["ts_code"] == "510300.SH"
    assert item["csname"] == "沪深300ETF"
    assert item["exchange"] == "SSE"
    assert item["etf_type"] == "股票型"
    assert item["list_date"] == "2012-05-28"
    assert item["list_status"] == "L"
    assert item["latest_fund_daily_date"] == "2026-06-17"
    assert item["data_status"] == "complete"


def test_ops_review_etf_active_list_filters_status_and_resource(app_client, user_factory, db_session) -> None:
    from src.foundation.models.core.fund_daily_bar import FundDailyBar
    from src.ops.models.ops.etf_series_active import EtfSeriesActive

    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    db_session.add_all(
        [
            EtfSeriesActive(
                resource="fund_daily",
                ts_code="510300.SH",
                first_seen_date=date(2026, 6, 16),
                last_seen_date=date(2026, 6, 16),
                last_checked_at=datetime(2026, 6, 17, 1, 0, tzinfo=timezone.utc),
            ),
            EtfSeriesActive(
                resource="fund_daily",
                ts_code="159919.SZ",
                first_seen_date=date(2026, 6, 16),
                last_seen_date=date(2026, 6, 16),
                last_checked_at=datetime(2026, 6, 17, 1, 0, tzinfo=timezone.utc),
            ),
            EtfSeriesActive(
                resource="etf_rt_daily",
                ts_code="588000.SH",
                first_seen_date=date(2026, 6, 16),
                last_seen_date=date(2026, 6, 16),
                last_checked_at=datetime(2026, 6, 17, 1, 0, tzinfo=timezone.utc),
            ),
            FundDailyBar(ts_code="510300.SH", trade_date=date(2026, 6, 17)),
            FundDailyBar(ts_code="588000.SH", trade_date=date(2026, 6, 17)),
        ]
    )
    db_session.commit()

    pending_response = app_client.get(
        "/api/v1/ops/review/etf/active?resource=fund_daily&data_status=pending&page=1&page_size=10",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert pending_response.status_code == 200
    pending_payload = pending_response.json()
    assert pending_payload["total"] == 1
    assert pending_payload["items"][0]["ts_code"] == "159919.SZ"
    assert pending_payload["items"][0]["data_status"] == "unsynced"

    rt_response = app_client.get(
        "/api/v1/ops/review/etf/active?resource=etf_rt_daily&page=1&page_size=10",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert rt_response.status_code == 200
    rt_payload = rt_response.json()
    assert rt_payload["total"] == 1
    assert rt_payload["items"][0]["ts_code"] == "588000.SH"
    assert rt_payload["items"][0]["data_status"] == "complete"


def test_ops_review_etf_active_summary_counts_available_daily(app_client, user_factory, db_session) -> None:
    from src.foundation.models.core.fund_daily_bar import FundDailyBar
    from src.ops.models.ops.etf_series_active import EtfSeriesActive

    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    db_session.add_all(
        [
            EtfSeriesActive(
                resource="fund_daily",
                ts_code="510300.SH",
                first_seen_date=date(2026, 6, 16),
                last_seen_date=date(2026, 6, 16),
                last_checked_at=datetime(2026, 6, 17, 1, 0, tzinfo=timezone.utc),
            ),
            EtfSeriesActive(
                resource="fund_daily",
                ts_code="159919.SZ",
                first_seen_date=date(2026, 6, 16),
                last_seen_date=date(2026, 6, 16),
                last_checked_at=datetime(2026, 6, 17, 1, 0, tzinfo=timezone.utc),
            ),
            FundDailyBar(ts_code="510300.SH", trade_date=date(2026, 6, 17)),
        ]
    )
    db_session.commit()

    response = app_client.get(
        "/api/v1/ops/review/etf/active/summary?resource=fund_daily",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert response.json() == {
        "active_count": 2,
        "fund_daily_available_count": 1,
        "pending_count": 1,
    }


def test_ops_review_etf_active_rejects_invalid_resource(app_client, user_factory) -> None:
    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    response = app_client.get(
        "/api/v1/ops/review/etf/active?resource=bad",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


def test_ops_review_etf_active_has_no_write_routes(app_client, user_factory) -> None:
    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    post_response = app_client.post(
        "/api/v1/ops/review/etf/active",
        json={"resource": "fund_daily", "ts_code": "510300.SH"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert post_response.status_code == 405

    delete_response = app_client.delete(
        "/api/v1/ops/review/etf/active/510300.SH?resource=fund_daily",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert delete_response.status_code == 404


def test_ops_review_ths_board_list_returns_members(app_client, user_factory, db_session) -> None:
    from src.foundation.models.core.ths_index import ThsIndex
    from src.foundation.models.core.ths_member import ThsMember

    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    db_session.add_all(
        [
            ThsIndex(ts_code="885001.TI", name="人工智能", exchange="A", type_="N"),
            ThsIndex(ts_code="885002.TI", name="新能源", exchange="A", type_="I"),
            ThsMember(ts_code="885001.TI", con_code="000001.SZ", con_name="平安银行", out_date=None),
            ThsMember(ts_code="885001.TI", con_code="000002.SZ", con_name="万科A", out_date=None),
            ThsMember(ts_code="885002.TI", con_code="000001.SZ", con_name="平安银行", out_date=None),
            ThsMember(ts_code="885002.TI", con_code="000003.SZ", con_name="国农科技", out_date=date(2026, 4, 1)),
        ]
    )
    db_session.commit()

    response = app_client.get(
        "/api/v1/ops/review/board/ths?board_type=N&min_constituent_count=2&page=1&page_size=10",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    item = payload["items"][0]
    assert item["board_code"] == "885001.TI"
    assert item["constituent_count"] == 2
    assert len(item["members"]) == 2


def test_ops_review_dc_board_list_defaults_to_latest_trade_date(app_client, user_factory, db_session) -> None:
    from src.foundation.models.core.dc_index import DcIndex
    from src.foundation.models.core.dc_member import DcMember

    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    db_session.add_all(
        [
            DcIndex(ts_code="BK001", trade_date=date(2026, 4, 14), name="算力", idx_type="概念"),
            DcIndex(ts_code="BK001", trade_date=date(2026, 4, 15), name="算力", idx_type="概念"),
            DcIndex(ts_code="BK002", trade_date=date(2026, 4, 15), name="消费", idx_type="行业"),
            DcMember(trade_date=date(2026, 4, 15), ts_code="BK001", con_code="000001.SZ", name="平安银行"),
            DcMember(trade_date=date(2026, 4, 15), ts_code="BK001", con_code="000002.SZ", name="万科A"),
        ]
    )
    db_session.commit()

    response = app_client.get(
        "/api/v1/ops/review/board/dc?page=1&page_size=10",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["trade_date"] == "2026-04-15"
    assert payload["idx_type_options"] == ["概念", "行业"]
    assert payload["total"] == 2
    assert payload["items"][0]["constituent_count"] == 2


def test_ops_review_equity_membership_aggregates_ths_and_dc(app_client, user_factory, db_session) -> None:
    from src.foundation.models.core.dc_index import DcIndex
    from src.foundation.models.core.dc_member import DcMember
    from src.foundation.models.core.ths_index import ThsIndex
    from src.foundation.models.core.ths_member import ThsMember
    from src.foundation.models.core_serving.security_serving import Security

    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    db_session.add_all(
        [
            Security(ts_code="000001.SZ", name="平安银行"),
            ThsIndex(ts_code="885001.TI", name="人工智能", exchange="A", type_="N"),
            ThsMember(ts_code="885001.TI", con_code="000001.SZ", con_name="平安银行", out_date=None),
            DcIndex(ts_code="BK001", trade_date=date(2026, 4, 15), name="算力", idx_type="概念"),
            DcMember(trade_date=date(2026, 4, 15), ts_code="BK001", con_code="000001.SZ", name="平安银行"),
        ]
    )
    db_session.commit()

    response = app_client.get(
        "/api/v1/ops/review/board/equity-membership?provider=all&page=1&page_size=10",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["dc_trade_date"] == "2026-04-15"
    assert payload["total"] == 1
    item = payload["items"][0]
    assert item["ts_code"] == "000001.SZ"
    assert item["equity_name"] == "平安银行"
    assert item["board_count"] == 2
    providers = sorted(board["provider"] for board in item["boards"])
    assert providers == ["dc", "ths"]


def test_ops_review_equity_membership_keyword_supports_cnspell(app_client, user_factory, db_session) -> None:
    from src.foundation.models.core.ths_index import ThsIndex
    from src.foundation.models.core.ths_member import ThsMember
    from src.foundation.models.core_serving.security_serving import Security

    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    db_session.add_all(
        [
            Security(ts_code="000001.SZ", name="平安银行", symbol="000001", cnspell="payh"),
            Security(ts_code="000002.SZ", name="万科A", symbol="000002", cnspell="wka"),
            ThsIndex(ts_code="885001.TI", name="人工智能", exchange="A", type_="N"),
            ThsMember(ts_code="885001.TI", con_code="000001.SZ", con_name="平安银行", out_date=None),
            ThsMember(ts_code="885001.TI", con_code="000002.SZ", con_name="万科A", out_date=None),
        ]
    )
    db_session.commit()

    response = app_client.get(
        "/api/v1/ops/review/board/equity-membership?provider=all&keyword=pay&page=1&page_size=10",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["items"][0]["ts_code"] == "000001.SZ"


def test_ops_review_equity_suggest_supports_ts_code_and_cnspell(app_client, user_factory, db_session) -> None:
    from src.foundation.models.core_serving.security_serving import Security

    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    db_session.add_all(
        [
            Security(ts_code="000001.SZ", name="平安银行", symbol="000001", cnspell="payh"),
            Security(ts_code="000002.SZ", name="万科A", symbol="000002", cnspell="wka"),
        ]
    )
    db_session.commit()

    code_response = app_client.get(
        "/api/v1/ops/review/board/equity-suggest?keyword=0000",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert code_response.status_code == 200
    code_payload = code_response.json()
    assert len(code_payload["items"]) == 2
    assert code_payload["items"][0]["ts_code"] == "000001.SZ"

    cnspell_response = app_client.get(
        "/api/v1/ops/review/board/equity-suggest?keyword=pay",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert cnspell_response.status_code == 200
    cnspell_payload = cnspell_response.json()
    assert len(cnspell_payload["items"]) == 1
    assert cnspell_payload["items"][0]["ts_code"] == "000001.SZ"
