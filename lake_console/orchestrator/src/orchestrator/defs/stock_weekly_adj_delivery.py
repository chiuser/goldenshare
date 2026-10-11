"""Capture one closed Prod batch and assemble bounded annual Raw candidates."""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from orchestrator.defs.bootstrap.stock_weekly_candidates import (
    fingerprint,
    partition_path,
    validate_root,
)
from orchestrator.defs.bootstrap.stock_weekly_capture import (
    WeeklyCaptureError,
    _atomic_json,
    _sync_directory,
    check_capture_path,
    check_weekly_cancel,
)
from orchestrator.defs.bootstrap.stock_weekly_promote import read_audit
from orchestrator.defs.duckdb_connection import (
    DuckDBConnectionSettings,
    connect_configured_duckdb,
)
from orchestrator.defs.io.stock_weekly_raw import (
    WEEK_SQL,
    assemble_adjusted_delivery_relation,
    columns,
    load_relation,
    write_and_audit_candidates,
)
from orchestrator.defs.prod_db.stock_weekly_adj_delivery import header_record_matches
from orchestrator.defs.run_contracts.stock_weekly import (
    StockWeeklySource,
    stable_weekly_hash,
    weekly_column_specs,
    weekly_schema_hash,
)
from orchestrator.defs.run_contracts.stock_weekly_adj_delivery import (
    DeliveryHeader,
    WeeklyAdjProdDeliveryBudget,
    delivery_digest,
    source_date,
    source_week,
)

ADJUSTED_SOURCE = StockWeeklySource.PRIMARY_ADJUSTED


def _json_size(value):
    return sum(
        len(chunk.encode())
        for chunk in json.JSONEncoder(
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).iterencode(value)
    )


def _read_json(path, byte_limit):
    check_capture_path(path)
    if path.stat().st_size > byte_limit:
        raise WeeklyCaptureError("adjusted_delivery_local_budget_exceeded")
    try:
        value = json.loads(path.read_text())
    except (ValueError, UnicodeError):
        raise WeeklyCaptureError("adjusted_delivery_local_json_invalid") from None
    if not isinstance(value, dict):
        raise WeeklyCaptureError("adjusted_delivery_local_json_invalid")
    return value


def _verify_record_payload(record):
    if stable_weekly_hash(record["payload"]) != record["payload_digest"]:
        raise WeeklyCaptureError("adjusted_delivery_payload_digest_mismatch")


def _capture_record(reader, header, kind, identity, path, limit, cancel, progress):
    check_weekly_cancel(cancel)
    if path.exists():
        record = _read_json(path, limit)
    else:
        record = reader.read_record(
            header, kind, identity, cancel=cancel, progress=progress
        )
        _verify_record_payload(record)
        check_weekly_cancel(cancel)
        _atomic_json(path, record)
    if (
        record["batch_id"] != header.batch_id
        or type(record["contract_version"]) is not int
        or record["contract_version"] != header.contract_version
        or record["scope_digest"] != header.scope_digest
        or record["cutoff_week"] != header.cutoff_week
        or record["record_kind"] != kind
        or type(record["revision"]) is not int
        or not 0 < record["revision"] <= header.revision
    ):
        raise WeeklyCaptureError("adjusted_delivery_record_identity_mismatch")
    if kind == "unit" and record["unit_id"] != identity:
        raise WeeklyCaptureError("adjusted_delivery_unit_identity_mismatch")
    _verify_record_payload(record)
    return record


def validate_closed_unit(record, planned, header, budget):
    """Bounded transport validation, including Decimal text and original Raw codes."""
    if record["intent"].get("bootstrap") is not False:
        raise WeeklyCaptureError("adjusted_delivery_bootstrap_requires_raw_capture")
    payload = record["payload"]
    if not isinstance(payload, dict) or set(payload) != {"rows"}:
        raise WeeklyCaptureError("adjusted_delivery_unit_payload_invalid")
    rows = payload["rows"]
    if not isinstance(rows, list) or len(rows) > budget.max_unit_rows:
        raise WeeklyCaptureError("adjusted_delivery_unit_row_budget_exceeded")
    payload_bytes = _json_size(payload)
    if payload_bytes > budget.max_unit_payload_bytes:
        raise WeeklyCaptureError("adjusted_delivery_unit_payload_budget_exceeded")
    counts = [
        record[n]
        for n in ("rows_received", "rows_unique", "rows_written", "rows_preserved")
    ]
    if (
        any(type(n) is not int or n < 0 for n in counts)
        or not record["rows_written"] == record["rows_unique"] == len(rows)
        or not len(rows) <= record["rows_received"] <= budget.max_unit_rows
    ):
        raise WeeklyCaptureError("adjusted_delivery_unit_counts_invalid")
    params = planned["params"]
    kind = planned["progress"]["unit_kind"]
    if (
        kind not in ("point_week", "stock_history")
        or record["unit_kind"] != kind
        or params.get("freq") != "week"
        or planned["unit_id"] != record["unit_id"]
    ):
        raise WeeklyCaptureError("adjusted_delivery_unit_scope_invalid")
    point = planned["trade_date"]
    if kind == "point_week":
        if point is None or source_week(params["trade_date"]) != point:
            raise WeeklyCaptureError("adjusted_delivery_unit_scope_invalid")
        begin = end = point
    else:
        begin = date.fromisoformat(record["start_date"]).isoformat()
        end = date.fromisoformat(record["end_date"]).isoformat()
        if (
            point is not None
            or params["end_date"] != end.replace("-", "")
            or params["start_date"] != begin.replace("-", "")
            or record["ts_code"] != params.get("ts_code")
            or begin > end
        ):
            raise WeeklyCaptureError("adjusted_delivery_unit_scope_invalid")
    if point is not None and end > header.cutoff_week:
        raise WeeklyCaptureError("adjusted_delivery_unit_scope_invalid")
    expected = {n for n, _, _ in weekly_column_specs(ADJUSTED_SOURCE)}
    previous = None
    maximum = None
    for row in rows:
        if not isinstance(row, dict) or set(row) != expected:
            raise WeeklyCaptureError("adjusted_delivery_source_schema_invalid")
        code = row["ts_code"]
        if (
            not isinstance(code, str)
            or not code.strip()
            or len(code) > 16
            or row["freq"] != "week"
        ):
            raise WeeklyCaptureError("adjusted_delivery_source_key_invalid")
        week = source_week(row["trade_date"])
        if not begin <= week <= min(end, header.cutoff_week) or (
            params.get("ts_code") and code != params["ts_code"]
        ):
            raise WeeklyCaptureError("adjusted_delivery_source_scope_mismatch")
        if row["end_date"] is not None:
            source_date(row["end_date"])
        for name, kind_name, _ in weekly_column_specs(ADJUSTED_SOURCE)[4:]:
            value = row[name]
            if value is None:
                continue
            precision = int(kind_name.removeprefix("DECIMAL(").split(",")[0])
            try:
                number = Decimal(value) if isinstance(value, str) else None
                if (
                    number is None
                    or not number.is_finite()
                    or abs(number) >= Decimal(10) ** (precision - 4)
                    or format(number, ".4f") != value
                    or number == 0
                    and value != "0.0000"
                ):
                    raise InvalidOperation
            except (ValueError, InvalidOperation):
                raise WeeklyCaptureError(
                    "adjusted_delivery_source_decimal_invalid"
                ) from None
        key = (code, row["trade_date"], "week")
        if previous is not None and previous >= key:
            raise WeeklyCaptureError("adjusted_delivery_source_keys_not_unique_sorted")
        previous = key
        maximum = max(maximum or week, week)
    return {
        "payload_bytes": payload_bytes,
        "max_input_week": maximum,
        "rows": len(rows),
    }


def _settings(directory, budget):
    weekly = budget.weekly_budget()
    return DuckDBConnectionSettings(
        temp_directory=directory,
        memory_limit=weekly.duckdb_memory_limit,
        threads=weekly.duckdb_threads,
        max_temp_directory_size=weekly.duckdb_max_temp,
    )


def _capture_unit_chunks(record, record_path, directory, budget, cancel):
    check_weekly_cancel(cancel)
    receipt_path = directory / "capture.json"
    if receipt_path.exists():
        receipt = _read_json(receipt_path, budget.max_closure_bytes)
        if receipt["record_sha256"] != fingerprint(record_path):
            raise WeeklyCaptureError("adjusted_delivery_captured_record_changed")
        for item in receipt["chunks"]:
            path = directory / item["path"]
            check_capture_path(path)
            if (
                not path.is_relative_to(directory)
                or fingerprint(path) != item["sha256"]
            ):
                raise WeeklyCaptureError("adjusted_delivery_capture_changed")
        return receipt["chunks"]
    # A crash before the receipt freezes no capture. Use a fresh attempt, never
    # treat an incomplete directory as a successful unit.
    import uuid

    attempt = directory / f"capture-{uuid.uuid4().hex}"
    attempt.mkdir()
    fields = weekly_column_specs(ADJUSTED_SOURCE)
    projection = ",".join(f'r.value."{n}" AS "{n}"' for n, t, _ in fields)
    structure = json.dumps([{n: t for n, t, _ in fields}])
    with connect_configured_duckdb(_settings(attempt / "spill", budget)) as con:
        con.execute(
            f"CREATE TEMP TABLE weekly_captured AS SELECT {projection},"
            "CAST(? AS VARCHAR) AS _unit_id, CAST(? AS BIGINT) AS _unit_revision,"
            "CAST(? AS VARCHAR) AS _unit_kind FROM (SELECT "
            "unnest(json_transform_strict(json_extract(j.json,'$.payload.rows'),?)) AS value "
            "FROM read_json_objects(?) j) r",
            [
                record["unit_id"],
                record["revision"],
                record["unit_kind"],
                structure,
                str(record_path),
            ],
        )
        if (
            con.execute("SELECT count(*) FROM weekly_captured").fetchone()[0]
            != record["rows_unique"]
        ):
            raise WeeklyCaptureError("adjusted_delivery_capture_count_mismatch")
        if record["rows_unique"]:
            con.execute(
                f"COPY (SELECT {columns(ADJUSTED_SOURCE)},_unit_id,_unit_revision,_unit_kind,"
                f"substr({WEEK_SQL},1,4) AS input_year FROM weekly_captured ORDER BY ts_code,trade_date,freq) "
                "TO ? (FORMAT PARQUET, COMPRESSION ZSTD, PARTITION_BY(input_year),"
                " WRITE_PARTITION_COLUMNS false, FILENAME_PATTERN 'part-{i}')",
                [str(attempt / "chunks")],
            )
        chunks = []
        for path in sorted((attempt / "chunks").glob("input_year=*/*.parquet")):
            check_weekly_cancel(cancel)
            rows = con.execute(
                "SELECT count(*) FROM read_parquet(?,hive_partitioning=false)",
                [str(path)],
            ).fetchone()[0]
            with path.open("rb") as stream:
                os.fsync(stream.fileno())
            _sync_directory(path.parent)
            chunks.append(
                {
                    "year": int(path.parent.name.removeprefix("input_year=")),
                    "path": str(path.relative_to(directory)),
                    "rows": rows,
                    "sha256": fingerprint(path),
                }
            )
        if sum(c["rows"] for c in chunks) != record["rows_unique"]:
            raise WeeklyCaptureError("adjusted_delivery_capture_count_mismatch")
    _atomic_json(
        receipt_path, {"record_sha256": fingerprint(record_path), "chunks": chunks}
    )
    return chunks


def capture_closed_adjusted_batch(
    reader,
    header: DeliveryHeader,
    *,
    staging_root,
    budget=None,
    cancel=lambda: False,
    progress=lambda _: None,
):
    budget = budget or WeeklyAdjProdDeliveryBudget()
    header.validate_budget(budget)
    if header.header["bootstrap"] or header.record_kind != "batch_closed":
        raise WeeklyCaptureError("adjusted_delivery_bootstrap_requires_raw_capture")
    validate_root(staging_root, staging=True)
    root = staging_root / "stock_weekly_adj_delivery" / header.intent_id
    check_capture_path(root)
    root.mkdir(parents=True, exist_ok=True)
    closure = _capture_record(
        reader,
        header,
        header.record_kind,
        header.revision,
        root / "closure.json",
        budget.max_closure_bytes,
        cancel,
        progress,
    )
    if not header_record_matches(header, closure) or set(closure["payload"]) != {
        "header",
        "unit_ids",
    }:
        raise WeeklyCaptureError("adjusted_delivery_closure_mismatch")
    ids = closure["payload"]["unit_ids"]
    if (
        not isinstance(ids, list)
        or len(ids) != header.header["unit_count"]
        or len(ids) != len(set(ids))
    ):
        raise WeeklyCaptureError("adjusted_delivery_unit_set_mismatch")
    for unit_id in ids:
        delivery_digest(unit_id)
    plan = _capture_record(
        reader,
        header,
        "plan",
        "plan",
        root / "plan.json",
        budget.max_plan_bytes + 16 * 1024,
        cancel,
        progress,
    )
    if _json_size(plan["payload"]) > budget.max_plan_bytes:
        raise WeeklyCaptureError("adjusted_delivery_plan_budget_exceeded")
    planned_units = plan["payload"]["units"]
    if [u["unit_id"] for u in planned_units] != ids or plan["payload"][
        "execution_context"
    ]["contract_digest"] != header.header["contract_digest"]:
        raise WeeklyCaptureError("adjusted_delivery_unit_set_mismatch")
    units, summaries, rows, received, preserved, payload_bytes, maximum = (
        [],
        [],
        0,
        0,
        0,
        0,
        None,
    )
    for planned in planned_units:
        check_weekly_cancel(cancel)
        directory = root / "units" / planned["unit_id"]
        check_capture_path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        record_path = directory / "record.json"
        record = _capture_record(
            reader,
            header,
            "unit",
            planned["unit_id"],
            record_path,
            budget.max_unit_payload_bytes + 16 * 1024,
            cancel,
            progress,
        )
        if (
            record["revision"] <= plan["revision"]
            or record["revision"] >= header.revision
        ):
            raise WeeklyCaptureError("adjusted_delivery_unit_revision_invalid")
        stats = validate_closed_unit(record, planned, header, budget)
        chunks = _capture_unit_chunks(record, record_path, directory, budget, cancel)
        units.append(
            {
                "unit_id": record["unit_id"],
                "revision": record["revision"],
                "chunks": chunks,
                **stats,
            }
        )
        summaries.append(
            {"unit_id": record["unit_id"], "digest": record["payload_digest"]}
        )
        rows += stats["rows"]
        received += record["rows_received"]
        preserved += record["rows_preserved"]
        payload_bytes += stats["payload_bytes"]
        if stats["max_input_week"] is not None:
            maximum = max(maximum or stats["max_input_week"], stats["max_input_week"])
        if payload_bytes > budget.max_batch_payload_bytes:
            raise WeeklyCaptureError("adjusted_delivery_batch_budget_exceeded")
        progress(
            {
                "stage": "capture",
                "completed_units": len(units),
                "total_units": len(ids),
                "rows": rows,
            }
        )
    if (
        stable_weekly_hash(summaries) != header.header["units_digest"]
        or payload_bytes != header.header["total_payload_bytes"]
        or rows != header.rows_written
        or received != header.rows_received
        or preserved != header.rows_preserved
        or maximum != header.anchor_partition
    ):
        raise WeeklyCaptureError("adjusted_delivery_batch_reconciliation_failed")
    manifest = {"version": 1, "header": asdict(header), "units": units}
    if (root / "capture.json").exists() and _read_json(
        root / "capture.json", budget.max_plan_bytes
    ) != manifest:
        raise WeeklyCaptureError("adjusted_delivery_capture_manifest_changed")
    _atomic_json(root / "capture.json", manifest)
    return root, manifest


def prepare_adjusted_delivery_year(
    root,
    manifest,
    *,
    target_root,
    year,
    budget=None,
    cancel=lambda: False,
    progress=lambda _: None,
):
    budget = budget or WeeklyAdjProdDeliveryBudget()
    validate_root(target_root, staging=False)
    header = DeliveryHeader(**manifest["header"])
    validate_root(root.parents[1], staging=True)
    check_capture_path(root)
    if (
        root != root.parents[1] / "stock_weekly_adj_delivery" / header.intent_id
        or root.is_relative_to(target_root)
        or target_root.is_relative_to(root)
        or _read_json(root / "capture.json", budget.max_plan_bytes) != manifest
    ):
        raise WeeklyCaptureError("adjusted_delivery_root_invalid")
    if type(year) is not int or not 1900 <= year <= 9999:
        raise WeeklyCaptureError("adjusted_delivery_year_invalid")
    annual_root = root / "assemblies" / str(year)
    check_capture_path(annual_root)
    receipt_path = annual_root / "prepared.json"
    if receipt_path.exists():
        receipt = _read_json(receipt_path, budget.max_control_bytes)
        audit_path = annual_root / receipt["audit"]
        check_capture_path(audit_path)
        if not audit_path.is_relative_to(annual_root):
            raise WeeklyCaptureError("adjusted_delivery_audit_identity_mismatch")
        audit = read_audit(audit_path)
        if (
            audit.get("delivery") != asdict(header)
            or audit["target_root"] != str(target_root)
            or audit["audit_hash"] != receipt["audit_hash"]
            or audit["year"] != year
        ):
            raise WeeklyCaptureError("adjusted_delivery_audit_identity_mismatch")
        return audit_path
    inputs, evidence = (
        [],
        [
            {
                "path": str(root / "capture.json"),
                "sha256": fingerprint(root / "capture.json"),
            }
        ],
    )
    for unit in manifest["units"]:
        delivery_digest(unit["unit_id"])
        directory = root / "units" / unit["unit_id"]
        for chunk in unit["chunks"]:
            if chunk["year"] != year:
                continue
            path = directory / chunk["path"]
            check_capture_path(path)
            if (
                not path.is_relative_to(directory)
                or fingerprint(path) != chunk["sha256"]
            ):
                raise WeeklyCaptureError("adjusted_delivery_capture_changed")
            inputs.append(path)
            evidence.append({"path": str(path), "sha256": chunk["sha256"]})
    if not inputs or len(inputs) > budget.max_phase_files:
        raise WeeklyCaptureError("adjusted_delivery_phase_file_budget_exceeded")
    import uuid

    # Only prepared.json freezes an annual candidate. A crash during assembly
    # leaves an unfinished attempt, and resume builds a fresh candidate.
    assembly = annual_root / f"attempt-{uuid.uuid4().hex}"
    audit_path = assembly / "audit.json"
    assembly.mkdir(parents=True)
    with connect_configured_duckdb(_settings(assembly / "spill", budget)) as con:
        con.execute(
            f"CREATE TEMP TABLE weekly_input AS SELECT {columns(ADJUSTED_SOURCE)},"
            "_unit_id,_unit_revision,_unit_kind FROM read_parquet(?,hive_partitioning=false)",
            [[str(p) for p in inputs]],
        )
        weeks = [
            r[0]
            for r in con.execute(
                f"SELECT DISTINCT {WEEK_SQL} AS week FROM weekly_input ORDER BY week LIMIT ?",
                [budget.max_phase_targets + 1],
            ).fetchall()
        ]
        if len(weeks) > budget.max_phase_targets:
            raise WeeklyCaptureError("adjusted_delivery_phase_target_budget_exceeded")
        existing, baselines = [], {}
        for week in weeks:
            path = partition_path(target_root, ADJUSTED_SOURCE, week)
            if path.parent.exists() and any(
                p != path for p in path.parent.glob("*.parquet")
            ):
                raise WeeklyCaptureError("target_layout_mismatch")
            baselines[week] = fingerprint(path)
            if path.exists():
                existing.append(path)
        if len(inputs) + len(existing) + len(weeks) > budget.max_phase_files:
            raise WeeklyCaptureError("adjusted_delivery_phase_file_budget_exceeded")
        load_relation(con, "weekly_existing", existing, ADJUSTED_SOURCE)
        for path in existing:
            if con.execute(
                f"SELECT count(*) FROM read_parquet(?,hive_partitioning=false) WHERE {WEEK_SQL}<>?",
                [str(path), path.parent.name.removeprefix("week_end=")],
            ).fetchone()[0]:
                raise WeeklyCaptureError("target_partition_mismatch")
        progress(
            {
                "stage": "assemble",
                "year": year,
                "input_files": len(inputs),
                "target_files": len(weeks),
            }
        )
        check_weekly_cancel(cancel)
        stats = assemble_adjusted_delivery_relation(
            con, year=year, budget=budget.weekly_budget()
        )
        expected, paths = write_and_audit_candidates(
            con,
            ADJUSTED_SOURCE,
            budget.weekly_budget(),
            assembly / "candidate",
        )
        files = []
        for path in paths:
            check_weekly_cancel(cancel)
            week = path.parent.name.removeprefix("week_end=")
            target = partition_path(target_root, ADJUSTED_SOURCE, week)
            if fingerprint(target) != baselines[week]:
                raise WeeklyCaptureError("target_changed_during_assembly")
            with path.open("rb") as stream:
                os.fsync(stream.fileno())
            files.append(
                {
                    "week": week,
                    "candidate": str(path),
                    "target": str(target),
                    "baseline": baselines[week],
                    "sha256": fingerprint(path),
                    **expected[week],
                }
            )
        if any(fingerprint(Path(item["path"])) != item["sha256"] for item in evidence):
            raise WeeklyCaptureError("adjusted_delivery_capture_changed")
        audit = {
            "version": 1,
            "plan_hash": header.intent_id,
            "source": ADJUSTED_SOURCE.value,
            "schema_hash": weekly_schema_hash(ADJUSTED_SOURCE),
            "year": year,
            "capture_root": str(root.parents[1]),
            "target_root": str(target_root),
            "assembly": str(assembly),
            "partial_scope": False,
            "excluded_week_keys": [],
            "budget": asdict(budget.weekly_budget()),
            "source_evidence": evidence,
            "files": files,
            "stats": stats,
            "value_difference_rows": 0,
            "source_key_outcomes": None,
            "write_policy": "replace_input_keys",
            "delivery": asdict(header),
            "manifest_hash": stable_weekly_hash(manifest),
        }
        audit["candidate_manifest_hash"] = stable_weekly_hash(files)
        audit["target_baseline_hash"] = stable_weekly_hash(
            [(f["target"], f["baseline"]) for f in files]
        )
        audit["source_evidence_hash"] = stable_weekly_hash(evidence)
        audit["audit_hash"] = stable_weekly_hash(audit)
        _atomic_json(audit_path, audit)
        _atomic_json(
            receipt_path,
            {
                "audit": str(audit_path.relative_to(annual_root)),
                "audit_hash": audit["audit_hash"],
            },
        )
    progress({"stage": "audited", "year": year, "files": len(files), **stats})
    return audit_path
