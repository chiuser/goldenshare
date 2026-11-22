from datetime import date, datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from sqlalchemy import event

from src.app.auth.dependencies import require_quote_access
from src.app.dependencies.db import get_db_session
from src.app.exceptions.web import install_exception_handlers
from src.biz.api.wealth.market import index_detail, index_detail_debug, index_detail_nine_turn
from src.foundation.clients.local_lake.index_daily_reader import IndexDailyLakeReader
from src.foundation.models.core.index_daily_basic import IndexDailyBasic
from src.foundation.models.core.index_weight import IndexWeight
from src.foundation.models.core_serving.index_nineturn_daily import IndexNineTurnDaily


BASE = "/api/v1/wealth/market/index-detail"
CODE = "399001.SZ"
STAR = "000688.SH"
WED, THU, FRI, SAT, SUN, MON = (date(2026, 11, day) for day in range(18, 24))


def write_daily(root, day, *, ts_code=CODE, row_day=None, **overrides):
    # Match the DG Silver DATE/VARCHAR/DOUBLE contract verified on 2026-11-20.
    path = root / f"silver/index_daily/trade_date={day}/part-000.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = dict(open=101.0, high=103.0, low=99.0, close=102.0, pre_close=100.0,
                  change_amount=2.0, pct_chg=2.0, vol=123456.0, amount=654321.0)
    fields.update(overrides)
    pq.write_table(pa.table({
        "ts_code": [ts_code], "trade_date": [row_day or day],
        **{name: pa.array([value], type=pa.float64()) for name, value in fields.items()},
    }), path)


@pytest.fixture
def local_index_client(tmp_path, db_session, monkeypatch):
    basic = tmp_path / "silver/index_basic/full/part-000.parquet"
    basic.parent.mkdir(parents=True)
    pq.write_table(pa.table({
        "ts_code": [CODE, STAR], "name": ["DG 深证成指", "DG 科创50"], "market": ["SZSE", "SSE"],
        "publisher": ["SZSE", "SSE"], "category": ["综合", "成份"],
    }), basic)
    calendar = tmp_path / "silver/calendar/trade_calendar/full/part-000.parquet"
    calendar.parent.mkdir(parents=True)
    pq.write_table(pa.table({
        "exchange": ["SSE"] * 6, "trade_date": [WED, THU, FRI, SAT, SUN, MON],
        "is_open": [True, True, True, False, False, True],
        "pretrade_date": [date(2026, 11, 17), WED, THU, FRI, FRI, FRI],
    }), calendar)
    for day in (WED, THU, FRI):
        write_daily(tmp_path, day)
    write_daily(tmp_path, date(2019, 12, 31), ts_code=STAR, open=None, high=None, low=None, close=1000.0)
    engine = db_session.get_bind()
    for table in (IndexDailyBasic.__table__, IndexWeight.__table__, IndexNineTurnDaily.__table__):
        table.create(engine, checkfirst=True)
    db_session.add_all([
        IndexNineTurnDaily(ts_code=CODE, trade_date=day, close=102.0, up_count=count, down_count=0,
                           nine_up_turn="+9" if count == 9 else None, formula_version=1,
                           published_at=datetime(2026, 11, 20, tzinfo=timezone.utc))
        for day, count in ((WED, 9), (FRI, 0))
    ])
    db_session.commit()

    def reject_factor_files(*args, **kwargs):
        pytest.fail("local requests must not read DG index daily technical factors")

    def reject_legacy_sql(conn, cursor, statement, parameters, context, executemany):
        assert not any(name in statement.lower() for name in (
            "index_factor_pro", "index_daily_serving", "index_basic", "trade_calendar",
        )), statement

    monkeypatch.setattr(IndexDailyLakeReader, "factor_dates", reject_factor_files)
    monkeypatch.setattr(IndexDailyLakeReader, "factor_rows", reject_factor_files)
    reader = IndexDailyLakeReader(tmp_path)
    app = FastAPI()
    install_exception_handlers(app)
    app.dependency_overrides[get_db_session] = lambda: db_session
    app.dependency_overrides[require_quote_access] = lambda: None
    for module in (index_detail, index_detail_debug, index_detail_nine_turn):
        app.include_router(module.build_router(daily_lake=reader), prefix="/api/v1")
    event.listen(engine, "before_cursor_execute", reject_legacy_sql)
    try:
        with TestClient(app) as client:
            yield client
    finally:
        event.remove(engine, "before_cursor_execute", reject_legacy_sql)


@pytest.mark.parametrize("path", ["/page-init", "/debug/page-init"])
def test_local_page_init_uses_one_dg_bar_and_preserves_latest_published_anchor(local_index_client, path):
    response = local_index_client.get(BASE + path, params={"tsCode": CODE, "tradeDate": str(MON)})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["pageContext"]["tradeDate"] == str(MON)
    assert body["pageContext"]["isTradingDay"]
    assert body["asOfTradeDate"] == body["quote"]["tradeDate"] == str(FRI)
    assert body["index"]["name"] == "DG 深证成指"
    assert body["quote"]["point"] == 102.0
    assert (body["quote"]["vol"], body["quote"]["amount"]) == (123456.0, 654321.0)
    assert body["quote"]["volDisplay"] == "12.35万"
    if path.startswith("/debug"):
        quote = next(row for row in body["debugInfo"]["modules"] if row["module"] == "quote")
        assert quote["status"] == "DELAYED"


def test_local_page_init_null_quantity_and_pre_origin_are_distinct(local_index_client, tmp_path):
    write_daily(tmp_path, FRI, amount=None)
    reply = local_index_client.get(BASE + "/debug/page-init", params={"tsCode": CODE, "tradeDate": str(SUN)})
    assert reply.status_code == 200, reply.text
    body = reply.json()
    assert body["quote"]["amount"] is None and body["quote"]["vol"] == 123456.0
    assert body["asOfTradeDate"] == str(FRI)
    assert body["dataStatus"]["status"] == "PARTIAL"
    missing = next(row for row in body["debugInfo"]["exceptions"] if row["code"] == "ID_FACTOR_PARTIAL")
    assert missing["message"] == "DG 普通指数日线缺失成交额"

    reply = local_index_client.get(BASE + "/page-init", params={"tsCode": STAR, "tradeDate": "2019-12-31"})
    assert reply.status_code == 200, reply.text
    body = reply.json()
    assert body["quote"] is body["asOfTradeDate"] is None
    assert body["dataStatus"]["status"] == "EMPTY"


def test_local_nine_turn_keeps_sql_results_and_uses_dg_dates_for_alignment_and_cursor(local_index_client):
    params = {"tsCode": CODE, "startDate": str(WED), "endDate": str(FRI), "limit": 3, "debug": 1}
    reply = local_index_client.get(BASE + "/nine-turn", params=params)
    assert reply.status_code == 200, reply.text
    body = reply.json()
    assert [row["tradeDate"] for row in body["markers"]] == [str(WED)]
    assert body["dataStatus"]["code"] == "NT_ALIGNMENT_PARTIAL"
    assert (body["meta"]["sourceRowCount"], body["meta"]["matchedRowCount"], body["meta"]["missingRowCount"]) == (3, 2, 1)
    assert body["latestMarker"] is None
    assert body["debugInfo"]["sourceTables"] == ["silver/index_daily", "core_serving.index_nineturn_daily"]

    params["limit"] = 2
    reply = local_index_client.get(BASE + "/nine-turn", params=params)
    assert reply.status_code == 200, reply.text
    first = reply.json()
    assert first["meta"]["sourceRowCount"] == 2 and first["meta"]["hasMore"]
    assert first["meta"]["observedStartDate"] == str(FRI) and first["markers"] == []
    reply = local_index_client.get(BASE + "/nine-turn", params={**params, "cursor": first["meta"]["nextCursor"]})
    assert reply.status_code == 200, reply.text
    second = reply.json()
    assert second["meta"]["sourceRowCount"] == 1 and not second["meta"]["hasMore"]
    assert second["meta"]["nextCursor"] is None
    assert [(row["tradeDate"], row["sequenceNumber"]) for row in second["markers"]] == [(str(WED), 9)]


@pytest.mark.parametrize("wrong_partition_key", [False, True])
def test_local_nine_turn_fails_when_required_dg_bar_is_missing(local_index_client, tmp_path, wrong_partition_key):
    if wrong_partition_key:
        write_daily(tmp_path, THU, row_day=FRI)
    else:
        write_daily(tmp_path, THU, ts_code=STAR)
    reply = local_index_client.get(BASE + "/nine-turn", params={"tsCode": CODE, "endDate": str(FRI), "limit": 2})
    assert reply.status_code == 500, reply.text
    assert reply.json()["code"] == "NT_QUERY_FAILED"
