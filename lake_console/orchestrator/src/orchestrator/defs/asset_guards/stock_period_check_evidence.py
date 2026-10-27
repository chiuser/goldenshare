"""Read period checks in evaluation order, with both stored event copies bound."""

import dagster as dg
import sqlalchemy as sa
from dagster._core.event_api import EventLogRecord
from dagster._core.events.log import EventLogEntry
from dagster._core.storage.asset_check_execution_record import AssetCheckExecutionRecord
from dagster._core.storage.event_log.schema import (
    AssetCheckExecutionsTable as Checks,
)
from dagster._core.storage.event_log.schema import SqlEventLogStorageTable as Events
from dagster._core.storage.event_log.sql_event_log import SqlEventLogStorage
from dagster._serdes import deserialize_value

from orchestrator.defs.run_contracts.stock_monthly import (
    StockMonthlySource,
    monthly_check_names,
)
from orchestrator.defs.run_contracts.stock_period_silver import asset_name, check_names
from orchestrator.defs.run_contracts.stock_weekly import (
    StockWeeklySource,
    weekly_check_names,
)


def latest_completed_checks_query(
    *, asset_check_names, partition_keys, before_event_id=None
):
    """Build one bounded query; no target/success filter may precede ranking."""
    allowed = {
        dg.AssetKey("raw_tushare_stk_period_bar_adj_week"): weekly_check_names(
            StockWeeklySource.PRIMARY_ADJUSTED
        ),
        dg.AssetKey("raw_tushare_stk_period_bar_adj_month"): monthly_check_names(
            StockMonthlySource.PRIMARY_ADJUSTED
        ),
        dg.AssetKey(asset_name("week")): check_names("week"),
        dg.AssetKey(asset_name("month")): check_names("month"),
    }
    if before_event_id is not None and (
        type(before_event_id) is not int or before_event_id <= 0
    ):
        raise ValueError("period_check_evidence_cutoff_invalid")
    scope = []
    for asset, names in asset_check_names.items():
        if asset not in allowed or not set(names) <= set(allowed[asset]):
            raise ValueError("period_check_evidence_scope_invalid")
        if names:
            scope.append(
                sa.and_(
                    Checks.c.asset_key == asset.to_string(),
                    Checks.c.check_name.in_(tuple(names)),
                )
            )
    groups = (Checks.c.asset_key, Checks.c.check_name, Checks.c.partition)
    event_id = Checks.c.evaluation_event_storage_id
    candidates = (
        sa.select(
            Checks.c.id,
            *groups,
            event_id,
            sa.func.sum(
                sa.case((sa.or_(event_id.is_(None), event_id <= 0), 1), else_=0)
            )
            .over(partition_by=groups)
            .label("invalid_id_count"),
            sa.func.count()
            .over(partition_by=(*groups, event_id))
            .label("same_event_count"),
        )
        .where(
            sa.or_(*scope) if scope and partition_keys else sa.false(),
            Checks.c.partition.in_(tuple(partition_keys)),
            Checks.c.execution_status.in_(("SUCCEEDED", "FAILED")),
        )
        .subquery()
    )
    groups = tuple(
        candidates.c[name] for name in ("asset_key", "check_name", "partition")
    )
    flagged = sa.select(
        candidates,
        sa.func.max(sa.case((candidates.c.same_event_count > 1, 1), else_=0))
        .over(partition_by=groups)
        .label("duplicate_id_count"),
    ).subquery()
    groups = tuple(flagged.c[name] for name in ("asset_key", "check_name", "partition"))
    eligible = (
        sa.select(flagged)
        .where(
            sa.true()
            if before_event_id is None
            else sa.or_(
                flagged.c.evaluation_event_storage_id < before_event_id,
                flagged.c.evaluation_event_storage_id.is_(None),
            )
        )
        .subquery()
    )
    groups = tuple(
        eligible.c[name] for name in ("asset_key", "check_name", "partition")
    )
    ranked = sa.select(
        eligible,
        sa.func.row_number()
        .over(
            partition_by=groups,
            order_by=(
                eligible.c.evaluation_event_storage_id.desc().nulls_first(),
            ),
        )
        .label("position"),
    ).subquery()
    evaluation_events = Events.alias("evaluation_events")
    bound_events = Events.alias("bound_events")
    return (
        sa.select(
            Checks,
            ranked.c.invalid_id_count,
            ranked.c.duplicate_id_count,
            evaluation_events.c.id.label("actual_evaluation_id"),
            evaluation_events.c.dagster_event_type.label("actual_evaluation_type"),
            evaluation_events.c.event.label("actual_evaluation_event"),
            bound_events.c.id.label("bound_id"),
            bound_events.c.dagster_event_type.label("bound_type"),
            bound_events.c.event.label("bound_event"),
        )
        .select_from(
            Checks.join(ranked, Checks.c.id == ranked.c.id)
            .outerjoin(
                evaluation_events,
                Checks.c.evaluation_event_storage_id == evaluation_events.c.id,
            )
            .outerjoin(
                bound_events,
                Checks.c.materialization_event_storage_id == bound_events.c.id,
            )
        )
        .where(ranked.c.position == 1)
        .subquery()
    )


def decode_completed_check_row(row, *, asset_key, check_name, partition_key):
    """Return (SDK record, actual evaluation ID, bound materialization)."""
    if row["invalid_id_count"] or row["duplicate_id_count"]:
        raise ValueError("period_check_evidence_event_id_invalid")
    event_id = row["evaluation_event_storage_id"]
    if (
        type(event_id) is not int
        or event_id <= 0
        or row["actual_evaluation_id"] != event_id
        or row["actual_evaluation_type"] != "ASSET_CHECK_EVALUATION"
        or row["actual_evaluation_event"] is None
        or row["asset_key"] != asset_key.to_string()
        or row["check_name"] != check_name
        or row["partition"] != partition_key
    ):
        raise ValueError("period_check_evidence_identity_invalid")
    record = AssetCheckExecutionRecord.from_db_row(
        row, dg.AssetCheckKey(asset_key, check_name)
    )
    actual = deserialize_value(row["actual_evaluation_event"], EventLogEntry)
    evaluation = record.evaluation
    if (
        record.event != actual
        or actual.dagster_event_type != dg.DagsterEventType.ASSET_CHECK_EVALUATION
        or actual.run_id != record.run_id
        or evaluation.asset_key != asset_key
        or evaluation.check_name != check_name
        or evaluation.partition != partition_key
        or type(evaluation.passed) is not bool
        or evaluation.passed != (record.status.value == "SUCCEEDED")
    ):
        raise ValueError("period_check_evidence_result_invalid")
    target = evaluation.target_materialization_data
    if row["materialization_event_storage_id"] != (
        target.storage_id if target else None
    ):
        raise ValueError("period_check_evidence_target_invalid")
    bound = None
    if row["bound_id"] is not None:
        if row["bound_type"] != "ASSET_MATERIALIZATION" or row["bound_event"] is None:
            raise ValueError("period_check_evidence_target_invalid")
        bound = EventLogRecord(
            row["bound_id"], deserialize_value(row["bound_event"], EventLogEntry)
        )
        mat = bound.asset_materialization
        if (
            mat is None
            or mat.asset_key != asset_key
            or mat.partition != partition_key
            or target is None
            or target.storage_id != bound.storage_id
            or target.run_id != bound.event_log_entry.run_id
            or target.timestamp != bound.timestamp
        ):
            raise ValueError("period_check_evidence_target_invalid")
    return record, event_id, bound


def read_latest_completed_checks(
    instance, *, asset_key, check_names, partition_key, before_event_id=None
):
    storage = instance.event_log_storage
    if not isinstance(storage, SqlEventLogStorage):
        raise TypeError("period_check_storage_unsupported")
    if not check_names:
        return {}
    selected = latest_completed_checks_query(
        asset_check_names={asset_key: tuple(check_names)},
        partition_keys=(partition_key,),
        before_event_id=before_event_id,
    )
    with storage.index_connection() as connection:
        rows = connection.execute(sa.select(selected)).mappings().all()
    return {
        row["check_name"]: decode_completed_check_row(
            row,
            asset_key=asset_key,
            check_name=row["check_name"],
            partition_key=partition_key,
        )
        for row in rows
    }
