"""指数周期 Raw 的文件保存契约；候选校验与原生 check 共用结果。"""

from dataclasses import dataclass
from pathlib import Path

import dagster as dg

from orchestrator.defs.duckdb_sql import duckdb_string, read_parquet
from orchestrator.defs.partitions import cn_a_index_months, cn_a_index_week_ends
from orchestrator.defs.run_contracts.asset_column_schemas import (
    RAW_INDEX_WEEKLY_SCHEMA,
    SILVER_INDEX_WEEKLY_SCHEMA,
)
from orchestrator.defs.run_contracts.index_period import INDEX_WEEKLY
from orchestrator.defs.run_contracts.metadata import CheckScope, build_check_metadata


@dataclass(frozen=True)
class IndexPeriodFileCheck:
    file_row_count: int
    source_row_count: int
    failure_counts: dict[str, int]
    failure_samples: tuple[str, ...] = ()

    @property
    def passed(self) -> bool:
        return not any(self.failure_counts.values())


class IndexPeriodContractError(ValueError):
    def __init__(self, result: IndexPeriodFileCheck, period_end):
        self.result = result
        self.period_end = period_end
        super().__init__(f"指数周期文件保存契约失败：{result.failure_counts}")


def index_period_raw_schema_matches(connection, relation: str) -> bool:
    return index_period_schema_matches(connection, relation, "raw")


def check_index_period_raw_file(
    connection,
    *,
    path: Path,
    delta_relation: str,
    source_row_count: int,
    expected_file_row_count: int,
    codes: tuple[str, ...],
    period_end,
) -> IndexPeriodFileCheck:
    """只审计本次 delta 的键与日期；完整文件仅读 schema、footer 行数。"""
    relation = read_parquet(path)
    schema_ok = index_period_raw_schema_matches(connection, relation)
    file_count = connection.execute(f"SELECT count(*) FROM {relation}").fetchone()[0]
    allowed = ",".join(duckdb_string(code) for code in codes)
    invalid_predicate = f"ts_code IS NULL OR ts_code NOT IN ({allowed}) OR trade_date IS NULL OR trade_date != {duckdb_string(period_end.strftime('%Y%m%d'))}"
    count, unique_count, invalid_count = connection.execute(
        f"SELECT count(*),count(DISTINCT (ts_code,trade_date)),count(*) FILTER (WHERE {invalid_predicate}) FROM {delta_relation}"
    ).fetchone()
    invalid = tuple(
        str(row)
        for row in connection.execute(
            f"SELECT ts_code,trade_date FROM {delta_relation} WHERE {invalid_predicate} LIMIT {len(codes)}"
        ).fetchall()
    )
    failures = {
        "schema": int(not schema_ok),
        "file_row_count": int(file_count != expected_file_row_count),
        "source_row_count": int(count != source_row_count),
        "duplicate_key": count - unique_count,
        "code_or_date": invalid_count,
    }
    return IndexPeriodFileCheck(
        file_count, source_row_count, failures, invalid[: len(codes)]
    )


def index_period_schema_matches(connection, relation, layer):
    schema = RAW_INDEX_WEEKLY_SCHEMA if layer == "raw" else SILVER_INDEX_WEEKLY_SCHEMA
    actual = connection.execute(f"DESCRIBE SELECT * FROM {relation}").fetchall()
    return tuple((r[0], r[1].replace(" ", "")) for r in actual) == tuple(
        (c.name, c.type) for c in schema
    )


def check_index_period_file(
    connection,
    *,
    path,
    delta_relation,
    layer,
    source_row_count,
    expected_file_row_count,
    codes,
    period_start=None,
    period_end=None,
):
    """单次复制／写入的集合式保存检查，不重算历史行情。"""
    relation = read_parquet(path)
    file_count = connection.execute(f"SELECT count(*) FROM {relation}").fetchone()[0]
    key_date = "trade_date" if layer == "raw" else "period_start_date"
    day = "try_strptime(trade_date,'%Y%m%d')::DATE" if layer == "raw" else "trade_date"
    allowed = ",".join(duckdb_string(code) for code in codes)
    invalid = f"ts_code IS NULL OR ts_code NOT IN ({allowed}) OR {key_date} IS NULL OR {day} IS NULL"
    if layer == "silver":
        invalid += " OR period_start_date > trade_date"
        if period_start is not None:
            invalid += f" OR period_start_date != DATE {duckdb_string(period_start)} OR trade_date > DATE {duckdb_string(period_end)}"
    count, unique_count, invalid_count = connection.execute(
        f"SELECT count(*), count(DISTINCT (ts_code,{key_date})), count(*) FILTER (WHERE {invalid}) FROM {delta_relation}"
    ).fetchone()
    samples = tuple(
        str(row)
        for row in connection.execute(
            f"SELECT ts_code,{key_date} FROM {delta_relation} WHERE {invalid} LIMIT {len(codes)}"
        ).fetchall()
    )
    return IndexPeriodFileCheck(
        file_count,
        source_row_count,
        {
            "schema": int(not index_period_schema_matches(connection, relation, layer)),
            "file_row_count": int(file_count != expected_file_row_count),
            "source_row_count": int(count != source_row_count),
            "duplicate_key": count - unique_count,
            "code_or_date": invalid_count,
        },
        samples,
    )


def index_period_silver_check_spec(period):
    return dg.AssetCheckSpec(
        name=period.silver_check,
        asset=period.silver_asset,
        blocking=True,
        partitions_def=cn_a_index_week_ends
        if period == INDEX_WEEKLY
        else cn_a_index_months,
        description="校验所选周／月的标准行情写入符合保存契约。",
        metadata=build_check_metadata(check_scope=CheckScope.SCHEMA),
    )


def index_period_silver_check_result(
    period, result, *, path, partition_key, period_end
):
    return index_period_check_result(
        period,
        result,
        layer="silver",
        path=path,
        partition_key=partition_key,
        period_end=period_end,
    )


def index_period_raw_check_spec(period) -> dg.AssetCheckSpec:
    return dg.AssetCheckSpec(
        name=period.raw_check,
        asset=period.raw_asset,
        blocking=True,
        partitions_def=cn_a_index_week_ends
        if period == INDEX_WEEKLY
        else cn_a_index_months,
        description="校验所选周／月的原始行情写入符合保存契约。",
        metadata=build_check_metadata(check_scope=CheckScope.SCHEMA),
    )


def index_period_raw_check_result(period, result, *, path, partition_key, period_end):
    return index_period_check_result(
        period,
        result,
        layer="raw",
        path=path,
        partition_key=partition_key,
        period_end=period_end,
    )


def index_period_check_result(
    period, result, *, layer, path, partition_key, period_end
):
    return dg.AssetCheckResult(
        asset_key=getattr(period, layer + "_asset"),
        check_name=getattr(period, layer + "_check"),
        passed=result.passed,
        severity=dg.AssetCheckSeverity.ERROR,
        metadata=build_check_metadata(
            check_scope=CheckScope.SCHEMA,
            file_path=path,
            checked_row_count=result.source_row_count,
            failed_row_count=sum(result.failure_counts.values()),
            extra_metadata={
                "partition_key": partition_key,
                "period_end": period_end.isoformat(),
                "frequency": period.frequency,
                "file_row_count": result.file_row_count,
                "failure_counts": result.failure_counts,
                "failure_samples": list(result.failure_samples),
            },
        ),
    )
