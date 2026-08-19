"""D5 serving-contract audit and runless-event recovery for daily nine-turn."""

from __future__ import annotations

import csv
import hashlib
import json
import re
import subprocess
import time
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

import dagster as dg
from dagster._core.definitions.asset_checks.asset_check_evaluation import (
    AssetCheckEvaluationTargetMaterializationData,
)

from orchestrator.defs.bootstrap.qfq_nineturn_events import (
    report_qfq_nineturn_check_event,
    report_qfq_nineturn_materialization_event,
)
from orchestrator.defs.bootstrap.stock_daily_qfq_nineturn_no_price_events import (
    CONTRACT as GOLD_CONTRACT,
)
from orchestrator.defs.bootstrap.stock_daily_qfq_nineturn_no_price_events import (
    EVENT_REVISION as GOLD_EVENT_REVISION,
)
from orchestrator.defs.bootstrap.stock_daily_qfq_nineturn_no_price_events import (
    StockDailyQfqNineTurnNoPriceEventPartition,
    load_stock_daily_qfq_nineturn_no_price_event_plan,
)
from orchestrator.defs.duckdb_sql import read_parquet
from orchestrator.defs.paths import DEFAULT_LAKE_ROOT
from orchestrator.defs.prod_db.stock_daily_qfq_nineturn import (
    PROD_CORE_STOCK_DAILY_QFQ_NINETURN_COLUMNS,
    PROD_CORE_STOCK_DAILY_QFQ_NINETURN_CONSTRAINTS,
    PROD_CORE_STOCK_DAILY_QFQ_NINETURN_INDEXES,
    PROD_CORE_STOCK_DAILY_QFQ_NINETURN_TABLE,
    ProdCoreStockDailyQfqNineTurnCheckpointAudit,
    ProdCoreStockDailyQfqNineTurnContractSnapshot,
    stock_daily_qfq_nineturn_business_content_hash,
)
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.run_contracts.metadata import (
    CheckScope,
    build_check_metadata,
    build_materialization_metadata,
)
from orchestrator.defs.run_contracts.qfq_nineturn import QFQ_NINETURN_VERSION

SCHEMA_VERSION = 1
SNAPSHOT_PHASE = "stock_daily_qfq_nineturn_no_price_serving_contract_snapshot"
PLAN_PHASE = "stock_daily_qfq_nineturn_no_price_serving_event_plan"
APPLY_PHASE = "stock_daily_qfq_nineturn_no_price_serving_event_apply"
EVENT_REVISION = "stock_daily_qfq_nineturn_serving_v2_no_price"
CONTRACT = "stock_daily_qfq_nineturn_serving_no_price_v2"
EVENT_BACKFILL_SCOPE = "serving_no_price_all_materializations_recent_checks"
ASSET_KEY = "prod_core_stock_daily_qfq_nineturn"
CHECK_NAME = "prod_core_stock_daily_qfq_nineturn_partition_check"
CHECK_WINDOW = 20
MAX_CHECK_HISTORY = 500
MAX_MATERIALIZATION_EVENTS = 4_000
MAX_CHECK_EVENTS = CHECK_WINDOW
PROD_CORE_STOCK_DAILY_QFQ_NINETURN_NO_PRICE_MIGRATION = "20260816_000137"
PROD_CORE_STOCK_DAILY_QFQ_NINETURN_PREVIOUS_MIGRATION = "20260814_000136"
PROD_CORE_STOCK_DAILY_QFQ_NINETURN_LEGACY_COLUMNS = (
    "ts_code",
    "trade_date",
    "close_qfq",
    "up_count",
    "down_count",
    "nine_up_turn",
    "nine_down_turn",
    "formula_version",
    "published_at",
)
PROD_CORE_STOCK_DAILY_QFQ_NINETURN_LEGACY_CONSTRAINTS = tuple(
    sorted(
        (
            *PROD_CORE_STOCK_DAILY_QFQ_NINETURN_CONSTRAINTS,
            "ck_equity_qfq_nineturn_daily_close_positive",
        )
    )
)
WRITER_SENSOR_NAMES = (
    "gold_stock_daily_qfq_nineturn_update_job_sensor",
    "prod_core_stock_daily_qfq_nineturn_sync_job_sensor",
)
WRITER_JOB_NAMES = (
    "gold_stock_daily_qfq_nineturn_update_job",
    "prod_core_stock_daily_qfq_nineturn_sync_job",
)
_IN_FLIGHT_STATUSES = (
    dg.DagsterRunStatus.QUEUED,
    dg.DagsterRunStatus.STARTING,
    dg.DagsterRunStatus.STARTED,
    dg.DagsterRunStatus.CANCELING,
)
_DEPLOYED_REVISION_PATTERN = re.compile(r"[0-9a-f]{40}")
_SERVING_CONTRACT_SNAPSHOT_SQL = f"""
BEGIN READ ONLY;
WITH
  migration AS (
    SELECT COALESCE(json_agg(version_num ORDER BY version_num), '[]'::json) AS value
    FROM alembic_version
  ),
  columns_contract AS (
    SELECT COALESCE(
      json_agg(
        json_build_array(
          column_name, data_type, udt_name, is_nullable, column_default
        ) ORDER BY ordinal_position
      ),
      '[]'::json
    ) AS value
    FROM information_schema.columns
    WHERE table_schema = 'core_serving'
      AND table_name = 'equity_qfq_nineturn_daily'
  ),
  named_constraints AS (
    SELECT COALESCE(
      json_agg(constraint_name ORDER BY constraint_name),
      '[]'::json
    ) AS value
    FROM information_schema.table_constraints
    WHERE table_schema = 'core_serving'
      AND table_name = 'equity_qfq_nineturn_daily'
      AND (
        constraint_name LIKE 'ck_equity_qfq_nineturn_daily_%'
        OR constraint_name = 'pk_equity_qfq_nineturn_daily'
      )
  ),
  indexes_contract AS (
    SELECT COALESCE(json_agg(indexname ORDER BY indexname), '[]'::json) AS value
    FROM pg_indexes
    WHERE schemaname = 'core_serving'
      AND tablename = 'equity_qfq_nineturn_daily'
  ),
  privileges_contract AS (
    SELECT COALESCE(
      json_agg(
        json_build_array(grantee, privilege_type, is_grantable)
        ORDER BY grantee, privilege_type, is_grantable
      ),
      '[]'::json
    ) AS value
    FROM information_schema.role_table_grants
    WHERE table_schema = 'core_serving'
      AND table_name = 'equity_qfq_nineturn_daily'
  ),
  owner_contract AS (
    SELECT tableowner AS value
    FROM pg_tables
    WHERE schemaname = 'core_serving'
      AND tablename = 'equity_qfq_nineturn_daily'
  ),
  stats AS (
    SELECT
      COUNT(*)::BIGINT AS row_count,
      COUNT(DISTINCT trade_date)::BIGINT AS partition_count,
      MIN(trade_date)::TEXT AS first_trade_date,
      MAX(trade_date)::TEXT AS last_trade_date
    FROM {PROD_CORE_STOCK_DAILY_QFQ_NINETURN_TABLE}
  )
SELECT json_build_object(
  'transaction_read_only', current_setting('transaction_read_only'),
  'migration_versions', migration.value,
  'columns', columns_contract.value,
  'constraints', named_constraints.value,
  'indexes', indexes_contract.value,
  'privileges', privileges_contract.value,
  'table_owner', owner_contract.value,
  'row_count', stats.row_count,
  'partition_count', stats.partition_count,
  'first_trade_date', stats.first_trade_date,
  'last_trade_date', stats.last_trade_date
)::TEXT
FROM migration, columns_contract, named_constraints, indexes_contract,
     privileges_contract, owner_contract, stats;
COMMIT;
"""
_SERVING_CHECKPOINT_COPY_SQL = f"""
BEGIN READ ONLY;
COPY (
  SELECT
    ts_code,
    trade_date::TEXT,
    up_count,
    down_count,
    nine_up_turn,
    nine_down_turn,
    formula_version
  FROM {PROD_CORE_STOCK_DAILY_QFQ_NINETURN_TABLE}
  WHERE trade_date = ANY(ARRAY[{{date_literals}}])
  ORDER BY trade_date, ts_code
) TO STDOUT WITH (FORMAT CSV, NULL '\\N');
COMMIT;
"""


class StockDailyQfqNineTurnNoPriceServingEventError(RuntimeError):
    """Raised when a D5 serving gate fails closed."""


class StockDailyQfqNineTurnServingAuditReader(Protocol):
    def snapshot(self) -> ProdCoreStockDailyQfqNineTurnContractSnapshot: ...

    def checkpoint(
        self,
        *,
        expected_content_hashes: Mapping[str, object],
    ) -> ProdCoreStockDailyQfqNineTurnCheckpointAudit: ...


@dataclass(slots=True)
class PsqlRemoteStockDailyQfqNineTurnServingAuditReader:
    repo_root: Path

    def snapshot(self) -> ProdCoreStockDailyQfqNineTurnContractSnapshot:
        payload = json.loads(self._run_text(_SERVING_CONTRACT_SNAPSHOT_SQL))
        if payload.get("transaction_read_only") != "on":
            raise StockDailyQfqNineTurnNoPriceServingEventError(
                "Prod contract snapshot did not run in a read-only transaction."
            )
        return _snapshot_from_dict(payload)

    def checkpoint(
        self,
        *,
        expected_content_hashes: Mapping[str, object],
    ) -> ProdCoreStockDailyQfqNineTurnCheckpointAudit:
        normalized_expected = {
            str(partition_key): str(content_hash).strip().lower()
            for partition_key, content_hash in expected_content_hashes.items()
        }
        if not normalized_expected:
            return ProdCoreStockDailyQfqNineTurnCheckpointAudit(
                passed=True,
                expected_partition_count=0,
                observed_partition_count=0,
                read_back_row_count=0,
                failed_partition_keys=(),
            )
        if any(
            not re.fullmatch(r"\d{4}-\d{2}-\d{2}", partition_key)
            for partition_key in normalized_expected
        ):
            raise StockDailyQfqNineTurnNoPriceServingEventError(
                "Prod checkpoint contains an invalid partition key."
            )
        if any(
            not re.fullmatch(r"[0-9a-f]{64}", content_hash)
            for content_hash in normalized_expected.values()
        ):
            raise StockDailyQfqNineTurnNoPriceServingEventError(
                "Prod checkpoint requires lowercase SHA-256 hashes."
            )
        date_literals = ",".join(
            f"DATE '{partition_key}'" for partition_key in sorted(normalized_expected)
        )
        sql = _SERVING_CHECKPOINT_COPY_SQL.format(date_literals=date_literals)
        command = self._command(sql)
        process = subprocess.Popen(
            command,
            cwd=self.repo_root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if process.stdout is None or process.stderr is None:
            process.kill()
            raise StockDailyQfqNineTurnNoPriceServingEventError(
                "Prod checkpoint process pipes are unavailable."
            )
        observed_hashes: dict[str, str] = {}
        read_back_row_count = 0
        current_partition_key: str | None = None
        current_digest: hashlib._Hash | None = None
        current_row_count = 0
        for raw_line in process.stdout:
            row = next(csv.reader((raw_line,)))
            if len(row) != 7:
                process.kill()
                raise StockDailyQfqNineTurnNoPriceServingEventError(
                    "Prod checkpoint returned an invalid row contract."
                )
            partition_key = row[1]
            if partition_key not in normalized_expected:
                process.kill()
                raise StockDailyQfqNineTurnNoPriceServingEventError(
                    "Prod checkpoint returned an unexpected partition."
                )
            if current_partition_key != partition_key:
                if current_partition_key is not None and current_digest is not None:
                    observed_hashes[current_partition_key] = current_digest.hexdigest()
                    read_back_row_count += current_row_count
                current_partition_key = partition_key
                current_digest = hashlib.sha256()
                current_row_count = 0
            if current_digest is None:
                process.kill()
                raise StockDailyQfqNineTurnNoPriceServingEventError(
                    "Prod checkpoint digest was not initialized."
                )
            payload = "\t".join(
                (
                    row[0],
                    row[1],
                    row[2],
                    row[3],
                    "" if row[4] == r"\N" else row[4],
                    "" if row[5] == r"\N" else row[5],
                    row[6],
                )
            )
            if current_row_count:
                current_digest.update(b"\n")
            current_digest.update(payload.encode("utf-8"))
            current_row_count += 1
        if current_partition_key is not None and current_digest is not None:
            observed_hashes[current_partition_key] = current_digest.hexdigest()
            read_back_row_count += current_row_count
        stderr = process.stderr.read()
        return_code = process.wait()
        if return_code != 0:
            raise StockDailyQfqNineTurnNoPriceServingEventError(
                "Prod checkpoint read failed: " + stderr.strip()[:500]
            )
        failed_partition_keys = tuple(
            partition_key
            for partition_key, expected_hash in sorted(normalized_expected.items())
            if observed_hashes.get(partition_key) != expected_hash
        )
        return ProdCoreStockDailyQfqNineTurnCheckpointAudit(
            passed=not failed_partition_keys,
            expected_partition_count=len(normalized_expected),
            observed_partition_count=len(observed_hashes),
            read_back_row_count=read_back_row_count,
            failed_partition_keys=failed_partition_keys,
        )

    def _run_text(self, sql: str) -> str:
        completed = subprocess.run(
            self._command(sql),
            cwd=self.repo_root,
            check=False,
            text=True,
            capture_output=True,
        )
        if completed.returncode != 0:
            raise StockDailyQfqNineTurnNoPriceServingEventError(
                "Prod contract snapshot failed: " + completed.stderr.strip()[:500]
            )
        output = completed.stdout.strip()
        if not output:
            raise StockDailyQfqNineTurnNoPriceServingEventError(
                "Prod contract snapshot returned no JSON."
            )
        return output

    def _command(self, sql: str) -> list[str]:
        script = (self.repo_root / "scripts/psql-remote.sh").resolve()
        if not script.is_file() or not script.is_relative_to(self.repo_root.resolve()):
            raise StockDailyQfqNineTurnNoPriceServingEventError(
                "Required scripts/psql-remote.sh is missing."
            )
        return ["bash", str(script), "-c", sql, "--", "-qAt"]


@dataclass(frozen=True, slots=True)
class StockDailyQfqNineTurnServingPartition:
    partition_key: str
    source_relative_path: str
    source_file_sha256: str
    row_count: int
    business_content_hash: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class StockDailyQfqNineTurnServingEventCandidate:
    partition_key: str
    event_type: str
    check_name: str | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class StockDailyQfqNineTurnServingEventPlan:
    report_path: Path
    identity_manifest_path: Path
    candidate_manifest_path: Path
    baseline_snapshot_report_path: Path
    d4_event_plan_report_path: Path
    plan_fingerprint: str
    deployed_revision: str
    partitions: tuple[StockDailyQfqNineTurnServingPartition, ...]
    candidates: tuple[StockDailyQfqNineTurnServingEventCandidate, ...]
    stop_reasons: tuple[str, ...]
    report: Mapping[str, object]

    @property
    def should_stop(self) -> bool:
        return bool(self.stop_reasons)

    def to_summary_dict(self) -> dict[str, object]:
        return {
            "phase": PLAN_PHASE,
            "read_only": True,
            "report_path": str(self.report_path),
            "plan_fingerprint": self.plan_fingerprint,
            "partition_count": len(self.partitions),
            "planned_materialization_event_count": sum(
                item.event_type == "materialization" for item in self.candidates
            ),
            "planned_check_event_count": sum(
                item.event_type == "check" for item in self.candidates
            ),
            "planned_event_count": len(self.candidates),
            "should_stop": self.should_stop,
            "stop_reasons": list(self.stop_reasons),
        }


@dataclass(frozen=True, slots=True)
class StockDailyQfqNineTurnServingEventApplyReport:
    report_path: Path
    plan_fingerprint: str
    batch_id: str
    materialization_event_count: int
    check_event_count: int
    post_plan_event_count: int
    current_revision_materialization_count: int
    current_revision_check_count: int
    elapsed_ms: float

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["report_path"] = str(self.report_path)
        return payload


def capture_stock_daily_qfq_nineturn_serving_contract_snapshot(
    *,
    audit_reader: StockDailyQfqNineTurnServingAuditReader,
    output_dir: Path = Path("/private/tmp"),
) -> Path:
    """Capture the pre-migration serving contract in a read-only transaction."""

    snapshot = audit_reader.snapshot()
    payload = {
        "schema_version": SCHEMA_VERSION,
        "phase": SNAPSHOT_PHASE,
        "read_only": True,
        "captured_at": datetime.now(UTC).isoformat(),
        "snapshot": snapshot.to_dict(),
    }
    fingerprint = _hash_payload(payload["snapshot"])
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / (
        "stock_daily_qfq_nineturn_no_price_serving_contract_snapshot_"
        f"{fingerprint}.json"
    )
    _write_json(report_path, {**payload, "snapshot_fingerprint": fingerprint})
    return report_path


def plan_stock_daily_qfq_nineturn_no_price_serving_events(
    *,
    instance: dg.DagsterInstance,
    baseline_snapshot_report_path: Path,
    d4_event_plan_report_path: Path,
    expected_d4_plan_fingerprint: str,
    deployed_revision: str,
    audit_reader: StockDailyQfqNineTurnServingAuditReader,
    lake_root: Path = Path(DEFAULT_LAKE_ROOT),
    duckdb_resource: DuckDBResource | None = None,
    output_dir: Path = Path("/private/tmp"),
) -> StockDailyQfqNineTurnServingEventPlan:
    """Build a read-only D5 plan after migration and code deployment."""

    started = time.perf_counter()
    normalized_revision = deployed_revision.strip().lower()
    if not _DEPLOYED_REVISION_PATTERN.fullmatch(normalized_revision):
        raise StockDailyQfqNineTurnNoPriceServingEventError(
            "Deployed revision must be a full lowercase Git SHA."
        )
    baseline_payload, baseline = _load_snapshot_report(baseline_snapshot_report_path)
    d4_plan = load_stock_daily_qfq_nineturn_no_price_event_plan(
        d4_event_plan_report_path
    )
    if d4_plan.plan_fingerprint != expected_d4_plan_fingerprint:
        raise StockDailyQfqNineTurnNoPriceServingEventError(
            "Reviewed D4 event-plan fingerprint does not match."
        )
    normalized_lake_root = Path(lake_root).resolve()
    if Path(str(d4_plan.report["lake_root"])).resolve() != normalized_lake_root:
        raise StockDailyQfqNineTurnNoPriceServingEventError(
            "D4 event-plan Lake root does not match D5."
        )

    stop_reasons = list(_baseline_stop_reasons(baseline))
    if d4_plan.candidates:
        stop_reasons.append("d4_event_recovery_not_complete")
    if int(d4_plan.report.get("partition_count", -1)) <= 0:
        stop_reasons.append("d4_partition_scope_empty")
    if (
        int(d4_plan.report.get("state", {}).get("current_revision_check_count", -1))
        != CHECK_WINDOW
    ):
        stop_reasons.append("d4_recent_checks_not_current")

    resource = duckdb_resource or DuckDBResource()
    partitions, identity_stop_reasons = _build_serving_partitions(
        lake_root=normalized_lake_root,
        d4_partitions=d4_plan.partitions,
        duckdb_resource=resource,
    )
    stop_reasons.extend(identity_stop_reasons)
    expected_hashes = {
        item.partition_key: item.business_content_hash for item in partitions
    }

    post_snapshot = audit_reader.snapshot()
    stop_reasons.extend(
        _post_migration_stop_reasons(
            baseline=baseline,
            post=post_snapshot,
            expected_partition_count=len(partitions),
            expected_row_count=sum(item.row_count for item in partitions),
        )
    )
    checkpoint = audit_reader.checkpoint(expected_content_hashes=expected_hashes)
    if not checkpoint.passed:
        stop_reasons.append("prod_business_content_mismatch")
    if checkpoint.observed_partition_count != len(partitions):
        stop_reasons.append("prod_partition_scope_mismatch")
    if checkpoint.read_back_row_count != sum(item.row_count for item in partitions):
        stop_reasons.append("prod_row_count_mismatch")

    sensor_states = _writer_sensor_states(instance)
    if any(status != "STOPPED" for status in sensor_states.values()):
        stop_reasons.append("writer_sensor_not_stopped")
    active_runs = _active_writer_run_counts(instance)
    if any(active_runs.values()):
        stop_reasons.append("writer_run_in_flight")
    stop_reasons.extend(
        _gold_event_stop_reasons(instance=instance, partitions=partitions)
    )

    recent_partition_keys = tuple(
        item.partition_key for item in partitions[-CHECK_WINDOW:]
    )
    candidates, event_state = _event_candidates(
        instance=instance,
        partitions=partitions,
        recent_partition_keys=recent_partition_keys,
        deployed_revision=normalized_revision,
    )
    materialization_count = sum(
        item.event_type == "materialization" for item in candidates
    )
    check_count = sum(item.event_type == "check" for item in candidates)
    if materialization_count > MAX_MATERIALIZATION_EVENTS:
        stop_reasons.append("materialization_event_limit_exceeded")
    if check_count > MAX_CHECK_EVENTS:
        stop_reasons.append("check_event_limit_exceeded")

    normalized_stop_reasons = tuple(sorted(set(stop_reasons)))
    physical_fingerprint = _hash_payload([item.to_dict() for item in partitions])
    fingerprint_payload = {
        "schema_version": SCHEMA_VERSION,
        "asset_key": ASSET_KEY,
        "check_name": CHECK_NAME,
        "event_revision": EVENT_REVISION,
        "contract": CONTRACT,
        "migration_revision": PROD_CORE_STOCK_DAILY_QFQ_NINETURN_NO_PRICE_MIGRATION,
        "deployed_revision": normalized_revision,
        "baseline_snapshot_sha256": _sha256_path(baseline_snapshot_report_path),
        "baseline_snapshot_fingerprint": baseline_payload["snapshot_fingerprint"],
        "d4_plan_fingerprint": d4_plan.plan_fingerprint,
        "physical_fingerprint": physical_fingerprint,
        "post_contract_snapshot": post_snapshot.to_dict(),
        "prod_checkpoint": asdict(checkpoint),
        "event_state": event_state,
        "candidates": [item.to_dict() for item in candidates],
        "stop_reasons": list(normalized_stop_reasons),
    }
    plan_fingerprint = _hash_payload(fingerprint_payload)
    output_dir.mkdir(parents=True, exist_ok=True)
    identity_manifest_path = output_dir / (
        f"stock_daily_qfq_nineturn_no_price_serving_identity_{plan_fingerprint}.jsonl"
    )
    candidate_manifest_path = output_dir / (
        f"stock_daily_qfq_nineturn_no_price_serving_candidates_{plan_fingerprint}.jsonl"
    )
    _write_jsonl(identity_manifest_path, [item.to_dict() for item in partitions])
    _write_jsonl(candidate_manifest_path, [item.to_dict() for item in candidates])
    report_path = output_dir / (
        f"stock_daily_qfq_nineturn_no_price_serving_event_plan_{plan_fingerprint}.json"
    )
    report = {
        **fingerprint_payload,
        "phase": PLAN_PHASE,
        "read_only": True,
        "planned_at": datetime.now(UTC).isoformat(),
        "plan_fingerprint": plan_fingerprint,
        "lake_root": str(normalized_lake_root),
        "baseline_snapshot_report_path": str(baseline_snapshot_report_path),
        "d4_event_plan_report_path": str(d4_event_plan_report_path),
        "identity_manifest_path": str(identity_manifest_path),
        "identity_manifest_sha256": _sha256_path(identity_manifest_path),
        "candidate_manifest_path": str(candidate_manifest_path),
        "candidate_manifest_sha256": _sha256_path(candidate_manifest_path),
        "partition_count": len(partitions),
        "row_count": sum(item.row_count for item in partitions),
        "first_partition_key": partitions[0].partition_key if partitions else None,
        "last_partition_key": partitions[-1].partition_key if partitions else None,
        "recent_check_partition_keys": list(recent_partition_keys),
        "sensor_states": sensor_states,
        "active_writer_run_counts": active_runs,
        "planned_materialization_event_count": materialization_count,
        "planned_check_event_count": check_count,
        "planned_event_count": len(candidates),
        "should_stop": bool(normalized_stop_reasons),
        "write_counters": {
            "formal_lake": 0,
            "prod_rows": 0,
            "dagster_events": 0,
        },
        "performance": {
            "gold_partition_scan_count": len(partitions),
            "prod_stream_fetch_size": 1_000,
            "materialization_event_write_limit": MAX_MATERIALIZATION_EVENTS,
            "check_event_write_limit": MAX_CHECK_EVENTS,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
        },
    }
    _write_json(report_path, report)
    return StockDailyQfqNineTurnServingEventPlan(
        report_path=report_path,
        identity_manifest_path=identity_manifest_path,
        candidate_manifest_path=candidate_manifest_path,
        baseline_snapshot_report_path=Path(baseline_snapshot_report_path),
        d4_event_plan_report_path=Path(d4_event_plan_report_path),
        plan_fingerprint=plan_fingerprint,
        deployed_revision=normalized_revision,
        partitions=partitions,
        candidates=candidates,
        stop_reasons=normalized_stop_reasons,
        report=report,
    )


def load_stock_daily_qfq_nineturn_no_price_serving_event_plan(
    report_path: Path,
) -> StockDailyQfqNineTurnServingEventPlan:
    payload = _load_json(report_path)
    if (
        payload.get("schema_version") != SCHEMA_VERSION
        or payload.get("phase") != PLAN_PHASE
        or payload.get("read_only") is not True
    ):
        raise StockDailyQfqNineTurnNoPriceServingEventError(
            "Unsupported D5 serving event plan."
        )
    if payload.get("should_stop"):
        raise StockDailyQfqNineTurnNoPriceServingEventError(
            f"D5 plan has stop reasons: {payload.get('stop_reasons', [])}."
        )
    identity_path = Path(str(payload["identity_manifest_path"]))
    candidate_path = Path(str(payload["candidate_manifest_path"]))
    if _sha256_path(identity_path) != str(payload["identity_manifest_sha256"]):
        raise StockDailyQfqNineTurnNoPriceServingEventError(
            "D5 identity manifest SHA-256 changed."
        )
    if _sha256_path(candidate_path) != str(payload["candidate_manifest_sha256"]):
        raise StockDailyQfqNineTurnNoPriceServingEventError(
            "D5 candidate manifest SHA-256 changed."
        )
    partitions = tuple(
        StockDailyQfqNineTurnServingPartition(**item)
        for item in _load_jsonl(identity_path)
    )
    candidates = tuple(
        StockDailyQfqNineTurnServingEventCandidate(**item)
        for item in _load_jsonl(candidate_path)
    )
    return StockDailyQfqNineTurnServingEventPlan(
        report_path=Path(report_path),
        identity_manifest_path=identity_path,
        candidate_manifest_path=candidate_path,
        baseline_snapshot_report_path=Path(
            str(payload["baseline_snapshot_report_path"])
        ),
        d4_event_plan_report_path=Path(str(payload["d4_event_plan_report_path"])),
        plan_fingerprint=str(payload["plan_fingerprint"]),
        deployed_revision=str(payload["deployed_revision"]),
        partitions=partitions,
        candidates=candidates,
        stop_reasons=(),
        report=payload,
    )


def apply_stock_daily_qfq_nineturn_no_price_serving_events(
    *,
    instance: dg.DagsterInstance,
    plan: StockDailyQfqNineTurnServingEventPlan,
    expected_plan_fingerprint: str,
    confirm_apply: bool,
    audit_reader: StockDailyQfqNineTurnServingAuditReader,
    duckdb_resource: DuckDBResource | None = None,
    output_dir: Path = Path("/private/tmp"),
) -> StockDailyQfqNineTurnServingEventApplyReport:
    """Append only the serving events from an unchanged fresh D5 plan."""

    if not confirm_apply:
        raise StockDailyQfqNineTurnNoPriceServingEventError(
            "D5 serving event apply requires explicit confirmation."
        )
    if plan.plan_fingerprint != expected_plan_fingerprint:
        raise StockDailyQfqNineTurnNoPriceServingEventError(
            "Explicit D5 fingerprint does not match the plan."
        )
    fresh_plan = plan_stock_daily_qfq_nineturn_no_price_serving_events(
        instance=instance,
        baseline_snapshot_report_path=plan.baseline_snapshot_report_path,
        d4_event_plan_report_path=plan.d4_event_plan_report_path,
        expected_d4_plan_fingerprint=str(plan.report["d4_plan_fingerprint"]),
        deployed_revision=plan.deployed_revision,
        audit_reader=audit_reader,
        lake_root=Path(str(plan.report["lake_root"])),
        duckdb_resource=duckdb_resource,
        output_dir=output_dir,
    )
    if (
        fresh_plan.should_stop
        or fresh_plan.plan_fingerprint != plan.plan_fingerprint
        or fresh_plan.partitions != plan.partitions
        or fresh_plan.candidates != plan.candidates
    ):
        raise StockDailyQfqNineTurnNoPriceServingEventError(
            "D5 serving event plan is stale; generate and review a new plan."
        )

    started = time.perf_counter()
    batch_id = str(uuid.uuid4())
    by_partition = {item.partition_key: item for item in plan.partitions}
    materialization_candidates = tuple(
        item for item in plan.candidates if item.event_type == "materialization"
    )
    check_candidates = tuple(
        item for item in plan.candidates if item.event_type == "check"
    )
    for candidate in materialization_candidates:
        partition = by_partition[candidate.partition_key]
        report_qfq_nineturn_materialization_event(
            instance,
            dg.AssetMaterialization(
                asset_key=dg.AssetKey(ASSET_KEY),
                partition=partition.partition_key,
                metadata=build_materialization_metadata(
                    uri=(
                        f"postgresql://prod/{PROD_CORE_STOCK_DAILY_QFQ_NINETURN_TABLE}"
                        f"?trade_date={partition.partition_key}"
                    ),
                    row_count=partition.row_count,
                    observed_columns=PROD_CORE_STOCK_DAILY_QFQ_NINETURN_COLUMNS,
                    extra_metadata={
                        "bootstrap_method": "stock_daily_qfq_nineturn_serving_no_price",
                        "bootstrap_event_backfill": True,
                        "event_backfill_scope": EVENT_BACKFILL_SCOPE,
                        "bootstrap_batch_id": batch_id,
                        "event_revision": EVENT_REVISION,
                        "contract": CONTRACT,
                        "migration_revision": PROD_CORE_STOCK_DAILY_QFQ_NINETURN_NO_PRICE_MIGRATION,
                        "deployed_revision": plan.deployed_revision,
                        "business_content_hash": partition.business_content_hash,
                        "source_gold_file_sha256": partition.source_file_sha256,
                        "source_gold_event_revision": GOLD_EVENT_REVISION,
                        "check_events_reported": False,
                        "formula_version": QFQ_NINETURN_VERSION,
                    },
                ),
            ),
        )

    for candidate in check_candidates:
        partition = by_partition[candidate.partition_key]
        materialization = _latest_materialization_records(
            instance,
            asset_key=ASSET_KEY,
            partition_keys=(partition.partition_key,),
        ).get(partition.partition_key)
        if materialization is None or not _serving_materialization_matches(
            materialization,
            partition=partition,
            deployed_revision=plan.deployed_revision,
        ):
            raise StockDailyQfqNineTurnNoPriceServingEventError(
                f"Missing D5 materialization for check: {partition.partition_key}."
            )
        target = AssetCheckEvaluationTargetMaterializationData(
            storage_id=int(materialization.storage_id),
            run_id=str(materialization.run_id),
            timestamp=float(materialization.timestamp),
        )
        source_path = (
            Path(str(plan.report["lake_root"])) / partition.source_relative_path
        )
        report_qfq_nineturn_check_event(
            instance,
            run_id=f"stock-daily-qfq-nineturn-serving-no-price-{batch_id}",
            evaluation=dg.AssetCheckEvaluation(
                asset_key=dg.AssetKey(ASSET_KEY),
                check_name=CHECK_NAME,
                passed=True,
                metadata=build_check_metadata(
                    check_scope=CheckScope.RECONCILIATION,
                    checked_row_count=partition.row_count,
                    file_path=source_path,
                    extra_metadata={
                        "summary": "日线九转无价格 serving 与 Gold 业务字段一致。",
                        "next_action": "无需处理，最近窗口已绑定 D5 新物化事件。",
                        "failed_rule_names": [],
                        "bootstrap_method": "stock_daily_qfq_nineturn_serving_no_price",
                        "bootstrap_event_backfill": True,
                        "event_backfill_scope": EVENT_BACKFILL_SCOPE,
                        "bootstrap_batch_id": batch_id,
                        "event_revision": EVENT_REVISION,
                        "contract": CONTRACT,
                        "migration_revision": PROD_CORE_STOCK_DAILY_QFQ_NINETURN_NO_PRICE_MIGRATION,
                        "deployed_revision": plan.deployed_revision,
                        "business_content_hash": partition.business_content_hash,
                        "source_gold_file_sha256": partition.source_file_sha256,
                        "formula_version": QFQ_NINETURN_VERSION,
                    },
                ),
                blocking=True,
                partition=partition.partition_key,
                target_materialization_data=target,
            ),
        )

    recent_partition_keys = tuple(
        item.partition_key for item in plan.partitions[-CHECK_WINDOW:]
    )
    post_candidates, post_state = _event_candidates(
        instance=instance,
        partitions=plan.partitions,
        recent_partition_keys=recent_partition_keys,
        deployed_revision=plan.deployed_revision,
    )
    if post_candidates:
        raise StockDailyQfqNineTurnNoPriceServingEventError(
            f"D5 post-event audit is not empty: {len(post_candidates)} candidates."
        )
    report_path = output_dir / (
        "stock_daily_qfq_nineturn_no_price_serving_event_apply_"
        f"{plan.plan_fingerprint}.json"
    )
    report = StockDailyQfqNineTurnServingEventApplyReport(
        report_path=report_path,
        plan_fingerprint=plan.plan_fingerprint,
        batch_id=batch_id,
        materialization_event_count=len(materialization_candidates),
        check_event_count=len(check_candidates),
        post_plan_event_count=len(post_candidates),
        current_revision_materialization_count=int(
            post_state["current_revision_materialization_count"]
        ),
        current_revision_check_count=int(post_state["current_revision_check_count"]),
        elapsed_ms=round((time.perf_counter() - started) * 1000, 2),
    )
    _write_json(
        report_path,
        {
            "schema_version": SCHEMA_VERSION,
            "phase": APPLY_PHASE,
            "event_revision": EVENT_REVISION,
            "contract": CONTRACT,
            **report.to_dict(),
        },
    )
    return report


def _build_serving_partitions(
    *,
    lake_root: Path,
    d4_partitions: Sequence[StockDailyQfqNineTurnNoPriceEventPartition],
    duckdb_resource: DuckDBResource,
) -> tuple[tuple[StockDailyQfqNineTurnServingPartition, ...], tuple[str, ...]]:
    partitions: list[StockDailyQfqNineTurnServingPartition] = []
    stop_reasons: list[str] = []
    with duckdb_resource.connect() as connection:
        connection.execute("SET memory_limit='2GB'")
        connection.execute("SET threads=1")
        for item in d4_partitions:
            source_path = lake_root / item.relative_path
            if (
                not source_path.resolve().is_relative_to(lake_root)
                or source_path.is_symlink()
                or not source_path.is_file()
            ):
                stop_reasons.append(f"{item.partition_key}:gold_file_invalid")
                continue
            file_sha256 = _sha256_path(source_path)
            if file_sha256 != item.file_sha256:
                stop_reasons.append(f"{item.partition_key}:gold_file_drift")
                continue
            rows = connection.execute(
                f"""
                SELECT
                  ts_code,
                  trade_date,
                  up_count,
                  down_count,
                  nine_up_turn,
                  nine_down_turn
                FROM {read_parquet(source_path, hive_partitioning=False)}
                ORDER BY ts_code
                """
            ).fetchall()
            if len(rows) != item.row_count:
                stop_reasons.append(f"{item.partition_key}:gold_row_count_drift")
                continue
            business_rows = tuple(
                {
                    "ts_code": row[0],
                    "trade_date": row[1],
                    "up_count": row[2],
                    "down_count": row[3],
                    "nine_up_turn": row[4],
                    "nine_down_turn": row[5],
                    "formula_version": QFQ_NINETURN_VERSION,
                }
                for row in rows
            )
            partitions.append(
                StockDailyQfqNineTurnServingPartition(
                    partition_key=item.partition_key,
                    source_relative_path=item.relative_path,
                    source_file_sha256=file_sha256,
                    row_count=item.row_count,
                    business_content_hash=(
                        stock_daily_qfq_nineturn_business_content_hash(business_rows)
                    ),
                )
            )
    normalized = tuple(sorted(partitions, key=lambda item: item.partition_key))
    if len(normalized) != len(d4_partitions):
        stop_reasons.append("gold_identity_scope_incomplete")
    return normalized, tuple(sorted(set(stop_reasons)))


def _baseline_stop_reasons(
    baseline: ProdCoreStockDailyQfqNineTurnContractSnapshot,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if baseline.migration_versions != (
        PROD_CORE_STOCK_DAILY_QFQ_NINETURN_PREVIOUS_MIGRATION,
    ):
        reasons.append("baseline_migration_revision_mismatch")
    if tuple(row[0] for row in baseline.columns) != (
        PROD_CORE_STOCK_DAILY_QFQ_NINETURN_LEGACY_COLUMNS
    ):
        reasons.append("baseline_column_contract_mismatch")
    if baseline.constraints != PROD_CORE_STOCK_DAILY_QFQ_NINETURN_LEGACY_CONSTRAINTS:
        reasons.append("baseline_constraint_contract_mismatch")
    if baseline.indexes != PROD_CORE_STOCK_DAILY_QFQ_NINETURN_INDEXES:
        reasons.append("baseline_index_contract_mismatch")
    if baseline.row_count <= 0 or baseline.partition_count <= 0:
        reasons.append("baseline_scope_empty")
    return tuple(reasons)


def _post_migration_stop_reasons(
    *,
    baseline: ProdCoreStockDailyQfqNineTurnContractSnapshot,
    post: ProdCoreStockDailyQfqNineTurnContractSnapshot,
    expected_partition_count: int,
    expected_row_count: int,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if post.migration_versions != (
        PROD_CORE_STOCK_DAILY_QFQ_NINETURN_NO_PRICE_MIGRATION,
    ):
        reasons.append("prod_migration_revision_mismatch")
    expected_columns = tuple(row for row in baseline.columns if row[0] != "close_qfq")
    if post.columns != expected_columns or tuple(row[0] for row in post.columns) != (
        PROD_CORE_STOCK_DAILY_QFQ_NINETURN_COLUMNS
    ):
        reasons.append("prod_no_price_column_contract_mismatch")
    if post.constraints != PROD_CORE_STOCK_DAILY_QFQ_NINETURN_CONSTRAINTS:
        reasons.append("prod_constraint_contract_mismatch")
    if post.indexes != baseline.indexes:
        reasons.append("prod_indexes_changed")
    if post.privileges != baseline.privileges:
        reasons.append("prod_privileges_changed")
    if post.table_owner != baseline.table_owner:
        reasons.append("prod_table_owner_changed")
    if post.row_count != baseline.row_count or post.row_count != expected_row_count:
        reasons.append("prod_row_count_changed")
    if (
        post.partition_count != baseline.partition_count
        or post.partition_count != expected_partition_count
    ):
        reasons.append("prod_partition_count_changed")
    if post.first_trade_date != baseline.first_trade_date:
        reasons.append("prod_first_trade_date_changed")
    if post.last_trade_date != baseline.last_trade_date:
        reasons.append("prod_last_trade_date_changed")
    return tuple(reasons)


def _gold_event_stop_reasons(
    *,
    instance: dg.DagsterInstance,
    partitions: Sequence[StockDailyQfqNineTurnServingPartition],
) -> tuple[str, ...]:
    reasons: list[str] = []
    latest = _latest_materialization_records(
        instance,
        asset_key="gold_stock_daily_qfq_nineturn",
        partition_keys=tuple(item.partition_key for item in partitions),
    )
    current = {
        item.partition_key
        for item in partitions
        if item.partition_key in latest
        and _gold_materialization_matches(
            latest[item.partition_key], file_sha256=item.source_file_sha256
        )
    }
    if len(current) != len(partitions):
        reasons.append("gold_d4_materializations_not_current")
    recent = tuple(item.partition_key for item in partitions[-CHECK_WINDOW:])
    checks = _latest_check_records(
        instance,
        asset_key="gold_stock_daily_qfq_nineturn",
        check_name="gold_stock_daily_qfq_nineturn_integrity_check",
        partition_keys=recent,
    )
    for partition_key in recent:
        materialization = latest.get(partition_key)
        check = checks.get(partition_key)
        if (
            materialization is None
            or check is None
            or not _check_matches(
                check,
                materialization_storage_id=int(materialization.storage_id),
                event_revision=GOLD_EVENT_REVISION,
                contract=GOLD_CONTRACT,
            )
        ):
            reasons.append("gold_d4_recent_checks_not_current")
            break
    return tuple(reasons)


def _event_candidates(
    *,
    instance: dg.DagsterInstance,
    partitions: Sequence[StockDailyQfqNineTurnServingPartition],
    recent_partition_keys: Sequence[str],
    deployed_revision: str,
) -> tuple[tuple[StockDailyQfqNineTurnServingEventCandidate, ...], dict[str, object]]:
    latest = _latest_materialization_records(
        instance,
        asset_key=ASSET_KEY,
        partition_keys=tuple(item.partition_key for item in partitions),
    )
    current = {
        item.partition_key: latest[item.partition_key]
        for item in partitions
        if item.partition_key in latest
        and _serving_materialization_matches(
            latest[item.partition_key],
            partition=item,
            deployed_revision=deployed_revision,
        )
    }
    checks = _latest_check_records(
        instance,
        asset_key=ASSET_KEY,
        check_name=CHECK_NAME,
        partition_keys=recent_partition_keys,
    )
    current_checks = {
        partition_key
        for partition_key in recent_partition_keys
        if partition_key in current
        and partition_key in checks
        and _check_matches(
            checks[partition_key],
            materialization_storage_id=int(current[partition_key].storage_id),
            event_revision=EVENT_REVISION,
            contract=CONTRACT,
        )
    }
    candidates = [
        StockDailyQfqNineTurnServingEventCandidate(
            partition_key=item.partition_key,
            event_type="materialization",
        )
        for item in partitions
        if item.partition_key not in current
    ]
    candidates.extend(
        StockDailyQfqNineTurnServingEventCandidate(
            partition_key=partition_key,
            event_type="check",
            check_name=CHECK_NAME,
        )
        for partition_key in recent_partition_keys
        if partition_key not in current_checks
    )
    normalized = tuple(
        sorted(candidates, key=lambda item: (item.partition_key, item.event_type))
    )
    return normalized, {
        "current_revision_materialization_count": len(current),
        "current_revision_check_count": len(current_checks),
        "latest_materialization_storage_id": max(
            (int(record.storage_id) for record in latest.values()), default=None
        ),
        "latest_check_storage_id": max(
            (
                int(record.id)
                for record in checks.values()
                if getattr(record, "id", None) is not None
            ),
            default=None,
        ),
    }


def _latest_materialization_records(
    instance: dg.DagsterInstance,
    *,
    asset_key: str,
    partition_keys: Sequence[str],
) -> dict[str, object]:
    if not partition_keys:
        return {}
    result = instance.fetch_materializations(
        dg.AssetRecordsFilter(
            asset_key=dg.AssetKey(asset_key),
            asset_partitions=list(partition_keys),
        ),
        limit=len(partition_keys),
    )
    records: dict[str, object] = {}
    for record in result.records:
        partition_key = getattr(record, "partition_key", None)
        if partition_key is not None and str(partition_key) not in records:
            records[str(partition_key)] = record
    return records


def _latest_check_records(
    instance: dg.DagsterInstance,
    *,
    asset_key: str,
    check_name: str,
    partition_keys: Sequence[str],
) -> dict[str, object]:
    selected = set(partition_keys)
    records = instance.event_log_storage.get_asset_check_execution_history(
        dg.AssetCheckKey(dg.AssetKey(asset_key), check_name),
        limit=MAX_CHECK_HISTORY,
    )
    latest: dict[str, object] = {}
    for record in records:
        partition_key = getattr(record, "partition", None)
        if partition_key in selected and str(partition_key) not in latest:
            latest[str(partition_key)] = record
    return latest


def _gold_materialization_matches(record: object, *, file_sha256: str) -> bool:
    materialization = getattr(record, "asset_materialization", None)
    metadata = getattr(materialization, "metadata", {})
    return (
        _metadata_value(metadata, "event_revision") == GOLD_EVENT_REVISION
        and _metadata_value(metadata, "contract") == GOLD_CONTRACT
        and _metadata_value(metadata, "formal_file_sha256") == file_sha256
    )


def _serving_materialization_matches(
    record: object,
    *,
    partition: StockDailyQfqNineTurnServingPartition,
    deployed_revision: str,
) -> bool:
    materialization = getattr(record, "asset_materialization", None)
    metadata = getattr(materialization, "metadata", {})
    return (
        _metadata_value(metadata, "event_revision") == EVENT_REVISION
        and _metadata_value(metadata, "contract") == CONTRACT
        and _metadata_value(metadata, "migration_revision")
        == PROD_CORE_STOCK_DAILY_QFQ_NINETURN_NO_PRICE_MIGRATION
        and _metadata_value(metadata, "deployed_revision") == deployed_revision
        and _metadata_value(metadata, "business_content_hash")
        == partition.business_content_hash
        and _metadata_value(metadata, "source_gold_file_sha256")
        == partition.source_file_sha256
    )


def _check_matches(
    record: object,
    *,
    materialization_storage_id: int,
    event_revision: str,
    contract: str,
) -> bool:
    event = getattr(record, "event", None)
    dagster_event = getattr(event, "dagster_event", None) if event else None
    evaluation = getattr(dagster_event, "event_specific_data", None)
    target = getattr(evaluation, "target_materialization_data", None)
    metadata = getattr(evaluation, "metadata", {})
    return (
        getattr(getattr(record, "status", None), "value", None) == "SUCCEEDED"
        and bool(getattr(evaluation, "passed", False))
        and bool(getattr(evaluation, "blocking", False))
        and target is not None
        and int(target.storage_id) == materialization_storage_id
        and _metadata_value(metadata, "event_revision") == event_revision
        and _metadata_value(metadata, "contract") == contract
    )


def _metadata_value(metadata: Mapping[str, object], key: str) -> object | None:
    value = metadata.get(key)
    if value is None:
        value = metadata.get(f"goldenshare/{key}")
    return getattr(value, "value", None) if value is not None else None


def _writer_sensor_states(instance: dg.DagsterInstance) -> dict[str, str]:
    states = {name: "NOT_FOUND" for name in WRITER_SENSOR_NAMES}
    for state in instance.all_instigator_state():
        name = getattr(state, "name", None) or getattr(state, "instigator_name", None)
        if name in states:
            states[str(name)] = str(
                getattr(getattr(state, "status", None), "value", "UNKNOWN")
            )
    return states


def _active_writer_run_counts(instance: dg.DagsterInstance) -> dict[str, int]:
    return {
        job_name: instance.get_runs_count(
            filters=dg.RunsFilter(
                job_name=job_name,
                statuses=list(_IN_FLIGHT_STATUSES),
            )
        )
        for job_name in WRITER_JOB_NAMES
    }


def _load_snapshot_report(
    path: Path,
) -> tuple[dict[str, object], ProdCoreStockDailyQfqNineTurnContractSnapshot]:
    payload = _load_json(path)
    if (
        payload.get("schema_version") != SCHEMA_VERSION
        or payload.get("phase") != SNAPSHOT_PHASE
        or payload.get("read_only") is not True
    ):
        raise StockDailyQfqNineTurnNoPriceServingEventError(
            "Unsupported D5 baseline snapshot."
        )
    snapshot_payload = payload.get("snapshot")
    if not isinstance(snapshot_payload, Mapping):
        raise StockDailyQfqNineTurnNoPriceServingEventError(
            "D5 baseline snapshot payload is missing."
        )
    if _hash_payload(snapshot_payload) != payload.get("snapshot_fingerprint"):
        raise StockDailyQfqNineTurnNoPriceServingEventError(
            "D5 baseline snapshot fingerprint changed."
        )
    return payload, _snapshot_from_dict(snapshot_payload)


def _snapshot_from_dict(
    payload: Mapping[str, object],
) -> ProdCoreStockDailyQfqNineTurnContractSnapshot:
    return ProdCoreStockDailyQfqNineTurnContractSnapshot(
        migration_versions=tuple(str(value) for value in payload["migration_versions"]),
        columns=tuple(tuple(value for value in row) for row in payload["columns"]),
        constraints=tuple(str(value) for value in payload["constraints"]),
        indexes=tuple(str(value) for value in payload["indexes"]),
        privileges=tuple(
            tuple(str(value) for value in row) for row in payload["privileges"]
        ),
        table_owner=str(payload["table_owner"]),
        row_count=int(payload["row_count"]),
        partition_count=int(payload["partition_count"]),
        first_trade_date=(
            str(payload["first_trade_date"])
            if payload.get("first_trade_date") is not None
            else None
        ),
        last_trade_date=(
            str(payload["last_trade_date"])
            if payload.get("last_trade_date") is not None
            else None
        ),
    )


def _hash_payload(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, object]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise StockDailyQfqNineTurnNoPriceServingEventError(
            f"Expected JSON object: {path}."
        )
    return payload


def _load_jsonl(path: Path) -> tuple[dict[str, object], ...]:
    return tuple(
        json.loads(line)
        for line in Path(path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    )


def _write_json(path: Path, payload: Mapping[str, object]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_jsonl(path: Path, rows: Sequence[Mapping[str, object]]) -> None:
    path.write_text(
        "".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows
        ),
        encoding="utf-8",
    )
