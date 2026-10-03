"""Single-week delivery with bounded requests and independent durable captures."""

from __future__ import annotations

import csv
import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from orchestrator.defs.bootstrap.stock_weekly_candidates import (
    fingerprint,
    partition_path,
    validate_root,
)
from orchestrator.defs.bootstrap.stock_weekly_capture import (
    WeeklyCaptureError,
    WeeklyCaptureStore,
    _atomic_json,
    capture_file_hash,
    check_capture_path,
)
from orchestrator.defs.bootstrap.stock_weekly_promote import promote_weekly_candidates
from orchestrator.defs.duckdb_connection import (
    DuckDBConnectionSettings,
    connect_configured_duckdb,
)
from orchestrator.defs.io.stock_weekly_raw import (
    WEEK_SQL,
    assemble_relation,
    load_relation,
    relation_hashes,
    validate_relation,
    write_and_audit_candidates,
)
from orchestrator.defs.run_contracts.stock_weekly import (
    ProdWeeklyUnit,
    StockWeeklyPointPolicy,
    StockWeeklySource,
    WeeklyBudget,
    WeeklyPlanManifest,
    WeeklySourceUnit,
    normalize_week_key,
    normalize_weekly_code,
    stable_weekly_hash,
    weekly_column_specs,
    weekly_schema_hash,
    weekly_source_api,
)
from orchestrator.defs.stock_weekly_source import fetch_weekly_request_supervised


def _request_progress(progress, payload):
    next_at = 0.0

    def emit():
        nonlocal next_at
        now = time.monotonic()
        if now >= next_at:
            progress(payload)
            next_at = now + 10

    return emit


@dataclass(frozen=True)
class StockWeeklyPointWorker:
    token: str = field(repr=False)
    source: StockWeeklySource

    def __call__(self, params, fields, max_rows):
        from orchestrator.defs.resources import TushareResource

        result = TushareResource(token=self.token).call(
            weekly_source_api(self.source), params, fields
        )
        return pd.DataFrame(result.rows, columns=result.columns, dtype=object)


def read_weekly_codes(path: str | None) -> tuple[tuple[str, ...], dict]:
    if not path:
        raise WeeklyCaptureError("code_list_required")
    reference = Path(path)
    check_capture_path(reference)
    repo = Path(__file__).resolve().parents[5]
    import tempfile

    roots = (
        repo / "reports",
        Path("/Volumes/datasource/data_lake_staging"),
        Path("/private/tmp"),
        Path(tempfile.gettempdir()).resolve(),
    )
    if (
        not any(reference.is_relative_to(root) for root in roots)
        or reference.stat().st_size > 65536
    ):
        raise WeeklyCaptureError("code_list_path_forbidden")
    before = capture_file_hash(reference)
    with reference.open() as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != ["ts_code"]:
            raise WeeklyCaptureError("code_list_schema_invalid")
        codes = []
        for row in reader:
            codes.append(normalize_weekly_code(row["ts_code"]))
            if len(codes) > WeeklyBudget().objects_per_batch:
                raise WeeklyCaptureError("code_list_budget_exceeded")
    if (
        not codes
        or len(codes) != len(set(codes))
        or capture_file_hash(reference) != before
    ):
        raise WeeklyCaptureError("code_list_invalid")
    return tuple(sorted(codes)), {"path": str(reference), "sha256": before}


def deliver_stock_weekly_point(
    source,
    week,
    *,
    target_root,
    staging_root,
    worker,
    code_list_path=None,
    cancel=lambda: False,
    progress=lambda payload: None,
    fetch=fetch_weekly_request_supervised,
):
    normalize_week_key(week)
    validate_root(target_root, staging=False)
    validate_root(staging_root, staging=True)
    if (
        target_root == staging_root
        or target_root.is_relative_to(staging_root)
        or staging_root.is_relative_to(target_root)
    ):
        raise WeeklyCaptureError("weekly_roots_overlap")
    if source is not StockWeeklySource.ALTERNATE_WEEKLY and code_list_path is not None:
        raise WeeklyCaptureError("primary_code_list_forbidden")
    codes, code_evidence = (
        read_weekly_codes(code_list_path)
        if source is StockWeeklySource.ALTERNATE_WEEKLY
        else ((), None)
    )
    budget, policy = WeeklyBudget(), StockWeeklyPointPolicy()
    intent = {
        "source": source.value,
        "week": week,
        "codes": codes,
        "code_evidence": code_evidence,
        "budget": asdict(budget),
        "policy": asdict(policy),
        "write_mode": "create_or_identical",
    }
    plan_hash = stable_weekly_hash(intent)
    assembly = (
        staging_root
        / "stock_weekly_raw"
        / plan_hash
        / "assemblies"
        / f"point-{uuid.uuid4().hex}"
    )
    check_capture_path(assembly)
    assembly.mkdir(parents=True)
    _atomic_json(assembly / "intent.json", intent)
    settings = DuckDBConnectionSettings(
        temp_directory=assembly / "spill",
        memory_limit=budget.duckdb_memory_limit,
        threads=budget.duckdb_threads,
        max_temp_directory_size=budget.duckdb_max_temp,
    )
    requests, inputs, evidence, receipt_index = 0, [], [], []
    if code_evidence:
        evidence.append(code_evidence)
    evidence.append(
        {
            "path": str(assembly / "intent.json"),
            "sha256": capture_file_hash(assembly / "intent.json"),
        }
    )
    fields = tuple(n for n, _, _ in weekly_column_specs(source))
    request_cap = (len(codes) if codes else policy.page_call_cap) * (
        budget.max_retries + 1
    )
    last_call = 0.0
    with connect_configured_duckdb(settings) as connection:
        connection.execute("SET autoinstall_known_extensions=false")
        connection.execute("SET autoload_known_extensions=false")
        total = 0
        for index in range(len(codes) if codes else policy.page_call_cap):
            if cancel():
                raise WeeklyCaptureError("canceled")
            anchor = date.fromisoformat(week)
            params = (
                {
                    "ts_code": codes[index],
                    "start_date": (anchor - timedelta(days=4)).strftime("%Y%m%d"),
                    "end_date": (anchor + timedelta(days=2)).strftime("%Y%m%d"),
                }
                if codes
                else {
                    "trade_date": week.replace("-", ""),
                    "freq": "week",
                    "limit": policy.page_limit,
                    "offset": index * policy.page_limit,
                }
            )
            for retry in range(budget.max_retries + 1):
                while time.monotonic() - last_call < budget.minimum_interval_seconds:
                    if cancel():
                        raise WeeklyCaptureError("canceled")
                    time.sleep(0.05)
                requests += 1
                if requests > request_cap:
                    raise WeeklyCaptureError("point_request_cap_exceeded")
                _atomic_json(
                    assembly / "requests.json",
                    {
                        "calls": requests,
                        "cap": request_cap,
                        "params": params,
                        "stage": "requesting",
                    },
                )
                progress(
                    {
                        "stage": "requesting",
                        "request": requests,
                        "window": week,
                        "object": params.get("ts_code", "full_market"),
                        "page": index,
                        "eta": "暂无法估算",
                    }
                )
                try:
                    frame = fetch(
                        worker,
                        params,
                        fields,
                        1 if codes else policy.page_limit,
                        budget,
                        cancel,
                        _request_progress(
                            progress,
                            {
                                "stage": "requesting",
                                "request": requests,
                                "window": week,
                                "object": params.get("ts_code", "full_market"),
                                "captured_rows": total,
                                "eta": "暂无法估算",
                            },
                        ),
                    )
                    break
                except WeeklyCaptureError as error:
                    if (
                        str(error) not in ("source_failed", "source_timeout")
                        or retry == budget.max_retries
                    ):
                        raise
                finally:
                    last_call = time.monotonic()
            total += len(frame)
            if total > budget.max_codes:
                raise WeeklyCaptureError("point_row_budget_exceeded")
            page_codes = tuple(sorted(set(frame.ts_code)))
            if codes and any(c != codes[index] for c in page_codes):
                raise WeeklyCaptureError("source_code_mismatch")
            unit = ProdWeeklyUnit(
                stable_weekly_hash({"intent": plan_hash, "index": index}),
                source,
                page_codes,
                date(anchor.year, 1, 1),
                date(anchor.year + 1, 1, 1),
                weekly_schema_hash(source),
                policy.page_limit,
            )
            if codes:
                unit = WeeklySourceUnit(
                    unit.unit_id,
                    source,
                    codes[index],
                    week,
                    week,
                    anchor - timedelta(days=4),
                    anchor + timedelta(days=2),
                    str(assembly / "intent.json"),
                    stable_weekly_hash([week]),
                    1,
                    1,
                    (),
                    (),
                )
            # The reusable typed capture validator treats this as transport; no Prod call.
            manifest = WeeklyPlanManifest(
                plan_hash,
                source,
                str(assembly / "intent.json"),
                capture_file_hash(assembly / "intent.json"),
                (unit,),
                budget,
                0,
                len(frame),
                0,
                (),
            )
            store = WeeklyCaptureStore(assembly / f"page-{index}", manifest)
            with store.locked():
                attempt = store.begin_attempt(unit)
                chunk = store.write_chunk(connection, frame, unit, attempt, 0)
                receipt = store.seal(
                    connection,
                    unit,
                    [chunk],
                    len(frame),
                    {
                        "api_name": weekly_source_api(source),
                        "params": params,
                        "fields": fields,
                    },
                )
                receipt_path, _ = store.validated_receipt(connection, unit)
                evidence.append(
                    {
                        "path": str(receipt_path),
                        "sha256": capture_file_hash(receipt_path),
                    }
                )
                path = receipt_path.parent / chunk["path"]
                evidence.append({"path": str(path), "sha256": chunk["sha256"]})
                inputs.append(path)
                receipt_index.append(
                    {
                        "unit": json.loads(json.dumps(asdict(unit), default=str)),
                        "receipt": str(receipt_path),
                        "rows": receipt["source_rows"],
                    }
                )
            if not codes and len(frame) < policy.page_limit:
                break
        else:
            if not codes:
                raise WeeklyCaptureError("point_page_cap_exceeded")
        if not codes and total == 0:
            raise WeeklyCaptureError("point_source_empty")
        load_relation(connection, "weekly_input", inputs, source)
        validate_relation(connection, "weekly_input", source, budget, unique=True)
        if connection.execute(
            f"SELECT count(*) FROM weekly_input WHERE {WEEK_SQL}<>?", [week]
        ).fetchone()[0]:
            raise WeeklyCaptureError("source_week_mismatch")
        if (
            source is not StockWeeklySource.ALTERNATE_WEEKLY
            and connection.execute(
                "SELECT count(*) FROM weekly_input WHERE trade_date<>?",
                [week.replace("-", "")],
            ).fetchone()[0]
        ):
            raise WeeklyCaptureError("primary_point_date_mismatch")
        target = partition_path(target_root, source, week)
        baseline = fingerprint(target)
        load_relation(
            connection, "weekly_existing", [target] if target.exists() else [], source
        )
        if target.exists() and relation_hashes(
            connection, "weekly_existing", source, budget
        ).keys() != {week}:
            raise WeeklyCaptureError("target_partition_mismatch")
        stats = assemble_relation(connection, source, anchor.year, budget, ())
        if baseline is not None and stats["new_keys"]:
            raise WeeklyCaptureError("create_or_identical_conflict")
        hashes, paths = write_and_audit_candidates(
            connection, source, budget, assembly / "candidate"
        )
        if not paths:
            raise WeeklyCaptureError("point_source_empty")
        if len(paths) != 1:
            raise WeeklyCaptureError("point_partition_count_mismatch")
        candidate = paths[0]
        with candidate.open("rb") as stream:
            import os

            os.fsync(stream.fileno())
        files = [
            {
                "week": week,
                "candidate": str(candidate),
                "target": str(target),
                "baseline": baseline,
                "sha256": capture_file_hash(candidate),
                **hashes[week],
            }
        ]
        audit = {
            "version": 1,
            "plan_hash": plan_hash,
            "source": source.value,
            "schema_hash": weekly_schema_hash(source),
            "year": anchor.year,
            "capture_root": str(staging_root),
            "target_root": str(target_root),
            "assembly": str(assembly),
            "partial_scope": False,
            "excluded_week_keys": [],
            "budget": asdict(budget),
            "source_evidence": evidence,
            "files": files,
            "stats": stats,
            "value_difference_rows": 0,
            "source_key_outcomes": None,
            "point_receipts": receipt_index,
            "manifest_hash": stable_weekly_hash(intent),
            "candidate_manifest_hash": stable_weekly_hash(files),
            "target_baseline_hash": stable_weekly_hash(
                [(f["target"], f["baseline"]) for f in files]
            ),
            "source_evidence_hash": stable_weekly_hash(evidence),
        }
        audit["audit_hash"] = stable_weekly_hash(audit)
        _atomic_json(assembly / "audit.json", audit)
    promote_weekly_candidates(
        assembly / "audit.json", apply=True, cancel=cancel, progress=progress
    )
    return {
        "path": str(target),
        "rows": stats["candidate_rows"],
        "source_rows": total,
        "audit_path": str(assembly / "audit.json"),
        "audit_hash": audit["audit_hash"],
        "source": source.value,
        "week": week,
        "delivery_method": "tushare_week_point",
        "requests": requests,
    }
