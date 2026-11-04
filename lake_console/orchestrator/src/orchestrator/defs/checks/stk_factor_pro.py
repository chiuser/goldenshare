"""Pure stock-factor file checks; no Dagster definitions or owned connections."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from pathlib import Path

from orchestrator.defs.duckdb_sql import read_parquet
from orchestrator.defs.run_contracts.stk_factor_pro import (
    STK_FACTOR_PRO_RAW_COLUMN_TYPES,
    STK_FACTOR_PRO_SILVER_COLUMN_TYPES,
    STK_FACTOR_PRO_SOURCE_COLUMNS,
    StkFactorProComparison,
    StkFactorProFileAudit,
)


def relation_identifier(value: str) -> str:
    if type(value) is not str or re.fullmatch(r"[a-z][a-z0-9_]*", value) is None:
        raise ValueError("技术因子临时关系名不合法")
    return f'"{value}"'


def factor_columns(alias: str | None = None) -> str:
    prefix = f"{relation_identifier(alias)}." if alias else ""
    return ", ".join(f'{prefix}"{name}"' for name in STK_FACTOR_PRO_SOURCE_COLUMNS)


def factor_file_sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def factor_file_identity(path: Path) -> tuple[int, int, int, int, int]:
    """Inspect a file's identity without reading its business data."""
    value = path.stat()
    return (
        value.st_dev,
        value.st_ino,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def factor_known_file_sha(path: Path, *, known_records: dict) -> str | None:
    """Return the first digest, refusing a later physical identity change."""
    try:
        identity = factor_file_identity(path)
    except FileNotFoundError:
        if path in known_records and known_records[path][2] is not None:
            raise ValueError("技术因子正式文件在首次读取后改变") from None
        known_records[path] = (None, None, None)
        return None
    if path in known_records:
        if known_records[path][2] != identity:
            raise ValueError("技术因子正式文件在首次读取后改变")
        return known_records[path][1]
    digest = factor_file_sha(path)
    if factor_file_identity(path) != identity:
        raise ValueError("技术因子文件在首次读取期间改变")
    known_records[path] = (None, digest, identity)
    return digest


def release_stk_factor_pro_audit_relations(connection) -> None:
    """Release this date's materialized file inputs after their final consumer."""
    names = connection.execute(
        "SELECT table_name FROM duckdb_tables() WHERE temporary "
        "AND starts_with(table_name, 'stk_factor_pro_checked_')"
    ).fetchall()
    failures = []
    for (name,) in names:
        try:
            connection.execute(f"DROP TABLE {relation_identifier(name)}")
        except BaseException as error:  # noqa: BLE001 -- finish all owned releases, then raise the first cleanup error.
            failures.append(error)
    if failures:
        for error in failures[1:]:
            failures[0].add_note(
                f"技术因子审计关系清理同时失败：{type(error).__name__}"
            )
        raise failures[0]


def factor_content_sha(connection, relation: str) -> str:
    fields = ", ".join(f'{name} := "{name}"' for name in STK_FACTOR_PRO_SOURCE_COLUMNS)
    return connection.execute(
        f"SELECT sha256(coalesce(string_agg(to_json(struct_pack({fields})), "
        f"'\n' ORDER BY ts_code, trade_date), '')) FROM {relation_identifier(relation)}"
    ).fetchone()[0]


def _require_factor_relation(
    connection,
    relation: str,
    *,
    types,
    invalid_date_sql: str,
    parameters: tuple,
    object_code: str | None = None,
):
    """Use the same schema/key/value checks for fixed day or history predicates."""
    name = relation_identifier(relation)
    observed = tuple(
        (row[0], row[1]) for row in connection.execute(f"DESCRIBE {name}").fetchall()
    )
    if observed != tuple(types.items()):
        raise ValueError("技术因子字段名称、顺序或类型与完整合同不符")
    invalid_numbers = " OR ".join(
        f'("{field}" IS NOT NULL AND NOT isfinite("{field}"))'
        for field in STK_FACTOR_PRO_SOURCE_COLUMNS[2:]
    )
    object_predicate = (
        " OR ts_code IS DISTINCT FROM ?" if object_code is not None else ""
    )
    values = ((object_code,) if object_code is not None else ()) + parameters
    rows, bad_keys, bad_dates, bad_numbers = connection.execute(
        f"SELECT count(*), count(*) FILTER (WHERE ts_code IS NULL OR "
        f"NOT regexp_full_match(ts_code, '[0-9]{{6}}\\.(SH|SZ|BJ)'){object_predicate}), "
        f"count(*) FILTER (WHERE {invalid_date_sql}), "
        f"count(*) FILTER (WHERE {invalid_numbers}) FROM {name}",
        values,
    ).fetchone()
    duplicate = connection.execute(
        f"SELECT count(*) FROM (SELECT ts_code, trade_date FROM {name} "
        "GROUP BY ts_code, trade_date HAVING count(*) > 1)"
    ).fetchone()[0]
    if any((bad_keys, bad_dates, bad_numbers, duplicate)):
        raise ValueError(
            f"技术因子结构检查失败：主键{bad_keys}、重复键{duplicate}、"
            f"日期{bad_dates}、非有限数值{bad_numbers}"
        )
    return int(rows), observed


def require_factor_relation(
    connection, relation: str, *, target_trade_date: date, layer: str
):
    """Require one exact day; historical requests use their separate entry point."""
    if layer not in ("raw", "silver") or type(target_trade_date) is not date:
        raise ValueError("技术因子检查层或日期不合法")
    types = (
        STK_FACTOR_PRO_RAW_COLUMN_TYPES
        if layer == "raw"
        else STK_FACTOR_PRO_SILVER_COLUMN_TYPES
    )
    wanted = (
        target_trade_date.strftime("%Y%m%d") if layer == "raw" else target_trade_date
    )
    return _require_factor_relation(
        connection,
        relation,
        types=types,
        invalid_date_sql="trade_date IS NULL OR trade_date IS DISTINCT FROM ?",
        parameters=(wanted,),
    )


def require_factor_history_relation(
    connection,
    relation: str,
    *,
    object_code: str,
    start_date: date,
    end_date: date,
):
    """Require complete Raw structure for one stock and its closed source range."""
    if (
        type(object_code) is not str
        or re.fullmatch(r"[0-9]{6}\.(SH|SZ|BJ)", object_code) is None
        or type(start_date) is not date
        or type(end_date) is not date
        or start_date > end_date
    ):
        raise ValueError("历史技术因子股票或闭区间日期不合法")
    return _require_factor_relation(
        connection,
        relation,
        types=STK_FACTOR_PRO_RAW_COLUMN_TYPES,
        invalid_date_sql=(
            "trade_date IS NULL OR NOT regexp_full_match(trade_date,'[0-9]{8}') "
            "OR try_strptime(trade_date,'%Y%m%d') IS NULL "
            "OR trade_date < ? OR trade_date > ?"
        ),
        parameters=(start_date.strftime("%Y%m%d"), end_date.strftime("%Y%m%d")),
        object_code=object_code,
    )


def compare_factor_relations(
    connection, *, expected: str, actual: str
) -> StkFactorProComparison:
    expected_name, actual_name = (
        relation_identifier(expected),
        relation_identifier(actual),
    )
    fields = STK_FACTOR_PRO_SOURCE_COLUMNS[2:]
    differences = [f'e."{field}" IS DISTINCT FROM a."{field}"' for field in fields]
    both = "e.ts_code IS NOT NULL AND a.ts_code IS NOT NULL"
    aggregations = ", ".join(
        f"count(*) FILTER (WHERE {both} AND ({diff}))" for diff in differences
    )
    result = connection.execute(
        f"SELECT count(*) FILTER (WHERE e.ts_code IS NOT NULL), "
        "count(*) FILTER (WHERE a.ts_code IS NOT NULL), "
        "count(*) FILTER (WHERE e.ts_code IS NOT NULL AND a.ts_code IS NULL), "
        "count(*) FILTER (WHERE e.ts_code IS NULL AND a.ts_code IS NOT NULL), "
        f"count(*) FILTER (WHERE {both} AND ({' OR '.join(differences)})), {aggregations} "
        f"FROM {expected_name} e FULL OUTER JOIN {actual_name} a "
        "ON e.ts_code=a.ts_code AND e.trade_date=a.trade_date"
    ).fetchone()
    return StkFactorProComparison(
        *result[:5], tuple(zip(fields, result[5:], strict=True))
    )


def audit_stk_factor_pro_file(
    connection,
    *,
    path: Path,
    expected_relation: str,
    target_trade_date: date,
    layer: str,
    known_records: dict,
    diagnostics_path: Path | None = None,
) -> StkFactorProFileAudit:
    identity = factor_file_identity(path)
    prior = known_records.get(path)
    if prior is not None and prior[2] != identity:
        raise ValueError("技术因子文件在首次读取后改变")
    before = (
        prior[1]
        if prior is not None and prior[1] is not None
        else factor_file_sha(path)
    )
    actual = (
        "stk_factor_pro_checked_"
        + hashlib.sha256(f"{path}:{before}".encode()).hexdigest()[:20]
    )
    primary = None
    try:
        if prior is not None and isinstance(prior[0], StkFactorProFileAudit):
            previous_audit = prior[0]
            if (previous_audit.trade_date, previous_audit.layer) != (
                target_trade_date,
                layer,
            ):
                raise ValueError("技术因子首次审计的日期或层与本次比较不符")
            if not connection.execute(
                "SELECT count(*) FROM duckdb_tables() WHERE temporary AND table_name=?",
                [actual],
            ).fetchone()[0]:
                raise ValueError("技术因子首次审计关系已经释放，请在新任务首次读取")
            rows, schema = previous_audit.row_count, previous_audit.observed_schema
        else:
            connection.execute(
                f"CREATE TEMP TABLE {actual} AS SELECT * FROM {read_parquet(path, hive_partitioning=False)}"
            )
            rows, schema = require_factor_relation(
                connection, actual, target_trade_date=target_trade_date, layer=layer
            )
        comparison = compare_factor_relations(
            connection, expected=expected_relation, actual=actual
        )
        passed = not any(
            (
                comparison.missing_key_count,
                comparison.unexpected_key_count,
                comparison.changed_row_count,
            )
        )
        if factor_file_identity(path) != identity:
            raise ValueError("技术因子检查期间文件已改变")
        saved_diagnostics = None
        if not passed and diagnostics_path is not None:
            # Bounded scalar diagnostics only; business rows never enter a source cache.
            columns = ", ".join(
                f'e."{field}" IS DISTINCT FROM a."{field}"'
                for field in STK_FACTOR_PRO_SOURCE_COLUMNS[2:]
            ).replace(", ", " OR ")
            samples = connection.execute(
                f"SELECT coalesce(e.ts_code,a.ts_code) FROM {relation_identifier(expected_relation)} e "
                f"FULL JOIN {actual} a USING (ts_code,trade_date) WHERE "
                f"e.ts_code IS NULL OR a.ts_code IS NULL OR ({columns}) "
                "ORDER BY 1 LIMIT 20"
            ).fetchall()
            diagnostics_path.parent.mkdir(parents=True, exist_ok=True)
            diagnostics_path.write_text(
                json.dumps(
                    {
                        "missing": comparison.missing_key_count,
                        "unexpected": comparison.unexpected_key_count,
                        "changed": comparison.changed_row_count,
                        "sample_codes": [row[0] for row in samples],
                    },
                    ensure_ascii=False,
                )
            )
            saved_diagnostics = diagnostics_path
        audit = StkFactorProFileAudit(
            target_trade_date,
            layer,
            path,
            before,
            schema,
            rows,
            0,
            0,
            0,
            0,
            comparison,
            passed,
            saved_diagnostics,
        )
        known_records[path] = (audit, before, identity)
        return audit
    except BaseException as error:
        primary = error
        raise
    finally:
        if primary is not None:
            try:
                connection.execute(f"DROP TABLE IF EXISTS {actual}")
            except BaseException as cleanup:  # noqa: BLE001 -- cleanup must not replace the existing business failure.
                primary.add_note(
                    f"技术因子文件检查清理同时失败：{type(cleanup).__name__}"
                )
                raise primary
