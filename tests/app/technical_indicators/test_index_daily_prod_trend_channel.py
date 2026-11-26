"""Prod wiring against a new disposable PostgreSQL; no configured DB is used."""

from contextlib import asynccontextmanager
from datetime import date
from functools import partial

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy.orm import sessionmaker

from src.app.auth.dependencies import require_quote_access
from src.app.dependencies import index_daily_technical_indicators as execution
from src.app.dependencies.db import get_db_session
from src.app.exceptions.web import install_exception_handlers
from src.app.runtime.technical_indicators.composition import create_runtime
from src.biz.api.wealth.market.index_detail import build_router
from src.biz.api.wealth.market.index_detail_debug import (
    build_router as build_debug_router,
)
from src.foundation.config.settings import Settings
from src.foundation.models.core.index_basic import IndexBasic
from src.foundation.models.core.index_factor_pro import IndexFactorPro
from src.foundation.models.core.trade_calendar import TradeCalendar
from src.foundation.models.core_serving.index_daily_serving import IndexDailyServing
from tests.wealth_watchlist_postgres_support import isolated_postgres


def test_prod_sse_daily_four_rails_normal_debug_and_next_page(tmp_path, monkeypatch):
    pg = tmp_path / "pg"
    pg.mkdir()
    days = [date(2010, 1, n) for n in (4, 5, 6)]
    # Producers: IndexDailyServing Numeric fields and TradeCalendar DATE/bool.
    # Constant high/low gives an independently known EMA for every output.
    with isolated_postgres(pg) as engine:
        sessions = sessionmaker(engine)
        monkeypatch.setattr(execution, "get_session_factory", lambda: sessions)
        with engine.begin() as conn:
            conn.exec_driver_sql("CREATE SCHEMA core_serving")
            for model in (IndexBasic, IndexFactorPro, TradeCalendar, IndexDailyServing):
                model.__table__.create(conn)
            conn.execute(
                IndexBasic.__table__.insert(),
                {"ts_code": "000001.SH", "name": "上证指数", "market": "SSE"},
            )
            conn.execute(
                TradeCalendar.__table__.insert(),
                [
                    dict(
                        exchange="SSE",
                        trade_date=day,
                        is_open=True,
                        pretrade_date=days[i - 1] if i else date(2009, 12, 31),
                    )
                    for i, day in enumerate(days)
                ],
            )
            conn.execute(
                IndexDailyServing.__table__.insert(),
                [
                    dict(
                        ts_code="000001.SH",
                        trade_date=day,
                        open=10,
                        high=13,
                        low=9,
                        close=11,
                        pre_close=10,
                        change_amount=1,
                        pct_chg=10,
                        vol=1234,
                        amount=2345,
                    )
                    for day in days
                ],
            )
            conn.execute(
                IndexFactorPro.__table__.insert(),
                dict(
                    ts_code="000001.SH",
                    trade_date=days[-1],
                    open=77,
                    high=79,
                    low=76,
                    close=78,
                    source="tushare",
                    pre_close=77,
                    change=1,
                    pct_change=1,
                    vol=456,
                    amount=789,
                ),
            )
        calls = []
        calculate = execution.TechnicalIndicatorService._calculate_result

        def observe(service, prepared, **kwargs):
            calls.append(prepared.request)
            return calculate(service, prepared, **kwargs)

        monkeypatch.setattr(
            execution.TechnicalIndicatorService, "_calculate_result", observe
        )
        settings = Settings(
            _env_file=None, APP_ENV="prod", TECHNICAL_INDICATOR_BATCH_ROWS=2
        )

        @asynccontextmanager
        async def lifespan(app):
            runtime = create_runtime(settings, session_factory=sessions)
            app.state.technical_indicator_runtime = runtime
            try:
                yield
            finally:
                await runtime.aclose()

        def session():
            with sessions() as active:
                yield active

        app = FastAPI(lifespan=lifespan)
        app.dependency_overrides[get_db_session] = session
        app.dependency_overrides[require_quote_access] = lambda: None
        install_exception_handlers(app)
        runner = partial(execution.run_index_daily_kline, daily_lake=None)
        app.include_router(build_router(run_sse_kline=runner))
        app.include_router(build_debug_router(run_sse_kline=runner))
        with TestClient(app) as client:
            params = {
                "tsCode": "000001.SH",
                "period": "day",
                "endDate": str(days[-1]),
                "limit": 2,
            }
            base = "/wealth/market/index-detail"
            normal = client.get(base + "/kline", params=params)
            debug = client.get(base + "/debug/kline", params=params)
            assert normal.status_code == debug.status_code == 200, (
                normal.text,
                debug.text,
            )
            first = normal.json()
            assert first["bars"] == debug.json()["bars"]
            assert [bar["tradeDate"] for bar in first["bars"]] == [
                "2010-01-05",
                "2010-01-06",
            ]
            assert first["meta"]["nextEndDate"] == "2010-01-04"
            assert (
                "nineTurnMarkers" not in first and "nineTurnMarkers" not in debug.json()
            )
            for bar in first["bars"]:
                assert bar["factors"]["trendChannel"] == pytest.approx(
                    {
                        "shortUpper": 13.0,
                        "shortLower": 9.0,
                        "longUpper": 13.0,
                        "longLower": 9.0,
                    },
                    abs=0.01,
                )
                assert bar["factors"]["ma"]["ma250"] is None
                assert bar["vol"] == 1234 and bar["amount"] == 2345
            previous = client.get(
                base + "/kline",
                params={**params, "endDate": first["meta"]["nextEndDate"]},
            )
            assert previous.status_code == 200, previous.text
            assert previous.json()["meta"]["nextEndDate"] is None
            assert previous.json()["bars"][0]["factors"][
                "trendChannel"
            ] == pytest.approx(
                {
                    "shortUpper": 13.0,
                    "shortLower": 9.0,
                    "longUpper": 13.0,
                    "longLower": 9.0,
                },
                abs=0.01,
            )
            legacy = client.get(base + "/kline", params={**params, "limit": 501})
            assert legacy.status_code == 200, legacy.text
            assert legacy.json()["bars"][0]["close"] == 78
            assert "trendChannel" not in legacy.json()["bars"][0]["factors"]
            assert "nineTurnMarkers" not in legacy.json()
            assert len(calls) == 3
            assert [item["calculation_id"] for item in calls[0].calculations] == [
                *(["ma"] * 7),
                "boll",
                "macd",
                "kdj",
                "trend_channel",
            ]
        assert engine.pool.checkedout() == 0
