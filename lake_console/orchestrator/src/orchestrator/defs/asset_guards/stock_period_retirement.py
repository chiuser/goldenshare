"""Read exact retirement results and original native work scopes, never price history."""

import dagster as dg
import sqlalchemy as sa
from dagster._core.events.log import EventLogEntry
from dagster._core.storage.event_log.schema import AssetCheckExecutionsTable as Checks
from dagster._core.storage.event_log.schema import SqlEventLogStorageTable as Events
from dagster._serdes import deserialize_value

from orchestrator.defs.asset_guards.stock_period_delivery import native_run_records
from orchestrator.defs.run_contracts.stock_period import digest
from orchestrator.defs.run_contracts.stock_period_delivery import (
    FREQUENCY_TAG,
    WORK_KEY,
)
from orchestrator.defs.run_contracts.stock_period_retirement_cleanup import (
    JOB_NAME,
    retirement_result_check_name,
)
from orchestrator.defs.stock_daily_qfq import (
    gold_stock_daily_qfq_factor_repair_codes_hash,
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
    if not runs:
        return set()
    run = runs[0].dagster_run
    asset = dg.AssetKey(f"raw_tushare_stk_period_bar_adj_{freq}")
    name = retirement_result_check_name(freq)
    with instance.event_log_storage.index_connection() as con:
        payload = con.execute(
            sa.select(Events.c.event)
            .select_from(
                Checks.join(Events, Checks.c.evaluation_event_storage_id == Events.c.id)
            )
            .where(
                Checks.c.run_id == run.run_id,
                Checks.c.asset_key == asset.to_string(),
                Checks.c.check_name == name,
                Events.c.run_id == run.run_id,
                Events.c.dagster_event_type == "ASSET_CHECK_EVALUATION",
            )
            .order_by(Events.c.id.desc())
            .limit(1)
        ).scalar_one_or_none()
    if payload is None:
        raise ValueError("period_retirement_result_missing")
    evaluation = deserialize_value(
        payload, EventLogEntry
    ).dagster_event.event_specific_data
    metadata = {key: value.value for key, value in evaluation.metadata.items()}
    if (
        not evaluation.passed
        or not evaluation.blocking
        or evaluation.asset_key != asset
        or evaluation.check_name != name
    ):
        raise ValueError("period_retirement_result_invalid")
    if (
        metadata.get("version") != "stock-period-result@1"
        or metadata.get("freq") != freq
        or metadata.get("kind") != "retirement_cleanup"
        or metadata.get("producer_run_id") != run.run_id
    ):
        raise ValueError("period_retirement_result_scope_invalid")
    for field, hash_field in [
        ("stock_codes", "codes_hash"),
        ("cleared_codes", "cleared_codes_hash"),
    ]:
        codes = metadata.get(field)
        if (
            not isinstance(codes, list)
            or codes != sorted(set(codes))
            or gold_stock_daily_qfq_factor_repair_codes_hash(codes)
            != metadata.get(hash_field)
        ):
            raise ValueError("period_retirement_result_codes_invalid")
    return set(metadata["cleared_codes"])


def parent_retirement_scope(instance, run, config):
    parent = run.parent_run_id
    while parent:
        ancestor = instance.get_run_by_id(parent)
        if ancestor is None:
            raise ValueError("period_retirement_parent_missing")
        observations = native_run_records(instance, [parent], ["ASSET_OBSERVATION"])
        for record in observations:
            observation = record.asset_observation
            if observation.asset_key != dg.AssetKey(
                f"raw_tushare_stk_period_bar_adj_{config.freq}"
            ):
                continue
            value = observation.metadata.get(WORK_KEY)
            if value is None:
                continue
            plan = value.value
            if (
                plan.get("kind") != "retirement_cleanup"
                or plan.get("business_date") != config.business_date
                or plan.get("freq") != config.freq
                or plan.get("codes_hash") != config.codes_hash
            ):
                continue
            if (
                plan.get("version") != "stock-period-work@1"
                or plan.get("producer_run_id") != parent
                or plan.get("stock_codes") != config.stock_codes
                or plan["periods"] != sorted(set(plan["periods"]))
                or plan.get("periods_hash") != digest(plan["periods"])
            ):
                raise ValueError("period_retirement_parent_scope_invalid")
            return plan["periods"]
        parent = ancestor.parent_run_id
    return []
