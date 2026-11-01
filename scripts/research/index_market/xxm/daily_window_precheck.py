"""Bounded 2020+ projection validation and explicitly isolated fixture client.

No CLI/capture/writer or old algorithm dependency. This is not formal-source
or performance acceptance. Input values are never recalculated or repaired.
"""
from contextlib import contextmanager
from datetime import date, timedelta
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from src.biz.queries.wealth.market.index_detail_xxm import query_service as q
from src.biz.queries.wealth.market.index_detail_xxm.source import assert_continuous
from src.biz.services.wealth.market.index_detail_xxm.forecast_spec import FORECAST_SPEC
from src.biz.services.wealth.market.index_detail_xxm.types import XxmBar
from src.foundation.models.core.index_factor_pro import IndexFactorPro
from src.foundation.models.core.trade_calendar import TradeCalendar

START = date(2020, 1, 1)
MAX_ROWS, MAX_CALENDAR = 2000, 3000

def validate_window(bars, calendar, end):
    if not bars or len(bars) > MAX_ROWS or not calendar or len(calendar) > MAX_CALENDAR:
        raise ValueError('Window empty or over budget')
    days = [date.fromisoformat(day) for day in calendar]
    if days != sorted(set(days)) or days[0] != START or days[-1] < end:
        raise ValueError('Calendar bounds/order invalid')
    if any(right-left != timedelta(days=1) for left,right in zip(days,days[1:])):
        raise ValueError('Calendar contains missing dates')
    if any(type(value) is not bool for value in calendar.values()):
        raise ValueError('Calendar open flag must be boolean')
    expected = tuple(day for day,opened in calendar.items() if opened and START.isoformat() <= day <= end.isoformat())
    for bar in bars:
        bar.validate('day')
    if tuple(bar.time for bar in bars) != expected:
        raise ValueError('Explicit window has missing/duplicate/out-of-range bars')
    assert_continuous(tuple(bars),period='day',open_dates=tuple(day for day in days if calendar[day.isoformat()]))


def read_window(session, end):
    """Real producer projection: IndexFactorPro and TradeCalendar ORM fields."""
    values, after = [], None
    while True:
        conditions = [IndexFactorPro.ts_code=='000001.SH',IndexFactorPro.trade_date>=START,
                      IndexFactorPro.trade_date<=end]
        if after is not None:
            conditions.append(IndexFactorPro.trade_date>after)
        rows = session.execute(select(IndexFactorPro.trade_date,IndexFactorPro.close,
            IndexFactorPro.macd_dif_bfq,IndexFactorPro.macd_dea_bfq,IndexFactorPro.macd_bfq)
            .where(*conditions).order_by(IndexFactorPro.trade_date).limit(1000)).all()
        if not rows:
            break
        values.extend(XxmBar(row[0].isoformat(),*(float(v) for v in row[1:])) for row in rows)
        if len(values)>MAX_ROWS:
            raise ValueError('Daily capture exceeds bounded window')
        after=rows[-1][0]
    rows=session.execute(select(TradeCalendar.trade_date,TradeCalendar.is_open).where(
        TradeCalendar.exchange=='SSE',TradeCalendar.trade_date>=START,
        TradeCalendar.trade_date<=end+timedelta(days=FORECAST_SPEC.future_calendar_days))
        .order_by(TradeCalendar.trade_date).limit(MAX_CALENDAR+1)).all()
    calendar={day.isoformat():opened for day,opened in rows}
    if len(rows)!=len(calendar):
        raise ValueError('Duplicate calendar dates')
    validate_window(values,calendar,end)
    return tuple(values),calendar



@contextmanager
def isolated_client(bars,calendar,now):
    """Temporary fixture based on the real read_daily producer projection.

    Replaces only storage, clock and auth. Business queries/calculation/DTO,
    source validators and all runtime limits are the unchanged product code.
    """
    from fastapi.testclient import TestClient
    engine=create_engine('sqlite://',poolclass=StaticPool,connect_args={'check_same_thread':False})
    @event.listens_for(engine,'connect')
    def attach(connection,_):
        connection.execute("ATTACH DATABASE ':memory:' AS core_serving")
    with engine.begin() as connection:
        connection.execute(text('CREATE TABLE core_serving.index_factor_pro (ts_code TEXT, trade_date DATE, close FLOAT, macd_dif_bfq FLOAT, macd_dea_bfq FLOAT, macd_bfq FLOAT)'))
        connection.execute(text('CREATE TABLE core_serving.trade_calendar (exchange TEXT, trade_date DATE, is_open BOOLEAN, pretrade_date DATE)'))
        connection.execute(text("INSERT INTO core_serving.index_factor_pro VALUES ('000001.SH',:day,:close,:dif,:dea,:hist)"),
            [dict(day=v.time,close=v.close,dif=v.dif,dea=v.dea,hist=v.hist) for v in bars])
        connection.execute(text("INSERT INTO core_serving.trade_calendar (exchange,trade_date,is_open) VALUES ('SSE',:day,:opened)"),
            [dict(day=day,opened=opened) for day,opened in calendar.items()])
        connection.execute(text('PRAGMA query_only=ON'))
    def session():
        with Session(engine) as value:
            yield value
    original_load,original_cache=q.IndexDetailXxmQueryService.load_entry,q._CACHE
    def load(self,session,*,period,now=None):
        return original_load(self,session,period=period,now=frozen_now)
    frozen_now=now
    q.IndexDetailXxmQueryService.load_entry=load
    q._CACHE=q.XxmCache()
    try:
        from fastapi import APIRouter, FastAPI
        from src.app.api.v1.router import _include_local_xxm_routers
        from src.app.dependencies import get_db_session
        from src.app.auth.dependencies import require_quote_access
        from src.app.exceptions import install_exception_handlers
        from src.foundation.config.settings import Settings
        app=FastAPI(); install_exception_handlers(app)
        target=APIRouter(prefix='/api/v1')
        _include_local_xxm_routers(target,Settings(_env_file=None,APP_ENV='local',WEALTH_LOCAL_LAKE_MINUTE_API_ENABLED=False))
        app.include_router(target)
        app.dependency_overrides[get_db_session]=session
        app.dependency_overrides[require_quote_access]=lambda:None
        with TestClient(app) as client:
            yield client,session
    finally:
        q.IndexDetailXxmQueryService.load_entry=original_load;q._CACHE=original_cache
        engine.dispose()
