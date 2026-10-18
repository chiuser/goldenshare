"""Audit case scope follows LLD 25.1; no real DB, Lake or HTTP is touched."""
import json
import sys

import pytest

from scripts.research.index_market.xxm import bottom_history_acceptance as budget
from scripts.research.index_market import xxm_page_request_audit as page


@pytest.mark.parametrize('periods', [(), ('m60','m90','m120')])
@pytest.mark.parametrize('mode',['budget','replay-budget'])
def test_budget_default_and_explicit_scope_select_cases_only(monkeypatch,tmp_path,periods,mode):
    from scripts.research.index_market.xxm import reference_rescue_acceptance as r1
    selected=[]
    monkeypatch.setattr(budget,'load_source',lambda source,period:selected.append(period) or [period])
    monkeypatch.setattr(budget,'sha',lambda path:'fixture-manifest')
    observed=[]
    monkeypatch.setattr(budget,'budget_mode',lambda source,out,sources:observed.append(tuple(sources)) or {'passed':True})
    monkeypatch.setattr(r1,'formal_replay_mode',lambda source,out,sources:observed.append(tuple(sources)) or {'passed':True})
    output=tmp_path/'report'
    args=['audit','--mode',mode,'--formal-source','--source',str(tmp_path),'--output',str(output)]
    if periods:args+=['--periods',*periods]
    monkeypatch.setattr(sys,'argv',args)
    budget.main()
    expected=list(periods) if periods else ['day','m60','m90','m120']
    assert selected==expected
    assert observed==[tuple(expected)]
    assert json.loads((output/'run.json').read_text())['periods']==expected


@pytest.mark.parametrize('invalid', [('m60','m60'),('m30',),()])
@pytest.mark.parametrize('module', [budget,page])
def test_invalid_scope_fails_before_source_access_or_server_start(monkeypatch,tmp_path,invalid,module):
    output=tmp_path/'no-report'
    args=['audit','--output',str(output),'--periods',*invalid]
    if module is budget:
        args+=['--mode','budget','--formal-source','--source',str(tmp_path)]
        monkeypatch.setattr(budget,'load_source',lambda *a:pytest.fail('must not read source'))
    else:
        monkeypatch.setattr(page.socket,'socket',lambda *a:pytest.fail('must not start server'))
    monkeypatch.setattr(sys,'argv',args)
    with pytest.raises(SystemExit) as exc:module.main()
    assert exc.value.code==2
    assert not output.exists()


@pytest.mark.parametrize('mode',['frozen','api'])
def test_frozen_or_api_cannot_silently_reduce_existing_four_period_cases(monkeypatch,tmp_path,mode):
    output=tmp_path/'no-report'
    monkeypatch.setattr(sys,'argv',['audit','--mode',mode,'--source',str(tmp_path),
                                  '--output',str(output),'--periods','m60','m90','m120'])
    monkeypatch.setattr(budget,'load_source',lambda *a:pytest.fail('must not read source'))
    with pytest.raises(SystemExit) as exc:budget.main()
    assert exc.value.code==2
    assert not output.exists()


def test_formal_replay_dependency_enters_and_closes_readonly_session(monkeypatch):
    from contextlib import contextmanager
    from fastapi import Depends,FastAPI
    from fastapi.testclient import TestClient
    from scripts.research.index_market.xxm.reference_rescue_acceptance import _readonly_request_session
    marker=object();events=[]
    @contextmanager
    def readonly():
        events.append('opened')
        try:yield marker
        finally:events.append('closed')
    monkeypatch.setattr(budget,'readonly_session',readonly)
    app=FastAPI()
    @app.get('/probe')
    def probe(session=Depends(_readonly_request_session)):
        assert session is marker
        assert events==['opened']
        return {'ok':True}
    with TestClient(app) as client:
        assert client.get('/probe').json()=={'ok':True}
    assert events==['opened','closed']


def test_warm_daily_keeps_sql_validation_while_reusing_the_calculator():
    # Current source._load_series intentionally rereads day SQL to validate
    # freshness, unlike minute signature reuse. This is not a cold calculator.
    budget.verify_cache_mode('day','warm',{'sourceReadSeconds':.1})
    with pytest.raises(AssertionError,match='reran calculator'):
        budget.verify_cache_mode('day','warm',{'sourceReadSeconds':.1,'detectorStepSeconds':.01})
    with pytest.raises(AssertionError,match='reread source'):
        budget.verify_cache_mode('m60','warm',{'sourceReadSeconds':.1})
    with pytest.raises(AssertionError,match='did not load'):
        budget.verify_cache_mode('day','cold',{})


def test_completed_frozen_units_restore_events_without_recomputing(monkeypatch,tmp_path):
    """Control-flow test only: literal totals and events, no math acceptance claim."""
    from scripts.research.index_market.xxm import reference_rescue_acceptance as current
    from scripts.research.index_market.xxm import cross_index_daily,frozen_inputs
    from scripts.research.index_market.xxm.cross_index_daily import seal as real_seal
    from scripts.research.index_market.xxm.cross_index_daily import read_unit as real_read
    monkeypatch.setattr(budget,'calendar_rows',lambda *_:())
    monkeypatch.setattr(frozen_inputs,'forecast_inventory',lambda:[])
    identity={}
    def read(out,name):
        if name=='frozen_identity':return identity.get(name)
        # Three equal groups prove all four periods can be entirely resumed.
        totals=dict(forecasts=405,retainedForecasts=237,independentForecasts=168,prefixRestoreCuts=15) if name.startswith('frozen_day_') else {}
        return dict(summary=dict(resumed=True),totals=totals,events=[dict(time=name)])
    def seal(out,name,value):identity[name]=value
    monkeypatch.setattr(cross_index_daily,'read_unit',read)
    monkeypatch.setattr(cross_index_daily,'seal',seal)
    monkeypatch.setattr(frozen_inputs,'assert_expected_recognition',lambda *a,**k:pytest.fail('must reuse completed recognition'))
    monkeypatch.setattr(current,'forecast',lambda *a,**k:pytest.fail('must reuse completed forecast'))
    monkeypatch.setattr(current,'simulations',lambda *a:[])
    source=current.ROOT/'reports/xxm_source_audit_20261013_213852'
    sources={p:() for p in ('day','m60','m90','m120')}
    summary=current.frozen_mode(source,tmp_path,sources)
    assert summary['totals']==dict(forecasts=1215,retainedForecasts=711,independentForecasts=504,prefixRestoreCuts=45)
    for period in sources:
        assert json.loads((tmp_path/f'events_{period}.json').read_text())==dict(events=[dict(time=f'frozen_{period}_1.2')])
    # Same source/code passes; changed identity must fail before reusing any unit.
    current.frozen_mode(source,tmp_path,sources)
    identity['frozen_identity']['forecastSpecHash']='wrong'
    with pytest.raises(AssertionError,match='Cannot resume changed'):current.frozen_mode(source,tmp_path,sources)
    # Actual SHA readback is tested separately from the resumed-control substitute.
    actual=tmp_path/'actual';actual.mkdir();real_seal(actual,'one',dict(events=['literal']))
    assert real_read(actual,'one')==dict(events=['literal'])
    (actual/'one.json').write_text('{}')
    with pytest.raises(ValueError,match='Changed completed'):real_read(actual,'one')
