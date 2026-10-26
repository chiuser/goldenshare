"""Frozen dates and single-window execution against temporary production-shaped files."""

import json
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from orchestrator.defs.anns_d_cli import announcement_cli
from orchestrator.defs.anns_d_contract import (
    ANNOUNCEMENT_FIELDS,
    AnnouncementCancelled,
    AnnouncementError,
)
from orchestrator.defs.anns_d_io import AnnouncementStore
from orchestrator.defs.anns_d_window import (
    ANNOUNCEMENT_EXECUTION_VERSION_TAG,
    ANNOUNCEMENT_WINDOW_TAG,
    announcement_bridge_dates,
    announcement_day_run_id,
    announcement_refresh_dates,
    announcement_schedule_tags,
    announcement_window_dates,
    announcement_window_identity,
    announcement_window_tags,
    execute_announcement_window,
)
from orchestrator.defs.run_contracts.anns_d import AnnouncementPolicy
from tests.anns_d_test_support import archive as _archive_fixture
from tests.anns_d_test_support import source_row

archive = _archive_fixture
DAYS = ("2023-06-08", "2023-06-09", "2023-06-10")
AUTO_DAYS = (
    "2026-10-19", "2026-10-20", "2026-10-21",
    "2026-10-22", "2026-10-23", "2026-10-24",
    "2026-10-25", "2026-10-26", "2026-10-27",
)


def run_window(archive, days, tags, call, *, factory=None):
    def store_factory(day):
        return AnnouncementStore(
            archive.root, archive.staging,
            announcement_day_run_id(tags[ANNOUNCEMENT_WINDOW_TAG], day),
            archive.policy, archive.control,
        )

    return execute_announcement_window(
        days,
        tags=tags,
        policy=archive.policy,
        control=archive.control,
        store_factory=store_factory,
        call_factory=factory or (lambda day, store: call),
    )


def state_for(archive, window_id):
    path = archive.staging / "anns_d" / "windows" / window_id / "execution.json"
    return json.loads(path.read_text())


def test_fixed_nine_day_range_and_schedule_identity(monkeypatch):
    tick = datetime(2026, 10, 26, 8, tzinfo=ZoneInfo("Asia/Shanghai"))
    monkeypatch.setattr(time, "time", lambda: tick.timestamp())
    assert announcement_refresh_dates(tick) == AUTO_DAYS
    tags = announcement_schedule_tags(tick)
    # LLD §3.1 exact preimage: anns_d:update:2:2026-10-26:2026-10-19:2026-10-27.
    assert tags[ANNOUNCEMENT_WINDOW_TAG] == "a506243d8f1fc45e76062cdf37842760"
    assert tags[ANNOUNCEMENT_EXECUTION_VERSION_TAG] == "2"
    assert tags == announcement_schedule_tags(tick)
    identity = announcement_window_identity(AUTO_DAYS, tags, AnnouncementPolicy())
    assert identity["days"] == list(AUTO_DAYS)
    assert identity["started_at"] == tick.timestamp()
    assert identity["automatic"] is True
    assert "max_window_seconds" not in identity["policy"]


@pytest.mark.parametrize(
    "tick,expected",
    [
        ("2026-01-03", (
            "2025-12-27", "2025-12-28", "2025-12-29", "2025-12-30",
            "2025-12-31", "2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04",
        )),
        ("2026-03-03", (
            "2026-02-24", "2026-02-25", "2026-02-26", "2026-02-27",
            "2026-02-28", "2026-03-01", "2026-03-02", "2026-03-03", "2026-03-04",
        )),
    ],
)
def test_refresh_cross_month_year_has_literal_dates(tick, expected):
    assert announcement_refresh_dates(
        datetime.fromisoformat(tick).replace(tzinfo=ZoneInfo("Asia/Shanghai"))
    ) == expected


def test_bridge_no_gap_or_future():
    assert announcement_bridge_dates(
        datetime(2026, 10, 1, tzinfo=ZoneInfo("Asia/Shanghai"))
    ) == ()
    assert announcement_bridge_dates(
        datetime(2026, 10, 4, tzinfo=ZoneInfo("Asia/Shanghai"))
    ) == ("2026-10-01", "2026-10-02", "2026-10-03")


def test_window_captures_each_day_and_reuses_same_intent(archive):
    tags = announcement_window_tags("window", DAYS[0], DAYS[-1])
    calls = []

    def call(params, control):
        calls.append(params["ann_date"])
        return [], ANNOUNCEMENT_FIELDS

    deliveries = run_window(archive, DAYS, tags, call)
    assert list(deliveries) == list(DAYS)
    assert calls == ["20230608", "20230609", "20230610"]
    assert all(archive.target(day).exists() for day in DAYS)
    again = run_window(
        archive, DAYS, tags, call,
        factory=lambda *_: pytest.fail("completed delivery created source"),
    )
    assert list(again) == list(DAYS) and len(calls) == 3
    state = state_for(archive, "window")
    assert state["phase"] == "files_completed"
    assert state["files_completed"] == list(DAYS) and not state["failed_days"]
    budget = json.loads((
        archive.staging / "anns_d/windows/window/budget.json"
    ).read_text())
    assert budget["requests"] == 3 and "deadline" not in budget


def test_middle_day_failure_does_not_block_later_day_and_recovery_clears_failure(archive):
    tags = announcement_window_tags("partial", DAYS[0], DAYS[-1])
    calls, failing = [], [True]

    def call(params, control):
        calls.append(params["ann_date"])
        if params["ann_date"] == "20230609" and failing[0]:
            return [], ()  # Deliberately invalid source schema, not a legitimate empty day.
        return [], ANNOUNCEMENT_FIELDS

    with pytest.raises(AnnouncementError, match="announcement_window_failed"):
        run_window(archive, DAYS, tags, call)
    assert calls == ["20230608", "20230609", "20230610"]
    assert archive.target(DAYS[0]).exists() and archive.target(DAYS[2]).exists()
    assert not archive.target(DAYS[1]).exists()
    assert state_for(archive, "partial")["failed_days"] == [DAYS[1]]
    failing[0] = False
    run_window(archive, DAYS, tags, call)
    state = state_for(archive, "partial")
    assert calls == ["20230608", "20230609", "20230610", "20230609"]
    assert state["phase"] == "files_completed" and state["failed_days"] == []
    assert "reason" not in state["days"][DAYS[1]]


@pytest.mark.parametrize(
    "error",
    [AnnouncementError("announcement_volume_changed"), RuntimeError("unexpected")],
)
def test_shared_or_unknown_failure_stops_remaining_days(archive, error):
    tags = announcement_window_tags("stop", DAYS[0], DAYS[-1])
    calls = []

    def call(params, control):
        calls.append(params["ann_date"])
        if params["ann_date"] == "20230609":
            raise error
        return [], ANNOUNCEMENT_FIELDS

    with pytest.raises(type(error)):
        run_window(archive, DAYS, tags, call)
    assert calls == ["20230608", "20230609"]
    assert archive.target(DAYS[0]).exists() and not archive.target(DAYS[2]).exists()
    state = state_for(archive, "stop")
    assert state["failed_days"] == [DAYS[1]]
    assert state["unattempted_days"] == [DAYS[2]]


def test_late_start_and_elapsed_hours_do_not_expire_window(archive, monkeypatch):
    tick = datetime(2026, 10, 26, 8, tzinfo=ZoneInfo("Asia/Shanghai"))
    clock = [tick.timestamp()]
    monkeypatch.setattr(time, "time", lambda: clock[0])
    tags = announcement_schedule_tags(tick)
    clock[0] += 7 * 3600 + 35 * 60
    calls = []

    def call(params, control):
        calls.append(params["ann_date"])
        clock[0] += 3700  # Running for over an hour never consumes a total-time allowance.
        return [], ANNOUNCEMENT_FIELDS

    run_window(archive, AUTO_DAYS, tags, call)
    assert calls == [day.replace("-", "") for day in AUTO_DAYS]
    state = state_for(archive, tags[ANNOUNCEMENT_WINDOW_TAG])
    assert state["identity"]["days"] == list(AUTO_DAYS)
    assert state["identity"]["started_at"] == tick.timestamp()


def test_cancel_between_days_and_resume_after_midnight(archive, monkeypatch):
    tick = datetime(2026, 10, 26, 23, 55, tzinfo=ZoneInfo("Asia/Shanghai"))
    clock = [tick.timestamp()]
    monkeypatch.setattr(time, "time", lambda: clock[0])
    tags = announcement_schedule_tags(tick)
    calls = []

    def emit(event):
        if event.get("phase") == "file_promoted" and event.get("files_completed") == 2:
            archive.control.cancelled = lambda: True

    archive.control.emit = emit

    def call(params, control):
        calls.append(params["ann_date"])
        return [], ANNOUNCEMENT_FIELDS

    with pytest.raises(AnnouncementCancelled):
        run_window(archive, AUTO_DAYS, tags, call)
    clock[0] += 25 * 3600
    archive.control.cancelled = lambda: False
    archive.control.emit = lambda _: None
    run_window(archive, AUTO_DAYS, tags, call)
    assert calls == [day.replace("-", "") for day in AUTO_DAYS]
    state = state_for(archive, tags[ANNOUNCEMENT_WINDOW_TAG])
    assert state["identity"]["started_at"] == tick.timestamp()
    assert not state["failed_days"] and state["files_completed"] == list(AUTO_DAYS)


@pytest.mark.parametrize("tamper", ["unsafe", "version", "range", "automatic_id"])
def test_invalid_intent_is_rejected_before_store_or_source(archive, tamper):
    tick = datetime(2026, 10, 20, 8, tzinfo=ZoneInfo("Asia/Shanghai"))
    tags = announcement_schedule_tags(tick)
    days = announcement_refresh_dates(tick)
    if tamper == "unsafe":
        tags[ANNOUNCEMENT_WINDOW_TAG] = "../escape"
    elif tamper == "version":
        tags.pop(ANNOUNCEMENT_EXECUTION_VERSION_TAG)
    elif tamper == "range":
        tags["anns_d/end_date"] = "2026-10-28"
    else:
        tags[ANNOUNCEMENT_WINDOW_TAG] = "not-the-scheduled-window"
    before = list(archive.staging.rglob("*"))
    with pytest.raises(AnnouncementError):
        execute_announcement_window(
            days, tags=tags, policy=archive.policy, control=archive.control,
            store_factory=lambda *_: pytest.fail("invalid intent constructed store"),
            call_factory=lambda *_: pytest.fail("invalid intent constructed source"),
        )
    assert list(archive.staging.rglob("*")) == before


def test_automatic_timezone_and_future_boundary(monkeypatch):
    scheduled = datetime(2026, 10, 11, 16, tzinfo=timezone.utc)
    monkeypatch.setattr(time, "time", lambda: scheduled.timestamp())
    expected = (
        "2026-10-05", "2026-10-06", "2026-10-07",
        "2026-10-08", "2026-10-09", "2026-10-10",
        "2026-10-11", "2026-10-12", "2026-10-13",
    )
    assert announcement_refresh_dates(scheduled) == expected
    assert announcement_window_dates(
        expected[0], expected[-1], scheduled.timestamp(), automatic=True
    ) == expected
    with pytest.raises(AnnouncementError, match="automatic_window_range"):
        announcement_window_tags(
            "invalid", expected[0], "2026-10-14", scheduled.timestamp(), automatic=True
        )
    with pytest.raises(AnnouncementError, match="range_not_closed"):
        announcement_window_tags("manual", expected[0], expected[-1], scheduled.timestamp())
    with pytest.raises(AnnouncementError, match="timezone"):
        announcement_refresh_dates(scheduled.replace(tzinfo=None))


@pytest.mark.parametrize("timestamp", [float("nan"), float("inf"), True, "invalid"])
def test_invalid_planned_time_is_rejected(timestamp):
    with pytest.raises(AnnouncementError, match="window_start_time"):
        announcement_window_tags("bad-time", DAYS[0], DAYS[-1], timestamp)


def test_new_tick_refetches_overlap_and_preserves_versions(archive, monkeypatch):
    clock = [datetime(2026, 10, 12, 8, tzinfo=ZoneInfo("Asia/Shanghai")).timestamp()]
    monkeypatch.setattr(time, "time", lambda: clock[0])
    calls = []

    def execute(tick, extra):
        tags = announcement_schedule_tags(tick)
        days = announcement_refresh_dates(tick)

        def call(params, control):
            calls.append(params["ann_date"])
            rows = []
            if params["ann_date"] == "20261012":
                rows = [source_row(ann_date="20261012", title="original")]
                if extra:
                    rows += [source_row(ann_date="20261012", title="late"), rows[0]]
            if extra and params["ann_date"] == "20261013":
                rows = [source_row(ann_date="20261013", title="tomorrow later")]
            return rows, ANNOUNCEMENT_FIELDS

        run_window(archive, days, tags, call)

    execute(datetime.fromtimestamp(clock[0], ZoneInfo("Asia/Shanghai")), False)
    assert archive.audit_file(archive.target("2026-10-13"), "2026-10-13")["written_rows"] == 0
    clock[0] += 86400
    execute(datetime.fromtimestamp(clock[0], ZoneInfo("Asia/Shanghai")), True)
    assert len(calls) == 18
    assert archive.audit_file(archive.target("2026-10-12"), "2026-10-12")["written_rows"] == 2
    assert archive.audit_file(archive.target("2026-10-13"), "2026-10-13")["written_rows"] == 1


def test_cli_default_plan_zero_writes(tmp_path, monkeypatch, capsys):
    import orchestrator.defs.anns_d_cli as cli

    monkeypatch.setattr(cli, "DEFAULT_LAKE_STAGING_ROOT", str(tmp_path / "not-created"))
    monkeypatch.setattr(cli, "AnnouncementStore", lambda *a: pytest.fail("plan store"))
    monkeypatch.setattr(cli, "TushareResource", lambda *a, **k: pytest.fail("plan source"))
    assert announcement_cli([
        "--start-date", DAYS[0], "--end-date", DAYS[-1], "--interval-seconds", "0",
    ]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["days_total"] == 3 and result["event_write"] is False
    assert "max_window_seconds" not in result
    assert not (tmp_path / "not-created").exists()


@pytest.mark.parametrize(
    "extra",
    [["--interval-seconds", "nan"], ["--interval-seconds", "-1"], ["--window-id", "../escape"]],
)
def test_cli_rejects_invalid_config(tmp_path, monkeypatch, extra):
    import orchestrator.defs.anns_d_cli as cli

    monkeypatch.setattr(cli, "DEFAULT_LAKE_STAGING_ROOT", str(tmp_path / "not-created"))
    with pytest.raises((ValueError, AnnouncementError)):
        announcement_cli(["--start-date", DAYS[0], "--end-date", DAYS[-1], *extra])
    assert not (tmp_path / "not-created").exists()
