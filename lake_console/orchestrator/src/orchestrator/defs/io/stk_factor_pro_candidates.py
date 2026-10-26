"""Column conversion and per-date candidates on the caller's connection."""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Sequence
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Literal

import pandas as pd

from orchestrator.defs.checks.stk_factor_pro import (
    audit_stk_factor_pro_file,
    factor_columns,
    require_factor_relation,
)
from orchestrator.defs.duckdb_sql import copy_query_to_parquet
from orchestrator.defs.run_contracts.stk_factor_pro import (
    STK_FACTOR_PRO_SOURCE_COLUMNS,
    VerifiedDaySource,
)
from orchestrator.tushare_download import UnitResult

DAY_SOURCE = "stk_factor_pro_day_source"
HISTORY_DAY_SOURCE = "stk_factor_pro_history_day_source"
DAY_PRIOR = "stk_factor_pro_day_prior"
RAW_EXPECTED = "stk_factor_pro_raw_expected"
SILVER_EXPECTED = "stk_factor_pro_silver_expected"
Source = Literal["http", "prod_postgres"]


def require_stk_factor_pro_safe_path(path: Path) -> None:
    if (
        not path.is_absolute()
        or ".." in path.parts
        or any(p.is_symlink() for p in (path, *path.parents))
    ):
        raise ValueError("技术因子路径必须绝对、无越界且无符号链接")
    retired = Path("/Volumes/datasource/goldenshare-tushare-lake")
    if path == retired or retired in path.parents:
        raise ValueError("技术因子禁止使用退役Lake")


def require_stk_factor_pro_candidate_path(
    *, candidate_path: Path, run_root: Path
) -> None:
    require_stk_factor_pro_safe_path(run_root)
    require_stk_factor_pro_safe_path(candidate_path)
    candidate_root = run_root / "candidates"
    if candidate_path == candidate_root or not candidate_path.is_relative_to(
        candidate_root
    ):
        raise ValueError("技术因子候选路径必须属于当前run的candidates目录")
    if candidate_path.exists():
        raise ValueError("技术因子候选已存在，不接受覆盖或续跑")


def _prepare_stk_factor_pro_candidate_path(
    *, candidate_path: Path, run_root: Path
) -> None:
    require_stk_factor_pro_candidate_path(
        candidate_path=candidate_path, run_root=run_root
    )
    candidate_path.parent.mkdir(parents=True, exist_ok=True)
    require_stk_factor_pro_candidate_path(
        candidate_path=candidate_path, run_root=run_root
    )


def stk_factor_pro_raw_trade_date(value: object, *, source: Source) -> str:
    if source == "http" and type(value) is str and re.fullmatch(r"[0-9]{8}", value):
        parsed = date(int(value[:4]), int(value[4:6]), int(value[6:8]))
        if parsed.strftime("%Y%m%d") == value:
            return value
    elif source == "prod_postgres" and type(value) is date:
        return value.strftime("%Y%m%d")
    raise ValueError("技术因子源日期类型或格式不合法")


def stk_factor_pro_double(value: object, *, source: Source) -> float | None:
    if source not in ("http", "prod_postgres"):
        raise ValueError("技术因子来源不合法")
    if value is None:
        return None
    accepted = (int, Decimal) if source == "http" else (float,)
    if type(value) not in accepted:
        raise ValueError("技术因子源数值类型不符合合同")
    if isinstance(value, Decimal) and not value.is_finite():
        raise ValueError("技术因子源数值不是有限数")
    try:
        converted = float(value)
    except (ValueError, OverflowError) as error:
        raise ValueError("技术因子源数值超出DOUBLE范围") from error
    if not math.isfinite(converted) or (value != 0 and converted == 0):
        raise ValueError("技术因子源数值无法表示为有限非丢失DOUBLE")
    return converted


def stk_factor_pro_http_rows(result: UnitResult, contract_fields: tuple[str, ...]):
    if (
        not isinstance(result, UnitResult)
        or contract_fields != STK_FACTOR_PRO_SOURCE_COLUMNS
    ):
        raise ValueError("技术因子HTTP结果或完整字段合同不符")
    if not result.termination.all_scopes_complete or result.statistics.row_count != len(
        result.records
    ):
        raise ValueError("技术因子unit未完整或行数不符")
    if not result.observed_field_sets:
        raise ValueError("技术因子空响应也必须声明完整字段")
    positions = {}
    for fields in result.observed_field_sets:
        if len(fields) != len(set(fields)) or set(fields) != set(contract_fields):
            raise ValueError("技术因子HTTP字段缺失、多出或重复")
        positions[fields] = tuple(fields.index(name) for name in contract_fields)
    for record in result.records:
        if record.fields not in positions or len(record.values) != len(record.fields):
            raise ValueError("技术因子记录字段和值错位")
        yield tuple(record.values[index] for index in positions[record.fields])


def build_stk_factor_pro_raw_batch(
    *,
    rows: Iterable[Sequence[object]],
    source_fields: tuple[str, ...],
    source: Source,
    expected_dates: tuple[date, ...],
) -> pd.DataFrame:
    if source not in ("http", "prod_postgres"):
        raise ValueError("技术因子批来源不合法")
    if (
        source_fields != STK_FACTOR_PRO_SOURCE_COLUMNS
        or not expected_dates
        or any(type(day) is not date for day in expected_dates)
    ):
        raise ValueError("技术因子批字段或批准日期不合法")
    allowed = {day.strftime("%Y%m%d") for day in expected_dates}
    columns: list[list] = [[] for _ in source_fields]
    for row in rows:
        if len(row) != len(source_fields):
            raise ValueError("技术因子批记录列数错误")
        code, day = row[:2]
        if type(code) is not str or re.fullmatch(r"[0-9]{6}\.(SH|SZ|BJ)", code) is None:
            raise ValueError("技术因子股票代码错误")
        day = stk_factor_pro_raw_trade_date(day, source=source)
        if day not in allowed:
            raise ValueError("技术因子源日期超出本次unit范围")
        columns[0].append(code)
        columns[1].append(day)
        for index, value in enumerate(row[2:], 2):
            try:
                columns[index].append(stk_factor_pro_double(value, source=source))
            except ValueError as error:
                raise ValueError(
                    f"技术因子{code}/{day}字段{source_fields[index]}转换失败：{error}"
                ) from error
    return pd.DataFrame(
        {
            name: pd.array(values, dtype="string" if index < 2 else "Float64")
            for index, (name, values) in enumerate(
                zip(source_fields, columns, strict=True)
            )
        }
    )


def materialize_stk_factor_pro_day_source(
    connection, result: UnitResult, target: date
) -> None:
    frame = build_stk_factor_pro_raw_batch(
        rows=stk_factor_pro_http_rows(result, STK_FACTOR_PRO_SOURCE_COLUMNS),
        source_fields=STK_FACTOR_PRO_SOURCE_COLUMNS,
        source="http",
        expected_dates=(target,),
    )
    connection.register("stk_factor_pro_current_batch", frame)
    try:
        projection = ", ".join(
            f'CAST("{name}" AS {"VARCHAR" if index < 2 else "DOUBLE"}) AS "{name}"'
            for index, name in enumerate(STK_FACTOR_PRO_SOURCE_COLUMNS)
        )
        connection.execute(
            f"CREATE TEMP TABLE {DAY_SOURCE} AS SELECT {projection} FROM stk_factor_pro_current_batch"
        )
        source_nulls = tuple(
            int(frame[name].isna().sum()) for name in STK_FACTOR_PRO_SOURCE_COLUMNS
        )
        null_counts = ", ".join(
            f'count(*) FILTER (WHERE "{name}" IS NULL)'
            for name in STK_FACTOR_PRO_SOURCE_COLUMNS
        )
        saved_nulls = connection.execute(
            f"SELECT {null_counts} FROM {DAY_SOURCE}"
        ).fetchone()
        count, _ = require_factor_relation(
            connection, DAY_SOURCE, target_trade_date=target, layer="raw"
        )
        if count != len(result.records) or tuple(saved_nulls) != source_nulls:
            raise ValueError("技术因子列转换前后NULL或行数发生变化")
    finally:
        connection.unregister("stk_factor_pro_current_batch")


def release_stk_factor_pro_day_source(connection) -> None:
    for name in (SILVER_EXPECTED, RAW_EXPECTED, DAY_PRIOR, DAY_SOURCE):
        connection.execute(f"DROP TABLE IF EXISTS {name}")


def build_stk_factor_pro_raw_candidate(
    connection, *, source, prior_path: Path | None, candidate_path: Path, run_root: Path
):
    if not isinstance(source, VerifiedDaySource) or source.raw_relation != DAY_SOURCE:
        raise TypeError("日Raw候选必须接收当前VerifiedDaySource")
    return build_stk_factor_pro_raw_candidate_from_relation(
        connection,
        source_relation=DAY_SOURCE,
        target_trade_date=source.identity.target_trade_date,
        prior_path=prior_path,
        candidate_path=candidate_path,
        run_root=run_root,
    )


def build_stk_factor_pro_raw_candidate_from_relation(
    connection,
    *,
    source_relation: str,
    target_trade_date: date,
    prior_path: Path | None,
    candidate_path: Path,
    run_root: Path,
):
    """Build B-K+U from an already verified, internal single-date relation."""
    if (
        source_relation not in (DAY_SOURCE, HISTORY_DAY_SOURCE)
        or type(target_trade_date) is not date
    ):
        raise ValueError("Raw候选只接受内部已核单日关系及DATE处理日期")
    require_stk_factor_pro_candidate_path(
        candidate_path=candidate_path, run_root=run_root
    )
    target = target_trade_date
    if prior_path is None:
        connection.execute(
            f"CREATE TEMP TABLE {DAY_PRIOR} AS SELECT * FROM {source_relation} WHERE false"
        )
    else:
        require_stk_factor_pro_safe_path(prior_path)
        connection.execute(
            f"CREATE TEMP TABLE {DAY_PRIOR} AS SELECT * FROM read_parquet(?, hive_partitioning=false)",
            [str(prior_path)],
        )
    require_factor_relation(
        connection, DAY_PRIOR, target_trade_date=target, layer="raw"
    )
    require_factor_relation(
        connection, source_relation, target_trade_date=target, layer="raw"
    )
    connection.execute(
        f"CREATE TEMP TABLE {RAW_EXPECTED} AS SELECT {factor_columns('b')} FROM {DAY_PRIOR} b "
        f"WHERE NOT EXISTS (SELECT 1 FROM {source_relation} u WHERE u.ts_code=b.ts_code AND u.trade_date=b.trade_date) "
        f"UNION ALL SELECT {factor_columns()} FROM {source_relation}"
    )
    base, new, overlap, actual = connection.execute(
        f"SELECT (SELECT count(*) FROM {DAY_PRIOR}), (SELECT count(*) FROM {source_relation}), "
        f"(SELECT count(*) FROM {DAY_PRIOR} JOIN {source_relation} USING (ts_code,trade_date)), "
        f"(SELECT count(*) FROM {RAW_EXPECTED})"
    ).fetchone()
    if actual != base - overlap + new:
        raise ValueError("技术因子Raw合并数量不符合B-K+U")
    _prepare_stk_factor_pro_candidate_path(
        candidate_path=candidate_path, run_root=run_root
    )
    connection.execute(
        copy_query_to_parquet(
            f"SELECT {factor_columns()} FROM {RAW_EXPECTED} ORDER BY ts_code,trade_date",
            candidate_path,
        )
    )
    return audit_stk_factor_pro_file(
        connection,
        path=candidate_path,
        expected_relation=RAW_EXPECTED,
        target_trade_date=target,
        layer="raw",
    )


def build_stk_factor_pro_silver_candidate(
    connection,
    *,
    verified_raw_path: Path,
    target_trade_date: date,
    candidate_path: Path,
    run_root: Path,
):
    require_stk_factor_pro_candidate_path(
        candidate_path=candidate_path, run_root=run_root
    )
    projection = ", ".join(
        "CAST(strptime(trade_date, '%Y%m%d') AS DATE) AS trade_date"
        if name == "trade_date"
        else f'"{name}"'
        for name in STK_FACTOR_PRO_SOURCE_COLUMNS
    )
    connection.execute(
        f"CREATE TEMP TABLE {SILVER_EXPECTED} AS SELECT {projection} FROM read_parquet(?, hive_partitioning=false)",
        [str(verified_raw_path)],
    )
    require_factor_relation(
        connection, SILVER_EXPECTED, target_trade_date=target_trade_date, layer="silver"
    )
    _prepare_stk_factor_pro_candidate_path(
        candidate_path=candidate_path, run_root=run_root
    )
    connection.execute(
        copy_query_to_parquet(
            f"SELECT {factor_columns()} FROM {SILVER_EXPECTED} ORDER BY ts_code,trade_date",
            candidate_path,
        )
    )
    return audit_stk_factor_pro_file(
        connection,
        path=candidate_path,
        expected_relation=SILVER_EXPECTED,
        target_trade_date=target_trade_date,
        layer="silver",
    )
