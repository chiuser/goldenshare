"""Bounded historical Silver fallback for audited major-index minute gaps."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from orchestrator.defs.bootstrap.major_index_mins_bootstrap_plan import (
    MajorIndexMinsDatePlan,
    MajorIndexMinsSourcePlan,
)
from orchestrator.defs.bootstrap.major_index_mins_bootstrap_stage import (
    source_window_parquet_path,
)
from orchestrator.defs.duckdb_sql import (
    copy_query_to_parquet,
    duckdb_string,
    read_parquet,
)
from orchestrator.defs.io.major_index_mins_quality import (
    prepare_major_index_mins_expected_tables,
    validate_major_index_mins_relation,
)
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.run_contracts.major_index_mins import (
    MAJOR_INDEX_MINS_NON_BSE_FALLBACK_REVISION,
    MAJOR_INDEX_MINS_NON_BSE_FALLBACK_RULES,
    MAJOR_INDEX_MINS_RAW_COLUMN_TYPES,
    MAJOR_INDEX_MINS_SOURCE_COLUMNS,
    MajorIndexMinsHistoricalFallbackRule,
    major_index_mins_historical_fallback_fingerprint,
    major_index_mins_historical_fallback_rule,
    major_index_mins_session_times,
)


_SAMPLE_LIMIT = 20


class MajorIndexMinsHistoricalFallbackError(RuntimeError):
    """Raised when a published historical fallback cannot be reproduced safely."""


@dataclass(frozen=True, slots=True)
class MajorIndexMinsFallbackSourceValidation:
    source_row_count: int
    expected_source_row_count: int
    source_revision: str
    errors: tuple[str, ...]

    @property
    def ready(self) -> bool:
        return not self.errors


@dataclass(frozen=True, slots=True)
class MajorIndexMinsFallbackWriteResult:
    trade_date: str
    target_freq: str
    source_freq: str
    source_mode: str
    reason_code: str
    target_codes: tuple[str, ...]
    source_row_count: int
    output_row_count: int
    expected_output_row_count: int
    source_revision: str
    rule_fingerprint: str
    target_path: Path
    write_mode: str
    elapsed_ms: float

    def to_details(self) -> dict[str, object]:
        return {
            "trade_date": self.trade_date,
            "target_freq": self.target_freq,
            "source_freq": self.source_freq,
            "source_mode": self.source_mode,
            "reason_code": self.reason_code,
            "target_code_count": len(self.target_codes),
            "target_code_samples": list(self.target_codes[:3]),
            "source_row_count": self.source_row_count,
            "output_row_count": self.output_row_count,
            "expected_output_row_count": self.expected_output_row_count,
            "source_revision": self.source_revision,
            "rule_fingerprint": self.rule_fingerprint,
            "target_path": str(self.target_path),
            "write_mode": self.write_mode,
            "elapsed_ms": round(self.elapsed_ms, 3),
        }


@dataclass(frozen=True, slots=True)
class MajorIndexMinsFallbackBatchReport:
    generated_at: str
    output_root: str
    fallback_revision: str
    rule_fingerprint: str
    rule_count: int
    expanded_scope_count: int
    source_partition_count: int
    source_row_count: int
    output_row_count: int
    written_count: int
    reused_count: int
    duckdb_connection_count: int
    source_request_count: int
    dagster_event_query_count: int
    should_stop: bool
    stop_reason_codes: tuple[str, ...]
    elapsed_ms: float
    results: tuple[MajorIndexMinsFallbackWriteResult, ...]
    failure_samples: tuple[Mapping[str, object], ...]

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["results"] = [result.to_details() for result in self.results]
        payload["failure_samples"] = [
            dict(sample) for sample in self.failure_samples
        ]
        payload["writes"] = {
            "fallback_samples": self.written_count,
            "formal_lake": 0,
            "dagster_db": 0,
            "dagster_events": 0,
        }
        return payload


def major_index_mins_fallback_sample_path(
    output_root: Path,
    *,
    target_freq: str,
    trade_date: str,
) -> Path:
    rule = major_index_mins_historical_fallback_rule(
        trade_date=trade_date,
        target_freq=target_freq,
    )
    if rule is None:
        raise MajorIndexMinsHistoricalFallbackError(
            "major-index minute fallback sample path requires a published rule."
        )
    return (
        output_root
        / "_major_index_mins_fallback"
        / f"revision={MAJOR_INDEX_MINS_NON_BSE_FALLBACK_REVISION}"
        / f"target_freq={rule.target_freq}"
        / f"trade_date={rule.trade_date}"
        / "part-000.parquet"
    )


def _atomic_write_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _safe_run_id(run_id: str) -> str:
    normalized = str(run_id).strip()
    if (
        not normalized
        or normalized in {".", ".."}
        or "/" in normalized
        or "\\" in normalized
    ):
        raise MajorIndexMinsHistoricalFallbackError(
            "major-index minute fallback run id must be a safe path component."
        )
    return normalized


def _require_published_rule(
    rule: MajorIndexMinsHistoricalFallbackRule,
) -> MajorIndexMinsHistoricalFallbackRule:
    published = major_index_mins_historical_fallback_rule(
        trade_date=rule.trade_date,
        target_freq=rule.target_freq,
    )
    if published != rule:
        raise MajorIndexMinsHistoricalFallbackError(
            "major-index minute fallback rule is not in the published contract."
        )
    return published


def _source_paths_for_codes(
    *,
    staging_root: Path,
    date_plan: MajorIndexMinsDatePlan,
    source_plan: MajorIndexMinsSourcePlan,
    trade_date: str,
    source_freq: str,
    target_codes: Sequence[str],
) -> tuple[Path, ...]:
    selected_paths: list[Path] = []
    for code in target_codes:
        matching_windows = tuple(
            window
            for window in source_plan.windows
            if window.ts_code == code
            and window.source_freq == source_freq
            and trade_date in window.trade_dates
        )
        if len(matching_windows) != 1:
            raise MajorIndexMinsHistoricalFallbackError(
                "historical fallback source plan must contain exactly one window: "
                f"date={trade_date}, freq={source_freq}, code={code}, "
                f"matches={len(matching_windows)}."
            )
        source_path = source_window_parquet_path(
            staging_root,
            date_plan,
            matching_windows[0],
        )
        if not source_path.is_file():
            raise MajorIndexMinsHistoricalFallbackError(
                f"historical fallback source file is missing: {source_path}"
            )
        selected_paths.append(source_path)
    return tuple(sorted(set(selected_paths)))


def _parquet_list(paths: Sequence[Path]) -> str:
    if not paths:
        raise MajorIndexMinsHistoricalFallbackError(
            "historical fallback source path list is empty."
        )
    return "[" + ", ".join(duckdb_string(path) for path in paths) + "]"


def _assert_source_schema(connection, *, relation_sql: str) -> None:
    try:
        description = connection.execute(f"DESCRIBE SELECT * FROM {relation_sql}").fetchall()
    except Exception as error:  # noqa: BLE001 - normalize corrupt Parquet failures.
        raise MajorIndexMinsHistoricalFallbackError(
            "historical fallback source cannot be read as Parquet."
        ) from error
    observed = tuple((str(row[0]), str(row[1]).upper()) for row in description)
    expected = tuple(
        (column, MAJOR_INDEX_MINS_RAW_COLUMN_TYPES[column])
        for column in MAJOR_INDEX_MINS_SOURCE_COLUMNS
    )
    if observed != expected:
        raise MajorIndexMinsHistoricalFallbackError(
            "historical fallback source schema does not match the Raw contract."
        )


def _create_source_relation(
    connection,
    *,
    table_name: str,
    source_paths: Sequence[Path],
    trade_date: str,
) -> int:
    parquet_relation = (
        f"read_parquet({_parquet_list(source_paths)}, hive_partitioning=false)"
    )
    _assert_source_schema(connection, relation_sql=parquet_relation)
    connection.execute(
        f"""
        CREATE TEMP TABLE {table_name} AS
        SELECT
          upper(trim(CAST(ts_code AS VARCHAR)))::VARCHAR AS ts_code,
          trim(CAST(freq AS VARCHAR))::VARCHAR AS freq,
          CAST(trade_time AS TIMESTAMP) AS trade_time,
          CAST(open AS DOUBLE) AS open,
          CAST(close AS DOUBLE) AS close,
          CAST(high AS DOUBLE) AS high,
          CAST(low AS DOUBLE) AS low,
          CAST(vol AS DOUBLE) AS vol,
          CAST(amount AS DOUBLE) AS amount,
          CASE
            WHEN right(upper(trim(CAST(ts_code AS VARCHAR))), 3) = '.SH'
              THEN 'XSHG'
            WHEN right(upper(trim(CAST(ts_code AS VARCHAR))), 3) = '.SZ'
              THEN 'XSHE'
            ELSE NULL
          END::VARCHAR AS exchange,
          CAST(vwap AS DOUBLE) AS vwap
        FROM {parquet_relation}
        WHERE CAST(trade_time AS DATE) = DATE {duckdb_string(trade_date)}
        """
    )
    return int(
        connection.execute(f"SELECT count(*) FROM {table_name}").fetchone()[0]
        or 0
    )


def _code_filter(target_codes: Sequence[str]) -> str:
    return ", ".join(duckdb_string(code) for code in target_codes)


def _source_revision(connection, *, source_relation_sql: str) -> str:
    revision = connection.execute(
        f"""
        WITH serialized AS (
          SELECT
            ts_code,
            trade_time,
            to_json(struct_pack(
              ts_code := ts_code,
              freq := freq,
              trade_time := strftime(trade_time, '%Y-%m-%d %H:%M:%S'),
              open := open,
              close := close,
              high := high,
              low := low,
              vol := vol,
              amount := amount,
              exchange := exchange,
              vwap := vwap
            )) AS row_payload
          FROM ({source_relation_sql}) source_rows
        )
        SELECT sha256(
          string_agg(row_payload, chr(10) ORDER BY ts_code, trade_time)
        )
        FROM serialized
        """
    ).fetchone()[0]
    return str(revision or "")


def validate_major_index_mins_fallback_source(
    *,
    connection,
    source_relation_sql: str,
    rule: MajorIndexMinsHistoricalFallbackRule,
) -> MajorIndexMinsFallbackSourceValidation:
    published = _require_published_rule(rule)
    prepare_major_index_mins_expected_tables(
        connection,
        expected_codes=published.target_codes,
        frequency=published.source_freq,
    )
    validation = validate_major_index_mins_relation(
        connection,
        relation_sql=source_relation_sql,
        expected_codes=published.target_codes,
        frequency=published.source_freq,
        partition_key=published.trade_date,
    )
    return MajorIndexMinsFallbackSourceValidation(
        source_row_count=validation.row_count,
        expected_source_row_count=validation.expected_row_count,
        source_revision=(
            _source_revision(connection, source_relation_sql=source_relation_sql)
            if not validation.errors
            else ""
        ),
        errors=validation.errors,
    )


def _prepare_fallback_window_map(
    connection,
    *,
    source_freq: str,
    target_freq: str,
) -> None:
    source_times = major_index_mins_session_times(
        exchange="XSHG",
        source_freq=source_freq,
    )
    target_times = major_index_mins_session_times(
        exchange="XSHG",
        source_freq=target_freq,
    )
    mapped_rows: list[tuple[str, str]] = []
    for source_time in source_times:
        target_time = next(
            (candidate for candidate in target_times if candidate >= source_time),
            None,
        )
        if target_time is None:
            raise MajorIndexMinsHistoricalFallbackError(
                "historical fallback source time has no target window: "
                f"{source_time}."
            )
        mapped_rows.append((source_time, target_time))
    counts = Counter(target_time for _, target_time in mapped_rows)
    if set(counts) != set(target_times):
        raise MajorIndexMinsHistoricalFallbackError(
            "historical fallback target window map is incomplete."
        )
    connection.execute("DROP TABLE IF EXISTS fallback_window_map")
    connection.execute(
        "CREATE TEMP TABLE fallback_window_map("
        "source_time TIME PRIMARY KEY, target_time TIME NOT NULL, "
        "expected_source_count INTEGER NOT NULL)"
    )
    connection.executemany(
        "INSERT INTO fallback_window_map VALUES (?, ?, ?)",
        [
            (source_time, target_time, counts[target_time])
            for source_time, target_time in mapped_rows
        ],
    )


def build_major_index_mins_fallback_relation(
    *,
    connection,
    source_relation_sql: str,
    rule: MajorIndexMinsHistoricalFallbackRule,
) -> str:
    published = _require_published_rule(rule)
    _prepare_fallback_window_map(
        connection,
        source_freq=published.source_freq,
        target_freq=published.target_freq,
    )
    return f"""
    SELECT * FROM (
      WITH windowed AS (
        SELECT source_rows.*, window_map.target_time,
               window_map.expected_source_count
        FROM ({source_relation_sql}) source_rows
        INNER JOIN fallback_window_map window_map
          ON CAST(source_rows.trade_time AS TIME) = window_map.source_time
      ), aggregated AS (
        SELECT
          ts_code,
          {duckdb_string(published.target_freq)}::VARCHAR AS freq,
          CAST(
            CAST(CAST(trade_time AS DATE) AS VARCHAR) || ' ' ||
            CAST(max(target_time) AS VARCHAR)
            AS TIMESTAMP
          ) AS trade_time,
          arg_min(open, trade_time)::DOUBLE AS open,
          arg_max(close, trade_time)::DOUBLE AS close,
          max(high)::DOUBLE AS high,
          min(low)::DOUBLE AS low,
          sum(vol)::DOUBLE AS vol,
          sum(amount)::DOUBLE AS amount,
          max(exchange)::VARCHAR AS exchange,
          count(*)::INTEGER AS source_row_count,
          max(expected_source_count)::INTEGER AS expected_source_count
        FROM windowed
        GROUP BY ts_code, CAST(trade_time AS DATE), target_time
      )
      SELECT
        ts_code,
        freq,
        trade_time,
        open,
        close,
        high,
        low,
        vol,
        amount,
        exchange,
        NULL::DOUBLE AS vwap
      FROM aggregated
      WHERE source_row_count = expected_source_count
    ) fallback_rows
    ORDER BY ts_code, trade_time
    """


def _validate_output(
    connection,
    *,
    relation_sql: str,
    rule: MajorIndexMinsHistoricalFallbackRule,
) -> int:
    prepare_major_index_mins_expected_tables(
        connection,
        expected_codes=rule.target_codes,
        frequency=rule.target_freq,
    )
    validation = validate_major_index_mins_relation(
        connection,
        relation_sql=relation_sql,
        expected_codes=rule.target_codes,
        frequency=rule.target_freq,
        partition_key=rule.trade_date,
        require_null_vwap=True,
    )
    if validation.errors:
        raise MajorIndexMinsHistoricalFallbackError(
            "historical fallback output failed the Silver contract: "
            f"date={rule.trade_date}, freq={rule.target_freq}, "
            f"errors={validation.errors!r}."
        )
    return validation.row_count


def _relations_match(
    connection,
    *,
    left_relation_sql: str,
    right_relation_sql: str,
) -> bool:
    def as_select(relation_sql: str) -> str:
        stripped = relation_sql.lstrip()
        return (
            relation_sql
            if stripped.lower().startswith(("select", "with"))
            else f"SELECT * FROM {relation_sql}"
        )

    left_select = as_select(left_relation_sql)
    right_select = as_select(right_relation_sql)
    difference_count = int(
        connection.execute(
            f"""
            WITH left_rows AS ({left_select}),
                 right_rows AS ({right_select}),
                 left_only AS (
                   SELECT * FROM left_rows
                   EXCEPT ALL
                   SELECT * FROM right_rows
                 ),
                 right_only AS (
                   SELECT * FROM right_rows
                   EXCEPT ALL
                   SELECT * FROM left_rows
                 )
            SELECT
              (SELECT count(*) FROM left_only) +
              (SELECT count(*) FROM right_only)
            """
        ).fetchone()[0]
        or 0
    )
    return difference_count == 0


def _write_rule_with_connection(
    *,
    connection,
    source_table: str,
    output_root: Path,
    rule: MajorIndexMinsHistoricalFallbackRule,
    run_id: str,
) -> MajorIndexMinsFallbackWriteResult:
    started_at = perf_counter()
    published = _require_published_rule(rule)
    source_sql = (
        f"SELECT * FROM {source_table} "
        f"WHERE ts_code IN ({_code_filter(published.target_codes)})"
    )
    source_validation = validate_major_index_mins_fallback_source(
        connection=connection,
        source_relation_sql=source_sql,
        rule=published,
    )
    if not source_validation.ready:
        raise MajorIndexMinsHistoricalFallbackError(
            "historical fallback source failed the finer-frequency contract: "
            f"date={published.trade_date}, freq={published.source_freq}, "
            f"errors={source_validation.errors!r}."
        )
    output_sql = build_major_index_mins_fallback_relation(
        connection=connection,
        source_relation_sql=source_sql,
        rule=published,
    )
    output_row_count = _validate_output(
        connection,
        relation_sql=output_sql,
        rule=published,
    )
    expected_output_row_count = len(published.target_codes) * len(
        major_index_mins_session_times(
            exchange="XSHG",
            source_freq=published.target_freq,
        )
    )
    if output_row_count != expected_output_row_count:
        raise MajorIndexMinsHistoricalFallbackError(
            "historical fallback output row count does not match the rule."
        )
    target_path = major_index_mins_fallback_sample_path(
        output_root,
        target_freq=published.target_freq,
        trade_date=published.trade_date,
    )
    if target_path.exists():
        target_relation = read_parquet(target_path, hive_partitioning=False)
        _validate_output(
            connection,
            relation_sql=target_relation,
            rule=published,
        )
        if not _relations_match(
            connection,
            left_relation_sql=target_relation,
            right_relation_sql=output_sql,
        ):
            raise MajorIndexMinsHistoricalFallbackError(
                f"historical fallback target conflicts with computed rows: {target_path}"
            )
        write_mode = "reuse_existing"
    else:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        staging_path = target_path.with_name(
            f".{target_path.name}.{run_id}.{uuid4().hex}.tmp"
        )
        try:
            connection.execute(copy_query_to_parquet(output_sql, staging_path))
            staged_relation = read_parquet(staging_path, hive_partitioning=False)
            staged_row_count = _validate_output(
                connection,
                relation_sql=staged_relation,
                rule=published,
            )
            if staged_row_count != output_row_count or not _relations_match(
                connection,
                left_relation_sql=staged_relation,
                right_relation_sql=output_sql,
            ):
                raise MajorIndexMinsHistoricalFallbackError(
                    "historical fallback staging readback mismatch."
                )
            if target_path.exists():
                raise MajorIndexMinsHistoricalFallbackError(
                    f"historical fallback target appeared during write: {target_path}"
                )
            os.replace(staging_path, target_path)
        finally:
            staging_path.unlink(missing_ok=True)
        write_mode = "staged_atomic_replace"
    return MajorIndexMinsFallbackWriteResult(
        trade_date=published.trade_date,
        target_freq=published.target_freq,
        source_freq=published.source_freq,
        source_mode="derived_fallback",
        reason_code=published.reason_code,
        target_codes=published.target_codes,
        source_row_count=source_validation.source_row_count,
        output_row_count=output_row_count,
        expected_output_row_count=expected_output_row_count,
        source_revision=source_validation.source_revision,
        rule_fingerprint=major_index_mins_historical_fallback_fingerprint(),
        target_path=target_path,
        write_mode=write_mode,
        elapsed_ms=(perf_counter() - started_at) * 1000,
    )


def write_major_index_mins_fallback_sample(
    *,
    staging_root: Path,
    output_root: Path,
    date_plan: MajorIndexMinsDatePlan,
    source_plan: MajorIndexMinsSourcePlan,
    duckdb_resource: DuckDBResource,
    rule: MajorIndexMinsHistoricalFallbackRule,
    run_id: str,
) -> MajorIndexMinsFallbackWriteResult:
    published = _require_published_rule(rule)
    if published.trade_date not in date_plan.expected_trade_dates:
        raise MajorIndexMinsHistoricalFallbackError(
            "historical fallback date is outside the frozen date plan."
        )
    safe_run_id = _safe_run_id(run_id)
    source_paths = _source_paths_for_codes(
        staging_root=staging_root,
        date_plan=date_plan,
        source_plan=source_plan,
        trade_date=published.trade_date,
        source_freq=published.source_freq,
        target_codes=published.target_codes,
    )
    with duckdb_resource.connect() as connection:
        _create_source_relation(
            connection,
            table_name="fallback_source_0",
            source_paths=source_paths,
            trade_date=published.trade_date,
        )
        return _write_rule_with_connection(
            connection=connection,
            source_table="fallback_source_0",
            output_root=output_root,
            rule=published,
            run_id=safe_run_id,
        )


def write_major_index_mins_fallback_samples(
    *,
    staging_root: Path,
    output_root: Path,
    date_plan: MajorIndexMinsDatePlan,
    source_plan: MajorIndexMinsSourcePlan,
    duckdb_resource: DuckDBResource,
    output_path: Path,
    run_id: str,
) -> MajorIndexMinsFallbackBatchReport:
    """Write all published non-BSE fallback samples through one connection."""

    started_at = perf_counter()
    safe_run_id = _safe_run_id(run_id)
    rules = MAJOR_INDEX_MINS_NON_BSE_FALLBACK_RULES
    results: list[MajorIndexMinsFallbackWriteResult] = []
    failure_samples: list[Mapping[str, object]] = []
    source_row_count = 0
    source_partition_count = 0
    grouped_rules: dict[
        tuple[str, str], list[MajorIndexMinsHistoricalFallbackRule]
    ] = defaultdict(list)
    for rule in rules:
        if rule.trade_date not in date_plan.expected_trade_dates:
            raise MajorIndexMinsHistoricalFallbackError(
                "published fallback date is outside the frozen date plan: "
                f"{rule.trade_date}."
            )
        grouped_rules[(rule.trade_date, rule.source_freq)].append(rule)

    try:
        with duckdb_resource.connect() as connection:
            for table_index, ((trade_date, source_freq), source_rules) in enumerate(
                sorted(grouped_rules.items())
            ):
                target_codes = tuple(
                    sorted(
                        {
                            code
                            for source_rule in source_rules
                            for code in source_rule.target_codes
                        }
                    )
                )
                source_paths = _source_paths_for_codes(
                    staging_root=staging_root,
                    date_plan=date_plan,
                    source_plan=source_plan,
                    trade_date=trade_date,
                    source_freq=source_freq,
                    target_codes=target_codes,
                )
                table_name = f"fallback_source_{table_index}"
                source_row_count += _create_source_relation(
                    connection,
                    table_name=table_name,
                    source_paths=source_paths,
                    trade_date=trade_date,
                )
                source_partition_count += 1
                for rule in source_rules:
                    results.append(
                        _write_rule_with_connection(
                            connection=connection,
                            source_table=table_name,
                            output_root=output_root,
                            rule=rule,
                            run_id=safe_run_id,
                        )
                    )
    except Exception as error:  # noqa: BLE001 - write a bounded fail-closed report.
        failure_samples.append(
            {
                "error_type": type(error).__name__,
                "message": str(error)[:500],
            }
        )

    report = MajorIndexMinsFallbackBatchReport(
        generated_at=datetime.now(timezone.utc).isoformat(),
        output_root=str(output_root),
        fallback_revision=MAJOR_INDEX_MINS_NON_BSE_FALLBACK_REVISION,
        rule_fingerprint=major_index_mins_historical_fallback_fingerprint(),
        rule_count=len(rules),
        expanded_scope_count=sum(len(rule.target_codes) for rule in rules),
        source_partition_count=source_partition_count,
        source_row_count=source_row_count,
        output_row_count=sum(result.output_row_count for result in results),
        written_count=sum(
            result.write_mode == "staged_atomic_replace" for result in results
        ),
        reused_count=sum(result.write_mode == "reuse_existing" for result in results),
        duckdb_connection_count=1,
        source_request_count=0,
        dagster_event_query_count=0,
        should_stop=bool(failure_samples),
        stop_reason_codes=("historical_fallback_failed",) if failure_samples else (),
        elapsed_ms=(perf_counter() - started_at) * 1000,
        results=tuple(results),
        failure_samples=tuple(failure_samples[:_SAMPLE_LIMIT]),
    )
    _atomic_write_json(output_path, report.to_dict())
    return report
