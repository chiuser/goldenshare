"""Real temporary delivery evidence guards check-only recovery.

File fixtures use the actual single-day source/capture/merge/promote producer.
The six literal source fields below come from the anns_d contract and its known
nullable URL/rec_time sample.  Only Dagster run/record lookup is replaced in the
target-selection cases; the real job definition and all frozen-intent checks run.
No formal instance, source endpoint, or Lake path is opened.
"""

import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import dagster as dg
import pytest

from orchestrator.defs.anns_d_checkpoint import AnnouncementControl
from orchestrator.defs.anns_d_contract import (
    ANNOUNCEMENT_ASSET,
    ANNOUNCEMENT_CHECKS,
    AnnouncementError,
)
from orchestrator.defs.anns_d_io import AnnouncementStore
from orchestrator.defs.anns_d_partitions import anns_d_natural_days
from orchestrator.defs.anns_d_window import (
    ANNOUNCEMENT_WINDOW_TAG,
    announcement_day_run_id,
    announcement_manual_window_tags,
    execute_announcement_window,
)
from orchestrator.defs.checks import anns_d_check_targets as targets
from orchestrator.defs.checks import anns_d_checks as checks
from orchestrator.defs.paths import raw_anns_d_path
from orchestrator.defs.resources import LakeRootResource
from orchestrator.defs.run_contracts.anns_d import AnnouncementPolicy

DAY = "2023-06-09"
ROOT_RUN_ID = "manual-source-run"
ASSET_KEY = dg.AssetKey(ANNOUNCEMENT_ASSET)
SOURCE_FIELDS = ("ann_date", "ts_code", "name", "title", "url", "rec_time")
SOURCE_ROW = {
    "ann_date": "20230609",
    "ts_code": "155162.SH",
    "name": "19津投04",
    "title": "同标题",
    "url": None,
    "rec_time": None,
}
_MISSING = object()


@pytest.fixture
def delivery_case(tmp_path, request):
    row_count = getattr(request, "param", 1)
    root, staging = tmp_path / "lake", tmp_path / "staging"
    root.mkdir()
    staging.mkdir()
    policy = AnnouncementPolicy(interval_seconds=0)
    control = AnnouncementControl()
    control.progress(active_run_id=ROOT_RUN_ID)
    tags = announcement_manual_window_tags(
        ROOT_RUN_ID, DAY, DAY, staging=staging, policy=policy
    )
    calls = []

    def store_factory(day):
        return AnnouncementStore(
            root,
            staging,
            announcement_day_run_id(tags[ANNOUNCEMENT_WINDOW_TAG], day),
            policy,
            control,
        )

    def call(params, current_control):
        calls.append(params)
        first = params["offset"]
        size = min(2000, max(0, row_count - first))
        return [
            {**SOURCE_ROW, "title": f"公告-{index}"}
            for index in range(first, first + size)
        ], SOURCE_FIELDS

    result = execute_announcement_window(
        (DAY,),
        tags=tags,
        policy=policy,
        control=control,
        store_factory=store_factory,
        call_factory=lambda day, store: call,
    )[DAY]
    expected_offsets = [0] if row_count < 2000 else [0, 2000]
    assert calls == [
        {"ann_date": "20230609", "limit": 2000, "offset": offset}
        for offset in expected_offsets
    ]
    document = json.loads(result.checkpoint_path.read_text())
    delivery = document["delivery"]
    # Literal source pagination contract: a full 2000-row page requires a second
    # request, even when it is the empty EOF page.  The verifier supplies none of
    # these expected values.
    expected_pages = 1 if row_count < 2000 else 2
    expected_last_offset = 0 if row_count < 2000 else 2000
    expected_last_rows = row_count if row_count < 2000 else row_count - 2000
    assert document["phase"] == "promoted"
    assert delivery["capture_complete"] is True
    assert delivery["page_count"] == expected_pages
    assert delivery["source_rows"] == row_count
    assert delivery["last_offset"] == expected_last_offset
    assert delivery["last_page_rows"] == expected_last_rows
    assert len(delivery["source_pages"]) == expected_pages
    for index, page in enumerate(delivery["source_pages"]):
        assert page["offset"] == expected_offsets[index]
        expected_rows = expected_last_rows if index == expected_pages - 1 else 2000
        assert page["rows"] == expected_rows
        page_path = Path(page["path"])
        assert page["fingerprint"] == {
            "size": page_path.stat().st_size,
            "sha256": hashlib.sha256(page_path.read_bytes()).hexdigest(),
        }
    target = raw_anns_d_path(root, DAY)
    assert delivery["fingerprint"] == {
        "size": target.stat().st_size,
        "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
    }
    materialization = dg.AssetMaterialization(
        asset_key=ASSET_KEY,
        partition=DAY,
        metadata={
            # Actual native P2/current asset metadata includes the delivery SHA.
            "goldenshare/fingerprint": dg.MetadataValue.json(delivery["fingerprint"]),
            "goldenshare/announcement_identity": dg.MetadataValue.json(
                dict(result.identity)
            ),
            "goldenshare/announcement_checkpoint": dg.MetadataValue.path(
                str(result.checkpoint_path)
            ),
        },
    )
    record = SimpleNamespace(
        asset_materialization=materialization,
        event_log_entry=SimpleNamespace(run_id=ROOT_RUN_ID),
        storage_id=11,
        timestamp=1234.0,
    )
    return SimpleNamespace(
        root=root,
        staging=staging,
        tags=tags,
        control=control,
        record=record,
        checkpoint_path=result.checkpoint_path,
        execution_path=staging
        / "anns_d"
        / "windows"
        / tags[ANNOUNCEMENT_WINDOW_TAG]
        / "execution.json",
    )


@pytest.mark.parametrize("delivery_case", [0, 1, 2000, 2001], indirect=True)
def test_reused_delivery_accepts_real_short_and_full_pages_without_audit_sql(
    delivery_case, monkeypatch
):
    case = delivery_case
    monkeypatch.setattr(
        AnnouncementStore,
        "audit_file",
        lambda *args, **kwargs: pytest.fail("reference reuse must not rerun file SQL"),
    )
    before = case.checkpoint_path.read_bytes()
    checks._verify_reused_delivery_references(
        case.record, case.root, case.staging, DAY, case.control
    )
    assert case.checkpoint_path.read_bytes() == before


@pytest.mark.parametrize(
    "field,value",
    [
        ("capture_complete", _MISSING),
        ("capture_complete", False),
        ("capture_complete", 1),
        ("source_pages", _MISSING),
        ("source_pages", []),
        ("source_pages", {}),
        ("source_pages", [None]),
        ("page_count", _MISSING),
        ("page_count", 0),
        ("page_count", True),
        ("page_count", 2),
        ("source_rows", _MISSING),
        ("source_rows", True),
        ("source_rows", 0),
        ("source_rows", 2),
        ("last_offset", _MISSING),
        ("last_offset", True),
        ("last_offset", 1),
        ("last_page_rows", _MISSING),
        ("last_page_rows", True),
        ("last_page_rows", 2),
        ("last_page_rows", 2000),
    ],
)
def test_incomplete_or_inconsistent_capture_metadata_rejects_reuse(
    delivery_case, field, value
):
    case = delivery_case
    document = json.loads(case.checkpoint_path.read_text())
    if value is _MISSING:
        document["delivery"].pop(field)
    else:
        document["delivery"][field] = copy.deepcopy(value)
    case.checkpoint_path.write_text(json.dumps(document))
    with pytest.raises(AnnouncementError):
        checks._verify_reused_delivery_references(
            case.record, case.root, case.staging, DAY, case.control
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("offset", _MISSING),
        ("offset", True),
        ("offset", 1),
        ("rows", _MISSING),
        ("rows", True),
        ("rows", 0),
        ("rows", 2000),
        ("path", _MISSING),
        ("path", ""),
        ("path", None),
        ("fingerprint", _MISSING),
        ("fingerprint", {}),
        ("fingerprint", "not-a-fingerprint"),
        ("fingerprint", {"size": 1, "sha256": "0" * 64}),
    ],
)
def test_missing_or_wrong_page_references_reject_reuse(delivery_case, field, value):
    case = delivery_case
    document = json.loads(case.checkpoint_path.read_text())
    page = document["delivery"]["source_pages"][0]
    if value is _MISSING:
        page.pop(field)
    else:
        page[field] = copy.deepcopy(value)
    case.checkpoint_path.write_text(json.dumps(document))
    with pytest.raises(AnnouncementError):
        checks._verify_reused_delivery_references(
            case.record, case.root, case.staging, DAY, case.control
        )


def _reexecution_context(case):
    # Real Dagster selection/step mapping; only persisted run and asset-record
    # lookup is a bounded stand-in.  No job is executed or source initialized.
    @dg.asset(name=ANNOUNCEMENT_ASSET, partitions_def=anns_d_natural_days)
    def producer():
        pytest.fail("metadata target selection must never execute the asset")

    defs = dg.Definitions(
        assets=[producer],
        asset_checks=[
            checks.raw_tushare_anns_d_file_contract_check,
            checks.raw_tushare_anns_d_delivery_reconciliation_check,
        ],
        jobs=[dg.define_asset_job("reused_delivery_target_fixture")],
        resources={"lake_root": LakeRootResource(root_path=str(case.root))},
    )
    job = defs.resolve_job_def("reused_delivery_target_fixture")
    check_keys = {dg.AssetCheckKey(ASSET_KEY, name) for name in ANNOUNCEMENT_CHECKS}
    check_steps = [
        str(job.asset_layer.get_op_output_handle(key).node_handle) for key in check_keys
    ]
    root_run = SimpleNamespace(
        run_id=ROOT_RUN_ID,
        root_run_id=None,
        tags={},
        asset_selection={ASSET_KEY},
        step_keys_to_execute=None,
        resolved_op_selection=None,
    )
    run = SimpleNamespace(
        run_id="manual-check-retry",
        root_run_id=ROOT_RUN_ID,
        tags={},
        asset_selection={ASSET_KEY},
        asset_check_selection=check_keys,
        step_keys_to_execute=check_steps,
    )
    calls = []

    def get_run(run_id):
        calls.append(("root", run_id))
        assert run_id == ROOT_RUN_ID
        return root_run

    def fetch_materializations(asset_filter, *, limit):
        calls.append(("materialization", asset_filter.asset_partitions, limit))
        assert asset_filter.asset_key == ASSET_KEY
        assert asset_filter.asset_partitions == [DAY] and limit == 1
        return SimpleNamespace(records=[case.record])

    instance = SimpleNamespace(
        get_run_by_id=get_run,
        fetch_materializations=fetch_materializations,
    )
    return SimpleNamespace(run=run, job_def=job, instance=instance), calls


def test_manual_file_reexecution_without_automatic_tags_finds_frozen_window(
    delivery_case,
):
    case = delivery_case
    context, calls = _reexecution_context(case)
    selected = targets.prepare_announcement_check_targets(context, (DAY,), case.staging)
    assert selected.materializing is False
    assert selected.window_identity["window_id"] == case.tags[ANNOUNCEMENT_WINDOW_TAG]
    assert selected.window_identity["days"] == [DAY]
    assert selected.window_identity["automatic"] is False
    assert selected.records[DAY] is case.record
    assert calls == [("root", ROOT_RUN_ID), ("materialization", [DAY], 1)]


def test_expected_manual_execution_missing_cannot_downgrade_to_independent_check(
    delivery_case,
):
    case = delivery_case
    context, calls = _reexecution_context(case)
    case.execution_path.unlink()
    with pytest.raises(AnnouncementError, match="check_execution_missing"):
        targets.prepare_announcement_check_targets(context, (DAY,), case.staging)
    assert calls == [("root", ROOT_RUN_ID)]


def test_latest_materialization_from_other_window_cannot_satisfy_manual_recovery(
    delivery_case,
):
    case = delivery_case
    context, _calls = _reexecution_context(case)
    foreign_identity = dict(
        case.record.asset_materialization.metadata[
            "goldenshare/announcement_identity"
        ].value
    )
    foreign_identity["window_id"] = "another-execution"
    metadata = dict(case.record.asset_materialization.metadata)
    metadata["goldenshare/announcement_identity"] = dg.MetadataValue.json(
        foreign_identity
    )
    case.record.asset_materialization = dg.AssetMaterialization(
        asset_key=ASSET_KEY, partition=DAY, metadata=metadata
    )
    with pytest.raises(AnnouncementError, match="recovery_materialization_conflict"):
        targets.prepare_announcement_check_targets(context, (DAY,), case.staging)
