"""Silver retirement results, original scope and the previous-failure startup rule."""

import dagster as dg
import sqlalchemy as sa
from dagster._core.events.log import EventLogEntry
from dagster._core.storage.event_log.schema import SqlEventLogStorageTable as Events
from dagster._serdes import deserialize_value

from orchestrator.defs.asset_guards.stock_period_delivery import native_run_records
from orchestrator.defs.run_contracts.stock_period import digest
from orchestrator.defs.run_contracts.stock_period_delivery import FREQUENCY_TAG
from orchestrator.defs.run_contracts.stock_period_retirement_cleanup import (
    JOB_NAME,
    OP_NAME,
    RESULT_KEY,
    RESULT_VERSION,
    WORK_KEY,
    WORK_VERSION,
)
from orchestrator.defs.run_contracts.stock_period_silver import asset_name
from orchestrator.defs.stock_daily_qfq import (
    gold_stock_daily_qfq_factor_repair_codes_hash as codes_hash,
)


def latest_retirement_result(instance, freq):
    runs = instance.get_run_records(
        filters=dg.RunsFilter(
            job_name=JOB_NAME,
            statuses=[dg.DagsterRunStatus.SUCCESS],
            tags={FREQUENCY_TAG: freq},
        ),
        limit=1,
        order_by="end_time",
        ascending=False,
    )
    return retirement_result(instance, runs[0].dagster_run, freq) if runs else set()


def retirement_result(instance, run, freq):
    asset = dg.AssetKey(asset_name(freq))
    with instance.event_log_storage.index_connection() as con:
        payload = con.execute(
            sa.select(Events.c.event)
            .where(
                Events.c.run_id == run.run_id,
                Events.c.asset_key == asset.to_string(),
                Events.c.dagster_event_type == "ASSET_OBSERVATION",
            )
            .order_by(Events.c.id.desc())
            .limit(1)
        ).scalar_one_or_none()
    if payload is None:
        raise ValueError("period_retirement_result_missing")
    observation = deserialize_value(
        payload, EventLogEntry
    ).dagster_event.event_specific_data.asset_observation
    value = observation.metadata.get(RESULT_KEY)
    if value is None:
        raise ValueError("period_retirement_result_missing")
    result = value.value
    if (
        result.get("version") != RESULT_VERSION
        or result.get("freq") != freq
        or result.get("producer_run_id") != run.run_id
        or observation.asset_key != asset
        or result.get("periods_hash") != digest(result.get("periods", []))
    ):
        raise ValueError("period_retirement_result_scope_invalid")
    for field, hash_field in [
        ("stock_codes", "codes_hash"),
        ("cleared_codes", "cleared_codes_hash"),
    ]:
        codes = result.get(field)
        if (
            not isinstance(codes, list)
            or codes != sorted(set(codes))
            or codes_hash(codes) != result.get(hash_field)
        ):
            raise ValueError("period_retirement_result_codes_invalid")
    return set(result["cleared_codes"])


def failure_origin(instance, run):
    for entry in instance.get_records_for_run(
        run.run_id, of_type=dg.DagsterEventType.STEP_FAILURE
    ).records:
        data = entry.event_log_entry.dagster_event.event_specific_data.user_failure_data
        if data and "original_failed_run_id" in data.metadata:
            return data.metadata["original_failed_run_id"].value
    return run.run_id


def require_previous_retirement_complete(instance, run, config):
    """Only the actual failed task's native rerun may pass an unresolved failure."""
    prior = instance.get_run_records(
        filters=dg.RunsFilter(
            job_name=JOB_NAME,
            statuses=[
                dg.DagsterRunStatus.SUCCESS,
                dg.DagsterRunStatus.FAILURE,
                dg.DagsterRunStatus.CANCELED,
            ],
            tags={FREQUENCY_TAG: config.freq},
        ),
        limit=1,
        order_by="end_time",
        ascending=False,
    )
    if not prior:
        return
    previous = prior[0].dagster_run
    if previous.status == dg.DagsterRunStatus.SUCCESS:
        retirement_result(instance, previous, config.freq)
        return
    original_id = failure_origin(instance, previous)
    original = instance.get_run_by_id(original_id)
    parent = instance.get_run_by_id(run.parent_run_id) if run.parent_run_id else None
    if (
        parent is not None
        and original is not None
        and parent.job_name == JOB_NAME
        and (parent.root_run_id or parent.run_id)
        == (original.root_run_id or original.run_id)
        and parent.run_config == original.run_config == run.run_config
        and failure_origin(instance, parent) == parent.run_id
    ):
        return
    label = "股票复权周线" if config.freq == "week" else "股票复权月线"
    raise dg.Failure(
        description=f"前次{label}退市清理尚未补齐，请先重跑原失败任务：{original_id}",
        metadata={"original_failed_run_id": original_id},
        allow_retries=False,
    )


def parent_retirement_scope(instance, run, config):
    parent = run.parent_run_id
    while parent:
        ancestor = instance.get_run_by_id(parent)
        if ancestor is None:
            raise ValueError("period_retirement_parent_missing")
        if (
            ancestor.job_name != JOB_NAME
            or ancestor.run_config.get("ops", {}).get(OP_NAME, {}).get("config")
            != config.model_dump()
        ):
            raise ValueError("period_retirement_parent_config_mismatch")
        for record in native_run_records(instance, [parent], ["ASSET_OBSERVATION"]):
            observation = record.asset_observation
            if observation.asset_key != dg.AssetKey(asset_name(config.freq)):
                continue
            value = observation.metadata.get(WORK_KEY)
            if value is None or "period" in value.value:
                continue
            plan = value.value
            if (
                plan.get("version") != WORK_VERSION
                or plan.get("producer_run_id") != parent
                or any(plan.get(k) != v for k, v in config.model_dump().items())
                or plan["periods"] != sorted(set(plan["periods"]))
                or plan.get("periods_hash") != digest(plan["periods"])
            ):
                raise ValueError("period_retirement_parent_scope_invalid")
            return plan["periods"]
        parent = ancestor.parent_run_id
    return []
