from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal

import pytest

from src.biz.schemas.wealth.market.trading_assistant.rules import Conditions
from src.biz.services.wealth.market.trading_assistant.condition_intervals import ConditionInterval
from src.biz.services.wealth.market.trading_assistant.execution_policy import (
    Deadline, DeadlineExceeded, TradingAssistantExecutionPolicyV1,
)
from src.biz.services.wealth.market.trading_assistant.rule_minute_batch import (
    MinuteFact, MinuteScanProgress, RequiredMinute, evaluate_minute_batch,
)


DAY = date(2026, 9, 15)


def at(minute):
    return datetime.fromisoformat(f"2026-09-15T09:{minute}:00+08:00")


def run(required, facts, progress=None, **overrides):
    params = dict(
        basis_id="frozen-one", trade_date=DAY,
        condition=Conditions(priceCondition={"operator": "LTE", "upper": "10.00"},
                             volumeCondition={"operator": "GTE", "thresholdLots": "3.00"}),
        interval=ConditionInterval("version-one", at(30), at(35)),
        required=tuple(required), facts=tuple(facts),
        progress=progress or MinuteScanProgress("frozen-one", DAY),
        policy=TradingAssistantExecutionPolicyV1(), deadline=Deadline.after_ms(1000),
    )
    params.update(overrides)
    return evaluate_minute_batch(**params)


def fixture():
    requirements = tuple(RequiredMinute(at(n), n != 30) for n in range(30, 34))
    facts = tuple(MinuteFact(at(n), Decimal("10.00"), 100) for n in range(30, 34))
    return requirements, facts


def test_every_batch_split_matches_whole_scan_and_auction_volume_counts_once():
    required, facts = fixture()
    whole = run(required, facts)
    assert whole.match.at == at(32)
    assert whole.match.cumulative_shares == 300
    for split in (1, 2):
        first = run(required[:split], facts[:split])
        assert first.match is None
        second = run(required[split:], facts[split:], first.progress)
        assert second == whole


def test_missing_prefix_cannot_publish_later_visible_hit():
    required, facts = fixture()
    result = run(required, facts[:1] + facts[2:])
    assert result.match is None
    assert result.waiting_at == at(31)
    assert result.progress.last_at == at(30)
    assert result.progress.cumulative_shares == 100


def test_new_condition_does_not_reset_opening_volume():
    required, facts = fixture()
    first = run(required[:2], facts[:2])
    second = run(required[2:], facts[2:], first.progress,
                 interval=ConditionInterval("version-two", at(31), at(35)))
    assert second.match.version_id == "version-two"
    assert second.match.cumulative_shares == 300


def test_price_only_does_not_require_volume_and_volume_only_does_not_require_price():
    required, facts = fixture()
    price_only = Conditions(priceCondition={"operator": "LTE", "upper": "10.00"},
                            volumeCondition=None)
    result = run(required, [replace(f, volume_shares=None) for f in facts], condition=price_only)
    assert result.match.at == at(31)
    assert result.match.cumulative_shares is None
    volume_only = Conditions(priceCondition=None,
                             volumeCondition={"operator": "GTE", "thresholdLots": "3.00"})
    result = run(required, [replace(f, price=None) for f in facts], condition=volume_only)
    assert result.match.at == at(32)
    assert result.match.price is None


def test_new_basis_or_day_cannot_reuse_old_accumulator():
    required, facts = fixture()
    for override in ({"basis_id": "another"}, {"trade_date": date(2026, 9, 16)}):
        with pytest.raises(ValueError):
            run(required, facts, MinuteScanProgress("frozen-one", DAY), **override)


def test_duplicate_page_or_duplicate_row_is_not_summed_again():
    required, facts = fixture()
    with pytest.raises(ValueError):
        run(required, facts[:1] + facts)
    first = run(required[:1], facts[:1])
    with pytest.raises(ValueError):
        run(required[:1], facts[:1], first.progress)


def test_missing_required_field_preserves_previous_committable_progress():
    required, facts = fixture()
    result = run(required, [facts[0], replace(facts[1], price=None), *facts[2:]])
    assert result.match is None
    assert result.progress.last_at == at(30)
    assert result.waiting_at == at(31)


def test_row_budget_and_deadline_do_not_change_callers_progress():
    required, facts = fixture()
    progress = MinuteScanProgress("frozen-one", DAY)
    with pytest.raises(ValueError):
        run(required, facts, progress, policy=TradingAssistantExecutionPolicyV1(page_rows=1))
    with pytest.raises(DeadlineExceeded):
        run(required, facts, progress, deadline=Deadline(0, lambda: 1))
    assert progress == MinuteScanProgress("frozen-one", DAY)


def test_complete_batch_without_hit_is_not_a_final_false_result():
    required, facts = fixture()
    result = run(required, [replace(f, price=Decimal("20.00")) for f in facts])
    assert result.match is None
    assert result.waiting_at is None
    assert result.progress.last_at == at(33)
