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
            from datetime import timedelta

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
        raise ValueError("silver_bootstrap_execution_required")
    if cache is not None:
        cache[verified_key] = result
    return result


def checkpoint_path(work, unit):
    return safe_path(work / "files" / unit["freq"] / (unit["period"] + ".json"))


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
    expected_candidate = (
        run_directory(identity["staging"], identity["run_id"])
        / "candidates"
        / unit["freq"]
        / unit["period"]
        / "part-000.parquet"
    )
    if record.get("candidate") != str(expected_candidate):
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
        yield from deliver_update_asset(context, config, lake, staging, freq)
        return
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
    yield dg.MaterializeResult(
        metadata=materialization_metadata(record, execution["identity"])
    )


def emit_progress(value):
    print(value, flush=True)


def build(
    lake,
    staging,
    run_id,
    *,
    audit_report=None,
    only=None,
    cancel=lambda: False,
    emit=emit_progress,
):
    """Independent initial Silver build only; daily updates use native runs."""
    lake, staging = validate_roots(lake, staging)
    with ExitStack() as locks:
        locks.enter_context(recovery_evidence())
        locks.enter_context(writer_lock(staging))
        execution = (
            make_execution(lake, staging, run_id, audit_report, only=only)
            if audit_report
            else load_execution(lake, staging, run_id)
        )
        identity = execution["identity"]
        work = run_directory(staging, run_id)
        for key, path in identity["references"].items():
            if file_version(path) != identity["reference_versions"][key]:
                raise ValueError("silver_reference_changed")
        settings = DuckDBConnectionSettings(temp_directory=work / "spill")
        started = time.monotonic()
        records = []
        with ExitStack() as stack:
            con, cancelled, references_loaded = (None, cancel, False)
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
                    if record is None and (not references_loaded):
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
                    if target.exists():
                        raise ValueError("silver_unknown_target")
                    source_version = file_version(unit["source"])
                    candidate = safe_path(
                        durable_directory(
                            work / "candidates" / unit["freq"] / unit["period"]
                        )
                        / "part-000.parquet"
                    )
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


def resolve_update_sources(lake, freq, reference, instance, *, cancel=lambda: False, origin=None):
    """Resolve this original range and all actual successor Raw deliveries in sets."""
    from orchestrator.defs.asset_guards.stock_period_delivery import (
        read_completion,
        read_completions,
    )
    from orchestrator.defs.asset_guards.stock_period_silver_readiness import (
        batch_event_evidence,
        require_checks,
    )
    from orchestrator.defs.run_contracts.stock_period_delivery import (
        FILE_DELIVERY_KEY,
        validate_delivery_ref,
    )
    from orchestrator.defs.stock_period_checks import verify_period_materialization

    origin = origin or read_completion(instance, reference, root=lake)
    minimum = "2014-01-03" if freq == "week" else "2014-01"
    periods = sorted(p for f, p in origin["items"] if f == freq and p >= minimum)
    evidence = batch_event_evidence(instance, freq, periods)
    latest, references = {}, {}
    for period in periods:
        check_cancel(cancel)
        materialization = require_checks(evidence.get((f"raw_tushare_stk_period_bar_adj_{freq}", period)), freq, raw=True)
        verify_period_materialization(materialization, period, raw_path(lake, freq, period))
        metadata = materialization.asset_materialization.metadata
        actual = validate_delivery_ref(getattr(metadata.get(FILE_DELIVERY_KEY), "value", None), freq)
        references[actual["upstream_batch_id"]] = actual
        latest[period] = (materialization, actual)
    deliveries = {reference["upstream_batch_id"]: origin}
    deliveries.update(read_completions(instance, [value for key, value in references.items() if key not in deliveries], root=lake))
    units = []
    for period, (materialization, actual) in latest.items():
        item = deliveries[actual["upstream_batch_id"]]["items"].get((freq, period))
        version = file_version(raw_path(lake, freq, period))
        if item is None or item["version"] != version:
            raise ValueError("silver_raw_file_not_in_completion")
        if materialization.event_log_entry.run_id != actual["producer_run_id"]:
            raise ValueError("silver_raw_producer_run_mismatch")
        units.append({"freq": freq, "period": period, "source": str(raw_path(lake, freq, period)),
                      "target": str(target_path(lake, freq, period)), "source_version": version,
                      "source_completion": actual, "asof": max(origin["asof"], item["asof"])})
    return units, evidence


def deliver_update_asset(context, config, lake, staging, freq):
    """Read the complete Raw range anew, rebuild every Silver file, record native facts."""
    import dagster as dg
    from dagster._core.definitions.asset_checks.asset_check_evaluation import (
        AssetCheckEvaluation,
        AssetCheckEvaluationTargetMaterializationData,
    )

    from orchestrator.defs.asset_guards.stock_period_delivery import (
        native_run_records,
        read_completion,
    )
    from orchestrator.defs.bootstrap.stock_period_history import writer
    from orchestrator.defs.io.stock_period_raw import (
        _BUDGET,
        DEFAULT_POLICY,
        StorageBudget,
        connection,
        execute,
        file_digest,
        process_memory_budget,
        publish_period,
        storage_record,
        storage_reserve,
    )
    from orchestrator.defs.run_contracts.stock_period_delivery import (
        SILVER_SCOPE_KEY,
        silver_update_run_tags,
        silver_update_scope,
    )
    from orchestrator.defs.run_contracts.stock_period_silver import check_names

    lake, staging = validate_roots(lake, staging)
    origin = read_completion(context.instance, config.source_completion, root=lake)
    business_date = origin["asof"]
    units, _ = resolve_update_sources(lake, freq, config.source_completion, context.instance, origin=origin)
    if not units or units[-1]["period"] != context.partition_key:
        raise ValueError("silver_update_anchor_mismatch")
    context.instance.add_run_tags(context.run.run_id, silver_update_run_tags(
        config.source_completion, business_date=business_date, kind=origin["completion"]["kind"]))
    periods = [unit["period"] for unit in units]
    references = {"lifecycle": str(silver_stock_lifecycle_path(lake)), "identity": str(silver_stock_identity_map_path(lake))}
    versions = {key: file_version(path) for key, path in references.items()}
    identity = {"intent": "update", "run_id": context.run.run_id, "asof": business_date,
                "lower": "2014-01-01", "reference_versions": versions}
    work = durable_directory(run_directory(staging, context.run.run_id))
    last_checked, cancelled = float("-inf"), False

    def cancel():
        nonlocal last_checked, cancelled
        if time.monotonic() - last_checked >= 2:
            last_checked = time.monotonic()
            run = context.instance.get_run_by_id(context.run.run_id)
            cancelled = run is not None and run.status in (dg.DagsterRunStatus.CANCELING, dg.DagsterRunStatus.CANCELED)
        return cancelled

    def assert_inputs(unit):
        if file_version(unit["source"]) != unit["source_version"]:
            raise ValueError("silver_source_changed")
        if any(file_version(path) != versions[key] for key, path in references.items()):
            raise ValueError("silver_reference_changed")

    progress = lambda value: context.log.info(str(value))
    with writer(staging), writer_lock(staging), process_memory_budget(DEFAULT_POLICY):
        budget = StorageBudget(work, DEFAULT_POLICY, cancel=cancel, progress=progress)
        token = _BUDGET.set(budget)
        try:
            yield dg.AssetObservation(asset_key=context.asset_key, metadata={SILVER_SCOPE_KEY: dg.MetadataValue.json(
                silver_update_scope(context.run.run_id, freq, business_date, config.source_completion, periods, phase="planned"))})
            completed = []
            with connection(work, DEFAULT_POLICY) as con, cancellation(con, cancel) as requested:
                load_references(con, references)
                for unit in units:
                    check_cancel(requested)
                    assert_inputs(unit)
                    progress({"stage": "silver_period", "freq": freq, "period": unit["period"],
                              "done": len(completed), "total": len(units)})
                    target = safe_path(unit["target"])
                    before = file_version(target) if target.exists() else None
                    candidate = durable_directory(work / "candidates" / freq) / (unit["period"] + ".parquet")
                    storage_reserve(unit["source_version"][2], spill=True)
                    select_period(con, unit["source"], freq, unit["period"], asof=unit["asof"])
                    execute(con, f"COPY (SELECT {COLUMNS} FROM silver_selected ORDER BY ts_code) TO ? (FORMAT PARQUET,COMPRESSION ZSTD)",
                            [str(candidate)], cancel=requested, progress=progress, stage="silver_candidate")
                    storage_record(candidate)
                    rows = validate_projection(con, candidate, freq, unit["period"])
                    assert_inputs(unit)
                    record = {**unit, "candidate": str(candidate), "candidate_version": file_version(candidate),
                              "target_preimage": before, "rows": rows, "sha256": file_digest(candidate)}
                    record = publish_period(record, cancel=requested)
                    remember_validation(record, identity)
                    completed.append(record)
                    metadata = materialization_metadata(record, identity)
                    if unit["period"] == context.partition_key:
                        yield dg.MaterializeResult(metadata=metadata)
                    else:
                        yield dg.AssetMaterialization(asset_key=context.asset_key, partition=unit["period"], metadata=metadata)
            # Every materialization above is persisted before its check binding is read.
            mats = {record.asset_materialization.partition: record for record in native_run_records(
                context.instance, [context.run.run_id], ["ASSET_MATERIALIZATION"])
                if record.asset_materialization.asset_key == context.asset_key}
            for record in completed:
                check_cancel(cancel)
                assert_inputs(record)
                if file_version(record["target"]) != record["version"]:
                    raise ValueError("silver_event_file_changed")
                if record["period"] == context.partition_key:
                    continue  # The original asset job executes its three checks after this generator.
                materialization = mats[record["period"]]
                for name in check_names(freq):
                    yield AssetCheckEvaluation(asset_key=context.asset_key, check_name=name, partition=record["period"],
                        passed=True, blocking=True, target_materialization_data=AssetCheckEvaluationTargetMaterializationData(
                            storage_id=materialization.storage_id, run_id=context.run.run_id,
                            timestamp=materialization.event_log_entry.timestamp))
            yield dg.AssetObservation(asset_key=context.asset_key, metadata={SILVER_SCOPE_KEY: dg.MetadataValue.json(
                silver_update_scope(context.run.run_id, freq, business_date, config.source_completion, periods, phase="files_complete"))})
        finally:
            _BUDGET.reset(token)


def evaluate_update_sensor(context, *, freq, staging_root=None):
    """Consume one complete native Raw delivery; failed runs need a complete rerun."""
    import dagster as dg

    from orchestrator.defs.asset_guards.stock_period_delivery import (
        read_completion,
        silver_completion_consumed,
    )
    from orchestrator.defs.run_contracts.requests import build_run_request
    from orchestrator.defs.run_contracts.run_keys import (
        build_upstream_triggered_run_key,
    )
    from orchestrator.defs.run_contracts.stock_period_delivery import (
        COMPLETION_KEY,
        validate_delivery_completion,
    )
    from orchestrator.defs.run_contracts.stock_period_silver import asset_name

    state = {"schema_version": 2, "after": 0}

    def result(reason, requests=()):
        state.update(decision=reason, evaluated_at=datetime.now(ZoneInfo("Asia/Shanghai")).isoformat())
        context.update_cursor(json.dumps(state, separators=(",", ":")))
        return dg.SensorResult(run_requests=list(requests), skip_reason=dg.SkipReason(reason) if not requests else None)

    try:
        if context.cursor:
            state = json.loads(context.cursor)
            if not isinstance(state, dict) or state.get("schema_version") != 2 or type(state.get("after")) is not int or state["after"] < 0:
                raise ValueError("silver_sensor_cursor_requires_cutover")
        from orchestrator.defs.paths import DEFAULT_LAKE_STAGING_ROOT

        lake, _ = validate_roots(context.resources.lake_root.root(), Path(staging_root or DEFAULT_LAKE_STAGING_ROOT))
        pending = state.get("pending")
        if pending is None:
            records = context.instance.fetch_observations(dg.AssetRecordsFilter(
                asset_key=dg.AssetKey(f"raw_tushare_stk_period_bar_adj_{freq}"), after_storage_id=state["after"]),
                limit=2, ascending=True).records
            for record in records:
                value = record.asset_observation.metadata.get(COMPLETION_KEY)
                if value is None:
                    state["after"] = record.storage_id
                    continue
                reference = validate_delivery_completion(value.value, freq)
                pending = {"observation_id": record.storage_id, "source_completion": reference}
                state["pending"] = pending
                break
            if pending is None:
                return result("silver_no_completion")
        reference = pending["source_completion"]
        producer = context.instance.get_run_by_id(reference["producer_run_id"])
        if producer is None:
            raise ValueError("silver_raw_producer_missing")
        if producer.status in (dg.DagsterRunStatus.FAILURE, dg.DagsterRunStatus.CANCELED):
            state["after"] = pending["observation_id"]
            state.pop("pending")
            return result("silver_raw_run_failed")
        if producer.status != dg.DagsterRunStatus.SUCCESS:
            return result("silver_raw_checks_pending")
        origin = read_completion(context.instance, reference, root=lake)
        minimum = "2014-01-03" if freq == "week" else "2014-01"
        periods = sorted(p for f, p in origin["items"] if f == freq and p >= minimum)
        if not periods or silver_completion_consumed(context.instance, reference, periods, root=lake, business_date=origin["asof"]):
            state["after"] = pending["observation_id"]
            state.pop("pending")
            return result("silver_batch_complete")
        asset, job = asset_name(freq), asset_name(freq) + "_update_job"
        run_key = build_upstream_triggered_run_key(consumer=asset, upstream_batch_id=reference["upstream_batch_id"])
        previous = context.instance.get_runs(filters=dg.RunsFilter(job_name=job, tags={"dagster/run_key": run_key}), limit=1)
        if previous:
            return result("silver_run_requires_review:" + previous[0].run_id)
        units, _ = resolve_update_sources(lake, freq, reference, context.instance, origin=origin)
        config = {"intent": "update", "source_completion": reference}
        return result("silver_requested", [build_run_request(run_key=run_key, job_name=job,
            partition_key=units[-1]["period"], run_config={"ops": {asset: {"config": config}}})])
    except (ValueError, TypeError, OSError) as error:
        return result(str(error))
