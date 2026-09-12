from dataclasses import FrozenInstanceError

import pytest

from src.biz.services.wealth.market.trading_assistant.execution_policy import (
    Deadline, DeadlineExceeded, TradingAssistantExecutionPolicyV1, TradingAssistantPayloadBudgetV1)


def test_frozen_policy_and_budget_order():
    policy = TradingAssistantExecutionPolicyV1()
    assert policy.page_rows == 500 and policy.page_bytes == 1048576
    assert policy.read_request_budget_ms < 8000
    assert policy.write_request_budget_ms < 12000
    with pytest.raises(FrozenInstanceError):
        policy.page_rows = 1000
    assert TradingAssistantPayloadBudgetV1().aggregate_payload_target_bytes == 5242880


@pytest.mark.parametrize("kwargs", [dict(local_concurrency=2), dict(page_rows=True),
    dict(lock_timeout_ms=2000), dict(max_validation_rebases=2), dict(lease_seconds=1)])
def test_invalid_policy_rejected(kwargs):
    with pytest.raises(ValueError):
        TradingAssistantExecutionPolicyV1(**kwargs)


def test_shared_deadline_does_not_restart_on_child_call():
    now = [0.0]
    deadline = Deadline.after_ms(10000, lambda: now[0])
    assert deadline.bounded_ms(1000) == 1000
    now[0] = 9.5
    assert deadline.bounded_ms(1000) == 500
    now[0] = 10.0
    with pytest.raises(DeadlineExceeded):
        deadline.remaining_ms()
