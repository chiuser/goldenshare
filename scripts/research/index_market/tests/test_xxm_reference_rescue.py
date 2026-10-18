"""Product R1 literal transitions, migrated from the sealed offline candidate."""
from copy import deepcopy
from dataclasses import replace
from datetime import date,timedelta

import pytest

from src.biz.services.wealth.market.index_detail_xxm.calculator import XxmCalculator
from src.biz.services.wealth.market.index_detail_xxm.forecast_detector import clone
from src.biz.services.wealth.market.index_detail_xxm.types import XxmBar


# A strong old negative segment (P90,D-20), a weaker recent one (P100,D-5),
# then two new green bars (P99/98,D-2/-3). All literal, not generated expected.
VALUES=[(90,-20,-2),(110,1,2),(100,-5,-2),(110,1,2),(99,-2,-2),(98,-3,-2)]


def bar(n,c,d,h=-2):
    return XxmBar((date(2020,1,1)+timedelta(days=n-1)).isoformat(),c,d,d-h/2,h)


def prepared(values=VALUES):
    calc=XxmCalculator(period='day',source_identity='literal-r1')
    for n,(c,d,h) in enumerate(values,1):calc.step(bar(n,c,d,h))
    if values==VALUES:
        assert calc.state=='DULL' and calc.reference.price==100 and calc.reference.dif==-5
        assert [(r.price,r.dif) for r in calc.history[-1]]==[(90,-20),(100,-5)]
    return calc


def test_rescue_uses_the_already_known_older_reference_without_new_event():
    calc=prepared();pool=deepcopy(calc.history);step=calc.step(bar(7,89,-6))
    assert calc.state=='DULL' and calc.reference.dif==-20
    assert not step.events and step.point['activeReference']['dif']==-20
    assert calc.history==pool


@pytest.mark.parametrize('close,dif',[(95,-6),(90,-6),(89,-20),(89,-21)])
def test_no_price_or_dif_qualified_alternative_preserves_real_cancel(close,dif):
    calc=prepared();step=calc.step(bar(7,close,dif))
    assert [e['type'] for e in step.events]==['CANCEL']
    assert calc.reference is None


def test_old_dif_equality_does_not_request_rescue_or_cancel():
    calc=prepared();step=calc.step(bar(7,89,-5))
    assert not step.events and calc.reference.dif==-5


def test_newest_price_gate_cannot_be_bypassed():
    # Recent P80 is lower than older P90. Incoming P85 cannot pass recent P80.
    values=[(90,-20,-2),(110,1,2),(80,-5,-2),(110,1,2),(79,-2,-2),(78,-3,-2)]
    calc=prepared(values=values)
    # Deliberately inject an ineligible active price for the pure gate test;
    # this fabricated state is not presented as a causal software episode.
    calc.wave.price=85;calc.reference=deepcopy(calc.history[-1][-1]);calc.state='DULL'
    assert calc._select_eligible_reference(calc.wave,calc.history[-1]) is None


def test_no_proactive_switch_before_old_reference_breaks():
    calc=prepared();step=calc.step(bar(7,89,-4))
    assert calc.reference.dif==-5 and not step.events


def test_rescued_reference_can_really_fail_on_the_very_next_bar():
    calc=prepared();calc.step(bar(7,89,-6));step=calc.step(bar(8,88,-21))
    assert [e['type'] for e in step.events]==['CANCEL'] and calc.state=='NONE'
    assert step.events[0]['eventReference']['dif']==-20


def test_rescue_uses_original_segment_price_not_an_extra_current_close_gate():
    calc=prepared();calc.step(bar(7,89,-4))
    step=calc.step(bar(8,95,-6))
    assert calc.state=='DULL' and calc.reference.price==90 and not step.events
    assert calc.wave.price==89


def test_following_turn_confirms_structure_using_the_rescued_reference():
    # The old-a1 contrast is preserved in baseline_source.zip, not a second
    # engine in the new product tests. These expectations are literal.
    calc=prepared();calc.step(bar(7,89,-6))
    step=calc.step(bar(8,89,-5.9))
    assert step.events[0]['type']=='STRUCTURE' and step.events[0]['route']=='dif_turn'
    assert step.events[0]['eventReference']['dif']==-20


def test_structure_state_is_not_rescued():
    calc=prepared();step=calc.step(bar(7,101,-2.95))
    assert step.events[0]['type']=='STRUCTURE'
    step=calc.step(bar(8,89,-6))
    assert step.events[0]['type']=='CANCEL'


def test_none_first_entry_is_not_reclassified_as_rescue():
    calc=prepared(values=VALUES[:-1]);step=calc.step(bar(6,89,-6))
    assert step.events[0]['type']=='DULL' and step.events[0]['route']=='activation'
    assert calc.reference.dif==-20


def test_waiting_reference_break_only_ends_wait():
    calc=prepared();calc.step(bar(7,101,-2.95));step=calc.step(bar(8,101,-3.1))
    assert step.events[0]['type']=='STRUCTURE_DISAPPEARED' and calc.pending_rearm is not None
    step=calc.step(bar(9,89,-6))
    assert calc.state=='NONE' and calc.pending_rearm is None and not step.events


def test_top_mirror_uses_unchanged_product_cancellation():
    values=[(200-c,-d,-h) for c,d,h in VALUES]
    calc=prepared(values=values);step=calc.step(bar(7,111,6,2))
    assert step.events[0]['direction']=='TOP' and step.events[0]['type']=='CANCEL'
    assert calc.reference is None


@pytest.mark.parametrize('hist', [0,2])
def test_zero_or_red_bar_is_not_rescued(hist):
    calc=prepared();step=calc.step(bar(7,89,-6,hist))
    assert calc.state=='NONE' and calc.reference is None
    assert [e['type'] for e in step.events]==(['CANCEL'] if hist else [])


@pytest.mark.parametrize('bad', [replace(bar(7,89,-6),completed=False),replace(bar(7,89,-6),dif=float('nan')),bar(6,89,-6)])
def test_rejected_bar_does_not_mutate_reference(bad):
    calc=prepared();saved=calc.snapshot()
    with pytest.raises(ValueError):calc.step(bad)
    assert calc.snapshot()==saved


def test_explicit_research_child_keeps_policy_and_does_not_pollute_parent():
    calc=prepared();saved=calc.snapshot();child=clone(calc)
    assert type(child) is XxmCalculator
    child.step(bar(7,89,-6))
    assert child.reference.dif==-20 and calc.snapshot()==saved
    restored=clone(child)
    assert restored.snapshot()==child.snapshot()
    assert restored.step(bar(8,89,-7))==child.step(bar(8,89,-7))


def test_same_dif_priority_retains_original_reversed_pool_stable_order():
    calc=prepared();older,newer=calc.history[-1]
    older.dif=newer.dif=-20
    calc.wave.price=89
    assert calc._select_eligible_reference(calc.wave,calc.history[-1]) is newer
