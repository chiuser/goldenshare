from __future__ import annotations

from datetime import date
from unittest.mock import patch

import pytest
from sqlalchemy import event, select

from src.biz.models.wealth.watchlist_item import WealthWatchlistItem
from src.foundation.models.core.equity_moneyflow import EquityMoneyflow
from src.foundation.models.core_serving.equity_daily_bar import EquityDailyBar
from src.foundation.models.core_serving.equity_daily_basic import EquityDailyBasic
from src.foundation.models.core_serving.security_serving import Security

BASE = "/api/v1/wealth/market/watchlist"
DAY = date(2026, 9, 2)
PRIOR = date(2026, 9, 1)


@pytest.fixture(autouse=True)
def watchlist_tables(db_session):
    for model in (
        WealthWatchlistItem,
        EquityDailyBar,
        EquityDailyBasic,
        EquityMoneyflow,
    ):
        model.__table__.create(db_session.get_bind(), checkfirst=True)


@pytest.fixture()
def headers(auth_token):
    return {"Authorization": f"Bearer {auth_token}"}


def security(code="000001.SZ", **overrides):
    fields = dict(
        ts_code=code,
        symbol=code.split(".")[0],
        name="平安银行",
        cnspell="PAYH",
        industry="银行",
        security_type="EQUITY",
        list_status="L",
        exchange="SZSE",
        curr_type="CNY",
        source="tushare",
    )
    return Security(**(fields | overrides))


def seed(db_session, *rows):
    db_session.add_all(rows)
    db_session.commit()


def add(app_client, headers, code="000001.SZ"):
    response = app_client.put(f"{BASE}/items/{code}", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize(
    "method,path",
    [
        ("get", ""),
        ("get", "/summary"),
        ("get", "/search?keyword=PAYH"),
        ("get", "/items/000001.SZ"),
        ("put", "/items/000001.SZ"),
        ("delete", "/items/000001.SZ"),
    ],
)
def test_all_endpoints_require_identity(app_client, method, path):
    assert getattr(app_client, method)(BASE + path).status_code == 401


def test_owner_isolation_and_idempotent_mutations(
    app_client, db_session, headers, user_factory
):
    seed(db_session, security())
    assert add(app_client, headers, " 000001.sz ")["created"] is True
    assert add(app_client, headers) == dict(
        tsCode="000001.SZ", isAdded=True, created=False, totalCount=1
    )
    user_factory(username="second", password="secret")
    token = app_client.post(
        "/api/v1/auth/login", json={"username": "second", "password": "secret"}
    ).json()["token"]
    second = {"Authorization": f"Bearer {token}"}
    assert app_client.get(f"{BASE}/summary", headers=second).json() == {"totalCount": 0}
    assert (
        app_client.get(f"{BASE}/items/000001.SZ", headers=second).json()["isAdded"]
        is False
    )
    assert app_client.get(BASE, headers=second).json()["items"] == []
    assert (
        app_client.delete(f"{BASE}/items/000001.SZ", headers=second).json()["removed"]
        is False
    )
    assert app_client.get(f"{BASE}/summary", headers=headers).json() == {
        "totalCount": 1
    }
    assert add(app_client, second)["created"] is True
    first_remove = app_client.delete(f"{BASE}/items/000001.SZ", headers=headers).json()
    assert first_remove == dict(
        tsCode="000001.SZ", isAdded=False, removed=True, totalCount=0
    )
    assert (
        app_client.delete(f"{BASE}/items/000001.SZ", headers=headers).json()["removed"]
        is False
    )
    assert app_client.get(f"{BASE}/summary", headers=second).json() == {"totalCount": 1}


def test_empty_does_not_query_quote_tables(app_client, db_session, headers):
    statements = []

    def capture(_conn, _cursor, statement, _parameters, _context, _many):
        statements.append(statement)

    engine = db_session.get_bind()
    event.listen(engine, "before_cursor_execute", capture)
    try:
        response = app_client.get(BASE, headers=headers)
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert response.status_code == 200
    assert response.json()["dataStatus"]["status"] == "EMPTY"
    assert not any(
        "equity_daily" in statement or "equity_moneyflow" in statement
        for statement in statements
    )


def test_same_day_core_fields_and_missing_rows_are_not_backfilled(
    app_client, db_session, headers
):
    seed(
        db_session,
        security(),
        security("600000.SH", name="浦发银行", exchange="SSE"),
        EquityDailyBar(
            ts_code="000001.SZ", trade_date=DAY, close=12.34, pct_chg=1.73, vol=1234567
        ),
        EquityDailyBasic(
            ts_code="000001.SZ",
            trade_date=DAY,
            pe_ttm=5.62,
            pb=0.71,
            volume_ratio=1.08,
            turnover_rate=0.92,
        ),
        EquityMoneyflow(ts_code="000001.SZ", trade_date=DAY, net_mf_amount=-2189.4),
        EquityDailyBasic(
            ts_code="600000.SH",
            trade_date=PRIOR,
            pe_ttm=999,
            pb=999,
            volume_ratio=999,
            turnover_rate=999,
        ),
        EquityMoneyflow(ts_code="600000.SH", trade_date=PRIOR, net_mf_amount=999),
    )
    add(app_client, headers)
    payload = app_client.get(
        BASE, params={"tradeDate": DAY.isoformat()}, headers=headers
    ).json()
    assert payload["dataStatus"] == dict(
        status="READY", expectedTradeDate=str(DAY), observedTradeDate=str(DAY)
    )
    item = payload["items"][0]
    assert item["stock"] == dict(
        tsCode="000001.SZ", name="平安银行", industry="银行", listStatus="L"
    )
    assert item["quote"] == dict(
        price=12.34, changePct=1.73, vol=1234567, direction="UP"
    )
    assert item["valuation"] == dict(peTtm=5.62, pb=0.71)
    assert item["activity"] == dict(volumeRatio=1.08, turnoverRate=0.92)
    assert item["moneyFlow"] == dict(netAmount=-2189.4, direction="DOWN")
    assert item["missingFields"] == []
    delayed = app_client.get(
        BASE, params={"tradeDate": "2026-09-03"}, headers=headers
    ).json()
    assert delayed["dataStatus"]["status"] == "DELAYED"
    add(app_client, headers, "600000.SH")
    partial = app_client.get(
        BASE, params={"tradeDate": "2026-09-03"}, headers=headers
    ).json()
    assert partial["dataStatus"]["status"] == "PARTIAL"
    missing = partial["items"][1]
    assert missing["quote"]["direction"] == "UNKNOWN"
    assert missing["valuation"] == dict(peTtm=None, pb=None)
    assert missing["moneyFlow"] == dict(netAmount=None, direction="UNKNOWN")
    assert "valuation.peTtm" in missing["missingFields"]
    stock = db_session.get(Security, "600000.SH")
    stock.list_status = "D"
    db_session.commit()
    assert app_client.get(f"{BASE}/summary", headers=headers).json()["totalCount"] == 2


def test_search_pool_membership_ranking_and_eligibility(
    app_client, db_session, headers
):
    excluded = [
        security("900001.SH", curr_type="USD"),
        security("200001.SZ", curr_type="HKD"),
        security("600002.SH", list_status="D"),
        security("600003.SH", list_status="P"),
        security("000300.SH", security_type="INDEX"),
        security("510300.SH", security_type="ETF"),
        security("000005.HK", exchange="HKEX"),
    ]
    seed(db_session, security(), security("920001.BJ", exchange="BSE"), *excluded)
    add(app_client, headers)
    result = app_client.get(
        f"{BASE}/search", params={"keyword": " payh "}, headers=headers
    ).json()
    assert result == dict(
        keyword="PAYH",
        items=[
            dict(tsCode="000001.SZ", name="平安银行", status="ADDED"),
            dict(tsCode="920001.BJ", name="平安银行", status="AVAILABLE"),
        ],
    )
    for stock in excluded:
        response = app_client.put(f"{BASE}/items/{stock.ts_code}", headers=headers)
        assert response.status_code == 422
        assert response.json()["code"] == "WL_STOCK_NOT_ELIGIBLE"
    assert (
        app_client.get(f"{BASE}/search?keyword=%25", headers=headers).json()["items"]
        == []
    )
    assert (
        app_client.get(f"{BASE}/search?keyword=000001.sz", headers=headers).json()[
            "items"
        ][0]["tsCode"]
        == "000001.SZ"
    )


def test_id_cursor_pagination_and_append_at_global_tail(
    app_client, db_session, headers
):
    codes = ["600009.SH", "000001.SZ", "600000.SH", "920001.BJ"]
    seed(db_session, *(security(code) for code in codes))
    for code in codes[:3]:
        add(app_client, headers, code)
    first = app_client.get(BASE, params={"limit": 2}, headers=headers).json()
    assert [item["stock"]["tsCode"] for item in first["items"]] == codes[:2]
    add(app_client, headers, codes[3])
    second = app_client.get(
        BASE, params={"limit": 2, "afterId": first["nextCursor"]}, headers=headers
    ).json()
    assert [item["stock"]["tsCode"] for item in second["items"]] == codes[2:]
    assert second["nextCursor"] is None
    assert first["items"][0]["id"] < second["items"][-1]["id"]


@pytest.mark.parametrize(
    "query",
    [
        "limit=0",
        "limit=201",
        "limit=no",
        "afterId=0",
        "afterId=-1",
        "afterId=1.5",
        "afterId=99999999999999999999",
        "tradeDate=2026-02-30",
        "tradeDate=no",
    ],
)
def test_invalid_inputs_use_registered_error(app_client, headers, query):
    response = app_client.get(f"{BASE}?{query}", headers=headers)
    assert response.status_code == 400
    assert response.json()["code"] == "WL_REQUEST_INVALID"


def test_errors_are_local_safe_and_writes_rollback(app_client, db_session, headers):
    seed(db_session, security())
    with patch(
        "src.biz.queries.wealth.market.watchlist.watchlist_query.WatchlistQuery.count",
        side_effect=RuntimeError("secret SQL app.wealth_watchlist_item"),
    ):
        response = app_client.get(f"{BASE}/summary", headers=headers)
    assert response.status_code == 500
    assert response.json()["code"] == "WL_QUERY_FAILED"
    assert "secret" not in response.text
    with patch.object(db_session, "flush", side_effect=RuntimeError("secret write")):
        response = app_client.put(f"{BASE}/items/000001.SZ", headers=headers)
    assert response.status_code == 500
    assert response.json()["code"] == "WL_WRITE_FAILED"
    assert "secret" not in response.text
    assert db_session.scalar(select(WealthWatchlistItem.id)) is None


def test_request_cannot_choose_another_owner(
    app_client, db_session, headers, user_factory
):
    other = user_factory(username="not-owner")
    seed(db_session, security())
    response = app_client.put(
        f"{BASE}/items/000001.SZ?userId={other.id}",
        json={"userId": other.id},
        headers=headers,
    )
    assert response.status_code == 200
    assert db_session.scalar(select(WealthWatchlistItem.user_id)) != other.id


def test_missing_security_and_no_observed_date_keep_membership_without_zero_fill(
    app_client, db_session, headers
):
    seed(db_session, security())
    add(app_client, headers)
    # A retained relation must not depend on the continued presence of security.
    stock = db_session.get(Security, "000001.SZ")
    db_session.delete(stock)
    db_session.commit()
    payload = app_client.get(BASE, headers=headers).json()
    assert payload["totalCount"] == 1
    assert payload["dataStatus"]["status"] == "PARTIAL"
    assert payload["dataStatus"]["observedTradeDate"] is None
    row = payload["items"][0]
    assert row["stock"]["name"] == "--"
    assert "stock.name" in row["missingFields"]
    assert row["quote"] == dict(
        price=None, changePct=None, vol=None, direction="UNKNOWN"
    )
    assert row["moneyFlow"] == dict(netAmount=None, direction="UNKNOWN")
    assert (
        app_client.delete(f"{BASE}/items/000001.SZ", headers=headers).json()["removed"]
        is True
    )


def test_add_rechecks_eligibility_after_search_and_zero_values_are_not_missing(
    app_client, db_session, headers
):
    seed(
        db_session,
        security(),
        EquityDailyBar(ts_code="000001.SZ", trade_date=DAY, close=0, pct_chg=0, vol=0),
        EquityDailyBasic(
            ts_code="000001.SZ",
            trade_date=DAY,
            pe_ttm=0,
            pb=0,
            volume_ratio=0,
            turnover_rate=0,
        ),
        EquityMoneyflow(ts_code="000001.SZ", trade_date=DAY, net_mf_amount=0),
    )
    add(app_client, headers)
    payload = app_client.get(
        BASE, params={"tradeDate": str(DAY)}, headers=headers
    ).json()
    assert payload["items"][0]["quote"]["direction"] == "FLAT"
    assert payload["items"][0]["moneyFlow"]["direction"] == "FLAT"
    assert payload["items"][0]["missingFields"] == []
    assert payload["dataStatus"]["status"] == "READY"
    assert app_client.get(f"{BASE}/search?keyword=PAYH", headers=headers).json()[
        "items"
    ]
    stock = db_session.get(Security, "000001.SZ")
    stock.list_status = "D"
    db_session.commit()
    rejected = app_client.put(f"{BASE}/items/000001.SZ", headers=headers)
    assert rejected.status_code == 422
    assert rejected.json()["code"] == "WL_STOCK_NOT_ELIGIBLE"
    assert app_client.get(f"{BASE}/summary", headers=headers).json()["totalCount"] == 1


@pytest.mark.parametrize(
    "query",
    [
        "keyword=",
        "keyword=" + "x" * 33,
        "keyword=PAYH&limit=21",
        "keyword=PAYH&limit=0",
    ],
)
def test_search_rejects_unbounded_or_blank_requests(app_client, headers, query):
    response = app_client.get(f"{BASE}/search?{query}", headers=headers)
    assert response.status_code == 400
    assert response.json()["code"] == "WL_REQUEST_INVALID"


@pytest.mark.parametrize("method", ["get", "put", "delete"])
def test_item_code_rejects_blank_and_overlong_identifiers(app_client, headers, method):
    for code in ["%20", "x" * 17]:
        response = getattr(app_client, method)(f"{BASE}/items/{code}", headers=headers)
        assert response.status_code == 400
        assert response.json()["code"] == "WL_REQUEST_INVALID"
