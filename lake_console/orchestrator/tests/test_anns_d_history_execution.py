"""Independent phases and real temporary files prove set equality and recovery."""

from pathlib import Path

import pytest

from orchestrator.defs.anns_d_checkpoint import announcement_file_fingerprint
from orchestrator.defs.anns_d_contract import AnnouncementCancelled, AnnouncementError
from orchestrator.defs.anns_d_io import AnnouncementStore
from orchestrator.defs.bootstrap.anns_d_history_execution import (
    AnnouncementHistoryControl,
    announcement_history_day_checkpoint,
    announcement_history_store,
    announcement_month_checkpoint,
    run_announcement_history_stage,
)
from tests.anns_d_test_support import archive as _archive_fixture
from tests.anns_d_test_support import source_row
from tests.test_anns_d_history_plan import month_plan

archive = _archive_fixture


class FrozenSource:
    def __init__(self, rows=None, expected=None):
        self.rows = (
            rows
            if rows is not None
            else [
                source_row(),
                source_row(),
                source_row(url="https://example.test/a.pdf"),
            ]
        )
        self.expected = len(self.rows) if expected is None else expected
        self.calls = 0

    def batches(self, month, upper, control, on_plan):
        self.calls += 1
        on_plan(
            {
                "expected_rows": self.expected,
                "month_start": month,
                "upper_id": str(upper),
            }
        )
        yield self.rows


def stage(archive, name, plan, **kwargs):
    return run_announcement_history_stage(
        name, plan, plan["months"][0], archive.control, **kwargs
    )


def prepared(archive):
    plan = month_plan(archive)
    source = FrozenSource()
    stage(archive, "capture", plan, source=source)
    stage(archive, "build", plan)
    return plan, source


def test_stage_pipeline_distinct_null_versions_empty_days_and_formal_audit(archive):
    plan, source = prepared(archive)
    assert not list(archive.root.rglob("*.parquet"))
    audit = stage(archive, "audit", plan)
    assert (
        audit["source_rows"] == 3 and audit["written_rows"] == 2 and audit["days"] == 30
    )
    assert audit["missing_url"] == 1 and audit["missing_rec_time"] == 2
    stage(archive, "promote", plan, audit=audit)
    assert len(list(archive.root.rglob("*.parquet"))) == 30
    hashes = {
        str(p): announcement_file_fingerprint(p)
        for p in archive.root.rglob("*.parquet")
    }
    stage(archive, "promote", plan, audit=audit)
    assert {
        str(p): announcement_file_fingerprint(p)
        for p in archive.root.rglob("*.parquet")
    } == hashes
    formal = stage(archive, "audit", plan, formal=True)
    assert formal["formal"] and formal["set_difference_rows"] == 0 and source.calls == 1


def test_source_plan_count_changed_blocks_capture(archive):
    plan = month_plan(archive)
    with pytest.raises(AnnouncementError, match="plan_source_changed"):
        stage(archive, "capture", plan, source=FrozenSource(expected=4))
    assert not list(archive.root.rglob("*.parquet"))


def test_no_audit_and_changed_target_never_promote(archive):
    plan, _source = prepared(archive)
    with pytest.raises(AnnouncementError, match="green_audit"):
        stage(archive, "promote", plan)
    path = archive.target("2023-06-09")
    path.parent.mkdir(parents=True)
    path.write_bytes(b"foreign-file")
    with pytest.raises(AnnouncementError, match="target_conflict"):
        stage(archive, "audit", plan)
    assert path.exists()


def test_build_cancel_keeps_candidates_and_resumes_remaining_only(archive, monkeypatch):
    plan = month_plan(archive)
    stage(archive, "capture", plan, source=FrozenSource())
    archive.control.cancelled = lambda: (
        archive.control.view.get("days_completed", 0) >= 2
    )
    with pytest.raises(AnnouncementCancelled):
        stage(archive, "build", plan)
    archive.control.cancelled = lambda: False
    store = announcement_history_store(plan, plan["months"][0], archive.control)
    checkpoint = announcement_month_checkpoint(plan, plan["months"][0], store)
    assert (
        len(checkpoint.document["deliveries"]) == 2
        and checkpoint.document["phase"] == "cancelled"
    )
    real = AnnouncementStore.build_day
    rebuilt = []

    def build(self, day, *args, **kwargs):
        rebuilt.append(day)
        return real(self, day, *args, **kwargs)

    monkeypatch.setattr(AnnouncementStore, "build_day", build)
    stage(archive, "build", plan)
    assert len(rebuilt) == 28 and "2023-06-01" not in rebuilt


def test_promote_cancel_retains_two_commits_and_resumes(archive, monkeypatch):
    plan, source = prepared(archive)
    audit = stage(archive, "audit", plan)
    real = AnnouncementStore.promote_day
    committed = []

    def promote(self, day, *args, **kwargs):
        real(self, day, *args, **kwargs)
        committed.append(day)

    monkeypatch.setattr(AnnouncementStore, "promote_day", promote)
    archive.control.cancelled = lambda: len(committed) >= 2
    with pytest.raises(AnnouncementCancelled):
        stage(archive, "promote", plan, audit=audit)
    hashes = {
        str(p): announcement_file_fingerprint(p)
        for p in archive.root.rglob("*.parquet")
    }
    assert len(hashes) == 2
    archive.control.cancelled = lambda: False
    stage(archive, "promote", plan, audit=audit)
    assert all(announcement_file_fingerprint(p) == value for p, value in hashes.items())
    assert (
        stage(archive, "audit", plan, formal=True)["written_rows"] == 2
        and source.calls == 1
    )


def test_same_count_corruption_is_rejected_by_set_audit(archive):
    plan, _source = prepared(archive)
    store = announcement_history_store(plan, plan["months"][0], archive.control)
    checkpoint = announcement_month_checkpoint(plan, plan["months"][0], store)
    delivery = checkpoint.document["deliveries"]["2023-06-09"]
    candidate = Path(delivery["candidate"])
    changed = store.directory / "different.parquet"
    store.write_page(
        [
            source_row(title="wrong"),
            source_row(title="wrong", url="https://example.test/a.pdf"),
        ],
        changed,
        archive.control,
    )
    candidate.write_bytes(changed.read_bytes())
    delivery["fingerprint"] = announcement_file_fingerprint(candidate)
    checkpoint.save(deliveries=checkpoint.document["deliveries"])
    with pytest.raises(AnnouncementError, match="set_reconciliation"):
        stage(archive, "audit", plan)


def test_month_deadline_visible_to_queries_and_checks(archive, monkeypatch):
    import orchestrator.defs.bootstrap.anns_d_history_execution as module

    monkeypatch.setattr(module.time, "monotonic", lambda: 100)
    bounded = AnnouncementHistoryControl(archive.control, 10)
    assert not bounded.cancelled()
    monkeypatch.setattr(module.time, "monotonic", lambda: 110)
    assert bounded.cancelled()
    with pytest.raises(AnnouncementError, match="month_timeout"):
        bounded.check()


def test_month_set_equality_cannot_hide_wrong_partition(archive):
    plan, _source = prepared(archive)
    store = announcement_history_store(plan, plan["months"][0], archive.control)
    checkpoint = announcement_month_checkpoint(plan, plan["months"][0], store)
    deliveries = checkpoint.document["deliveries"]
    nonempty, empty = deliveries["2023-06-09"], deliveries["2023-06-10"]
    left, right = Path(nonempty["candidate"]), Path(empty["candidate"])
    saved = left.read_bytes()
    left.write_bytes(right.read_bytes())
    right.write_bytes(saved)
    nonempty["fingerprint"] = announcement_file_fingerprint(left)
    empty["fingerprint"] = announcement_file_fingerprint(right)
    checkpoint.save(deliveries=deliveries)
    with pytest.raises(AnnouncementError, match="set_reconciliation"):
        stage(archive, "audit", plan)


def test_bootstrap_day_evidence_is_consumable_by_registered_daily_check(
    archive, monkeypatch
):
    from types import SimpleNamespace

    import dagster as dg

    import orchestrator.defs.checks.anns_d_checks as checks
    from orchestrator.defs.resources import LakeRootResource

    plan, _source = prepared(archive)
    audit = stage(archive, "audit", plan)
    stage(archive, "promote", plan, audit=audit)
    store = announcement_history_store(plan, plan["months"][0], archive.control)
    checkpoint = announcement_history_day_checkpoint(plan, "2023-06-09", store)
    record = SimpleNamespace(
        storage_id=1,
        asset_materialization=SimpleNamespace(
            metadata={
                "goldenshare/announcement_identity": dg.MetadataValue.json(
                    checkpoint.identity
                ),
                "goldenshare/announcement_checkpoint": dg.MetadataValue.path(
                    str(checkpoint.path)
                ),
            }
        ),
    )
    monkeypatch.setattr(checks, "DEFAULT_LAKE_ROOT", str(archive.root))
    monkeypatch.setattr(checks, "announcement_materialization", lambda *args: record)
    context = SimpleNamespace(
        partition_key="2023-06-09",
        instance=None,
        run=SimpleNamespace(
            run_id="check-only", asset_selection=set(), step_keys_to_execute=None
        ),
    )
    result = checks.evaluate_announcement_check(
        context,
        LakeRootResource(root_path=str(archive.root)),
        reconciliation=True,
        staging_root=archive.staging,
    )
    assert result.passed
