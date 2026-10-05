"""Persist independent monthly Prod units and verified annual candidates."""

from __future__ import annotations

import os
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from uuid import uuid4

from orchestrator.defs.bootstrap.stock_monthly_files import (
    check_monthly_cancel,
    check_monthly_free_space,
    check_monthly_path,
    check_monthly_root,
    monthly_file_hash,
    monthly_file_lock,
    read_monthly_json,
    sync_monthly_directory,
    sync_monthly_file,
    write_monthly_json,
)
from orchestrator.defs.duckdb_connection import (
    DuckDBConnectionSettings,
    connect_configured_duckdb,
)
from orchestrator.defs.io.stock_monthly_raw import (
    MONTH_SQL,
    canonical_month_hashes,
    load_monthly_csv,
    load_monthly_parquets,
    validate_month_relation,
)
from orchestrator.defs.prod_db.stock_monthly import validate_monthly_export_evidence
from orchestrator.defs.run_contracts.stock_monthly import (
    MonthlyBootstrapIOPolicy,
    monthly_contract_hash,
    normalize_month_key,
)
from orchestrator.defs.stock_monthly_planner import plan_month_bootstrap


def monthly_target_path(root, source, month):
    from orchestrator.defs.paths import raw_stock_monthly_path
    check_monthly_root(root, staging=False)
    normalize_month_key(month)
    target = raw_stock_monthly_path(root, source, month)
    check_monthly_path(target)
    return target


class MonthlyCaptureStore:
    def __init__(self, plan, staging_root: Path, *, io_policy=None):
        check_monthly_root(staging_root, staging=True)
        self.plan = plan
        self.io_policy = (
            io_policy if io_policy is not None else MonthlyBootstrapIOPolicy()
        )
        self.io_hash = monthly_contract_hash(asdict(self.io_policy))
        self.verify_plan()
        self.root = staging_root / "stock_monthly_raw" / plan.plan_hash / self.io_hash
        check_monthly_path(self.root)
        self.root.mkdir(parents=True, exist_ok=True)

    def verify_plan(self):
        plan = self.plan
        expected = plan_month_bootstrap(
            plan.source,
            plan.inventories,
            first_month=plan.first_month,
            last_month=plan.last_month,
            inventory_ref=plan.inventory_ref,
            inventory_hash=plan.inventory_hash,
            policy=plan.policy,
        )
        if expected != plan:
            raise ValueError("monthly_frozen_plan_invalid")
        evidence = Path(plan.inventory_ref)
        if not evidence.is_absolute():
            evidence = Path(__file__).resolve().parents[6] / evidence
        if (
            monthly_file_hash(evidence, max_bytes=self.io_policy.inventory_max_bytes)
            != plan.inventory_hash
        ):
            raise ValueError("monthly_inventory_changed")

    @contextmanager
    def connection(self):
        spill = self.root / "spill"
        check_monthly_path(spill)
        settings = DuckDBConnectionSettings(
            temp_directory=spill,
            memory_limit=f"{self.io_policy.duckdb_memory_mb}MB",
            threads=self.io_policy.duckdb_threads,
            max_temp_directory_size=f"{self.io_policy.duckdb_temp_mb}MB",
        )
        with connect_configured_duckdb(settings) as connection:
            connection.execute("SET autoinstall_known_extensions=false")
            connection.execute("SET autoload_known_extensions=false")
            yield connection

    def unit_directory(self, unit):
        if unit not in self.plan.units:
            raise ValueError("monthly_unit_outside_plan")
        directory = self.root / "units" / unit.unit_id
        check_monthly_path(directory)
        return directory

    def read_receipt(self, unit):
        directory = self.unit_directory(unit)
        receipt = read_monthly_json(
            directory / "receipt.json", self.io_policy.control_max_bytes
        )
        if (
            receipt.get("plan_hash") != self.plan.plan_hash
            or receipt.get("io_hash") != self.io_hash
            or receipt.get("unit_hash") != monthly_contract_hash(asdict(unit))
        ):
            raise ValueError("monthly_receipt_identity_mismatch")
        attempt = directory / receipt["attempt"]
        if attempt.parent != directory or not attempt.name.startswith("attempt-"):
            raise ValueError("monthly_receipt_path_invalid")
        check_monthly_path(attempt)
        for name, digest in receipt["artifacts"].items():
            if name not in (
                "transport.csv",
                "capture.parquet",
                "control.json",
                "transport.sql",
            ):
                raise ValueError("monthly_receipt_artifact_invalid")
            maximum = (
                self.io_policy.prod_csv_max_bytes
                if name == "transport.csv"
                else self.io_policy.control_max_bytes
                if name != "capture.parquet"
                else self.io_policy.prod_csv_max_bytes
            )
            if monthly_file_hash(attempt / name, max_bytes=maximum) != digest:
                raise ValueError("monthly_capture_changed")
        if set(receipt["artifacts"]) != {
            "transport.csv",
            "capture.parquet",
            "control.json",
            "transport.sql",
        }:
            raise ValueError("monthly_receipt_artifact_missing")
        evidence = read_monthly_json(
            attempt / "control.json", self.io_policy.control_max_bytes
        )
        validate_monthly_export_evidence(
            evidence, unit, self.plan.policy.max_capture_rows
        )
        with self.connection() as con:
            load_monthly_csv(
                con,
                attempt / "transport.csv",
                unit,
                self.plan.policy,
                evidence["source_rows"],
            )
            load_monthly_parquets(
                con, "monthly_candidate", [attempt / "capture.parquet"], unit.source
            )
            count = validate_month_relation(
                con,
                "monthly_candidate",
                unit.source,
                self.plan.policy,
                max_rows=unit.max_rows,
                allow_excluded=True,
            )
            differences = con.execute(
                "SELECT count(*) FROM ((SELECT * FROM monthly_capture EXCEPT ALL SELECT * FROM monthly_candidate) UNION ALL (SELECT * FROM monthly_candidate EXCEPT ALL SELECT * FROM monthly_capture))"
            ).fetchone()[0]
            if count != receipt.get("source_rows") or differences:
                raise ValueError("monthly_capture_readback_mismatch")
        return receipt, attempt / "capture.parquet"

    def capture_unit(
        self, unit, exporter, *, cancel=lambda: False, progress=lambda event: None
    ):
        check_monthly_cancel(cancel)
        self.verify_plan()
        directory = self.unit_directory(unit)
        directory.mkdir(parents=True, exist_ok=True)
        with monthly_file_lock(directory / "writer.lock"):
            if (directory / "receipt.json").exists():
                receipt, _ = self.read_receipt(unit)
                progress(
                    {
                        "phase": "capture_reused",
                        "unit": unit.unit_id,
                        "source_rows": receipt["source_rows"],
                    }
                )
                return receipt
            check_monthly_free_space(
                self.root,
                2 * self.io_policy.prod_csv_max_bytes
                + self.io_policy.control_max_bytes
                + self.io_policy.duckdb_temp_mb * 1024 * 1024,
            )
            attempt = directory / ("attempt-" + uuid4().hex)
            attempt.mkdir()
            check_monthly_cancel(cancel)
            csv_path, evidence = exporter.export(
                unit,
                self.plan.policy,
                self.io_policy,
                attempt,
                cancel,
                progress,
                self.plan.policy.max_capture_rows,
            )
            if csv_path != attempt / "transport.csv":
                raise ValueError("monthly_export_artifact_path_invalid")
            validate_monthly_export_evidence(
                evidence, unit, self.plan.policy.max_capture_rows
            )
            if (
                read_monthly_json(
                    attempt / "control.json", self.io_policy.control_max_bytes
                )
                != evidence
            ):
                raise ValueError("monthly_export_evidence_mismatch")
            monthly_file_hash(csv_path, max_bytes=self.io_policy.prod_csv_max_bytes)
            check_monthly_cancel(cancel)
            with self.connection() as con:
                load_monthly_csv(
                    con, csv_path, unit, self.plan.policy, evidence["source_rows"]
                )
                target = attempt / "capture.parquet"
                con.execute(
                    "COPY (SELECT * FROM monthly_capture ORDER BY ts_code,trade_date,freq) TO ? (FORMAT PARQUET, COMPRESSION ZSTD)",
                    [str(target)],
                )
                sync_monthly_file(target)
                load_monthly_parquets(con, "monthly_candidate", [target], unit.source)
                difference = con.execute(
                    "SELECT count(*) FROM ((SELECT * FROM monthly_capture EXCEPT ALL SELECT * FROM monthly_candidate) UNION ALL (SELECT * FROM monthly_candidate EXCEPT ALL SELECT * FROM monthly_capture))"
                ).fetchone()[0]
                if difference:
                    raise ValueError("monthly_capture_readback_mismatch")
            check_monthly_cancel(cancel)
            sync_monthly_directory(attempt)
            self.verify_plan()
            receipt = {
                "version": 1,
                "plan_hash": self.plan.plan_hash,
                "io_hash": self.io_hash,
                "unit_hash": monthly_contract_hash(asdict(unit)),
                "source_rows": evidence["source_rows"],
                "attempt": attempt.name,
                "artifacts": {
                    name: monthly_file_hash(attempt / name)
                    for name in (
                        "transport.csv",
                        "capture.parquet",
                        "control.json",
                        "transport.sql",
                    )
                },
            }
            write_monthly_json(
                directory / "receipt.json", receipt, self.io_policy.control_max_bytes
            )
            progress(
                {
                    "phase": "capture_committed",
                    "unit": unit.unit_id,
                    "source_rows": evidence["source_rows"],
                }
            )
            return receipt


def build_month_candidates(
    store: MonthlyCaptureStore, year: int, lake_root: Path, *, cancel=lambda: False
):
    check_monthly_root(lake_root, staging=False)
    check_monthly_cancel(cancel)
    store.verify_plan()
    inventory = next((i for i in store.plan.inventories if i.year == year), None)
    if inventory is None:
        raise ValueError("monthly_year_outside_plan")
    units = [u for u in store.plan.units if int(u.source_date_start[:4]) == year]
    receipts, paths = [], []
    for unit in units:
        check_monthly_cancel(cancel)
        _receipt, path = store.read_receipt(unit)
        paths.append(path)
        receipts.append(
            {
                "unit_id": unit.unit_id,
                "receipt_hash": monthly_file_hash(
                    store.unit_directory(unit) / "receipt.json"
                ),
            }
        )
    check_monthly_free_space(
        store.root,
        store.plan.policy.max_year_rows * 512
        + store.io_policy.control_max_bytes
        + store.io_policy.duckdb_temp_mb * 1024 * 1024,
    )
    directory = store.root / "assemblies" / f"{year}-{uuid4().hex}"
    check_monthly_path(directory)
    directory.mkdir(parents=True)
    with store.connection() as con:
        load_monthly_parquets(con, "monthly_year", paths, store.plan.source)
        captured = validate_month_relation(
            con,
            "monthly_year",
            store.plan.source,
            store.plan.policy,
            max_rows=store.plan.policy.max_year_rows,
            allow_excluded=True,
        )
        dates = tuple(
            con.execute(
                "SELECT trade_date,count(*) FROM monthly_year GROUP BY trade_date ORDER BY trade_date"
            ).fetchall()
        )
        codes = tuple(
            r[0]
            for r in con.execute(
                "SELECT DISTINCT ts_code FROM monthly_year ORDER BY ts_code"
            ).fetchall()
        )
        if (
            dates != inventory.source_date_counts
            or codes != inventory.codes
            or captured != inventory.source_rows
        ):
            raise ValueError("monthly_inventory_count_changed")
        excluded_path = directory / "excluded_month_version.parquet"
        con.execute(
            "COPY (SELECT * FROM monthly_year WHERE trade_date='20200229' ORDER BY ts_code) TO ? (FORMAT PARQUET,COMPRESSION ZSTD)",
            [str(excluded_path)],
        )
        sync_monthly_file(excluded_path)
        excluded = con.execute(
            "SELECT count(*) FROM monthly_year WHERE trade_date='20200229'"
        ).fetchone()[0]
        con.execute(
            "CREATE OR REPLACE TEMP TABLE monthly_candidate AS SELECT * FROM monthly_year WHERE trade_date <> '20200229'"
        )
        accepted = validate_month_relation(
            con,
            "monthly_candidate",
            store.plan.source,
            store.plan.policy,
            max_rows=store.plan.policy.max_year_rows,
        )
        expected = canonical_month_hashes(con, "monthly_candidate", store.plan.source)
        if len(expected) > 12 or accepted + excluded != captured:
            raise ValueError("monthly_candidate_count_invalid")
        candidate_dir = directory / "candidates"
        if expected:
            con.execute(
                f"COPY (SELECT *,{MONTH_SQL} AS month FROM monthly_candidate ORDER BY ts_code,trade_date,freq) TO ? (FORMAT PARQUET,COMPRESSION ZSTD, PARTITION_BY(month),WRITE_PARTITION_COLUMNS false,FILENAME_PATTERN 'data')",
                [str(candidate_dir)],
            )
        candidate_paths = sorted(candidate_dir.glob("month=*/*.parquet"))
        # DuckDB appends a shard suffix; enforce the frozen one-file month layout.
        for shard in candidate_paths:
            canonical = shard.parent / "data.parquet"
            if shard != canonical:
                if canonical.exists():
                    raise ValueError("monthly_candidate_shard_conflict")
                os.replace(shard, canonical)
        candidate_paths = sorted(candidate_dir.glob("month=*/*.parquet"))
        if len(candidate_paths) != len(expected):
            raise ValueError("monthly_candidate_file_count_mismatch")
        load_monthly_parquets(
            con, "monthly_capture", candidate_paths, store.plan.source
        )
        validate_month_relation(
            con,
            "monthly_capture",
            store.plan.source,
            store.plan.policy,
            max_rows=store.plan.policy.max_year_rows,
        )
        difference = con.execute(
            "SELECT count(*) FROM ((SELECT * FROM monthly_capture EXCEPT ALL SELECT * FROM monthly_candidate) UNION ALL (SELECT * FROM monthly_candidate EXCEPT ALL SELECT * FROM monthly_capture))"
        ).fetchone()[0]
        if (
            difference
            or canonical_month_hashes(con, "monthly_capture", store.plan.source)
            != expected
        ):
            raise ValueError("monthly_candidate_readback_mismatch")
        records = []
        for path in candidate_paths:
            check_monthly_cancel(cancel)
            month = path.parent.name.removeprefix("month=")
            load_monthly_parquets(con, "monthly_capture", [path], store.plan.source)
            if canonical_month_hashes(con, "monthly_capture", store.plan.source) != {
                month: expected[month]
            }:
                raise ValueError("monthly_candidate_partition_mismatch")
            sync_monthly_file(path)
            sync_monthly_directory(path.parent)
            target = monthly_target_path(lake_root, store.plan.source, month)
            records.append(
                {
                    "month": month,
                    "path": str(path.relative_to(directory)),
                    "sha256": monthly_file_hash(path),
                    "target_sha256": monthly_file_hash(target)
                    if target.exists()
                    else None,
                    **expected[month],
                }
            )
    if candidate_dir.exists():
        sync_monthly_directory(candidate_dir)
    audit = {
        "version": 1,
        "plan_hash": store.plan.plan_hash,
        "io_hash": store.io_hash,
        "source": store.plan.source.value,
        "year": year,
        "lake_root": str(lake_root),
        "captured_rows": captured,
        "excluded_rows": excluded,
        "accepted_rows": accepted,
        "excluded_sha256": monthly_file_hash(excluded_path),
        "receipts": receipts,
        "records": records,
    }
    audit_path = directory / "audit.json"
    write_monthly_json(audit_path, audit, store.io_policy.control_max_bytes)
    return audit_path, monthly_file_hash(audit_path)
