"""Read complete native Raw deliveries by explicit run set, without private receipts."""

from datetime import datetime
from zoneinfo import ZoneInfo

import dagster as dg
import sqlalchemy as sa
from dagster._core.event_api import EventLogRecord
from dagster._core.events.log import EventLogEntry
from dagster._core.storage.event_log.schema import SqlEventLogStorageTable as Events
from dagster._serdes import deserialize_value

from orchestrator.defs.asset_guards.stock_period_silver_readiness import raw_check_names
from orchestrator.defs.run_contracts.stock_period_delivery import (
    COMPLETION_KEY,
    FILE_DELIVERY_KEY,
    WORK_KEY,
    iso_business_date,
    validate_delivery_completion,
    validate_delivery_ref,
)
from orchestrator.defs.run_contracts.stock_period_silver import raw_path
from orchestrator.defs.stock_period_checks import verify_period_materialization_metadata


def native_run_records(instance, run_ids, event_types):
    """One indexed event query for an explicit set; never per-file history reads."""
    storage = instance.event_log_storage
    with storage.index_connection() as connection:
        rows = (
            connection.execute(
                sa.select(Events.c.id, Events.c.event)
                .where(
                    Events.c.run_id.in_(sorted(set(run_ids))),
                    Events.c.dagster_event_type.in_(event_types),
                )
                .order_by(Events.c.id)
            )
            .mappings()
            .all()
        )
    return [
        EventLogRecord(row["id"], deserialize_value(row["event"], EventLogEntry))
        for row in rows
    ]


def read_completions(instance, references, *, root):
    references = [validate_delivery_ref(reference) for reference in references]
    if not references:
        return {}
    run_ids = sorted({reference["producer_run_id"] for reference in references})
    runs = instance.get_runs(filters=dg.RunsFilter(run_ids=run_ids), limit=len(run_ids))
    if len(runs) != len(run_ids) or any(
        run.status != dg.DagsterRunStatus.SUCCESS for run in runs
    ):
        raise ValueError("period_delivery_run_not_successful")
    records = native_run_records(
        instance,
        run_ids,
        [
            "ASSET_OBSERVATION",
            "ASSET_MATERIALIZATION",
            "ASSET_CHECK_EVALUATION",
        ],
    )
    result = {}
    for reference in references:
        run_id, freq = reference["producer_run_id"], reference["freq"]
        asset = dg.AssetKey(f"raw_tushare_stk_period_bar_adj_{freq}")
        scoped = [
            record for record in records if record.event_log_entry.run_id == run_id
        ]
        observations = [
            record
            for record in scoped
            if record.asset_observation is not None
            and record.asset_observation.asset_key == asset
        ]
        completions = [
            record
            for record in observations
            if COMPLETION_KEY in record.asset_observation.metadata
        ]
        matching = []
        for record in completions:
            value = record.asset_observation.metadata[COMPLETION_KEY].value
            if validate_delivery_completion(value, freq) == reference:
                matching.append((record, value))
        if len(matching) != 1:
            raise ValueError("period_delivery_completion_missing")
        completion_record, completion = matching[0]
        plans = [
            record
            for record in observations
            if WORK_KEY in record.asset_observation.metadata
            and record.asset_observation.metadata[WORK_KEY].value.get(
                "upstream_batch_id"
            )
            == reference["upstream_batch_id"]
        ]
        if len(plans) != 1:
            raise ValueError("period_delivery_work_missing")
        plan = plans[0].asset_observation.metadata[WORK_KEY].value
        if (
            plan.get("version") != "stock-period-work@1"
            or any(plan.get(key) != value for key, value in reference.items())
            or any(
                plan.get(key) != completion[key]
                for key in ("kind", "business_date", "periods", "periods_hash")
            )
        ):
            raise ValueError("period_delivery_work_mismatch")
        mats = [
            record
            for record in scoped
            if record.asset_materialization is not None
            and record.asset_materialization.asset_key == asset
        ]
        items = {}
        completed_day = (
            datetime.fromtimestamp(
                completion_record.event_log_entry.timestamp, ZoneInfo("Asia/Shanghai")
            )
            .date()
            .isoformat()
        )
        checks = {}
        for record in scoped:
            event = record.event_log_entry.dagster_event
            if event.event_type_value == "ASSET_CHECK_EVALUATION":
                evaluation = event.event_specific_data
                if evaluation.asset_key == asset:
                    checks[(evaluation.partition, evaluation.check_name)] = evaluation
        for record in mats:
            mat = record.asset_materialization
            period, metadata = mat.partition, mat.metadata
            value = {
                key: getattr(item, "value", None) for key, item in metadata.items()
            }.get
            if value(FILE_DELIVERY_KEY) != reference:
                continue
            if (
                period in items
                or not plans[0].storage_id
                < record.storage_id
                < completion_record.storage_id
            ):
                raise ValueError("period_delivery_file_scope_invalid")
            version, rows = (
                value("goldenshare/period_file_version"),
                value("dagster/row_count"),
            )
            verify_period_materialization_metadata(
                record,
                period,
                raw_path(root, freq, period),
                version=version,
                rows=rows,
                asset_key=asset,
            )
            source_asof = value("goldenshare/source_asof")
            if source_asof is None:
                if rows != 0:
                    raise ValueError("period_delivery_source_asof_missing")
            elif iso_business_date(source_asof) > completed_day:
                raise ValueError("period_delivery_source_asof_future")
            if value("goldenshare/business_date") != completion["business_date"]:
                raise ValueError("period_delivery_business_date_mismatch")
            for name in raw_check_names(freq):
                evaluation = checks.get((period, name))
                target = evaluation.target_materialization_data if evaluation else None
                if (
                    evaluation is None
                    or not evaluation.passed
                    or not evaluation.blocking
                    or target is None
                    or target.storage_id != record.storage_id
                    or target.run_id != run_id
                    or target.timestamp != record.event_log_entry.timestamp
                ):
                    raise ValueError("period_delivery_checks_incomplete")
            items[(freq, period)] = {
                "freq": freq,
                "period": period,
                "target": str(raw_path(root, freq, period)),
                "version": version,
                "rows": rows,
                "source_asof": source_asof,
                "asof": max(
                    completion["business_date"],
                    source_asof or completion["business_date"],
                ),
            }
        if sorted(period for _, period in items) != completion["periods"]:
            raise ValueError("period_delivery_files_incomplete")
        result[reference["upstream_batch_id"]] = {
            "reference": reference,
            "items": items,
            "asof": completion["business_date"],
            "completion": completion,
        }
    return result


def read_completion(instance, reference, *, root):
    return read_completions(instance, [reference], root=root)[
        reference["upstream_batch_id"]
    ]


def silver_completion_consumed(instance, reference, periods, *, root, business_date):
    """A real SUCCESS and original bound checks close consumption, including manual full reruns."""
    from orchestrator.defs.run_contracts.stock_period_delivery import (
        SILVER_SCOPE_KEY,
        SOURCE_BATCH_TAG,
        silver_update_scope,
    )
    from orchestrator.defs.run_contracts.stock_period_silver import (
        asset_name,
        check_names,
        target_path,
    )

    freq = reference["freq"]
    asset = dg.AssetKey(asset_name(freq))
    runs = instance.get_runs(
        filters=dg.RunsFilter(
            job_name=asset_name(freq) + "_update_job",
            statuses=[dg.DagsterRunStatus.SUCCESS],
            tags={SOURCE_BATCH_TAG: reference["upstream_batch_id"]},
        ),
        limit=1,
    )
    if not runs:
        return False
    run = runs[0]
    records = native_run_records(
        instance,
        [run.run_id],
        ["ASSET_OBSERVATION", "ASSET_MATERIALIZATION", "ASSET_CHECK_EVALUATION"],
    )
    scopes = [
        record.asset_observation.metadata[SILVER_SCOPE_KEY].value
        for record in records
        if record.asset_observation is not None
        and record.asset_observation.asset_key == asset
        and SILVER_SCOPE_KEY in record.asset_observation.metadata
    ]
    complete = [scope for scope in scopes if scope.get("phase") == "files_complete"]
    if len(complete) != 1:
        raise ValueError("silver_consumption_scope_missing")
    scope = complete[0]
    expected = silver_update_scope(
        run.run_id, freq, business_date, reference, periods, phase="files_complete"
    )
    if (
        scope != expected
        or silver_update_scope(
            run.run_id, freq, business_date, reference, periods, phase="planned"
        )
        not in scopes
    ):
        raise ValueError("silver_consumption_scope_mismatch")
    mats = {
        record.asset_materialization.partition: record
        for record in records
        if record.asset_materialization is not None
        and record.asset_materialization.asset_key == asset
    }
    checks = {}
    for record in records:
        event = record.event_log_entry.dagster_event
        if event.event_type_value == "ASSET_CHECK_EVALUATION":
            evaluation = event.event_specific_data
            if evaluation.asset_key == asset:
                checks[(evaluation.partition, evaluation.check_name)] = evaluation
    if sorted(mats) != periods:
        raise ValueError("silver_consumption_files_incomplete")
    for period, record in mats.items():
        metadata = record.asset_materialization.metadata
        verify_period_materialization_metadata(
            record,
            period,
            target_path(root, freq, period),
            version=getattr(
                metadata.get("goldenshare/period_file_version"), "value", None
            ),
            asset_key=asset,
        )
        if (
            getattr(metadata.get("goldenshare/silver_execution_id"), "value", None)
            != run.run_id
        ):
            raise ValueError("silver_consumption_run_mismatch")
        for name in check_names(freq):
            evaluation = checks.get((period, name))
            target = evaluation.target_materialization_data if evaluation else None
            if (
                evaluation is None
                or not evaluation.passed
                or not evaluation.blocking
                or target is None
                or target.storage_id != record.storage_id
                or target.run_id != run.run_id
                or target.timestamp != record.event_log_entry.timestamp
            ):
                raise ValueError("silver_consumption_checks_incomplete")
    return True
