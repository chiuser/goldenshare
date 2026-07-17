"""Guarded full-load apply for ``gold_dc_daily_technical`` ClickHouse serving.

The apply path is intentionally separate from the read-only planner.  A data
writer inserts rows into an isolated staging table; an admin connection owns
DDL and the final atomic rename.  No Dagster definition imports this module.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from time import perf_counter
from typing import Any

from orchestrator.defs.bootstrap.dc_daily_technical_clickhouse_bootstrap import (
    DcDailyTechnicalClickHouseBootstrapError,
    _safe_staging_table,
    audit_sample_staging,
    insert_sample_rows,
    iter_gold_clickhouse_rows,
)
from orchestrator.defs.run_contracts.dc_daily_technical_serving import (
    DC_DAILY_TECHNICAL_SERVING_COLUMNS,
    DC_DAILY_TECHNICAL_SERVING_TABLE,
)


_SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9_]+$")


@dataclass(frozen=True, slots=True)
class DcDailyTechnicalClickHouseApplyResult:
    target: str
    staging: str
    backup: str
    plan_fingerprint: str
    inserted_row_count: int
    batch_count: int
    staging_audit: dict[str, object]
    target_audit: dict[str, object]
    switched: bool
    elapsed_ms: int

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "target": self.target,
            "staging": self.staging,
            "backup": self.backup,
            "plan_fingerprint": self.plan_fingerprint,
            "inserted_row_count": self.inserted_row_count,
            "batch_count": self.batch_count,
            "staging_audit": dict(self.staging_audit),
            "target_audit": dict(self.target_audit),
            "switched": self.switched,
            "elapsed_ms": self.elapsed_ms,
            "backup_cleanup": "explicit_admin_action_required",
        }


def validate_apply_request(
    *,
    target: str,
    expected_plan_fingerprint: str,
    actual_plan_fingerprint: str,
    confirm_clickhouse_write: bool,
    confirm_target_empty: bool,
    run_id: str,
) -> None:
    if target not in {"local", "prod", "both"}:
        raise ValueError("target must be one of: local, prod, both")
    if not confirm_clickhouse_write:
        raise PermissionError("--confirm-clickhouse-write is required")
    if not confirm_target_empty:
        raise PermissionError("--confirm-target-empty is required")
    if not expected_plan_fingerprint:
        raise ValueError("expected plan fingerprint is required")
    if expected_plan_fingerprint != actual_plan_fingerprint:
        raise DcDailyTechnicalClickHouseBootstrapError(
            "Bootstrap plan fingerprint mismatch: "
            f"expected={expected_plan_fingerprint}, actual={actual_plan_fingerprint}"
        )
    if not _SAFE_RUN_ID.fullmatch(run_id):
        raise ValueError("run_id must contain only ASCII letters, digits and underscores")


def _database_and_table(table: str) -> tuple[str, str]:
    parts = table.split(".")
    if len(parts) != 2 or not all(parts):
        raise ValueError(f"Expected database.table, got {table!r}")
    return parts[0], parts[1]


def _qualified_staging_table(staging_table: str) -> str:
    database, _ = _database_and_table(DC_DAILY_TECHNICAL_SERVING_TABLE)
    return f"{database}.{_safe_staging_table(staging_table)}"


def _columns(client, table: str) -> tuple[str, ...]:
    return tuple(str(row[0]) for row in client.execute(f"DESCRIBE TABLE {table}"))


def _assert_contract_schema(client, table: str) -> None:
    expected = (*DC_DAILY_TECHNICAL_SERVING_COLUMNS, "updated_at")
    observed = _columns(client, table)
    if observed != expected:
        raise DcDailyTechnicalClickHouseBootstrapError(
            f"ClickHouse schema mismatch for {table}: expected={expected}, observed={observed}"
        )


def _count_table(client, table: str) -> int:
    rows = client.execute(f"SELECT count() FROM {table}")
    return int(rows[0][0]) if rows else 0


def _assert_empty_target(client, table: str) -> None:
    _assert_contract_schema(client, table)
    count = _count_table(client, table)
    if count != 0:
        raise DcDailyTechnicalClickHouseBootstrapError(
            f"Bootstrap target is not empty: table={table}, row_count={count}"
        )


def _prepare_staging(admin_client, staging_table: str) -> str:
    qualified = _qualified_staging_table(staging_table)
    exists = admin_client.execute(f"EXISTS TABLE {qualified}")
    if exists and int(exists[0][0]) == 1:
        _assert_contract_schema(admin_client, qualified)
        if _count_table(admin_client, qualified) != 0:
            raise DcDailyTechnicalClickHouseBootstrapError(
                f"Existing staging table is not empty: {qualified}"
            )
        return qualified
    admin_client.execute(
        f"CREATE TABLE {qualified} AS {DC_DAILY_TECHNICAL_SERVING_TABLE}"
    )
    _assert_contract_schema(admin_client, qualified)
    if _count_table(admin_client, qualified) != 0:
        raise DcDailyTechnicalClickHouseBootstrapError(
            f"New staging table is not empty: {qualified}"
        )
    return qualified


def prepare_apply_target(admin_client, staging_table: str) -> str:
    """Run the admin-only target and staging preflight before opening a writer."""

    target = DC_DAILY_TECHNICAL_SERVING_TABLE
    _assert_empty_target(admin_client, target)
    return _prepare_staging(admin_client, staging_table)


def _audit_target_table(
    client,
    table: str,
    expected_rows_by_date: dict[str, int],
) -> dict[str, object]:
    _assert_contract_schema(client, table)
    rows = client.execute(
        f"""
        SELECT trade_date, count(),
               uniqExact(tuple(ts_code, trade_date, category))
        FROM {table}
        GROUP BY trade_date
        ORDER BY trade_date
        """
    )
    actual = {str(row[0]): int(row[1]) for row in rows}
    unique = {str(row[0]): int(row[2]) for row in rows}
    expected = {str(key): int(value) for key, value in expected_rows_by_date.items()}
    if actual != expected:
        raise DcDailyTechnicalClickHouseBootstrapError(
            f"Final target row count mismatch: expected={expected}, actual={actual}"
        )
    duplicate_dates = [
        trade_date
        for trade_date, count in actual.items()
        if unique[trade_date] != count
    ]
    if duplicate_dates:
        raise DcDailyTechnicalClickHouseBootstrapError(
            "Final target duplicate business keys: " + ",".join(duplicate_dates)
        )
    return {
        "table": table,
        "trade_date_count": len(actual),
        "row_count": sum(actual.values()),
        "unique_key_count": sum(unique.values()),
        "duplicate_trade_dates": duplicate_dates,
    }


def apply_gold_dc_daily_technical(
    *,
    source_connection,
    writer_client,
    admin_client,
    lake_root,
    trade_dates: tuple[str, ...],
    expected_rows_by_date: dict[str, int],
    plan_fingerprint: str,
    expected_plan_fingerprint: str,
    staging_table: str,
    run_id: str,
    confirm_clickhouse_write: bool,
    confirm_target_empty: bool,
    batch_size: int,
    target_name: str = "local",
    prepared_staging_table: str | None = None,
) -> DcDailyTechnicalClickHouseApplyResult:
    """Load staging and atomically switch it into the empty formal target."""

    started = perf_counter()
    validate_apply_request(
        target=target_name,
        expected_plan_fingerprint=expected_plan_fingerprint,
        actual_plan_fingerprint=plan_fingerprint,
        confirm_clickhouse_write=confirm_clickhouse_write,
        confirm_target_empty=confirm_target_empty,
        run_id=run_id,
    )
    target = DC_DAILY_TECHNICAL_SERVING_TABLE
    database, table_name = _database_and_table(target)
    backup = f"{database}.{table_name}__prebootstrap_{run_id}"
    qualified_staging = (
        prepare_apply_target(admin_client, staging_table)
        if prepared_staging_table is None
        else prepared_staging_table
    )
    if qualified_staging != _qualified_staging_table(staging_table):
        raise DcDailyTechnicalClickHouseBootstrapError(
            "Prepared staging table does not match the requested staging table"
        )

    row_batches = iter_gold_clickhouse_rows(
        connection=source_connection,
        lake_root=lake_root,
        trade_dates=trade_dates,
        batch_size=batch_size,
    )
    insert_result = insert_sample_rows(
        client=writer_client,
        staging_table=staging_table,
        row_batches=row_batches,
    )
    staging_audit = audit_sample_staging(
        client=writer_client,
        staging_table=staging_table,
        expected_rows_by_date=expected_rows_by_date,
    )
    admin_client.execute(
        f"RENAME TABLE {target} TO {backup}, {qualified_staging} TO {target}"
    )
    target_audit = _audit_target_table(
        admin_client,
        target,
        expected_rows_by_date,
    )
    return DcDailyTechnicalClickHouseApplyResult(
        target=target,
        staging=qualified_staging,
        backup=backup,
        plan_fingerprint=plan_fingerprint,
        inserted_row_count=int(insert_result["inserted_row_count"]),
        batch_count=int(insert_result["batch_count"]),
        staging_audit=staging_audit,
        target_audit=target_audit,
        switched=True,
        elapsed_ms=max(0, int((perf_counter() - started) * 1000)),
    )


__all__ = [
    "DcDailyTechnicalClickHouseApplyResult",
    "apply_gold_dc_daily_technical",
    "prepare_apply_target",
    "validate_apply_request",
]
