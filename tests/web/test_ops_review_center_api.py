from __future__ import annotations

from datetime import date, datetime, timezone


def test_ops_review_center_requires_admin(app_client, user_factory) -> None:
    user_factory(username="user", password="secret", is_admin=False)
    login = app_client.post("/api/v1/auth/login", json={"username": "user", "password": "secret"})
    token = login.json()["token"]

    response = app_client.get("/api/v1/ops/review/index/active", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"


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


def test_ops_review_index_active_add_and_remove_only_change_active_pool(app_client, user_factory, db_session) -> None:
    from src.foundation.models.core.index_basic import IndexBasic
    from src.foundation.models.core_serving.index_daily_serving import IndexDailyServing
    from src.ops.models.ops.index_series_active import IndexSeriesActive

    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

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
