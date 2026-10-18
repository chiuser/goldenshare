"""Real projection contract and isolated clock/storage boundaries, no real I/O."""
from datetime import date, datetime, timedelta
import math

import pytest
from sqlalchemy import create_engine,event,text
from sqlalchemy.orm import Session

from scripts.research.index_market.xxm import bottom_history_acceptance as b
from scripts.research.index_market.xxm.daily_window_precheck import (
    START,isolated_client,read_window,validate_window,
)
from src.biz.services.wealth.market.index_detail_xxm.types import XxmBar


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


def test_real_route_uses_frozen_2020_fixture_and_preserves_calibration_guard():
    bars,calendar=sample()
    with isolated_client(bars,calendar,datetime.fromisoformat('2020-01-10T21:00:00+08:00')) as (client,session):
        value=b.prediction(client,'day','2020-01-10')
        assert value.status_code==200
        payload=value.json()
        assert payload['computedThrough']=='2020-01-10' and payload['dataStatus']=='READY'
        assert payload['status']=='PRECISION_PENDING' and payload['reasonCode']=='CALIBRATION_FAILED'
        assert payload['targetEndpoint'] is None
        generator=session();s=next(generator)
        assert s.execute(text('PRAGMA query_only')).scalar_one()==1
        generator.close()


def test_missing_future_calendar_is_not_bypassed_for_isolation():
    bars,calendar=sample(future=False)
    with isolated_client(bars,calendar,datetime.fromisoformat('2020-01-10T21:00:00+08:00')) as (client,_):
        value=b.prediction(client,'day','2020-01-10')
        assert value.status_code==500
        assert value.json()['code']=='XXMF_SOURCE_CONTRACT_INVALID'


def test_source_capture_identity_accepts_new_capture_and_only_approved_old_bytes(tmp_path):
    import json
    from scripts.research.index_market.xxm.daily_window_precheck import validate_capture_identity, ROOT
    from src.biz.services.wealth.market.index_detail_xxm.spec import MAIN_SPEC
    old_source=ROOT/'reports/xxm_reference_rescue_r1_implementation_20261017/daily_2020_source_01'
    old=json.loads((old_source/'manifest.json').read_text())
    validate_capture_identity(old_source,old)
    # Normal new capture must not be blocked by pinning to the historical file.
    current=dict(old,specHash=MAIN_SPEC.spec_hash,algorithmVersion=MAIN_SPEC.algorithm_version)
    validate_capture_identity(tmp_path,current)
    wrong=dict(current,algorithmVersion='xxm-direction-v0.1-r1')
    with pytest.raises(AssertionError):validate_capture_identity(tmp_path,wrong)
    with pytest.raises((AssertionError,ValueError)):validate_capture_identity(tmp_path,old)
