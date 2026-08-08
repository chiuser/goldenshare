"""Explicit-write M1 tool for the 000680.SH history supplement.

Importing this module never writes. Every batch entrypoint requires a frozen
green plan, the expected plan hash, and an explicit ``apply=True`` argument.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from orchestrator.defs.assets.index_daily import (
    write_silver_index_daily_partition_from_raw_file,
)
from orchestrator.defs.assets.market_major_indices import (
    create_major_indices_seed_table,
    write_gold_market_major_indices_daily_partition,
)
from orchestrator.defs.bootstrap.index_daily_000680_history_supplement_plan import (
    DEFAULT_STAGING_ROOT,
    MAX_BATCH_DATE_COUNT,
    SUPPLEMENT_NAME,
    TARGET_CODE,
    build_source_audit,
    compute_frozen_plan_hash,
    file_sha256,
    read_prod_source_rows,
)
from orchestrator.defs.duckdb_sql import (
    INDEX_DAILY_RAW_COLUMNS,
    copy_query_to_parquet,
    describe_parquet_query,
    duckdb_string,
    read_parquet,
)
from orchestrator.defs.paths import (
    gold_market_major_indices_daily_path,
    raw_index_daily_path,
    silver_index_daily_path,
)
from orchestrator.defs.resources import DuckDBResource, ProdPostgresResource
from orchestrator.defs.run_contracts.asset_column_schemas import (
    GOLD_MARKET_MAJOR_INDICES_DAILY_SCHEMA,
    RAW_INDEX_DAILY_SCHEMA,
    SILVER_INDEX_DAILY_SCHEMA,
)

FORMAL_LAKE_ROOT = Path("/Volumes/datasource/data_lake")


class IndexDaily000680HistorySupplementApplyError(RuntimeError):
    """Raised before an unsafe supplement write can reach the formal Lake."""


@dataclass(frozen=True, slots=True)
class CandidateAudit:
    layer: str
    partition_key: str
    formal_path: str
    candidate_path: str
    before_row_count: int
    after_row_count: int
    target_row_count: int
    duplicate_key_count: int
    invalid_partition_row_count: int
    before_non_target_fingerprint: str
    after_non_target_fingerprint: str
    target_row_fingerprint: str
    candidate_sha256: str
    observed_columns: tuple[str, ...]
    passed: bool

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class LayerBatchReport:
    layer: str
    plan_hash: str
    selected_dates: tuple[str, ...]
    audits: tuple[CandidateAudit, ...]
    promoted_count: int
    checkpoint_path: str

    @property
    def passed(self) -> bool:
        return len(self.audits) == len(self.selected_dates) and all(
            audit.passed for audit in self.audits
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "layer": self.layer,
            "plan_hash": self.plan_hash,
            "selected_dates": list(self.selected_dates),
            "audits": [value.to_dict() for value in self.audits],
            "promoted_count": self.promoted_count,
            "checkpoint_path": self.checkpoint_path,
            "passed": self.passed,
        }


def load_frozen_plan(
    plan_path: Path,
    *,
    expected_plan_hash: str,
    require_green: bool = True,
) -> Mapping[str, Any]:
    try:
        payload = json.loads(plan_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise IndexDaily000680HistorySupplementApplyError(
            f"Cannot read frozen plan: {plan_path}"
        ) from error
    if not isinstance(payload, Mapping):
        raise IndexDaily000680HistorySupplementApplyError(
            "Frozen supplement plan must be a JSON object."
        )
    observed_hash = str(payload.get("plan_hash") or "")
    if not expected_plan_hash or observed_hash != expected_plan_hash:
        raise IndexDaily000680HistorySupplementApplyError(
            "Expected plan hash does not match the frozen supplement plan."
        )
    try:
        computed_hash = compute_frozen_plan_hash(payload)
    except ValueError as error:
        raise IndexDaily000680HistorySupplementApplyError(
            "Frozen supplement plan hash contract is invalid."
        ) from error
    if computed_hash != observed_hash:
        raise IndexDaily000680HistorySupplementApplyError(
            "Frozen supplement plan content does not match its plan hash."
        )
    if require_green and payload.get("should_stop") is not False:
        raise IndexDaily000680HistorySupplementApplyError(
            "Frozen supplement plan is not green."
        )
    if payload.get("target_code") != TARGET_CODE:
        raise IndexDaily000680HistorySupplementApplyError(
            "Frozen supplement plan target code changed."
        )
    if Path(str(payload.get("lake_root"))).resolve() != FORMAL_LAKE_ROOT:
        raise IndexDaily000680HistorySupplementApplyError(
            "Frozen supplement plan does not target the formal Lake root."
        )
    if Path(str(payload.get("staging_root"))).resolve() != DEFAULT_STAGING_ROOT:
        raise IndexDaily000680HistorySupplementApplyError(
            "Frozen supplement plan does not target the approved staging root."
        )
    return payload


def require_explicit_apply(apply: bool) -> None:
    if not apply:
        raise IndexDaily000680HistorySupplementApplyError(
            "Lake writes require explicit apply=True."
        )


def require_frozen_plan_contract(
    plan: Mapping[str, Any], *, expected_plan_hash: str
) -> None:
    if str(plan.get("plan_hash")) != expected_plan_hash:
        raise IndexDaily000680HistorySupplementApplyError("Plan hash changed.")
    try:
        computed_hash = compute_frozen_plan_hash(plan)
    except ValueError as error:
        raise IndexDaily000680HistorySupplementApplyError(
            "Plan hash contract is invalid."
        ) from error
    if computed_hash != expected_plan_hash:
        raise IndexDaily000680HistorySupplementApplyError(
            "Plan content changed after it was frozen."
        )
    if plan.get("should_stop") is not False:
        raise IndexDaily000680HistorySupplementApplyError(
            "Frozen supplement plan is not green."
        )
    if plan.get("target_code") != TARGET_CODE:
        raise IndexDaily000680HistorySupplementApplyError(
            "Frozen supplement plan target code changed."
        )
    if Path(str(plan.get("lake_root"))).resolve() != FORMAL_LAKE_ROOT:
        raise IndexDaily000680HistorySupplementApplyError(
            "Supplement apply only supports the formal Lake root."
        )
    if Path(str(plan.get("staging_root"))).resolve() != DEFAULT_STAGING_ROOT:
        raise IndexDaily000680HistorySupplementApplyError(
            "Supplement apply only supports the approved staging root."
        )


def _date_from_target_path(value: str) -> str:
    for part in Path(value).parts:
        if part.startswith("trade_date="):
            return part.removeprefix("trade_date=")
    raise IndexDaily000680HistorySupplementApplyError(
        f"Target path has no trade_date partition: {value}"
    )


def _plan_dates(plan: Mapping[str, Any], layer: str) -> tuple[str, ...]:
    targets = plan.get("targets")
    if not isinstance(targets, Mapping):
        raise IndexDaily000680HistorySupplementApplyError(
            "Frozen plan has no targets object."
        )
    values = targets.get(f"{layer}_files")
    if not isinstance(values, list):
        raise IndexDaily000680HistorySupplementApplyError(
            f"Frozen plan has no {layer} target files."
        )
    return tuple(_date_from_target_path(str(value)) for value in values)


def select_batch_dates(
    plan: Mapping[str, Any],
    *,
    layer: str,
    start_date: str | None,
    end_date: str | None,
) -> tuple[str, ...]:
    selected = tuple(
        value
        for value in _plan_dates(plan, layer)
        if (start_date is None or value >= start_date)
        and (end_date is None or value <= end_date)
    )
    if not selected:
        raise IndexDaily000680HistorySupplementApplyError(
            f"No {layer} dates selected from the frozen plan."
        )
    if len(selected) > MAX_BATCH_DATE_COUNT:
        raise IndexDaily000680HistorySupplementApplyError(
            f"A batch may contain at most {MAX_BATCH_DATE_COUNT} dates."
        )
    return selected


def source_staging_path(plan: Mapping[str, Any]) -> Path:
    return (
        Path(str(plan["staging_root"]))
        / SUPPLEMENT_NAME
        / f"run_id={plan['run_id']}"
        / "source"
        / "part-000.parquet"
    )


def candidate_path(plan: Mapping[str, Any], layer: str, partition_key: str) -> Path:
    return (
        Path(str(plan["staging_root"]))
        / SUPPLEMENT_NAME
        / f"run_id={plan['run_id']}"
        / "candidate"
        / layer
        / f"trade_date={partition_key}"
        / "part-000.parquet"
    )


def checkpoint_path(plan: Mapping[str, Any], layer: str) -> Path:
    return (
        Path(str(plan["staging_root"]))
        / SUPPLEMENT_NAME
        / f"run_id={plan['run_id']}"
        / "manifest"
        / f"{layer}-checkpoints.json"
    )


def _parquet_columns(connection: Any, path: Path) -> tuple[str, ...]:
    return tuple(
        str(row[0])
        for row in connection.execute(
            describe_parquet_query(path, hive_partitioning=False)
        ).fetchall()
    )


def _relation_rows(
    connection: Any,
    *,
    path: Path,
    columns: Sequence[str],
    target: bool,
) -> tuple[tuple[object, ...], ...]:
    predicate = "=" if target else "<>"
    rows = connection.execute(
        f"""
        SELECT {', '.join(columns)}
        FROM {read_parquet(path, hive_partitioning=False)}
        WHERE ts_code {predicate} {duckdb_string(TARGET_CODE)}
        ORDER BY ts_code, trade_date
        """
    ).fetchall()
    return tuple(tuple(value) for value in rows)


def _rows_fingerprint(rows: Sequence[Sequence[object]]) -> str:
    return hashlib.sha256(
        json.dumps(
            rows,
            ensure_ascii=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()


def _json_compatible(value: object) -> object:
    """Normalize tuples and other JSON containers before frozen-plan comparison."""
    return json.loads(json.dumps(value, ensure_ascii=True, sort_keys=True))


def audit_candidate(
    connection: Any,
    *,
    layer: str,
    formal_path: Path,
    candidate: Path,
    partition_key: str,
) -> CandidateAudit:
    if not formal_path.is_file():
        raise IndexDaily000680HistorySupplementApplyError(
            f"Formal {layer} file is missing: {formal_path}"
        )
    if not candidate.is_file():
        raise IndexDaily000680HistorySupplementApplyError(
            f"Candidate {layer} file is missing: {candidate}"
        )
    schema = {
        "raw": RAW_INDEX_DAILY_SCHEMA,
        "silver": SILVER_INDEX_DAILY_SCHEMA,
        "gold": GOLD_MARKET_MAJOR_INDICES_DAILY_SCHEMA,
    }[layer]
    expected_columns = tuple(column.name for column in schema)
    observed_columns = _parquet_columns(connection, candidate)
    before_rows = connection.execute(
        f"SELECT count(*) FROM {read_parquet(formal_path, hive_partitioning=False)}"
    ).fetchone()
    after_rows = connection.execute(
        f"SELECT count(*) FROM {read_parquet(candidate, hive_partitioning=False)}"
    ).fetchone()
    date_expression = (
        "strptime(trade_date, '%Y%m%d')" if layer == "raw" else "CAST(trade_date AS DATE)"
    )
    key_columns = "ts_code, trade_date"
    target_row_count = int(
        connection.execute(
            f"SELECT count(*) FROM {read_parquet(candidate, hive_partitioning=False)} "
            f"WHERE ts_code = {duckdb_string(TARGET_CODE)}"
        ).fetchone()[0]
    )
    duplicate_key_count = int(
        connection.execute(
            f"""
            SELECT count(*) FROM (
              SELECT {key_columns}
              FROM {read_parquet(candidate, hive_partitioning=False)}
              GROUP BY {key_columns}
              HAVING count(*) > 1
            ) duplicate_keys
            """
        ).fetchone()[0]
    )
    invalid_partition_row_count = int(
        connection.execute(
            f"""
            SELECT count(*)
            FROM {read_parquet(candidate, hive_partitioning=False)}
            WHERE {date_expression} <> DATE {duckdb_string(partition_key)}
            """
        ).fetchone()[0]
    )
    before_non_target = _rows_fingerprint(
        _relation_rows(
            connection,
            path=formal_path,
            columns=expected_columns,
            target=False,
        )
    )
    after_non_target = _rows_fingerprint(
        _relation_rows(
            connection,
            path=candidate,
            columns=expected_columns,
            target=False,
        )
    )
    target_fingerprint = _rows_fingerprint(
        _relation_rows(
            connection,
            path=candidate,
            columns=expected_columns,
            target=True,
        )
    )
    before_row_count = int(before_rows[0])
    after_row_count = int(after_rows[0])
    before_target_count = int(
        connection.execute(
            f"SELECT count(*) FROM {read_parquet(formal_path, hive_partitioning=False)} "
            f"WHERE ts_code = {duckdb_string(TARGET_CODE)}"
        ).fetchone()[0]
    )
    expected_after_count = before_row_count + (1 if before_target_count == 0 else 0)
    passed = (
        observed_columns == expected_columns
        and target_row_count == 1
        and duplicate_key_count == 0
        and invalid_partition_row_count == 0
        and after_row_count == expected_after_count
        and before_non_target == after_non_target
    )
    return CandidateAudit(
        layer=layer,
        partition_key=partition_key,
        formal_path=str(formal_path),
        candidate_path=str(candidate),
        before_row_count=before_row_count,
        after_row_count=after_row_count,
        target_row_count=target_row_count,
        duplicate_key_count=duplicate_key_count,
        invalid_partition_row_count=invalid_partition_row_count,
        before_non_target_fingerprint=before_non_target,
        after_non_target_fingerprint=after_non_target,
        target_row_fingerprint=target_fingerprint,
        candidate_sha256=file_sha256(candidate),
        observed_columns=observed_columns,
        passed=passed,
    )


def promote_candidate(
    *,
    candidate: Path,
    formal_path: Path,
    expected_sha256: str,
    replace_fn: Callable[[str | Path, str | Path], None] = os.replace,
) -> None:
    if file_sha256(candidate) != expected_sha256:
        raise IndexDaily000680HistorySupplementApplyError(
            f"Candidate hash changed before promotion: {candidate}"
        )
    formal_path.parent.mkdir(parents=True, exist_ok=True)
    incoming = formal_path.with_name(f".{formal_path.name}.incoming")
    if incoming.exists():
        incoming.unlink()
    shutil.copyfile(candidate, incoming)
    try:
        replace_fn(incoming, formal_path)
    except Exception:
        if incoming.exists():
            incoming.unlink()
        raise
    if file_sha256(formal_path) != expected_sha256:
        raise IndexDaily000680HistorySupplementApplyError(
            f"Formal file hash differs after promotion: {formal_path}"
        )


def _write_source_staging(
    *,
    connection: Any,
    rows: Sequence[Sequence[object]],
    target_path: Path,
) -> None:
    column_definitions = ", ".join(
        f"{column.name} {column.type}" for column in RAW_INDEX_DAILY_SCHEMA
    )
    connection.execute(f"CREATE TEMP TABLE supplement_source ({column_definitions})")
    connection.executemany(
        "INSERT INTO supplement_source VALUES (" + ", ".join("?" for _ in INDEX_DAILY_RAW_COLUMNS) + ")",
        rows,
    )
    target_path.parent.mkdir(parents=True, exist_ok=True)
    if target_path.exists():
        target_path.unlink()
    connection.execute(
        copy_query_to_parquet(
            "SELECT "
            + ", ".join(INDEX_DAILY_RAW_COLUMNS)
            + " FROM supplement_source ORDER BY trade_date",
            target_path,
        )
    )


def run_source_staging(
    *,
    plan: Mapping[str, Any],
    expected_plan_hash: str,
    duckdb_resource: DuckDBResource,
    prod_postgres: ProdPostgresResource,
    apply: bool,
) -> Mapping[str, object]:
    require_explicit_apply(apply)
    require_frozen_plan_contract(plan, expected_plan_hash=expected_plan_hash)
    rows, boundary_close, following_pre_close = read_prod_source_rows(prod_postgres)
    expected_dates = tuple(
        _date_from_target_path(value)
        for value in plan["targets"]["raw_files"]
    )
    audit = build_source_audit(
        rows=rows,
        expected_dates=expected_dates,
        boundary_close=boundary_close,
        following_pre_close=following_pre_close,
    )
    source_audit = _json_compatible(audit.to_dict())
    if not audit.passed or source_audit != plan["source_audit"]:
        raise IndexDaily000680HistorySupplementApplyError(
            "Current source audit differs from the frozen green plan."
        )
    target_path = source_staging_path(plan)
    with duckdb_resource.connect() as connection:
        _write_source_staging(connection=connection, rows=rows, target_path=target_path)
    return {
        "plan_hash": expected_plan_hash,
        "source_path": str(target_path),
        "source_sha256": file_sha256(target_path),
        "source_audit": source_audit,
    }


def _build_raw_candidate(
    connection: Any,
    *,
    formal_path: Path,
    source_path: Path,
    candidate: Path,
    partition_key: str,
) -> CandidateAudit:
    if not formal_path.is_file():
        raise IndexDaily000680HistorySupplementApplyError(
            f"Existing Raw partition is required: {formal_path}"
        )
    if not source_path.is_file():
        raise IndexDaily000680HistorySupplementApplyError(
            f"Frozen source staging is missing: {source_path}"
        )
    candidate.parent.mkdir(parents=True, exist_ok=True)
    if candidate.exists():
        candidate.unlink()
    columns = ", ".join(INDEX_DAILY_RAW_COLUMNS)
    source_trade_date = partition_key.replace("-", "")
    connection.execute(
        copy_query_to_parquet(
            f"""
            SELECT {columns}
            FROM (
              SELECT {columns}
              FROM {read_parquet(formal_path, hive_partitioning=False)}
              WHERE ts_code <> {duckdb_string(TARGET_CODE)}
              UNION ALL
              SELECT {columns}
              FROM {read_parquet(source_path, hive_partitioning=False)}
              WHERE ts_code = {duckdb_string(TARGET_CODE)}
                AND trade_date = {duckdb_string(source_trade_date)}
            ) merged
            ORDER BY ts_code
            """,
            candidate,
        )
    )
    audit = audit_candidate(
        connection,
        layer="raw",
        formal_path=formal_path,
        candidate=candidate,
        partition_key=partition_key,
    )
    if not audit.passed:
        raise IndexDaily000680HistorySupplementApplyError(
            f"Raw candidate audit failed for {partition_key}."
        )
    return audit


def _checkpoint(report: LayerBatchReport) -> None:
    path = Path(report.checkpoint_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )


def run_raw_batch(
    *,
    plan: Mapping[str, Any],
    expected_plan_hash: str,
    duckdb_resource: DuckDBResource,
    start_date: str | None,
    end_date: str | None,
    apply: bool,
) -> LayerBatchReport:
    require_explicit_apply(apply)
    require_frozen_plan_contract(plan, expected_plan_hash=expected_plan_hash)
    dates = select_batch_dates(
        plan, layer="raw", start_date=start_date, end_date=end_date
    )
    lake_root = Path(str(plan["lake_root"]))
    source_path = source_staging_path(plan)
    audits: list[CandidateAudit] = []
    with duckdb_resource.connect() as connection:
        for partition_key in dates:
            formal_path = raw_index_daily_path(lake_root, partition_key)
            candidate = candidate_path(plan, "raw", partition_key)
            audit = _build_raw_candidate(
                connection,
                formal_path=formal_path,
                source_path=source_path,
                candidate=candidate,
                partition_key=partition_key,
            )
            promote_candidate(
                candidate=candidate,
                formal_path=formal_path,
                expected_sha256=audit.candidate_sha256,
            )
            audits.append(audit)
            report = LayerBatchReport(
                layer="raw",
                plan_hash=expected_plan_hash,
                selected_dates=dates,
                audits=tuple(audits),
                promoted_count=len(audits),
                checkpoint_path=str(checkpoint_path(plan, "raw")),
            )
            _checkpoint(report)
    return report


def run_silver_batch(
    *,
    plan: Mapping[str, Any],
    expected_plan_hash: str,
    duckdb_resource: DuckDBResource,
    start_date: str | None,
    end_date: str | None,
    apply: bool,
) -> LayerBatchReport:
    require_explicit_apply(apply)
    require_frozen_plan_contract(plan, expected_plan_hash=expected_plan_hash)
    dates = select_batch_dates(
        plan, layer="silver", start_date=start_date, end_date=end_date
    )
    lake_root = Path(str(plan["lake_root"]))
    audits: list[CandidateAudit] = []
    with duckdb_resource.connect() as connection:
        for partition_key in dates:
            raw_path = raw_index_daily_path(lake_root, partition_key)
            formal_path = silver_index_daily_path(lake_root, partition_key)
            candidate = candidate_path(plan, "silver", partition_key)
            write_silver_index_daily_partition_from_raw_file(
                connection,
                raw_path=raw_path,
                target_path=candidate,
                partition_key=partition_key,
            )
            audit = audit_candidate(
                connection,
                layer="silver",
                formal_path=formal_path,
                candidate=candidate,
                partition_key=partition_key,
            )
            if not audit.passed:
                raise IndexDaily000680HistorySupplementApplyError(
                    f"Silver candidate audit failed for {partition_key}."
                )
            promote_candidate(
                candidate=candidate,
                formal_path=formal_path,
                expected_sha256=audit.candidate_sha256,
            )
            audits.append(audit)
            report = LayerBatchReport(
                layer="silver",
                plan_hash=expected_plan_hash,
                selected_dates=dates,
                audits=tuple(audits),
                promoted_count=len(audits),
                checkpoint_path=str(checkpoint_path(plan, "silver")),
            )
            _checkpoint(report)
    return report


def run_gold_batch(
    *,
    plan: Mapping[str, Any],
    expected_plan_hash: str,
    duckdb_resource: DuckDBResource,
    start_date: str | None,
    end_date: str | None,
    apply: bool,
) -> LayerBatchReport:
    require_explicit_apply(apply)
    require_frozen_plan_contract(plan, expected_plan_hash=expected_plan_hash)
    if int(plan["seed"]["current_count"]) != int(plan["seed"]["target_count"]):
        raise IndexDaily000680HistorySupplementApplyError(
            "Gold apply is blocked until the frozen plan observes the released 11-index seed."
        )
    dates = select_batch_dates(
        plan, layer="gold", start_date=start_date, end_date=end_date
    )
    lake_root = Path(str(plan["lake_root"]))
    audits: list[CandidateAudit] = []
    with duckdb_resource.connect() as connection:
        seed_count = create_major_indices_seed_table(connection)
        for partition_key in dates:
            silver_path = silver_index_daily_path(lake_root, partition_key)
            formal_path = gold_market_major_indices_daily_path(
                lake_root, partition_key
            )
            candidate = candidate_path(plan, "gold", partition_key)
            write_gold_market_major_indices_daily_partition(
                connection,
                seed_table_name="major_indices_seed",
                seed_count=seed_count,
                silver_path=silver_path,
                target_path=candidate,
                partition_key=partition_key,
            )
            audit = audit_candidate(
                connection,
                layer="gold",
                formal_path=formal_path,
                candidate=candidate,
                partition_key=partition_key,
            )
            if not audit.passed:
                raise IndexDaily000680HistorySupplementApplyError(
                    f"Gold candidate audit failed for {partition_key}."
                )
            promote_candidate(
                candidate=candidate,
                formal_path=formal_path,
                expected_sha256=audit.candidate_sha256,
            )
            audits.append(audit)
            report = LayerBatchReport(
                layer="gold",
                plan_hash=expected_plan_hash,
                selected_dates=dates,
                audits=tuple(audits),
                promoted_count=len(audits),
                checkpoint_path=str(checkpoint_path(plan, "gold")),
            )
            _checkpoint(report)
    return report


def write_report(report: Mapping[str, object] | LayerBatchReport, output: Path) -> None:
    payload = report.to_dict() if isinstance(report, LayerBatchReport) else dict(report)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
