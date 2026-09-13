from scripts.research.index_market.chan.stock_parameter_study import ParameterSpec,CHANGES,PERIODS,summarize
from scripts.research.index_market.chan.minute_variant_a import VARIANT_A


def test_single_buy_parameter_only():
    original=VARIANT_A.chan_config()
    assert ParameterSpec().chan_config()==original
    for name,change in CHANGES.items():
        actual=ParameterSpec(mode=name).chan_config()
        assert actual==dict(original,**change)
        assert len(change)<=1
        assert all(k.endswith('-buy') for k in change)


def test_periods_do_not_overlap():
    assert PERIODS['early'][1]<PERIODS['late'][0]


def test_boundary_censor_not_silently_dropped():
    times=['2024-08-20 10:30:00']
    event=dict(signal_time=times[0],buy=True,sure=True,group='B1')
    cache={('early',10):({}, {0:'period_end'}, {})}
    result=summarize([event],times,cache)
    assert result[0]['total']==1 and result[0]['n']==0
    assert result[0]['censored']=={'period_end':1}


def test_observation_purge_uses_exit_date(monkeypatch):
    from scripts.research.index_market.chan import stock_parameter_study as study
    from scripts.research.index_market.chan.minute_data import slots
    days=[f'2024-08-{i:02d}' for i in range(1,9)]
    rows=[dict(time=f'{d} {s}',date=d,open=10,high=10,low=10,close=10,vol=1,amount=10)
          for d in days for s in slots(30)]
    monkeypatch.setattr(study,'PERIODS',{'early':(days[0],days[1])})
    _,cache=study.observations(rows,days)
    items,reasons,_=cache[('early',5)]
    assert not items and reasons[0]=='period_end'
