"""Bounded native event reconciliation for seven repaired dataset dates."""

import dagster as dg
from dagster._core.definitions.asset_checks.asset_check_evaluation import (
    AssetCheckEvaluation,
    AssetCheckEvaluationTargetMaterializationData,
)
from dagster._core.event_api import PartitionKeyFilter

from orchestrator.defs.bootstrap.moneyflow_history_plan import history_schema
from orchestrator.defs.bootstrap.moneyflow_history_supplement_control import (
    CONTRACTS,
    file_hash,
    require,
)
from orchestrator.defs.run_contracts.metadata import (
    CheckScope,
    build_check_metadata,
    build_materialization_metadata,
)


def metadata(mat):
    return {
        k.removeprefix("goldenshare/"): v.value
        for k, v in mat.asset_materialization.metadata.items()
    }


def facts(instance, entry, layer, control):
    contract = CONTRACTS[entry["dataset"]]
    asset = dg.AssetKey(contract.raw_asset if layer == "raw" else contract.silver_asset)
    check_name = contract.raw_check if layer == "raw" else contract.silver_check
    mats = control.read(
        instance.fetch_materializations,
        dg.AssetRecordsFilter(asset_key=asset, asset_partitions=[entry["day"]]),
        limit=1,
    ).records
    checks = control.read(
        instance.event_log_storage.get_asset_check_execution_history,
        dg.AssetCheckKey(asset, check_name),
        limit=1,
        partition_filter=PartitionKeyFilter(key=entry["day"]),
    )
    return (mats[0] if mats else None, checks[0] if checks else None)


def valid_check(mat, check, *, sha=None, file_sha=None):
    if not mat or not check or not check.event or not check.event.dagster_event:
        return False
    evaluation = check.event.dagster_event.event_specific_data
    binding = getattr(evaluation, "target_materialization_data", None)
    values = {
        k.removeprefix("goldenshare/"): v.value for k, v in evaluation.metadata.items()
    }
    return (
        check.status.value == "SUCCEEDED"
        and getattr(evaluation, "passed", False)
        and getattr(evaluation, "blocking", False)
        and binding is not None
        and binding.storage_id == mat.storage_id
        and binding.run_id == mat.event_log_entry.run_id
        and binding.timestamp == mat.timestamp
        and (sha is None or values.get("supplement_plan_sha256") == sha)
        and (file_sha is None or values.get("file_sha256") == file_sha)
    )


def baseline(instance, entry, layer, file_sha, control):
    mat, check = facts(instance, entry, layer, control)
    if file_sha is None:
        require(mat is None and check is None, "events_without_file")
    else:
        require(
            mat is not None and metadata(mat).get("file_sha256") == file_sha,
            "old_materialization",
        )
        require(
            check is None or valid_check(mat, check, file_sha=file_sha),
            "old_check_failed_or_stale",
        )
        require(
            check is None or bool(check.event.run_id),
            "old_runless_check_revision_unsupported",
        )
        if layer == "silver":
            require(
                metadata(mat).get("raw_sha256") == entry["baseline"]["raw"]["hash"],
                "old_silver_lineage",
            )
    return {
        "mat_id": mat.storage_id if mat else None,
        "check_id": check.id if check else None,
    }


def unchanged_baseline(instance, entry, layer, control):
    mat, check = facts(instance, entry, layer, control)
    old = entry["baseline"][layer]
    require(
        (mat.storage_id if mat else None) == old["mat_id"]
        and (check.id if check else None) == old["check_id"],
        "native_baseline_changed",
    )
    if mat:
        require(
            metadata(mat).get("file_sha256") == old["hash"],
            "old_materialization_changed",
        )


def _materialization_identity(mat, entry, layer, hashes, control):
    index = control.plan["entries"].index(entry)
    proof_sha = control.state["items"][str(index)]["proof_sha256"]
    require(mat is not None, "materialization_missing")
    values = metadata(mat)
    require(
        values.get("supplement_plan_sha256") == control.sha
        and values.get("file_sha256") == hashes[layer]
        and values.get("supplement_proof_sha256") == proof_sha
        and values.get("dagster/row_count") == len(entry["keys"]),
        "materialization_identity",
    )
    if layer == "silver":
        require(values.get("raw_sha256") == hashes["raw"], "silver_lineage")


def accepted(instance, entry, hashes, control):
    for layer in ("raw", "silver"):
        mat, check = facts(instance, entry, layer, control)
        _materialization_identity(mat, entry, layer, hashes, control)
        require(
            valid_check(mat, check, sha=control.sha, file_sha=hashes[layer]),
            "check_binding",
        )


def register(instance, entry, paths, hashes, control):
    contract = CONTRACTS[entry["dataset"]]
    key_prefix = entry["dataset"] + "/" + entry["day"]
    index = control.plan["entries"].index(entry)
    item = control.state["items"][str(index)]
    present = control.read(
        instance.has_dynamic_partition, contract.partition_set, entry["day"]
    )
    if not present:
        key = key_prefix + "/partition"
        require(not entry["partition_exists"], "partition_disappeared")
        control.intent(key, "partitions")
        instance.add_dynamic_partitions(contract.partition_set, [entry["day"]])
        require(
            control.read(
                instance.has_dynamic_partition, contract.partition_set, entry["day"]
            ),
            "partition_readback",
        )
        control.state["actions"][key] = "complete"
        control.save()
    for layer in ("raw", "silver"):
        mat, check = facts(instance, entry, layer, control)
        require(file_hash(paths[layer]) == hashes[layer], "event_file_changed")
        key = key_prefix + "/" + layer
        old = entry["baseline"][layer]
        is_own = (
            mat is not None
            and metadata(mat).get("supplement_plan_sha256") == control.sha
        )
        if is_own:
            require(
                metadata(mat).get("file_sha256") == hashes[layer],
                "own_materialization_changed",
            )
        else:
            require(
                (mat.storage_id if mat else None) == old["mat_id"]
                and (check.id if check else None) == old["check_id"],
                "unknown_native_revision",
            )
            control.intent(key + "/mat", "materializations")
            extra = {
                "file_sha256": hashes[layer],
                "supplement_plan_sha256": control.sha,
                "supplement_proof_sha256": item["proof_sha256"],
                "source_receipt_sha256": item["source"]["receipt_sha256"],
                "operation_id": control.plan["operation_id"],
                "source": "prod_raw_history_supplement",
                "partition_key": entry["day"],
                "source_row_count": len(entry["keys"]),
                "rejected_row_count": 0,
            }
            if layer == "silver":
                extra["raw_sha256"] = hashes["raw"]
            instance.report_runless_asset_event(
                dg.AssetMaterialization(
                    asset_key=contract.raw_asset
                    if layer == "raw"
                    else contract.silver_asset,
                    partition=entry["day"],
                    metadata=build_materialization_metadata(
                        uri=paths[layer],
                        row_count=len(entry["keys"]),
                        observed_columns=[
                            c.name
                            for c in history_schema(
                                entry["dataset"], silver=layer == "silver"
                            )
                        ],
                        extra_metadata=extra,
                    ),
                )
            )
            mat, check = facts(instance, entry, layer, control)
            require(
                mat is not None
                and metadata(mat).get("supplement_plan_sha256") == control.sha,
                "materialization_readback",
            )
        control.state["actions"][key + "/mat"] = "complete"
        control.save()
        _materialization_identity(mat, entry, layer, hashes, control)
        if not valid_check(mat, check, sha=control.sha, file_sha=hashes[layer]):
            require(file_hash(paths[layer]) == hashes[layer], "event_file_changed")
            require(
                (check.id if check else None) == old["check_id"],
                "unknown_check_revision",
            )
            control.intent(key + "/check", "checks")
            instance.report_runless_asset_event(
                AssetCheckEvaluation(
                    asset_key=mat.asset_key,
                    check_name=contract.raw_check
                    if layer == "raw"
                    else contract.silver_check,
                    passed=True,
                    partition=entry["day"],
                    blocking=True,
                    severity=dg.AssetCheckSeverity.ERROR,
                    target_materialization_data=AssetCheckEvaluationTargetMaterializationData(
                        storage_id=mat.storage_id,
                        run_id=mat.event_log_entry.run_id,
                        timestamp=mat.timestamp,
                    ),
                    metadata=build_check_metadata(
                        check_scope=CheckScope.SCHEMA
                        if layer == "raw"
                        else CheckScope.RECONCILIATION,
                        checked_row_count=len(entry["keys"]),
                        failed_row_count=0,
                        file_path=paths[layer],
                        extra_metadata={
                            "file_sha256": hashes[layer],
                            "supplement_plan_sha256": control.sha,
                            "partition_key": entry["day"],
                        },
                    ),
                )
            )
            mat, check = facts(instance, entry, layer, control)
            require(
                valid_check(mat, check, sha=control.sha, file_sha=hashes[layer]),
                "check_readback",
            )
        control.state["actions"][key + "/check"] = "complete"
        control.save()
