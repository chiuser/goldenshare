"""Real projection contract and isolated clock/storage boundaries, no real I/O."""
from datetime import date, datetime, timedelta
import math

import pytest
from sqlalchemy import create_engine,event,text
from sqlalchemy.orm import Session

from scripts.research.index_market.xxm.daily_window_precheck import (
    START,isolated_client,read_window,validate_window,
)
from goldenshare_technical_indicators.xxm.types import XxmBar


def sample(future=True):
    # Producer projection follows current IndexFactorPro/TradeCalendar ORM and
    # source.read_daily. Calendar after 1/10 is deliberately synthetic, not an
    # assertion about real SSE holiday dates; only the future guard is tested.
    last=date(2020,3,1) if future else date(2020,1,10)
    days=[START+timedelta(days=i) for i in range((last-START).days+1)]
    calendar={day.isoformat():day.weekday()<5 and day!=START for day in days}
    bars=tuple(XxmBar(day,100.,0.,0.,0.) for day,opened in calendar.items()
               if opened and day<='2020-01-10')
    return bars,calendar


def test_capture_excludes_an_invalid_2019_record_using_real_projection_contract():
    bars,calendar=sample()
    engine=create_engine('sqlite://')
    @event.listens_for(engine,'connect')
    def attach(connection,_):connection.execute("ATTACH DATABASE ':memory:' AS core_serving")
    with engine.begin() as c:
        c.execute(text('CREATE TABLE core_serving.index_factor_pro (ts_code TEXT, trade_date DATE, close FLOAT, macd_dif_bfq FLOAT, macd_dea_bfq FLOAT, macd_bfq FLOAT)'))
        c.execute(text('CREATE TABLE core_serving.trade_calendar (exchange TEXT, trade_date DATE, is_open BOOLEAN)'))
        c.execute(text("INSERT INTO core_serving.index_factor_pro VALUES ('000001.SH','2019-12-31',NULL,NULL,NULL,NULL)"))
        c.execute(text("INSERT INTO core_serving.index_factor_pro VALUES ('000001.SH',:day,100,0,0,0)"),[dict(day=v.time) for v in bars])
        c.execute(text("INSERT INTO core_serving.trade_calendar VALUES ('SSE',:day,:opened)"),[dict(day=k,opened=v) for k,v in calendar.items()])
    with Session(engine) as session:
        values,dates=read_window(session,date(2020,1,10))
    assert values==bars and dates==calendar
    assert values[0].time=='2020-01-02' and values[-1].time=='2020-01-10' and len(values)==7
    engine.dispose()


@pytest.mark.parametrize('missing',['2020-01-02','2020-01-07'])
def test_explicit_range_rejects_leading_and_internal_missing_open_days(missing):
    bars,calendar=sample()
    with pytest.raises(ValueError,match='Explicit window'):
        validate_window(tuple(v for v in bars if v.time!=missing),calendar,date(2020,1,10))


def test_duplicate_or_out_of_range_source_rows_are_rejected():
    bars,calendar=sample()
    for values in ((bars[0],*bars), (XxmBar('2019-12-31',100,0,0,0),*bars)):
        with pytest.raises(ValueError,match='Explicit window'):
            validate_window(values,calendar,date(2020,1,10))


@pytest.mark.parametrize('bad',[math.inf,math.nan,-1.])
def test_original_finite_positive_close_guard_is_kept(bad):
    bars,calendar=sample()
    with pytest.raises(ValueError,match='finite completed'):
        validate_window((XxmBar(bars[0].time,bad,0,0,0),*bars[1:]),calendar,date(2020,1,10))


def test_calendar_closed_day_cannot_be_silently_omitted():
    bars,calendar=sample();calendar.pop('2020-01-04')
    with pytest.raises(ValueError,match='Calendar contains missing'):
        validate_window(bars,calendar,date(2020,1,10))


def test_real_route_uses_literal_zero_window_and_returns_static_no_candidate():
    bars,calendar=sample()
    with isolated_client(bars,calendar,datetime.fromisoformat('2020-01-10T21:00:00+08:00')) as (client,session):
        value=client.get('/api/v1/wealth/market/index-detail/xxm-key-point-forecast',params={'tsCode':'000001.SH','period':'day','asOf':'2020-01-10'})
        assert value.status_code==200
        payload=value.json()
        assert payload['computedThrough']=='2020-01-10' and payload['dataStatus']=='READY'
        assert payload['status']=='NO_CANDIDATE' and payload['reasonCode']=='ZERO_WAVE'
        assert payload['targetEndpoint'] is None
        generator=session();s=next(generator)
        assert s.execute(text('PRAGMA query_only')).scalar_one()==1
        generator.close()


def test_isolated_clock_forwards_explicit_code_and_requested_window(monkeypatch):
    from contextlib import contextmanager
    from src.biz.queries.wealth.market.index_detail_xxm import query_service as q

    # This checks the observation wrapper, not recognition or source admission.
    # The isolated tool freezes time; it must forward every product argument.
    calls=[];marker=object()
    @contextmanager
    def load(self,session,*,ts_code,period,now=None,window_rows=None,requested_end=None):
        calls.append((session,ts_code,period,now,window_rows,requested_end))
        yield marker
    monkeypatch.setattr(q.IndexDetailXxmQueryService,'load_entry',load)
    frozen=datetime.fromisoformat('2020-01-10T21:00:00+08:00')
    bars,calendar=sample();session_marker=object()
    with isolated_client(bars,calendar,frozen):
        with q.IndexDetailXxmQueryService().load_entry(
            session_marker,ts_code='000001.SH',period='day',
            now=datetime.fromisoformat('2020-01-09T21:00:00+08:00'),
            window_rows=37,requested_end=date(2020,1,9),
        ) as value:
            assert value is marker
    assert calls==[(session_marker,'000001.SH','day',frozen,37,date(2020,1,9))]
    assert q.IndexDetailXxmQueryService.load_entry is load


def test_missing_future_calendar_is_not_bypassed_for_isolation():
    bars,calendar=sample(future=False)
    with isolated_client(bars,calendar,datetime.fromisoformat('2020-01-10T21:00:00+08:00')) as (client,_):
        value=client.get('/api/v1/wealth/market/index-detail/xxm-key-point-forecast',params={'tsCode':'000001.SH','period':'day','asOf':'2020-01-10'})
        # ZERO_WAVE deliberately skips future-calendar reads in current P3.
        assert value.status_code==200 and value.json()['reasonCode']=='ZERO_WAVE'
        from src.biz.queries.wealth.market.index_detail_xxm.forecast_query_service import future_calendar
        from src.biz.queries.wealth.market.index_detail_xxm.query_service import XxmQueryError
        with isolated_client(bars,calendar,datetime.fromisoformat('2020-01-10T21:00:00+08:00')) as (_, session):
            source=session(); s=next(source)
            try:
                with pytest.raises(XxmQueryError,match='未来交易日历'):
                    future_calendar(s,'day','2020-01-10',lambda:1.)
            finally: source.close()



def test_non_ema_literal_window_reaches_the_existing_calibration_guard():
    bars,calendar=sample()
    values=[(100,-60,-2),(110,0,2),(90,-50,-2),(100,0,2),(89,-15,-30),(88,-14,-28),(88,-14,-28)]
    bars=tuple(XxmBar(old.time,c,d,d-h/2,h) for old,(c,d,h) in zip(bars,values))
    with isolated_client(bars,calendar,datetime.fromisoformat('2020-01-10T21:00:00+08:00')) as (client,_):
        response=client.get('/api/v1/wealth/market/index-detail/xxm-key-point-forecast',params={'tsCode':'000001.SH','period':'day','asOf':'2020-01-10'})
        assert response.status_code==200
        assert response.json()['status']=='PRECISION_PENDING' and response.json()['reasonCode']=='CALIBRATION_FAILED'
