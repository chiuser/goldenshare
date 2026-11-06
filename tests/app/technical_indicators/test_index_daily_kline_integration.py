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
from src.biz.services.wealth.market.index_detail.index_detail_universe import IndexDetailUniverseService
from src.foundation.clients.local_lake.index_daily_reader import IndexDailyLakeReader
from src.foundation.config.settings import Settings


PATH = "/wealth/market/index-detail/kline"
CODE = "000001.SH"
BEFORE_ORIGIN = date(1999, 12, 30)
ORIGIN, THU, FRI, SUN, MON = (date(2000, 1, day) for day in (4, 6, 7, 9, 10))


def write_partition(root, day, *, close):
    # Same DATE / VARCHAR / DOUBLE types and layout as the DG Silver producer.
    target = root / f"silver/index/index_factor_pro/trade_date={day}/part-000.parquet"
    target.parent.mkdir(parents=True, exist_ok=True)
    prices = {"open": 10.0, "high": 13.0, "low": 9.0, "close": close,
              "pre_close": 10.0, "change": 1.0, "pct_change": 10.0, "vol": 123456.0, "amount": 1000.0}
    columns = {"ts_code": [CODE], "trade_date": [day]}
    columns.update({name: pa.array([value], type=pa.float64()) for name, value in prices.items()})
    pq.write_table(pa.table(columns), target)
    return target


@pytest.fixture
def dg_client(tmp_path, monkeypatch):
    basic = tmp_path / "silver/index_basic/full/part-000.parquet"
    basic.parent.mkdir(parents=True)
    pq.write_table(pa.table({"ts_code": [CODE], "name": ["上证指数"], "market": ["SSE"],
                             "publisher": ["SSE"], "category": ["综合"]}), basic)
    calendar = tmp_path / "silver/calendar/trade_calendar/full/part-000.parquet"
    calendar.parent.mkdir(parents=True)
    pq.write_table(pa.table({
        "exchange": ["SSE"] * 6,
        "trade_date": [BEFORE_ORIGIN, ORIGIN, THU, FRI, SUN, MON],
        "is_open": [True, True, True, True, False, True],
        "pretrade_date": [None, BEFORE_ORIGIN, ORIGIN, THU, FRI, FRI],
    }), calendar)
    partitions = {day: write_partition(tmp_path, day, close=float(10 + index))
                  for index, day in enumerate((ORIGIN, THU, FRI, MON))}
    reads, encoded, calculated = [], [], []

    class ObservedReader(IndexDailyLakeReader):
        def factor_rows(self, **kwargs):
            reads.append((tuple(kwargs["dates"]), tuple(kwargs["columns"])))
            return super().factor_rows(**kwargs)

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
    monkeypatch.setattr(IndexDetailUniverseService, "require_supported", lambda self, code: None)

    @asynccontextmanager
    async def lifespan(app):
        runtime = create_runtime(Settings(_env_file=None))
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
    app.include_router(build_router(daily_lake=reader, run_sse_kline=partial(
        integration.run_index_daily_kline, daily_lake=reader,
    )))
    with TestClient(app) as client:
        yield client, partitions, reads, encoded, calculated


def test_sse_kline_reuses_page_and_uses_previous_trading_day(dg_client):
    client, _, reads, encoded, calculated = dg_client
    params = {"tsCode": " 000001.sh ", "endDate": str(MON), "limit": 1, "debug": 1}
    response = client.get(PATH, params=params)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["meta"] == {"count": 1, "limit": 1, "startDate": None, "endDate": str(MON), "nextEndDate": str(FRI)}
    assert body["bars"][0]["tradeDate"] == str(MON)
    assert body["bars"][0]["close"] == 13.0
    assert body["bars"][0]["volDisplay"] == "12.35万"
    assert body["bars"][0]["amount"] == 1000.0
    assert body["bars"][0]["factors"]["macd"]["dif"] > 0
    assert body["debugInfo"]["modules"][0]["rowCount"] == 1
    assert [days for days, _ in reads] == [(MON,), (ORIGIN, THU, FRI)]
    assert reads[1][1] == ("trade_date", "high", "low", "close")
    assert len(encoded) == len(calculated) == 1

    response = client.get(PATH, params={**params, "endDate": body["meta"]["nextEndDate"]})
    assert response.status_code == 200, response.text
    assert [bar["tradeDate"] for bar in response.json()["bars"]] == [str(FRI)]
    assert response.json()["meta"]["nextEndDate"] == str(THU)

    response = client.get(PATH, params={**params, "endDate": str(SUN), "startDate": str(FRI)})
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
        reason = "日线行情文件读取失败"
    else:
        write_partition(tmp_path, FRI, close=None)
        reason = "收盘价缺失"
    response = client.get(PATH, params={"tsCode": CODE, "endDate": str(MON)})
    assert response.status_code == 500, response.text
    body = response.json()
    assert body["code"] == "ID_QUERY_FAILED"
    assert f"{CODE} {FRI} {reason}" in body["message"]
    assert "request_id" in body
    assert len(reads) == 1
    assert not calculated and not encoded
