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

from orchestrator.defs.catalog.lake_assets import (
    SILVER_STOCK_DAILY_CHECKS,
    get_lake_asset_catalog_entry,
)
from orchestrator.defs.checks.daily_audit_coverage import stat_version
from orchestrator.defs.daily_data_audit.registry import (
    DAILY_SNAPSHOTS,
    DELIVERY_DATE_FIELDS,
    FIXED_SNAPSHOTS,
    LATE_STOCK_DAILY_COVERAGE_CHECKS,
    OUTSIDE_LOCAL,
    SILVER_INDEX_PERIOD,
    AuditTarget,
)
from orchestrator.defs.paths import silver_stock_daily_path

STOCK_DAILY = "silver_stock_daily"
SUMMARY_JOB = "daily_data_audit_summary_job"
SUMMARY_META = "data_audit_summary"
INDEX_MINUTE_JOB = "daily_data_audit_index_minute_job"
INDEX_MINUTE_META = "data_audit_result"
AUDIT_ASSET_TAG = "audit/asset_key"
AUDIT_PUBLICATION_TAG = "audit/target_publication_run_id"
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


def _publication_at_date(connection, scoped, midnight, snapshot_cutoff):
    return sa.and_(
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


def _audit_day_bounds(day):
    start = datetime.combine(day, time.min, SHANGHAI).astimezone(UTC).replace(tzinfo=None)
    return start, start + timedelta(days=1)


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
    midnight, snapshot_cutoff = _audit_day_bounds(day)
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
            .where(_publication_at_date(connection, scoped, midnight, snapshot_cutoff))
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
                    Checks.c.check_name.in_(tuple(LATE_STOCK_DAILY_COVERAGE_CHECKS.values())),
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


def find_audit_changes(instance, targets, rows, day, observed_at):
    """Read only changed asset keys and observation times from the event index."""
    cutoff = observed_at.astimezone(UTC).replace(tzinfo=None)
    midnight, snapshot_cutoff = _audit_day_bounds(day)
    day_scope = []
    check_scope = []
    keys = {}
    for target in targets:
        asset = target.asset_key
        row = rows[asset]
        partition = row["scope"]["partition_key"]
        expected = row["update"]["expected_date"]
        if asset in OUTSIDE_LOCAL or (
            partition is None and asset not in FIXED_SNAPSHOTS
            and not (target.exact_as_of and target.frequency == "日更")
        ):
            continue
        native_key = dg.AssetKey(asset).to_string()
        keys[native_key] = asset
        day_scope.append((
            native_key, partition,
            min(cutoff, snapshot_cutoff) if asset in FIXED_SNAPSHOTS else cutoff,
            expected if target.exact_as_of else None,
            asset in DAILY_SNAPSHOTS, asset in SILVER_INDEX_PERIOD,
            datetime.fromisoformat(row["observed_at"]).astimezone(UTC).replace(tzinfo=None),
        ))
        check_scope.extend((native_key, name) for name in target.check_names)
    if not day_scope:
        return {}
    scope = sa.values(
        sa.column("asset_key", sa.Text), sa.column("partition", sa.Text),
        sa.column("cutoff", sa.DateTime), sa.column("as_of", sa.Text),
        sa.column("day_snapshot", sa.Boolean), sa.column("trade_date_only", sa.Boolean),
        sa.column("observed_at", sa.DateTime),
    ).data(day_scope).cte("audit_refresh_scope")
    with instance.event_log_storage.index_connection() as connection:
        latest = (
            sa.select(Events.c.id)
            .where(_publication_at_date(connection, scope, midnight, snapshot_cutoff))
            .order_by(Events.c.id.desc()).limit(1).correlate(scope).scalar_subquery()
        )
        publications = sa.select(
            scope.c.asset_key, scope.c.observed_at, scope.c.partition,
            scope.c.trade_date_only, Events.c.id, Events.c.timestamp, Events.c.run_id,
        ).select_from(scope.join(Events, Events.c.id == latest)).cte("audit_refresh_publications")
        changes = sa.select(
            publications.c.asset_key, publications.c.timestamp.label("changed_at"),
        ).where(publications.c.timestamp > publications.c.observed_at)
        if check_scope:
            names = sa.values(
                sa.column("asset_key", sa.Text), sa.column("check_name", sa.Text),
            ).data(check_scope).cte("audit_refresh_checks")
            checks = sa.select(
                publications.c.asset_key, Checks.c.evaluation_event_timestamp.label("changed_at"),
            ).select_from(publications.join(names, names.c.asset_key == publications.c.asset_key).join(
                Checks,
                sa.and_(
                    Checks.c.asset_key == names.c.asset_key,
                    Checks.c.check_name == names.c.check_name,
                    Checks.c.materialization_event_storage_id == publications.c.id,
                    sa.or_(Checks.c.partition.is_(None), Checks.c.partition == publications.c.partition),
                    sa.or_(
                        publications.c.trade_date_only.is_(False),
                        Checks.c.run_id == publications.c.run_id,
                        Checks.c.check_name.in_(tuple(LATE_STOCK_DAILY_COVERAGE_CHECKS.values())),
                    ),
                ),
            )).where(
                Checks.c.execution_status.in_(("SUCCEEDED", "FAILED")),
                Checks.c.evaluation_event_timestamp > publications.c.observed_at,
                Checks.c.evaluation_event_timestamp <= cutoff,
            )
            changes = changes.union_all(checks)
        hits = changes.subquery()
        query = sa.select(hits.c.asset_key, sa.func.max(hits.c.changed_at)).group_by(hits.c.asset_key)
        return {
            keys[key]: timestamp.replace(tzinfo=UTC).timestamp()
            for key, timestamp in connection.execute(query)
        }


def verified_stock_daily(instance, root, day):
    """Return the published daily quote file only when its own Checks passed."""
    path = silver_stock_daily_path(root, day)
    version = stat_version(path)
    if version is None:
        return None
    trade_date = date.fromisoformat(day)
    target = AuditTarget(
        get_lake_asset_catalog_entry(STOCK_DAILY),
        day, trade_date, True, SILVER_STOCK_DAILY_CHECKS, False, "日更",
    )
    try:
        bundle = load_evidence(instance, (target,), trade_date, datetime.now(SHANGHAI)).get(STOCK_DAILY)
    except SQLAlchemyError:
        logger.warning("暂无法读取 %s 股票日线的齐备证据", day, exc_info=True)
        return None
    if (
        bundle
        and bundle.materialization
        and metadata(bundle.materialization.asset_materialization).get("audit_file_version") == version
        and all(name in bundle.checks and bundle.checks[name].evaluation.passed for name in SILVER_STOCK_DAILY_CHECKS)
    ):
        return path, version
    return None


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


def read_index_minute_result(instance, day, asset_key, publication_run_id, observed_at):
    runs = instance.get_run_records(
        filters=dg.RunsFilter(
            job_name=INDEX_MINUTE_JOB,
            statuses=[dg.DagsterRunStatus.SUCCESS],
            tags={
                BUSINESS_DATE_TAG: day.isoformat(),
                AUDIT_ASSET_TAG: asset_key,
                AUDIT_PUBLICATION_TAG: publication_run_id,
            },
            updated_before=observed_at,
        ),
        order_by="update_timestamp",
        limit=1,
    )
    if not runs:
        return None
    outputs = instance.get_records_for_run(
        runs[0].dagster_run.run_id, of_type=dg.DagsterEventType.STEP_OUTPUT, limit=1,
    ).records
    if not outputs:
        return None
    output = outputs[0]
    event = output.event_log_entry.dagster_event
    if event.step_key != "audit_index_minute":
        return None
    entry = event.step_output_data.metadata.get(INDEX_MINUTE_META)
    if not isinstance(entry, dg.JsonMetadataValue) or not isinstance(entry.value, dict):
        return None
    result = entry.value
    if not all(isinstance(result.get(key), dict) for key in ("scope", "version", "completeness", "files")):
        return None
    if result.get("target_publication_run_id") != publication_run_id:
        return None
    return output, result


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
