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
        ("2026-01-03", "2025-12-27", "2026-01-02"),
        ("2026-03-03", "2026-02-24", "2026-03-02"),
    ],
)
def test_refresh_closed_natural_days(tick, first, last):
    days = announcement_refresh_dates(
        datetime.fromisoformat(tick).replace(tzinfo=ZoneInfo("Asia/Shanghai"))
    )
    assert len(days) == 7 and days[0] == first and days[-1] == last
    assert len(set(days)) == 7


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
