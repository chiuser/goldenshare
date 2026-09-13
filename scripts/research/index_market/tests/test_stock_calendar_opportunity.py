import pytest
from scripts.research.index_market.chan.stock_calendar_opportunity import grid,outcome
from scripts.research.index_market.chan.stock_calendar_run import validate


def rows():
    return [dict(time=f'2025-01-02 {s}',date='2025-01-02',code='000001.SZ',frequency=30,exchange='SZSE',open=10,close=10,high=10,low=10,vol=1,amount=10) for s in ('10:00:00','10:30:00','11:00:00','11:30:00','13:30:00','14:00:00','14:30:00','15:00:00')]


def test_suspension_does_not_compress_window():
    r=rows()
    times,data=grid(r,['2025-01-02','2025-01-03'])
    assert len(data)==16 and data[8] is None
    assert outcome(times,data,0,8)[1]=='exit_untradable'
    assert outcome(times,data,7,8)[1]=='entry_untradable'
    assert outcome(times,data,0,16)[1]=='tail'


def test_zero_entry_and_internal_zero():
    r=rows();r[1].update(vol=0,amount=0)
    t,d=grid(r,['2025-01-02'])
    assert outcome(t,d,0,3)[1]=='entry_untradable'
    x,reason=outcome(t,d,-1,4)
    assert reason is None and x['return_value']==0


def test_known_suspension_allowed_unknown_gap_rejected():
    r=rows();days=['2025-01-02','2025-01-03']
    validate(r,days,'000001.SZ',30,{'2025-01-03'})
    with pytest.raises(ValueError):validate(r,days,'000001.SZ',30,set())


def test_zero_volume_flat_only():
    r=rows();r[0].update(vol=0,amount=0)
    validate(r,['2025-01-02'],'000001.SZ',30,set())
    r[0]['high']=11
    with pytest.raises(ValueError):validate(r,['2025-01-02'],'000001.SZ',30,set())
