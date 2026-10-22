"""One reviewed maintenance phase, invoked by the process holding prepared Basic.

A new shell process cannot inherit that memory. This module deliberately has no
Basic file option, instance initializer, source downloader, or all-phases command.
"""

from __future__ import annotations

import argparse
import json
from contextlib import contextmanager
from pathlib import Path
from time import perf_counter

from orchestrator.defs.asset_guards.etf_adj_factor_history_completion import (
    require_prepared_basic,
)
from orchestrator.defs.bootstrap.etf_adj_factor_history_completion import (
    _budget,
    _fixed_totals,
    _prepared_cache,
    _reject_links,
    audit_completion_candidates,
    audit_completion_final,
    build_completion_plan,
    completion_directory,
    prepare_completion_candidates,
    promote_completion_candidates,
    report_completion_events,
)
from orchestrator.defs.bootstrap.etf_daily_bootstrap_plan import (
    BOOTSTRAP_STAGING_ROOT,
    FORMAL_LAKE_ROOT,
    atomic_write_json,
    write_immutable_json,
)
from orchestrator.defs.duckdb_connection import (
    DuckDBConnectionSettings,
    connect_configured_duckdb,
)
from orchestrator.defs.resources import DuckDBResource, LakeRootResource
from orchestrator.defs.run_contracts.etf_daily import EtfFactorCompletionPlan


class CompletionDuckDBResource(DuckDBResource):
    """Fixed maintenance limits; directory is supplied internally, never by env."""

    temp_directory: str

    @contextmanager
    def connect(self):
        with connect_configured_duckdb(
            DuckDBConnectionSettings(
                temp_directory=Path(self.temp_directory),
                memory_limit="256MB",
                threads=1,
                max_temp_directory_size="0B",
            ),
            temp_policy="existing_no_spill",
        ) as connection:
            yield connection


def _parser():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="stage", required=True)
    for stage in (
        "plan",
        "candidates",
        "candidate-audit",
        "promote",
        "events",
        "final-audit",
    ):
        command = commands.add_parser(stage)
        command.add_argument("--plan", type=Path, required=True)
        if stage != "plan":
            command.add_argument("--expected-plan-hash", required=True)
        if stage in {"candidates", "promote", "events"}:
            command.add_argument("--confirm-stage", action="store_true")
    return parser


def _plan_path(path: Path, staging_root: Path):
    if (
        not path.is_absolute()
        or ".." in path.parts
        or not path.is_relative_to(staging_root / "etf_daily")
        or any(parent.is_symlink() for parent in (path, *path.parents))
    ):
        raise ValueError("completion_plan_path_outside_staging")


def run_stage(
    stage: str,
    *,
    plan_path: Path,
    expected_plan_hash: str | None = None,
    prepared_basic=None,
    scope=None,
    basic_reference=None,
    storage=None,
    instance=None,
    job=None,
    duckdb_resource=None,
    lake_root: Path = FORMAL_LAKE_ROOT,
    staging_root: Path = BOOTSTRAP_STAGING_ROOT,
    approved=False,
    previous_process_exited=False,
    check_cancel=lambda: False,
):
    """Objects and roots are internal seams; CLI does not expose root overrides."""
    started = perf_counter()
    caller_cancel = check_cancel

    def check_cancel():
        return caller_cancel() or perf_counter() - started > 30

    prepared = require_prepared_basic(prepared_basic)  # Before opening any Plan/data.
    if stage not in {
        "plan",
        "candidates",
        "candidate-audit",
        "promote",
        "events",
        "final-audit",
    }:
        raise ValueError("completion_unknown_stage")
    _plan_path(plan_path, staging_root)
    if stage in {"candidates", "promote", "events"} and not approved:
        raise ValueError("completion_stage_not_approved")
    if storage is None or duckdb_resource is None:
        raise ValueError("completion_existing_storage_and_resource_required")
    if not isinstance(duckdb_resource, CompletionDuckDBResource):
        raise TypeError("completion_controlled_duckdb_resource_required")
    _budget(started, check_cancel)
    if stage in {"promote", "events", "final-audit"} and instance is None:
        raise ValueError("completion_existing_instance_required")
    if stage == "events" and job is None:
        raise ValueError("completion_resolved_existing_job_required")
    if stage == "plan":
        if scope is None or basic_reference is None:
            raise ValueError("completion_reviewed_scope_and_latest_reference_required")
        # No file exists yet; use the caller's independently validated references.
        references = tuple(prepared.references.values())
        with duckdb_resource.connect() as connection:
            cache = prepared.seed_cache(connection, lake_root, references)
            plan = build_completion_plan(
                connection=connection,
                lake_root=lake_root,
                storage=storage,
                scope=scope,
                basic_reference=basic_reference,
                basic_cache=cache,
                check_cancel=check_cancel,
            )
        _fixed_totals(plan)
        _budget(started, check_cancel)
        write_immutable_json(plan_path, plan.to_dict())
        _budget(started, check_cancel)
        return plan.to_dict()
    if plan_path.stat().st_size > 256 * 1024:
        raise ValueError("completion_plan_payload_exceeds_budget")
    plan = EtfFactorCompletionPlan.from_dict(json.loads(plan_path.read_text()))
    _fixed_totals(plan)
    if plan.plan_hash != expected_plan_hash:
        raise ValueError("completion_expected_plan_hash_mismatch")
    if stage == "final-audit":
        _reject_links(completion_directory(staging_root, plan) / "final-audit.json")
        report = audit_completion_final(
            lake_root=lake_root,
            instance=instance,
            duckdb_resource=duckdb_resource,
            plan=plan,
            prepared_basic=prepared,
            check_cancel=check_cancel,
        )
        atomic_write_json(
            completion_directory(staging_root, plan) / "final-audit.json", report
        )
        _budget(started, check_cancel)
        return report
    with duckdb_resource.connect() as connection:
        cache = _prepared_cache(prepared, connection, lake_root, plan)
        common = {
            "connection": connection,
            "lake_root": lake_root,
            "staging_root": staging_root,
            "plan": plan,
            "check_cancel": check_cancel,
        }
        if stage == "candidates":
            result = prepare_completion_candidates(
                storage=storage, basic_cache=cache, **common
            )
        elif stage == "candidate-audit":
            result = audit_completion_candidates(
                storage=storage, prepared_basic=prepared, **common
            )
        elif stage == "promote":
            result = promote_completion_candidates(
                storage=storage,
                instance=instance,
                prepared_basic=prepared,
                approved=approved,
                **common,
            )
        else:
            result = report_completion_events(
                instance=instance,
                job=job,
                prepared_basic=prepared,
                resources={
                    "duckdb": duckdb_resource,
                    "lake_root": LakeRootResource(root_path=str(lake_root)),
                },
                approved=approved,
                previous_process_exited=previous_process_exited,
                **common,
            )
    _budget(started, check_cancel)
    return result


def main(argv=None, *, prepared_basic=None, **context):
    args = _parser().parse_args(argv)
    return run_stage(
        args.stage,
        plan_path=args.plan,
        expected_plan_hash=getattr(args, "expected_plan_hash", None),
        prepared_basic=prepared_basic,
        approved=getattr(args, "confirm_stage", False),
        **context,
    )


if __name__ == "__main__":
    main()
