"""Offline, five-frequency replacement for one incomplete stk_mins raw day.

This module is deliberately not registered in Dagster definitions.  It is a
guarded recovery tool for a single approved historical partition, not a
replacement for the normal raw job or sensor path.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from time import perf_counter
from typing import Protocol

from orchestrator.defs.assets import stk_mins as stk_mins_assets
from orchestrator.defs.asset_guards.stk_mins_stock_universe import (
    load_current_listed_stock_codes_for_stk_mins,
    normalize_stk_mins_stock_codes,
    stk_mins_stock_code_set_hash,
)
from orchestrator.defs.duckdb_connection import connect_configured_duckdb
from orchestrator.defs.duckdb_sql import (
    copy_query_to_parquet,
    describe_parquet_query,
    duckdb_string,
    read_parquet,
)
from orchestrator.defs.paths import raw_stk_mins_path
from orchestrator.defs.prod_db.stk_mins import (
    PROD_STK_MINS_SOURCE_COLUMNS,
    build_prod_stk_mins_duckdb_source_sql,
    validate_prod_stk_mins_duckdb_attach_options_contract,
    validate_prod_stk_mins_duckdb_source_contract,
    validate_prod_stk_mins_select_contract,
)
from orchestrator.defs.prod_db.stk_mins_task_run import (
    full_market_stk_mins_task_run_from_row,
)
from orchestrator.defs.resources import DuckDBResource, ProdPostgresResource
from orchestrator.defs.run_contracts.stk_mins import STK_MINS_FREQS


SCHEMA_VERSION = 1
STK_MINS_RECOVERY_FREQS = STK_MINS_FREQS
TASK_RUN_QUERY_LIMIT = 20
_FULL_DAY_START = "09:30:00"
_FULL_DAY_END = "15:00:00"


class StkMinsRawReplaceFromProdError(RuntimeError):
    """Raised when a historical raw replacement cannot prove its safety."""


@dataclass(frozen=True, slots=True)
class StkMinsRecoveryTaskRun:
    task_run_id: int
    ended_at: str
    unit_total: int
    unit_done: int
    unit_failed: int
    progress_percent: float
    rows_fetched: int
    rows_saved: int
    rows_rejected: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class StkMinsRecoveryFrequencyFact:
    freq: int
    row_count: int
    code_count: int
    code_hash: str | None
    duplicate_key_count: int
    empty_key_count: int
    min_trade_time: str | None
    max_trade_time: str | None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class StkMinsRecoveryFileFingerprint:
    freq: int
    path: str
    exists: bool
    size_bytes: int | None
    sha256: str | None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class StkMinsRawReplaceFromProdPlan:
    trade_date: str
    expected_code_count: int
    expected_code_hash: str
    task_run: StkMinsRecoveryTaskRun | None
    frequency_facts: tuple[StkMinsRecoveryFrequencyFact, ...]
    target_files: tuple[StkMinsRecoveryFileFingerprint, ...]
    plan_fingerprint: str
    elapsed_ms: int
    stop_reasons: tuple[str, ...]

    @property
    def should_stop(self) -> bool:
        return bool(self.stop_reasons)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": SCHEMA_VERSION,
            "recovery_kind": "stk_mins_raw_replace_from_prod",
            "read_only": True,
            "trade_date": self.trade_date,
            "expected_code_count": self.expected_code_count,
            "expected_code_hash": self.expected_code_hash,
            "task_run": self.task_run.to_dict() if self.task_run is not None else None,
            "frequency_facts": [fact.to_dict() for fact in self.frequency_facts],
            "target_files": [file.to_dict() for file in self.target_files],
            "plan_fingerprint": self.plan_fingerprint,
            "elapsed_ms": self.elapsed_ms,
            "should_stop": self.should_stop,
            "stop_reasons": list(self.stop_reasons),
        }


@dataclass(frozen=True, slots=True)
class StkMinsRawReplaceFromProdApplyReport:
    trade_date: str
    plan_fingerprint: str
    recovery_run_id: str
    staged_files: tuple[StkMinsRecoveryFileFingerprint, ...]
    quarantine_manifest_path: str
    promoted_frequency_count: int
    elapsed_ms: int

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": SCHEMA_VERSION,
            "recovery_kind": "stk_mins_raw_replace_from_prod",
            "trade_date": self.trade_date,
            "plan_fingerprint": self.plan_fingerprint,
            "recovery_run_id": self.recovery_run_id,
            "staged_files": [file.to_dict() for file in self.staged_files],
            "quarantine_manifest_path": self.quarantine_manifest_path,
            "promoted_frequency_count": self.promoted_frequency_count,
            "elapsed_ms": self.elapsed_ms,
        }


class StkMinsRawReplaceSource(Protocol):
    """Bounded source operations used by the offline recovery."""

    def select_full_market_task_run(
        self,
        *,
        trade_date: str,
    ) -> StkMinsRecoveryTaskRun | None: ...

    def load_frequency_facts(
        self,
        *,
        trade_date: str,
        stock_codes: Sequence[str],
    ) -> tuple[StkMinsRecoveryFrequencyFact, ...]: ...

    def write_frequency_staging_file(
        self,
        *,
        trade_date: str,
        freq: int,
        stock_codes: Sequence[str],
        target_path: Path,
    ) -> None: ...


class ProdStkMinsRawReplaceSource:
    """Production read-only source adapter for the recovery CLI."""

    def __init__(
        self,
        *,
        duckdb: DuckDBResource,
        prod_postgres: ProdPostgresResource,
    ) -> None:
        self._duckdb = duckdb
        self._prod_postgres = prod_postgres

    def select_full_market_task_run(
        self,
        *,
        trade_date: str,
    ) -> StkMinsRecoveryTaskRun | None:
        rows = self._task_run_rows(trade_date=trade_date)
        for row in rows:
            task_run = full_market_stk_mins_task_run_from_row(
                row,
                trade_date=trade_date,
            )
            if task_run is not None:
                return StkMinsRecoveryTaskRun(
                    task_run_id=task_run.task_run_id,
                    ended_at=task_run.ended_at,
                    unit_total=task_run.unit_total,
                    unit_done=task_run.unit_done,
                    unit_failed=task_run.unit_failed,
                    progress_percent=task_run.progress_percent,
                    rows_fetched=task_run.rows_fetched,
                    rows_saved=task_run.rows_saved,
                    rows_rejected=task_run.rows_rejected,
                )
        return None

    def load_frequency_facts(
        self,
        *,
        trade_date: str,
        stock_codes: Sequence[str],
    ) -> tuple[StkMinsRecoveryFrequencyFact, ...]:
        if not stock_codes:
            raise StkMinsRawReplaceFromProdError("Expected stock code set is empty.")
        start_datetime, end_datetime = _trade_day_window(trade_date)
        sql = """
        WITH source_rows AS (
          SELECT
            freq,
            ts_code,
            trade_time
          FROM raw_tushare.stk_mins
          WHERE freq = ANY(%s)
            AND trade_time >= %s::timestamp
            AND trade_time < %s::timestamp
            AND ts_code = ANY(%s)
        ),
        distinct_codes AS (
          SELECT DISTINCT
            freq,
            ts_code
          FROM source_rows
          WHERE ts_code IS NOT NULL
            AND btrim(ts_code) != ''
        ),
        code_stats AS (
          SELECT
            freq,
            count(*) AS code_count,
            md5(string_agg(ts_code, ',' ORDER BY ts_code)) AS code_hash
          FROM distinct_codes
          GROUP BY freq
        )
        SELECT
          source_rows.freq,
          count(*) AS row_count,
          code_stats.code_count,
          code_stats.code_hash,
          count(*) - count(DISTINCT (source_rows.ts_code, source_rows.trade_time))
            AS duplicate_key_count,
          count(*) FILTER (
            WHERE source_rows.ts_code IS NULL
               OR btrim(source_rows.ts_code) = ''
               OR source_rows.trade_time IS NULL
          ) AS empty_key_count,
          min(source_rows.trade_time) AS min_trade_time,
          max(source_rows.trade_time) AS max_trade_time
        FROM source_rows
        JOIN code_stats USING (freq)
        GROUP BY source_rows.freq, code_stats.code_count, code_stats.code_hash
        ORDER BY source_rows.freq
        """
        with self._prod_postgres.connect_readonly_transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    sql,
                    (
                        list(STK_MINS_RECOVERY_FREQS),
                        start_datetime,
                        end_datetime,
                        list(stock_codes),
                    ),
                )
                rows = cursor.fetchall()
        return tuple(
            StkMinsRecoveryFrequencyFact(
                freq=int(row[0]),
                row_count=int(row[1]),
                code_count=int(row[2]),
                code_hash=str(row[3]) if row[3] is not None else None,
                duplicate_key_count=int(row[4]),
                empty_key_count=int(row[5]),
                min_trade_time=_trade_time_text(row[6]) if row[6] is not None else None,
                max_trade_time=_trade_time_text(row[7]) if row[7] is not None else None,
            )
            for row in rows
        )

    def write_frequency_staging_file(
        self,
        *,
        trade_date: str,
        freq: int,
        stock_codes: Sequence[str],
        target_path: Path,
    ) -> None:
        validate_prod_stk_mins_select_contract()
        validate_prod_stk_mins_duckdb_source_contract()
        validate_prod_stk_mins_duckdb_attach_options_contract()
        start_datetime, end_datetime = _trade_day_window(trade_date)
        source_sql = build_prod_stk_mins_duckdb_source_sql(
            stock_codes=stock_codes,
            freq=freq,
            start_datetime=start_datetime,
            end_datetime=end_datetime,
        )
        target_path.parent.mkdir(parents=True, exist_ok=True)
        with connect_configured_duckdb() as connection:
            stk_mins_assets._load_duckdb_postgres_extension(connection)
            stk_mins_assets._attach_prod_postgres_database(
                connection,
                postgres_connection_string=self._prod_postgres.duckdb_connection_string(),
            )
            connection.execute(
                "CREATE TEMP TABLE prod_stk_mins_source AS "
                + "SELECT "
                + ", ".join(PROD_STK_MINS_SOURCE_COLUMNS)
                + f" FROM ({source_sql}) AS source_rows"
            )
            connection.execute(
                copy_query_to_parquet(
                    stk_mins_assets._prod_db_raw_stk_mins_output_sql(freq=freq),
                    target_path,
                )
            )

    def _task_run_rows(self, *, trade_date: str) -> tuple[dict[str, object], ...]:
        sql = """
        SELECT
          id,
          task_type,
          resource_key,
          action,
          status,
          status_reason_code,
          ended_at,
          unit_total,
          unit_done,
          unit_failed,
          progress_percent,
          rows_fetched,
          rows_saved,
          rows_rejected,
          time_input_json,
          filters_json
        FROM ops.task_run
        WHERE task_type = 'dataset_action'
          AND resource_key = 'stk_mins'
          AND action = 'maintain'
          AND status = 'success'
          AND ended_at IS NOT NULL
          AND time_input_json ->> 'trade_date' = %s
        ORDER BY ended_at DESC, id DESC
        LIMIT %s
        """
        with self._prod_postgres.connect_readonly_transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql, (trade_date, TASK_RUN_QUERY_LIMIT))
                columns = tuple(str(column[0]) for column in cursor.description)
                return tuple(
                    {column: value for column, value in zip(columns, row, strict=True)}
                    for row in cursor.fetchall()
                )


def plan_stk_mins_raw_replace_from_prod(
    *,
    lake_root: Path,
    duckdb: DuckDBResource,
    prod_postgres: ProdPostgresResource,
    trade_date: str,
    source: StkMinsRawReplaceSource | None = None,
) -> StkMinsRawReplaceFromProdPlan:
    """Build a read-only, source-and-target-frozen recovery plan."""

    _validate_trade_date(trade_date)
    started = perf_counter()
    expected_codes = _expected_stock_codes(
        lake_root=lake_root,
        duckdb=duckdb,
        trade_date=trade_date,
    )
    expected_code_hash = stock_code_set_hash(expected_codes)
    resolved_source = source or ProdStkMinsRawReplaceSource(
        duckdb=duckdb,
        prod_postgres=prod_postgres,
    )
    task_run = resolved_source.select_full_market_task_run(
        trade_date=trade_date,
    )
    frequency_facts = tuple(
        sorted(
            resolved_source.load_frequency_facts(
                trade_date=trade_date,
                stock_codes=expected_codes,
            ),
            key=lambda fact: fact.freq,
        )
    )
    target_files = tuple(
        _file_fingerprint(
            freq=freq,
            path=raw_stk_mins_path(lake_root, freq, trade_date),
        )
        for freq in STK_MINS_RECOVERY_FREQS
    )
    stop_reasons = _plan_stop_reasons(
        task_run=task_run,
        expected_code_count=len(expected_codes),
        expected_code_hash=expected_code_hash,
        frequency_facts=frequency_facts,
        target_files=target_files,
        trade_date=trade_date,
    )
    elapsed_ms = int((perf_counter() - started) * 1000)
    fingerprint_payload = {
        "schema_version": SCHEMA_VERSION,
        "trade_date": trade_date,
        "expected_code_count": len(expected_codes),
        "expected_code_hash": expected_code_hash,
        "task_run": task_run.to_dict() if task_run is not None else None,
        "frequency_facts": [fact.to_dict() for fact in frequency_facts],
        "target_files": [file.to_dict() for file in target_files],
        "stop_reasons": list(stop_reasons),
    }
    return StkMinsRawReplaceFromProdPlan(
        trade_date=trade_date,
        expected_code_count=len(expected_codes),
        expected_code_hash=expected_code_hash,
        task_run=task_run,
        frequency_facts=frequency_facts,
        target_files=target_files,
        plan_fingerprint=_payload_hash(fingerprint_payload),
        elapsed_ms=elapsed_ms,
        stop_reasons=stop_reasons,
    )


def load_stk_mins_raw_replace_from_prod_plan(
    plan_report: Path,
) -> StkMinsRawReplaceFromProdPlan:
    """Load a reviewed plan report without trusting an arbitrary apply payload."""

    try:
        payload = json.loads(plan_report.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise StkMinsRawReplaceFromProdError(
            f"Recovery plan report does not exist: {plan_report}"
        ) from error
    except json.JSONDecodeError as error:
        raise StkMinsRawReplaceFromProdError(
            f"Recovery plan report is not valid JSON: {plan_report}"
        ) from error
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise StkMinsRawReplaceFromProdError("Unsupported recovery plan schema version.")
    if payload.get("recovery_kind") != "stk_mins_raw_replace_from_prod":
        raise StkMinsRawReplaceFromProdError("Plan report has the wrong recovery kind.")
    if payload.get("read_only") is not True:
        raise StkMinsRawReplaceFromProdError("Apply requires a read-only recovery plan.")
    if payload.get("should_stop"):
        raise StkMinsRawReplaceFromProdError(
            f"Recovery plan has stop reasons: {payload.get('stop_reasons', [])}."
        )
    task_payload = payload.get("task_run")
    if not isinstance(task_payload, Mapping):
        raise StkMinsRawReplaceFromProdError("Recovery plan is missing TaskRun evidence.")
    frequency_payload = payload.get("frequency_facts")
    target_payload = payload.get("target_files")
    if not isinstance(frequency_payload, list) or not isinstance(target_payload, list):
        raise StkMinsRawReplaceFromProdError("Recovery plan has invalid frequency/file evidence.")
    return StkMinsRawReplaceFromProdPlan(
        trade_date=str(payload["trade_date"]),
        expected_code_count=int(payload["expected_code_count"]),
        expected_code_hash=str(payload["expected_code_hash"]),
        task_run=StkMinsRecoveryTaskRun(
            task_run_id=int(task_payload["task_run_id"]),
            ended_at=str(task_payload["ended_at"]),
            unit_total=int(task_payload["unit_total"]),
            unit_done=int(task_payload["unit_done"]),
            unit_failed=int(task_payload["unit_failed"]),
            progress_percent=float(task_payload["progress_percent"]),
            rows_fetched=int(task_payload["rows_fetched"]),
            rows_saved=int(task_payload["rows_saved"]),
            rows_rejected=int(task_payload["rows_rejected"]),
        ),
        frequency_facts=tuple(
            StkMinsRecoveryFrequencyFact(
                freq=int(item["freq"]),
                row_count=int(item["row_count"]),
                code_count=int(item["code_count"]),
                code_hash=str(item["code_hash"]) if item["code_hash"] is not None else None,
                duplicate_key_count=int(item["duplicate_key_count"]),
                empty_key_count=int(item["empty_key_count"]),
                min_trade_time=str(item["min_trade_time"])
                if item["min_trade_time"] is not None
                else None,
                max_trade_time=str(item["max_trade_time"])
                if item["max_trade_time"] is not None
                else None,
            )
            for item in frequency_payload
            if isinstance(item, Mapping)
        ),
        target_files=tuple(
            StkMinsRecoveryFileFingerprint(
                freq=int(item["freq"]),
                path=str(item["path"]),
                exists=bool(item["exists"]),
                size_bytes=int(item["size_bytes"]) if item["size_bytes"] is not None else None,
                sha256=str(item["sha256"]) if item["sha256"] is not None else None,
            )
            for item in target_payload
            if isinstance(item, Mapping)
        ),
        plan_fingerprint=str(payload["plan_fingerprint"]),
        elapsed_ms=int(payload.get("elapsed_ms", 0)),
        stop_reasons=tuple(str(item) for item in payload.get("stop_reasons", ())),
    )


def apply_stk_mins_raw_replace_from_prod(
    *,
    lake_root: Path,
    duckdb: DuckDBResource,
    prod_postgres: ProdPostgresResource,
    plan: StkMinsRawReplaceFromProdPlan,
    expected_plan_fingerprint: str,
    confirm_apply: bool,
    source: StkMinsRawReplaceSource | None = None,
    recovery_run_id: str | None = None,
) -> StkMinsRawReplaceFromProdApplyReport:
    """Stage, quarantine and replace all five raw files as one guarded operation."""

    if not confirm_apply:
        raise StkMinsRawReplaceFromProdError("Apply requires explicit confirm_apply=True.")
    if plan.should_stop:
        raise StkMinsRawReplaceFromProdError("Apply refuses a stopped recovery plan.")
    if plan.plan_fingerprint != expected_plan_fingerprint:
        raise StkMinsRawReplaceFromProdError("Approved recovery plan fingerprint mismatch.")

    started = perf_counter()
    resolved_source = source or ProdStkMinsRawReplaceSource(
        duckdb=duckdb,
        prod_postgres=prod_postgres,
    )
    fresh_plan = plan_stk_mins_raw_replace_from_prod(
        lake_root=lake_root,
        duckdb=duckdb,
        prod_postgres=prod_postgres,
        trade_date=plan.trade_date,
        source=resolved_source,
    )
    if fresh_plan.should_stop:
        raise StkMinsRawReplaceFromProdError(
            f"Fresh recovery plan has stop reasons: {list(fresh_plan.stop_reasons)}."
        )
    if fresh_plan.plan_fingerprint != expected_plan_fingerprint:
        raise StkMinsRawReplaceFromProdError(
            "Recovery plan is stale; regenerate and review a new plan before apply."
        )

    expected_codes = _expected_stock_codes(
        lake_root=lake_root,
        duckdb=duckdb,
        trade_date=plan.trade_date,
    )
    if len(expected_codes) != plan.expected_code_count or stock_code_set_hash(expected_codes) != plan.expected_code_hash:
        raise StkMinsRawReplaceFromProdError(
            "Current DG stock code set differs from the approved recovery plan."
        )

    run_id = recovery_run_id or str(uuid.uuid4())
    staging_root = _staging_root(lake_root=lake_root, trade_date=plan.trade_date, run_id=run_id)
    quarantine_root = _quarantine_root(lake_root=lake_root, trade_date=plan.trade_date, run_id=run_id)
    target_paths = {
        freq: raw_stk_mins_path(lake_root, freq, plan.trade_date)
        for freq in STK_MINS_RECOVERY_FREQS
    }
    stage_paths = {
        freq: staging_root / f"freq={freq}" / f"trade_date={plan.trade_date}" / "part-000.parquet"
        for freq in STK_MINS_RECOVERY_FREQS
    }
    _assert_same_volume(lake_root=lake_root, target_paths=target_paths.values())
    if staging_root.exists() or quarantine_root.exists():
        raise StkMinsRawReplaceFromProdError(
            f"Recovery run id already has staging or quarantine state: {run_id}."
        )

    stage_fingerprints: list[StkMinsRecoveryFileFingerprint] = []
    try:
        for freq in STK_MINS_RECOVERY_FREQS:
            resolved_source.write_frequency_staging_file(
                trade_date=plan.trade_date,
                freq=freq,
                stock_codes=expected_codes,
                target_path=stage_paths[freq],
            )
            stage_fingerprint = _validate_staged_file(
                freq=freq,
                path=stage_paths[freq],
                trade_date=plan.trade_date,
                expected_code_count=plan.expected_code_count,
                expected_code_hash=plan.expected_code_hash,
                expected_source_fact=_frequency_fact_for(plan.frequency_facts, freq),
            )
            stage_fingerprints.append(stage_fingerprint)
    except Exception:
        _remove_tree(staging_root)
        raise

    manifest_path = quarantine_root / "manifest.json"
    quarantine_root.mkdir(parents=True, exist_ok=False)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "recovery_kind": "stk_mins_raw_replace_from_prod",
        "trade_date": plan.trade_date,
        "recovery_run_id": run_id,
        "plan_fingerprint": expected_plan_fingerprint,
        "status": "staged",
        "target_files_before": [file.to_dict() for file in fresh_plan.target_files],
        "staged_files": [file.to_dict() for file in stage_fingerprints],
        "backup_paths": {
            str(freq): str(_backup_path(quarantine_root, freq, plan.trade_date))
            for freq in STK_MINS_RECOVERY_FREQS
        },
    }
    _write_json(manifest_path, manifest)

    backed_up: list[int] = []
    promoted: list[int] = []
    try:
        for freq in STK_MINS_RECOVERY_FREQS:
            backup_path = _backup_path(quarantine_root, freq, plan.trade_date)
            backup_path.parent.mkdir(parents=True, exist_ok=True)
            os.replace(target_paths[freq], backup_path)
            backed_up.append(freq)
        manifest["status"] = "backed_up"
        _write_json(manifest_path, manifest)

        for freq in STK_MINS_RECOVERY_FREQS:
            os.replace(stage_paths[freq], target_paths[freq])
            promoted.append(freq)
        manifest["status"] = "promoted"
        manifest["promoted_frequencies"] = promoted
        _write_json(manifest_path, manifest)
    except Exception as error:
        rollback_errors = _restore_backups(
            target_paths=target_paths,
            quarantine_root=quarantine_root,
            backed_up=backed_up,
            trade_date=plan.trade_date,
        )
        manifest["status"] = "rolled_back" if not rollback_errors else "rollback_failed"
        manifest["promoted_frequencies"] = promoted
        manifest["rollback_errors"] = rollback_errors
        manifest["apply_error"] = type(error).__name__
        _write_json(manifest_path, manifest)
        _remove_tree(staging_root)
        if rollback_errors:
            raise StkMinsRawReplaceFromProdError(
                "Recovery promote failed and rollback was incomplete: "
                + "; ".join(rollback_errors)
            ) from error
        raise StkMinsRawReplaceFromProdError(
            "Recovery promote failed; all previously moved raw files were restored."
        ) from error

    _remove_tree(staging_root)
    return StkMinsRawReplaceFromProdApplyReport(
        trade_date=plan.trade_date,
        plan_fingerprint=expected_plan_fingerprint,
        recovery_run_id=run_id,
        staged_files=tuple(stage_fingerprints),
        quarantine_manifest_path=str(manifest_path),
        promoted_frequency_count=len(promoted),
        elapsed_ms=int((perf_counter() - started) * 1000),
    )


def stock_code_set_hash(stock_codes: Sequence[str]) -> str:
    """Return the stable MD5 code-set identity used by the frozen R0 baseline."""

    return stk_mins_stock_code_set_hash(stock_codes)


def _expected_stock_codes(
    *,
    lake_root: Path,
    duckdb: DuckDBResource,
    trade_date: str,
) -> tuple[str, ...]:
    return normalize_stk_mins_stock_codes(
        load_current_listed_stock_codes_for_stk_mins(
            lake_root=lake_root,
            duckdb=duckdb,
            partition_key=trade_date,
        )
    )


def _plan_stop_reasons(
    *,
    task_run: StkMinsRecoveryTaskRun | None,
    expected_code_count: int,
    expected_code_hash: str,
    frequency_facts: Sequence[StkMinsRecoveryFrequencyFact],
    target_files: Sequence[StkMinsRecoveryFileFingerprint],
    trade_date: str,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if task_run is None:
        reasons.append("full_market_task_run_missing")
    facts_by_freq = {fact.freq: fact for fact in frequency_facts}
    for freq in STK_MINS_RECOVERY_FREQS:
        fact = facts_by_freq.get(freq)
        if fact is None:
            reasons.append(f"source_frequency_missing:{freq}")
            continue
        if fact.code_count != expected_code_count or fact.code_hash != expected_code_hash:
            reasons.append(f"source_code_coverage_mismatch:{freq}")
        if fact.duplicate_key_count:
            reasons.append(f"source_duplicate_key:{freq}")
        if fact.empty_key_count:
            reasons.append(f"source_empty_key:{freq}")
        expected_min, expected_max = _expected_trade_time_bounds(trade_date)
        if fact.min_trade_time != expected_min or fact.max_trade_time != expected_max:
            reasons.append(f"source_time_range_mismatch:{freq}")
    if {fact.freq for fact in frequency_facts} - set(STK_MINS_RECOVERY_FREQS):
        reasons.append("source_unexpected_frequency")
    for target in target_files:
        if not target.exists:
            reasons.append(f"target_raw_file_missing:{target.freq}")
    return tuple(reasons)


def _validate_staged_file(
    *,
    freq: int,
    path: Path,
    trade_date: str,
    expected_code_count: int,
    expected_code_hash: str,
    expected_source_fact: StkMinsRecoveryFrequencyFact,
) -> StkMinsRecoveryFileFingerprint:
    if not path.is_file():
        raise StkMinsRawReplaceFromProdError(f"Staging file was not written: {path}")
    relation = read_parquet(path, hive_partitioning=False)
    with connect_configured_duckdb() as connection:
        observed_schema = {
            str(row[0]): str(row[1])
            for row in connection.execute(
                describe_parquet_query(path, hive_partitioning=False)
            ).fetchall()
        }
        if observed_schema != stk_mins_assets.STK_MINS_RAW_COLUMN_TYPES:
            raise StkMinsRawReplaceFromProdError(
                f"Staging schema mismatch for freq={freq}: {observed_schema!r}."
            )
        row = connection.execute(
            f"""
            WITH source_rows AS (
              SELECT
                {", ".join(stk_mins_assets.STK_MINS_RAW_COLUMNS)}
              FROM {relation}
            ),
            distinct_codes AS (
              SELECT DISTINCT CAST(ts_code AS VARCHAR) AS ts_code
              FROM source_rows
              WHERE ts_code IS NOT NULL
                AND trim(CAST(ts_code AS VARCHAR)) != ''
              ORDER BY ts_code
            )
            SELECT
              count(*) AS row_count,
              (SELECT count(*) FROM distinct_codes) AS code_count,
              (SELECT md5(string_agg(ts_code, ',' ORDER BY ts_code)) FROM distinct_codes)
                AS code_hash,
              count(*) - count(DISTINCT (ts_code, trade_time)) AS duplicate_key_count,
              count(*) FILTER (
                WHERE ts_code IS NULL
                   OR trim(CAST(ts_code AS VARCHAR)) = ''
                   OR trade_time IS NULL
              ) AS empty_key_count,
              count(*) FILTER (WHERE CAST(freq AS INTEGER) != {freq}) AS freq_mismatch_count,
              count(*) FILTER (
                WHERE CAST(trade_time AS DATE) != CAST({duckdb_string(trade_date)} AS DATE)
              ) AS date_mismatch_count,
              min(trade_time)::VARCHAR AS min_trade_time,
              max(trade_time)::VARCHAR AS max_trade_time
            FROM source_rows
            """
        ).fetchone()
    row_count = int(row[0])
    code_count = int(row[1])
    code_hash = str(row[2]) if row[2] is not None else None
    duplicate_key_count = int(row[3])
    empty_key_count = int(row[4])
    freq_mismatch_count = int(row[5])
    date_mismatch_count = int(row[6])
    min_trade_time = str(row[7]) if row[7] is not None else None
    max_trade_time = str(row[8]) if row[8] is not None else None
    expected_min, expected_max = _expected_trade_time_bounds(trade_date)
    errors = []
    if row_count != expected_source_fact.row_count:
        errors.append("row_count")
    if code_count != expected_code_count or code_hash != expected_code_hash:
        errors.append("code_coverage")
    if duplicate_key_count:
        errors.append("duplicate_key")
    if empty_key_count:
        errors.append("empty_key")
    if freq_mismatch_count:
        errors.append("freq")
    if date_mismatch_count:
        errors.append("trade_date")
    if min_trade_time != expected_min or max_trade_time != expected_max:
        errors.append("time_range")
    if errors:
        raise StkMinsRawReplaceFromProdError(
            f"Staging validation failed for freq={freq}: {', '.join(errors)}."
        )
    return _file_fingerprint(freq=freq, path=path)


def _frequency_fact_for(
    facts: Sequence[StkMinsRecoveryFrequencyFact],
    freq: int,
) -> StkMinsRecoveryFrequencyFact:
    for fact in facts:
        if fact.freq == freq:
            return fact
    raise StkMinsRawReplaceFromProdError(f"Missing approved source fact for freq={freq}.")


def _restore_backups(
    *,
    target_paths: Mapping[int, Path],
    quarantine_root: Path,
    backed_up: Sequence[int],
    trade_date: str,
) -> list[str]:
    errors = []
    for freq in reversed(backed_up):
        backup_path = _backup_path(quarantine_root, freq, trade_date)
        if not backup_path.exists():
            errors.append(f"backup_missing:{freq}")
            continue
        try:
            os.replace(backup_path, target_paths[freq])
        except OSError as error:
            errors.append(f"restore_failed:{freq}:{type(error).__name__}")
    return errors


def _file_fingerprint(*, freq: int, path: Path) -> StkMinsRecoveryFileFingerprint:
    if not path.is_file():
        return StkMinsRecoveryFileFingerprint(
            freq=freq,
            path=str(path),
            exists=False,
            size_bytes=None,
            sha256=None,
        )
    return StkMinsRecoveryFileFingerprint(
        freq=freq,
        path=str(path),
        exists=True,
        size_bytes=path.stat().st_size,
        sha256=_sha256_path(path),
    )


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _payload_hash(payload: Mapping[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _trade_day_window(trade_date: str) -> tuple[str, str]:
    parsed = date.fromisoformat(trade_date)
    return (
        f"{parsed.isoformat()} 00:00:00",
        f"{(parsed + timedelta(days=1)).isoformat()} 00:00:00",
    )


def _expected_trade_time_bounds(trade_date: str) -> tuple[str, str]:
    return f"{trade_date} {_FULL_DAY_START}", f"{trade_date} {_FULL_DAY_END}"


def _staging_root(*, lake_root: Path, trade_date: str, run_id: str) -> Path:
    return (
        raw_stk_mins_path(lake_root, STK_MINS_RECOVERY_FREQS[0], trade_date)
        .parents[2]
        / "_staging"
        / f"recovery_run_id={run_id}"
    )


def _quarantine_root(*, lake_root: Path, trade_date: str, run_id: str) -> Path:
    return (
        lake_root
        / "_quarantine"
        / "stk_mins_raw_replace_from_prod"
        / f"trade_date={trade_date}"
        / f"recovery_run_id={run_id}"
    )


def _backup_path(quarantine_root: Path, freq: int, trade_date: str) -> Path:
    return quarantine_root / f"freq={freq}" / f"trade_date={trade_date}" / "part-000.parquet"


def _assert_same_volume(*, lake_root: Path, target_paths: Sequence[Path]) -> None:
    lake_root_stat = lake_root.stat()
    for target_path in target_paths:
        if not target_path.parent.exists():
            raise StkMinsRawReplaceFromProdError(
                f"Raw target parent does not exist: {target_path.parent}"
            )
        if target_path.parent.stat().st_dev != lake_root_stat.st_dev:
            raise StkMinsRawReplaceFromProdError(
                f"Raw target is not on the Lake root volume: {target_path}"
            )


def _write_json(path: Path, payload: Mapping[str, object]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _remove_tree(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)


def _validate_trade_date(value: str) -> None:
    try:
        date.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"Invalid trade_date: {value!r}") from error


def _int(value: object) -> int:
    return int(value) if value is not None else 0


def _float(value: object) -> float:
    return float(value) if value is not None else 0.0


def _datetime_text(value: object) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _trade_time_text(value: object) -> str:
    if isinstance(value, datetime):
        return value.replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S")
    return str(value).replace("T", " ")[:19]
