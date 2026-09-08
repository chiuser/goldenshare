from __future__ import annotations

from datetime import date, datetime, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import delete, event, select, text

from src.biz.models.wealth.watchlist_group import WealthWatchlistGroup as Group
from src.biz.models.wealth.watchlist_membership import (
    WealthWatchlistMembership as Membership,
)
from src.biz.queries.wealth.market.watchlist.watchlist_group_query import (
    WatchlistGroupQuery,
)
from src.biz.queries.wealth.market.watchlist.watchlist_item_query import (
    WatchlistItemQuery,
)
from src.biz.services.wealth.market.watchlist.watchlist_policy import (
    MAX_API_ID,
    PALETTE,
    SORT_FIELDS,
)
from src.foundation.models.core.equity_moneyflow import EquityMoneyflow
from src.foundation.models.core_serving.equity_daily_bar import EquityDailyBar
from src.foundation.models.core_serving.equity_daily_basic import EquityDailyBasic
from src.foundation.models.core_serving.security_serving import Security

BASE = "/api/v1/wealth/market/watchlist"
DAY = date(2026, 9, 2)
PRIOR = date(2026, 9, 1)


@pytest.fixture(autouse=True)
def watchlist_tables(db_session):
    for model in (EquityDailyBar, EquityDailyBasic, EquityMoneyflow):
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


def seed(session, *rows):
    session.add_all(rows)
    session.commit()


def groups(client, headers):
    response = client.get(BASE + "/groups", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["groups"]


def default(client, headers):
    return groups(client, headers)[0]["id"]


def create(client, headers, name="成长", color=PALETTE[0]):
    response = client.post(
        BASE + "/groups", headers=headers, json={"name": name, "color": color}
    )
    assert response.status_code == 200, response.text
    return response.json()["group"]["id"]


def add(client, headers, group_id, code="000001.SZ"):
    response = client.put(f"{BASE}/groups/{group_id}/items/{code}", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def page(client, headers, group_id, **params):
    response = client.get(
        f"{BASE}/groups/{group_id}/items", headers=headers, params=params
    )
    assert response.status_code == 200, response.text
    return response.json()


def action(client, headers, group_id, name, ids, **extra):
    return client.post(
        f"{BASE}/groups/{group_id}/actions/{name}",
        headers=headers,
        json={"membershipIds": ids, **extra},
    )


ROUTES = [
    ("get", "/groups", None),
    ("post", "/groups", {"name": "a", "color": PALETTE[0]}),
    ("patch", "/groups/1/color", {"color": PALETTE[0]}),
    ("delete", "/groups/1", None),
    ("get", "/groups/1/items", None),
    ("get", "/groups/1/search?keyword=PAYH", None),
    ("put", "/groups/1/items/000001.SZ", None),
    ("post", "/groups/1/actions/move", {"membershipIds": [1], "targetGroupId": 2}),
    (
        "post",
        "/groups/1/actions/add-to-groups",
        {"membershipIds": [1], "targetGroupIds": [2]},
    ),
    *[
        ("post", f"/groups/1/actions/{a}", {"membershipIds": [1]})
        for a in ("remove", "pin", "unpin")
    ],
    ("get", "/stocks/000001.SZ/groups", None),
    ("put", "/stocks/000001.SZ/groups", {"groupIds": [1]}),
    ("get", "/summary", None),
]


@pytest.mark.parametrize("method,path,body", ROUTES)
def test_all_fifteen_routes_require_identity(app_client, method, path, body):
    assert app_client.request(method, BASE + path, json=body).status_code == 401


@pytest.mark.parametrize(
    "method,path",
    [
        ("get", ""),
        ("get", "/search"),
        ("get", "/items/000001.SZ"),
        ("put", "/items/000001.SZ"),
        ("delete", "/items/000001.SZ"),
        ("patch", "/groups/1"),
        ("put", "/groups/1"),
    ],
)
def test_old_contracts_and_rename_routes_are_absent(app_client, headers, method, path):
    assert app_client.request(method, BASE + path, headers=headers).status_code in (
        404,
        405,
    )


def test_groups_rules_constraints_and_delete_neighbors(app_client, headers):
    original = groups(app_client, headers)
    assert len(original) == 1
    assert original[0] | {"id": 1, "createdAt": ""} == dict(
        id=1, name="我的自选", isDefault=True, color=None, memberCount=0, createdAt=""
    )
    d = original[0]["id"]
    rules = app_client.get(BASE + "/groups", headers=headers).json()["rules"]
    assert rules == dict(
        maxGroups=10,
        maxCustomGroups=9,
        nameMaxVisibleChars=6,
        nameMaxUtf8Bytes=1024,
        maxBatchMemberships=200,
        palette=list(PALETTE),
    )
    for method, path, body in [
        ("delete", f"/groups/{d}", None),
        ("patch", f"/groups/{d}/color", {"color": PALETTE[0]}),
    ]:
        result = app_client.request(method, BASE + path, headers=headers, json=body)
        assert result.status_code == 409
        assert result.json()["code"] == "WL_DEFAULT_GROUP_IMMUTABLE"
    ids = [create(app_client, headers, f"组{i}") for i in range(9)]
    assert d < min(ids)
    assert (
        app_client.post(
            BASE + "/groups",
            headers=headers,
            json={"name": "超额", "color": PALETTE[0]},
        ).json()["code"]
        == "WL_GROUP_LIMIT_REACHED"
    )
    assert app_client.delete(f"{BASE}/groups/{ids[2]}", headers=headers).json() == dict(
        deletedGroupId=ids[2], deletedMemberCount=0, nextGroupId=ids[3]
    )
    assert (
        app_client.delete(f"{BASE}/groups/{ids[-1]}", headers=headers).json()[
            "nextGroupId"
        ]
        == d
    )
    changed = app_client.patch(
        f"{BASE}/groups/{ids[0]}/color", headers=headers, json={"color": PALETTE[1]}
    )
    assert changed.status_code == 200 and changed.json()["group"]["color"] == PALETTE[1]


@pytest.mark.parametrize(
    "name,color",
    [
        ("", PALETTE[0]),
        ("我的自选", PALETTE[0]),
        ("1234567", PALETTE[0]),
        ("A\nI", PALETTE[0]),
        ("成长", "#000000"),
    ],
)
def test_invalid_group_requests(app_client, headers, name, color):
    result = app_client.post(
        BASE + "/groups", headers=headers, json={"name": name, "color": color}
    )
    assert result.status_code == 400
    assert result.json()["code"] == "WL_REQUEST_INVALID"


def test_normalized_name_conflict_extra_fields_and_same_color(app_client, headers):
    first = create(app_client, headers, " e\u0301 ")
    second = create(app_client, headers, "AI-组")
    result = app_client.post(
        BASE + "/groups", headers=headers, json={"name": "é", "color": PALETTE[1]}
    )
    assert result.json()["code"] == "WL_GROUP_NAME_CONFLICT"
    result = app_client.patch(
        f"{BASE}/groups/{first}/color",
        headers=headers,
        json={"color": PALETTE[1], "name": "rename"},
    )
    assert result.status_code == 422
    assert groups(app_client, headers)[1]["id"] == first
    assert groups(app_client, headers)[2]["id"] == second


def test_batch_lifecycle_counts_marks_and_detail_diff(app_client, db_session, headers):
    d = default(app_client, headers)
    a, b = create(app_client, headers, "成长"), create(app_client, headers, "观察")
    seed(db_session, security(), security("600000.SH"))
    add(app_client, headers, d)
    add(app_client, headers, d, "600000.SH")
    source = page(app_client, headers, d)["items"]
    ids = [item["membershipId"] for item in source]
    response = action(
        app_client, headers, d, "add-to-groups", ids, targetGroupIds=[b, a]
    )
    assert response.status_code == 200, response.text
    assert response.json() == dict(
        action="ADD_TO_GROUPS",
        requestedCount=2,
        createdCount=4,
        removedCount=0,
        updatedCount=0,
        groupCounts=[dict(groupId=g, memberCount=2) for g in (d, a, b)],
    )
    marks = page(app_client, headers, d)["items"][0]["groupMarks"]
    assert [m["groupId"] for m in marks] == [a, b]
    assert marks[0]["color"] == marks[1]["color"]
    target_before = page(app_client, headers, a)["items"]
    assert (
        action(
            app_client, headers, d, "add-to-groups", ids, targetGroupIds=[a, b]
        ).json()["createdCount"]
        == 0
    )
    assert (
        action(app_client, headers, d, "move", ids, targetGroupId=a).json()[
            "removedCount"
        ]
        == 2
    )
    assert page(app_client, headers, d)["totalCount"] == 0
    assert page(app_client, headers, a)["items"] == target_before
    assert app_client.get(BASE + "/summary", headers=headers).json() == {
        "totalCount": 0
    }
    detail = app_client.get(BASE + "/stocks/000001.SZ/groups", headers=headers).json()
    assert detail["isAdded"] and [
        g["groupId"] for g in detail["groups"] if g["selected"]
    ] == [a, b]
    assert (
        action(app_client, headers, d, "remove", ids).json()["code"]
        == "WL_SELECTION_STALE"
    )
    put = app_client.put(
        BASE + "/stocks/000001.SZ/groups", headers=headers, json={"groupIds": [b]}
    )
    assert put.json() == dict(
        tsCode="000001.SZ", isAdded=True, groupIds=[b], createdCount=0, removedCount=1
    )
    assert (
        app_client.put(
            BASE + "/stocks/000001.SZ/groups", headers=headers, json={"groupIds": []}
        ).json()["code"]
        == "WL_MEMBERSHIP_REQUIRED"
    )
    removal = app_client.delete(f"{BASE}/groups/{b}", headers=headers)
    assert removal.json() == dict(deletedGroupId=b, deletedMemberCount=2, nextGroupId=d)
    assert not app_client.get(
        BASE + "/stocks/000001.SZ/groups", headers=headers
    ).json()["isAdded"]
    assert page(app_client, headers, a)["totalCount"] == 1


def test_search_eligibility_and_only_new_relations_recheck(
    app_client, db_session, headers
):
    d = default(app_client, headers)
    a = create(app_client, headers)
    seed(
        db_session,
        security(),
        security("920001.BJ", exchange="BSE"),
        security("900001.SH", curr_type="USD"),
        security("000300.SH", security_type="INDEX"),
        security("000005.HK", exchange="HKEX"),
        security("510300.SH", security_type="ETF"),
    )
    add(app_client, headers, d)
    for g, status in [(d, "ADDED"), (a, "AVAILABLE")]:
        result = app_client.get(
            f"{BASE}/groups/{g}/search?keyword=payh", headers=headers
        ).json()
        assert result == dict(
            groupId=g,
            keyword="PAYH",
            items=[
                dict(tsCode="000001.SZ", name="平安银行", status=status),
                dict(tsCode="920001.BJ", name="平安银行", status="AVAILABLE"),
            ],
        )
    source = page(app_client, headers, d)["items"][0]["membershipId"]
    stock = db_session.get(Security, "000001.SZ")
    stock.list_status = "D"
    db_session.commit()
    assert not add(app_client, headers, d)["created"]
    for action_name, targets in [
        ("move", {"targetGroupId": a}),
        ("add-to-groups", {"targetGroupIds": [a]}),
    ]:
        result = action(app_client, headers, d, action_name, [source], **targets)
        assert result.json()["code"] == "WL_STOCK_NOT_ELIGIBLE"
        assert page(app_client, headers, d)["totalCount"] == 1
    assert (
        app_client.put(
            BASE + "/stocks/000001.SZ/groups", headers=headers, json={"groupIds": [a]}
        ).json()["code"]
        == "WL_STOCK_NOT_ELIGIBLE"
    )
    assert (
        app_client.put(
            BASE + "/stocks/000001.SZ/groups", headers=headers, json={"groupIds": [d]}
        ).json()["createdCount"]
        == 0
    )
    assert action(app_client, headers, d, "pin", [source]).json()["updatedCount"] == 1
    assert action(app_client, headers, d, "pin", [source]).json()["updatedCount"] == 0
    assert action(app_client, headers, d, "unpin", [source]).json()["updatedCount"] == 1
    assert (
        action(app_client, headers, d, "remove", [source]).json()["removedCount"] == 1
    )


def test_existing_target_keeps_id_pin_when_delisted_move(
    app_client, db_session, headers
):
    d = default(app_client, headers)
    a = create(app_client, headers)
    seed(db_session, security())
    add(app_client, headers, d)
    add(app_client, headers, a)
    source = page(app_client, headers, d)["items"][0]["membershipId"]
    target = page(app_client, headers, a)["items"][0]["membershipId"]
    action(app_client, headers, a, "pin", [target])
    db_session.get(Security, "000001.SZ").list_status = "D"
    db_session.commit()
    before = page(app_client, headers, a)["items"]
    assert (
        action(app_client, headers, d, "move", [source], targetGroupId=a).json()[
            "createdCount"
        ]
        == 0
    )
    assert page(app_client, headers, a)["items"] == before


@pytest.mark.parametrize("sort_by", [None, *SORT_FIELDS])
@pytest.mark.parametrize("direction", ["desc", "asc"])
def test_all_sort_fields_pin_null_ties_and_seek(
    app_client, db_session, headers, sort_by, direction
):
    d = default(app_client, headers)
    values = [2, None, 0, -3, 2, 1, None, 2]
    for i, value in enumerate(values, 1):
        code = f"{i:06d}.SZ"
        seed(
            db_session,
            security(code),
            EquityDailyBar(
                ts_code=code, trade_date=DAY, close=value, pct_chg=value, vol=value
            ),
            EquityDailyBasic(
                ts_code=code,
                trade_date=DAY,
                pe_ttm=value,
                pb=value,
                volume_ratio=value,
                turnover_rate=value,
            ),
            EquityMoneyflow(ts_code=code, trade_date=DAY, net_mf_amount=value),
        )
        add(app_client, headers, d, code)
    rows = list(
        db_session.scalars(
            select(Membership).where(Membership.group_id == d).order_by(Membership.id)
        )
    )
    pins = {rows[i].id for i in (0, 1, 4)}
    for i, row in enumerate(rows):
        row.created_at = datetime(
            2026, 9, 8 - i, tzinfo=timezone.utc
        )  # Opposes ID order.
    db_session.commit()
    action(app_client, headers, d, "pin", sorted(pins))
    params = dict(tradeDate=str(DAY), limit=2)
    if sort_by:
        params.update(sortBy=sort_by, direction=direction)

    def key(pair):
        row, value = pair
        pinned = row.id in pins
        stable = -row.id if pinned else row.id
        return (
            (
                not pinned,
                value is None,
                (value or 0) * (-1 if direction == "desc" else 1),
                stable,
            )
            if sort_by
            else (not pinned, stable)
        )

    expected = [r.id for r, _ in sorted(zip(rows, values), key=key)]
    found = []
    while True:
        result = page(app_client, headers, d, **params)
        found.extend(item["membershipId"] for item in result["items"])
        if result["nextCursor"] is None:
            break
        params["cursor"] = result["nextCursor"]
    assert found == expected and len(set(found)) == 8
    assert (
        action(app_client, headers, d, "unpin", sorted(pins)).json()["updatedCount"]
        == 3
    )
    assert [item["membershipId"] for item in page(app_client, headers, d)["items"]] == [
        r.id for r in rows
    ]


@pytest.mark.parametrize("value", [True, "1", 1.0, 0, -1, MAX_API_ID + 1])
def test_json_ids_are_strict(app_client, headers, value):
    d = default(app_client, headers)
    assert action(app_client, headers, d, "remove", [value]).status_code == 422
    assert (
        action(app_client, headers, d, "move", [1], targetGroupId=value).status_code
        == 422
    )
    assert (
        app_client.put(
            BASE + "/stocks/000001.SZ/groups",
            headers=headers,
            json={"groupIds": [value]},
        ).status_code
        == 422
    )


@pytest.mark.parametrize("ids", [[], [1, 1], list(range(1, 202))])
def test_invalid_batch_size_or_duplicate(app_client, headers, ids):
    result = action(app_client, headers, default(app_client, headers), "remove", ids)
    assert result.status_code == 400 and result.json()["code"] == "WL_REQUEST_INVALID"


@pytest.mark.parametrize(
    "query",
    [
        "limit=0",
        "limit=201",
        "limit=x",
        "sortBy=price",
        "direction=desc",
        "sortBy=bad&direction=asc",
        "tradeDate=2026-02-30",
        "cursor=broken",
    ],
)
def test_invalid_page_inputs(app_client, headers, query):
    d = default(app_client, headers)
    result = app_client.get(f"{BASE}/groups/{d}/items?{query}", headers=headers)
    assert result.status_code == 400


def test_isolation_and_stale_selection(app_client, headers, db_session, user_factory):
    d = default(app_client, headers)
    user = user_factory(username="other", password="secret")
    token = app_client.post(
        "/api/v1/auth/login", json={"username": "other", "password": "secret"}
    ).json()["token"]
    other = {"Authorization": "Bearer " + token}
    foreign = default(app_client, other)
    seed(db_session, security())
    add(app_client, other, foreign)
    ids = [page(app_client, other, foreign)["items"][0]["membershipId"]]
    assert (
        app_client.get(f"{BASE}/groups/{foreign}/items", headers=headers).json()["code"]
        == "WL_GROUP_NOT_FOUND"
    )
    assert (
        action(app_client, headers, d, "remove", ids).json()["code"]
        == "WL_SELECTION_STALE"
    )
    add(app_client, headers, d)
    own = [page(app_client, headers, d)["items"][0]["membershipId"]]
    for target in (foreign, MAX_API_ID):
        assert (
            action(app_client, headers, d, "move", own, targetGroupId=target).json()[
                "code"
            ]
            == "WL_TARGET_GROUP_INVALID"
        )
    assert (
        action(app_client, headers, d, "move", own, targetGroupId=d).json()["code"]
        == "WL_TARGET_GROUP_INVALID"
    )
    assert page(app_client, other, foreign)["totalCount"] == 1
    assert (
        app_client.post(
            BASE + "/groups",
            headers=headers,
            json={"name": "a", "color": PALETTE[0], "userId": user.id},
        ).status_code
        == 422
    )


def test_empty_no_quote_sql_and_missing_default_is_error(
    app_client, headers, db_session
):
    d = default(app_client, headers)
    statements = []

    def capture(_conn, _cursor, statement, *_args):
        statements.append(statement)

    event.listen(db_session.get_bind(), "before_cursor_execute", capture)
    try:
        result = page(app_client, headers, d)
    finally:
        event.remove(db_session.get_bind(), "before_cursor_execute", capture)
    assert result["dataStatus"]["status"] == "EMPTY" and result["pageContext"]
    assert not any(
        "equity_daily" in sql or "equity_moneyflow" in sql for sql in statements
    )
    db_session.execute(delete(Group).where(Group.id == d))
    db_session.commit()
    assert (
        app_client.get(BASE + "/groups", headers=headers).json()["code"]
        == "WL_QUERY_FAILED"
    )
    assert (
        app_client.get(BASE + "/summary", headers=headers).json()["code"]
        == "WL_QUERY_FAILED"
    )
    assert db_session.get(Group, d) is None


def test_same_day_fields_zero_missing_and_delayed(app_client, headers, db_session):
    d = default(app_client, headers)
    seed(
        db_session,
        security(),
        security("600000.SH"),
        EquityDailyBar(
            ts_code="000001.SZ", trade_date=DAY, close=12.34, pct_chg=0, vol=1234567
        ),
        EquityDailyBasic(
            ts_code="000001.SZ",
            trade_date=DAY,
            pe_ttm=5.62,
            pb=0.71,
            volume_ratio=1.08,
            turnover_rate=0,
        ),
        EquityMoneyflow(ts_code="000001.SZ", trade_date=DAY, net_mf_amount=-2189.4),
        EquityDailyBasic(ts_code="600000.SH", trade_date=PRIOR, pe_ttm=999, pb=999),
    )
    add(app_client, headers, d)
    result = page(app_client, headers, d, tradeDate=str(DAY))
    row = result["items"][0]
    assert row["quote"] == dict(price=12.34, changePct=0, vol=1234567, direction="FLAT")
    assert row["valuation"] == dict(peTtm=5.62, pb=0.71)
    assert row["activity"] == dict(volumeRatio=1.08, turnoverRate=0)
    assert row["moneyFlow"] == dict(netAmount=-2189.4, direction="DOWN")
    assert not row["missingFields"] and result["dataStatus"]["status"] == "READY"
    assert (
        page(app_client, headers, d, tradeDate="2026-09-03")["dataStatus"]["status"]
        == "DELAYED"
    )
    add(app_client, headers, d, "600000.SH")
    result = page(app_client, headers, d, tradeDate="2026-09-03")
    assert result["dataStatus"]["status"] == "PARTIAL"
    assert result["items"][1]["valuation"] == dict(peTtm=None, pb=None)
    db_session.delete(db_session.get(Security, "600000.SH"))
    db_session.commit()
    assert page(app_client, headers, d)["items"][1]["stock"]["name"] == "--"


def test_precommit_count_failure_rolls_back_and_commit_unknown_is_distinct(
    app_client, db_session, headers
):
    d = default(app_client, headers)
    seed(db_session, security())
    with patch.object(
        WatchlistGroupQuery, "count_memberships", side_effect=RuntimeError("secret sql")
    ):
        response = app_client.put(f"{BASE}/groups/{d}/items/000001.SZ", headers=headers)
    assert (
        response.json()["code"] == "WL_WRITE_FAILED" and "secret" not in response.text
    )
    assert db_session.scalar(select(Membership.id)) is None
    with patch.object(
        db_session, "commit", side_effect=ConnectionError("commit response lost")
    ):
        response = app_client.put(f"{BASE}/groups/{d}/items/000001.SZ", headers=headers)
    assert (
        response.status_code == 503
        and response.json()["code"] == "WL_WRITE_OUTCOME_UNKNOWN"
    )


def test_cursor_context_and_external_pin_refresh_boundary(
    app_client, headers, db_session
):
    d = default(app_client, headers)
    for i in range(1, 4):
        seed(db_session, security(f"{i:06d}.SZ"))
        add(app_client, headers, d, f"{i:06d}.SZ")
    first = page(app_client, headers, d, limit=2)
    token = first["nextCursor"]
    a = create(app_client, headers)
    assert (
        app_client.get(
            f"{BASE}/groups/{a}/items", headers=headers, params={"cursor": token}
        ).json()["code"]
        == "WL_CURSOR_INVALID"
    )
    assert (
        app_client.get(
            f"{BASE}/groups/{d}/items",
            headers=headers,
            params={"cursor": token, "sortBy": "price", "direction": "desc"},
        ).json()["code"]
        == "WL_CURSOR_INVALID"
    )
    last = page(app_client, headers, d)["items"][-1]["membershipId"]
    action(app_client, headers, d, "pin", [last])
    assert page(app_client, headers, d, cursor=token)["items"] == []
    assert page(app_client, headers, d)["items"][0]["membershipId"] == last


def test_batch_mixed_eligibility_is_checked_once_and_is_atomic(
    app_client, headers, db_session
):
    d = default(app_client, headers)
    a = create(app_client, headers)
    seed(db_session, security(), security("000002.SZ"))
    for code in ("000001.SZ", "000002.SZ"):
        add(app_client, headers, d, code)
    ids = [row["membershipId"] for row in page(app_client, headers, d)["items"]]
    db_session.get(Security, "000002.SZ").list_status = "D"
    db_session.commit()
    original = WatchlistItemQuery.load_eligible_ts_codes
    calls = []

    def checked(self, session, codes):
        calls.append(codes)
        return original(self, session, codes)

    with patch.object(WatchlistItemQuery, "load_eligible_ts_codes", checked):
        response = action(app_client, headers, d, "move", ids, targetGroupId=a)
    assert response.json()["code"] == "WL_STOCK_NOT_ELIGIBLE"
    assert calls == [["000001.SZ", "000002.SZ"]]
    assert page(app_client, headers, a)["totalCount"] == 0
    assert [row["membershipId"] for row in page(app_client, headers, d)["items"]] == ids


@pytest.mark.parametrize(
    "table", ["wealth_watchlist_group", "wealth_watchlist_membership"]
)
def test_allocated_unsafe_id_is_server_failure_and_rolls_back(
    app_client, headers, db_session, table
):
    d = default(app_client, headers)
    seed(db_session, security())
    add(app_client, headers, d)
    # Only the fresh in-memory fixture sequence is modified, never a configured DB.
    db_session.execute(
        text("UPDATE app.sqlite_sequence SET seq=:maximum WHERE name=:name"),
        {"maximum": MAX_API_ID, "name": table},
    )
    db_session.commit()
    if table.endswith("group"):
        response = app_client.post(
            BASE + "/groups",
            headers=headers,
            json={"name": "超界", "color": PALETTE[0]},
        )
        assert len(groups(app_client, headers)) == 1
    else:
        seed(db_session, security("000002.SZ"))
        response = app_client.put(f"{BASE}/groups/{d}/items/000002.SZ", headers=headers)
        assert page(app_client, headers, d)["totalCount"] == 1
    assert response.status_code == 500 and response.json()["code"] == "WL_WRITE_FAILED"


def test_error_logs_have_context_but_no_credentials(app_client, headers, caplog):
    d = default(app_client, headers)
    response = action(app_client, headers, d, "remove", [MAX_API_ID])
    assert response.json()["code"] == "WL_SELECTION_STALE"
    record = next(
        record
        for record in caplog.records
        if getattr(record, "code", None) == "WL_SELECTION_STALE"
    )
    assert (record.action, record.groupId, record.count, record.exceptionType) == (
        "REMOVE",
        str(d),
        1,
        "WatchlistError",
    )
    assert isinstance(record.userId, int)
    assert headers["Authorization"] not in str(record.__dict__)


def test_same_day_quote_change_needs_first_page_refresh(
    app_client, headers, db_session
):
    d = default(app_client, headers)
    for i in (1, 2):
        code = f"{i:06d}.SZ"
        seed(
            db_session,
            security(code),
            EquityDailyBar(ts_code=code, trade_date=DAY, close=i, source="tushare"),
        )
        add(app_client, headers, d, code)
    params = dict(sortBy="price", direction="asc", tradeDate=str(DAY), limit=1)
    first = page(app_client, headers, d, **params)
    quote = db_session.get(EquityDailyBar, ("000002.SZ", DAY))
    quote.close = 0
    db_session.commit()
    assert (
        page(app_client, headers, d, cursor=first["nextCursor"], **params)["items"]
        == []
    )
    assert (
        page(app_client, headers, d, **params)["items"][0]["stock"]["tsCode"]
        == "000002.SZ"
    )
