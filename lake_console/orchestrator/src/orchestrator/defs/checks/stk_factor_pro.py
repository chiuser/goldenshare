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


def factor_content_sha(connection, relation: str) -> str:
    fields = ", ".join(f'{name} := "{name}"' for name in STK_FACTOR_PRO_SOURCE_COLUMNS)
    return connection.execute(
        f"SELECT sha256(coalesce(string_agg(to_json(struct_pack({fields})), "
        f"'\n' ORDER BY ts_code, trade_date), '')) FROM {relation_identifier(relation)}"
    ).fetchone()[0]


def require_factor_relation(
    connection, relation: str, *, target_trade_date: date, layer: str
):
    """Reject invalid structure before a key join can multiply/misclassify rows."""
    name = relation_identifier(relation)
    types = (
        STK_FACTOR_PRO_RAW_COLUMN_TYPES
        if layer == "raw"
        else STK_FACTOR_PRO_SILVER_COLUMN_TYPES
    )
    if layer not in ("raw", "silver") or type(target_trade_date) is not date:
        raise ValueError("技术因子检查层或日期不合法")
    observed = tuple(
        (row[0], row[1]) for row in connection.execute(f"DESCRIBE {name}").fetchall()
    )
    if observed != tuple(types.items()):
        raise ValueError("技术因子字段名称、顺序或类型与完整合同不符")
    invalid_numbers = " OR ".join(
        f'("{field}" IS NOT NULL AND NOT isfinite("{field}"))'
        for field in STK_FACTOR_PRO_SOURCE_COLUMNS[2:]
    )
    wanted = (
        target_trade_date.strftime("%Y%m%d") if layer == "raw" else target_trade_date
    )
    rows, bad_keys, bad_dates, bad_numbers = connection.execute(
        f"SELECT count(*), count(*) FILTER (WHERE ts_code IS NULL OR "
        f"NOT regexp_full_match(ts_code, '[0-9]{{6}}\\.(SH|SZ|BJ)')), "
        f"count(*) FILTER (WHERE trade_date IS NULL OR trade_date IS DISTINCT FROM ?), "
        f"count(*) FILTER (WHERE {invalid_numbers}) FROM {name}",
        [wanted],
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
    diagnostics_path: Path | None = None,
) -> StkFactorProFileAudit:
    before = factor_file_sha(path)
    actual = "stk_factor_pro_checked_file"
    connection.execute(
        f"CREATE OR REPLACE TEMP VIEW {actual} AS SELECT * FROM {read_parquet(path, hive_partitioning=False)}"
    )
    try:
        rows, schema = require_factor_relation(
            connection, actual, target_trade_date=target_trade_date, layer=layer
        )
        require_factor_relation(
            connection,
            expected_relation,
            target_trade_date=target_trade_date,
            layer=layer,
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
        if factor_file_sha(path) != before:
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
        return StkFactorProFileAudit(
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
    finally:
        connection.execute(f"DROP VIEW IF EXISTS {actual}")
