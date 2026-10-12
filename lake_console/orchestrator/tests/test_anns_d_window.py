"""Window dates, ordered admission, persisted deadlines and CLI negative gates."""

import json
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from orchestrator.defs.anns_d_cli import announcement_cli
from orchestrator.defs.anns_d_contract import ANNOUNCEMENT_FIELDS, AnnouncementError
from orchestrator.defs.anns_d_window import (
    announcement_bridge_dates,
    announcement_refresh_dates,
    announcement_window_tags,
    execute_announcement_window_day,
)
from tests.anns_d_test_support import archive as _archive_fixture

archive = _archive_fixture


@pytest.mark.parametrize(
    "tick,first,last",
    [
        ("2026-01-03", "2025-12-27", "2026-01-04"),
        ("2026-03-03", "2026-02-24", "2026-03-04"),
    ],
)
def test_refresh_seven_past_days_today_and_tomorrow(tick, first, last):
    days = announcement_refresh_dates(
        datetime.fromisoformat(tick).replace(tzinfo=ZoneInfo("Asia/Shanghai"))
    )
    assert len(days) == 9 and days[0] == first and days[-1] == last
    assert len(set(days)) == 9


def test_bridge_no_gap_or_future():
    assert (
        announcement_bridge_dates(
            datetime(2026, 10, 1, tzinfo=ZoneInfo("Asia/Shanghai"))
        )
        == ()
    )
    assert tuple(
        announcement_bridge_dates(
            datetime(2026, 10, 4, tzinfo=ZoneInfo("Asia/Shanghai"))
        )
    ) == ("2026-10-01", "2026-10-02", "2026-10-03")


def test_window_ordered_resume_and_frozen_policy(archive):
    store, control = archive, archive.control
    tags = announcement_window_tags("window", "2023-06-08", "2023-06-09")
    calls = []

    def call(params, control):
        calls.append(params)
        return [], ANNOUNCEMENT_FIELDS

    with pytest.raises(AnnouncementError, match="predecessor"):
        execute_announcement_window_day("2023-06-09", call, store, control, tags)
    assert not calls
    # Each date owns its own run-scoped evidence.
    from orchestrator.defs.anns_d_io import AnnouncementStore

    first_store = AnnouncementStore(
        store.root, store.staging, "first", store.policy, control
    )
    execute_announcement_window_day("2023-06-08", call, first_store, control, tags)
    execute_announcement_window_day("2023-06-09", call, store, control, tags)
    execute_announcement_window_day(
        "2023-06-09",
        lambda *a: pytest.fail("committed day re-fetched"),
        store,
        control,
        tags,
    )
    assert len(calls) == 2
    state = json.loads(
        (store.staging / "anns_d/windows/window/admission.json").read_text()
    )
    assert (
        state["completed"] == ["2023-06-08", "2023-06-09"]
        and state["phase"] == "completed"
    )
    tags["anns_d/end_date"] = "2023-06-10"
    with pytest.raises(AnnouncementError, match="contract_changed"):
        execute_announcement_window_day("2023-06-09", call, store, control, tags)


def test_expired_window_no_calls(archive):
    store, control = archive, archive.control
    tags = announcement_window_tags(
        "expired", "2023-06-09", "2023-06-09", time.time() - 4000
    )
    with pytest.raises(AnnouncementError, match="expired"):
        execute_announcement_window_day(
            "2023-06-09",
            lambda *a: pytest.fail("expired called source"),
            store,
            control,
            tags,
        )
    assert not store.target("2023-06-09").exists()


def test_cli_default_plan_zero_writes(tmp_path, monkeypatch, capsys):
    import orchestrator.defs.anns_d_cli as cli

    monkeypatch.setattr(
        cli, "AnnouncementStore", lambda *a: pytest.fail("plan opened store")
    )
    monkeypatch.setattr(
        cli, "TushareResource", lambda *a, **k: pytest.fail("plan opened source")
    )
    assert (
        announcement_cli(
            [
                "--start-date",
                "2023-06-09",
                "--end-date",
                "2023-06-10",
                "--interval-seconds",
                "0",
            ]
        )
        == 0
    )
    result = json.loads(capsys.readouterr().out)
    assert (
        result["days_total"] == 2
        and result["interval_seconds"] == 0
        and result["event_write"] is False
    )


@pytest.mark.parametrize(
    "extra",
    [
        ["--interval-seconds", "nan"],
        ["--interval-seconds", "-1"],
        ["--window-id", "../escape"],
    ],
)
def test_cli_rejects_invalid_config(extra):
    with pytest.raises((ValueError, AnnouncementError)):
        announcement_cli(
            ["--start-date", "2023-06-09", "--end-date", "2023-06-10", *extra]
        )


def test_window_failure_preserves_prior_commit(archive):
    from orchestrator.defs.anns_d_io import AnnouncementStore

    store, control = archive, archive.control
    tags = announcement_window_tags("failed", "2023-06-08", "2023-06-09")
    first_store = AnnouncementStore(
        store.root, store.staging, "first", store.policy, control
    )
    execute_announcement_window_day(
        "2023-06-08", lambda *a: ([], ANNOUNCEMENT_FIELDS), first_store, control, tags
    )

    def fail(*args):
        raise AnnouncementError("bad-source")

    with pytest.raises(AnnouncementError):
        execute_announcement_window_day("2023-06-09", fail, store, control, tags)
    assert (
        first_store.target("2023-06-08").exists()
        and not store.target("2023-06-09").exists()
    )


@pytest.mark.parametrize("window_id", ["/tmp/outside", "../outside"])
def test_untrusted_window_tags_cannot_escape_staging(archive, window_id):
    tags = announcement_window_tags("safe", "2023-06-09", "2023-06-09")
    tags["anns_d/window_id"] = window_id
    with pytest.raises(AnnouncementError, match="identity"):
        execute_announcement_window_day(
            "2023-06-09",
            lambda *a: pytest.fail("unsafe source call"),
            archive,
            archive.control,
            tags,
        )


@pytest.mark.parametrize(
    "started_at", [float("nan"), float("inf"), time.time() + 10000]
)
def test_untrusted_deadline_rejected(started_at):
    with pytest.raises(AnnouncementError, match="start_time"):
        announcement_window_tags("safe", "2023-06-09", "2023-06-09", started_at)


def test_window_cancelled_terminal_and_no_source(archive):
    from orchestrator.defs.anns_d_contract import AnnouncementCancelled

    archive.control.cancelled = lambda: True
    tags = announcement_window_tags("cancelled", "2023-06-09", "2023-06-09")
    with pytest.raises(AnnouncementCancelled):
        execute_announcement_window_day(
            "2023-06-09",
            lambda *a: pytest.fail("cancelled called source"),
            archive,
            archive.control,
            tags,
        )
    state = json.loads(
        (archive.staging / "anns_d/windows/cancelled/admission.json").read_text()
    )
    assert state["phase"] == "cancelled" and not state["completed"]


def test_automatic_window_timezone_and_future_boundary(monkeypatch):
    from datetime import timezone

    from orchestrator.defs.anns_d_window import announcement_window_dates

    scheduled = datetime(2026, 10, 11, 16, tzinfo=timezone.utc)
    monkeypatch.setattr(time, "time", lambda: scheduled.timestamp())
    days = announcement_refresh_dates(scheduled)
    assert days == (
        "2026-10-05",
        "2026-10-06",
        "2026-10-07",
        "2026-10-08",
        "2026-10-09",
        "2026-10-10",
        "2026-10-11",
        "2026-10-12",
        "2026-10-13",
    )
    tags = announcement_window_tags(
        "auto", days[0], days[-1], scheduled.timestamp(), automatic=True
    )
    assert tags["anns_d/automatic"] == "true"
    assert (
        announcement_window_dates(
            days[0], days[-1], scheduled.timestamp(), automatic=True
        )
        == days
    )
    for start, end in [(days[0], "2026-10-14"), (days[1], days[-1])]:
        with pytest.raises(AnnouncementError, match="automatic_window_range"):
            announcement_window_tags(
                "auto", start, end, scheduled.timestamp(), automatic=True
            )
    with pytest.raises(AnnouncementError, match="range_not_closed"):
        announcement_window_tags("manual", days[0], days[-1], scheduled.timestamp())
    with pytest.raises(AnnouncementError, match="timezone"):
        announcement_refresh_dates(scheduled.replace(tzinfo=None))


def test_new_tick_refetches_overlap_after_empty_tomorrow_and_keeps_versions(
    archive, monkeypatch
):
    from orchestrator.defs.anns_d_io import AnnouncementStore
    from orchestrator.defs.anns_d_window import announcement_day_run_id
    from tests.anns_d_test_support import source_row

    calls = []
    scheduled = datetime(2026, 10, 12, 8, tzinfo=ZoneInfo("Asia/Shanghai"))
    monkeypatch.setattr(time, "time", lambda: scheduled.timestamp())

    def run_window(window_id, tick, extra):
        dates = announcement_refresh_dates(tick)
        tags = announcement_window_tags(
            window_id, dates[0], dates[-1], tick.timestamp(), automatic=True
        )
        for day in dates:
            store = AnnouncementStore(
                archive.root,
                archive.staging,
                announcement_day_run_id(window_id, day),
                archive.policy,
                archive.control,
            )

            def call(params, control):
                calls.append((window_id, params["ann_date"]))
                rows = []
                if params["ann_date"] == "20261012":
                    rows = [source_row(ann_date="20261012", title="original")]
                    if extra:
                        rows += [source_row(ann_date="20261012", title="late"), rows[0]]
                if extra and params["ann_date"] == "20261013":
                    rows = [
                        source_row(
                            ann_date="20261013", title="tomorrow published later"
                        )
                    ]
                return rows, ANNOUNCEMENT_FIELDS

            execute_announcement_window_day(day, call, store, archive.control, tags)
        return dates

    run_window("first", scheduled, False)
    assert (
        archive.audit_file(archive.target("2026-10-13"), "2026-10-13")["written_rows"]
        == 0
    )
    run_window("first", scheduled, False)
    assert len(calls) == 9  # Same frozen execution reuses complete capture/delivery.
    scheduled = datetime(2026, 10, 13, 8, tzinfo=ZoneInfo("Asia/Shanghai"))
    run_window("second", scheduled, True)
    assert len(calls) == 18
    assert ("second", "20261012") in calls and ("second", "20261013") in calls
    assert (
        archive.audit_file(archive.target("2026-10-12"), "2026-10-12")["written_rows"]
        == 2
    )
    assert (
        archive.audit_file(archive.target("2026-10-13"), "2026-10-13")["written_rows"]
        == 1
    )
    # A further observation with exact duplicates does not grow the business set.
    scheduled = datetime(2026, 10, 14, 8, tzinfo=ZoneInfo("Asia/Shanghai"))
    run_window("third", scheduled, True)
    assert len(calls) == 27
    assert (
        archive.audit_file(archive.target("2026-10-12"), "2026-10-12")["written_rows"]
        == 2
    )


def test_automatic_cancel_resume_across_midnight_keeps_window_and_budget(
    archive, monkeypatch
):
    from orchestrator.defs.anns_d_contract import AnnouncementCancelled
    from orchestrator.defs.anns_d_io import AnnouncementStore
    from orchestrator.defs.anns_d_window import announcement_day_run_id

    tick = datetime(2026, 10, 12, 23, 55, tzinfo=ZoneInfo("Asia/Shanghai"))
    clock = [tick.timestamp()]
    monkeypatch.setattr(time, "time", lambda: clock[0])
    days = announcement_refresh_dates(tick)
    tags = announcement_window_tags(
        "midnight", days[0], days[-1], clock[0], automatic=True
    )
    calls = []

    def execute(day):
        store = AnnouncementStore(
            archive.root,
            archive.staging,
            announcement_day_run_id("midnight", day),
            archive.policy,
            archive.control,
        )

        def call(params, control):
            calls.append(params["ann_date"])
            return [], ANNOUNCEMENT_FIELDS

        return execute_announcement_window_day(day, call, store, archive.control, tags)

    execute(days[0])
    budget_path = archive.staging / "anns_d/windows/midnight/budget.json"
    before = json.loads(budget_path.read_text())
    archive.control.cancelled = lambda: True
    with pytest.raises(AnnouncementCancelled):
        execute(days[1])
    archive.control.cancelled = lambda: False
    clock[0] += 600  # 00:05, within the original one-hour deadline.
    for day in days:
        execute(day)
    after = json.loads(budget_path.read_text())
    assert calls == [day.replace("-", "") for day in days]
    assert after["deadline"] == before["deadline"]
    state = json.loads(
        (archive.staging / "anns_d/windows/midnight/admission.json").read_text()
    )
    assert state["phase"] == "completed" and state["completed"] == list(days)
    assert state["identity"]["days"] == list(days)
