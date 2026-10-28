"""Bounded event evidence for an explicit period delivery; no lake content reads.

SQL semantics mirror the installed SqlEventLogStorage's materialization filter and
COMPLETED_ASSET_CHECK_EXECUTION_RECORD_STATUSES. Two set queries, not N API calls.
"""

import dagster as dg
import sqlalchemy as sa
from dagster._core.event_api import EventLogRecord
from dagster._core.events.log import EventLogEntry
from dagster._core.storage.event_log.schema import (
    SqlEventLogStorageTable as Events,
)
from dagster._core.storage.event_log.sql_event_log import SqlEventLogStorage
from dagster._serdes import deserialize_value

from orchestrator.defs.asset_guards.stock_period_check_evidence import (
    decode_completed_check_row,
    latest_completed_checks_query,
)
from orchestrator.defs.run_contracts.stock_monthly import (
    StockMonthlySource,
    monthly_check_names,
)
from orchestrator.defs.run_contracts.stock_period_silver import (
    VERSION,
    asset_name,
    check_names,
    materialization_scope,
    validate_materialization_scope,
)
from orchestrator.defs.run_contracts.stock_weekly import (
    StockWeeklySource,
    weekly_check_names,
)


def raw_check_names(freq):
    return (
        weekly_check_names(StockWeeklySource.PRIMARY_ADJUSTED)
        if freq == "week"
        else monthly_check_names(StockMonthlySource.PRIMARY_ADJUSTED)
    )


def batch_event_evidence(instance, freq, periods, *, include_raw=True):
    """Return latest actual materializations and latest completed checks, failures included."""
    storage = instance.event_log_storage
    if not isinstance(storage, SqlEventLogStorage):
        raise TypeError("silver_event_storage_unsupported")
    periods = tuple(sorted(set(periods)))
    keys = {
        asset_name(freq): check_names(freq),
    }
    if include_raw:
        keys[f"raw_tushare_stk_period_bar_adj_{freq}"] = raw_check_names(freq)
    encoded = {name: dg.AssetKey(name).to_string() for name in keys}
    if not periods:
        return {}
    latest_mats = (
        sa.select(sa.func.max(Events.c.id))
        .where(
            Events.c.asset_key.in_(list(encoded.values())),
            Events.c.partition.in_(periods),
            Events.c.dagster_event_type == "ASSET_MATERIALIZATION",
        )
        .group_by(Events.c.asset_key, Events.c.partition)
    )
    latest_checks = latest_completed_checks_query(
        asset_check_names={dg.AssetKey(name): names for name, names in keys.items()},
        partition_keys=periods,
    )
    with storage.index_connection() as connection:
        mats = (
            connection.execute(
                sa.select(Events.c.id, Events.c.event).where(
                    Events.c.id.in_(latest_mats)
                )
            )
            .mappings()
            .all()
        )
        checks = connection.execute(sa.select(latest_checks)).mappings().all()
    result = {}
    for row in mats:
        record = EventLogRecord(
            row["id"], deserialize_value(row["event"], EventLogEntry)
        )
        mat = record.asset_materialization
        result[(mat.asset_key.to_user_string(), mat.partition)] = {
            "materialization": record,
            "checks": {},
            "bound_materializations": {},
            "check_event_storage_ids": {},
        }
    for row in checks:
        key = dg.AssetCheckKey(
            dg.AssetKey.from_db_string(row["asset_key"]), row["check_name"]
        )
        try:
            record, event_id, bound = decode_completed_check_row(
                row,
                asset_key=key.asset_key,
                check_name=key.name,
                partition_key=row["partition"],
            )
        except ValueError as error:
            raise ValueError(
                "silver_target_checks_not_ready"
                if key.asset_key == dg.AssetKey(asset_name(freq))
                else "silver_upstream_checks_not_ready"
            ) from error
        item = result.setdefault(
            (key.asset_key.to_user_string(), row["partition"]),
            {
                "materialization": None,
                "checks": {},
                "bound_materializations": {},
                "check_event_storage_ids": {},
            },
        )
        item["checks"][key.name] = record
        item["check_event_storage_ids"][key.name] = event_id
        if bound is not None:
            item["bound_materializations"][key.name] = bound
    return result


def require_silver_materialization(
    materialization, freq, record=None, identity=None, *, allow_preimage=False
):
    """Validate event metadata against its own scope or an explicit committed unit.

    Old preimages use their original declared scope, never the new unit's date or
    the stat of the path now occupied by a newer file. No file or event reads.
    """
    from orchestrator.defs.stock_period_checks import (
        verify_period_materialization_metadata,
    )

    try:
        if materialization is None or materialization.asset_materialization is None:
            raise ValueError("silver_unknown_target")
        mat = materialization.asset_materialization
        metadata = mat.metadata
        def value(key):
            return getattr(metadata.get(key), "value", None)
        version = value("goldenshare/period_file_version")
        period = record["period"] if record is not None else mat.partition
        target = record["target"] if record is not None else value("dagster/uri")
        if type(target) is not str or not target:
            raise ValueError("silver_materialization_path_invalid")
        rows, expected_version = None, version
        current = False
        if record is not None:
            if identity is None:
                raise ValueError("silver_materialization_identity_missing")
            expected_asof, expected_lower = materialization_scope(record, identity)
            current = version == record.get("version")
            if not current and not allow_preimage:
                raise ValueError("silver_materialization_version_mismatch")
            expected_version = (
                record.get("version") if current
                else record.get("event_preimage", record.get("target_preimage"))
            )
            if current:
                rows = record["rows"]
                if (
                    value("goldenshare/silver_asof") != expected_asof
                    or value("goldenshare/silver_lower") != expected_lower
                ):
                    raise ValueError("silver_materialization_input_mismatch")
        verify_period_materialization_metadata(
            materialization, period, target, version=expected_version,
            rows=rows, asset_key=dg.AssetKey(asset_name(freq)),
        )
        if value("goldenshare/silver_rule") != VERSION:
            raise ValueError("silver_materialization_rule_invalid")
        validate_materialization_scope(
            freq, period, value("goldenshare/silver_asof"), value("goldenshare/silver_lower")
        )
        if current and identity.get("intent") == "update":
            # Prior bootstrap metadata remains sufficient to recognize an old
            # target. A current committed update has its own frozen inputs.
            for key, expected in (
                ("goldenshare/silver_source", record["source"]),
                ("goldenshare/silver_source_version", record["source_version"]),
                ("goldenshare/silver_reference_versions", identity["reference_versions"]),
            ):
                if value(key) != expected:
                    raise ValueError("silver_materialization_input_mismatch")
        return materialization
    except (ValueError, TypeError, AttributeError) as error:
        raise ValueError("silver_target_checks_not_ready") from error


def require_checks(item, freq, *, raw):
    if item is None or item["materialization"] is None:
        raise ValueError(
            "silver_upstream_materialization_missing"
            if raw
            else "silver_unknown_target"
        )
    materialization = item["materialization"]
    mat = materialization.asset_materialization
    if not raw:
        require_silver_materialization(materialization, freq)
    for name in raw_check_names(freq) if raw else check_names(freq):
        record = item["checks"].get(name)
        evaluation = record.evaluation if record else None
        if (
            evaluation is None
            or record.status.value != "SUCCEEDED"
            or not evaluation.passed
            or not evaluation.blocking
            or evaluation.asset_key != mat.asset_key
            or evaluation.partition != mat.partition
            or evaluation.check_name != name
            or evaluation.target_materialization_data is None
            or evaluation.target_materialization_data.storage_id
            != materialization.storage_id
        ):
            raise ValueError(
                "silver_upstream_checks_not_ready"
                if raw
                else "silver_target_checks_not_ready"
            )
    return materialization


def require_recoverable_checks(item, freq, record, identity):
    """Missing registration is recoverable; an actual failure or unexplained binding is not."""
    try:
        materialization_scope(record, identity)
    except ValueError as error:
        raise ValueError("silver_target_checks_not_ready") from error
    if item is None:
        return
    asset = dg.AssetKey(asset_name(freq))

    def matches(materialization):
        if materialization is None:
            return False
        require_silver_materialization(
            materialization, freq, record, identity, allow_preimage=True
        )
        return True

    if item["materialization"] is not None and not matches(item["materialization"]):
        raise ValueError("silver_target_checks_not_ready")
    for name, check in item["checks"].items():
        evaluation = check.evaluation
        bound = item.get("bound_materializations", {}).get(name)
        current = item["materialization"]
        event_id = item.get("check_event_storage_ids", {}).get(name)
        if (
            check.status.value != "SUCCEEDED"
            or evaluation is None
            or not evaluation.passed
            or not evaluation.blocking
            or evaluation.asset_key != asset
            or evaluation.partition != record["period"]
            or evaluation.check_name != name
            or evaluation.target_materialization_data is None
            or not matches(bound)
            or evaluation.target_materialization_data.storage_id != bound.storage_id
            or current is None
            or (
                bound.storage_id != current.storage_id
                and (type(event_id) is not int or event_id >= current.storage_id)
            )
        ):
            raise ValueError("silver_target_checks_not_ready")
