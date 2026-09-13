import pytest
from scripts.research.index_market.chan.stock_signal_timing import feature,keep


@pytest.mark.parametrize('lag,expected',[(4,True),(5,False)])
def test_lag4_boundary(lag,expected):
    assert keep(dict(lag=lag,group='B1'),'lag4') is expected


def test_lag8_boundary_and_type():
    assert keep(dict(lag=8,group='B2'),'lag8')
    assert not keep(dict(lag=9,group='B2'),'lag8')
    assert not keep(dict(lag=4,group='B2'),'B1')
    assert keep(dict(lag=4,group='B2'),'B2')
    with pytest.raises(ValueError):keep(dict(lag=4),'invented')


def test_feature_prefix_and_future_rejection():
    rows=[dict(time=f'2025-01-02 {h}:30:00',date='2025-01-02',low=10,close=11) for h in (10,11)]
    e=dict(signal_index=1,anchor_index=0,lag_bars=1,signal_time=rows[1]['time'],anchor_time=rows[0]['time'],buy=True,sure=True,group='B1',event_id='a')
    assert feature(rows,['2025-01-02'],e)['lag']==1
    for change in (dict(anchor_index=2),dict(lag_bars=2),dict(anchor_time='wrong'),dict(sure=False)):
        with pytest.raises(ValueError):feature(rows,['2025-01-02'],dict(e,**change))
