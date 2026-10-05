"""Real isolated Dagster events prove target binding, recovery and rejection."""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import dagster as dg
import pytest
from dagster._core.definitions.asset_checks.asset_check_evaluation import (
    AssetCheckEvaluation,
)

from orchestrator.defs.anns_d_checkpoint import (
    AnnouncementControl,
    announcement_file_fingerprint,
)
from orchestrator.defs.anns_d_contract import (
    ANNOUNCEMENT_CHECKS,
    AnnouncementCancelled,
    AnnouncementError,
)
from orchestrator.defs.bootstrap import anns_d_event_files as files
from orchestrator.defs.bootstrap import anns_d_events as execution
from orchestrator.defs.bootstrap.anns_d_event_state import (
    ASSET,
    EventReadBudget,
    freeze_announcement_events,
    matching_check,
    read_announcement_event_state,
)
from orchestrator.defs.bootstrap.anns_d_history_plan import seal_history_document
from tests.anns_d_test_support import archive as _archive_fixture
from tests.test_anns_d_history_execution import prepared, stage

archive = _archive_fixture


@pytest.fixture
def event_case(tmp_path, monkeypatch):
    entries = []
    for day in ("2023-06-01", "2023-06-02"):
        path = tmp_path / f"{day}.parquet"
        path.write_bytes(day.encode())
        cp = tmp_path / f"{day}.json"
        cp.write_text("{}")
        entries.append(
            {
                "day": day,
                "path": str(path),
                "file": announcement_file_fingerprint(path),
                "rows": 0 if day.endswith("01") else 2,
                "source_rows": 3,
                "checkpoint": str(cp),
                "checkpoint_file": announcement_file_fingerprint(cp),
                "identity": {"day": day, "policy": {}},
            }
        )
    monkeypatch.setattr(execution, "verify_announcement_event_evidence", lambda _: None)
    monkeypatch.setattr(execution, "DEFAULT_LAKE_STAGING_ROOT", str(tmp_path))
    monkeypatch.setattr(
        execution, "read_announcement_event_files", lambda *_args, **_kw: entries
    )
    with dg.DagsterInstance.ephemeral() as instance:
        control = AnnouncementControl()
        plan = seal_history_document(
            {
                **freeze_announcement_events(instance, entries, {}, control),
                "source": {"mode": "daily"},
            }
        )
        yield instance, plan, control, entries


def test_real_event_pipeline_partition_targets_and_replay(event_case):
    instance, plan, control, entries = event_case
    assert (
        execution.apply_announcement_events(
            instance, plan, "materializations", control
        )["written"]
        == 2
    )
    assert (
        execution.apply_announcement_events(instance, plan, "checks", control)[
            "written"
        ]
        == 4
    )
    assert (
        execution.apply_announcement_events(instance, plan, "audit", control)["written"]
        == 0
    )
    assert (
        execution.apply_announcement_events(instance, plan, "checks", control)[
            "written"
        ]
        == 0
    )
    state = read_announcement_event_state(instance, entries, EventReadBudget(), control)
    for e in entries:
        s = state[e["day"]]
        assert all(
            matching_check(s["checks"][n][1], n, s["mat"], e)
            for n in ANNOUNCEMENT_CHECKS
        )
    assert len(instance.fetch_materializations(ASSET, limit=20).records) == 2


def test_checks_before_materializations_rejected(event_case):
    instance, plan, control, _ = event_case
    with pytest.raises(AnnouncementError, match="materialization_missing"):
        execution.apply_announcement_events(instance, plan, "checks", control)


@pytest.mark.parametrize("failure", ["cancel", "exit", "checkpoint", "response"])
def test_partial_writes_resume_from_actual_events(event_case, monkeypatch, failure):
    instance, plan, control, _ = event_case
    original = instance.report_runless_asset_event
    called = 0

    def report(event):
        nonlocal called
        original(event)
        called += 1
        if called == 1:
            if failure == "cancel":
                control.cancelled = lambda: True
            elif failure == "exit":
                raise SystemExit("crash")
            elif failure == "response":
                raise RuntimeError("lost acknowledgement")

    monkeypatch.setattr(instance, "report_runless_asset_event", report)
    if failure == "checkpoint":
        monkeypatch.setattr(
            execution.AnnouncementCheckpoint, "save", Mock(side_effect=OSError("disk"))
        )
    with pytest.raises((AnnouncementCancelled, SystemExit, RuntimeError, OSError)):
        execution.apply_announcement_events(instance, plan, "materializations", control)
    monkeypatch.undo()
    # Reinstall only the fixture's harmless path/evidence substitutions.
    entries = [
        {
            k: v
            for k, v in e.items()
            if k
            not in (
                "missing_mat",
                "missing_checks",
                "previous_mat_id",
                "previous_check_ids",
            )
        }
        for e in plan["entries"]
    ]
    monkeypatch.setattr(
        execution, "DEFAULT_LAKE_STAGING_ROOT", str(Path(entries[0]["path"]).parent)
    )
    monkeypatch.setattr(
        execution, "read_announcement_event_files", lambda *_args, **_kw: entries
    )
    monkeypatch.setattr(execution, "verify_announcement_event_evidence", lambda _: None)
    control.cancelled = lambda: False
    assert (
        execution.apply_announcement_events(
            instance, plan, "materializations", control
        )["written"]
        == 1
    )
    assert len(instance.fetch_materializations(ASSET, limit=20).records) == 2


def test_external_materialization_competition_blocks(event_case):
    instance, plan, control, entries = event_case
    instance.report_runless_asset_event(
        dg.AssetMaterialization(ASSET, partition=entries[0]["day"])
    )
    with pytest.raises(AnnouncementError, match="materialization_changed"):
        execution.apply_announcement_events(instance, plan, "materializations", control)


def test_failed_check_is_not_overwritten(event_case):
    instance, plan, control, entries = event_case
    execution.apply_announcement_events(instance, plan, "materializations", control)
    instance.report_runless_asset_event(
        AssetCheckEvaluation(
            asset_key=ASSET,
            check_name=ANNOUNCEMENT_CHECKS[0],
            passed=False,
            partition=entries[0]["day"],
        )
    )
    with pytest.raises(AnnouncementError, match="check_changed"):
        execution.apply_announcement_events(instance, plan, "checks", control)
    with pytest.raises(AnnouncementError, match="existing_check_conflict"):
        freeze_announcement_events(instance, entries, {}, control)


@pytest.mark.parametrize("mutation", ["file", "evidence", "hash"])
def test_file_and_plan_identity_changes_block(event_case, mutation):
    instance, plan, control, entries = event_case
    if mutation == "file":
        Path(entries[0]["path"]).write_bytes(b"changed")
    elif mutation == "evidence":
        entries[0]["checkpoint_file"] = {"size": 1, "sha256": "changed"}
    else:
        plan["entries"][0]["rows"] += 1
    with pytest.raises(AnnouncementError):
        execution.apply_announcement_events(instance, plan, "materializations", control)
    assert not instance.fetch_materializations(ASSET, limit=20).records


def test_read_budget_and_stuck_cursor():
    instance = Mock()
    record = SimpleNamespace(
        asset_materialization=SimpleNamespace(partition="2023-06-01")
    )
    instance.fetch_materializations.return_value = SimpleNamespace(
        records=[record], cursor="stuck", has_more=True
    )
    entries = [{"day": "2023-06-01"}, {"day": "2023-06-02"}]
    with pytest.raises(AnnouncementError, match="read_budget"):
        read_announcement_event_state(
            instance, entries, EventReadBudget(0), AnnouncementControl()
        )
    with pytest.raises(AnnouncementError, match="cursor_not_advancing"):
        read_announcement_event_state(
            instance, entries, EventReadBudget(), AnnouncementControl()
        )


def test_readonly_evidence_adapter_full_month_and_corruption(archive, monkeypatch):
    plan, _ = prepared(archive)
    audit = stage(archive, "audit", plan)
    stage(archive, "promote", plan, audit=audit)
    formal = stage(archive, "audit", plan, formal=True)
    plan_path = archive.directory / "plan.json"
    audit_path = archive.directory / "audit.json"
    plan_path.write_text(json.dumps(plan))
    bundle = seal_history_document(
        {
            "kind": "anns_d_history_audit_bundle",
            "plan_fingerprint": plan["fingerprint"],
            "months": [formal],
        }
    )
    audit_path.write_text(json.dumps(bundle))
    spec = {
        "mode": "history",
        "history_plan": str(plan_path),
        "history_audit": str(audit_path),
    }
    real = files.validate_announcement_history_plan
    monkeypatch.setattr(
        files,
        "validate_announcement_history_plan",
        lambda p: real(p, roots=(archive.root, archive.staging)),
    )
    before = {
        str(p): announcement_file_fingerprint(p)
        for p in archive.staging.rglob("*")
        if p.is_file()
    }
    entries = files.read_announcement_event_files(spec, archive.control)
    assert len(entries) == 30 and sum(e["rows"] for e in entries) == 2
    assert before == {
        str(p): announcement_file_fingerprint(p)
        for p in archive.staging.rglob("*")
        if p.is_file()
    }
    assert not hasattr(files.AnnouncementEvidenceReader, "promote_day")
    monkeypatch.setattr(execution, "DEFAULT_LAKE_STAGING_ROOT", str(archive.staging))
    with dg.DagsterInstance.ephemeral() as instance:
        event_plan = seal_history_document(
            {
                **freeze_announcement_events(instance, entries, {}, archive.control),
                "source": spec,
            }
        )
        assert (
            execution.apply_announcement_events(
                instance, event_plan, "materializations", archive.control
            )["written"]
            == 30
        )
        assert (
            execution.apply_announcement_events(
                instance, event_plan, "checks", archive.control
            )["written"]
            == 60
        )
        assert (
            execution.apply_announcement_events(
                instance, event_plan, "audit", archive.control
            )["written"]
            == 0
        )
    Path(entries[0]["path"]).write_bytes(b"bad")
    with pytest.raises(AnnouncementError):
        files.read_announcement_event_files(spec, archive.control)


def test_wrong_partition_and_target_cannot_match(event_case):
    instance, plan, control, entries = event_case
    execution.apply_announcement_events(instance, plan, "materializations", control)
    execution.apply_announcement_events(instance, plan, "checks", control)
    state = read_announcement_event_state(instance, entries, EventReadBudget(), control)
    first, second = state[entries[0]["day"]], state[entries[1]["day"]]
    name = ANNOUNCEMENT_CHECKS[0]
    assert not matching_check(first["checks"][name][1], name, second["mat"], entries[0])
    assert not matching_check(first["checks"][name][1], name, first["mat"], entries[1])


def test_instance_changes_and_progress_monotonic(event_case):
    instance, plan, control, _ = event_case
    with pytest.raises(AnnouncementError, match="identity_changed"):
        execution.apply_announcement_events(
            instance,
            plan,
            "materializations",
            control,
            identity_probe=lambda: {"changed": 1},
        )
    progress = []
    control.emit = lambda e: progress.append(e)
    execution.apply_announcement_events(instance, plan, "materializations", control)
    values = [e["completed"] for e in progress if e.get("phase") == "materializations"]
    assert values == sorted(values) and values[-1] == 2


def test_daily_reader_and_evidence_source_changes(archive, monkeypatch):
    from orchestrator.defs.bootstrap.anns_d_history_execution import (
        announcement_history_day_checkpoint,
        announcement_history_store,
    )

    plan, _ = prepared(archive)
    stage(archive, "promote", plan, audit=stage(archive, "audit", plan))
    store = announcement_history_store(plan, plan["months"][0], archive.control)
    child = announcement_history_day_checkpoint(plan, "2023-06-09", store)
    manifest = archive.directory / "manifest.json"
    manifest.write_text(json.dumps([str(child.path)]))
    monkeypatch.setattr(files, "DEFAULT_LAKE_STAGING_ROOT", str(archive.staging))
    real = files.AnnouncementEvidenceReader
    monkeypatch.setattr(
        files,
        "AnnouncementEvidenceReader",
        lambda directory, policy, control: real(
            directory, policy, control, root=archive.root, staging=archive.staging
        ),
    )
    spec = {"mode": "daily", "delivery_manifest": str(manifest)}
    entries = files.read_announcement_event_files(spec, archive.control)
    assert len(entries) == 1 and entries[0]["rows"] == 2
    files.verify_announcement_event_evidence(entries)
    source = Path(child.document["delivery"]["source_pages"][0]["path"])
    source.write_bytes(b"changed")
    with pytest.raises(AnnouncementError, match="source_changed"):
        files.verify_announcement_event_evidence(entries)


def test_month_and_daily_limits(event_case):
    _, plan, _, _ = event_case
    plan["entries"] *= 4
    for i, entry in enumerate(plan["entries"]):
        plan["entries"][i] = {**entry, "day": f"2023-06-{i + 1:02d}"}
    plan = seal_history_document(plan)
    with pytest.raises(AnnouncementError, match="daily_budget"):
        execution.validate_announcement_event_plan(plan)
    with pytest.raises(AnnouncementError, match="month_budget"):
        read_announcement_event_state(
            Mock(),
            [{"day": f"2023-06-{i:02d}"} for i in range(32)],
            EventReadBudget(),
            AnnouncementControl(),
        )
