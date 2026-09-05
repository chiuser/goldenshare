"""Offline, five-frequency replacement for one incomplete stk_mins raw day.

This module is deliberately not registered in Dagster definitions.  It is a
guarded recovery tool for a single approved historical partition, not a
replacement for the normal raw job or sensor path.
"""

from __future__ import annotations

import errno
import hashlib
import json
import os
import shutil
import sys
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from time import perf_counter
from typing import Protocol

from duckdb import OutOfMemoryException

from orchestrator.defs.asset_guards.stk_mins_stock_universe import (
    load_current_listed_stock_codes_for_stk_mins,
    normalize_stk_mins_stock_codes,
    stk_mins_stock_code_set_hash,
)
from orchestrator.defs.assets import stk_mins as stk_mins_assets
from orchestrator.defs.duckdb_connection import connect_configured_duckdb
from orchestrator.defs.duckdb_sql import (
    copy_query_to_parquet,
    describe_parquet_query,
    duckdb_string,
    read_parquet,
)
from orchestrator.defs.paths import (
    DEFAULT_LAKE_ROOT,
    DEFAULT_LAKE_STAGING_ROOT,
    raw_stk_mins_path,
    stk_mins_raw_recovery_run_root,
)
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

SCHEMA_VERSION = 2
RECOVERY_KIND = "stk_mins_raw_replace_from_prod"
STK_MINS_RECOVERY_FREQS = STK_MINS_FREQS
TASK_RUN_QUERY_LIMIT = 20
_FULL_DAY_START = "09:30:00"
_FULL_DAY_END = "15:00:00"


class StkMinsRawReplaceFromProdError(RuntimeError):
    """Raised when a historical raw replacement cannot prove its safety."""

    def __init__(self, message: str, code: str = "candidate_invalid") -> None:
        self.code = code
        super().__init__(f"{code}: {message}")


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
    recovery_run_id: str
    lake_root: str
    staging_root: str
    staging_free_bytes_before: int
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
            "recovery_run_id": self.recovery_run_id,
            "lake_root": self.lake_root,
            "staging_root": self.staging_root,
            "staging_free_bytes_before": self.staging_free_bytes_before,
            "source_row_count_by_freq": {str(f.freq): f.row_count for f in self.frequency_facts},
            "target_size_bytes_by_freq": {str(f.freq): f.size_bytes for f in self.target_files},
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
    checkpoint_path: str
    final_report_path: str
    promoted_frequency_count: int
    elapsed_ms: int
    phase: str
    staging_free_bytes: int
    candidate_size_bytes_by_freq: dict[str, int | None]
    stage_records: tuple[dict[str, object], ...]
    slow_operation_warning: bool

    def to_dict(self) -> dict[str, object]:
        return {"schema_version": SCHEMA_VERSION, "recovery_kind": RECOVERY_KIND, **asdict(self)}


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
        with self._prod_postgres.connect_readonly_transaction() as connection, connection.cursor() as cursor:
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
        with self._prod_postgres.connect_readonly_transaction() as connection, connection.cursor() as cursor:
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
    staging_root: Path | None = None,
    recovery_run_id: str | None = None,
    source: StkMinsRawReplaceSource | None = None,
) -> StkMinsRawReplaceFromProdPlan:
    """Freeze one plan in staging; never write formal Raw or remote state."""
    run_id = recovery_run_id or str(uuid.uuid4())
    lake_root, staging_root, run_root = _recovery_paths(
        lake_root, staging_root, trade_date, run_id,
    )
    _assert_new_run_allowed(run_root)
    plan = _collect_recovery_plan(
        lake_root=lake_root, staging_root=staging_root, recovery_run_id=run_id,
        duckdb=duckdb, prod_postgres=prod_postgres, trade_date=trade_date, source=source,
    )
    _ensure_directory(run_root)
    _write_json(run_root / "plan.json", plan.to_dict())
    _save_checkpoint(run_root, _initial_checkpoint(plan, run_root))
    return plan


def _collect_recovery_plan(
    *,
    lake_root: Path,
    duckdb: DuckDBResource,
    prod_postgres: ProdPostgresResource,
    trade_date: str,
    staging_root: Path,
    recovery_run_id: str,
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
    plan = StkMinsRawReplaceFromProdPlan(
        trade_date=trade_date,
        recovery_run_id=recovery_run_id,
        lake_root=str(lake_root),
        staging_root=str(staging_root),
        staging_free_bytes_before=shutil.disk_usage(staging_root).free,
        expected_code_count=len(expected_codes),
        expected_code_hash=expected_code_hash,
        task_run=task_run,
        frequency_facts=frequency_facts,
        target_files=target_files,
        plan_fingerprint="",
        elapsed_ms=elapsed_ms,
        stop_reasons=stop_reasons,
    )
    return replace(plan, plan_fingerprint=_plan_fingerprint(plan))


def load_stk_mins_raw_replace_from_prod_plan(
    plan_report: Path,
) -> StkMinsRawReplaceFromProdPlan:
    """Load only a complete, fingerprint-verified plan in its frozen run."""
    payload = _read_json(plan_report)
    if (
        payload.get("schema_version") != SCHEMA_VERSION
        or payload.get("recovery_kind") != RECOVERY_KIND
        or payload.get("read_only") is not True
    ):
        raise StkMinsRawReplaceFromProdError("Unsupported recovery plan", "checkpoint_identity_mismatch")
    try:
        plan = StkMinsRawReplaceFromProdPlan(
            trade_date=payload["trade_date"],
            recovery_run_id=payload["recovery_run_id"],
            lake_root=payload["lake_root"],
            staging_root=payload["staging_root"],
            staging_free_bytes_before=payload["staging_free_bytes_before"],
            expected_code_count=payload["expected_code_count"],
            expected_code_hash=payload["expected_code_hash"],
            task_run=StkMinsRecoveryTaskRun(**payload["task_run"]) if payload["task_run"] else None,
            frequency_facts=tuple(StkMinsRecoveryFrequencyFact(**f) for f in payload["frequency_facts"]),
            target_files=tuple(StkMinsRecoveryFileFingerprint(**f) for f in payload["target_files"]),
            plan_fingerprint=payload["plan_fingerprint"],
            elapsed_ms=payload["elapsed_ms"],
            stop_reasons=tuple(payload["stop_reasons"]),
        )
        _, _, run_root = _recovery_paths(
            Path(plan.lake_root), Path(plan.staging_root), plan.trade_date, plan.recovery_run_id,
        )
        _safe_child(plan_report, run_root)
        _validate_plan_identity(plan)
        if payload["should_stop"] != plan.should_stop:
            raise ValueError("inconsistent stop reasons")
    except (KeyError, TypeError, ValueError) as error:
        raise StkMinsRawReplaceFromProdError(
            f"Invalid recovery plan: {error}", "checkpoint_identity_mismatch",
        ) from error
    return plan


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
    staging_root: Path | None = None,
    abort_before_promote: bool = False,
    cancel_requested: Callable[[], bool] | None = None,
) -> StkMinsRawReplaceFromProdApplyReport:
    """Audit candidates, atomically replace each file, and resume the same run."""
    if not confirm_apply:
        raise StkMinsRawReplaceFromProdError("Apply requires explicit confirmation", "confirmation_required")
    _validate_plan_identity(plan)
    lake_root, staging_root, run_root = _recovery_paths(
        lake_root, staging_root, plan.trade_date, recovery_run_id or plan.recovery_run_id,
    )
    if (
        str(lake_root) != plan.lake_root or str(staging_root) != plan.staging_root
        or run_root.name != f"recovery_run_id={plan.recovery_run_id}"
        or expected_plan_fingerprint != plan.plan_fingerprint
        or _read_json(run_root / "plan.json") != plan.to_dict()
    ):
        raise StkMinsRawReplaceFromProdError("Approved recovery plan mismatch", "checkpoint_identity_mismatch")
    checkpoint = _load_checkpoint(run_root, plan)
    if checkpoint["phase"] == "aborted_before_promote":
        raise StkMinsRawReplaceFromProdError("Aborted run cannot apply", "run_aborted")
    if abort_before_promote:
        return _abort_recovery(plan, checkpoint, run_root)
    if plan.should_stop:
        raise StkMinsRawReplaceFromProdError(f"Plan has stop reasons: {plan.stop_reasons}", "scope_invalid")

    started = perf_counter()
    try:
        _check_cancel(cancel_requested)
        target_states = _inspect_targets(plan, checkpoint)
        already_promoted = any(
            item["state"] != "pending" or item["promoted_at"] is not None
            or (target_states[freq] == "candidate" and
                item["candidate_sha256"] != item["approved_old_sha256"])
            for freq, item in checkpoint["frequencies"].items()
        )
        completed = checkpoint["phase"] == "completed"
        if not already_promoted and not completed:
            resolved_source = source or ProdStkMinsRawReplaceSource(
                duckdb=duckdb, prod_postgres=prod_postgres,
            )
            fresh = _collect_recovery_plan(
                lake_root=lake_root, staging_root=staging_root,
                recovery_run_id=plan.recovery_run_id, duckdb=duckdb,
                prod_postgres=prod_postgres, trade_date=plan.trade_date, source=resolved_source,
            )
            if fresh.plan_fingerprint != plan.plan_fingerprint or fresh.should_stop:
                raise StkMinsRawReplaceFromProdError("Source, code set or target facts changed", "plan_stale")
            codes = _expected_stock_codes(lake_root=lake_root, duckdb=duckdb, trade_date=plan.trade_date)
            if len(codes) != plan.expected_code_count or stock_code_set_hash(codes) != plan.expected_code_hash:
                raise StkMinsRawReplaceFromProdError("Stock code set changed", "plan_stale")
            _build_candidates(plan, checkpoint, run_root, resolved_source, codes, cancel_requested)
            # The bounded source and target facts must still hold after all five exports.
            fresh = _collect_recovery_plan(
                lake_root=lake_root, staging_root=staging_root,
                recovery_run_id=plan.recovery_run_id, duckdb=duckdb,
                prod_postgres=prod_postgres, trade_date=plan.trade_date, source=resolved_source,
            )
            if fresh.plan_fingerprint != plan.plan_fingerprint or fresh.should_stop:
                raise StkMinsRawReplaceFromProdError("Facts changed during candidate generation", "plan_stale")

        _inspect_targets(plan, checkpoint)  # Check all remaining candidates before any next rename.
        if not completed:
            checkpoint["phase"] = "candidates_verified"
            checkpoint["failure_code"] = None
            checkpoint["operator_action_required"] = False
            _save_checkpoint(run_root, checkpoint)
            checkpoint["phase"] = "promoting"
            checkpoint["promote_started"] = True
            _save_checkpoint(run_root, checkpoint)

        for freq in STK_MINS_RECOVERY_FREQS:
            _check_cancel(cancel_requested)
            item = checkpoint["frequencies"][str(freq)]
            mark = _begin_stage(checkpoint, staging_root, "promote_verify", freq)
            state = _inspect_targets(plan, checkpoint)[str(freq)]
            target = Path(item["target_path"])
            candidate = Path(item["candidate_path"])
            if state != "candidate":
                _audit_recovery_file(plan, item, candidate)
                _check_cancel(cancel_requested)
                os.replace(candidate, target)
                _sync_directory(candidate.parent)
                _sync_directory(target.parent)
                item["state"] = "promoted"
                item["promoted_at"] = _now()
                _save_checkpoint(run_root, checkpoint)
            _audit_recovery_file(plan, item, target)
            item["state"] = "verified"
            item["verified_at"] = _now()
            item["failure_code"] = None
            _finish_stage(checkpoint, staging_root, mark, item)
            _save_checkpoint(run_root, checkpoint)
            _check_cancel(cancel_requested)

        if set(_inspect_targets(plan, checkpoint).values()) != {"candidate"}:
            raise StkMinsRawReplaceFromProdError("Final five-frequency audit failed", "target_drift")
        checkpoint["phase"] = "completed"
        checkpoint["failure_code"] = None
        checkpoint["operator_action_required"] = False
        checkpoint["elapsed_ms"] += int((perf_counter() - started) * 1000)
        _save_checkpoint(run_root, checkpoint)
        report = _apply_report(plan, checkpoint, run_root)
        _write_json(run_root / "final-report.json", report.to_dict())
        return report
    except BaseException as error:
        # Keep every promoted file and all remaining evidence. Never undo data writes.
        code = _failure_code(error)
        checkpoint["phase"] = "failed"
        checkpoint["failure_code"] = code
        checkpoint["operator_action_required"] = True
        checkpoint["elapsed_ms"] += int((perf_counter() - started) * 1000)
        try:
            _save_checkpoint(run_root, checkpoint)
        except OSError:
            pass  # The last durable checkpoint plus file fingerprints remains authoritative.
        raise


def _build_candidates(plan, checkpoint, run_root, source, codes, cancel_requested) -> None:
    for freq in STK_MINS_RECOVERY_FREQS:
        _check_cancel(cancel_requested)
        item = checkpoint["frequencies"][str(freq)]
        candidate = Path(item["candidate_path"])
        if item["candidate_sha256"] is not None:
            _audit_recovery_file(plan, item, candidate)
            continue
        if checkpoint["promote_started"]:
            raise StkMinsRawReplaceFromProdError("Cannot export after promotion began", "candidate_drift")
        mark = _begin_stage(checkpoint, Path(plan.staging_root), "candidate_export_audit", freq)
        _save_checkpoint(run_root, checkpoint)
        _ensure_directory(candidate.parent)
        building = candidate.with_name(f".part-000.{uuid.uuid4()}.parquet")
        source.write_frequency_staging_file(
            trade_date=plan.trade_date, freq=freq, stock_codes=codes, target_path=building,
        )
        _check_cancel(cancel_requested)
        fingerprint = _validate_staged_file(
            freq=freq, path=building, trade_date=plan.trade_date,
            expected_code_count=plan.expected_code_count, expected_code_hash=plan.expected_code_hash,
            expected_source_fact=_frequency_fact_for(plan.frequency_facts, freq),
        )
        _sync_file(building)
        os.replace(building, candidate)
        _sync_directory(candidate.parent)
        item.update(
            candidate_sha256=fingerprint.sha256, candidate_size_bytes=fingerprint.size_bytes,
            candidate_row_count=_frequency_fact_for(plan.frequency_facts, freq).row_count,
        )
        _write_json(run_root / "audits" / f"freq={freq}.json", {
            "freq": freq, "plan_fingerprint": plan.plan_fingerprint,
            "sha256": fingerprint.sha256, "size_bytes": fingerprint.size_bytes,
            "row_count": item["candidate_row_count"],
        })
        _finish_stage(checkpoint, Path(plan.staging_root), mark, item)
        _save_checkpoint(run_root, checkpoint)
        _check_cancel(cancel_requested)


def _inspect_targets(plan, checkpoint) -> dict[str, str]:
    states = {}
    for freq in STK_MINS_RECOVERY_FREQS:
        item = checkpoint["frequencies"][str(freq)]
        target = _file_fingerprint(freq=freq, path=Path(item["target_path"]))
        if _matches(target, item["candidate_sha256"], item["candidate_size_bytes"]):
            states[str(freq)] = "candidate"
            continue
        if not _matches(target, item["approved_old_sha256"], item["approved_old_size_bytes"]):
            raise StkMinsRawReplaceFromProdError(f"Target changed: freq={freq}", "target_drift")
        if item["state"] != "pending" or item["promoted_at"] is not None:
            raise StkMinsRawReplaceFromProdError(f"Target reverted: freq={freq}", "checkpoint_target_mismatch")
        candidate = _file_fingerprint(freq=freq, path=Path(item["candidate_path"]))
        if item["candidate_sha256"] is not None:
            if not _matches(candidate, item["candidate_sha256"], item["candidate_size_bytes"]):
                raise StkMinsRawReplaceFromProdError(f"Frozen candidate changed/missing: freq={freq}", "candidate_drift")
        elif checkpoint["promote_started"]:
            raise StkMinsRawReplaceFromProdError(f"Missing frozen candidate: freq={freq}", "candidate_drift")
        states[str(freq)] = "old"
    return states


def _audit_recovery_file(plan, item, path) -> None:
    freq = int(Path(item["candidate_path"]).parent.name.removeprefix("freq="))
    observed = _validate_staged_file(
        freq=freq, path=path, trade_date=plan.trade_date,
        expected_code_count=plan.expected_code_count, expected_code_hash=plan.expected_code_hash,
        expected_source_fact=_frequency_fact_for(plan.frequency_facts, freq),
    )
    if not _matches(observed, item["candidate_sha256"], item["candidate_size_bytes"]):
        raise StkMinsRawReplaceFromProdError(f"Frozen fingerprint mismatch: {path}", "candidate_drift")


def _matches(fingerprint, sha256, size_bytes) -> bool:
    return sha256 is not None and fingerprint.exists and (
        fingerprint.sha256 == sha256 and fingerprint.size_bytes == size_bytes
    )


def _abort_recovery(plan, checkpoint, run_root):
    for freq in STK_MINS_RECOVERY_FREQS:
        item = checkpoint["frequencies"][str(freq)]
        target_path = Path(item["target_path"])
        target = _file_fingerprint(freq=freq, path=target_path)
        original = next(f for f in plan.target_files if f.freq == freq)
        unchanged = _matches(target, item["approved_old_sha256"], item["approved_old_size_bytes"])
        # A stopped plan can record an already absent target. Abort may acknowledge
        # that absence, but never a disappearance after a successful plan.
        if not original.exists and not target_path.exists():
            unchanged = True
        if (
            item["state"] != "pending" or item["promoted_at"] is not None
            or not unchanged
            or (checkpoint["promote_started"] and item["candidate_sha256"] is not None
                and not Path(item["candidate_path"]).is_file())
        ):
            raise StkMinsRawReplaceFromProdError("Cannot prove zero promotions; keep this run", "abort_unsafe")
    checkpoint["phase"] = "aborted_before_promote"
    checkpoint["failure_code"] = None
    checkpoint["operator_action_required"] = False
    _save_checkpoint(run_root, checkpoint)
    report = _apply_report(plan, checkpoint, run_root)
    _write_json(run_root / "final-report.json", report.to_dict())
    return report


def _apply_report(plan, checkpoint, run_root):
    entries = checkpoint["frequencies"]
    return StkMinsRawReplaceFromProdApplyReport(
        trade_date=plan.trade_date, plan_fingerprint=plan.plan_fingerprint,
        recovery_run_id=plan.recovery_run_id,
        staged_files=tuple(
            StkMinsRecoveryFileFingerprint(
                freq=freq, path=entries[str(freq)]["candidate_path"],
                exists=Path(entries[str(freq)]["candidate_path"]).is_file(),
                size_bytes=entries[str(freq)]["candidate_size_bytes"],
                sha256=entries[str(freq)]["candidate_sha256"],
            ) for freq in STK_MINS_RECOVERY_FREQS
        ),
        checkpoint_path=str(run_root / "checkpoint.json"),
        final_report_path=str(run_root / "final-report.json"),
        promoted_frequency_count=sum(item["state"] == "verified" for item in entries.values()),
        elapsed_ms=checkpoint["elapsed_ms"], phase=checkpoint["phase"],
        staging_free_bytes=checkpoint["staging_free_bytes"],
        candidate_size_bytes_by_freq={freq: item["candidate_size_bytes"] for freq, item in entries.items()},
        stage_records=tuple(checkpoint["stage_records"]),
        slow_operation_warning=checkpoint["slow_operation_warning"],
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
        if (
            observed_schema != stk_mins_assets.STK_MINS_RAW_COLUMN_TYPES
            or tuple(observed_schema) != tuple(stk_mins_assets.STK_MINS_RAW_COLUMNS)
        ):
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
              count(*) FILTER (WHERE freq IS NULL OR CAST(freq AS INTEGER) != {freq}) AS freq_mismatch_count,
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

def _plan_fingerprint(plan: StkMinsRawReplaceFromProdPlan) -> str:
    payload = plan.to_dict()
    for key in (
        "plan_fingerprint", "elapsed_ms", "staging_free_bytes_before",
        "source_row_count_by_freq", "target_size_bytes_by_freq",
    ):
        payload.pop(key)
    return _payload_hash(payload)


def _validate_plan_identity(plan: StkMinsRawReplaceFromProdPlan) -> None:
    _validate_trade_date(plan.trade_date)
    if (
        tuple(f.freq for f in plan.target_files) != tuple(STK_MINS_RECOVERY_FREQS)
        or tuple(sorted({f.freq for f in plan.frequency_facts}))
        != tuple(f.freq for f in plan.frequency_facts)
        or plan.plan_fingerprint != _plan_fingerprint(plan)
    ):
        raise StkMinsRawReplaceFromProdError("Plan identity or frequency evidence mismatch", "checkpoint_identity_mismatch")
    for target in plan.target_files:
        if target.path != str(raw_stk_mins_path(Path(plan.lake_root), target.freq, plan.trade_date)):
            raise StkMinsRawReplaceFromProdError("Plan target path mismatch", "checkpoint_identity_mismatch")
    if not plan.should_stop and (
        tuple(f.freq for f in plan.frequency_facts) != tuple(STK_MINS_RECOVERY_FREQS)
        or plan.expected_code_count <= 0 or plan.task_run is None
    ):
        raise StkMinsRawReplaceFromProdError("Plan is not a single-day five-frequency scope", "scope_invalid")


def _initial_checkpoint(plan, run_root) -> dict:
    return {
        "schema_version": SCHEMA_VERSION, "recovery_kind": RECOVERY_KIND,
        "trade_date": plan.trade_date, "recovery_run_id": plan.recovery_run_id,
        "plan_fingerprint": plan.plan_fingerprint,
        "expected_code_count": plan.expected_code_count,
        "expected_code_hash": plan.expected_code_hash,
        "source_task_run_id": plan.task_run.task_run_id if plan.task_run else None,
        "phase": "planned", "promote_started": False,
        "failure_code": None, "operator_action_required": False,
        "staging_free_bytes_before": plan.staging_free_bytes_before,
        "staging_free_bytes": plan.staging_free_bytes_before,
        "elapsed_ms": 0, "stage_records": [], "candidate_elapsed_ms": 0,
        "slow_operation_warning": False,
        "frequencies": {
            str(f.freq): {
                "target_path": f.path,
                "approved_old_sha256": f.sha256, "approved_old_size_bytes": f.size_bytes,
                "candidate_path": str(run_root / "candidates" / f"freq={f.freq}" / "part-000.parquet"),
                "candidate_sha256": None, "candidate_size_bytes": None,
                "candidate_row_count": None, "state": "pending",
                "promoted_at": None, "verified_at": None, "failure_code": None,
            } for f in plan.target_files
        },
    }


def _save_checkpoint(run_root: Path, checkpoint: dict) -> None:
    checkpoint["updated_at"] = _now()
    checkpoint["checkpoint_hash"] = _checkpoint_hash(checkpoint)
    _write_json(run_root / "checkpoint.json", checkpoint)


def _checkpoint_hash(checkpoint: dict) -> str:
    return _payload_hash({k: v for k, v in checkpoint.items() if k != "checkpoint_hash"})


def _load_checkpoint(run_root: Path, plan) -> dict:
    checkpoint = _read_json(run_root / "checkpoint.json")
    baseline = _initial_checkpoint(plan, run_root)
    identity_keys = (
        "schema_version", "recovery_kind", "trade_date", "recovery_run_id",
        "plan_fingerprint", "expected_code_count", "expected_code_hash", "source_task_run_id",
    )
    try:
        if (
            checkpoint["checkpoint_hash"] != _checkpoint_hash(checkpoint)
            or any(checkpoint[k] != baseline[k] for k in identity_keys)
            or set(checkpoint["frequencies"]) != set(baseline["frequencies"])
            or checkpoint["phase"] not in {
                "planned", "candidates_verified", "promoting", "completed", "failed", "aborted_before_promote",
            }
        ):
            raise ValueError("identity/hash/phase mismatch")
        volume_paths = [Path(plan.lake_root), Path(plan.staging_root), run_root]
        for freq, item in checkpoint["frequencies"].items():
            expected = baseline["frequencies"][freq]
            for key in ("target_path", "candidate_path", "approved_old_sha256", "approved_old_size_bytes"):
                if item[key] != expected[key]:
                    raise ValueError(f"{key} mismatch")
            _safe_child(Path(item["target_path"]), Path(plan.lake_root))
            _safe_child(Path(item["candidate_path"]), run_root)
            for parent in (Path(item["candidate_path"]).parent, run_root / "audits"):
                _safe_child(parent, run_root)
                while not parent.exists():
                    parent = parent.parent
                volume_paths.append(parent)
            if item["state"] not in {"pending", "promoted", "verified"}:
                raise ValueError("unknown frequency state")
            if item["candidate_sha256"] is not None:
                audit = _read_json(run_root / "audits" / f"freq={freq}.json")
                if audit != {
                    "freq": int(freq), "plan_fingerprint": plan.plan_fingerprint,
                    "sha256": item["candidate_sha256"], "size_bytes": item["candidate_size_bytes"],
                    "row_count": item["candidate_row_count"],
                } or item["candidate_row_count"] != _frequency_fact_for(plan.frequency_facts, int(freq)).row_count:
                    raise ValueError("candidate audit mismatch")
        _assert_same_volume(volume_paths)
    except (KeyError, TypeError, ValueError) as error:
        raise StkMinsRawReplaceFromProdError(str(error), "checkpoint_identity_mismatch") from error
    return checkpoint


def _recovery_paths(lake_root, staging_root, trade_date, run_id) -> tuple[Path, Path, Path]:
    lake_root = Path(lake_root).expanduser().resolve()
    staging_root = Path(staging_root or DEFAULT_LAKE_STAGING_ROOT).expanduser().resolve()
    if lake_root != Path(DEFAULT_LAKE_ROOT).resolve() or staging_root != Path(DEFAULT_LAKE_STAGING_ROOT).resolve():
        raise StkMinsRawReplaceFromProdError("Recovery requires canonical Lake and staging roots", "scope_invalid")
    if not lake_root.is_dir() or not staging_root.is_dir() or lake_root == staging_root:
        raise StkMinsRawReplaceFromProdError("Lake and staging roots must exist separately", "scope_invalid")
    run_root = stk_mins_raw_recovery_run_root(staging_root, trade_date, run_id)
    _safe_child(run_root, staging_root)
    parents = [lake_root, staging_root]
    for freq in STK_MINS_RECOVERY_FREQS:
        target = raw_stk_mins_path(lake_root, freq, trade_date)
        _safe_child(target, lake_root)
        if not target.parent.is_dir():
            raise StkMinsRawReplaceFromProdError("Raw target parent is missing", "scope_invalid")
        parents.append(target.parent)
    current = run_root
    while not current.exists():
        current = current.parent
    parents.append(current)
    _assert_same_volume(parents)
    return lake_root, staging_root, run_root


def _assert_same_volume(paths: Sequence[Path]) -> None:
    if len({path.stat().st_dev for path in paths}) != 1:
        raise StkMinsRawReplaceFromProdError("Recovery paths cross filesystems", "cross_filesystem")


def _safe_child(path: Path, root: Path) -> Path:
    absolute = path.absolute()
    if absolute.resolve() != absolute or not absolute.is_relative_to(root.resolve()):
        raise StkMinsRawReplaceFromProdError(f"Path escapes run/root or uses symlink: {path}", "scope_invalid")
    return absolute


def _assert_new_run_allowed(run_root: Path) -> None:
    if run_root.exists():
        raise StkMinsRawReplaceFromProdError("Existing run must be resumed", "unfinished_run")
    if run_root.parent.exists():
        for existing in sorted(run_root.parent.iterdir()):
            _safe_child(existing, run_root.parent)
            if not existing.is_dir():
                continue
            plan = load_stk_mins_raw_replace_from_prod_plan(existing / "plan.json")
            checkpoint = _load_checkpoint(existing, plan)
            if checkpoint["phase"] not in {"completed", "aborted_before_promote"}:
                raise StkMinsRawReplaceFromProdError(f"Resume or inspect existing run: {existing}", "unfinished_run")
    # This is a preflight, not a process lock. The human maintenance window is mandatory.


def _read_json(path: Path) -> dict:
    if path.is_symlink():
        raise StkMinsRawReplaceFromProdError(f"Refuse symlink JSON: {path}", "scope_invalid")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise StkMinsRawReplaceFromProdError(f"Cannot read recovery evidence: {path}", "checkpoint_identity_mismatch") from error
    if not isinstance(payload, dict):
        raise StkMinsRawReplaceFromProdError("Recovery evidence must be an object", "checkpoint_identity_mismatch")
    return payload


def _ensure_directory(path: Path) -> None:
    if not path.exists():
        _ensure_directory(path.parent)
        path.mkdir()
        _sync_directory(path.parent)


def _sync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _sync_file(path: Path) -> None:
    with path.open("rb") as handle:
        os.fsync(handle.fileno())


def _write_json(path: Path, payload: Mapping[str, object]) -> None:
    if path.is_symlink():
        raise StkMinsRawReplaceFromProdError(f"Refuse symlink output: {path}", "scope_invalid")
    _ensure_directory(path.parent)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4()}.tmp")
    with temporary.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    _sync_directory(path.parent)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _check_cancel(cancel_requested) -> None:
    if cancel_requested is not None and cancel_requested():
        raise StkMinsRawReplaceFromProdError("Operator cancelled; retain this run", "cancelled")


def _begin_stage(checkpoint, staging_root, phase, freq):
    checkpoint["staging_free_bytes"] = shutil.disk_usage(staging_root).free
    mark = {
        "phase": phase, "freq": freq, "started_at": _now(), "ended_at": None,
        "completed_frequencies": sum(f["state"] == "verified" for f in checkpoint["frequencies"].values()),
        "staging_free_bytes_before": checkpoint["staging_free_bytes"],
    }
    checkpoint["stage_records"].append(mark)
    print(json.dumps({**mark, "waiting_for_database": phase == "candidate_export_audit"}), file=sys.stderr, flush=True)
    return mark, perf_counter()


def _finish_stage(checkpoint, staging_root, started, item):
    mark, clock_start = started
    mark.update(
        ended_at=_now(), elapsed_ms=int((perf_counter() - clock_start) * 1000),
        row_count=item["candidate_row_count"], size_bytes=item["candidate_size_bytes"],
        completed_frequencies=sum(f["state"] == "verified" for f in checkpoint["frequencies"].values()),
    )
    checkpoint["staging_free_bytes"] = shutil.disk_usage(staging_root).free
    mark["staging_free_bytes_after"] = checkpoint["staging_free_bytes"]
    if mark["phase"] == "candidate_export_audit":
        checkpoint["candidate_elapsed_ms"] += mark["elapsed_ms"]
    if checkpoint["candidate_elapsed_ms"] > 300_000:
        checkpoint["slow_operation_warning"] = True
    mark["slow_operation_warning"] = checkpoint["slow_operation_warning"]
    print(json.dumps(mark), file=sys.stderr, flush=True)


def _failure_code(error: BaseException) -> str:
    if isinstance(error, StkMinsRawReplaceFromProdError):
        return error.code
    if isinstance(error, (KeyboardInterrupt, SystemExit)):
        return "interrupted"
    if isinstance(error, (MemoryError, OutOfMemoryException)) or (
        isinstance(error, OSError) and error.errno in {errno.ENOSPC, errno.ENOMEM, errno.EDQUOT}
    ):
        return "resource_exhausted"
    if isinstance(error, OSError) and error.errno == errno.EXDEV:
        return "cross_filesystem"
    return "recovery_failed"
