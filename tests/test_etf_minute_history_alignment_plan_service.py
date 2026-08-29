from __future__ import annotations

import json
from datetime import date, datetime, timezone
from uuid import UUID

import pytest

from src.foundation.dao.etf_basic_dao import (
    EtfRequestTarget,
    EtfRequestabilitySnapshot,
)
from src.foundation.ingestion.etf_minute_windows import build_etf_minute_windows
from src.ops.services.etf_minute_history_alignment_plan_service import (
    ETF_MINUTE_FREQUENCIES,
    EtfMinuteHistoryAlignmentPlanError,
    EtfMinuteHistoryAlignmentPlanService,
    EtfMinuteRawMonthlyCoverage,
    EtfMinuteSuccessfulTaskCoverage,
    canonical_etf_minute_alignment_hash,
)


GENERATED_AT = datetime(2026, 8, 28, 16, 30, tzinfo=timezone.utc)
ALIGNMENT_START_DATE = date(2024, 1, 2)
ALIGNMENT_END_DATE = date(2026, 8, 28)


def _target(
    ts_code: str = "510300.SH",
    *,
    list_date: date = date(2024, 1, 2),
    exchange: str = "SH",
) -> EtfRequestTarget:
    return EtfRequestTarget(  # type: ignore[arg-type]
        ts_code=ts_code,
        list_date=list_date,
        exchange=exchange,
    )


def _snapshot(
    *targets: EtfRequestTarget,
    excluded_reason_counts: dict[str, int] | None = None,
    serving_row_count: int | None = None,
) -> EtfRequestabilitySnapshot:
    return EtfRequestabilitySnapshot(
        as_of_date=date(2026, 8, 29),
        exchange=None,
        targets=tuple(targets),
        serving_row_count=serving_row_count or len(targets),
        requestable_count=len(targets),
        excluded_reason_counts=excluded_reason_counts or {},
    )


def _service() -> EtfMinuteHistoryAlignmentPlanService:
    return EtfMinuteHistoryAlignmentPlanService(
        uuid_factory=lambda: UUID("00000000-0000-0000-0000-000000000001")
    )


def _raw_for_all(
    *,
    start_date: date,
    end_date: date,
    ts_code: str = "510300.SH",
) -> tuple[EtfMinuteRawMonthlyCoverage, ...]:
    return tuple(
        EtfMinuteRawMonthlyCoverage(
            ts_code=ts_code,
            frequency=frequency,
            month_start=date(start_date.year, start_date.month, 1),
            row_count=1,
            start_date=start_date,
            end_date=end_date,
        )
        for frequency in ETF_MINUTE_FREQUENCIES
    )


def _tasks_for_all(
    *,
    start_date: date,
    end_date: date,
    ts_code: str = "510300.SH",
) -> tuple[EtfMinuteSuccessfulTaskCoverage, ...]:
    return tuple(
        EtfMinuteSuccessfulTaskCoverage(
            ts_code=ts_code,
            frequency=frequency,
            start_date=start_date,
            end_date=end_date,
        )
        for frequency in ETF_MINUTE_FREQUENCIES
    )


def _build(
    *,
    targets: tuple[EtfRequestTarget, ...] = (_target(),),
    raw: tuple[EtfMinuteRawMonthlyCoverage, ...] = (),
    tasks: tuple[EtfMinuteSuccessfulTaskCoverage, ...] = (),
    alignment_start_date: date = ALIGNMENT_START_DATE,
    alignment_end_date: date = ALIGNMENT_END_DATE,
    alignment_open_dates: tuple[date, ...] | None = None,
    excluded_reason_counts: dict[str, int] | None = None,
):
    return _service().build_plan_from_coverage(
        snapshot=_snapshot(
            *targets,
            excluded_reason_counts=excluded_reason_counts,
        ),
        alignment_start_date=alignment_start_date,
        alignment_end_date=alignment_end_date,
        generated_at=GENERATED_AT,
        alignment_open_dates=(
            alignment_open_dates
            if alignment_open_dates is not None
            else (alignment_start_date, alignment_end_date)
        ),
        raw_monthly_coverages=raw,
        successful_task_coverages=tasks,
    )


def test_no_coverage_generates_one_merged_full_range_action() -> None:
    plan = _build()

    assert plan.requestable_etf_count == 1
    assert plan.alignment_target_etf_count == 1
    assert plan.raw_covered_target_frequency_count == 0
    assert plan.missing_prefix_target_frequency_count == 5
    assert plan.missing_suffix_target_frequency_count == 0
    assert plan.planned_action_count == 1
    assert plan.actions[0].frequencies == ETF_MINUTE_FREQUENCIES
    assert plan.actions[0].start_date == date(2024, 1, 2)
    assert plan.actions[0].end_date == ALIGNMENT_END_DATE
    assert plan.source_request_lower_bound == plan.planned_unit_count
    assert plan.page_request_upper_bound == plan.planned_unit_count * 4


@pytest.mark.parametrize(
    ("raw_start", "raw_end", "expected_start", "expected_end", "prefix", "suffix"),
    [
        (
            date(2024, 1, 2),
            date(2025, 1, 31),
            date(2025, 2, 1),
            ALIGNMENT_END_DATE,
            0,
            5,
        ),
        (
            date(2025, 2, 1),
            ALIGNMENT_END_DATE,
            date(2024, 1, 2),
            date(2025, 1, 31),
            5,
            0,
        ),
    ],
)
def test_prefix_or_suffix_coverage_generates_only_outer_gap(
    raw_start: date,
    raw_end: date,
    expected_start: date,
    expected_end: date,
    prefix: int,
    suffix: int,
) -> None:
    plan = _build(raw=_raw_for_all(start_date=raw_start, end_date=raw_end))

    assert plan.planned_action_count == 1
    assert plan.actions[0].start_date == expected_start
    assert plan.actions[0].end_date == expected_end
    assert plan.missing_prefix_target_frequency_count == prefix
    assert plan.missing_suffix_target_frequency_count == suffix


def test_full_coverage_generates_no_action() -> None:
    plan = _build(
        raw=_raw_for_all(
            start_date=date(2024, 1, 2),
            end_date=ALIGNMENT_END_DATE,
        )
    )

    assert plan.raw_covered_target_frequency_count == 5
    assert plan.planned_action_count == 0
    assert plan.planned_unit_count == 0


def test_requested_start_uses_first_open_date_without_false_holiday_prefix() -> None:
    first_open = date(2026, 1, 5)
    end_date = date(2026, 1, 9)
    plan = _build(
        targets=(_target(list_date=date(2020, 1, 1)),),
        alignment_start_date=date(2026, 1, 1),
        alignment_end_date=end_date,
        alignment_open_dates=(
            first_open,
            date(2026, 1, 6),
            date(2026, 1, 7),
            date(2026, 1, 8),
            end_date,
        ),
        raw=_raw_for_all(start_date=first_open, end_date=end_date),
    )

    assert plan.alignment_start_date == date(2026, 1, 1)
    assert plan.raw_covered_target_frequency_count == 5
    assert plan.missing_prefix_target_frequency_count == 0
    assert plan.planned_action_count == 0


def test_requested_start_is_clipped_by_list_date_then_next_open_date() -> None:
    plan = _build(
        targets=(_target(list_date=date(2026, 1, 3)),),
        alignment_start_date=date(2026, 1, 1),
        alignment_end_date=date(2026, 1, 9),
        alignment_open_dates=(
            date(2026, 1, 5),
            date(2026, 1, 6),
            date(2026, 1, 7),
            date(2026, 1, 8),
            date(2026, 1, 9),
        ),
    )

    assert plan.planned_action_count == 1
    assert plan.actions[0].start_date == date(2026, 1, 5)
    assert plan.actions[0].end_date == date(2026, 1, 9)


def test_raw_entirely_before_current_list_date_does_not_count_as_coverage() -> None:
    plan = _build(
        raw=_raw_for_all(
            start_date=date(2020, 1, 1),
            end_date=date(2023, 12, 31),
        )
    )

    assert plan.raw_covered_target_frequency_count == 0
    assert plan.actions[0].start_date == date(2024, 1, 2)
    assert plan.actions[0].end_date == ALIGNMENT_END_DATE


def test_raw_and_task_intervals_are_clipped_and_internal_gap_is_not_requested() -> None:
    plan = _build(
        raw=_raw_for_all(
            start_date=date(2020, 1, 1),
            end_date=date(2024, 2, 1),
        ),
        tasks=_tasks_for_all(
            start_date=date(2026, 8, 1),
            end_date=date(2027, 1, 1),
        ),
    )

    assert plan.planned_action_count == 0
    assert plan.raw_covered_target_frequency_count == 5
    assert plan.interior_gap_not_audited is True


def test_successful_explicit_task_can_cover_pair_without_raw_boundary() -> None:
    plan = _build(
        tasks=_tasks_for_all(
            start_date=date(2024, 1, 2),
            end_date=ALIGNMENT_END_DATE,
        )
    )

    assert plan.raw_covered_target_frequency_count == 0
    assert plan.successful_task_only_covered_target_frequency_count == 5
    assert plan.planned_action_count == 0


def test_same_range_frequencies_merge_but_different_ranges_do_not() -> None:
    raw = (
        EtfMinuteRawMonthlyCoverage(
            ts_code="510300.SH",
            frequency="1min",
            month_start=date(2024, 1, 1),
            row_count=1,
            start_date=date(2024, 1, 2),
            end_date=date(2025, 1, 31),
        ),
        EtfMinuteRawMonthlyCoverage(
            ts_code="510300.SH",
            frequency="5min",
            month_start=date(2024, 1, 1),
            row_count=1,
            start_date=date(2024, 1, 2),
            end_date=date(2025, 1, 31),
        ),
        *_raw_for_all(
            start_date=date(2024, 1, 2),
            end_date=ALIGNMENT_END_DATE,
        )[2:],
    )
    plan = _build(raw=raw)

    assert plan.planned_action_count == 1
    assert plan.actions[0].frequencies == ("1min", "5min")

    different = _build(
        raw=(
            EtfMinuteRawMonthlyCoverage(
                ts_code="510300.SH",
                frequency="1min",
                month_start=date(2024, 1, 1),
                row_count=1,
                start_date=date(2024, 1, 2),
                end_date=date(2025, 1, 31),
            ),
            EtfMinuteRawMonthlyCoverage(
                ts_code="510300.SH",
                frequency="5min",
                month_start=date(2024, 1, 1),
                row_count=1,
                start_date=date(2024, 1, 2),
                end_date=date(2025, 2, 28),
            ),
            *_raw_for_all(
                start_date=date(2024, 1, 2),
                end_date=ALIGNMENT_END_DATE,
            )[2:],
        )
    )
    assert different.planned_action_count == 2
    assert [action.frequencies for action in different.actions] == [
        ("1min",),
        ("5min",),
    ]


def test_target_listed_after_alignment_end_is_hashed_but_not_aligned() -> None:
    current = _target()
    future = _target(
        "159001.SZ",
        list_date=date(2026, 9, 1),
        exchange="SZ",
    )
    plan = _build(targets=(future, current))
    current_only = _build(targets=(current,))

    assert plan.requestable_etf_count == 2
    assert plan.alignment_target_etf_count == 1
    assert plan.list_date_after_alignment_end_count == 1
    assert all(action.ts_code == current.ts_code for action in plan.actions)
    assert plan.request_target_hash != current_only.request_target_hash


def test_unit_counts_reuse_existing_window_builder_for_each_frequency() -> None:
    plan = _build()
    action = plan.actions[0]
    expected = sum(
        len(
            build_etf_minute_windows(
                freq=frequency,
                start_date=action.start_date,
                end_date=action.end_date,
            )
        )
        for frequency in ETF_MINUTE_FREQUENCIES
    )

    assert action.planned_unit_count == expected
    assert plan.planned_unit_count == expected
    assert [item.frequency for item in plan.frequency_summaries] == list(
        ETF_MINUTE_FREQUENCIES
    )


def test_actions_and_payload_have_stable_order() -> None:
    plan = _build(
        targets=(
            _target("159001.SZ", exchange="SZ"),
            _target("510300.SH"),
        )
    )
    payload = plan.to_payload()

    assert [action.ts_code for action in plan.actions] == ["159001.SZ", "510300.SH"]
    assert payload["actions"][0]["frequencies"] == list(ETF_MINUTE_FREQUENCIES)
    assert json.loads(plan.to_json()) == payload


def test_target_hash_uses_only_sorted_code_list_date_and_exchange() -> None:
    first = _target("510300.SH")
    second = _target("159001.SZ", exchange="SZ")
    plan_a = _service().build_plan_from_coverage(
        snapshot=_snapshot(
            first,
            second,
            excluded_reason_counts={"STATUS_NOT_LISTED": 10},
            serving_row_count=99,
        ),
        alignment_start_date=ALIGNMENT_START_DATE,
        alignment_end_date=ALIGNMENT_END_DATE,
        generated_at=GENERATED_AT,
        alignment_open_dates=(ALIGNMENT_START_DATE, ALIGNMENT_END_DATE),
        raw_monthly_coverages=(),
        successful_task_coverages=(),
    )
    plan_b = _service().build_plan_from_coverage(
        snapshot=_snapshot(
            second,
            first,
            excluded_reason_counts={"STATUS_NOT_LISTED": 20},
            serving_row_count=199,
        ),
        alignment_start_date=ALIGNMENT_START_DATE,
        alignment_end_date=ALIGNMENT_END_DATE,
        generated_at=GENERATED_AT,
        alignment_open_dates=(ALIGNMENT_START_DATE, ALIGNMENT_END_DATE),
        raw_monthly_coverages=(),
        successful_task_coverages=(),
    )
    changed_date = _build(
        targets=(_target("510300.SH", list_date=date(2024, 1, 3)), second)
    )
    changed_exchange = _build(
        targets=(_target("510300.SH", exchange="SZ"), second)
    )

    assert plan_a.request_target_hash == plan_b.request_target_hash
    assert plan_a.request_target_hash != changed_date.request_target_hash
    assert plan_a.request_target_hash != changed_exchange.request_target_hash


def test_plan_content_hash_is_canonical_payload_without_hash_field() -> None:
    plan = _build(excluded_reason_counts={"STATUS_NOT_LISTED": 2})

    assert plan.plan_content_hash == canonical_etf_minute_alignment_hash(
        plan.to_payload(include_content_hash=False)
    )


def test_requested_window_changes_plan_hash_but_not_request_target_hash() -> None:
    original = _build()
    narrowed = _build(
        alignment_start_date=date(2025, 1, 2),
        alignment_open_dates=(date(2025, 1, 2), ALIGNMENT_END_DATE),
    )

    assert original.request_target_hash == narrowed.request_target_hash
    assert original.plan_content_hash != narrowed.plan_content_hash
    assert narrowed.to_payload()["alignment_start_date"] == "2025-01-02"
    assert narrowed.actions[0].start_date == date(2025, 1, 2)


def test_task_parser_restores_multi_code_point_and_historical_string_range() -> None:
    point = _service()._parse_task_coverage(  # noqa: SLF001
        filters_json={
            "ts_code": ["510300.sh", "159915.sz", "510300.SH"],
            "freq": ["5min", "1min"],
        },
        time_input_json={"mode": "point", "trade_date": "2026-08-28"},
    )
    range_items = _service()._parse_task_coverage(  # noqa: SLF001
        filters_json={"ts_code": "510300.SH", "freq": ["60min", "15min"]},
        time_input_json={
            "mode": "range",
            "start_date": "2026-08-01",
            "end_date": "2026-08-28",
        },
    )

    assert [
        (item.ts_code, item.frequency, item.start_date, item.end_date)
        for item in point
    ] == [
        ("159915.SZ", "1min", ALIGNMENT_END_DATE, ALIGNMENT_END_DATE),
        ("159915.SZ", "5min", ALIGNMENT_END_DATE, ALIGNMENT_END_DATE),
        ("510300.SH", "1min", ALIGNMENT_END_DATE, ALIGNMENT_END_DATE),
        ("510300.SH", "5min", ALIGNMENT_END_DATE, ALIGNMENT_END_DATE),
    ]
    assert {item.ts_code for item in range_items} == {"510300.SH"}
    assert [item.frequency for item in range_items] == ["15min", "60min"]


@pytest.mark.parametrize(
    ("filters_json", "time_input_json"),
    [
        ({"freq": ["1min"]}, {"mode": "point", "trade_date": "2026-08-28"}),
        ({"ts_code": [], "freq": ["1min"]}, {"mode": "point", "trade_date": "2026-08-28"}),
        ({"ts_code": ["510300.SH", 159915], "freq": ["1min"]}, {"mode": "point", "trade_date": "2026-08-28"}),
        ({"ts_code": ["510300.SH", "  "], "freq": ["1min"]}, {"mode": "point", "trade_date": "2026-08-28"}),
        ({"ts_code": "510300.SH", "freq": []}, {"mode": "point", "trade_date": "2026-08-28"}),
        ({"ts_code": "510300.SH", "freq": ["2min"]}, {"mode": "point", "trade_date": "2026-08-28"}),
        ({"ts_code": "510300.SH", "freq": ["1min"]}, {"mode": "point"}),
        ({"ts_code": "510300.SH", "freq": ["1min"]}, {"mode": "range", "start_date": "2026-08-01"}),
        ({"ts_code": "510300.SH", "freq": ["1min"]}, {"mode": "range", "start_date": "2026-08-29", "end_date": "2026-08-28"}),
        ({"ts_code": "510300.SH", "freq": ["1min"]}, {"mode": "none"}),
    ],
)
def test_task_parser_ignores_pool_incomplete_and_invalid_tasks(
    filters_json,
    time_input_json,
) -> None:
    assert (
        _service()._parse_task_coverage(  # noqa: SLF001
            filters_json=filters_json,
            time_input_json=time_input_json,
        )
        == ()
    )


def test_build_plan_reads_clock_calendars_basic_raw_and_tasks_once(mocker) -> None:
    import src.ops.services.etf_minute_history_alignment_plan_service as module

    clock = mocker.Mock(return_value=GENERATED_AT)
    calendar = mocker.Mock()
    calendar.get_latest_open_date.return_value = ALIGNMENT_END_DATE
    first_open = date(2026, 1, 5)
    calendar.get_open_dates.return_value = [first_open, ALIGNMENT_END_DATE]
    basic = mocker.Mock()
    basic.load_requestability_snapshot.return_value = _snapshot(_target())
    mocker.patch.object(module, "TradeCalendarDAO", return_value=calendar)
    mocker.patch.object(module, "EtfBasicDAO", return_value=basic)
    service = EtfMinuteHistoryAlignmentPlanService(clock=clock)
    raw_loader = mocker.patch.object(
        service,
        "_load_raw_monthly_coverages",
        return_value=(),
    )
    task_loader = mocker.patch.object(
        service,
        "_load_successful_task_coverages",
        return_value=(),
    )
    session = mocker.Mock()

    service.build_plan(
        session,
        alignment_start_date=date(2026, 1, 1),
        alignment_end_date=ALIGNMENT_END_DATE,
    )

    clock.assert_called_once_with()
    calendar.get_latest_open_date.assert_called_once_with("SSE", date(2026, 8, 29))
    calendar.get_open_dates.assert_called_once_with(
        "SSE", date(2026, 1, 1), ALIGNMENT_END_DATE
    )
    basic.load_requestability_snapshot.assert_called_once_with(
        as_of_date=date(2026, 8, 29)
    )
    raw_loader.assert_called_once_with(
        session,
        earliest_alignment_date=first_open,
        alignment_end_date=ALIGNMENT_END_DATE,
    )
    task_loader.assert_called_once_with(session)


@pytest.mark.parametrize(
    ("latest_open", "open_dates", "expected_code"),
    [
        (None, [], "trade_calendar_not_ready"),
        (date(2026, 8, 27), [], "alignment_end_date_after_latest_open"),
        (ALIGNMENT_END_DATE, [], "alignment_end_date_not_open"),
    ],
)
def test_calendar_validation_is_structured_and_does_not_load_basic(
    mocker,
    latest_open,
    open_dates,
    expected_code,
) -> None:
    import src.ops.services.etf_minute_history_alignment_plan_service as module

    calendar = mocker.Mock()
    calendar.get_latest_open_date.return_value = latest_open
    calendar.get_open_dates.return_value = open_dates
    basic_cls = mocker.patch.object(module, "EtfBasicDAO")
    mocker.patch.object(module, "TradeCalendarDAO", return_value=calendar)

    with pytest.raises(EtfMinuteHistoryAlignmentPlanError) as captured:
        EtfMinuteHistoryAlignmentPlanService(clock=lambda: GENERATED_AT).build_plan(
            mocker.Mock(),
            alignment_start_date=date(2026, 1, 1),
            alignment_end_date=ALIGNMENT_END_DATE,
        )

    assert captured.value.code == expected_code
    calendar.get_latest_open_date.assert_called_once()
    calendar.get_open_dates.assert_called_once()
    basic_cls.assert_not_called()


def test_start_date_after_end_date_is_rejected_before_dao_queries(mocker) -> None:
    import src.ops.services.etf_minute_history_alignment_plan_service as module

    calendar_cls = mocker.patch.object(module, "TradeCalendarDAO")
    basic_cls = mocker.patch.object(module, "EtfBasicDAO")

    with pytest.raises(EtfMinuteHistoryAlignmentPlanError) as captured:
        EtfMinuteHistoryAlignmentPlanService(clock=lambda: GENERATED_AT).build_plan(
            mocker.Mock(),
            alignment_start_date=date(2026, 8, 29),
            alignment_end_date=ALIGNMENT_END_DATE,
        )

    assert captured.value.code == "alignment_start_date_after_end_date"
    calendar_cls.assert_not_called()
    basic_cls.assert_not_called()


def test_empty_basic_universe_is_structured_and_skips_coverage_queries(mocker) -> None:
    import src.ops.services.etf_minute_history_alignment_plan_service as module

    calendar = mocker.Mock()
    calendar.get_latest_open_date.return_value = ALIGNMENT_END_DATE
    calendar.get_open_dates.return_value = [date(2026, 1, 5), ALIGNMENT_END_DATE]
    basic = mocker.Mock()
    basic.load_requestability_snapshot.return_value = _snapshot()
    mocker.patch.object(module, "TradeCalendarDAO", return_value=calendar)
    mocker.patch.object(module, "EtfBasicDAO", return_value=basic)
    service = EtfMinuteHistoryAlignmentPlanService(clock=lambda: GENERATED_AT)
    raw_loader = mocker.patch.object(service, "_load_raw_monthly_coverages")
    task_loader = mocker.patch.object(service, "_load_successful_task_coverages")

    with pytest.raises(EtfMinuteHistoryAlignmentPlanError) as captured:
        service.build_plan(
            mocker.Mock(),
            alignment_start_date=date(2026, 1, 1),
            alignment_end_date=ALIGNMENT_END_DATE,
        )

    assert captured.value.code == "universe_empty"
    raw_loader.assert_not_called()
    task_loader.assert_not_called()


def test_raw_loader_queries_once_per_month_with_half_open_bounds(mocker) -> None:
    january = mocker.Mock()
    january.mappings.return_value = [
        {
            "ts_code": "510300.SH",
            "freq": "1min",
            "row_count": 100,
            "min_trade_time": datetime(2024, 1, 2, 9, 31),
            "max_trade_time": datetime(2024, 1, 31, 15, 0),
        },
        {
            "ts_code": "510300.SH",
            "freq": "5min",
            "row_count": 0,
            "min_trade_time": None,
            "max_trade_time": None,
        },
    ]
    february = mocker.Mock()
    february.mappings.return_value = []
    session = mocker.Mock()
    session.execute.side_effect = [january, february]

    coverages = _service()._load_raw_monthly_coverages(  # noqa: SLF001
        session,
        earliest_alignment_date=date(2024, 1, 2),
        alignment_end_date=date(2024, 2, 20),
    )

    assert session.execute.call_count == 2
    statement = str(session.execute.call_args_list[0].args[0])
    assert "COUNT(*)" in statement
    assert "MIN(raw.trade_time)" in statement
    assert "MAX(raw.trade_time)" in statement
    assert "GROUP BY raw.ts_code, raw.freq" in statement
    assert "etf_basic" not in statement
    assert "LATERAL" not in statement
    assert session.execute.call_args_list[0].args[1] == {
        "month_start": date(2024, 1, 1),
        "next_month_start": date(2024, 2, 1),
    }
    assert session.execute.call_args_list[1].args[1] == {
        "month_start": date(2024, 2, 1),
        "next_month_start": date(2024, 3, 1),
    }
    assert len(coverages) == 1
    assert coverages[0].month_start == date(2024, 1, 1)
    assert coverages[0].row_count == 100


def test_month_sequence_crosses_year_boundary_without_weekly_subdivision() -> None:
    assert _service()._month_starts(  # noqa: SLF001
        date(2024, 11, 30),
        date(2025, 2, 1),
    ) == (
        date(2024, 11, 1),
        date(2024, 12, 1),
        date(2025, 1, 1),
        date(2025, 2, 1),
    )


def test_raw_month_failure_propagates_without_retry_or_weekly_fallback(mocker) -> None:
    first_month = mocker.Mock()
    first_month.mappings.return_value = []
    session = mocker.Mock()
    session.execute.side_effect = [first_month, RuntimeError("month failed")]

    with pytest.raises(RuntimeError, match="month failed"):
        _service()._load_raw_monthly_coverages(  # noqa: SLF001
            session,
            earliest_alignment_date=date(2024, 1, 2),
            alignment_end_date=date(2024, 3, 20),
        )

    assert session.execute.call_count == 2
    assert session.execute.call_args_list[1].args[1] == {
        "month_start": date(2024, 2, 1),
        "next_month_start": date(2024, 3, 1),
    }


def test_successful_task_loader_executes_one_query_and_ignores_invalid_rows(mocker) -> None:
    result = mocker.Mock()
    result.all.return_value = [
        (
            {
                "ts_code": ["510300.SH", "159915.SZ"],
                "freq": ["1min", "5min"],
            },
            {"mode": "range", "start_date": "2026-08-01", "end_date": "2026-08-28"},
        ),
        ({"freq": ["1min"]}, {"mode": "point", "trade_date": "2026-08-28"}),
    ]
    session = mocker.Mock()
    session.execute.return_value = result

    coverages = _service()._load_successful_task_coverages(session)  # noqa: SLF001

    session.execute.assert_called_once()
    assert [(item.ts_code, item.frequency) for item in coverages] == [
        ("159915.SZ", "1min"),
        ("159915.SZ", "5min"),
        ("510300.SH", "1min"),
        ("510300.SH", "5min"),
    ]


@pytest.mark.parametrize("failing_loader", ["raw", "task"])
def test_coverage_query_exceptions_propagate_without_fallback(mocker, failing_loader) -> None:
    import src.ops.services.etf_minute_history_alignment_plan_service as module

    calendar = mocker.Mock()
    calendar.get_latest_open_date.return_value = ALIGNMENT_END_DATE
    calendar.get_open_dates.return_value = [date(2026, 1, 5), ALIGNMENT_END_DATE]
    basic = mocker.Mock()
    basic.load_requestability_snapshot.return_value = _snapshot(_target())
    mocker.patch.object(module, "TradeCalendarDAO", return_value=calendar)
    mocker.patch.object(module, "EtfBasicDAO", return_value=basic)
    service = EtfMinuteHistoryAlignmentPlanService(clock=lambda: GENERATED_AT)
    raw = mocker.patch.object(
        service,
        "_load_raw_monthly_coverages",
        return_value=(),
    )
    task = mocker.patch.object(service, "_load_successful_task_coverages", return_value=())
    if failing_loader == "raw":
        raw.side_effect = RuntimeError("raw failed")
    else:
        task.side_effect = RuntimeError("task failed")

    with pytest.raises(RuntimeError, match=f"{failing_loader} failed"):
        service.build_plan(
            mocker.Mock(),
            alignment_start_date=date(2026, 1, 1),
            alignment_end_date=ALIGNMENT_END_DATE,
        )
