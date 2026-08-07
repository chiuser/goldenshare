from __future__ import annotations

import pytest

from orchestrator.defs.run_contracts.cn_a_derived_minute_bars import (
    AUCTION_ANCHOR_ROLE,
    REGULAR_SOURCE_ROLE,
    cn_a_derived_minute_completion_predicate,
    cn_a_derived_minute_target_times,
    cn_a_derived_minute_window_map_sql,
    cn_a_derived_minute_window_rows,
    cn_a_derived_minute_windows,
    normalize_cn_a_derived_minute_freq,
)


def test_shared_windows_freeze_90m_and_120m_contract() -> None:
    windows_90 = cn_a_derived_minute_windows(90)
    assert [window.target_time for window in windows_90] == [
        "11:00:00",
        "14:00:00",
        "15:00:00",
    ]
    assert windows_90[0].auction_anchor_time == "09:30:00"
    assert windows_90[0].regular_source_times == (
        "10:00:00",
        "10:30:00",
        "11:00:00",
    )
    assert windows_90[1].regular_source_times == (
        "11:30:00",
        "13:30:00",
        "14:00:00",
    )
    assert windows_90[2].regular_source_times == ("14:30:00", "15:00:00")

    windows_120 = cn_a_derived_minute_windows("120min")
    assert [window.target_time for window in windows_120] == [
        "11:30:00",
        "15:00:00",
    ]
    assert windows_120[0].auction_anchor_time == "09:30:00"
    assert windows_120[0].regular_source_times == ("10:30:00", "11:30:00")
    assert windows_120[1].regular_source_times == ("14:00:00", "15:00:00")


def test_anchor_is_a_separate_source_role() -> None:
    rows = cn_a_derived_minute_window_rows(120)
    assert rows == (
        ("09:30:00", AUCTION_ANCHOR_ROLE, 1, "11:30:00", 2, 1),
        ("10:30:00", REGULAR_SOURCE_ROLE, 1, "11:30:00", 2, 1),
        ("11:30:00", REGULAR_SOURCE_ROLE, 1, "11:30:00", 2, 1),
        ("14:00:00", REGULAR_SOURCE_ROLE, 2, "15:00:00", 2, 0),
        ("15:00:00", REGULAR_SOURCE_ROLE, 2, "15:00:00", 2, 0),
    )
    sql = cn_a_derived_minute_window_map_sql(120)
    assert "'09:30:00', 'auction_anchor', 1, '11:30:00'" in sql
    assert "'09:30:00', 'regular'" not in sql


def test_target_times_and_completion_predicate_are_exact() -> None:
    assert cn_a_derived_minute_target_times(90) == (
        "11:00:00",
        "14:00:00",
        "15:00:00",
    )
    assert cn_a_derived_minute_target_times(120) == ("11:30:00", "15:00:00")
    predicate = cn_a_derived_minute_completion_predicate(
        regular_row_count_column="regular_rows",
        regular_time_count_column="regular_times",
        anchor_row_count_column="anchor_rows",
        anchor_time_count_column="anchor_times",
        expected_regular_count_column="expected_regular",
        expected_anchor_count_column="expected_anchor",
    )
    assert predicate == (
        "regular_rows = expected_regular AND regular_times = expected_regular "
        "AND anchor_rows = expected_anchor AND anchor_times = expected_anchor"
    )


def test_invalid_frequency_is_rejected() -> None:
    assert normalize_cn_a_derived_minute_freq("90m") == 90
    with pytest.raises(ValueError):
        normalize_cn_a_derived_minute_freq(60)
    with pytest.raises(ValueError):
        normalize_cn_a_derived_minute_freq(True)
