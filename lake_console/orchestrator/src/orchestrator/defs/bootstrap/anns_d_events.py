"""Independent, recoverable event-only apply. Business files are never changed."""

from collections import defaultdict
from pathlib import Path

import dagster as dg
from dagster._core.definitions.asset_checks.asset_check_evaluation import (
    AssetCheckEvaluation,
    AssetCheckEvaluationTargetMaterializationData,
)

from orchestrator.defs.anns_d_checkpoint import (
    AnnouncementCheckpoint,
    announcement_file_fingerprint,
    announcement_file_lock,
)
from orchestrator.defs.anns_d_contract import (
    ANNOUNCEMENT_CHECKS,
    ANNOUNCEMENT_FIELDS,
    ANNOUNCEMENT_VERSION,
    AnnouncementError,
)
from orchestrator.defs.bootstrap.anns_d_event_files import (
    read_announcement_event_files,
    verify_announcement_event_evidence,
)
from orchestrator.defs.bootstrap.anns_d_event_state import (
    ASSET,
    TOKEN,
    EventReadBudget,
    matching_check,
    matching_mat,
    read_announcement_event_state,
    value,
)
from orchestrator.defs.bootstrap.anns_d_history_execution import (
    AnnouncementHistoryControl,
)
from orchestrator.defs.bootstrap.anns_d_history_plan import history_document_fingerprint
from orchestrator.defs.paths import DEFAULT_LAKE_STAGING_ROOT
from orchestrator.defs.run_contracts.asset_column_schemas import RAW_ANNS_D_SCHEMA
from orchestrator.defs.run_contracts.column_schema import build_column_schema_metadata
from orchestrator.defs.run_contracts.metadata import (
    build_check_metadata,
    build_materialization_metadata,
)


def validate_announcement_event_plan(plan):
    if (
        plan.get("kind") != "anns_d_event_plan"
        or plan.get("version") != 1
        or plan.get("fingerprint") != history_document_fingerprint(plan)
    ):
        raise AnnouncementError("announcement_event_plan_identity")
    entries = plan["entries"]
    if (
        not entries
        or len(entries) > 2465
        or len({e["day"] for e in entries}) != len(entries)
    ):
        raise AnnouncementError("announcement_event_file_budget")
    if plan["source"]["mode"] == "daily" and len(entries) > 7:
        raise AnnouncementError("announcement_event_daily_budget")
    for e in entries:
        if set(e["previous_check_ids"]) != set(ANNOUNCEMENT_CHECKS) or set(
            e["missing_checks"]
        ) - set(ANNOUNCEMENT_CHECKS):
            raise AnnouncementError("announcement_event_check_scope")


def _guard_state(plan, entry, state):
    mat = state["mat"]
    current = mat.storage_id if mat else None
    if current != entry["previous_mat_id"] and not (
        matching_mat(mat, entry)
        and value(mat.asset_materialization.metadata, TOKEN) == plan["fingerprint"]
    ):
        raise AnnouncementError("announcement_event_materialization_changed")
    if mat is not None and not matching_mat(mat, entry):
        raise AnnouncementError("announcement_event_materialization_conflict")
    for name, (storage_id, record) in state["checks"].items():
        if storage_id != entry["previous_check_ids"][name] and not (
            matching_check(record, name, mat, entry)
            and value(
                record.event_log_entry.dagster_event.event_specific_data.metadata, TOKEN
            )
            == plan["fingerprint"]
        ):
            raise AnnouncementError("announcement_event_check_changed")
        if record is not None and not matching_check(record, name, mat, entry):
            raise AnnouncementError("announcement_event_check_conflict")


def apply_announcement_events(
    instance, plan, stage, control, *, month=None, identity_probe=None
):
    validate_announcement_event_plan(plan)
    if stage not in ("materializations", "checks", "audit"):
        raise AnnouncementError("announcement_event_stage")
    selected = [
        e for e in plan["entries"] if month is None or e["day"][:7] + "-01" == month
    ]
    if not selected:
        raise AnnouncementError("announcement_event_month_not_planned")
    groups = defaultdict(list)
    for entry in selected:
        groups[entry["day"][:7] + "-01"].append(entry)
    budget, results = EventReadBudget(), []
    completed = 0
    total = len(selected) * (1 if stage == "materializations" else 2)

    def check_identity():
        if identity_probe is not None and identity_probe() != plan["instance_identity"]:
            raise AnnouncementError("instance_identity_changed")

    for key, entries in sorted(groups.items()):
        child = AnnouncementHistoryControl(control, 1800)
        child.check()
        check_identity()
        actual = read_announcement_event_files(plan["source"], child, month=key)
        frozen = [
            {
                k: v
                for k, v in e.items()
                if k
                not in (
                    "previous_mat_id",
                    "previous_check_ids",
                    "missing_mat",
                    "missing_checks",
                )
            }
            for e in entries
        ]
        if actual != frozen:
            raise AnnouncementError("announcement_event_file_evidence_changed")

        def run_month(entries=entries, child=child, key=key, completed=completed):
            state = read_announcement_event_state(instance, entries, budget, child)
            for entry in entries:
                _guard_state(plan, entry, state[entry["day"]])
            written = 0
            checkpoint = None
            if stage != "audit":
                checkpoint = AnnouncementCheckpoint(
                    Path(DEFAULT_LAKE_STAGING_ROOT)
                    / "anns_d"
                    / "events"
                    / plan["fingerprint"]
                    / f"{key}.json",
                    {"event_plan": plan["fingerprint"], "month": key},
                )
            for entry in entries:
                day, current = entry["day"], state[entry["day"]]
                names = (
                    [None]
                    if stage == "materializations"
                    else list(ANNOUNCEMENT_CHECKS)
                    if stage == "checks"
                    else []
                )
                if stage == "checks" and current["mat"] is None:
                    raise AnnouncementError(
                        "announcement_event_materialization_missing"
                    )
                for name in names:
                    child.check()
                    check_identity()
                    if (
                        announcement_file_fingerprint(entry["checkpoint"])
                        != entry["checkpoint_file"]
                    ):
                        raise AnnouncementError("announcement_event_checkpoint_changed")
                    if announcement_file_fingerprint(entry["path"]) != entry["file"]:
                        raise AnnouncementError("announcement_event_file_changed")
                    if (name is None and matching_mat(current["mat"], entry)) or (
                        name is not None
                        and matching_check(
                            current["checks"][name][1], name, current["mat"], entry
                        )
                    ):
                        continue
                    extra = {
                        "announcement_file": entry["file"],
                        "announcement_contract_version": ANNOUNCEMENT_VERSION,
                        "announcement_event_plan": plan["fingerprint"],
                    }
                    if name is None:
                        event = dg.AssetMaterialization(
                            asset_key=ASSET,
                            partition=day,
                            metadata=build_materialization_metadata(
                                uri=entry["path"],
                                row_count=entry["rows"],
                                observed_columns=ANNOUNCEMENT_FIELDS,
                                extra_metadata={
                                    **extra,
                                    "announcement_checkpoint": entry["checkpoint"],
                                    "announcement_identity": entry["identity"],
                                    "source_row_count": entry["source_rows"],
                                    "rejected_row_count": 0,
                                    "dagster/column_schema": build_column_schema_metadata(
                                        RAW_ANNS_D_SCHEMA
                                    ),
                                },
                            ),
                        )
                    else:
                        mat = current["mat"]
                        event = AssetCheckEvaluation(
                            asset_key=ASSET,
                            check_name=name,
                            passed=True,
                            partition=day,
                            severity=dg.AssetCheckSeverity.ERROR,
                            blocking=True,
                            target_materialization_data=AssetCheckEvaluationTargetMaterializationData(
                                storage_id=mat.storage_id,
                                run_id=mat.event_log_entry.run_id,
                                timestamp=mat.event_log_entry.timestamp,
                            ),
                            metadata=build_check_metadata(
                                check_scope="schema"
                                if name == ANNOUNCEMENT_CHECKS[0]
                                else "reconciliation",
                                checked_row_count=entry["rows"],
                                failed_row_count=0,
                                file_path=entry["path"],
                                extra_metadata=extra,
                            ),
                        )
                    instance.report_runless_asset_event(event)
                    written += 1
                    child.check()
                    checkpoint.save(
                        phase=stage,
                        last_day=day,
                        last_check=name,
                        written_this_attempt=written,
                    )
                    child.progress(
                        phase=stage,
                        month=key,
                        day=day,
                        completed=completed + written,
                        total=total,
                    )
            after = read_announcement_event_state(instance, entries, budget, child)
            for entry in entries:
                _guard_state(plan, entry, after[entry["day"]])
                if not matching_mat(after[entry["day"]]["mat"], entry) or (
                    stage != "materializations"
                    and not all(
                        matching_check(
                            after[entry["day"]]["checks"][n][1],
                            n,
                            after[entry["day"]]["mat"],
                            entry,
                        )
                        for n in ANNOUNCEMENT_CHECKS
                    )
                ):
                    raise AnnouncementError("announcement_event_readback_failed")
                if announcement_file_fingerprint(entry["path"]) != entry["file"]:
                    raise AnnouncementError("announcement_event_file_changed")
            verify_announcement_event_evidence(entries)
            check_identity()
            if checkpoint:
                checkpoint.save(phase=stage + "_verified", written_this_attempt=written)
            return {
                "month": key,
                "files": len(entries),
                "written": written,
                "passed": True,
            }

        if stage == "audit":
            results.append(run_month())
        else:
            with announcement_file_lock(
                Path(DEFAULT_LAKE_STAGING_ROOT)
                / "anns_d"
                / "locks"
                / "event-execution.lock"
            ):
                results.append(run_month())
        completed += len(entries) * (1 if stage == "materializations" else 2)
        child.progress(phase=stage, month=key, completed=completed, total=total)
    return {
        "kind": "anns_d_event_result",
        "stage": stage,
        "plan_fingerprint": plan["fingerprint"],
        "months": results,
        "records_returned": budget.returned,
        "written": sum(r["written"] for r in results),
    }
