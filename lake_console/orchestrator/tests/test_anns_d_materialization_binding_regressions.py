"""Original materializations bind temporary file evidence, even after CP damage.

The native asset creates the first immutable materialization. Source calls are
substituted; the asset, capture, merge, promotion and temporary instance are real.
"""

import hashlib
import json
from copy import deepcopy
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
from orchestrator.defs.anns_d_window import (
    announcement_day_run_id,
    announcement_window_tags,
    execute_announcement_window,
)
from orchestrator.defs.checks import anns_d_check_targets as targets
from orchestrator.defs.checks import anns_d_checks as checks
from orchestrator.defs.resources import LakeRootResource, TushareResource
from orchestrator.defs.run_contracts.anns_d import AnnouncementPolicy

DAY = "2023-06-09"
FIELDS = ("ann_date", "ts_code", "name", "title", "url", "rec_time")
ROW = {
    "ann_date": "20230609", "ts_code": "155162.SH", "name": "19津投04",
    "title": "original announcement", "url": None, "rec_time": None,
}
ASSET_KEY = dg.AssetKey(ANNOUNCEMENT_ASSET)
_ORIGINAL_RECORD = object()


@pytest.fixture
def original_materialization(tmp_path, monkeypatch):
    import orchestrator.defs.assets.anns_d as asset_module

    root, staging = tmp_path / "lake", tmp_path / "staging"
    root.mkdir()
    staging.mkdir()
    monkeypatch.setattr(asset_module, "DEFAULT_LAKE_ROOT", str(root))
    monkeypatch.setattr(asset_module, "DEFAULT_LAKE_STAGING_ROOT", str(staging))
    monkeypatch.setattr(checks, "DEFAULT_LAKE_ROOT", str(root))
    monkeypatch.setattr(checks, "DEFAULT_LAKE_STAGING_ROOT", str(staging))
    monkeypatch.setattr(LakeRootResource, "ensure_available_for_run", lambda *_: None)
    calls = []

    def source(params, control):
        calls.append(params)
        return [dict(ROW)], FIELDS

    monkeypatch.setattr(asset_module, "AnnouncementProcessCall", lambda *_: source)
    resources = {
        "lake_root": LakeRootResource(root_path=str(root)),
        "tushare": TushareResource(token="isolated-unused-token"),
    }
    with dg.DagsterInstance.ephemeral() as instance:
        result = dg.materialize(
            [asset_module.raw_tushare_anns_d],
            partition_key=DAY,
            resources=resources,
            instance=instance,
            run_config={"ops": {ANNOUNCEMENT_ASSET: {"config": {"interval_seconds": 0}}}},
        )
        assert result.success
        record = instance.fetch_materializations(
            dg.AssetRecordsFilter(asset_key=ASSET_KEY, asset_partitions=[DAY]), limit=1
        ).records[0]
        metadata = record.asset_materialization.metadata
        checkpoint_path = Path(metadata["goldenshare/announcement_checkpoint"].value)
        checkpoint = json.loads(checkpoint_path.read_text())
        policy, control = AnnouncementPolicy(interval_seconds=0), AnnouncementControl()
        store = AnnouncementStore(root, staging, "binding-test", policy, control)
        target = store.target(DAY)
        # Independent stat/hash verifies the real native producer's metadata key.
        fingerprint = {
            "size": target.stat().st_size,
            "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
        }
        assert metadata["goldenshare/fingerprint"].value == fingerprint
        assert checkpoint["delivery"]["fingerprint"] == fingerprint
        assert calls == [{"ann_date": "20230609", "limit": 2000, "offset": 0}]
        identity = checkpoint["identity"]
        definitions = dg.Definitions(
            assets=[asset_module.raw_tushare_anns_d],
            asset_checks=[
                checks.raw_tushare_anns_d_file_contract_check,
                checks.raw_tushare_anns_d_delivery_reconciliation_check,
            ],
            jobs=[dg.define_asset_job("binding_retry")],
            resources=resources,
        )
        yield SimpleNamespace(
            root=root, staging=staging, instance=instance, record=record,
            checkpoint_path=checkpoint_path, identity=identity, store=store,
            fingerprint=fingerprint, definitions=definitions,
            execution_path=staging / "anns_d/windows" / identity["window_id"] / "execution.json",
        )


def _evaluate(
    case, *, reconciliation=True, reuse_delivery=False, record=_ORIGINAL_RECORD,
    materializing=False,
):
    context = SimpleNamespace(
        instance=case.instance,
        run=SimpleNamespace(
            run_id=case.record.event_log_entry.run_id if materializing else "independent-check"
        ),
    )
    return checks.evaluate_announcement_check(
        context, LakeRootResource(root_path=str(case.root)), day=DAY,
        reconciliation=reconciliation, reuse_delivery=reuse_delivery,
        staging_root=case.staging,
        target_record=case.record if record is _ORIGINAL_RECORD else record,
        materializing=materializing,
    )


def _second_delivery(case):
    policy, control = AnnouncementPolicy(interval_seconds=0), AnnouncementControl()
    tags = announcement_window_tags("second-complete-delivery", DAY, DAY)
    result = execute_announcement_window(
        (DAY,), tags=tags, policy=policy, control=control,
        store_factory=lambda day: AnnouncementStore(
            case.root, case.staging, announcement_day_run_id(tags["anns_d/window_id"], day),
            policy, control,
        ),
        call_factory=lambda *_: lambda *_: (
            [{**ROW, "title": "second legitimate announcement"}], FIELDS
        ),
    )[DAY]
    assert result.delivery["written_rows"] == 2
    assert result.delivery["fingerprint"] != case.fingerprint
    return deepcopy(dict(result.delivery))


@pytest.mark.parametrize("reuse_delivery", [False, True])
def test_original_native_materialization_rejects_complete_foreign_cp_delivery(
    original_materialization, reuse_delivery
):
    case = original_materialization
    assert _evaluate(case).passed
    replacement = _second_delivery(case)
    document = json.loads(case.checkpoint_path.read_text())
    document["delivery"] = replacement  # Deliberate CP corruption; original A identity remains.
    case.checkpoint_path.write_text(json.dumps(document))
    before = (case.execution_path.read_bytes(), case.checkpoint_path.read_bytes())
    with pytest.raises(AnnouncementError, match="fingerprint|materialization|delivery"):
        _evaluate(case, reconciliation=not reuse_delivery, reuse_delivery=reuse_delivery)
    assert (case.execution_path.read_bytes(), case.checkpoint_path.read_bytes()) == before


def _recovery_context(case):
    job = case.definitions.resolve_job_def("binding_retry")
    check_keys = {dg.AssetCheckKey(ASSET_KEY, name) for name in ANNOUNCEMENT_CHECKS}
    check_steps = [
        str(job.asset_layer.get_op_output_handle(key).node_handle) for key in check_keys
    ]
    return SimpleNamespace(
        job_def=job,
        instance=case.instance,
        run=SimpleNamespace(
            run_id="binding-check-retry", root_run_id=case.record.event_log_entry.run_id,
            tags={}, asset_selection={ASSET_KEY}, asset_check_selection=check_keys,
            step_keys_to_execute=check_steps,
        ),
    )


def test_original_window_day_fingerprint_must_match_immutable_materialization(
    original_materialization,
):
    case = original_materialization
    context = _recovery_context(case)
    assert targets.prepare_announcement_check_targets(
        context, (DAY,), case.staging
    ).window_identity is not None
    document = json.loads(case.execution_path.read_text())
    document["days"][DAY]["fingerprint"] = {"size": 13, "sha256": "0" * 64}
    case.execution_path.write_text(json.dumps(document))
    before = case.execution_path.read_bytes()
    with pytest.raises(AnnouncementError, match="fingerprint|materialization|delivery"):
        targets.prepare_announcement_check_targets(context, (DAY,), case.staging)
    assert case.execution_path.read_bytes() == before


def _record_with_metadata(case, metadata):
    # Only the supported producer metadata representation is substituted here;
    # the original native record's storage id, run id and timestamp remain real.
    return SimpleNamespace(
        asset_materialization=dg.AssetMaterialization(
            asset_key=ASSET_KEY, partition=DAY, metadata=metadata
        ),
        storage_id=case.record.storage_id,
        event_log_entry=case.record.event_log_entry,
        timestamp=case.record.timestamp,
    )


@pytest.mark.parametrize("form", ["native", "runless", "both"])
def test_known_materialization_fingerprint_keys_accept_original_delivery(
    original_materialization, form
):
    case = original_materialization
    metadata = dict(case.record.asset_materialization.metadata)
    original = metadata.pop("goldenshare/fingerprint")
    if form in ("native", "both"):
        metadata["goldenshare/fingerprint"] = original
    if form in ("runless", "both"):
        # anns_d_events.py uses announcement_file for daily and bootstrap events.
        metadata["goldenshare/announcement_file"] = original
    record = _record_with_metadata(case, metadata)
    assert targets.announcement_materialization_fingerprint(record) == case.fingerprint
    assert _evaluate(case, record=record).passed


@pytest.mark.parametrize(
    "value", [None, {}, {"size": True, "sha256": "0" * 64},
              {"size": -1, "sha256": "0" * 64}, {"size": 1, "sha256": "short"}],
)
def test_missing_or_invalid_materialization_sha_is_not_filled_from_cp(
    original_materialization, value
):
    case = original_materialization
    metadata = dict(case.record.asset_materialization.metadata)
    if value is None:
        del metadata["goldenshare/fingerprint"]
    else:
        metadata["goldenshare/fingerprint"] = value
    record = _record_with_metadata(case, metadata)
    before = case.checkpoint_path.read_bytes()
    result = _evaluate(case, record=record)
    assert not result.passed
    assert result.metadata["goldenshare/failed_rule_names"].value == [
        "announcement_materialization_fingerprint_missing"
    ]
    assert case.checkpoint_path.read_bytes() == before
    with pytest.raises(AnnouncementError, match="recovery_delivery_evidence"):
        _evaluate(case, reconciliation=False, reuse_delivery=True, record=record)


def test_two_valid_but_conflicting_materialization_sha_keys_are_rejected(
    original_materialization,
):
    case = original_materialization
    metadata = dict(case.record.asset_materialization.metadata)
    metadata["goldenshare/announcement_file"] = {"size": 13, "sha256": "0" * 64}
    with pytest.raises(AnnouncementError, match="materialization_fingerprint_conflict"):
        _evaluate(case, record=_record_with_metadata(case, metadata))


@pytest.mark.parametrize("damage", ["missing_day", "phase", "missing_sha", "bad_sha", "path"])
def test_frozen_recovery_requires_original_promoted_day_proof(
    original_materialization, damage
):
    case = original_materialization
    document = json.loads(case.execution_path.read_text())
    if damage == "missing_day":
        del document["days"][DAY]
    elif damage == "phase":
        document["days"][DAY]["phase"] = "running"
    elif damage == "missing_sha":
        del document["days"][DAY]["fingerprint"]
    elif damage == "bad_sha":
        document["days"][DAY]["fingerprint"]["size"] = True
    else:
        document["days"][DAY]["checkpoint"] = str(case.staging / "other-delivery.json")
    case.execution_path.write_text(json.dumps(document))
    before = case.execution_path.read_bytes()
    with pytest.raises(AnnouncementError, match="recovery_delivery"):
        targets.prepare_announcement_check_targets(_recovery_context(case), (DAY,), case.staging)
    assert case.execution_path.read_bytes() == before


def test_frozen_recovery_keeps_original_checkpoint_path_binding(
    original_materialization, monkeypatch
):
    case = original_materialization
    metadata = dict(case.record.asset_materialization.metadata)
    metadata["goldenshare/announcement_checkpoint"] = str(
        case.staging / "anns_d/run_id=another/delivery.json"
    )
    record = _record_with_metadata(case, metadata)
    context = _recovery_context(case)
    # Only the materialization lookup is replaced, to model the wrong path field.
    monkeypatch.setattr(targets, "announcement_materialization", lambda *_: record)
    with pytest.raises(AnnouncementError, match="delivery_checkpoint_conflict"):
        targets.prepare_announcement_check_targets(context, (DAY,), case.staging)


def test_same_run_file_check_binds_before_sha_without_loading_cp_or_source(
    original_materialization, monkeypatch
):
    case = original_materialization
    _second_delivery(case)
    monkeypatch.setattr(
        checks, "_delivery_evidence",
        lambda *_args, **_kwargs: pytest.fail("same-run file rule loaded delivery CP"),
    )
    with pytest.raises(AnnouncementError, match="delivery_file_changed"):
        _evaluate(case, reconciliation=False, materializing=True)


def test_independent_schema_without_materialization_still_uses_file_rules_only(
    original_materialization,
):
    case = original_materialization
    assert _evaluate(case, reconciliation=False, record=None).passed
    result = _evaluate(case, reconciliation=True, record=None)
    assert not result.passed
    assert result.metadata["goldenshare/failed_rule_names"].value == [
        "announcement_materialization_missing"
    ]
    metadata = dict(case.record.asset_materialization.metadata)
    del metadata["goldenshare/fingerprint"]
    assert _evaluate(
        case, reconciliation=False, record=_record_with_metadata(case, metadata)
    ).passed
