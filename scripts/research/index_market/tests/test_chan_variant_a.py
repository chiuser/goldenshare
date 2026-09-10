"""A is one buy-side setting, never a general parameter-search surface."""
from copy import deepcopy
from dataclasses import replace
import inspect

import pytest

from scripts.research.index_market.chan import minute_variant_a as variant
from scripts.research.index_market.chan.minute_data import MINUTE, load_input
from scripts.research.index_market.chan.run_m0 import verify_source
from scripts.research.index_market.chan.run_minute import run


def expanded_fixture():
    return dict(bs_point_conf=dict(b_conf=dict(bsp3_follow_1=True,bsp3a_max_zs_cnt=1),
        s_conf=dict(bsp3_follow_1=True)),seg_bs_point_conf=dict(b_conf=dict(bsp3_follow_1=True)),
        macd_config=dict(fast=12,slow=26,signal=9))


def test_raw_config_is_single_buy_override():
    assert variant.VARIANT_A.chan_config()==dict(MINUTE.chan_config(),**{'bsp3_follow_1-buy':False})
    variant.require_scope(variant.VARIANT_A)


@pytest.mark.parametrize('field,value',[('start','2020-01-01'),('cooldown_days',1),
    ('bsp3_follow_1_buy',True),('frequencies',(30,)),('repetitions',100),
    ('baseline_manifest_sha256','bad')])
def test_scope_rejects_unapproved_change(field,value):
    with pytest.raises(ValueError):
        variant.require_scope(replace(variant.VARIANT_A,**{field:value}))


@pytest.mark.parametrize('extra',['none','sell','segment','macd','centers','no_change'])
def test_full_configuration_diff(extra):
    before = expanded_fixture()
    after = deepcopy(before)
    after['bs_point_conf']['b_conf']['bsp3_follow_1'] = False
    if extra=='sell':
        after['bs_point_conf']['s_conf']['bsp3_follow_1'] = False
    if extra=='segment':
        after['seg_bs_point_conf']['b_conf']['bsp3_follow_1'] = False
    if extra=='macd':
        after['macd_config']['fast'] = 7
    if extra=='centers':
        after['bs_point_conf']['b_conf']['bsp3a_max_zs_cnt'] = 2
    if extra=='no_change':
        after = before
    if extra=='none':
        variant.require_single_change(before,after)
    else:
        with pytest.raises(ValueError):
            variant.require_single_change(before,after)


def test_bad_baseline_fingerprint_fails_before_artifact_access(tmp_path,monkeypatch):
    monkeypatch.setattr(variant,'REPO',tmp_path)
    root = tmp_path/variant.VARIANT_A.baseline
    root.mkdir(parents=True)
    (root/'manifest.json').write_text('{}')
    with pytest.raises(ValueError,match='fingerprint'):
        variant.read_baseline()


def test_default_runner_dependencies_unchanged():
    defaults = inspect.signature(run).parameters
    assert defaults['source_verifier'].default is verify_source
    assert defaults['input_loader'].default is load_input
    assert defaults['spec'].default is MINUTE


def test_event_set_comparison_includes_timing_changes():
    def event(key,time,index):
        return dict(event_id=key,signal_time=time,anchor_index=index)
    before = [event('a','t1',1),event('b','t2',2),event('d','t4',4)]
    after = [event('a','t1',1),event('b','t3',2),event('c','t4',4)]
    assert variant.event_diff(before,after)==dict(added=['c'],removed=['d'],
        timing_or_anchor_changed=['b'],unchanged=1)
