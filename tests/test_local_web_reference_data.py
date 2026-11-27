import asyncio
from datetime import date, datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import duckdb
import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, literal, select
from sqlalchemy.orm import Session

from src.app.auth.dependencies import require_quote_access
from src.app.dependencies import db
from src.app.dependencies import stock_daily_technical_indicators as stock_daily
from src.app.exceptions import install_exception_handlers
from src.app.runtime.reference_data import build_reference_data
from src.biz.api import market
from src.biz.api.wealth.market import stock_search
from src.biz.api.wealth.market.trading_assistant.errors import TradingAssistantRoute
from src.biz.queries.wealth.market.context.market_page_context_query import (
    MarketPageContextQuery,
)
from src.biz.queries.wealth.market.leaderboards.equity_rankings_query import (
    LeaderboardEquityRankingsQuery,
)
from src.biz.queries.wealth.market.sector_analysis.sector_momentum_query import (
    SectorMomentumQuery,
)
from src.biz.queries.wealth.market.trading_assistant.record_scope import (
    read_record_names,
)
from src.biz.services.wealth.market.stock_detail.stock_daily_kline_contracts import (
    StockDailyKlineRequest,
)
from src.biz.services.wealth.market.trading_assistant.execution_policy import (
    Deadline,
    TradingAssistantExecutionPolicyV1,
)
from src.foundation.clients.local_lake import reference_data_reader
from src.foundation.clients.reference_data import (
    ReferenceDataReadError,
    bind_reference_data,
)
from src.foundation.clients.reference_data_relations import (
    calendar_relation,
    security_relation,
)
from src.foundation.config.settings import Settings
from src.foundation.models.core.dc_daily import DcDaily
from src.foundation.models.core_serving.equity_daily_bar import EquityDailyBar
from src.foundation.models.core_serving.equity_daily_basic import EquityDailyBasic
from tests.wealth_watchlist_postgres_support import isolated_postgres


@pytest.fixture
def lake(tmp_path):
    # Both projections match the physical DG Parquet descriptions. All stock
    # fields in Raw are VARCHAR, including its two YYYYMMDD date columns.
    stock = tmp_path / "raw/tushare/stock_basic/full/part-000.parquet"
    calendar = tmp_path / "silver/calendar/trade_calendar/full/part-000.parquet"
    for path in (stock, calendar):
        path.parent.mkdir(parents=True)
    with duckdb.connect() as connection:
        connection.execute(
            """
            COPY (SELECT ts_code, name, symbol, NULL::VARCHAR AS area, NULL::VARCHAR AS industry,
                         NULL::VARCHAR AS fullname, NULL::VARCHAR AS enname, cnspell,
                         '主板'::VARCHAR AS market, exchange, 'CNY'::VARCHAR AS curr_type,
                         list_status, list_date, delist_date, NULL::VARCHAR AS is_hs,
                         NULL::VARCHAR AS act_name, NULL::VARCHAR AS act_ent_type
                  FROM (VALUES
                    ('000001.SZ','平安银行','000001','PAYH','SZSE','L','19910403',NULL),
                    ('600005.SH','武钢股份(退)','600005','WGGF','SSE','D','19990803','20170214'),
                    ('600519.SH','贵州茅台','600519','GZMT','SSE','L','20010827',NULL)
                  ) AS source(ts_code,name,symbol,cnspell,exchange,list_status,list_date,delist_date)
            ) TO ? (FORMAT PARQUET)
        """,
            [str(stock)],
        )
        connection.execute(
            """
            COPY (SELECT * FROM (VALUES
                ('SSE',DATE '2026-12-30',true,NULL),
                ('SSE',DATE '2026-12-31',true,DATE '2026-12-30'),
                ('SSE',DATE '2027-01-01',false,DATE '2026-12-31'),
                ('SSE',DATE '2027-01-04',true,DATE '2026-12-31')
            ) AS source(exchange,trade_date,is_open,pretrade_date)) TO ? (FORMAT PARQUET)
        """,
            [str(calendar)],
        )
    return tmp_path


def local_settings(lake):
    return Settings(_env_file=None, APP_ENV="local", GOLDENSHARE_LAKE_ROOT=str(lake))


def test_local_web_api_reads_both_files_with_no_serving_tables(lake, monkeypatch):
    app = FastAPI()
    app.state.reference_data = build_reference_data(local_settings(lake))
    app.include_router(market.router)
    app.include_router(stock_search.router)
    app.dependency_overrides[require_quote_access] = lambda: None
    engine = create_engine("sqlite+pysqlite://")

    @event.listens_for(engine, "before_cursor_execute")
    def reject_old_tables(
        connection, cursor, statement, parameters, context, executemany
    ):
        assert "security_serving" not in statement and "trade_calendar" not in statement

    def sessions():
        with Session(engine) as session:
            yield session

    monkeypatch.setattr(db, "get_session", sessions)
    with TestClient(app) as client:
        response = client.get(
            "/market/trade-calendar",
            params=dict(
                start_date="2026-12-31",
                end_date="2027-01-01",
            ),
        )
        assert response.status_code == 200
        assert response.json()["items"] == [
            {
                "trade_date": "2026-12-31",
                "is_open": True,
                "pretrade_date": "2026-12-30",
            },
            {
                "trade_date": "2027-01-01",
                "is_open": False,
                "pretrade_date": "2026-12-31",
            },
        ]
        response = client.get(
            "/market/trade-calendar",
            params=dict(
                exchange="SZSE",
                start_date="2027-01-01",
                end_date="2027-01-01",
            ),
        )
        assert response.status_code == 200 and response.json()["items"] == []
        response = client.get(
            "/wealth/market/stock-search", params={"keyword": "000001"}
        )
        assert response.status_code == 200
        assert response.json()["items"] == [{"tsCode": "000001.SZ", "name": "平安银行"}]
    engine.dispose()


def test_local_page_anchor_and_stock_lifecycle(lake):
    with Session() as session:
        reference = build_reference_data(local_settings(lake))
        bind_reference_data(session, reference)
        context = MarketPageContextQuery().resolve_context(
            session,
            market="CN_A",
            requested_trade_date=None,
            now=datetime(2027, 1, 4, 19, 59, tzinfo=ZoneInfo("Asia/Shanghai")),
        )
        assert context.trade_date == date(2026, 12, 31)
        stock = reference.security.get(ts_code="600005.SH")
        assert stock.list_status == "D" and stock.delist_date == date(2017, 2, 14)
        assert reference.security.get(ts_code="T00018.SH") is None
        assert reference.security.get(ts_code="TS0018.SH") is None


def test_local_file_error_surfaces_without_postgres_fallback(tmp_path):
    reference = build_reference_data(local_settings(tmp_path))
    with Session() as session:
        bind_reference_data(session, reference)
        with pytest.raises(
            ReferenceDataReadError, match="silver/calendar/trade_calendar"
        ):
            MarketPageContextQuery().resolve_context(
                session,
                market="CN_A",
                requested_trade_date=date(2027, 1, 4),
            )
    assert build_reference_data(Settings(_env_file=None, APP_ENV="production")) is None


@pytest.mark.parametrize("exchange, day", [("SSE", None), ("", date(2027, 1, 4))])
def test_calendar_damaged_key_is_a_read_error_even_outside_the_window(
    lake, exchange, day
):
    path = lake / "silver/calendar/trade_calendar/full/part-000.parquet"
    path.unlink()
    with duckdb.connect() as connection:
        connection.execute(
            """
            CREATE TEMP TABLE invalid_calendar AS
            SELECT ?::VARCHAR AS exchange, ?::DATE AS trade_date, true AS is_open,
                   NULL::DATE AS pretrade_date
        """,
            [exchange, day],
        )
        connection.execute("COPY invalid_calendar TO ? (FORMAT PARQUET)", [str(path)])
    reference = build_reference_data(local_settings(lake))
    with pytest.raises(ReferenceDataReadError, match="交易日历主键"):
        reference.calendar.range_rows(
            exchange="SSE", start=date(2027, 1, 4), end=date(2027, 1, 4)
        )


def test_trading_assistant_keeps_query_failed_error_for_missing_dg_stock(tmp_path):
    app = FastAPI()
    router = APIRouter(route_class=TradingAssistantRoute)
    install_exception_handlers(app)
    reference = build_reference_data(local_settings(tmp_path))

    @router.get("/positions")
    def positions():
        with Session() as session:
            bind_reference_data(session, reference)
            return read_record_names(
                session,
                ["000001.SZ"],
                deadline=Deadline.after_ms(1000),
                policy=TradingAssistantExecutionPolicyV1(),
            )

    app.include_router(router)
    with TestClient(app) as client:
        response = client.get("/positions")
    assert response.json()["code"] == "TA_QUERY_FAILED"


def test_stock_daily_reference_reads_share_the_existing_deadline(lake, monkeypatch):
    def reject_pg(*args):
        pytest.fail("DG reference reads must not open a PostgreSQL session")

    monkeypatch.setattr(stock_daily, "open_technical_indicator_read_session", reject_pg)
    read = reference_data_reader._read
    requested = []

    def read_with_timeout(root, location, sql, params, columns, *, timeout_seconds):
        requested.append((location, timeout_seconds))
        if location == reference_data_reader.STOCK_BASIC_LOCATION:
            raise TimeoutError("simulated DG query interruption")
        return read(
            root, location, sql, params, columns, timeout_seconds=timeout_seconds
        )

    monkeypatch.setattr(reference_data_reader, "_read", read_with_timeout)
    observed_clocks = iter([1, 2])
    control = SimpleNamespace(
        work_until=5, clock=lambda: next(observed_clocks), check_active=lambda: None
    )
    request = StockDailyKlineRequest(
        "000001.SZ", "day", "forward", date(2027, 1, 4), None, None, 2, False
    )

    async def run_request():
        settings = local_settings(lake)
        runtime = stock_daily.create_runtime(settings)
        try:
            backend = stock_daily.StockDailyKlineAppBackend(
                runtime, reject_pg, reference_data=build_reference_data(settings),
            )
            with pytest.raises(stock_daily.CalculationDeadlineError, match="stock_daily_reference_data/deadline"):
                backend.work(request, control)
        finally:
            await runtime.aclose()

    asyncio.run(run_request())
    assert requested == [
        (reference_data_reader.TRADE_CALENDAR_LOCATION, 4),
        (reference_data_reader.STOCK_BASIC_LOCATION, 3),
    ]


def test_postgres_can_join_reference_rows_without_old_tables(lake, tmp_path):
    pgroot = tmp_path / "pg"
    pgroot.mkdir()
    with isolated_postgres(pgroot) as engine, Session(engine) as session:
        bind_reference_data(session, build_reference_data(local_settings(lake)))
        candidates = (
            select(literal("600005.SH").label("ts_code"))
            .union_all(select(literal("T00018.SH").label("ts_code")))
            .subquery()
        )
        security = security_relation(
            session,
            columns=("ts_code", "name", "delist_date"),
            codes=select(candidates.c.ts_code),
        )
        rows = session.execute(
            select(candidates.c.ts_code, security.c.name, security.c.delist_date)
            .select_from(
                candidates.outerjoin(
                    security, security.c.ts_code == candidates.c.ts_code
                )
            )
            .order_by(candidates.c.ts_code)
        ).all()
        assert rows == [
            ("600005.SH", "武钢股份(退)", date(2017, 2, 14)),
            ("T00018.SH", None, None),
        ]
        calendar = calendar_relation(
            session, start=date(2027, 1, 1), end=date(2027, 1, 4)
        )
        assert session.execute(
            select(calendar.c.trade_date, calendar.c.is_open).order_by(
                calendar.c.trade_date
            )
        ).all() == [
            (date(2027, 1, 1), False),
            (date(2027, 1, 4), True),
        ]
        with engine.begin() as connection:
            connection.exec_driver_sql("CREATE SCHEMA core_serving")
            EquityDailyBar.__table__.create(connection)
            EquityDailyBasic.__table__.create(connection)
            DcDaily.__table__.create(connection)
            day = date(2026, 12, 31)
            connection.execute(
                EquityDailyBar.__table__.insert(),
                [
                    {"ts_code": "T00018.SH", "trade_date": day, "amount": 100},
                    {"ts_code": "600519.SH", "trade_date": day, "amount": 20},
                    {"ts_code": "000001.SZ", "trade_date": day, "amount": 10},
                ],
            )
            connection.execute(
                DcDaily.__table__.insert(),
                {
                    "ts_code": "BK001",
                    "trade_date": day,
                    "category": "行业板块",
                    "close": 20,
                    "pct_change": 1,
                },
            )
        ranks = LeaderboardEquityRankingsQuery().load_board_rows(
            session,
            trade_date=day,
            board_key="amount",
            stock_pool_codes={"T00018.SH", "600519.SH", "000001.SZ"},
            limit=1,
        )
        assert [(row.ts_code, row.subject_name, row.amount) for row in ranks] == [
            ("600519.SH", "贵州茅台", 20),
        ]
        resolution = SectorMomentumQuery().resolve_trading_date(
            session,
            expected_trade_date=date(2027, 1, 4),
            coverage_end_date=date(2027, 1, 4),
            sector_codes=("BK001",),
            is_explicit=False,
        )
        assert resolution.expected.trade_date == date(2027, 1, 4)
        assert resolution.observed.trade_date == day
