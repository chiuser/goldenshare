"""Frozen candidate proofs and native isolated event storage, with write traps."""

from types import SimpleNamespace

import dagster as dg
import pytest

from orchestrator.defs.bootstrap.moneyflow_history_cohort import _large_json
from orchestrator.defs.bootstrap.moneyflow_mkt_dc_event_preview import (
    preview_market_moneyflow_history,
)
from orchestrator.defs.paths import raw_moneyflow_path
from orchestrator.defs.run_contracts.moneyflow import MoneyflowContractError

from .test_moneyflow_history_promote import (
    DAY,
    hashes,
    isolated_space,  # noqa: F401 - pytest fixture
    operation,
    run,
    setup,
)


def prepare(tmp_path):
    staging, lake, source = setup(tmp_path)
    assert run(staging, lake, apply=True)["stage"] == "files_complete"
    return staging, lake, source


def preview(staging, lake, instance):
    return preview_market_moneyflow_history(
        instance=instance,
        staging_root=staging,
        lake_root=lake,
        operation_id="cohort",
        cutoff=DAY,
        expected_cohort_hash=_large_json(operation(staging) / "cohort.json")[
            "cohort_hash"
        ],
    )


class ReadOnly:
    def __init__(self, instance):
        self.instance = instance
        self.event_log_storage = SimpleNamespace(
            get_asset_check_execution_history=instance.event_log_storage.get_asset_check_execution_history
        )

    def get_dynamic_partitions(self, *args):
        return self.instance.get_dynamic_partitions(*args)

    def fetch_materializations(self, *args, **kwargs):
        return self.instance.fetch_materializations(*args, **kwargs)


def test_preview_hashes_frozen_physical_files_but_never_writes(tmp_path):
    staging, lake, source = prepare(tmp_path)
    before = hashes(staging), hashes(lake), source.calls
    instance_home = tmp_path / "instance"
    instance_home.mkdir()
    with dg.DagsterInstance.local_temp(
        str(instance_home), overrides={"telemetry": {"enabled": False}}
    ) as instance:
        result = preview(staging, lake, ReadOnly(instance))
        assert (
            result["history_dates"]
            == result["history_rows"]
            == result["verified_units"]
            == 1
        )
        assert result["verified_files"] == 2
        assert result["partitions_to_add"] == 1
        assert result["metadata_queries"] == 5 and result["formal_writes"] == 0
        assert result["control_files_unchanged"] == 4
        assert all(
            value["materializations_to_add"] == value["recent_checks_to_add"] == 1
            for value in result["layers"].values()
        )
        assert preview(staging, lake, ReadOnly(instance)) == result
    assert before == (hashes(staging), hashes(lake), source.calls)


@pytest.mark.parametrize(
    "kind", ["changed_file", "missing_file", "checkpoint", "promotion"]
)
def test_preview_rejects_changed_proof_or_physical_file(tmp_path, kind):
    staging, lake, _ = prepare(tmp_path)
    path = raw_moneyflow_path(lake, "moneyflow_mkt_dc", DAY)
    if kind == "changed_file":
        path.write_bytes(path.read_bytes() + b"changed")
    elif kind == "missing_file":
        path.unlink()  # only this test's isolated temporary file
    else:
        control = next((operation(staging) / "moneyflow_mkt_dc").rglob(kind + ".json"))
        control.write_text("{}")
    with pytest.raises(MoneyflowContractError):
        preview(staging, lake, SimpleNamespace())


@pytest.mark.parametrize(
    "kind", ["valid", "wrong_hash", "wrong_upstream", "failed_check", "stale_check"]
)
def test_existing_native_events_reused_only_with_exact_file_and_target(tmp_path, kind):
    from dagster._core.definitions.asset_checks.asset_check_evaluation import (
        AssetCheckEvaluation,
        AssetCheckEvaluationTargetMaterializationData,
    )

    from orchestrator.defs.io.moneyflow_candidates import candidate_file_hash
    from orchestrator.defs.paths import silver_moneyflow_path
    from orchestrator.defs.run_contracts.moneyflow import (
        MONEYFLOW_MKT_DC_RAW_CHECK,
        MONEYFLOW_MKT_DC_SILVER_CHECK,
    )

    staging, lake, _ = prepare(tmp_path)
    raw_hash = candidate_file_hash(raw_moneyflow_path(lake, "moneyflow_mkt_dc", DAY))
    instance_home = tmp_path / "instance"
    instance_home.mkdir()
    with dg.DagsterInstance.local_temp(
        str(instance_home), overrides={"telemetry": {"enabled": False}}
    ) as instance:
        for layer, name in (
            ("raw", MONEYFLOW_MKT_DC_RAW_CHECK),
            ("silver", MONEYFLOW_MKT_DC_SILVER_CHECK),
        ):
            key = dg.AssetKey(
                "raw_tushare_moneyflow_mkt_dc"
                if layer == "raw"
                else "silver_moneyflow_mkt_dc"
            )
            digest = (
                raw_hash
                if layer == "raw"
                else candidate_file_hash(
                    silver_moneyflow_path(lake, "moneyflow_mkt_dc", DAY)
                )
            )
            instance.report_runless_asset_event(
                dg.AssetMaterialization(
                    asset_key=key,
                    partition=DAY,
                    metadata={
                        "goldenshare/file_sha256": "0" * 64
                        if kind == "wrong_hash"
                        else digest,
                        "goldenshare/raw_sha256": "0" * 64
                        if kind == "wrong_upstream"
                        else raw_hash,
                    },
                )
            )
            mat = instance.fetch_materializations(
                dg.AssetRecordsFilter(asset_key=key, asset_partitions=[DAY]), limit=1
            ).records[0]
            instance.report_runless_asset_event(
                AssetCheckEvaluation(
                    asset_key=key,
                    check_name=name,
                    passed=kind != "failed_check",
                    partition=DAY,
                    blocking=True,
                    target_materialization_data=AssetCheckEvaluationTargetMaterializationData(
                        storage_id=mat.storage_id + (1 if kind == "stale_check" else 0),
                        run_id=mat.event_log_entry.run_id,
                        timestamp=mat.timestamp,
                    ),
                )
            )
        if kind == "valid":
            result = preview(staging, lake, ReadOnly(instance))
            assert all(
                v["materializations_to_add"] == v["recent_checks_to_add"] == 0
                and v["materializations_reusable"] == v["recent_checks_reusable"] == 1
                for v in result["layers"].values()
            )
        else:
            with pytest.raises(MoneyflowContractError):
                preview(staging, lake, ReadOnly(instance))


def test_unit_symlink_rejected_before_checkpoint_reader(tmp_path, monkeypatch):
    import orchestrator.defs.bootstrap.moneyflow_mkt_dc_event_preview as module

    staging, lake, _ = prepare(tmp_path)
    unit = next((operation(staging) / "moneyflow_mkt_dc").rglob("unit-000000"))
    moved = tmp_path / "moved-unit"
    unit.rename(moved)
    unit.symlink_to(moved, target_is_directory=True)

    def forbidden(*args):
        raise AssertionError(
            "A symlinked unit must be rejected before reading its checkpoint."
        )

    monkeypatch.setattr(module, "_promotion_state", forbidden)
    with pytest.raises(MoneyflowContractError, match="history_promotion_path"):
        preview(staging, lake, SimpleNamespace())
