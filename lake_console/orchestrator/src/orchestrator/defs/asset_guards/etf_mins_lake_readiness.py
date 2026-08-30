"""Shared stable Raw validation semantics for ETF minute lake files."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from orchestrator.defs.run_contracts.asset_column_schemas import RAW_ETF_MINS_SCHEMA
from orchestrator.defs.run_contracts.etf_mins import (
    ETF_MINS_DIAGNOSTIC_SAMPLE_LIMIT,
    asset_freq_for_etf_mins_source_freq,
    normalize_etf_mins_source_freq,
    normalize_etf_mins_trade_date,
)

ETF_MINS_RAW_POLICY_STATE_UNCLASSIFIED = "unclassified"

_SQL_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_RAW_SCHEMA = tuple((column.name, column.type) for column in RAW_ETF_MINS_SCHEMA)


@dataclass(frozen=True, slots=True)
class EtfMinsRawCandidateValidation:
    promotion_allowed: bool
    silver_eligible: bool
    policy_state: str
    stable_blocking_reason_codes: tuple[str, ...]
    source_row_count: int
    candidate_row_count: int
    source_minus_candidate_count: int
    candidate_minus_source_count: int
    distinct_code_count: int
    null_key_count: int
    duplicate_key_count: int
    date_mismatch_count: int
    freq_mismatch_count: int
    exchange_mismatch_count: int
    invalid_ohlc_count: int
    invalid_volume_amount_count: int
    invalid_vwap_count: int
    off_session_time_count: int
    grid_gap_candidate_count: int
    expected_count: int
    present_count: int
    missing_count: int
    known_non_required_present_count: int
    retained_legacy_count: int
    unexplained_new_count: int
    missing_samples: tuple[str, ...]
    known_non_required_samples: tuple[str, ...]
    retained_legacy_samples: tuple[str, ...]
    unexplained_new_samples: tuple[str, ...]


def evaluate_etf_mins_raw_candidate(
    *,
    connection: Any,
    source_relation: str,
    candidate_relation: str,
    basic_all_relation: str,
    requestable_targets_relation: str,
    trade_date: str,
    source_freq: str,
    existing_target_relation: str | None = None,
) -> EtfMinsRawCandidateValidation:
    """Evaluate transport, stable Raw gates, set classes, and N3 diagnostics."""

    normalized_trade_date = normalize_etf_mins_trade_date(trade_date)
    normalized_source_freq = normalize_etf_mins_source_freq(source_freq)
    source_name = _normalize_relation_name(source_relation)
    candidate_name = _normalize_relation_name(candidate_relation)
    basic_name = _normalize_relation_name(basic_all_relation)
    requestable_name = _normalize_relation_name(requestable_targets_relation)
    existing_name = (
        None
        if existing_target_relation is None
        else _normalize_relation_name(existing_target_relation)
    )

    _assert_exact_raw_schema(connection, source_name)
    _assert_exact_raw_schema(connection, candidate_name)
    _assert_relation_columns(connection, basic_name, required=("ts_code",))
    _assert_relation_columns(
        connection,
        requestable_name,
        required=("ts_code", "list_date"),
    )
    if existing_name is not None:
        _assert_relation_columns(connection, existing_name, required=("ts_code",))

    existing_codes_sql = (
        "SELECT DISTINCT trim(CAST(ts_code AS VARCHAR)) AS ts_code "
        f"FROM {existing_name} WHERE ts_code IS NOT NULL"
        if existing_name is not None
        else "SELECT CAST(NULL AS VARCHAR) AS ts_code WHERE FALSE"
    )
    summary_sql = _build_etf_mins_raw_candidate_summary_sql(
        source_relation=source_name,
        candidate_relation=candidate_name,
        basic_all_relation=basic_name,
        requestable_targets_relation=requestable_name,
        existing_codes_sql=existing_codes_sql,
        trade_date=normalized_trade_date,
        source_freq=normalized_source_freq,
    )
    row = connection.execute(summary_sql).fetchone()
    if row is None:
        raise RuntimeError("ETF minute Raw validation did not return a summary row.")

    numeric_values = tuple(int(value) for value in row[:21])
    (
        source_row_count,
        candidate_row_count,
        source_minus_candidate_count,
        candidate_minus_source_count,
        distinct_code_count,
        null_key_count,
        duplicate_key_count,
        date_mismatch_count,
        freq_mismatch_count,
        exchange_mismatch_count,
        invalid_ohlc_count,
        invalid_volume_amount_count,
        invalid_vwap_count,
        off_session_time_count,
        grid_gap_candidate_count,
        expected_count,
        present_count,
        missing_count,
        known_non_required_present_count,
        retained_legacy_count,
        unexplained_new_count,
    ) = numeric_values
    samples = tuple(
        tuple(str(code) for code in (value or ())) for value in row[21:25]
    )

    blocking_reasons: list[str] = []
    if (
        source_row_count != candidate_row_count
        or source_minus_candidate_count != 0
        or candidate_minus_source_count != 0
    ):
        blocking_reasons.append("etf_mins_raw_transport_mismatch")
    if null_key_count != 0 or duplicate_key_count != 0:
        blocking_reasons.append("etf_mins_raw_key_contract_failed")
    if date_mismatch_count != 0 or freq_mismatch_count != 0:
        blocking_reasons.append("etf_mins_raw_partition_contract_failed")
    if exchange_mismatch_count != 0:
        blocking_reasons.append("etf_mins_raw_exchange_identity_failed")
    if unexplained_new_count != 0:
        blocking_reasons.append("etf_mins_unexplained_new_code")

    return EtfMinsRawCandidateValidation(
        promotion_allowed=not blocking_reasons,
        silver_eligible=False,
        policy_state=ETF_MINS_RAW_POLICY_STATE_UNCLASSIFIED,
        stable_blocking_reason_codes=tuple(blocking_reasons),
        source_row_count=source_row_count,
        candidate_row_count=candidate_row_count,
        source_minus_candidate_count=source_minus_candidate_count,
        candidate_minus_source_count=candidate_minus_source_count,
        distinct_code_count=distinct_code_count,
        null_key_count=null_key_count,
        duplicate_key_count=duplicate_key_count,
        date_mismatch_count=date_mismatch_count,
        freq_mismatch_count=freq_mismatch_count,
        exchange_mismatch_count=exchange_mismatch_count,
        invalid_ohlc_count=invalid_ohlc_count,
        invalid_volume_amount_count=invalid_volume_amount_count,
        invalid_vwap_count=invalid_vwap_count,
        off_session_time_count=off_session_time_count,
        grid_gap_candidate_count=grid_gap_candidate_count,
        expected_count=expected_count,
        present_count=present_count,
        missing_count=missing_count,
        known_non_required_present_count=known_non_required_present_count,
        retained_legacy_count=retained_legacy_count,
        unexplained_new_count=unexplained_new_count,
        missing_samples=samples[0],
        known_non_required_samples=samples[1],
        retained_legacy_samples=samples[2],
        unexplained_new_samples=samples[3],
    )


def _build_etf_mins_raw_candidate_summary_sql(
    *,
    source_relation: str,
    candidate_relation: str,
    basic_all_relation: str,
    requestable_targets_relation: str,
    existing_codes_sql: str,
    trade_date: str,
    source_freq: str,
) -> str:
    columns = ", ".join(column.name for column in RAW_ETF_MINS_SCHEMA)
    asset_freq = asset_freq_for_etf_mins_source_freq(source_freq)
    sample_limit = ETF_MINS_DIAGNOSTIC_SAMPLE_LIMIT
    return f"""
WITH source_rows AS (
  SELECT {columns} FROM {source_relation}
),
candidate_rows AS (
  SELECT {columns} FROM {candidate_relation}
),
candidate_codes AS (
  SELECT DISTINCT trim(ts_code) AS ts_code
  FROM candidate_rows
  WHERE ts_code IS NOT NULL
),
basic_codes AS (
  SELECT DISTINCT trim(CAST(ts_code AS VARCHAR)) AS ts_code
  FROM {basic_all_relation}
  WHERE ts_code IS NOT NULL
),
requestable_targets AS (
  SELECT DISTINCT
    trim(CAST(ts_code AS VARCHAR)) AS ts_code,
    CAST(list_date AS DATE) AS list_date
  FROM {requestable_targets_relation}
  WHERE ts_code IS NOT NULL AND list_date IS NOT NULL
),
expected_codes AS (
  SELECT ts_code
  FROM requestable_targets
  WHERE list_date <= DATE '{trade_date}'
),
existing_codes AS (
  {existing_codes_sql}
),
missing_codes AS (
  SELECT expected.ts_code
  FROM expected_codes AS expected
  LEFT JOIN candidate_codes AS candidate USING (ts_code)
  WHERE candidate.ts_code IS NULL
),
known_non_required_codes AS (
  SELECT candidate.ts_code
  FROM candidate_codes AS candidate
  JOIN basic_codes AS basic USING (ts_code)
  LEFT JOIN expected_codes AS expected USING (ts_code)
  WHERE expected.ts_code IS NULL
),
retained_legacy_codes AS (
  SELECT candidate.ts_code
  FROM candidate_codes AS candidate
  LEFT JOIN basic_codes AS basic USING (ts_code)
  JOIN existing_codes AS existing USING (ts_code)
  WHERE basic.ts_code IS NULL
),
unexplained_new_codes AS (
  SELECT candidate.ts_code
  FROM candidate_codes AS candidate
  LEFT JOIN basic_codes AS basic USING (ts_code)
  LEFT JOIN existing_codes AS existing USING (ts_code)
  WHERE basic.ts_code IS NULL AND existing.ts_code IS NULL
),
duplicate_keys AS (
  SELECT count(*) - 1 AS duplicate_count
  FROM candidate_rows
  GROUP BY ts_code, freq, trade_time
  HAVING count(*) > 1
),
ordered_rows AS (
  SELECT
    ts_code,
    trade_time,
    lag(trade_time) OVER (PARTITION BY ts_code ORDER BY trade_time) AS previous_time
  FROM candidate_rows
  WHERE ts_code IS NOT NULL AND trade_time IS NOT NULL
),
source_minus_candidate AS (
  SELECT {columns} FROM source_rows
  EXCEPT ALL
  SELECT {columns} FROM candidate_rows
),
candidate_minus_source AS (
  SELECT {columns} FROM candidate_rows
  EXCEPT ALL
  SELECT {columns} FROM source_rows
)
SELECT
  (SELECT count(*) FROM source_rows) AS source_row_count,
  (SELECT count(*) FROM candidate_rows) AS candidate_row_count,
  (SELECT count(*) FROM source_minus_candidate) AS source_minus_candidate_count,
  (SELECT count(*) FROM candidate_minus_source) AS candidate_minus_source_count,
  (SELECT count(*) FROM candidate_codes) AS distinct_code_count,
  (SELECT count(*) FROM candidate_rows
    WHERE ts_code IS NULL OR freq IS NULL OR trade_time IS NULL) AS null_key_count,
  COALESCE((SELECT sum(duplicate_count) FROM duplicate_keys), 0) AS duplicate_key_count,
  (SELECT count(*) FROM candidate_rows
    WHERE trade_time IS NOT NULL AND CAST(trade_time AS DATE) <> DATE '{trade_date}')
    AS date_mismatch_count,
  (SELECT count(*) FROM candidate_rows
    WHERE freq IS NOT NULL AND freq <> '{source_freq}') AS freq_mismatch_count,
  (SELECT count(*) FROM candidate_rows
    WHERE ts_code IS NOT NULL AND NOT (
      (right(upper(trim(ts_code)), 3) = '.SH' AND exchange = 'XSHG') OR
      (right(upper(trim(ts_code)), 3) = '.SZ' AND exchange = 'XSHE')
    )) AS exchange_mismatch_count,
  (SELECT count(*) FROM candidate_rows
    WHERE open IS NULL OR close IS NULL OR high IS NULL OR low IS NULL
      OR NOT isfinite(open) OR NOT isfinite(close)
      OR NOT isfinite(high) OR NOT isfinite(low)
      OR high < greatest(open, close, low)
      OR low > least(open, close, high)) AS invalid_ohlc_count,
  (SELECT count(*) FROM candidate_rows
    WHERE vol IS NULL OR amount IS NULL OR vol < 0
      OR NOT isfinite(amount) OR amount < 0) AS invalid_volume_amount_count,
  (SELECT count(*) FROM candidate_rows
    WHERE vwap IS NULL OR NOT isfinite(vwap) OR vwap < 0) AS invalid_vwap_count,
  (SELECT count(*) FROM candidate_rows
    WHERE trade_time IS NOT NULL AND (
      CAST(trade_time AS TIME) < TIME '09:00:00'
      OR CAST(trade_time AS TIME) > TIME '16:00:00'
    )) AS off_session_time_count,
  (SELECT count(*) FROM ordered_rows
    WHERE previous_time IS NOT NULL
      AND date_diff('minute', previous_time, trade_time) > {asset_freq})
    AS grid_gap_candidate_count,
  (SELECT count(*) FROM expected_codes) AS expected_count,
  (SELECT count(*) FROM candidate_codes) AS present_count,
  (SELECT count(*) FROM missing_codes) AS missing_count,
  (SELECT count(*) FROM known_non_required_codes)
    AS known_non_required_present_count,
  (SELECT count(*) FROM retained_legacy_codes) AS retained_legacy_count,
  (SELECT count(*) FROM unexplained_new_codes) AS unexplained_new_count,
  COALESCE((SELECT list(ts_code ORDER BY ts_code) FROM (
    SELECT ts_code FROM missing_codes ORDER BY ts_code LIMIT {sample_limit}
  )), []::VARCHAR[]) AS missing_samples,
  COALESCE((SELECT list(ts_code ORDER BY ts_code) FROM (
    SELECT ts_code FROM known_non_required_codes ORDER BY ts_code LIMIT {sample_limit}
  )), []::VARCHAR[]) AS known_non_required_samples,
  COALESCE((SELECT list(ts_code ORDER BY ts_code) FROM (
    SELECT ts_code FROM retained_legacy_codes ORDER BY ts_code LIMIT {sample_limit}
  )), []::VARCHAR[]) AS retained_legacy_samples,
  COALESCE((SELECT list(ts_code ORDER BY ts_code) FROM (
    SELECT ts_code FROM unexplained_new_codes ORDER BY ts_code LIMIT {sample_limit}
  )), []::VARCHAR[]) AS unexplained_new_samples
"""


def _assert_exact_raw_schema(connection: Any, relation_name: str) -> None:
    observed = _relation_schema(connection, relation_name)
    if observed != _RAW_SCHEMA:
        raise ValueError(
            "ETF minute Raw relation schema does not match the exact 11-column contract: "
            f"relation={relation_name}, observed={observed}."
        )


def _assert_relation_columns(
    connection: Any,
    relation_name: str,
    *,
    required: tuple[str, ...],
) -> None:
    observed_names = {name for name, _ in _relation_schema(connection, relation_name)}
    missing = tuple(column for column in required if column not in observed_names)
    if missing:
        raise ValueError(
            f"ETF minute validation relation {relation_name} is missing {missing}."
        )


def _relation_schema(connection: Any, relation_name: str) -> tuple[tuple[str, str], ...]:
    rows = connection.execute(f"DESCRIBE SELECT * FROM {relation_name}").fetchall()
    return tuple((str(row[0]), str(row[1]).upper()) for row in rows)


def _normalize_relation_name(value: object) -> str:
    normalized = str(value).strip()
    if not _SQL_IDENTIFIER_RE.fullmatch(normalized):
        raise ValueError("ETF minute validation relation must be a simple identifier.")
    return normalized


__all__ = [
    "ETF_MINS_RAW_POLICY_STATE_UNCLASSIFIED",
    "EtfMinsRawCandidateValidation",
    "evaluate_etf_mins_raw_candidate",
]
