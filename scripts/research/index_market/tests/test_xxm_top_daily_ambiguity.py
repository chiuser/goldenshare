"""Literal selector counterexamples; intentionally synthetic, not software truth."""
from dataclasses import asdict

import pytest

from scripts.research.index_market.xxm.top_daily_ambiguity import ReferenceGateCalculator
from src.biz.services.wealth.market.index_detail_xxm.calculator import XxmCalculator
from src.biz.services.wealth.market.index_detail_xxm.types import Wave,XxmBar


def wave(start,count,price,dif,sign=1):
    return Wave(sign,start,start,count,price,dif,start,start)


def selected(variant,current,history,*,incoming_dif=None):
    calc=ReferenceGateCalculator(period='day',source_identity='literal',variant=variant)
    calc.incoming=XxmBar('2024-01-10',current.price,current.dif if incoming_dif is None else incoming_dif,0,current.sign)
    before=[asdict(v) for v in history]
    result=calc._select_eligible_reference(current,history)
    assert before==[asdict(v) for v in history]
    return result


def test_singleton_still_occupies_nearest_gate_and_cannot_be_removed_first():
    old=wave('2024-01-01',3,90,12);single=wave('2024-01-05',1,110,10)
    current=wave('2024-01-08',2,105,8)
    assert selected('T2',current,[old,single]) is None


def test_singleton_cannot_be_reference_but_no_third_segment_is_added():
    old=wave('2024-01-01',3,110,12);single=wave('2024-01-05',1,100,10)
    current=wave('2024-01-08',2,105,8)
    assert selected('BASE',current,[old,single]) is single
    assert selected('T2',current,[old,single]) is None


def test_eligible_older_segment_in_same_pool_can_replace_filtered_singleton():
    old=wave('2024-01-01',2,102,9);single=wave('2024-01-05',1,100,10)
    current=wave('2024-01-08',2,105,8)
    assert selected('BASE',current,[old,single]) is single
    assert selected('T2',current,[old,single]) is old


def test_top_only_gate_preserves_bottom_but_symmetric_hypothesis_rejects():
    old=wave('2024-01-01',3,90,-12,-1);single=wave('2024-01-05',1,100,-10,-1)
    current=wave('2024-01-08',2,95,-8,-1)
    assert selected('T2',current,[old,single]) is single
    assert selected('S2',current,[old,single]) is None
    assert selected('ZC',current,[old,single]) is single
    assert selected('ZR',current,[old,single]) is single


@pytest.mark.parametrize('incoming,allowed',[(0,False),(-1,False),(.001,True)])
def test_current_dif_gate_uses_this_bar_not_segment_peak(incoming,allowed):
    reference=wave('2024-01-01',2,100,10);current=wave('2024-01-08',2,105,5)
    assert selected('ZC',current,[reference],incoming_dif=incoming) is (reference if allowed else None)


@pytest.mark.parametrize('ref_dif,allowed',[(0,False),(-3,False),(.001,True)])
def test_reference_zero_gate_is_independent_of_current_bar(ref_dif,allowed):
    reference=wave('2024-01-01',2,100,ref_dif);current=wave('2024-01-08',2,105,-5)
    assert selected('ZR',current,[reference],incoming_dif=-5) is (reference if allowed else None)


def test_base_uses_unmodified_product_selector_and_current_two_bar_guard():
    reference=wave('2024-01-01',1,100,10)
    for count in (1,2):
        current=wave('2024-01-08',count,105,8)
        original=XxmCalculator(period='day',source_identity='literal')._select_eligible_reference(current,[reference])
        assert selected('BASE',current,[reference]) is original
        assert original is (reference if count==2 else None)


def test_unknown_hypothesis_rejected():
    with pytest.raises(ValueError,match='Unknown isolated'):
        ReferenceGateCalculator(period='day',source_identity='literal',variant='OTHER')
