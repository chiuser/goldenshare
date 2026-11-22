import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import dagster as dg
import sqlalchemy as sa
from dagster._core.event_api import EventLogRecord
from dagster._core.events.log import EventLogEntry
from dagster._core.storage.asset_check_execution_record import AssetCheckExecutionRecord
from dagster._core.storage.event_log.schema import (
    AssetCheckExecutionsTable as Checks,
)
from dagster._core.storage.event_log.schema import (
    SqlEventLogStorageTable as Events,
)
from dagster._core.storage.event_log.sql_event_log import SqlEventLogStorage
from dagster._serdes import deserialize_value
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import SQLAlchemyError

from orchestrator.defs.daily_data_audit.registry import (
    DAILY_SNAPSHOTS,
    DELIVERY_DATE_FIELDS,
    FIXED_SNAPSHOTS,
    OUTSIDE_LOCAL,
    SILVER_INDEX_PERIOD,
    AuditTarget,
)

SUMMARY_JOB = "daily_data_audit_summary_job"
SUMMARY_META = "data_audit_summary"
BUSINESS_DATE_TAG = "audit/business_date"
SHANGHAI = ZoneInfo("Asia/Shanghai")
logger = logging.getLogger(__name__)


@dataclass
class DeliveryEvidence:
    materialization: EventLogRecord | None = None
    checks: dict[str, AssetCheckExecutionRecord] = field(default_factory=dict)


def metadata(record) -> dict:
    return {
        name.removeprefix("goldenshare/"): item.value
        for name, item in record.metadata.items()
    }


def _delivery_date_matches(connection, target):
    path = (
        "dagster_event",
        "event_specific_data",
        "materialization",
        "metadata_entries",
    )
    if connection.dialect.name == "postgresql":
        entries = sa.cast(Events.c.event, JSONB)[path]
        item = sa.func.jsonb_array_elements(entries).column_valued("entry")
        label = sa.cast(item, JSONB)["label"].as_string()
        value = sa.cast(item, JSONB)[("entry_data", "text")].as_string()
    else:
        fields = sa.func.json_each(Events.c.event, "$." + ".".join(path)).table_valued(
            "value"
        )
        label = sa.func.json_extract(fields.c.value, "$.label")
        value = sa.func.json_extract(fields.c.value, "$.entry_data.text")
    names = (
        *DELIVERY_DATE_FIELDS,
        *(f"goldenshare/{key}" for key in DELIVERY_DATE_FIELDS),
    )
    return sa.exists(
        sa.select(1)
        .where(
            label.in_(names),
            sa.or_(
                target.c.trade_date_only.is_(False),
                label.in_(("trade_date", "goldenshare/trade_date")),
            ),
            sa.func.replace(value, "-", "") == sa.func.replace(target.c.as_of, "-", ""),
        )
        .correlate(Events, target)
    )


def load_evidence(
    instance: dg.DagsterInstance,
    targets: tuple[AuditTarget, ...],
    day: date,
    observed_at: datetime,
) -> dict[str, DeliveryEvidence]:
    """Two reads across the exact asset/partition pairs. No reads of asset files."""
    storage = instance.event_log_storage
    if not isinstance(storage, SqlEventLogStorage):
        raise TypeError("data audit requires SQL event storage")
    eligible = [
        target
        for target in targets
        if target.asset_key not in OUTSIDE_LOCAL
        and (
            target.partition is not None
            or target.asset_key in FIXED_SNAPSHOTS
            or target.exact_as_of
            and target.frequency == "日更"
        )
    ]
    if not eligible:
        return {}
    keys = {dg.AssetKey(item.asset_key).to_string(): item for item in eligible}
    cutoff = observed_at.astimezone(UTC).replace(tzinfo=None)
    next_midnight = datetime.combine(day + timedelta(days=1), time.min, SHANGHAI)
    midnight = (
        datetime.combine(day, time.min, SHANGHAI).astimezone(UTC).replace(tzinfo=None)
    )
    snapshot_cutoff = next_midnight.astimezone(UTC).replace(tzinfo=None)
    scoped = (
        sa.values(
            sa.column("asset_key", sa.Text),
            sa.column("partition", sa.Text),
            sa.column("cutoff", sa.DateTime),
            sa.column("as_of", sa.Text),
            sa.column("day_snapshot", sa.Boolean),
            sa.column("trade_date_only", sa.Boolean),
        )
        .data(
            [
                (
                    key,
                    target.partition,
                    min(cutoff, snapshot_cutoff)
                    if target.asset_key in FIXED_SNAPSHOTS
                    else cutoff,
                    target.expected_date.isoformat()
                    if target.exact_as_of and target.expected_date
                    else None,
                    target.asset_key in DAILY_SNAPSHOTS,
                    target.asset_key in SILVER_INDEX_PERIOD,
                )
                for key, target in keys.items()
            ]
        )
        .cte("audit_targets")
    )
    evidence = {}
    with storage.index_connection() as connection:
        last_event = (
            sa.select(Events.c.id)
            .where(
                Events.c.asset_key == scoped.c.asset_key,
                Events.c.partition.is_not_distinct_from(scoped.c.partition),
                Events.c.dagster_event_type == "ASSET_MATERIALIZATION",
                Events.c.timestamp <= scoped.c.cutoff,
                sa.or_(
                    scoped.c.as_of.is_(None),
                    _delivery_date_matches(connection, scoped),
                    sa.and_(
                        scoped.c.day_snapshot,
                        Events.c.timestamp >= midnight,
                        Events.c.timestamp < snapshot_cutoff,
                    ),
                ),
            )
            .order_by(Events.c.id.desc())
            .limit(1)
            .correlate(scoped)
            .scalar_subquery()
        )
        materializations = sa.select(
            scoped.c.asset_key, scoped.c.partition, Events.c.id, Events.c.event
        ).select_from(scoped.outerjoin(Events, Events.c.id == last_event))
        for row in connection.execute(materializations).mappings():
            key = keys[row["asset_key"]].asset_key
            record = (
                None
                if row["id"] is None
                else EventLogRecord(
                    row["id"], deserialize_value(row["event"], EventLogEntry)
                )
            )
            evidence[key] = DeliveryEvidence(record)
        check_scope = [
            (
                key,
                target.partition,
                name,
                evidence[target.asset_key].materialization.storage_id,
                evidence[target.asset_key].materialization.run_id
                if target.asset_key in SILVER_INDEX_PERIOD
                else None,
            )
            for key, target in keys.items()
            if evidence[target.asset_key].materialization is not None
            for name in target.check_names
        ]
        if not check_scope:
            return evidence
        scope = (
            sa.values(
                sa.column("asset_key", sa.Text),
                sa.column("partition", sa.Text),
                sa.column("check_name", sa.Text),
                sa.column("materialization_id", sa.BigInteger),
                sa.column("producer_run_id", sa.Text),
            )
            .data(check_scope)
            .cte("audit_checks")
        )
        last_check = (
            sa.select(Checks.c.id)
            .where(
                Checks.c.asset_key == scope.c.asset_key,
                Checks.c.check_name == scope.c.check_name,
                Checks.c.materialization_event_storage_id == scope.c.materialization_id,
                sa.or_(
                    scope.c.producer_run_id.is_(None),
                    Checks.c.run_id == scope.c.producer_run_id,
                ),
                # Legacy checks can omit their own partition. The native
                # target still points to the exact partitioned publication.
                sa.or_(
                    Checks.c.partition.is_(None),
                    Checks.c.partition == scope.c.partition,
                ),
                Checks.c.execution_status.in_(("SUCCEEDED", "FAILED")),
                Checks.c.evaluation_event_timestamp <= cutoff,
            )
            .order_by(Checks.c.evaluation_event_storage_id.desc())
            .limit(1)
            .correlate(scope)
            .scalar_subquery()
        )
        query = sa.select(Checks).select_from(
            scope.join(Checks, Checks.c.id == last_check)
        )
        try:
            evaluations = connection.execute(query).mappings().all()
        except SQLAlchemyError:
            logger.exception("无法读取本批 Check 记录")
            return evidence
        for row in evaluations:
            target = keys[row["asset_key"]]
            check_key = dg.AssetCheckKey(
                dg.AssetKey(target.asset_key), row["check_name"]
            )
            record = AssetCheckExecutionRecord.from_db_row(row, check_key)
            current = evidence[target.asset_key]
            reference = (
                record.evaluation.target_materialization_data
                if record.evaluation
                else None
            )
            if (
                reference
                and reference.run_id == current.materialization.run_id
                and reference.storage_id == current.materialization.storage_id
            ):
                current.checks[row["check_name"]] = record
    return evidence


def read_summary(instance: dg.DagsterInstance, business_date: date) -> dict | None:
    records = instance.get_run_records(
        filters=dg.RunsFilter(
            job_name=SUMMARY_JOB,
            tags={BUSINESS_DATE_TAG: business_date.isoformat()},
            statuses=[dg.DagsterRunStatus.SUCCESS],
        ),
        limit=1,
    )
    if not records:
        return None
    records = instance.get_records_for_run(
        records[0].dagster_run.run_id,
        of_type=dg.DagsterEventType.STEP_OUTPUT,
        limit=1,
    ).records
    if not records:
        return None
    entry = records[0].event_log_entry.dagster_event.step_output_data.metadata.get(
        SUMMARY_META
    )
    if (
        entry
        and entry.value["schema_version"] == 1
        and entry.value["business_date"] == business_date.isoformat()
    ):
        return entry.value
    return None


def get_completeness(
    instance: dg.DagsterInstance, scope: dict, version: dict
) -> dict | None:
    """Return only the published result for the caller's exact input and target versions."""
    if not version.get("target_version") or not version.get("rule_version"):
        return None
    summary = read_summary(instance, date.fromisoformat(scope["business_date"]))
    if summary is not None:
        for row in summary["rows"]:
            if row["scope"] == scope and row["version"] == version:
                return row["completeness"]
    return None
