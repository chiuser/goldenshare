"""Curve coverage folds preserve the first missing prefix per account."""
from types import SimpleNamespace
from uuid import UUID

import pytest

from src.biz.queries.wealth.market.trading_assistant.return_curve import curve_coverage
from src.biz.schemas.wealth.market.trading_assistant.common import AccountCoverage


def account(day, status, *, key=1, through=None):
    return AccountCoverage(accountId=str(UUID(int=key)), initializedOn="2026-09-01",
        effectiveStartDate=f"2026-09-{day:02}", targetThroughDate=f"2026-09-{day:02}",
        calculatedThroughDate=through, valuationAt=None, dataStatus=status,
        reason=None if status in ("Ready", "Empty") else "收益尚未就绪")


@pytest.mark.parametrize("missing", ["Delayed", "Error", "Recalculating", "Partial"])
def test_curve_does_not_advance_past_missing_period(missing):
    points = [SimpleNamespace(accounts=[account(1, "Ready", through="2026-09-01")]),
              SimpleNamespace(accounts=[account(2, missing)]),
              SimpleNamespace(accounts=[account(3, "Ready", through="2026-09-03")])]
    result = curve_coverage(points)
    assert result.dataStatus == "Partial" and not result.isFinal
    assert result.accounts[0].calculatedThroughDate == "2026-09-01"
    assert result.accounts[0].effectiveStartDate == "2026-09-01"
    assert result.accounts[0].targetThroughDate == "2026-09-03"


def test_curve_accounts_keep_independent_completion_and_cash_does_not_dilute():
    points = [SimpleNamespace(accounts=[account(1, "Delayed"), account(1, "Ready", key=2, through="2026-09-01")]),
              SimpleNamespace(accounts=[account(2, "Ready", through="2026-09-02"),
                  account(2, "Ready", key=2, through="2026-09-02"), account(2, "Empty", key=3)])]
    result = curve_coverage(points)
    assert result.dataStatus == "Partial"
    assert [a.calculatedThroughDate for a in result.accounts] == [None, "2026-09-02", None]
    assert curve_coverage([SimpleNamespace(accounts=points[1].accounts[1:])]).dataStatus == "Ready"


def test_curve_empty_points_have_no_fabricated_account_coverage():
    result = curve_coverage([])
    assert result.dataStatus == "Empty" and result.isFinal and result.accounts == []
