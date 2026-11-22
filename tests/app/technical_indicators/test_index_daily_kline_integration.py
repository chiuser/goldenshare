from contextlib import asynccontextmanager
from datetime import date
from functools import partial

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from src.app.auth.dependencies import require_quote_access
from src.app.dependencies import index_daily_technical_indicators as integration
from src.app.dependencies.db import get_db_session
from src.app.exceptions.web import install_exception_handlers
from src.app.runtime.technical_indicators.composition import create_runtime
from src.biz.api.wealth.market.index_detail import build_router
from src.biz.api.wealth.market.index_detail_debug import build_router as build_debug_router
from src.foundation.clients.local_lake.index_daily_reader import IndexDailyLakeReader
from src.foundation.config.settings import Settings


PATH = "/wealth/market/index-detail/kline"
CODE = "000001.SH"
BEFORE_ORIGIN = date(1999, 12, 30)
ORIGIN, THU, FRI, SUN, MON = (date(2000, 1, day) for day in (4, 6, 7, 9, 10))
A500 = "000510.SH"
A500_PREVIOUS = date(2024, 9, 20)
A500_ORIGIN, A500_SECOND, A500_THIRD = (date(2024, 9, day) for day in (23, 24, 25))
STAR50 = "000688.SH"
STAR50_BASE, STAR50_ORIGIN = date(2019, 12, 31), date(2020, 1, 2)


def write_partition(root, day, *, close, code=CODE, **price_overrides):
    # Same DATE / VARCHAR / DOUBLE types and layout as the DG Silver producer.
    target = root / f"silver/index_daily/trade_date={day}/part-000.parquet"
    target.parent.mkdir(parents=True, exist_ok=True)
    prices = {"open": 10.0, "high": 13.0, "low": 9.0, "close": close,
              "pre_close": 10.0, "change_amount": 1.0, "pct_chg": 10.0, "vol": 123456.0, "amount": 1000.0}
    prices.update(price_overrides)
    columns = {"ts_code": [code], "trade_date": [day]}
    columns.update({name: pa.array([value], type=pa.float64()) for name, value in prices.items()})
    pq.write_table(pa.table(columns), target)
    return target


@pytest.fixture
def dg_client(tmp_path, monkeypatch):
    basic = tmp_path / "silver/index_basic/full/part-000.parquet"
    basic.parent.mkdir(parents=True)
    pq.write_table(pa.table({"ts_code": [CODE, STAR50, A500], "name": ["上证指数", "科创50", "中证A500"],
                             "market": ["SSE"] * 3, "publisher": ["SSE", "SSE", "CSI"], "category": ["综合"] * 3}), basic)
    calendar = tmp_path / "silver/calendar/trade_calendar/full/part-000.parquet"
    calendar.parent.mkdir(parents=True)
    pq.write_table(pa.table({
        "exchange": ["SSE"] * 17,
        "trade_date": [BEFORE_ORIGIN, ORIGIN, date(2000, 1, 5), THU, FRI, date(2000, 1, 8), SUN, MON,
                       STAR50_BASE, date(2020, 1, 1), STAR50_ORIGIN,
                       A500_PREVIOUS, date(2024, 9, 21), date(2024, 9, 22), A500_ORIGIN, A500_SECOND, A500_THIRD],
        "is_open": [True, True, False, True, True, False, False, True, True, False, True,
                    True, False, False, True, True, True],
        "pretrade_date": [None, BEFORE_ORIGIN, ORIGIN, ORIGIN, THU, FRI, FRI, FRI,
                          MON, STAR50_BASE, STAR50_BASE,
                          STAR50_ORIGIN, A500_PREVIOUS, A500_PREVIOUS, A500_PREVIOUS, A500_ORIGIN, A500_SECOND],
    }), calendar)
    partitions = {day: write_partition(tmp_path, day, close=float(10 + index))
                  for index, day in enumerate((ORIGIN, THU, FRI, MON))}
    for index, day in enumerate((A500_ORIGIN, A500_SECOND, A500_THIRD)):
        partitions[day] = write_partition(tmp_path, day, close=float(20 + index), code=A500)
    reads, encoded, calculated = [], [], []

    class ObservedReader(IndexDailyLakeReader):
        def factor_rows(self, **kwargs):
            raise AssertionError("the migrated route must not access technical-factor data")

    encode = integration.encode_response_utf8
    calculate = integration.TechnicalIndicatorService._calculate_result

    def observe_encoding(*args, **kwargs):
        encoded.append(True)
        return encode(*args, **kwargs)

    def observe_calculation(self, *args, **kwargs):
        calculated.append(True)
        return calculate(self, *args, **kwargs)

    monkeypatch.setattr(integration, "encode_response_utf8", observe_encoding)
    monkeypatch.setattr(integration.TechnicalIndicatorService, "_calculate_result", observe_calculation)
    @asynccontextmanager
    async def lifespan(app):
        runtime = create_runtime(Settings(_env_file=None, APP_ENV="local", GOLDENSHARE_LAKE_ROOT=str(tmp_path)))
        read = runtime.source.daily_rows

        def observe_read(dataset, code, dates, fields, **kwargs):
            reads.append((tuple(dates), tuple(fields)))
            return read(dataset, code, dates, fields, **kwargs)

        monkeypatch.setattr(runtime.source, "daily_rows", observe_read)
        app.state.technical_indicator_runtime = runtime
        try:
            yield
        finally:
            await runtime.aclose()

    app = FastAPI(lifespan=lifespan)
    app.dependency_overrides[get_db_session] = lambda: None
    app.dependency_overrides[require_quote_access] = lambda: None
    install_exception_handlers(app)
    reader = ObservedReader(tmp_path)
    runner = partial(integration.run_index_daily_kline, daily_lake=reader)
    app.include_router(build_router(daily_lake=reader, run_sse_kline=runner))
    app.include_router(build_debug_router(daily_lake=reader, run_sse_kline=runner))
    with TestClient(app) as client:
        yield client, partitions, reads, encoded, calculated


def test_sse_kline_reuses_page_and_uses_previous_trading_day(dg_client):
    client, _, reads, encoded, calculated = dg_client
    params = {"tsCode": " 000001.sh ", "endDate": str(MON), "limit": 1}
    response = client.get(PATH.replace("/kline", "/debug/kline"), params=params)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["meta"] == {"count": 1, "limit": 1, "startDate": None, "endDate": str(MON), "nextEndDate": str(FRI)}
    assert body["bars"][0]["tradeDate"] == str(MON)
    assert body["bars"][0]["close"] == 13.0
    assert body["bars"][0]["volDisplay"] == "12.35万"
    assert body["bars"][0]["amount"] == 1000.0
    assert body["bars"][0]["factors"]["macd"]["dif"] > 0
    assert body["debugInfo"]["modules"][0]["rowCount"] == 1
    assert [days for days, _ in reads] == [(MON,)]
    assert reads[0][1] == ("vol", "amount", "pre_close", "change_amount", "pct_chg")
    assert len(encoded) == len(calculated) == 1

    response = client.get(PATH.replace("/kline", "/debug/kline"), params={**params, "endDate": body["meta"]["nextEndDate"]})
    assert response.status_code == 200, response.text
    assert [bar["tradeDate"] for bar in response.json()["bars"]] == [str(FRI)]
    assert response.json()["meta"]["nextEndDate"] == str(THU)

    response = client.get(PATH.replace("/kline", "/debug/kline"), params={**params, "endDate": str(SUN), "startDate": str(FRI)})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["meta"]["endDate"] == str(SUN)
    assert body["meta"]["nextEndDate"] is None
    assert body["dataStatus"]["status"] == "READY"
    assert body["dataStatus"]["expectedTradeDate"] == body["dataStatus"]["observedTradeDate"] == str(FRI)
    assert body["debugInfo"]["modules"][0]["expectedTradeDate"] == str(FRI)


def test_sse_kline_origin_short_page_and_empty_page(dg_client):
    client, _, reads, encoded, calculated = dg_client
    response = client.get(PATH, params={"tsCode": CODE, "endDate": str(FRI)})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["meta"]["limit"] == 300
    assert body["meta"]["count"] == 3
    assert body["meta"]["nextEndDate"] is None
    assert body["debugInfo"] is None
    for bar in body["bars"]:
        assert set(bar["factors"]["ma"].values()) == {None}
        assert set(bar["factors"]["boll"].values()) == {None}
    assert body["bars"][0]["factors"]["macd"] == {"dif": 0, "dea": 0, "macd": 0}
    assert [days for days, _ in reads] == [(ORIGIN, THU, FRI)]

    response = client.get(PATH, params={"tsCode": CODE, "endDate": str(BEFORE_ORIGIN)})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["bars"] == [] and body["dataStatus"]["status"] == "EMPTY"
    assert body["meta"]["nextEndDate"] is None
    assert len(reads) == len(calculated) == 1
    assert len(encoded) == 2


@pytest.mark.parametrize("missing_file", [True, False])
def test_sse_kline_rejects_missing_bar_or_close(dg_client, tmp_path, missing_file):
    client, partitions, reads, encoded, calculated = dg_client
    if missing_file:
        partitions[FRI].unlink()
    else:
        write_partition(tmp_path, FRI, close=None)
    response = client.get(PATH, params={"tsCode": CODE, "endDate": str(MON)})
    assert response.status_code == 500, response.text
    body = response.json()
    assert body["code"] == "ID_QUERY_FAILED"
    assert CODE in body["message"]
    assert "request_id" in body
    assert not reads and not encoded
    assert len(calculated) == 1


def test_a500_kline_paginates_and_stops_at_its_verified_origin(dg_client, tmp_path):
    client, _, reads, encoded, calculated = dg_client
    # A real file path that must never be opened by an A500 calculation.
    before_origin = tmp_path / f"silver/index_daily/trade_date={A500_PREVIOUS}/part-000.parquet"
    before_origin.parent.mkdir()
    before_origin.write_bytes(b"not a parquet file")

    first = client.get(PATH, params={"tsCode": A500, "endDate": str(A500_THIRD), "limit": 2})
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["indexRef"]["tsCode"] == A500
    assert [bar["close"] for bar in body["bars"]] == [21.0, 22.0]
    assert body["bars"][0]["volDisplay"] == "12.35万"
    assert body["bars"][0]["amount"] == 1000.0
    # The first visible bar uses the preceding source bar for MACD.
    assert body["bars"][0]["factors"]["macd"]["dif"] > 0
    assert body["meta"]["nextEndDate"] == str(A500_ORIGIN)

    debug_path = PATH.replace("/kline", "/debug/kline")
    last = client.get(debug_path, params={"tsCode": A500, "endDate": body["meta"]["nextEndDate"], "limit": 1})
    assert last.status_code == 200, last.text
    body = last.json()
    assert body["meta"]["nextEndDate"] is None  # Full page at the origin still ends pagination.
    assert [bar["tradeDate"] for bar in body["bars"]] == [str(A500_ORIGIN)]
    assert body["bars"][0]["factors"]["macd"] == {"dif": 0, "dea": 0, "macd": 0}
    assert set(body["bars"][0]["factors"]["ma"].values()) == {None}
    assert set(body["bars"][0]["factors"]["boll"].values()) == {None}

    empty = client.get(debug_path, params={"tsCode": A500, "endDate": str(A500_PREVIOUS), "limit": 500})
    assert empty.status_code == 200, empty.text
    assert empty.json()["meta"]["nextEndDate"] is None
    assert empty.json()["bars"] == []
    assert empty.json()["debugInfo"]["exceptions"][0]["message"] == "指数日线无可用数据"
    assert [days for days, _ in reads] == [(A500_SECOND, A500_THIRD), (A500_ORIGIN,)]
    assert len(calculated) == 2
    assert len(encoded) == 3


@pytest.mark.parametrize("missing_date", [A500_ORIGIN, A500_SECOND])
def test_a500_kline_rejects_a_missing_warmup_bar(dg_client, missing_date):
    client, partitions, reads, _, _ = dg_client
    partitions[missing_date].unlink()
    response = client.get(PATH, params={"tsCode": A500, "endDate": str(A500_THIRD), "limit": 1})
    assert response.status_code == 500, response.text
    assert response.json()["code"] == "ID_QUERY_FAILED"
    assert not reads


def test_star50_kline_starts_after_the_close_only_index_base(dg_client, tmp_path):
    client, _, _, _, calculated = dg_client
    # The DG 2019-12-31 row records the published index base value of 1,000.
    write_partition(tmp_path, STAR50_BASE, code=STAR50, open=None, high=None, low=None, close=1000.0)
    write_partition(tmp_path, STAR50_ORIGIN, code=STAR50, open=1005.6174, high=1019.9098,
                    low=1005.6174, close=1019.7234)

    response = client.get(PATH, params={"tsCode": STAR50, "endDate": str(STAR50_ORIGIN), "limit": 1})
    assert response.status_code == 200, response.text
    assert response.json()["meta"]["nextEndDate"] is None
    assert response.json()["bars"][0]["close"] == 1019.7234
    assert response.json()["bars"][0]["factors"]["macd"] == {"dif": 0, "dea": 0, "macd": 0}

    response = client.get(PATH, params={"tsCode": STAR50, "endDate": str(STAR50_BASE), "limit": 1})
    assert response.status_code == 200, response.text
    assert response.json()["bars"] == []
    assert len(calculated) == 1


@pytest.mark.parametrize("path", [PATH, PATH.replace("/kline", "/debug/kline")])
@pytest.mark.parametrize("ts_code", [CODE, A500, "899050.BJ"])
def test_local_daily_limit_rejects_501_before_reading(dg_client, monkeypatch, path, ts_code):
    client, _, reads, encoded, calculated = dg_client

    def unexpected_read(*args, **kwargs):
        pytest.fail("oversized requests must be rejected before reading index identity or calendar")

    monkeypatch.setattr(IndexDailyLakeReader, "index_identity", unexpected_read)
    monkeypatch.setattr(IndexDailyLakeReader, "calendar_rows", unexpected_read)
    response = client.get(path, params={"tsCode": ts_code, "endDate": str(A500_THIRD), "limit": 501})
    assert response.status_code == 400, response.text
    assert response.json()["code"] == "ID_REQUEST_INVALID"
    assert not (reads or encoded or calculated)
