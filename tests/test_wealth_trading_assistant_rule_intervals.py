from datetime import datetime
from uuid import UUID

import pytest

from src.biz.schemas.wealth.market.trading_assistant.rules import ConditionVersion
from src.biz.services.wealth.market.trading_assistant.condition_intervals import (
    iter_condition_intervals,
)
from src.biz.services.wealth.market.trading_assistant.minute_coverage import (
    audit_minute_coverage,
)


def at(clock):
    return datetime.fromisoformat(f"2026-09-15T{clock}+08:00")


def version(number, clock):
    return ConditionVersion(
        ruleVersionId=str(UUID(int=number)), versionNo=str(number),
        effectiveAt=at(clock).isoformat(), deadlineAt=at("15:00:00").isoformat(),
        conditions={"priceCondition": {"operator": "LTE", "upper": "10.00"},
                    "volumeCondition": None}, conditionSummary="价格不高于10.00",
    )


def test_exact_revision_checkpoint_belongs_only_to_old_version():
    first, second = tuple(iter_condition_intervals([
        version(1, "09:45:30"), version(2, "11:00:00"),
    ]))
    assert not first.contains(at("09:45:30"))
    assert first.contains(at("10:20:00"))  # Unswept old hits remain legitimate.
    assert first.contains(at("11:00:00"))
    assert not second.contains(at("11:00:00"))
    assert second.contains(at("11:01:00"))
    assert second.contains(at("15:00:00"))
    assert not second.contains(at("15:00:01"))


def test_seconds_are_not_rounded_down_and_equal_saved_times_do_not_overlap():
    intervals = tuple(iter_condition_intervals([
        version(1, "10:00:30"), version(2, "10:00:30"),
        version(3, "11:00:30"),
    ]))
    assert not intervals[0].contains(at("10:01:00"))
    for clock, owner in [("10:00:00", None), ("10:01:00", 1),
                         ("11:00:00", 1), ("11:01:00", 2)]:
        assert [i for i, interval in enumerate(intervals) if interval.contains(at(clock))] == (
            [] if owner is None else [owner]
        )


@pytest.mark.parametrize("versions", [[], [version(2, "10:00:00")],
    [version(1, "10:00:00"), version(3, "11:00:00")],
    [version(1, "11:00:00"), version(2, "10:00:00")]])
def test_invalid_history_is_not_silently_sorted_or_filled(versions):
    with pytest.raises(ValueError):
        tuple(iter_condition_intervals(versions))


def test_missing_minute_cannot_be_hidden_by_equal_row_count():
    expected = tuple(at(t) for t in ["09:31:00", "09:32:00", "09:33:00"])
    result = audit_minute_coverage(expected, [expected[0], expected[2], expected[2]])
    assert not result.complete
    assert result.missing == (expected[1],)
    assert result.duplicates == (expected[2],)
    assert result.complete_prefix_through == expected[0]


def test_revision_cannot_change_deadline():
    changed = version(2, "11:00:00").model_copy(update={
        "deadlineAt": at("14:00:00").isoformat(),
    })
    with pytest.raises(ValueError):
        tuple(iter_condition_intervals([version(1, "10:00:00"), changed]))


def test_cross_day_intervals_keep_real_dates():
    first = version(1, "10:00:00").model_copy(update={
        "effectiveAt": "2026-09-14T14:00:30+08:00",
    })
    intervals = tuple(iter_condition_intervals([first, version(2, "10:00:00")]))
    assert intervals[0].contains(datetime.fromisoformat("2026-09-14T15:00:00+08:00"))
    assert intervals[0].contains(at("09:31:00"))
    assert not intervals[1].contains(at("09:31:00"))


def test_expected_grid_must_not_hide_its_own_duplicates():
    with pytest.raises(ValueError):
        audit_minute_coverage((at("09:31:00"), at("09:31:00")), ())


def test_supplied_sessions_skip_lunch_without_inventing_missing_minutes():
    expected = (at("11:30:00"), at("13:01:00"))
    assert audit_minute_coverage(expected, reversed(expected)).complete
    unexpected = audit_minute_coverage(expected, [*expected, at("12:00:00")])
    assert not unexpected.complete
    assert unexpected.complete_prefix_through is None


def test_opening_volume_prefix_must_not_be_skipped():
    required = (at("09:30:00"), at("09:31:00"))
    result = audit_minute_coverage(required, [required[1]])
    assert result.missing == (required[0],)
    assert result.complete_prefix_through is None


def test_unknown_calendar_is_not_inferred_by_this_auditor():
    # An empty *authoritative* set can represent no required checkpoints;
    # absence of calendar evidence must be handled by the caller, not passed as [].
    assert audit_minute_coverage((), ()).complete
    with pytest.raises(ValueError):
        audit_minute_coverage((datetime(2026, 9, 15, 9, 31),), ())
