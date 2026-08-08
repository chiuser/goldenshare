from __future__ import annotations

from pathlib import Path

import pytest

from orchestrator.defs.bootstrap import (
    index_daily_000680_history_supplement_events as events,
)
from orchestrator.defs.bootstrap.index_daily_000680_history_supplement_plan import (
    TARGET_CODE,
)
from tests._index_daily_000680_history_supplement_helpers import (
    FakeDagsterInstance,
    frozen_plan_payload,
    write_green_physical_audit,
    write_plan,
)


def _files(tmp_path: Path) -> tuple[Path, Path, dict[str, object]]:
    payload = frozen_plan_payload(
        dates=("2020-01-02", "2020-01-03"),
        gold_dates=("2020-01-02", "2020-01-03", "2020-01-06"),
    )
    plan_path = tmp_path / "plan.json"
    audit_path = tmp_path / "audit.json"
    write_plan(plan_path, payload)
    write_green_physical_audit(audit_path, plan_hash=str(payload["plan_hash"]))
    return plan_path, audit_path, payload


def test_event_plan_is_read_only_and_only_lists_missing_events(tmp_path: Path) -> None:
    plan_path, audit_path, payload = _files(tmp_path)
    instance = FakeDagsterInstance(
        dates=("2020-01-02",),
        codes=(TARGET_CODE,),
        materialized={"raw_index_daily": {"2020-01-02"}},
    )

    result = events.plan_supplement_events(
        instance=instance,
        plan_path=plan_path,
        physical_audit_path=audit_path,
        expected_plan_hash=str(payload["plan_hash"]),
    )

    assert result.missing_date_partitions == ("2020-01-03", "2020-01-06")
    assert result.raw_materializations == ("2020-01-03",)
    assert result.silver_materializations == ("2020-01-02", "2020-01-03")
    assert result.gold_materializations == (
        "2020-01-02",
        "2020-01-03",
        "2020-01-06",
    )
    assert instance.partition_writes == []
    assert instance.events == []


def test_event_apply_requires_explicit_apply(tmp_path: Path) -> None:
    plan_path, audit_path, payload = _files(tmp_path)
    instance = FakeDagsterInstance()

    with pytest.raises(
        events.IndexDaily000680HistorySupplementEventsError,
        match="apply=True",
    ):
        events.report_supplement_events(
            instance=instance,
            plan_path=plan_path,
            physical_audit_path=audit_path,
            expected_plan_hash=str(payload["plan_hash"]),
            apply=False,
            confirm_partition_write=False,
            confirm_event_write=False,
        )
    assert instance.partition_writes == []
    assert instance.events == []


def test_missing_event_confirmation_causes_no_partial_partition_write(
    tmp_path: Path,
) -> None:
    plan_path, audit_path, payload = _files(tmp_path)
    instance = FakeDagsterInstance()

    with pytest.raises(
        events.IndexDaily000680HistorySupplementEventsError,
        match="confirm-event-write",
    ):
        events.report_supplement_events(
            instance=instance,
            plan_path=plan_path,
            physical_audit_path=audit_path,
            expected_plan_hash=str(payload["plan_hash"]),
            apply=True,
            confirm_partition_write=True,
            confirm_event_write=False,
        )
    assert instance.partition_writes == []
    assert instance.events == []


def test_event_apply_writes_only_the_planned_partitions_and_materializations(
    tmp_path: Path,
) -> None:
    plan_path, audit_path, payload = _files(tmp_path)
    instance = FakeDagsterInstance()

    report = events.report_supplement_events(
        instance=instance,
        plan_path=plan_path,
        physical_audit_path=audit_path,
        expected_plan_hash=str(payload["plan_hash"]),
        apply=True,
        confirm_partition_write=True,
        confirm_event_write=True,
    )

    assert report.registered_date_partition_count == 3
    assert report.registered_code_partition_count == 1
    assert report.reported_raw_materialization_count == 2
    assert report.reported_silver_materialization_count == 2
    assert report.reported_gold_materialization_count == 3
    assert report.reported_materialization_count == 7
    assert len(instance.events) == 7
