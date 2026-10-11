"""Frozen independent moneyflow event scope and actual storage identity, without writes."""

from pathlib import Path

from dagster._core.storage.event_log.sqlite.sqlite_event_log import (
    SqliteEventLogStorage,
)
from dagster._core.storage.runs.sqlite.sqlite_run_storage import SqliteRunStorage
from dagster_postgres import PostgresEventLogStorage, PostgresRunStorage
from sqlalchemy.engine import make_url

from orchestrator.defs.bootstrap.moneyflow_history_event_preview import (
    moneyflow_history_proof,
)
from orchestrator.defs.bootstrap.moneyflow_history_plan import _hash
from orchestrator.defs.bootstrap.moneyflow_history_promote import _check_path
from orchestrator.defs.paths import DEFAULT_LAKE_ROOT
from orchestrator.defs.run_contracts.moneyflow import (
    MONEYFLOW_EVENT_DATE_BATCH,
    MONEYFLOW_EVENT_MAX_METADATA_READS,
    MONEYFLOW_EVENT_MAX_SECONDS,
    MONEYFLOW_EVENT_MAX_WRITES,
    MONEYFLOW_HISTORY_SQL_TIMEOUT_SECONDS,
    MoneyflowContractError,
)
from orchestrator.defs.run_contracts.moneyflow_automation import (
    require_moneyflow_automation_contract,
)


def moneyflow_event_instance_identity(instance, lake_root: Path):
    """Do not call get_run_storage_id: that API may INSERT a missing UUID."""
    event, run = instance.event_log_storage, instance.run_storage
    if isinstance(event, PostgresEventLogStorage) and isinstance(
        run, PostgresRunStorage
    ):
        identities = []
        for store in (event, run):
            url = make_url(store.postgres_url)
            if (
                store.should_autocreate_tables
                or url.host not in {"localhost", "127.0.0.1", "::1"}
                or url.database != "goldenshare_dagster"
            ):
                raise MoneyflowContractError("history_event_instance")
            identities.append(
                {
                    "driver": url.drivername,
                    "host": url.host,
                    "port": url.port or 5432,
                    "database": url.database,
                    "user": url.username,
                }
            )
        if identities[0] != identities[1]:
            raise MoneyflowContractError("history_event_instance")
        return {"backend": "postgres", "storage": identities[0]}
    if (
        lake_root != Path(DEFAULT_LAKE_ROOT)
        and isinstance(event, SqliteEventLogStorage)
        and isinstance(run, SqliteRunStorage)
    ):
        paths = (
            Path(event.path_for_shard("index")),
            Path(make_url(run._conn_string).database),
        )
        for path in paths:
            _check_path(path)
            if not path.is_file() or not any(
                root in path.parents
                for root in (Path("/private/tmp"), Path("/tmp").resolve())
            ):
                raise MoneyflowContractError("history_event_instance")
        return {
            "backend": "sqlite",
            "event_path": str(paths[0]),
            "run_path": str(paths[1]),
        }
    raise MoneyflowContractError("history_event_instance")


def _assemble(
    proof, *, staging_root, lake_root, operation_id, identity, contract, dates=None
):
    require_moneyflow_automation_contract(contract)
    entries = proof["entries"]
    if dates is not None:
        if (
            not isinstance(dates, (tuple, list))
            or not dates
            or len(set(dates)) != len(dates)
            or not set(dates).issubset(e["day"] for e in entries)
        ):
            raise MoneyflowContractError("history_event_selection")
        entries = [e for e in entries if e["day"] in dates]
    recent = [
        d for d in proof["recent_check_dates"] if d in {e["day"] for e in entries}
    ]
    total = len(entries) * 3 + len(recent) * 2
    if total > MONEYFLOW_EVENT_MAX_WRITES:
        raise MoneyflowContractError("history_event_write_budget")
    payload = {
        "revision": contract.event_revision,
        "dataset": contract.dataset,
        "cohort_hash": proof["cohort_hash"],
        "cutoff": proof["cutoff"],
        "staging_root": str(staging_root),
        "lake_root": str(lake_root),
        "operation_id": operation_id,
        "instance_identity": identity,
        "controls": proof["controls"],
        "entries": entries,
        "recent_check_dates": recent,
        "total_work_items": total,
        "limits": {
            "date_batch": MONEYFLOW_EVENT_DATE_BATCH,
            "max_work_items": MONEYFLOW_EVENT_MAX_WRITES,
            "seconds": MONEYFLOW_EVENT_MAX_SECONDS,
            "unit_seconds": MONEYFLOW_HISTORY_SQL_TIMEOUT_SECONDS,
            "metadata_reads": MONEYFLOW_EVENT_MAX_METADATA_READS,
        },
    }
    return {**payload, "plan_hash": _hash(payload)}


def build_moneyflow_event_plan(
    *,
    instance,
    staging_root: Path,
    lake_root: Path,
    operation_id: str,
    cutoff: str,
    expected_cohort_hash: str,
    dates=None,
    contract,
):
    require_moneyflow_automation_contract(contract)
    identity = moneyflow_event_instance_identity(instance, lake_root)
    proof = moneyflow_history_proof(
        staging_root=staging_root,
        lake_root=lake_root,
        operation_id=operation_id,
        cutoff=cutoff,
        expected_cohort_hash=expected_cohort_hash,
        contract=contract,
    )
    return _assemble(
        proof,
        staging_root=staging_root,
        lake_root=lake_root,
        operation_id=operation_id,
        identity=identity,
        dates=dates,
        contract=contract,
    )


def validate_moneyflow_event_plan(plan, instance, *, contract, check=lambda: None):
    require_moneyflow_automation_contract(contract)
    if (
        not isinstance(plan, dict)
        or not isinstance(plan.get("entries"), list)
        or not plan["entries"]
    ):
        raise MoneyflowContractError("history_event_plan")
    if (
        plan.get("dataset") != contract.dataset
        or plan.get("revision") != contract.event_revision
    ):
        raise MoneyflowContractError("history_event_dataset")
    try:
        payload = {k: v for k, v in plan.items() if k != "plan_hash"}
        if plan["plan_hash"] != _hash(payload):
            raise MoneyflowContractError("history_event_plan_changed")
        lake = Path(plan["lake_root"])
        if (
            moneyflow_event_instance_identity(instance, lake)
            != plan["instance_identity"]
        ):
            raise MoneyflowContractError("history_event_instance_changed")
        proof = moneyflow_history_proof(
            staging_root=Path(plan["staging_root"]),
            lake_root=lake,
            operation_id=plan["operation_id"],
            cutoff=plan["cutoff"],
            expected_cohort_hash=plan["cohort_hash"],
            check=check,
            contract=contract,
        )
        expected = _assemble(
            proof,
            staging_root=Path(plan["staging_root"]),
            lake_root=lake,
            operation_id=plan["operation_id"],
            identity=plan["instance_identity"],
            dates=[e["day"] for e in plan["entries"]],
            contract=contract,
        )
    except (KeyError, TypeError) as error:
        raise MoneyflowContractError("history_event_plan") from error
    if expected != plan:
        raise MoneyflowContractError("history_event_plan_changed")
