"""One Raw period read, source-row selection, validated COPY and durable commit."""

import hashlib
import json
import os
import resource
import shutil
import signal
import threading
import time
from contextlib import ExitStack, contextmanager
from contextvars import ContextVar
from datetime import UTC, date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from orchestrator.defs.duckdb_connection import (
    DuckDBConnectionSettings,
    connect_configured_duckdb,
)
from orchestrator.defs.io.stock_period_raw import (
    atomic_json,
    durable_directory,
    file_version,
    safe_path,
)
from orchestrator.defs.io.stock_period_silver import (
    publish,
    read_json,
    recover_committed,
    run_directory,
    validate_roots,
    writer_lock,
)
from orchestrator.defs.paths import (
    silver_stock_identity_map_path,
    silver_stock_lifecycle_path,
)
from orchestrator.defs.run_contracts.stock_period_silver import (
    COLUMNS,
    FIELDS,
    SPECS,
    VERSION,
    canonical_run_id,
    materialization_scope,
    period_key,
    period_start,
    raw_path,
    recovery_run_id,
    target_path,
)


class SilverCancelled(RuntimeError):
    pass


_RECOVERY_EVIDENCE = ContextVar("period_silver_recovery_evidence", default=None)


@contextmanager
def recovery_evidence():
    """Only immutable execution/provenance JSON, only for this call, version guarded."""
    token = _RECOVERY_EVIDENCE.set({})
    try:
        yield
    finally:
        _RECOVERY_EVIDENCE.reset(token)


def read_recovery_evidence(path):
    cache = _RECOVERY_EVIDENCE.get()
    version = file_version(path)
    key = str(path)
    if cache is not None and key in cache:
        previous, value = cache[key]
        if previous != version:
            raise ValueError("silver_recovery_evidence_changed")
        return value
    value = read_json(path)
    if file_version(path) != version:
        raise ValueError("silver_recovery_evidence_changed")
    if cache is not None:
        cache[key] = (version, value)
    return value


def check_cancel(cancel):
    if cancel():
        raise SilverCancelled("silver_cancelled")


def fingerprint(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


@contextmanager
def cancellation(connection, requested):
    """Interrupt long SQL on TERM/INT; a callback also supports isolated callers."""
    stop = threading.Event()
    cancelled = threading.Event()
    previous = {}

    def receive(signum, frame):
        cancelled.set()
        connection.interrupt()

    def watch():
        while not stop.wait(0.1):
            if requested():
                cancelled.set()
                connection.interrupt()
                return

    if threading.current_thread() is threading.main_thread():
        for signum in (signal.SIGTERM, signal.SIGINT):
            previous[signum] = signal.signal(signum, receive)
    monitor = threading.Thread(target=watch, daemon=True)
    monitor.start()
    try:
        yield lambda: cancelled.is_set() or requested()
    finally:
        stop.set()
        monitor.join()
        for signum, handler in previous.items():
            signal.signal(signum, handler)


def load_references(con, references):
    con.execute(
        "CREATE OR REPLACE TEMP TABLE silver_life AS SELECT ts_code,list_status,list_date,delist_date,is_cny_stock FROM read_parquet(?,hive_partitioning=false)",
        [references["lifecycle"]],
    )
    con.execute(
        "CREATE OR REPLACE TEMP TABLE silver_identity AS SELECT source_ts_code,latest_ts_code,confidence FROM read_parquet(?,hive_partitioning=false)",
        [references["identity"]],
    )
    for table, key in (
        ("silver_life", "ts_code"),
        ("silver_identity", "source_ts_code"),
    ):
        if con.execute(
            f"SELECT count(*)-count(DISTINCT {key}) FROM {table}"
        ).fetchone()[0]:
            raise ValueError("silver_reference_key_invalid")


def assert_schema(con, relation):
    actual = tuple(
        (r[0], r[1])
        for r in con.execute(f"DESCRIBE SELECT * FROM {relation}").fetchall()
    )
    if actual != SPECS:
        raise ValueError("silver_schema_mismatch")


def select_period(con, source, freq, period, *, asof):
    """Materialize one input once; all subsequent queries use this unit in memory."""
    period_key(period, freq)
    con.execute(
        "CREATE OR REPLACE TEMP TABLE silver_input AS SELECT * FROM read_parquet(?,hive_partitioning=false)",
        [str(source)],
    )
    assert_schema(con, "silver_input")
    con.execute(f"""CREATE OR REPLACE TEMP TABLE silver_scoped AS
        SELECT r.*, i.latest_ts_code canonical_code,i.confidence,l.list_status,l.list_date,l.delist_date,l.is_cny_stock,
          try_strptime(r.trade_date,'%Y%m%d')::DATE bar_date,
          try_strptime(r.end_date,'%Y%m%d')::DATE source_asof,
          date_trunc('{freq}',try_strptime(r.trade_date,'%Y%m%d'))::DATE period_start
        FROM silver_input r LEFT JOIN silver_identity i ON r.ts_code=i.source_ts_code
        LEFT JOIN silver_life l ON l.ts_code=i.latest_ts_code""")
    invalid = con.execute(
        """SELECT count(*) FROM silver_scoped WHERE
        canonical_code IS NULL OR confidence IS DISTINCT FROM 'confirmed' OR list_status IS NULL
        OR bar_date IS NULL OR source_asof IS NULL OR freq IS DISTINCT FROM ?
        OR strftime(bar_date,'%Y%m%d')<>trade_date OR strftime(source_asof,'%Y%m%d')<>end_date
        OR period_start<>?::DATE OR source_asof>?::DATE
        OR (list_status='L' AND is_cny_stock AND list_date IS NULL)""",
        [freq, period_start(period, freq), asof],
    ).fetchone()[0]
    if invalid:
        raise ValueError("silver_source_identity_date_or_partition_invalid")
    con.execute(f"""CREATE OR REPLACE TEMP TABLE silver_latest AS
        SELECT * FROM silver_scoped WHERE list_status='L' AND is_cny_stock
          AND period_start>=date_trunc('{freq}',list_date)
          AND (delist_date IS NULL OR period_start<=date_trunc('{freq}',delist_date-1))
        QUALIFY source_asof=max(source_asof) OVER(PARTITION BY canonical_code)""")
    values = ",".join(f'"{n}"' for n in FIELDS[4:])
    if con.execute(
        f"SELECT count(*) FROM (SELECT canonical_code FROM silver_latest GROUP BY 1 HAVING count(DISTINCT ({values}))>1)"
    ).fetchone()[0]:
        raise ValueError("silver_latest_version_conflict")
    con.execute(f"""CREATE OR REPLACE TEMP TABLE silver_selected AS SELECT {COLUMNS}
        FROM silver_latest QUALIFY row_number() OVER(PARTITION BY canonical_code ORDER BY trade_date DESC,ts_code DESC)=1""")
    return con.execute("SELECT count(*) FROM silver_selected").fetchone()[0]


def validate_projection(con, path, freq, period):
    # Exactly one full candidate read, shared by the three blocking checks.
    con.execute(
        "CREATE OR REPLACE TEMP TABLE silver_output AS SELECT * FROM read_parquet(?,hive_partitioning=false)",
        [str(path)],
    )
    assert_schema(con, "silver_output")
    rows, distinct_codes, invalid = con.execute(
        f"""SELECT count(*),count(DISTINCT ts_code),
        count(*) FILTER(WHERE ts_code IS NULL OR freq IS DISTINCT FROM ? OR
          date_trunc('{freq}',try_strptime(trade_date,'%Y%m%d'))::DATE IS DISTINCT FROM ?::DATE)
        FROM silver_output""",
        [freq, period_start(period, freq)],
    ).fetchone()
    if rows != distinct_codes or invalid:
        raise ValueError("silver_key_partition_invalid")
    differences = con.execute(f"""SELECT
        (SELECT count(*) FROM ((SELECT {COLUMNS} FROM silver_selected) EXCEPT ALL (SELECT {COLUMNS} FROM silver_output)))+
        (SELECT count(*) FROM ((SELECT {COLUMNS} FROM silver_output) EXCEPT ALL (SELECT {COLUMNS} FROM silver_selected)))""").fetchone()[
        0
    ]
    if differences:
        raise ValueError("silver_source_projection_mismatch")
    return rows


def make_execution(lake, staging, run_id, audit_report, *, only=None):
    canonical_run_id(run_id)
    report = safe_path(Path(audit_report))
    summary, inputs = (
        read_json(report / "summary.json"),
        read_json(report / "inputs.json"),
    )
    if summary.get("status") != "passed" or any(
        summary["frequencies"][f]["status"] != "passed" for f in ("week", "month")
    ):
        raise ValueError("silver_audit_not_passed")
    references = {
        "lifecycle": str(silver_stock_lifecycle_path(lake)),
        "identity": str(silver_stock_identity_map_path(lake)),
    }
    if any(
        summary["references"][k] != p or inputs["references"][k] != p
        for k, p in references.items()
    ):
        raise ValueError("silver_reference_root_mismatch")
    units = []
    for freq in ("week", "month"):
        if len(inputs["raw_files"][freq]) != summary["input_file_counts"][freq]:
            raise ValueError("silver_audit_inventory_mismatch")
        for source in inputs["raw_files"][freq]:
            path = safe_path(Path(source))
            period = path.parent.name.split("=", 1)[1]
            from datetime import date, timedelta

            def boundary(day, frequency=freq):
                d = date.fromisoformat(day)
                return (
                    (d - timedelta(days=d.weekday())).isoformat()
                    if frequency == "week"
                    else d.replace(day=1).isoformat()
                )

            if (
                not boundary(summary["lower"])
                <= period_start(period, freq)
                <= boundary(summary["asof"])
            ):
                raise ValueError("silver_input_outside_audit_scope")
            if path != raw_path(lake, freq, period):
                raise ValueError("silver_source_path_invalid")
            if only is None or (freq, period) == only:
                units.append(
                    {
                        "freq": freq,
                        "period": period,
                        "source": str(path),
                        "target": str(target_path(lake, freq, period)),
                    }
                )
    if not units or len({(u["freq"], u["period"]) for u in units}) != len(units):
        raise ValueError("silver_scope_invalid")
    expected = (
        None
        if only
        else {
            f: {
                "files": summary["input_file_counts"][f],
                "rows": summary["frequencies"][f]["selected"]["stock_periods"],
            }
            for f in ("week", "month")
        }
    )
    identity = {
        "rule": VERSION,
        "run_id": run_id,
        "lake": str(lake),
        "staging": str(staging),
        "audit_report": str(report),
        "audit_fingerprint": fingerprint({"summary": summary, "inputs": inputs}),
        "asof": summary["asof"],
        "lower": summary["lower"],
        "references": references,
        "reference_versions": {k: file_version(v) for k, v in references.items()},
        "units": units,
        "expected": expected,
    }
    execution = {"identity": identity, "identity_hash": fingerprint(identity)}
    work = run_directory(staging, run_id)
    if (work / "execution.json").exists():
        if read_json(work / "execution.json") != execution:
            raise ValueError("silver_execution_identity_changed")
    else:
        # No changes to unknown targets, including outputs from another execution.
        if any(safe_path(u["target"]).exists() for u in units):
            raise ValueError("silver_unknown_target")
        atomic_json(work / "execution.json", execution)
    return execution


def load_execution(lake, staging, run_id, *, _seen=None):
    seen = set() if _seen is None else _seen
    if run_id in seen:
        raise ValueError("silver_recovery_cycle")
    seen.add(run_id)
    path = run_directory(staging, run_id) / "execution.json"
    result = read_recovery_evidence(path)
    cache = _RECOVERY_EVIDENCE.get()
    verified_key = ("execution", str(path))
    if cache is not None and verified_key in cache:
        if (
            result["identity"]["lake"] != str(lake)
            or result["identity"]["staging"] != str(staging)
            or result["identity"]["run_id"] != run_id
        ):
            raise ValueError("silver_execution_identity_changed")
        return result
    identity = result["identity"]
    if (
        result["identity_hash"] != fingerprint(identity)
        or identity["rule"] != VERSION
        or identity["run_id"] != run_id
        or identity["lake"] != str(lake)
        or identity["staging"] != str(staging)
    ):
        raise ValueError("silver_execution_identity_changed")
    if identity.get("intent") == "update":
        units = identity["units"]
        if (
            not units
            or identity["lower"] != "2014-01-01"
            or len({u["freq"] for u in units}) != 1
        ):
            raise ValueError("silver_update_scope_invalid")
        keys = [(u["freq"], u["period"]) for u in units]
        if len(set(keys)) != len(keys) or any(
            u["source"] != str(raw_path(lake, *key))
            or u["target"] != str(target_path(lake, *key))
            for key, u in zip(keys, units, strict=True)
        ):
            raise ValueError("silver_update_scope_invalid")
        parent_id = identity.get("resume_from_execution_id")
        if parent_id is not None:
            parent = load_execution(
                lake, staging, canonical_run_id(parent_id), _seen=seen
            )
            if (
                parent["identity_hash"] != identity["resume_from_identity_hash"]
                or parent["identity"].get("intent") != "update"
                or [(u["freq"], u["period"]) for u in parent["identity"]["units"]]
                != keys
                or parent["identity"]["source_completion"]
                != identity["source_completion"]
            ):
                raise ValueError("silver_recovery_parent_invalid")
    if cache is not None:
        cache[verified_key] = result
    return result


def read_completion(lake, staging, reference, freq):
    """Validate the immutable receipt, including stale notifications, without scanning files."""
    from orchestrator.defs.bootstrap.stock_period_history import check_devices
    from orchestrator.defs.run_contracts.stock_period import (
        digest,
        validate_completion_reference,
        verify_execution,
    )

    reference = validate_completion_reference(reference, freq)
    run_id = reference["raw_execution_id"]
    run = safe_path(Path(staging) / "stock_period" / "runs" / run_id)
    saved, complete = read_json(run / "manifest.json"), read_json(run / "complete.json")
    identity = verify_execution(saved, run_id)
    if (
        identity["root"] != str(lake)
        or saved["phase"] not in ("files_complete", "events_complete")
        or complete["run_id"] != run_id
        or saved.get("file_receipt_hash") != reference["file_receipt_hash"]
        or digest(complete) != reference["file_receipt_hash"]
    ):
        raise ValueError("silver_raw_completion_changed")
    check_devices(lake, staging, saved["devices"])
    completed_at = datetime.fromisoformat(saved["files_completed_at"])
    if completed_at.tzinfo is None:
        raise ValueError("silver_raw_completion_time_invalid")
    asof = (
        identity["intent"].get("asof")
        or completed_at.astimezone(ZoneInfo("Asia/Shanghai")).date().isoformat()
    )
    if date.fromisoformat(asof).isoformat() != asof:
        raise ValueError("silver_raw_completion_time_invalid")
    items = {}
    for item in complete["files"]:
        f, period = item["freq"], item["period"]
        if item["target"] != str(raw_path(lake, f, period)) or (f, period) in items:
            raise ValueError("silver_raw_completion_scope_invalid")
        items[(f, period)] = item
    return {"reference": reference, "items": items, "asof": asof}


def resolve_update_sources(
    lake, staging, freq, reference, instance, *, cancel=lambda: False, origin=None
):
    """Resolve explicit Raw scope and current published versions in two set queries."""
    from orchestrator.defs.asset_guards.stock_period_silver_readiness import (
        batch_event_evidence,
        require_checks,
    )
    from orchestrator.defs.run_contracts.stock_period import (
        COMPLETION_METADATA_KEY,
        validate_completion_notice,
    )
    from orchestrator.defs.stock_period_checks import verify_period_materialization

    origin = origin or read_completion(lake, staging, reference, freq)
    minimum = "2014-01-03" if freq == "week" else "2014-01"
    periods = sorted(p for f, p in origin["items"] if f == freq and p >= minimum)
    evidence = batch_event_evidence(instance, freq, periods)
    deliveries = {reference["upstream_batch_id"]: origin}
    units = []
    for period in periods:
        check_cancel(cancel)
        source, target = raw_path(lake, freq, period), target_path(lake, freq, period)
        raw = require_checks(
            evidence.get((f"raw_tushare_stk_period_bar_adj_{freq}", period)),
            freq,
            raw=True,
        )
        verify_period_materialization(raw, period, source)
        raw_version = file_version(source)
        delivery = origin
        if origin["items"][(freq, period)]["version"] != raw_version:
            metadata = raw.asset_materialization.metadata
            value = getattr(metadata.get(COMPLETION_METADATA_KEY), "value", None)
            if not isinstance(value, dict):
                raise ValueError("silver_newer_raw_completion_missing")
            latest_ref = validate_completion_notice(value, freq)
            batch_id = latest_ref["upstream_batch_id"]
            if batch_id not in deliveries:
                deliveries[batch_id] = read_completion(lake, staging, latest_ref, freq)
            delivery = deliveries[batch_id]
        item = delivery["items"].get((freq, period))
        if item is None or item["version"] != raw_version:
            raise ValueError("silver_raw_file_not_in_completion")
        units.append(
            {
                "freq": freq,
                "period": period,
                "source": str(source),
                "target": str(target),
                "source_version": raw_version,
                "source_completion": delivery["reference"],
                "asof": delivery["asof"],
                "supersedes": reference if delivery is not origin else None,
            }
        )
    return units, evidence


def update_inputs(
    lake,
    staging,
    freq,
    reference,
    instance,
    *,
    cancel=lambda: False,
    known=None,
    known_identity=None,
    resolved=None,
):
    """Recognize registered targets or explicitly owned durable commits, never unknown files."""
    from orchestrator.defs.asset_guards.stock_period_silver_readiness import (
        require_checks,
        require_recoverable_checks,
    )
    from orchestrator.defs.run_contracts.stock_period_silver import asset_name
    from orchestrator.defs.stock_period_checks import verify_period_materialization

    units, evidence = (
        resolved
        if resolved is not None
        else resolve_update_sources(
            lake, staging, freq, reference, instance, cancel=cancel
        )
    )
    for unit in units:
        check_cancel(cancel)
        period, target = unit["period"], safe_path(unit["target"])
        current = evidence.get((asset_name(freq), period))
        owned = (known or {}).get(period)
        target_version, metadata = None, {}
        if owned is not None and owned["state"] == "committed":
            if file_version(target) != owned["version"]:
                raise ValueError("silver_committed_target_changed")
            require_recoverable_checks(current, freq, owned, known_identity)
            target_version = owned["version"]
            unit["event_preimage"] = owned.get(
                "event_preimage", owned.get("target_preimage")
            )
        elif target.exists() or current is not None:
            previous = require_checks(current, freq, raw=False)
            verify_period_materialization(previous, period, target)
            metadata = previous.asset_materialization.metadata
            if (
                getattr(metadata.get("goldenshare/silver_rule"), "value", None)
                != VERSION
                or getattr(metadata.get("goldenshare/silver_lower"), "value", None)
                != "2014-01-01"
            ):
                raise ValueError("silver_target_rule_mismatch")
            target_version = file_version(target)
        unit.update(target_preimage=target_version, previous_metadata=metadata)
    return units


def make_update_execution(
    lake,
    staging,
    run_id,
    freq,
    reference,
    instance,
    *,
    cancel=lambda: False,
    parent=None,
    known=None,
    resolved=None,
):
    canonical_run_id(run_id)
    if instance is None:
        raise ValueError("silver_update_instance_required")
    units = update_inputs(
        lake,
        staging,
        freq,
        reference,
        instance,
        cancel=cancel,
        known=known,
        known_identity=parent["identity"] if parent is not None else None,
        resolved=resolved,
    )
    if not units:
        raise ValueError("silver_update_scope_empty")
    references = {
        "lifecycle": str(silver_stock_lifecycle_path(lake)),
        "identity": str(silver_stock_identity_map_path(lake)),
    }
    versions = {k: file_version(p) for k, p in references.items()}
    for unit in units:
        metadata = unit.pop("previous_metadata")
        unit["reuse"] = unit["target_preimage"] is not None and all(
            getattr(metadata.get(key), "value", None) == value
            for key, value in (
                ("goldenshare/silver_source_version", unit["source_version"]),
                ("goldenshare/silver_reference_versions", versions),
                ("goldenshare/silver_asof", unit["asof"]),
            )
        )
        if unit["reuse"]:
            unit["reused_rows"] = metadata["dagster/row_count"].value
        owned = (known or {}).get(unit["period"])
        if parent is not None and owned is not None and owned["state"] == "committed":
            origin = owned.get("inherited_from") or {
                "execution_id": parent["identity"]["run_id"],
                "identity_hash": parent["identity_hash"],
                "record_hash": fingerprint(owned),
            }
            unit["preimage_from"] = origin
            if (
                owned["source_version"] == unit["source_version"]
                and parent["identity"]["reference_versions"] == versions
                and owned.get("asof", parent["identity"]["asof"]) == unit["asof"]
            ):
                unit.update(
                    reuse=True, reused_rows=owned["rows"], inherited_from=origin
                )
    identity = {
        "intent": "update",
        "rule": VERSION,
        "run_id": run_id,
        "lake": str(lake),
        "staging": str(staging),
        "source_completion": reference,
        "asof": max(u["asof"] for u in units),
        "lower": "2014-01-01",
        "references": references,
        "reference_versions": versions,
        "units": units,
        "expected": None,
    }
    if parent is not None:
        identity.update(
            resume_from_execution_id=parent["identity"]["run_id"],
            resume_from_identity_hash=parent["identity_hash"],
        )
    result = {"identity": identity, "identity_hash": fingerprint(identity)}
    path = run_directory(staging, run_id) / "execution.json"
    if path.exists():
        if read_json(path) != result:
            raise ValueError("silver_execution_identity_changed")
    else:
        atomic_json(path, result)
    return result


def reused_update_record(execution, unit):
    record = {
        **unit,
        "rule": VERSION,
        "identity_hash": execution["identity_hash"],
        "version": unit["target_preimage"],
        "state": "committed",
        "rows": unit["reused_rows"],
        "checks": {
            k: True for k in ("file_contract", "key_partition", "source_projection")
        },
    }
    record["validation_hash"] = checkpoint_validation_hash(record)
    validate_record(
        record, execution["identity"], unit, identity_hash=execution["identity_hash"]
    )
    if file_version(unit["target"]) != record["version"]:
        raise ValueError("silver_target_preimage_changed")
    return record


def owned_update_records(lake, staging, execution, *, cancel=lambda: False):
    """Validate each saved fact and normalize an already committed rename only."""
    identity = execution["identity"]
    work = run_directory(staging, identity["run_id"])
    records = {}
    for unit in identity["units"]:
        check_cancel(cancel)
        path = checkpoint_path(work, unit)
        if not path.exists() and unit.get("reuse"):
            atomic_json(path, reused_update_record(execution, unit))
        if not path.exists():
            continue
        before = file_version(path)
        record = read_json(path)
        validate_record(
            record, identity, unit, identity_hash=execution["identity_hash"]
        )
        committed = recover_committed(record, path)
        if record["state"] == "committed" and file_version(path) != before:
            raise ValueError("silver_recovery_evidence_changed")
        records[unit["period"]] = committed if committed is not None else record
        cache = _RECOVERY_EVIDENCE.get()
        if cache is not None and committed is not None:
            cache[str(path)] = (file_version(path), committed)
    return records


def recover_update_execution(
    lake, staging, execution, instance, *, cancel=lambda: False, expected_run_id=None
):
    """Preserve immutable scope; only a published changed input requires a successor."""
    identity = execution["identity"]
    receipts = set()
    for unit in identity["units"]:
        check_cancel(cancel)
        reference = unit["source_completion"]
        if reference["upstream_batch_id"] not in receipts:
            read_completion(lake, staging, reference, unit["freq"])
            receipts.add(reference["upstream_batch_id"])
    changed = any(
        file_version(u["source"]) != u["source_version"] for u in identity["units"]
    )
    if any(
        file_version(p) != identity["reference_versions"][k]
        for k, p in identity["references"].items()
    ):
        raise ValueError("silver_reference_changed")
    if not changed:
        if expected_run_id is not None and expected_run_id != identity["run_id"]:
            raise ValueError("silver_recovery_identity_invalid")
        known = owned_update_records(lake, staging, execution, cancel=cancel)
        if instance is not None:
            from orchestrator.defs.asset_guards.stock_period_silver_readiness import (
                batch_event_evidence,
                require_checks,
                require_recoverable_checks,
            )
            from orchestrator.defs.run_contracts.stock_period_silver import asset_name
            from orchestrator.defs.stock_period_checks import (
                verify_period_materialization,
            )

            freq = identity["units"][0]["freq"]
            evidence = batch_event_evidence(
                instance, freq, [u["period"] for u in identity["units"]]
            )
            for unit in identity["units"]:
                check_cancel(cancel)
                raw = require_checks(
                    evidence.get(
                        (f"raw_tushare_stk_period_bar_adj_{freq}", unit["period"])
                    ),
                    freq,
                    raw=True,
                )
                verify_period_materialization(raw, unit["period"], unit["source"])
                record = known.get(unit["period"])
                if record is not None and record["state"] == "committed":
                    require_recoverable_checks(
                        evidence.get((asset_name(freq), unit["period"])),
                        freq,
                        record,
                        identity,
                    )
                else:
                    target = safe_path(unit["target"])
                    if (file_version(target) if target.exists() else None) != unit[
                        "target_preimage"
                    ]:
                        raise ValueError("silver_target_preimage_changed")
                    current = evidence.get((asset_name(freq), unit["period"]))
                    if target.exists() or current is not None:
                        previous = require_checks(current, freq, raw=False)
                        verify_period_materialization(previous, unit["period"], target)
        return execution
    if instance is None:
        owned_update_records(lake, staging, execution, cancel=cancel)
        raise ValueError("silver_source_changed")
    freq, reference = identity["units"][0]["freq"], identity["source_completion"]
    resolved = resolve_update_sources(
        lake, staging, freq, reference, instance, cancel=cancel
    )
    units, _ = resolved
    if [(u["freq"], u["period"]) for u in units] != [
        (u["freq"], u["period"]) for u in identity["units"]
    ]:
        raise ValueError("silver_recovery_scope_changed")
    input_hash = fingerprint(
        {
            "parent_hash": execution["identity_hash"],
            "rule": VERSION,
            "lower": identity["lower"],
            "references": identity["reference_versions"],
            "units": [
                {
                    k: u[k]
                    for k in (
                        "freq",
                        "period",
                        "source_version",
                        "source_completion",
                        "asof",
                    )
                }
                for u in units
            ],
        }
    )
    successor = recovery_run_id(identity["run_id"], input_hash)
    if expected_run_id is not None and expected_run_id != successor:
        raise ValueError("silver_recovery_identity_invalid")
    if (run_directory(staging, successor) / "execution.json").exists():
        return recover_update_execution(
            lake,
            staging,
            load_execution(lake, staging, successor),
            instance,
            cancel=cancel,
        )
    known = owned_update_records(lake, staging, execution, cancel=cancel)
    return make_update_execution(
        lake,
        staging,
        successor,
        freq,
        reference,
        instance,
        cancel=cancel,
        parent=execution,
        known=known,
        resolved=resolved,
    )


def checkpoint_path(work, unit):
    return safe_path(work / "files" / unit["freq"] / (unit["period"] + ".json"))


def checkpoint_validation_hash(record):
    return fingerprint(
        {
            k: v
            for k, v in record.items()
            if k not in {"state", "version", "publish_seconds", "validation_hash"}
        }
    )


def validate_record(record, identity, unit, *, identity_hash, _seen=None):
    seen = set() if _seen is None else _seen
    key = (identity["run_id"], unit["freq"], unit["period"])
    if key in seen:
        raise ValueError("silver_recovery_cycle")
    seen.add(key)
    if (
        any(record.get(k) != unit[k] for k in ("freq", "period", "source", "target"))
        or record.get("identity_hash") != identity_hash
        or record.get("rule") != VERSION
    ):
        raise ValueError("silver_checkpoint_identity_invalid")
    if (
        record.get("state") not in ("validated", "committed")
        or not isinstance(record.get("rows"), int)
        or record["rows"] < 0
    ):
        raise ValueError("silver_checkpoint_state_invalid")
    if identity.get("intent") == "update" and any(
        record.get(k) != unit.get(k)
        for k in (
            "source_version",
            "source_completion",
            "asof",
            "target_preimage",
            "event_preimage",
            "inherited_from",
            "preimage_from",
        )
    ):
        raise ValueError("silver_checkpoint_input_invalid")
    if identity.get("intent") == "update" and record.get(
        "validation_hash"
    ) != checkpoint_validation_hash(record):
        raise ValueError("silver_validation_record_changed")
    origin = unit.get("inherited_from") or unit.get("preimage_from")
    if origin is not None:
        parent = load_execution(
            Path(identity["lake"]), Path(identity["staging"]), origin["execution_id"]
        )
        if parent["identity_hash"] != origin["identity_hash"]:
            raise ValueError("silver_inherited_identity_changed")
        parent_unit = next(
            (
                u
                for u in parent["identity"]["units"]
                if (u["freq"], u["period"]) == (unit["freq"], unit["period"])
            ),
            None,
        )
        if parent_unit is None:
            raise ValueError("silver_inherited_scope_invalid")
        inherited_path = checkpoint_path(
            run_directory(identity["staging"], origin["execution_id"]), parent_unit
        )
        inherited = read_recovery_evidence(inherited_path)
        cache = _RECOVERY_EVIDENCE.get()
        hash_key = ("record_hash", str(inherited_path))
        record_hash = cache.get(hash_key) if cache is not None else None
        if record_hash is None:
            record_hash = fingerprint(inherited)
            if cache is not None:
                cache[hash_key] = record_hash
        if (
            record_hash != origin["record_hash"]
            or inherited.get("state") != "committed"
        ):
            raise ValueError("silver_inherited_record_changed")
        validate_record(
            inherited,
            parent["identity"],
            parent_unit,
            identity_hash=parent["identity_hash"],
            _seen=seen,
        )
        if unit.get("inherited_from") is not None and (
            inherited["version"] != record.get("version")
            or inherited["rows"] != record["rows"]
            or inherited["source_version"] != record["source_version"]
            or parent["identity"]["reference_versions"]
            != identity["reference_versions"]
        ):
            raise ValueError("silver_inherited_version_invalid")
    expected_candidate = (
        run_directory(identity["staging"], identity["run_id"])
        / "candidates"
        / unit["freq"]
        / unit["period"]
        / "part-000.parquet"
    )
    if unit.get("reuse"):
        if (
            record.get("state") != "committed"
            or record.get("version") != unit["target_preimage"]
            or record.get("candidate") is not None
        ):
            raise ValueError("silver_reused_record_invalid")
    elif record.get("candidate") != str(expected_candidate):
        raise ValueError("silver_candidate_path_invalid")
    elif (
        record["state"] == "committed"
        and record.get("version", [])[:4] != record.get("candidate_version", [])[:4]
    ):
        raise ValueError("silver_committed_candidate_identity_changed")
    if record.get("checks") != {
        k: True for k in ("file_contract", "key_partition", "source_projection")
    }:
        raise ValueError("silver_validation_evidence_missing")


def materialization_metadata(record, identity):
    import dagster as dg

    from orchestrator.defs.run_contracts.metadata import build_materialization_metadata

    asof, lower = materialization_scope(record, identity)
    return build_materialization_metadata(
        uri=record["target"],
        row_count=record["rows"],
        observed_columns=FIELDS,
        extra_metadata={
            "goldenshare/period_file_version": dg.MetadataValue.json(record["version"]),
            "goldenshare/silver_rule": VERSION,
            "goldenshare/silver_source": record["source"],
            "goldenshare/silver_asof": asof,
            "goldenshare/silver_lower": lower,
            "goldenshare/silver_execution_id": identity["run_id"],
            "goldenshare/silver_source_version": dg.MetadataValue.json(
                record["source_version"]
            ),
            "goldenshare/silver_reference_versions": dg.MetadataValue.json(
                identity["reference_versions"]
            ),
            **(
                {
                    "goldenshare/silver_source_completion": dg.MetadataValue.json(
                        record["source_completion"]
                    )
                }
                if "source_completion" in record
                else {}
            ),
            **(
                {
                    "goldenshare/silver_inherited_from": dg.MetadataValue.json(
                        record["inherited_from"]
                    )
                }
                if record.get("inherited_from")
                else {}
            ),
        },
    )


_VALIDATED = {}


def current_validation(lake, staging, freq, period, *, asof):
    """No bootstrap-receipt dependency: one partition, shared by all three checks."""
    source, target = raw_path(lake, freq, period), target_path(lake, freq, period)
    references = {
        "lifecycle": str(silver_stock_lifecycle_path(lake)),
        "identity": str(silver_stock_identity_map_path(lake)),
    }
    key = (
        str(target),
        tuple(file_version(target)),
        tuple(file_version(source)),
        tuple(tuple(file_version(p)) for p in references.values()),
        VERSION,
        asof,
    )
    if key in _VALIDATED:
        return _VALIDATED[key]
    # Only the fallback path needs SQL. Never read suspension or daily history here.
    with connect_configured_duckdb(
        DuckDBConnectionSettings(
            temp_directory=Path(staging) / "stock_period_silver" / "check_spill"
        )
    ) as con:
        load_references(con, references)
        select_period(con, source, freq, period, asof=asof)
        rows = validate_projection(con, target, freq, period)
    if (
        file_version(target) != list(key[1])
        or file_version(source) != list(key[2])
        or tuple(tuple(file_version(p)) for p in references.values()) != key[3]
    ):
        raise ValueError("silver_check_input_changed")
    if len(_VALIDATED) >= 16:
        _VALIDATED.clear()
    _VALIDATED[key] = rows
    return rows


def remember_validation(record, identity):
    key = (
        record["target"],
        tuple(record["version"]),
        tuple(record["source_version"]),
        tuple(
            tuple(identity["reference_versions"][k]) for k in ("lifecycle", "identity")
        ),
        VERSION,
        record.get("asof", identity["asof"]),
    )
    if len(_VALIDATED) >= 16:
        _VALIDATED.clear()
    _VALIDATED[key] = record["rows"]


def deliver_asset(context, config, lake_root, freq):
    import dagster as dg

    from orchestrator.defs.paths import DEFAULT_LAKE_STAGING_ROOT

    lake, staging = lake_root.root(), Path(DEFAULT_LAKE_STAGING_ROOT)
    config.validate_intent(freq)
    if config.intent == "update":
        return deliver_update_asset(context, config, lake, staging, freq)
    work = run_directory(staging, config.execution_id)
    only = (freq, context.partition_key)
    if (work / "execution.json").exists():
        execution = load_execution(lake, staging, config.execution_id)
        if [(u["freq"], u["period"]) for u in execution["identity"]["units"]] != [
            only
        ] or execution["identity"]["audit_report"] != config.audit_report:
            raise ValueError("silver_asset_execution_scope_mismatch")
        build(lake, staging, config.execution_id, emit=context.log.info)
    else:
        build(
            lake,
            staging,
            config.execution_id,
            audit_report=config.audit_report,
            only=only,
            emit=context.log.info,
        )
        execution = load_execution(lake, staging, config.execution_id)
    unit = execution["identity"]["units"][0]
    record = read_json(checkpoint_path(work, unit))
    remember_validation(record, execution["identity"])
    return dg.MaterializeResult(
        metadata=materialization_metadata(record, execution["identity"])
    )


def deliver_update_asset(context, config, lake, staging, freq):
    import dagster as dg

    from orchestrator.defs.bootstrap.stock_period_silver_cli import report_update_events

    last_checked, cancelled = float("-inf"), False

    def cancel():
        nonlocal last_checked, cancelled
        if time.monotonic() - last_checked >= 2:
            last_checked = time.monotonic()
            run = context.instance.get_run_by_id(context.run_id)
            cancelled = run is not None and run.status in (
                dg.DagsterRunStatus.CANCELING,
                dg.DagsterRunStatus.CANCELED,
            )
        return cancelled

    result = build(
        lake,
        staging,
        config.execution_id,
        instance=context.instance,
        freq=freq,
        source_completion=config.source_completion,
        resume_from_execution_id=config.resume_from_execution_id,
        only=(freq, context.partition_key),
        cancel=cancel,
        emit=context.log.info,
    )
    actual_id = result["run_id"]
    execution = load_execution(lake, staging, actual_id)
    identity = execution["identity"]
    # Native anchor materialization/checks run after the asset returns. Never pre-ack it.
    report_update_events(
        lake,
        staging,
        actual_id,
        context.instance,
        context.op_execution_context,
        anchor=context.partition_key,
        cancel=cancel,
    )
    unit = identity["units"][-1]
    record = read_json(checkpoint_path(run_directory(staging, actual_id), unit))
    remember_validation(record, identity)
    return dg.MaterializeResult(metadata=materialization_metadata(record, identity))


def emit_progress(value):
    print(value, flush=True)


def update_delivery_progress(staging, execution):
    """Read file-stage facts without creating checkpoints or recovering writes."""
    identity = execution["identity"]
    work = run_directory(staging, identity["run_id"])
    for key, path in identity["references"].items():
        if file_version(path) != identity["reference_versions"][key]:
            raise ValueError("silver_event_reference_changed")
    summary_path = work / "complete.json"
    summary = None
    if summary_path.exists():
        try:
            summary = read_recovery_evidence(summary_path)
        except json.JSONDecodeError as error:
            raise ValueError("silver_completion_invalid") from error
        if not isinstance(summary, dict):
            raise ValueError("silver_completion_invalid")
        if summary.get("run_id") != identity["run_id"]:
            raise ValueError("silver_completion_identity_changed")
    totals = {freq: {"files": 0, "rows": 0} for freq in ("week", "month")}
    for unit in identity["units"]:
        path = checkpoint_path(work, unit)
        if not path.exists():
            if summary is not None:
                raise ValueError(
                    "silver_completion_checkpoint_missing:" + unit["period"]
                )
            continue
        try:
            record = read_recovery_evidence(path)
        except json.JSONDecodeError as error:
            raise ValueError("silver_checkpoint_invalid:" + unit["period"]) from error
        if not isinstance(record, dict):
            raise TypeError("silver_checkpoint_invalid:" + unit["period"])
        validate_record(
            record, identity, unit, identity_hash=execution["identity_hash"]
        )
        if record["state"] != "committed":
            if summary is not None:
                raise ValueError(
                    "silver_completion_checkpoint_uncommitted:" + unit["period"]
                )
            continue
        target = safe_path(unit["target"])
        if not target.exists() or file_version(target) != record["version"]:
            raise ValueError("silver_event_file_changed")
        totals[unit["freq"]]["files"] += 1
        totals[unit["freq"]]["rows"] += record["rows"]
    if summary is not None:
        saved = summary.get("totals")
        if (
            not isinstance(saved, dict)
            or set(saved) != set(totals)
            or any(
                not isinstance(saved[freq], dict)
                or set(saved[freq]) != {"files", "rows"}
                or any(
                    type(value) is not int or value < 0
                    for value in saved[freq].values()
                )
                for freq in totals
            )
            or saved != totals
        ):
            raise ValueError("silver_completion_totals_invalid")
    return {
        "files": len(identity["units"]),
        "committed": sum(value["files"] for value in totals.values()),
        "files_complete": summary is not None,
    }


def update_recovery_message(execution, progress):
    """Describe the existing job/config needed to finish this exact execution."""
    from orchestrator.defs.run_contracts.stock_period_silver import asset_name

    identity = execution["identity"]
    anchor = identity["units"][-1]
    asset = asset_name(anchor["freq"])
    config = {
        "intent": "update",
        "execution_id": identity["run_id"],
        "source_completion": identity["source_completion"],
    }
    if "resume_from_execution_id" in identity:
        config["resume_from_execution_id"] = identity["resume_from_execution_id"]
    run_config = json.dumps({"ops": {asset: {"config": config}}}, separators=(",", ":"))
    return (
        "silver_recovery_required:"
        + identity["run_id"]
        + f";files_committed={progress['committed']}/{progress['files']}"
        + ";files_complete="
        + str(progress["files_complete"]).lower()
        + ";job="
        + asset
        + "_update_job;partition="
        + anchor["period"]
        + ";run_config="
        + run_config
    )


def confirm_update_delivery(lake, staging, execution, evidence):
    """Persist completion from actual bound events; never emit events or compute data."""
    from orchestrator.defs.asset_guards.stock_period_silver_readiness import (
        require_checks,
        require_silver_materialization,
    )
    from orchestrator.defs.bootstrap.stock_period_silver_cli import (
        record_update_coverage,
    )
    from orchestrator.defs.run_contracts.stock_period_silver import (
        asset_name,
        check_names,
    )
    from orchestrator.defs.stock_period_checks import verify_period_materialization

    if not update_delivery_progress(staging, execution)["files_complete"]:
        raise ValueError("silver_update_files_incomplete")
    identity, entries = execution["identity"], []
    work = run_directory(staging, identity["run_id"])
    for key, path in identity["references"].items():
        if file_version(path) != identity["reference_versions"][key]:
            raise ValueError("silver_event_reference_changed")
    for unit in identity["units"]:
        record = read_recovery_evidence(checkpoint_path(work, unit))
        validate_record(
            record, identity, unit, identity_hash=execution["identity_hash"]
        )
        if (
            record["state"] != "committed"
            or file_version(unit["source"]) != unit["source_version"]
            or file_version(unit["target"]) != record["version"]
        ):
            raise ValueError("silver_event_file_changed")
        freq, period = unit["freq"], unit["period"]
        raw = require_checks(
            evidence.get((f"raw_tushare_stk_period_bar_adj_{freq}", period)),
            freq,
            raw=True,
        )
        verify_period_materialization(raw, period, unit["source"])
        current = evidence.get((asset_name(freq), period))
        mat = require_checks(current, freq, raw=False)
        verify_period_materialization(mat, period, unit["target"], rows=record["rows"])
        require_silver_materialization(mat, freq, record, identity)
        entries.append(
            (
                unit,
                {
                    "version": record["version"],
                    "identity_hash": execution["identity_hash"],
                    "materialization_id": mat.storage_id,
                    "checks": list(check_names(freq)),
                    "event_run_id": current["checks"][check_names(freq)[0]].run_id,
                },
            )
        )
    # All evidence must pass before any completion record can claim success.
    for unit, receipt in entries:
        atomic_json(
            work / "events" / unit["freq"] / (unit["period"] + ".json"), receipt
        )
    for unit, receipt in entries:
        if (
            file_version(unit["source"]) != unit["source_version"]
            or file_version(unit["target"]) != receipt["version"]
        ):
            raise ValueError("silver_event_file_changed")
    if any(
        file_version(path) != identity["reference_versions"][key]
        for key, path in identity["references"].items()
    ):
        raise ValueError("silver_event_reference_changed")
    result = {
        "run_id": identity["run_id"],
        "identity_hash": execution["identity_hash"],
        "files": len(entries),
        "checks": 3 * len(entries),
        "status": "complete",
    }
    atomic_json(work / "events_complete.json", result)
    record_update_coverage(lake, staging, execution, result)
    return result


def evaluate_update_sensor(context, *, freq, staging_root=None):
    """One delivery and at most one request; only metadata/stat and two set queries."""
    import dagster as dg
    from dagster._core.storage.dagster_run import JobBucket

    from orchestrator.defs.asset_guards.stock_period_silver_readiness import (
        batch_event_evidence,
    )
    from orchestrator.defs.paths import DEFAULT_LAKE_STAGING_ROOT
    from orchestrator.defs.run_contracts.requests import build_run_request
    from orchestrator.defs.run_contracts.run_keys import (
        build_upstream_triggered_run_key,
    )
    from orchestrator.defs.run_contracts.stock_period import (
        COMPLETION_METADATA_KEY,
        validate_completion_notice,
    )
    from orchestrator.defs.run_contracts.stock_period_silver import (
        SENSOR_CURSOR_VERSION,
        asset_name,
        update_run_id,
    )

    state = {"schema_version": SENSOR_CURSOR_VERSION, "after": 0}

    def skip(reason):
        state.update(
            decision=reason,
            evaluated_at=datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
        )
        context.update_cursor(json.dumps(state, separators=(",", ":")))
        return dg.SensorResult(skip_reason=dg.SkipReason(reason))

    try:
        if context.cursor:
            state = json.loads(context.cursor)
            if not isinstance(state, dict):
                return dg.SensorResult(
                    skip_reason=dg.SkipReason("silver_sensor_cursor_invalid")
                )
            if (
                state.get("schema_version") != SENSOR_CURSOR_VERSION
                or type(state.get("after")) is not int
                or state["after"] < 0
            ):
                raise ValueError("silver_sensor_cursor_invalid")
        lake, staging = validate_roots(
            context.resources.lake_root.root(),
            Path(staging_root or DEFAULT_LAKE_STAGING_ROOT),
        )
        asset = asset_name(freq)
        job = asset + "_update_job"
        active = [
            dg.DagsterRunStatus.NOT_STARTED,
            dg.DagsterRunStatus.QUEUED,
            dg.DagsterRunStatus.STARTING,
            dg.DagsterRunStatus.STARTED,
            dg.DagsterRunStatus.CANCELING,
        ]
        if context.instance.get_runs(
            filters=dg.RunsFilter(statuses=active),
            bucket_by=JobBucket(
                job_names=[
                    "silver_stock_weekly_update_job",
                    "silver_stock_monthly_update_job",
                ],
                bucket_limit=1,
            ),
        ):
            return skip("silver_run_active")
        pending = state.get("pending")
        if pending is None:
            records = context.instance.fetch_observations(
                dg.AssetRecordsFilter(
                    asset_key=dg.AssetKey(f"raw_tushare_stk_period_bar_adj_{freq}"),
                    after_storage_id=state["after"],
                ),
                limit=1,
                ascending=True,
            ).records
            if not records:
                return skip("silver_no_completion")
            notice = records[0].asset_observation.metadata.get(COMPLETION_METADATA_KEY)
            notice = getattr(notice, "value", None)
            reference = validate_completion_notice(notice, freq)
            pending = {
                "observation_id": records[0].storage_id,
                "completion": notice,
                "execution_id": update_run_id(freq, reference),
            }
            state["pending"] = pending
        reference = validate_completion_notice(pending["completion"], freq)
        run_id = canonical_run_id(pending["execution_id"])
        original_id = update_run_id(freq, reference)
        original_work = run_directory(staging, original_id)

        def ack(reason):
            state["after"] = pending["observation_id"]
            state.pop("pending", None)
            return skip(reason)

        # A previously closed batch is historical evidence, not a demand that
        # its old output remain the current version after later valid updates.
        if (original_work / "events_complete.json").exists():
            original = load_execution(lake, staging, original_id)
            closed = read_json(original_work / "events_complete.json")
            if (
                original["identity"].get("source_completion") != reference
                or closed.get("run_id") != original_id
                or closed.get("identity_hash") != original["identity_hash"]
                or closed.get("status") != "complete"
                or closed.get("files") != len(original["identity"]["units"])
                or closed.get("checks") != 3 * len(original["identity"]["units"])
            ):
                raise ValueError("silver_completion_identity_changed")
            if closed.get("covered_by_execution_id"):
                child = load_execution(lake, staging, closed["covered_by_execution_id"])
                child_complete = read_json(
                    run_directory(staging, child["identity"]["run_id"])
                    / "events_complete.json"
                )
                if (
                    child["identity_hash"] != closed.get("covered_by_identity_hash")
                    or child_complete.get("identity_hash") != child["identity_hash"]
                    or child_complete.get("status") != "complete"
                ):
                    raise ValueError("silver_event_coverage_invalid")
            return ack("silver_batch_already_complete")
        run_key = build_upstream_triggered_run_key(
            consumer=asset, upstream_batch_id=reference["upstream_batch_id"]
        )
        runs = context.instance.get_runs(
            filters=dg.RunsFilter(job_name=job, tags={"dagster/run_key": run_key}),
            limit=1,
        )
        work = run_directory(staging, run_id)
        failed_original = bool(
            run_id == original_id
            and runs
            and runs[0].status
            in (
                dg.DagsterRunStatus.FAILURE,
                dg.DagsterRunStatus.CANCELED,
            )
        )

        def recovery_reason(execution, progress):
            message = update_recovery_message(execution, progress)
            if not failed_original:
                return message
            return (
                "silver_run_requires_review:"
                + runs[0].run_id
                + ";resume_execution_id="
                + execution["identity"]["run_id"]
                + ";"
                + message
            )

        if (work / "execution.json").exists():
            with writer_lock(staging), recovery_evidence():
                execution = load_execution(lake, staging, run_id)
                if execution["identity"].get("source_completion") != reference:
                    raise ValueError("silver_completion_identity_changed")
                if any(
                    file_version(u["source"]) != u["source_version"]
                    for u in execution["identity"]["units"]
                ):
                    execution = recover_update_execution(
                        lake, staging, execution, context.instance
                    )
                    pending["execution_id"] = execution["identity"]["run_id"]
                    return skip(
                        recovery_reason(
                            execution, update_delivery_progress(staging, execution)
                        )
                    )
                progress = update_delivery_progress(staging, execution)
                if not progress["files_complete"]:
                    return skip(recovery_reason(execution, progress))
                try:
                    evidence = batch_event_evidence(
                        context.instance,
                        freq,
                        [u["period"] for u in execution["identity"]["units"]],
                    )
                    confirm_update_delivery(lake, staging, execution, evidence)
                except (ValueError, TypeError, OSError) as error:
                    return skip(
                        str(error) + ";" + update_recovery_message(execution, progress)
                    )
                return ack("silver_batch_complete")
        if runs:
            reason = "silver_run_requires_review:" + runs[0].run_id
            if failed_original:
                reason += ";resume_execution_id=" + pending["execution_id"]
            return skip(reason)
        receipt = read_completion(lake, staging, reference, freq)
        if (
            sum(f == freq for f, _ in receipt["items"])
            != pending["completion"]["file_count"]
        ):
            raise ValueError("silver_completion_count_mismatch")
        units, evidence = resolve_update_sources(
            lake, staging, freq, reference, context.instance, origin=receipt
        )
        if not units:
            return ack("silver_scope_before_2014")
        update_inputs(
            lake, staging, freq, reference, context.instance, resolved=(units, evidence)
        )
        config = {
            "intent": "update",
            "execution_id": run_id,
            "source_completion": reference,
        }
        state.update(
            decision="silver_requested",
            evaluated_at=datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
        )
        context.update_cursor(json.dumps(state, separators=(",", ":")))
        return dg.SensorResult(
            run_requests=[
                build_run_request(
                    run_key=run_key,
                    job_name=job,
                    partition_key=units[-1]["period"],
                    run_config={"ops": {asset: {"config": config}}},
                )
            ]
        )
    except (ValueError, TypeError, OSError) as error:
        return skip(str(error))


def build(
    lake,
    staging,
    run_id,
    *,
    audit_report=None,
    only=None,
    cancel=lambda: False,
    emit=emit_progress,
    source_completion=None,
    freq=None,
    instance=None,
    resume_from_execution_id=None,
):
    lake, staging = validate_roots(lake, staging)
    if audit_report is not None and source_completion is not None:
        raise ValueError("silver_execution_intent_mixed")
    existing = (
        load_execution(lake, staging, run_id)
        if (run_directory(staging, run_id) / "execution.json").exists()
        else None
    )
    update = source_completion is not None or (
        existing and existing["identity"].get("intent") == "update"
    )
    with ExitStack() as locks:
        locks.enter_context(recovery_evidence())
        if update:
            from orchestrator.defs.bootstrap.stock_period_history import writer

            locks.enter_context(writer(staging))
        locks.enter_context(writer_lock(staging))
        if resume_from_execution_id is not None:
            if (
                existing is not None
                and existing["identity"].get("resume_from_execution_id")
                != resume_from_execution_id
            ):
                raise ValueError("silver_recovery_parent_invalid")
            parent = load_execution(
                lake, staging, canonical_run_id(resume_from_execution_id)
            )
            if (
                parent["identity"].get("intent") != "update"
                or source_completion != parent["identity"]["source_completion"]
                or any(u["freq"] != freq for u in parent["identity"]["units"])
            ):
                raise ValueError("silver_recovery_parent_invalid")
            execution = recover_update_execution(
                lake,
                staging,
                parent,
                instance,
                cancel=cancel,
                expected_run_id=run_id if existing is None else None,
            )
            if execution["identity"]["run_id"] != run_id:
                raise ValueError("silver_recovery_identity_invalid")
            existing = execution
        if source_completion is not None:
            if existing:
                execution = existing
                if (
                    execution["identity"].get("intent") != "update"
                    or execution["identity"]["source_completion"] != source_completion
                    or any(u["freq"] != freq for u in execution["identity"]["units"])
                ):
                    raise ValueError("silver_asset_execution_scope_mismatch")
            else:
                execution = make_update_execution(
                    lake,
                    staging,
                    run_id,
                    freq,
                    source_completion,
                    instance,
                    cancel=cancel,
                )
        elif audit_report:
            execution = make_execution(lake, staging, run_id, audit_report, only=only)
        else:
            execution = existing or load_execution(lake, staging, run_id)
        identity = execution["identity"]
        work = run_directory(staging, run_id)
        if (
            update
            and only is not None
            and (identity["units"][-1]["freq"], identity["units"][-1]["period"]) != only
        ):
            raise ValueError("silver_update_anchor_mismatch")
        if update and existing is not None and resume_from_execution_id is None:
            execution = recover_update_execution(
                lake, staging, execution, instance, cancel=cancel
            )
            identity = execution["identity"]
            if identity["run_id"] != run_id:
                emit(
                    json.dumps(
                        {
                            "stage": "recovery",
                            "requested_execution_id": run_id,
                            "run_id": identity["run_id"],
                            "reuse": [
                                u["period"] for u in identity["units"] if u.get("reuse")
                            ],
                            "rebuild": [
                                u["period"]
                                for u in identity["units"]
                                if not u.get("reuse")
                            ],
                        }
                    )
                )
            run_id = identity["run_id"]
            work = run_directory(staging, run_id)
        for key, path in identity["references"].items():
            if file_version(path) != identity["reference_versions"][key]:
                raise ValueError("silver_reference_changed")
        settings = DuckDBConnectionSettings(temp_directory=work / "spill")
        started = time.monotonic()
        records = []
        with ExitStack() as stack:
            con, cancelled, references_loaded = None, cancel, False
            check_cancel(cancelled)
            for unit in identity["units"]:
                check_cancel(cancelled)
                emit(
                    json.dumps(
                        {
                            "stage": "period",
                            "freq": unit["freq"],
                            "period": unit["period"],
                            "done": len(records),
                            "total": len(identity["units"]),
                            "updated_at": datetime.now(UTC).isoformat(),
                        }
                    )
                )
                cp = checkpoint_path(work, unit)
                record = read_json(cp) if cp.exists() else None
                if record is None and unit.get("reuse"):
                    record = reused_update_record(execution, unit)
                    atomic_json(cp, record)
                if record:
                    validate_record(
                        record, identity, unit, identity_hash=execution["identity_hash"]
                    )
                    if file_version(unit["source"]) != record["source_version"]:
                        raise ValueError("silver_source_changed")
                if record is None or record["state"] != "committed":
                    if con is None:
                        con = stack.enter_context(connect_configured_duckdb(settings))
                        cancelled = stack.enter_context(cancellation(con, cancel))
                    if record is None and not references_loaded:
                        load_references(con, identity["references"])
                        for key, path in identity["references"].items():
                            if (
                                file_version(path)
                                != identity["reference_versions"][key]
                            ):
                                raise ValueError("silver_reference_changed")
                        references_loaded = True
                if not record:
                    target = safe_path(unit["target"])
                    if update:
                        if (file_version(target) if target.exists() else None) != unit[
                            "target_preimage"
                        ]:
                            raise ValueError("silver_target_preimage_changed")
                    elif target.exists():
                        raise ValueError("silver_unknown_target")
                    source_version = file_version(unit["source"])
                    if update and source_version != unit["source_version"]:
                        raise ValueError("silver_source_changed")
                    candidate = safe_path(
                        durable_directory(
                            work / "candidates" / unit["freq"] / unit["period"]
                        )
                        / "part-000.parquet"
                    )
                    # An interrupted COPY has no acceptance evidence and is rebuilt only here.
                    if candidate.exists():
                        candidate.unlink()
                    if shutil.disk_usage(work).free <= source_version[2]:
                        raise ValueError("silver_space_insufficient")
                    before = time.monotonic()
                    emit(
                        json.dumps(
                            {
                                "stage": "select",
                                **unit,
                                "done": len(records),
                                "total": len(identity["units"]),
                            }
                        )
                    )
                    rows = select_period(
                        con,
                        unit["source"],
                        unit["freq"],
                        unit["period"],
                        asof=unit.get("asof", identity["asof"]),
                    )
                    if rows == 0 and identity["expected"] is not None:
                        raise ValueError("silver_unexpected_empty_selection")
                    select_seconds = time.monotonic() - before
                    check_cancel(cancelled)
                    emit(
                        json.dumps(
                            {
                                "stage": "copy",
                                "period": unit["period"],
                                "done": len(records),
                            }
                        )
                    )
                    copy_began = time.monotonic()
                    con.execute(
                        f"COPY (SELECT {COLUMNS} FROM silver_selected ORDER BY ts_code) TO ? (FORMAT PARQUET,COMPRESSION ZSTD)",
                        [str(candidate)],
                    )
                    copy_seconds = time.monotonic() - copy_began
                    check_cancel(cancelled)
                    emit(
                        json.dumps(
                            {
                                "stage": "validate",
                                "period": unit["period"],
                                "done": len(records),
                            }
                        )
                    )
                    validate_began = time.monotonic()
                    rows = validate_projection(
                        con, candidate, unit["freq"], unit["period"]
                    )
                    check_cancel(cancelled)
                    if file_version(unit["source"]) != source_version:
                        raise ValueError("silver_source_changed")
                    with candidate.open("rb") as handle:
                        os.fsync(handle.fileno())
                    record = {
                        **unit,
                        "rule": VERSION,
                        "identity_hash": execution["identity_hash"],
                        "source_version": source_version,
                        "candidate": str(candidate),
                        "candidate_version": file_version(candidate),
                        "state": "validated",
                        "rows": rows,
                        "empty_reason": "no_eligible_listed_rows"
                        if rows == 0
                        else None,
                        "checks": {
                            k: True
                            for k in (
                                "file_contract",
                                "key_partition",
                                "source_projection",
                            )
                        },
                        "seconds": time.monotonic() - before,
                        "select_seconds": select_seconds,
                        "copy_seconds": copy_seconds,
                        "validation_seconds": time.monotonic() - validate_began,
                    }
                    if update:
                        record["validation_hash"] = checkpoint_validation_hash(record)
                    atomic_json(cp, record)
                check_cancel(cancelled)
                record = publish(record, cp, con=con, cancel=cancelled)
                records.append(record)
        totals = {
            f: {
                "files": sum(r["freq"] == f for r in records),
                "rows": sum(r["rows"] for r in records if r["freq"] == f),
            }
            for f in ("week", "month")
        }
        if identity["expected"] is not None and totals != identity["expected"]:
            raise ValueError("silver_audit_totals_mismatch")
        result = {
            "run_id": run_id,
            "totals": totals,
            "elapsed_seconds": time.monotonic() - started,
            "settings": {**settings.config()},
            "source_requests": 0,
            "process_peak_rss_bytes": resource.getrusage(
                resource.RUSAGE_SELF
            ).ru_maxrss,
            "output_bytes": sum(r["version"][2] for r in records),
            "stage_seconds": {
                k: sum(r.get(k, 0.0) for r in records)
                for k in (
                    "select_seconds",
                    "copy_seconds",
                    "validation_seconds",
                    "publish_seconds",
                )
            },
        }
        atomic_json(work / "complete.json", result)
        emit(json.dumps({"stage": "files_complete", **result}))
        return result
