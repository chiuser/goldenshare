"""Explicit dates, canonical whole-job requests and immutable parent scope."""

from datetime import date, datetime, time, timedelta

from orchestrator.defs.run_contracts.run_keys import (
    build_asset_update_run_key,
    build_repair_attempt_run_key,
)
from orchestrator.moneyflow_continuation.contract import (
    CONTRACTS,
    DATASETS,
    ENDPOINT,
    POLICY,
    REPOSITORY,
    ContinuationError,
    digest,
    policy_dict,
    require,
    unit_identity,
)

REGISTER = """mutation($repositorySelector:RepositorySelector!,$partitionsDefName:String!,$partitionKey:String!){addDynamicPartition(repositorySelector:$repositorySelector,partitionsDefName:$partitionsDefName,partitionKey:$partitionKey){__typename ... on AddDynamicPartitionSuccess{partitionsDefName partitionKey}}}"""
LAUNCH = """mutation($executionParams:ExecutionParams!){launchRun(executionParams:$executionParams){__typename ... on LaunchRunSuccess{run{runId status}}}}"""


def validate_scope(entries, open_days, at):
    require(
        isinstance(entries, list) and 0 < len(entries) <= POLICY.max_units,
        "scope_size",
        2,
    )
    keys = set()
    for item in entries:
        require(
            isinstance(item, dict) and set(item) == {"dataset", "trade_date"},
            "scope_fields",
            2,
        )
        dataset, day = item["dataset"], item["trade_date"]
        require(dataset in DATASETS, "unknown_dataset", 2)
        try:
            parsed = date.fromisoformat(day)
        except (TypeError, ValueError) as error:
            raise ContinuationError("date_format", 2) from error
        require(
            parsed.isoformat() == day and day > "2026-09-30", "history_out_of_scope", 2
        )
        require(day in open_days, "not_sse_open", 2)
        require(
            parsed < at.date()
            or (parsed == at.date() and at.time().replace(tzinfo=None) >= time(22)),
            "date_not_mature",
            2,
        )
        require((dataset, day) not in keys, "duplicate_unit", 2)
        keys.add((dataset, day))
    return sorted(keys, key=lambda x: (DATASETS.index(x[0]), x[1]))


def request_for(unit, action, attempt_day, raw_sha=None):
    require(action in {"register", "raw", "silver"}, "action_not_allowed", 2)
    dataset, day = unit["dataset"], unit["trade_date"]
    require(unit == unit_identity(dataset, day), "unit_contract_drift")
    c = CONTRACTS[dataset]
    if action == "register":
        return {
            "query": REGISTER,
            "variables": {
                "repositorySelector": REPOSITORY,
                "partitionsDefName": c.partition_set,
                "partitionKey": day,
            },
        }
    if action == "raw":
        require(
            date.fromisoformat(attempt_day).isoformat() == attempt_day, "attempt_day", 2
        )
        key = build_repair_attempt_run_key(
            subject=c.raw_asset,
            repair_scope_id=day,
            attempt=1,
            attempt_scope=attempt_day,
        )
    else:
        require(
            isinstance(raw_sha, str)
            and len(raw_sha) == 64
            and all(c in "0123456789abcdef" for c in raw_sha),
            "raw_hash_required",
            2,
        )
        key = build_asset_update_run_key(
            subject=c.silver_asset, unit_id=day + ":" + raw_sha
        )
    tags = {
        "dagster/partition": day,
        "dagster/partition_set": getattr(c, action + "_job") + "_partition_set",
        "dagster/run_key": key,
    }
    return {
        "query": LAUNCH,
        "variables": {
            "executionParams": {
                "selector": {**REPOSITORY, "jobName": getattr(c, action + "_job")},
                "runConfigData": {},
                "executionMetadata": {
                    "tags": [{"key": k, "value": v} for k, v in sorted(tags.items())]
                },
            }
        },
    }


def make_plan(
    entries,
    open_days,
    at,
    verification,
    inventory,
    observations,
    parent=None,
    parent_sha=None,
):
    keys = validate_scope(entries, open_days, at)
    units = [unit_identity(*key) for key in keys]
    root_units = units
    if parent:
        validate_plan(parent)
        require(parent_sha is not None, "parent_hash_required", 2)
        allowed = {(x["dataset"], x["trade_date"]) for x in parent["units"]}
        require(set(keys) <= allowed, "parent_scope_expanded", 2)
        root_units = parent["root_units"]
    plan = {
        "format": 1,
        "mode": "plan",
        "complete": False,
        "created_at": at.isoformat(),
        "valid_until": datetime.combine(
            at.date() + timedelta(days=1), time(), at.tzinfo
        ).isoformat(),
        "parent_sha256": parent_sha,
        "root_scope_digest": digest(root_units),
        "root_units": root_units,
        "units": units,
        "policy": policy_dict(),
        "endpoint": ENDPOINT,
        "repository": REPOSITORY,
        "verification": verification,
        "source_inventory": inventory,
        "observations": observations,
        "authorization": "Requires explicit approval of this exact scope; a plan is not approval.",
    }
    validate_plan(plan)
    return plan


def validate_plan(plan):
    require(plan.get("format") == 1 and plan.get("mode") == "plan", "plan_format", 2)
    require(
        plan.get("policy") == policy_dict()
        and plan.get("endpoint") == ENDPOINT
        and plan.get("repository") == REPOSITORY,
        "plan_policy",
        2,
    )
    root, units = plan.get("root_units"), plan.get("units")
    require(
        isinstance(root, list)
        and isinstance(units, list)
        and 0 < len(units) <= len(root) <= POLICY.max_units,
        "plan_scope",
        2,
    )
    for items in (root, units):
        keys = []
        for unit in items:
            require(
                isinstance(unit, dict) and unit.get("dataset") in DATASETS,
                "plan_unit",
                2,
            )
            try:
                require(
                    date.fromisoformat(unit["trade_date"]).isoformat()
                    == unit["trade_date"]
                    and unit["trade_date"] > "2026-09-30",
                    "plan_date",
                    2,
                )
                require(
                    unit == unit_identity(unit["dataset"], unit["trade_date"]),
                    "plan_contract",
                    2,
                )
            except (KeyError, ValueError) as error:
                raise ContinuationError("plan_unit", 2) from error
            keys.append((unit["dataset"], unit["trade_date"]))
        require(
            len(set(keys)) == len(keys)
            and keys == sorted(keys, key=lambda x: (DATASETS.index(x[0]), x[1])),
            "plan_order",
            2,
        )
    require(
        all(unit in root for unit in units)
        and digest(root) == plan.get("root_scope_digest"),
        "root_scope_digest",
        2,
    )
    require(isinstance(plan.get("verification"), dict), "verification_required", 2)
    try:
        created, expires = (
            datetime.fromisoformat(plan[k]) for k in ("created_at", "valid_until")
        )
        require(
            created.tzinfo is not None
            and expires.tzinfo is not None
            and expires.date() == created.date() + timedelta(days=1)
            and expires.timetz().replace(tzinfo=None) == time(),
            "plan_validity",
            2,
        )
    except (KeyError, ValueError, TypeError) as error:
        raise ContinuationError("plan_validity", 2) from error
