"""Basic-filtered Silver writers and audits for ETF daily datasets."""

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from time import perf_counter

from orchestrator.defs.assets.etf_basic import audit_etf_basic_silver_snapshot
from orchestrator.defs.duckdb_sql import duckdb_string, read_parquet
from orchestrator.defs.io.etf_daily_raw_writer import (
    FUND_ADJ_RAW_SPEC,
    FUND_DAILY_RAW_SPEC,
    EtfDailyRawSpec,
    audit_etf_daily_raw_relation,
)
from orchestrator.defs.paths import (
    raw_etf_basic_snapshot_path,
    silver_etf_adj_factor_path,
    silver_etf_adj_factor_staging_path,
    silver_etf_basic_snapshot_path,
    silver_etf_daily_path,
    silver_etf_daily_staging_path,
)
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.run_contracts.etf_basic import (
    EtfBasicSilverSnapshotReference,
    classify_etf_basic_requestability,
    compute_etf_requestable_target_hash,
)
from orchestrator.defs.run_contracts.etf_daily import (
    ETF_DAILY_CHANGE_TOLERANCE,
    ETF_DAILY_DIAGNOSTIC_SAMPLE_LIMIT,
    ETF_DAILY_PCT_CHG_TOLERANCE,
    ETF_DAILY_REJECTION_REASON_CODES,
    FUND_ADJ_SILVER_COLUMN_TYPES,
    FUND_DAILY_SILVER_COLUMN_TYPES,
    SILVER_ETF_ADJ_FACTOR_ASSET_KEY,
    SILVER_ETF_DAILY_ASSET_KEY,
    normalize_etf_daily_trade_date,
)


class EtfDailySilverValidationError(ValueError):
    """Raised when Raw, Basic, candidate, or an existing Silver target is unsafe."""


@dataclass(frozen=True, slots=True)
class EtfDailySilverSpec:
    asset_key: str
    raw_spec: EtfDailyRawSpec
    silver_column_types: Mapping[str, str]
    target_path_builder: Callable[[Path, str], Path]
    staging_path_builder: Callable[[Path, str, str], Path]
    domain_kind: str

    @property
    def source_columns(self) -> tuple[str, ...]:
        return self.raw_spec.source_columns


FUND_DAILY_SILVER_SPEC = EtfDailySilverSpec(
    asset_key=SILVER_ETF_DAILY_ASSET_KEY,
    raw_spec=FUND_DAILY_RAW_SPEC,
    silver_column_types=FUND_DAILY_SILVER_COLUMN_TYPES,
    target_path_builder=silver_etf_daily_path,
    staging_path_builder=silver_etf_daily_staging_path,
    domain_kind="daily_bar",
)
FUND_ADJ_SILVER_SPEC = EtfDailySilverSpec(
    asset_key=SILVER_ETF_ADJ_FACTOR_ASSET_KEY,
    raw_spec=FUND_ADJ_RAW_SPEC,
    silver_column_types=FUND_ADJ_SILVER_COLUMN_TYPES,
    target_path_builder=silver_etf_adj_factor_path,
    staging_path_builder=silver_etf_adj_factor_staging_path,
    domain_kind="adj_factor",
)
_APPROVED_SILVER_SPECS = (FUND_DAILY_SILVER_SPEC, FUND_ADJ_SILVER_SPEC)


@dataclass(frozen=True, slots=True)
class EtfDailySilverAudit:
    columns: tuple[str, ...]
    column_types: tuple[str, ...]
    row_count: int
    invalid_key_count: int
    duplicate_key_count: int
    invalid_date_count: int
    min_trade_date: str | None
    max_trade_date: str | None
    content_hash: str | None
    failure_samples: tuple[dict[str, object], ...]
    error_codes: tuple[str, ...]

    @property
    def schema_errors(self) -> tuple[str, ...]:
        return tuple(
            code
            for code in self.error_codes
            if code in {"schema_columns", "schema_types", "partition_date"}
        )

    @property
    def key_errors(self) -> tuple[str, ...]:
        return tuple(
            code
            for code in self.error_codes
            if code in {"invalid_key", "duplicate_key"}
        )


@dataclass(frozen=True, slots=True)
class EtfDailySourceFilterAudit:
    checked_row_count: int
    failure_count: int
    failure_samples: tuple[dict[str, object], ...]

    @property
    def error_codes(self) -> tuple[str, ...]:
        return ("source_filter",) if self.failure_count else ()


@dataclass(frozen=True, slots=True)
class EtfDailySourceParityAudit:
    raw_row_count: int
    selected_row_count: int
    rejected_row_count: int
    silver_row_count: int
    reason_counts: Mapping[str, int]
    expected_minus_silver_count: int
    silver_minus_expected_count: int
    failure_samples: tuple[dict[str, object], ...]

    @property
    def error_codes(self) -> tuple[str, ...]:
        errors: list[str] = []
        if self.selected_row_count + self.rejected_row_count != self.raw_row_count:
            errors.append("row_conservation")
        if self.silver_row_count != self.selected_row_count:
            errors.append("selected_row_count")
        if self.expected_minus_silver_count:
            errors.append("expected_rows_missing")
        if self.silver_minus_expected_count:
            errors.append("unexpected_silver_rows")
        return tuple(errors)


@dataclass(frozen=True, slots=True)
class EtfDailyCoverageAudit:
    expected_code_count: int
    raw_matching_code_count: int
    silver_code_count: int
    missing_expected_code_count: int
    raw_extra_code_count: int
    silver_extra_code_count: int
    failure_samples: tuple[dict[str, object], ...]

    @property
    def has_warning(self) -> bool:
        return bool(self.missing_expected_code_count or self.silver_extra_code_count)


@dataclass(frozen=True, slots=True)
class EtfDailyDomainAudit:
    checked_row_count: int
    failed_row_count: int
    failure_counts: Mapping[str, int]
    failure_samples: tuple[dict[str, object], ...]

    @property
    def error_codes(self) -> tuple[str, ...]:
        return tuple(name for name, count in self.failure_counts.items() if count)


@dataclass(frozen=True, slots=True)
class EtfDailySilverWriteResult:
    asset_key: str
    partition_key: str
    raw_path: Path
    target_path: Path
    staging_path: Path
    write_mode: str
    raw_row_count: int
    selected_row_count: int
    rejected_row_count: int
    written_row_count: int
    reason_counts: Mapping[str, int]
    rejection_samples: tuple[dict[str, object], ...]
    basic_reference: EtfBasicSilverSnapshotReference
    content_hash: str
    output_bytes: int
    elapsed_ms: float

    def to_details(self) -> dict[str, object]:
        reference = self.basic_reference
        return {
            "asset_key": self.asset_key,
            "partition_key": self.partition_key,
            "raw_file_path": str(self.raw_path),
            "target_path": str(self.target_path),
            "staging_path": str(self.staging_path),
            "write_mode": self.write_mode,
            "raw_row_count": self.raw_row_count,
            "selected_row_count": self.selected_row_count,
            "rejected_row_count": self.rejected_row_count,
            "written_row_count": self.written_row_count,
            "reject_reason_counts": dict(self.reason_counts),
            "sample_rows": list(self.rejection_samples),
            "basic_reference": reference.model_dump(mode="json"),
            "basic_reference_fingerprint": reference.reference_fingerprint,
            "basic_raw_snapshot_hash": reference.raw_snapshot_hash,
            "basic_silver_content_hash": reference.silver_content_hash,
            "basic_raw_uri": reference.raw_uri,
            "basic_silver_uri": reference.silver_uri,
            "content_hash": self.content_hash,
            "output_bytes": self.output_bytes,
            "elapsed_ms": round(self.elapsed_ms, 3),
        }


def _approved_spec(spec: EtfDailySilverSpec) -> None:
    if not any(spec is approved for approved in _APPROVED_SILVER_SPECS):
        raise ValueError("ETF daily Silver operation requires one frozen dataset spec")


def _relation_select(relation_sql: str) -> str:
    stripped = relation_sql.lstrip().lower()
    return (
        relation_sql
        if stripped.startswith(("select", "with"))
        else f"SELECT * FROM {relation_sql}"
    )


def _quoted_columns(spec: EtfDailySilverSpec, *, alias: str | None = None) -> str:
    prefix = f"{alias}." if alias else ""
    return ", ".join(f'{prefix}"{column}"' for column in spec.source_columns)


def _expected_types(spec: EtfDailySilverSpec) -> tuple[str, ...]:
    return tuple(spec.silver_column_types[column] for column in spec.source_columns)


def _classified_select(
    *,
    raw_relation_sql: str,
    basic_relation_sql: str,
) -> str:
    raw_sql = _relation_select(raw_relation_sql)
    basic_sql = _relation_select(basic_relation_sql)
    return f"""
    SELECT
      raw_rows.*,
      CASE
        WHEN NOT ends_with(raw_rows.ts_code, '.SH')
         AND NOT ends_with(raw_rows.ts_code, '.SZ')
          THEN 'NON_EXCHANGE_SUFFIX'
        WHEN basic_rows.ts_code IS NULL THEN 'BASIC_CODE_ABSENT'
        WHEN basic_rows.exchange IS DISTINCT FROM right(raw_rows.ts_code, 2)
          THEN 'EXCHANGE_MISMATCH'
        WHEN basic_rows.list_status IS DISTINCT FROM 'L' THEN 'STATUS_NOT_LISTED'
        WHEN basic_rows.list_date IS NULL THEN 'LIST_DATE_NULL'
        WHEN basic_rows.list_date > strptime(raw_rows.trade_date, '%Y%m%d')::DATE
          THEN 'LIST_DATE_AFTER_TRADE_DATE'
        ELSE NULL
      END AS rejection_reason
    FROM ({raw_sql}) raw_rows
    LEFT JOIN ({basic_sql}) basic_rows USING (ts_code)
    """


def _silver_projection(
    *,
    classified_sql: str,
    spec: EtfDailySilverSpec,
) -> str:
    trailing_columns = ", ".join(
        f'classified."{column}"' for column in spec.source_columns[2:]
    )
    return f"""
    SELECT
      classified.ts_code,
      strptime(classified.trade_date, '%Y%m%d')::DATE AS trade_date,
      {trailing_columns}
    FROM ({classified_sql}) classified
    WHERE classified.rejection_reason IS NULL
    ORDER BY classified.ts_code, classified.trade_date
    """


def _canonical_content_hash(
    connection,
    *,
    select_sql: str,
    spec: EtfDailySilverSpec,
) -> str:
    struct_fields = ", ".join(
        f'{column} := "{column}"' for column in spec.source_columns
    )
    value = connection.execute(
        f"""
        SELECT sha256(
          coalesce(
            string_agg(
              to_json(struct_pack({struct_fields})),
              '\n' ORDER BY ts_code, trade_date
            ),
            ''
          )
        )
        FROM ({select_sql}) relation_rows
        """
    ).fetchone()[0]
    return str(value)


def validate_etf_daily_basic_reference(
    *,
    lake_root_path: Path,
    duckdb_resource: DuckDBResource,
    basic_reference: EtfBasicSilverSnapshotReference,
) -> EtfBasicSilverSnapshotReference:
    """Revalidate the exact content-addressed Basic pair used by Silver."""

    try:
        reference = basic_reference.validate_contract()
        raw_path = Path(reference.raw_uri)
        silver_path = Path(reference.silver_uri)
        if raw_path != raw_etf_basic_snapshot_path(
            lake_root_path,
            reference.raw_snapshot_hash,
        ) or silver_path != silver_etf_basic_snapshot_path(
            lake_root_path,
            reference.raw_snapshot_hash,
        ):
            raise EtfDailySilverValidationError(
                "ETF Basic reference is not bound to the formal content-addressed paths"
            )
        audit = audit_etf_basic_silver_snapshot(
            path=silver_path,
            duckdb_resource=duckdb_resource,
            raw_path=raw_path,
            expected_raw_snapshot_hash=reference.raw_snapshot_hash,
            expected_silver_content_hash=reference.silver_content_hash,
        )
    except EtfDailySilverValidationError:
        raise
    except Exception as error:
        raise EtfDailySilverValidationError(
            "ETF Basic reference could not be validated: "
            f"error_type={type(error).__name__}"
        ) from error
    if not audit.passed:
        raise EtfDailySilverValidationError(
            "ETF Basic reference content failed validation: "
            f"source_filter_failures={audit.source_filter_failures!r}, "
            f"key_domain_failures={audit.key_domain_failures!r}, "
            f"content_hash_failures={audit.content_hash_failures!r}"
        )
    eligibility_as_of = date.fromisoformat(reference.eligibility_as_of)
    requestable_rows = tuple(
        row
        for row in audit.rows
        if classify_etf_basic_requestability(
            row,
            eligibility_as_of=eligibility_as_of,
        )
        is None
    )
    if (
        len(requestable_rows) != reference.requestable_code_count
        or compute_etf_requestable_target_hash(requestable_rows)
        != reference.requestable_code_hash
    ):
        raise EtfDailySilverValidationError(
            "ETF Basic requestable count/hash differs from the frozen reference"
        )
    return reference


def audit_etf_daily_silver_relation(
    connection,
    *,
    relation_sql: str,
    spec: EtfDailySilverSpec,
    partition_key: str,
) -> EtfDailySilverAudit:
    """Audit one Silver relation without reimplementing source selection."""

    _approved_spec(spec)
    normalized_partition = normalize_etf_daily_trade_date(partition_key)
    select_sql = _relation_select(relation_sql)
    description = connection.execute(f"DESCRIBE {select_sql}").fetchall()
    columns = tuple(str(row[0]) for row in description)
    column_types = tuple(str(row[1]).upper() for row in description)
    row_count = int(
        connection.execute(
            f"SELECT count(*) FROM ({select_sql}) relation_rows"
        ).fetchone()[0]
        or 0
    )
    errors: list[str] = []
    if columns != spec.source_columns:
        errors.append("schema_columns")
    if column_types != _expected_types(spec):
        errors.append("schema_types")
    if errors:
        return EtfDailySilverAudit(
            columns=columns,
            column_types=column_types,
            row_count=row_count,
            invalid_key_count=row_count,
            duplicate_key_count=0,
            invalid_date_count=row_count,
            min_trade_date=None,
            max_trade_date=None,
            content_hash=None,
            failure_samples=(),
            error_codes=tuple(errors),
        )
    counts = connection.execute(
        f"""
        SELECT
          count(*) FILTER (
            WHERE ts_code IS NULL OR trim(ts_code) = '' OR trade_date IS NULL
          ),
          count(*) FILTER (WHERE trade_date != CAST(? AS DATE)),
          min(trade_date),
          max(trade_date)
        FROM ({select_sql}) relation_rows
        """,
        [normalized_partition],
    ).fetchone()
    duplicate_key_count = int(
        connection.execute(
            f"""
            SELECT coalesce(sum(key_count - 1), 0)
            FROM (
              SELECT count(*) AS key_count
              FROM ({select_sql}) relation_rows
              GROUP BY ts_code, trade_date
              HAVING count(*) > 1
            ) duplicate_keys
            """
        ).fetchone()[0]
        or 0
    )
    invalid_key_count = int(counts[0] or 0)
    invalid_date_count = int(counts[1] or 0)
    if invalid_key_count:
        errors.append("invalid_key")
    if duplicate_key_count:
        errors.append("duplicate_key")
    if invalid_date_count:
        errors.append("partition_date")
    sample_rows = connection.execute(
        f"""
        SELECT ts_code, trade_date
        FROM ({select_sql}) relation_rows
        WHERE ts_code IS NULL OR trim(ts_code) = '' OR trade_date IS NULL
           OR trade_date != CAST(? AS DATE)
        ORDER BY ts_code NULLS FIRST, trade_date NULLS FIRST
        LIMIT ?
        """,
        [normalized_partition, ETF_DAILY_DIAGNOSTIC_SAMPLE_LIMIT],
    ).fetchall()
    return EtfDailySilverAudit(
        columns=columns,
        column_types=column_types,
        row_count=row_count,
        invalid_key_count=invalid_key_count,
        duplicate_key_count=duplicate_key_count,
        invalid_date_count=invalid_date_count,
        min_trade_date=str(counts[2]) if counts[2] is not None else None,
        max_trade_date=str(counts[3]) if counts[3] is not None else None,
        content_hash=_canonical_content_hash(
            connection,
            select_sql=select_sql,
            spec=spec,
        ),
        failure_samples=tuple(
            {"ts_code": row[0], "trade_date": str(row[1]) if row[1] else None}
            for row in sample_rows
        ),
        error_codes=tuple(errors),
    )


def audit_etf_daily_source_filter(
    connection,
    *,
    silver_relation_sql: str,
    basic_relation_sql: str,
) -> EtfDailySourceFilterAudit:
    """Prove every Silver row is requestable under the frozen Basic snapshot."""

    silver_sql = _relation_select(silver_relation_sql)
    basic_sql = _relation_select(basic_relation_sql)
    invalid_sql = f"""
    SELECT
      silver_rows.ts_code,
      silver_rows.trade_date,
      CASE
        WHEN NOT ends_with(silver_rows.ts_code, '.SH')
         AND NOT ends_with(silver_rows.ts_code, '.SZ')
          THEN 'NON_EXCHANGE_SUFFIX'
        WHEN basic_rows.ts_code IS NULL THEN 'BASIC_CODE_ABSENT'
        WHEN basic_rows.exchange IS DISTINCT FROM right(silver_rows.ts_code, 2)
          THEN 'EXCHANGE_MISMATCH'
        WHEN basic_rows.list_status IS DISTINCT FROM 'L' THEN 'STATUS_NOT_LISTED'
        WHEN basic_rows.list_date IS NULL THEN 'LIST_DATE_NULL'
        WHEN basic_rows.list_date > silver_rows.trade_date
          THEN 'LIST_DATE_AFTER_TRADE_DATE'
        ELSE NULL
      END AS rejection_reason
    FROM ({silver_sql}) silver_rows
    LEFT JOIN ({basic_sql}) basic_rows USING (ts_code)
    """
    checked_row_count = int(
        connection.execute(
            f"SELECT count(*) FROM ({silver_sql}) rows"
        ).fetchone()[0]
        or 0
    )
    failure_count = int(
        connection.execute(
            f"SELECT count(*) FROM ({invalid_sql}) rows "
            "WHERE rejection_reason IS NOT NULL"
        ).fetchone()[0]
        or 0
    )
    samples = connection.execute(
        f"""
        SELECT ts_code, trade_date, rejection_reason
        FROM ({invalid_sql}) rows
        WHERE rejection_reason IS NOT NULL
        ORDER BY ts_code, trade_date
        LIMIT ?
        """,
        [ETF_DAILY_DIAGNOSTIC_SAMPLE_LIMIT],
    ).fetchall()
    return EtfDailySourceFilterAudit(
        checked_row_count=checked_row_count,
        failure_count=failure_count,
        failure_samples=tuple(
            {
                "ts_code": row[0],
                "trade_date": str(row[1]),
                "reason_code": row[2],
            }
            for row in samples
        ),
    )


def audit_etf_daily_source_parity(
    connection,
    *,
    raw_relation_sql: str,
    silver_relation_sql: str,
    basic_relation_sql: str,
    spec: EtfDailySilverSpec,
) -> EtfDailySourceParityAudit:
    """Reconcile Silver bidirectionally against Raw plus frozen Basic."""

    _approved_spec(spec)
    classified_sql = _classified_select(
        raw_relation_sql=raw_relation_sql,
        basic_relation_sql=basic_relation_sql,
    )
    expected_sql = _silver_projection(classified_sql=classified_sql, spec=spec)
    silver_sql = _relation_select(silver_relation_sql)
    counts = connection.execute(
        f"""
        SELECT
          count(*),
          count(*) FILTER (WHERE rejection_reason IS NULL),
          count(*) FILTER (WHERE rejection_reason IS NOT NULL)
        FROM ({classified_sql}) rows
        """
    ).fetchone()
    silver_row_count = int(
        connection.execute(
            f"SELECT count(*) FROM ({silver_sql}) rows"
        ).fetchone()[0]
        or 0
    )
    reason_rows = connection.execute(
        f"""
        SELECT rejection_reason, count(*)
        FROM ({classified_sql}) rows
        WHERE rejection_reason IS NOT NULL
        GROUP BY rejection_reason
        """
    ).fetchall()
    reason_counts = {
        reason: next(
            (int(count) for observed, count in reason_rows if observed == reason),
            0,
        )
        for reason in ETF_DAILY_REJECTION_REASON_CODES
    }
    columns_sql = _quoted_columns(spec)
    difference_counts = connection.execute(
        f"""
        SELECT
          (SELECT count(*) FROM (
            SELECT {columns_sql} FROM ({expected_sql}) expected_rows
            EXCEPT ALL
            SELECT {columns_sql} FROM ({silver_sql}) silver_rows
          ) rows),
          (SELECT count(*) FROM (
            SELECT {columns_sql} FROM ({silver_sql}) silver_rows
            EXCEPT ALL
            SELECT {columns_sql} FROM ({expected_sql}) expected_rows
          ) rows)
        """
    ).fetchone()
    sample_rows = connection.execute(
        f"""
        SELECT direction, ts_code, trade_date FROM (
          SELECT 'EXPECTED_MISSING' AS direction, ts_code, trade_date
          FROM (
            SELECT {columns_sql} FROM ({expected_sql}) expected_rows
            EXCEPT ALL
            SELECT {columns_sql} FROM ({silver_sql}) silver_rows
          ) rows
          UNION ALL
          SELECT 'SILVER_EXTRA' AS direction, ts_code, trade_date
          FROM (
            SELECT {columns_sql} FROM ({silver_sql}) silver_rows
            EXCEPT ALL
            SELECT {columns_sql} FROM ({expected_sql}) expected_rows
          ) rows
        ) differences
        ORDER BY direction, ts_code, trade_date
        LIMIT ?
        """,
        [ETF_DAILY_DIAGNOSTIC_SAMPLE_LIMIT],
    ).fetchall()
    return EtfDailySourceParityAudit(
        raw_row_count=int(counts[0] or 0),
        selected_row_count=int(counts[1] or 0),
        rejected_row_count=int(counts[2] or 0),
        silver_row_count=silver_row_count,
        reason_counts=reason_counts,
        expected_minus_silver_count=int(difference_counts[0] or 0),
        silver_minus_expected_count=int(difference_counts[1] or 0),
        failure_samples=tuple(
            {
                "direction": row[0],
                "ts_code": row[1],
                "trade_date": str(row[2]),
            }
            for row in sample_rows
        ),
    )


def audit_etf_daily_basic_coverage(
    connection,
    *,
    raw_relation_sql: str,
    silver_relation_sql: str,
    basic_relation_sql: str,
    partition_key: str,
) -> EtfDailyCoverageAudit:
    """Compare expected Basic codes with Raw and Silver without blocking writes."""

    trade_date = normalize_etf_daily_trade_date(partition_key)
    raw_sql = _relation_select(raw_relation_sql)
    silver_sql = _relation_select(silver_relation_sql)
    basic_sql = _relation_select(basic_relation_sql)
    expected_sql = f"""
    SELECT ts_code
    FROM ({basic_sql}) basic_rows
    WHERE (ends_with(ts_code, '.SH') OR ends_with(ts_code, '.SZ'))
      AND exchange = right(ts_code, 2)
      AND list_status = 'L'
      AND list_date IS NOT NULL
      AND list_date <= CAST({duckdb_string(trade_date)} AS DATE)
    """
    raw_codes_sql = f"SELECT DISTINCT ts_code FROM ({raw_sql}) rows"
    silver_codes_sql = f"SELECT DISTINCT ts_code FROM ({silver_sql}) rows"
    counts = connection.execute(
        f"""
        SELECT
          (SELECT count(*) FROM ({expected_sql}) rows),
          (SELECT count(*) FROM (
            SELECT ts_code FROM ({expected_sql})
            INTERSECT SELECT ts_code FROM ({raw_codes_sql})
          ) rows),
          (SELECT count(*) FROM ({silver_codes_sql}) rows),
          (SELECT count(*) FROM (
            SELECT ts_code FROM ({expected_sql})
            EXCEPT SELECT ts_code FROM ({silver_codes_sql})
          ) rows),
          (SELECT count(*) FROM (
            SELECT ts_code FROM ({raw_codes_sql})
            EXCEPT SELECT ts_code FROM ({expected_sql})
          ) rows),
          (SELECT count(*) FROM (
            SELECT ts_code FROM ({silver_codes_sql})
            EXCEPT SELECT ts_code FROM ({expected_sql})
          ) rows)
        """
    ).fetchone()
    samples = connection.execute(
        f"""
        SELECT reason_code, ts_code FROM (
          SELECT 'MISSING_EXPECTED_CODE' AS reason_code, ts_code
          FROM (
            SELECT ts_code FROM ({expected_sql})
            EXCEPT SELECT ts_code FROM ({silver_codes_sql})
          ) rows
          UNION ALL
          SELECT 'RAW_EXTRA_CODE' AS reason_code, ts_code
          FROM (
            SELECT ts_code FROM ({raw_codes_sql})
            EXCEPT SELECT ts_code FROM ({expected_sql})
          ) rows
          UNION ALL
          SELECT 'SILVER_EXTRA_CODE' AS reason_code, ts_code
          FROM (
            SELECT ts_code FROM ({silver_codes_sql})
            EXCEPT SELECT ts_code FROM ({expected_sql})
          ) rows
        ) differences
        ORDER BY reason_code, ts_code
        LIMIT ?
        """,
        [ETF_DAILY_DIAGNOSTIC_SAMPLE_LIMIT],
    ).fetchall()
    return EtfDailyCoverageAudit(
        expected_code_count=int(counts[0] or 0),
        raw_matching_code_count=int(counts[1] or 0),
        silver_code_count=int(counts[2] or 0),
        missing_expected_code_count=int(counts[3] or 0),
        raw_extra_code_count=int(counts[4] or 0),
        silver_extra_code_count=int(counts[5] or 0),
        failure_samples=tuple(
            {"reason_code": row[0], "ts_code": row[1]} for row in samples
        ),
    )


def audit_etf_daily_domain(
    connection,
    *,
    silver_relation_sql: str,
    spec: EtfDailySilverSpec,
) -> EtfDailyDomainAudit:
    """Aggregate the exact post-write value rules without repairing values."""

    _approved_spec(spec)
    silver_sql = _relation_select(silver_relation_sql)
    if spec.domain_kind == "daily_bar":
        predicates = {
            "null_or_nonfinite_price_count": """
                pre_close IS NULL OR NOT isfinite(pre_close)
                OR open IS NULL OR NOT isfinite(open)
                OR high IS NULL OR NOT isfinite(high)
                OR low IS NULL OR NOT isfinite(low)
                OR close IS NULL OR NOT isfinite(close)
            """,
            "non_positive_price_count": """
                (pre_close IS NOT NULL AND isfinite(pre_close) AND pre_close <= 0)
                OR (open IS NOT NULL AND isfinite(open) AND open <= 0)
                OR (high IS NOT NULL AND isfinite(high) AND high <= 0)
                OR (low IS NOT NULL AND isfinite(low) AND low <= 0)
                OR (close IS NOT NULL AND isfinite(close) AND close <= 0)
            """,
            "ohlc_relation_failure_count": """
                open IS NOT NULL AND isfinite(open)
                AND high IS NOT NULL AND isfinite(high)
                AND low IS NOT NULL AND isfinite(low)
                AND close IS NOT NULL AND isfinite(close)
                AND (high < greatest(open, close, low)
                     OR low > least(open, close, high))
            """,
            "null_or_nonfinite_volume_count": """
                vol IS NULL OR NOT isfinite(vol)
                OR amount IS NULL OR NOT isfinite(amount)
            """,
            "negative_volume_count": """
                (vol IS NOT NULL AND isfinite(vol) AND vol < 0)
                OR (amount IS NOT NULL AND isfinite(amount) AND amount < 0)
            """,
            "change_formula_failure_count": f"""
                change IS NULL OR NOT isfinite(change)
                OR (
                  pre_close IS NOT NULL AND isfinite(pre_close) AND pre_close > 0
                  AND close IS NOT NULL AND isfinite(close)
                  AND abs(change - (close - pre_close)) > {ETF_DAILY_CHANGE_TOLERANCE!r}
                )
            """,
            "pct_chg_formula_failure_count": f"""
                pct_chg IS NULL OR NOT isfinite(pct_chg)
                OR (
                  pre_close IS NOT NULL AND isfinite(pre_close) AND pre_close > 0
                  AND close IS NOT NULL AND isfinite(close)
                  AND abs(pct_chg - (close - pre_close) / pre_close * 100)
                    > {ETF_DAILY_PCT_CHG_TOLERANCE!r}
                )
            """,
        }
    else:
        predicates = {
            "adj_factor_null_count": "adj_factor IS NULL",
            "adj_factor_nonfinite_count": (
                "adj_factor IS NOT NULL AND NOT isfinite(adj_factor)"
            ),
            "adj_factor_non_positive_count": (
                "adj_factor IS NOT NULL AND isfinite(adj_factor) AND adj_factor <= 0"
            ),
            "discount_rate_nonfinite_count": (
                "discount_rate IS NOT NULL AND NOT isfinite(discount_rate)"
            ),
        }
    count_columns = ",\n".join(
        f"count(*) FILTER (WHERE {predicate})"
        for predicate in predicates.values()
    )
    any_failure_predicate = " OR ".join(
        f"({predicate})" for predicate in predicates.values()
    )
    counts = connection.execute(
        f"SELECT count(*), {count_columns}, "
        f"count(*) FILTER (WHERE {any_failure_predicate}) "
        f"FROM ({silver_sql}) rows"
    ).fetchone()
    failure_counts = {
        name: int(value or 0)
        for name, value in zip(predicates, counts[1:-1], strict=True)
    }
    sample_selects = " UNION ALL ".join(
        f"SELECT {duckdb_string(name)} AS reason_code, ts_code, trade_date "
        f"FROM ({silver_sql}) rows WHERE {predicate}"
        for name, predicate in predicates.items()
    )
    samples = connection.execute(
        f"SELECT reason_code, ts_code, trade_date FROM ({sample_selects}) failures "
        "ORDER BY reason_code, ts_code, trade_date LIMIT ?",
        [ETF_DAILY_DIAGNOSTIC_SAMPLE_LIMIT],
    ).fetchall()
    return EtfDailyDomainAudit(
        checked_row_count=int(counts[0] or 0),
        failed_row_count=int(counts[-1] or 0),
        failure_counts=failure_counts,
        failure_samples=tuple(
            {
                "reason_code": row[0],
                "ts_code": row[1],
                "trade_date": str(row[2]),
            }
            for row in samples
        ),
    )


def _difference_count(
    connection,
    *,
    left_sql: str,
    right_sql: str,
    spec: EtfDailySilverSpec,
) -> int:
    columns_sql = _quoted_columns(spec)
    return int(
        connection.execute(
            f"""
            SELECT count(*) FROM (
              SELECT {columns_sql} FROM ({_relation_select(left_sql)}) left_rows
              EXCEPT ALL
              SELECT {columns_sql} FROM ({_relation_select(right_sql)}) right_rows
            ) rows
            """
        ).fetchone()[0]
        or 0
    )


def _relations_are_equivalent(
    connection,
    *,
    candidate_sql: str,
    existing_sql: str,
    candidate_audit: EtfDailySilverAudit,
    existing_audit: EtfDailySilverAudit,
    spec: EtfDailySilverSpec,
) -> bool:
    if existing_audit.error_codes:
        return False
    if candidate_audit.row_count != existing_audit.row_count:
        return False
    if candidate_audit.content_hash != existing_audit.content_hash:
        return False
    return not _difference_count(
        connection,
        left_sql=candidate_sql,
        right_sql=existing_sql,
        spec=spec,
    ) and not _difference_count(
        connection,
        left_sql=existing_sql,
        right_sql=candidate_sql,
        spec=spec,
    )


def _require_preflight_roots(lake_root_path: Path, staging_root_path: Path) -> None:
    for label, path in (("Lake", lake_root_path), ("staging", staging_root_path)):
        if not path.is_dir():
            raise EtfDailySilverValidationError(
                f"{label} root must already exist as a directory: {path}"
            )
    if lake_root_path.stat().st_dev != staging_root_path.stat().st_dev:
        raise EtfDailySilverValidationError(
            "Silver staging and target must share one filesystem for atomic os.replace"
        )


def _write_etf_daily_silver_partition(
    *,
    spec: EtfDailySilverSpec,
    lake_root_path: Path,
    staging_root_path: Path,
    duckdb_resource: DuckDBResource,
    partition_key: str,
    operation_id: str,
    basic_reference: EtfBasicSilverSnapshotReference,
) -> EtfDailySilverWriteResult:
    _approved_spec(spec)
    started_at = perf_counter()
    normalized_partition = normalize_etf_daily_trade_date(partition_key)
    _require_preflight_roots(lake_root_path, staging_root_path)
    reference = validate_etf_daily_basic_reference(
        lake_root_path=lake_root_path,
        duckdb_resource=duckdb_resource,
        basic_reference=basic_reference,
    )
    raw_path = spec.raw_spec.target_path_builder(
        lake_root_path,
        normalized_partition,
    )
    target_path = spec.target_path_builder(lake_root_path, normalized_partition)
    staging_path = spec.staging_path_builder(
        staging_root_path,
        operation_id,
        normalized_partition,
    )
    if not raw_path.is_file():
        raise EtfDailySilverValidationError(f"ETF daily Raw file is missing: {raw_path}")
    if staging_path.exists():
        raise EtfDailySilverValidationError(
            f"operation-scoped Silver staging file already exists: {staging_path}"
        )
    target_existed_at_start = target_path.exists()
    target_path.parent.mkdir(parents=True, exist_ok=True)
    staging_path.parent.mkdir(parents=True, exist_ok=True)
    write_mode = ""
    candidate_audit: EtfDailySilverAudit | None = None
    parity: EtfDailySourceParityAudit | None = None
    rejection_samples: tuple[dict[str, object], ...] = ()
    try:
        with duckdb_resource.connect() as connection:
            raw_sql = read_parquet(raw_path, hive_partitioning=False)
            basic_sql = read_parquet(Path(reference.silver_uri), hive_partitioning=False)
            raw_audit = audit_etf_daily_raw_relation(
                connection,
                relation_sql=raw_sql,
                spec=spec.raw_spec,
                partition_key=normalized_partition,
            )
            if raw_audit.error_codes:
                raise EtfDailySilverValidationError(
                    "ETF daily Raw file failed the admission contract: "
                    f"errors={raw_audit.error_codes!r}, path={raw_path}"
                )
            classified_sql = _classified_select(
                raw_relation_sql=raw_sql,
                basic_relation_sql=basic_sql,
            )
            selected_sql = _silver_projection(classified_sql=classified_sql, spec=spec)
            connection.execute(
                f"COPY ({selected_sql}) TO {duckdb_string(staging_path)} "
                "(FORMAT PARQUET, COMPRESSION ZSTD)"
            )
            candidate_sql = read_parquet(staging_path, hive_partitioning=False)
            candidate_audit = audit_etf_daily_silver_relation(
                connection,
                relation_sql=candidate_sql,
                spec=spec,
                partition_key=normalized_partition,
            )
            parity = audit_etf_daily_source_parity(
                connection,
                raw_relation_sql=raw_sql,
                silver_relation_sql=candidate_sql,
                basic_relation_sql=basic_sql,
                spec=spec,
            )
            if candidate_audit.error_codes:
                raise EtfDailySilverValidationError(
                    "Silver candidate failed contract validation: "
                    f"errors={candidate_audit.error_codes!r}"
                )
            if parity.error_codes:
                raise EtfDailySilverValidationError(
                    "Silver candidate failed Raw and Basic reconciliation: "
                    f"errors={parity.error_codes!r}, samples={parity.failure_samples!r}"
                )
            rejection_rows = connection.execute(
                f"""
                SELECT rejection_reason, ts_code, trade_date
                FROM ({classified_sql}) rows
                WHERE rejection_reason IS NOT NULL
                ORDER BY rejection_reason, ts_code, trade_date
                LIMIT ?
                """,
                [ETF_DAILY_DIAGNOSTIC_SAMPLE_LIMIT],
            ).fetchall()
            rejection_samples = tuple(
                {
                    "reason_code": row[0],
                    "ts_code": row[1],
                    "trade_date": row[2],
                }
                for row in rejection_rows
            )
            if target_existed_at_start:
                try:
                    existing_sql = read_parquet(target_path, hive_partitioning=False)
                    existing_audit = audit_etf_daily_silver_relation(
                        connection,
                        relation_sql=existing_sql,
                        spec=spec,
                        partition_key=normalized_partition,
                    )
                except Exception as error:
                    raise EtfDailySilverValidationError(
                        "existing Silver target is unreadable and cannot be overwritten: "
                        f"path={target_path}, error_type={type(error).__name__}"
                    ) from error
                if not _relations_are_equivalent(
                    connection,
                    candidate_sql=candidate_sql,
                    existing_sql=existing_sql,
                    candidate_audit=candidate_audit,
                    existing_audit=existing_audit,
                    spec=spec,
                ):
                    raise EtfDailySilverValidationError(
                        "existing Silver target conflicts with the frozen Basic result; "
                        f"refusing overwrite: {target_path}"
                    )
                staging_path.unlink()
                write_mode = "reuse_existing"
            else:
                if target_path.exists():
                    raise EtfDailySilverValidationError(
                        "Silver target appeared during candidate creation; refusing overwrite: "
                        f"{target_path}"
                    )
                os.replace(staging_path, target_path)
                write_mode = "write_new"
    except Exception:
        if staging_path.exists():
            staging_path.unlink()
        raise
    if candidate_audit is None or candidate_audit.content_hash is None or parity is None:
        raise AssertionError("ETF daily Silver writer completed without audit evidence")
    return EtfDailySilverWriteResult(
        asset_key=spec.asset_key,
        partition_key=normalized_partition,
        raw_path=raw_path,
        target_path=target_path,
        staging_path=staging_path,
        write_mode=write_mode,
        raw_row_count=parity.raw_row_count,
        selected_row_count=parity.selected_row_count,
        rejected_row_count=parity.rejected_row_count,
        written_row_count=candidate_audit.row_count,
        reason_counts=parity.reason_counts,
        rejection_samples=rejection_samples,
        basic_reference=reference,
        content_hash=candidate_audit.content_hash,
        output_bytes=target_path.stat().st_size,
        elapsed_ms=(perf_counter() - started_at) * 1000,
    )


def write_etf_daily_silver_partition(
    *,
    lake_root_path: Path,
    staging_root_path: Path,
    duckdb_resource: DuckDBResource,
    partition_key: str,
    operation_id: str,
    basic_reference: EtfBasicSilverSnapshotReference,
) -> EtfDailySilverWriteResult:
    return _write_etf_daily_silver_partition(
        spec=FUND_DAILY_SILVER_SPEC,
        lake_root_path=lake_root_path,
        staging_root_path=staging_root_path,
        duckdb_resource=duckdb_resource,
        partition_key=partition_key,
        operation_id=operation_id,
        basic_reference=basic_reference,
    )


def write_etf_adj_factor_silver_partition(
    *,
    lake_root_path: Path,
    staging_root_path: Path,
    duckdb_resource: DuckDBResource,
    partition_key: str,
    operation_id: str,
    basic_reference: EtfBasicSilverSnapshotReference,
) -> EtfDailySilverWriteResult:
    return _write_etf_daily_silver_partition(
        spec=FUND_ADJ_SILVER_SPEC,
        lake_root_path=lake_root_path,
        staging_root_path=staging_root_path,
        duckdb_resource=duckdb_resource,
        partition_key=partition_key,
        operation_id=operation_id,
        basic_reference=basic_reference,
    )


__all__ = [
    "FUND_ADJ_SILVER_SPEC",
    "FUND_DAILY_SILVER_SPEC",
    "EtfDailyCoverageAudit",
    "EtfDailyDomainAudit",
    "EtfDailySilverAudit",
    "EtfDailySilverSpec",
    "EtfDailySilverValidationError",
    "EtfDailySilverWriteResult",
    "EtfDailySourceFilterAudit",
    "EtfDailySourceParityAudit",
    "audit_etf_daily_basic_coverage",
    "audit_etf_daily_domain",
    "audit_etf_daily_silver_relation",
    "audit_etf_daily_source_filter",
    "audit_etf_daily_source_parity",
    "validate_etf_daily_basic_reference",
    "write_etf_adj_factor_silver_partition",
    "write_etf_daily_silver_partition",
]
