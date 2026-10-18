"""Preparation safeguards; not tests claiming the future product is implemented."""
import gzip
import hashlib
import json
from fractions import Fraction as F

import pytest

from scripts.research.index_market.xxm.top_activation_expectations import IdMap, verify_stream, encoded
from scripts.research.index_market.xxm.top_activation_math import expectations
from scripts.research.index_market.xxm.cross_index_daily import seal, read_unit
from src.biz.services.wealth.market.index_detail_xxm.spec import XxmSpec


def test_independent_literal_math_and_three_thresholds():
    result=expectations()
    assert result['minuteEntry']==dict(lower=[1103,14],upper=[1429,7],lowerStrict=True,upperStrict=True)
    assert result['secondDif']==dict(p=[7588,123201],c=[28,351],b=[-1565182,123201])
    assert [v['activation'] for v in result['literalPrices']]==[False,True,False]
    assert [v['expected'] for v in result['dailyPrecision']]==['NONPOSITIVE']*6+['MIXED']*3+['POSITIVE']*2
    assert [v['targetBarsAhead'] for v in result['minuteRelations']]==[2,2,2]
    assert result['noEntry']['targetEndpoint'] is None and result['noEntry']['activationRanges']==[]
    assert result['existingDull']['dif']==[-758,117]
    # Hand-derived at P=100: flip C<30137/455; 1% turn C<=1875539/18200.
    one=result['minuteRelations'][1]
    for key, wanted in [('colorFlip',F(30137,455)),('difTurn',F(1875539,18200))]:
        expr=one[key]['upperC']
        assert F(*expr['p'])*100+F(*expr['b'])==wanted


def test_versioned_ids_keep_relationships_and_reject_unknown_old_ids():
    from dataclasses import asdict, make_dataclass
    # Data record of the sealed pre-development spec, not a runnable old engine.
    values=asdict(XxmSpec());values['algorithm_version']='xxm-direction-v0.1-r1'
    FrozenSpec=make_dataclass('FrozenSpec',[(k,type(v)) for k,v in values.items()],namespace={
        'spec_hash':property(lambda self:hashlib.sha256(json.dumps(asdict(self),sort_keys=True,separators=(',',':')).encode()).hexdigest())})
    ids=IdMap('m60',FrozenSpec(**values))
    # Independent original report event, not generated through calculator._id.
    parts=['2009-01-15T10:30:00+08:00','DULL',1,'2009-01-12T14:00:00+08:00']
    ids.register('2c77a4b943d1237a09631ef5','event',parts)
    identity='|'.join(['xxm-direction-v0.1-r2','6db425730c72f22ea756c121a832f27c966d1324ef0a72a2312a3c572038724d','000001.SH','m60',*map(str,parts)])
    expected=hashlib.sha256(identity.encode()).hexdigest()[:24]
    assert ids.convert({'id':'2c77a4b943d1237a09631ef5','relatedRearmId':None})=={'id':expected,'relatedRearmId':None}
    with pytest.raises(AssertionError):ids.register('0'*24,'event',parts)
    with pytest.raises(AssertionError):ids.convert({'pendingRearmId':'0'*24})


def test_sealed_units_resume_and_reject_changed_or_partial_files(tmp_path):
    assert read_unit(tmp_path,'one') is None
    seal(tmp_path,'one',{'normal':1})
    assert read_unit(tmp_path,'one')=={'normal':1}
    with pytest.raises(ValueError):seal(tmp_path,'one',{'normal':2})
    (tmp_path/'one.json').write_text('{}')
    with pytest.raises(ValueError):read_unit(tmp_path,'one')
    (tmp_path/'partial.json').write_text('{}')
    with pytest.raises(ValueError):read_unit(tmp_path,'partial')


def test_full_stream_readback_detects_corruption_count_and_time(tmp_path):
    line=encoded(dict(time='2026-01-06',expected={'point':{'time':'2026-01-06'}}))+b'\n'
    path=tmp_path/'x.gz';path.write_bytes(gzip.compress(line,mtime=0))
    info=dict(file='x.gz',sha256=hashlib.sha256(path.read_bytes()).hexdigest(),rows=1,through='2026-01-06',
              rawBytes=len(line),contentSha256=hashlib.sha256(line).hexdigest())
    verify_stream(tmp_path,'x',info)
    for change in ({'rows':2},{'through':'2026-01-07'},{'sha256':'0'*64}):
        with pytest.raises(AssertionError):verify_stream(tmp_path,'x',{**info,**change})
