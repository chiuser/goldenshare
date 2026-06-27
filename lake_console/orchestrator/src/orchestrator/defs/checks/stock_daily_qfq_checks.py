from collections.abc import Sequence
from pathlib import Path
from typing import Any

import dagster as dg

from orchestrator.defs.assets.adj_factor import silver_adj_factor
from orchestrator.defs.assets.stock_daily import silver_stock_daily
from orchestrator.defs.assets.stock_daily_qfq import gold_stock_daily_qfq
from orchestrator.defs.duckdb_sql import (
    count_parquet_query,
    describe_parquet_query,
    read_parquet,
)
from orchestrator.defs.paths import (
    gold_stock_daily_qfq_path,
    silver_adj_factor_path,
    silver_stock_daily_path,
)
from orchestrator.defs.partitions import cn_a_stock_trade_days
from orchestrator.defs.resources import DuckDBResource, LakeRootResource
from orchestrator.defs.run_contracts.metadata import CheckScope, build_check_metadata
from orchestrator.defs.stock_daily_qfq import (
    GOLD_STOCK_DAILY_QFQ_COLUMNS,
    build_stock_daily_qfq_coverage_sql,
    build_stock_daily_qfq_select_sql,
    load_stock_daily_qfq_previous_lookup_trade_dates,
)


GOLD_STOCK_DAILY_QFQ_CHECK_NAMES = (
    "gold_stock_daily_qfq_contract_check",
    "gold_stock_daily_qfq_qfq_semantics_check",
)
GOLD_STOCK_DAILY_QFQ_PRICE_TOLERANCE = 1e-6


def _sample_dicts(
    columns: Sequence[str],
    rows: Sequence[Sequence[Any]],
) -> list[dict[str, Any]]:
    samples = []
    for row in rows:
        sample = {}
        for column, value in zip(columns, row, strict=True):
            sample[column] = value.isoformat() if hasattr(value, "isoformat") else value
        samples.append(sample)
    return samples


def _missing_file_result(path: Path, *, check_scope: CheckScope) -> dg.AssetCheckResult:
    return dg.AssetCheckResult(
        passed=False,
        metadata=build_check_metadata(
            check_scope=check_scope,
            file_path=path,
            missing_file_paths=[path],
            extra_metadata={
                "summary": "股票日线前复权检查失败：必需文件不存在。",
                "next_action": "先生成缺失文件，再重新运行 gold_stock_daily_qfq 或对应 check。",
                "failed_rule_names": ["file_exists"],
            },
        ),
    )


def _column_names(connection, path: Path) -> list[str]:
    rows = connection.execute(
        describe_parquet_query(path, hive_partitioning=False)
    ).fetchall()
    return [str(row[0]) for row in rows]


def _row_count(connection, path: Path) -> int:
    return int(
        connection.execute(
            count_parquet_query(path, hive_partitioning=False)
        ).fetchone()[0]
    )


def _contract_rule_counts(
    connection,
    path: Path,
    partition_key: str,
) -> dict[str, int]:
    row = connection.execute(
        f"""
        WITH rows AS (
          SELECT
            CAST(ts_code AS VARCHAR) AS ts_code,
            CAST(trade_date AS DATE) AS trade_date
          FROM {read_parquet(path, hive_partitioning=False)}
        ),
        duplicate_keys AS (
          SELECT ts_code, trade_date
          FROM rows
          GROUP BY ts_code, trade_date
          HAVING count(*) > 1
        )
        SELECT
          count(*) FILTER (WHERE trade_date IS NULL OR trade_date != DATE '{partition_key}')
            AS partition_date_mismatch_count,
          count(*) FILTER (WHERE ts_code IS NULL OR trim(ts_code) = '' OR trade_date IS NULL)
            AS null_key_count,
          (SELECT count(*) FROM duplicate_keys) AS duplicate_key_count
        FROM rows
        """
    ).fetchone()
    return {
        "partition_date_mismatch_count": int(row[0]),
        "null_key_count": int(row[1]),
        "duplicate_key_count": int(row[2]),
    }


def _contract_failure_samples(
    connection,
    path: Path,
    partition_key: str,
) -> list[dict[str, Any]]:
    rows = connection.execute(
        f"""
        WITH rows AS (
          SELECT
            CAST(ts_code AS VARCHAR) AS ts_code,
            CAST(trade_date AS DATE) AS trade_date
          FROM {read_parquet(path, hive_partitioning=False)}
        ),
        duplicate_keys AS (
          SELECT ts_code, trade_date
          FROM rows
          GROUP BY ts_code, trade_date
          HAVING count(*) > 1
        )
        SELECT rows.ts_code, rows.trade_date
        FROM rows
        LEFT JOIN duplicate_keys
          ON rows.ts_code = duplicate_keys.ts_code
         AND rows.trade_date = duplicate_keys.trade_date
        WHERE rows.trade_date IS NULL
           OR rows.trade_date != DATE '{partition_key}'
           OR rows.ts_code IS NULL
           OR trim(rows.ts_code) = ''
           OR duplicate_keys.ts_code IS NOT NULL
        ORDER BY rows.ts_code, rows.trade_date
        LIMIT 10
        """
    ).fetchall()
    return _sample_dicts(("ts_code", "trade_date"), rows)


@dg.asset_check(
    asset=gold_stock_daily_qfq,
    partitions_def=cn_a_stock_trade_days,
    blocking=True,
)
def gold_stock_daily_qfq_contract_check(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    partition_key = context.partition_key
    path = gold_stock_daily_qfq_path(lake_root.root(), partition_key)
    if not path.exists():
        return _missing_file_result(path, check_scope=CheckScope.FILE_EXISTS)

    expected_columns = tuple(GOLD_STOCK_DAILY_QFQ_COLUMNS)
    connect_duckdb = duckdb.connect
    connection_context = connect_duckdb()
    with connection_context as connection:
        observed_columns = tuple(_column_names(connection, path))
        row_count = _row_count(connection, path)
        failed_rule_names = []
        if row_count <= 0:
            failed_rule_names.append("row_count_positive")
        if observed_columns != expected_columns:
            failed_rule_names.append("schema_matches_contract")
            rule_counts = {
                "partition_date_mismatch_count": 0,
                "null_key_count": 0,
                "duplicate_key_count": 0,
            }
            samples: list[dict[str, Any]] = []
        else:
            rule_counts = _contract_rule_counts(connection, path, partition_key)
            if rule_counts["partition_date_mismatch_count"]:
                failed_rule_names.append("partition_date_matches")
            if rule_counts["null_key_count"]:
                failed_rule_names.append("key_columns_non_null")
            if rule_counts["duplicate_key_count"]:
                failed_rule_names.append("unique_ts_code_trade_date")
            samples = _contract_failure_samples(connection, path, partition_key)

    return dg.AssetCheckResult(
        passed=not failed_rule_names,
        metadata=build_check_metadata(
            check_scope=CheckScope.SCHEMA,
            checked_row_count=row_count,
            failed_row_count=(
                rule_counts["partition_date_mismatch_count"]
                + rule_counts["null_key_count"]
                + rule_counts["duplicate_key_count"]
            ),
            file_path=path,
            extra_metadata={
                "summary": (
                    "股票日线前复权 contract check 通过。"
                    if not failed_rule_names
                    else "股票日线前复权 contract check 失败，先看 failed_rule_names。"
                ),
                "next_action": (
                    "无需处理，等待 qfq semantics check。"
                    if not failed_rule_names
                    else "检查目标 Parquet 的 schema、partition date 和主键唯一性，再重跑 asset/check。"
                ),
                "partition_key": partition_key,
                "observed_columns": list(observed_columns),
                "expected_columns": list(expected_columns),
                "failed_rule_names": failed_rule_names,
                **rule_counts,
                "sample_rows": samples,
            },
        ),
    )


@dg.asset_check(
    asset=gold_stock_daily_qfq,
    partitions_def=cn_a_stock_trade_days,
    additional_deps=[silver_stock_daily, silver_adj_factor],
    blocking=True,
)
def gold_stock_daily_qfq_qfq_semantics_check(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    partition_key = context.partition_key
    root = lake_root.root()
    qfq_path = gold_stock_daily_qfq_path(root, partition_key)
    stock_daily_path = silver_stock_daily_path(root, partition_key)
    adj_factor_path = silver_adj_factor_path(root, partition_key)
    for path in (qfq_path, stock_daily_path, adj_factor_path):
        if not path.exists():
            return _missing_file_result(path, check_scope=CheckScope.RECONCILIATION)

    connect_duckdb = duckdb.connect
    connection_context = connect_duckdb()
    with connection_context as connection:
        previous_lookup_trade_dates = load_stock_daily_qfq_previous_lookup_trade_dates(
            connection=connection,
            lake_root=root,
            trade_date=partition_key,
        )
        previous_stock_daily_paths = tuple(
            path
            for path in (
                silver_stock_daily_path(root, trade_date)
                for trade_date in previous_lookup_trade_dates
            )
            if path.exists()
        )
        previous_adj_factor_paths = tuple(
            path
            for path in (
                silver_adj_factor_path(root, trade_date)
                for trade_date in previous_lookup_trade_dates
            )
            if path.exists()
        )
        coverage = _coverage_counts(
            connection=connection,
            stock_daily_path=stock_daily_path,
            adj_factor_path=adj_factor_path,
            previous_stock_daily_paths=previous_stock_daily_paths,
            previous_adj_factor_paths=previous_adj_factor_paths,
            trade_date=partition_key,
        )
        comparison = _qfq_comparison_counts(
            connection=connection,
            qfq_path=qfq_path,
            stock_daily_path=stock_daily_path,
            adj_factor_path=adj_factor_path,
            previous_stock_daily_paths=previous_stock_daily_paths,
            previous_adj_factor_paths=previous_adj_factor_paths,
            trade_date=partition_key,
        )
        samples = _qfq_failure_samples(
            connection=connection,
            qfq_path=qfq_path,
            stock_daily_path=stock_daily_path,
            adj_factor_path=adj_factor_path,
            previous_stock_daily_paths=previous_stock_daily_paths,
            previous_adj_factor_paths=previous_adj_factor_paths,
            trade_date=partition_key,
        )

    failed_rule_names = []
    if coverage["source_row_count"] <= 0:
        failed_rule_names.append("source_row_count_positive")
    if coverage["missing_trade_factor_count"]:
        failed_rule_names.append("trade_adj_factor_covered")
    if coverage["missing_as_of_factor_count"]:
        failed_rule_names.append("as_of_adj_factor_covered")
    if coverage["missing_previous_factor_count"]:
        failed_rule_names.append("previous_adj_factor_covered")
    if comparison["target_row_count"] != coverage["source_row_count"]:
        failed_rule_names.append("target_row_count_matches_source")
    if comparison["missing_target_row_count"] or comparison["unexpected_target_row_count"]:
        failed_rule_names.append("target_keys_match_expected")
    if comparison["formula_mismatch_count"]:
        failed_rule_names.append("qfq_formula_matches_source_and_factor")
    if comparison["price_domain_failed_count"]:
        failed_rule_names.append("price_domain_valid")

    return dg.AssetCheckResult(
        passed=not failed_rule_names,
        metadata=build_check_metadata(
            check_scope=CheckScope.RECONCILIATION,
            checked_row_count=comparison["target_row_count"],
            failed_row_count=(
                comparison["missing_target_row_count"]
                + comparison["unexpected_target_row_count"]
                + comparison["formula_mismatch_count"]
                + comparison["price_domain_failed_count"]
                + coverage["missing_trade_factor_count"]
                + coverage["missing_as_of_factor_count"]
                + coverage["missing_previous_factor_count"]
            ),
            file_path=qfq_path,
            input_file_paths=[stock_daily_path, adj_factor_path],
            extra_metadata={
                "summary": (
                    "股票日线前复权 qfq semantics check 通过。"
                    if not failed_rule_names
                    else "股票日线前复权 qfq semantics check 失败，先看 failed_rule_names。"
                ),
                "next_action": (
                    "无需处理，后续 sensor/readiness 可消费该分区。"
                    if not failed_rule_names
                    else "检查 silver_stock_daily、silver_adj_factor 和 qfq 公式输出；修复后重跑 gold_stock_daily_qfq。"
                ),
                "partition_key": partition_key,
                "previous_lookup_trade_date_count": len(previous_lookup_trade_dates),
                "previous_stock_daily_file_count": len(previous_stock_daily_paths),
                "previous_adj_factor_file_count": len(previous_adj_factor_paths),
                "failed_rule_names": failed_rule_names,
                "price_tolerance": GOLD_STOCK_DAILY_QFQ_PRICE_TOLERANCE,
                **coverage,
                **comparison,
                "sample_rows": samples,
            },
        ),
    )


def _coverage_counts(
    *,
    connection,
    stock_daily_path: Path,
    adj_factor_path: Path,
    previous_stock_daily_paths: Sequence[Path],
    previous_adj_factor_paths: Sequence[Path],
    trade_date: str,
) -> dict[str, int]:
    row = connection.execute(
        build_stock_daily_qfq_coverage_sql(
            stock_daily_path=stock_daily_path,
            trade_adj_factor_path=adj_factor_path,
            previous_stock_daily_paths=previous_stock_daily_paths,
            previous_adj_factor_paths=previous_adj_factor_paths,
            as_of_adj_factor_path=adj_factor_path,
            trade_date=trade_date,
            as_of_trade_date=trade_date,
        )
    ).fetchone()
    return {
        "source_row_count": int(row[0]),
        "expected_output_row_count": int(row[1]),
        "missing_trade_factor_count": int(row[2]),
        "missing_as_of_factor_count": int(row[3]),
        "allowed_missing_previous_row_count": int(row[4]),
        "missing_previous_factor_count": int(row[5]),
    }


def _qfq_comparison_counts(
    *,
    connection,
    qfq_path: Path,
    stock_daily_path: Path,
    adj_factor_path: Path,
    previous_stock_daily_paths: Sequence[Path],
    previous_adj_factor_paths: Sequence[Path],
    trade_date: str,
) -> dict[str, int]:
    expected_sql = build_stock_daily_qfq_select_sql(
        stock_daily_path=stock_daily_path,
        trade_adj_factor_path=adj_factor_path,
        previous_stock_daily_paths=previous_stock_daily_paths,
        previous_adj_factor_paths=previous_adj_factor_paths,
        as_of_adj_factor_path=adj_factor_path,
        trade_date=trade_date,
        as_of_trade_date=trade_date,
    )
    tolerance = GOLD_STOCK_DAILY_QFQ_PRICE_TOLERANCE
    row = connection.execute(
        f"""
        WITH expected_rows AS (
          {expected_sql}
        ),
        target_rows AS (
          SELECT
            CAST(ts_code AS VARCHAR) AS ts_code,
            CAST(trade_date AS DATE) AS trade_date,
            CAST(open AS DOUBLE) AS open,
            CAST(high AS DOUBLE) AS high,
            CAST(low AS DOUBLE) AS low,
            CAST(close AS DOUBLE) AS close,
            CAST(pre_close AS DOUBLE) AS pre_close,
            CAST(change_amount AS DOUBLE) AS change_amount,
            CAST(pct_chg AS DOUBLE) AS pct_chg,
            CAST(vol AS DOUBLE) AS vol,
            CAST(amount AS DOUBLE) AS amount
          FROM {read_parquet(qfq_path, hive_partitioning=False)}
        ),
        joined_rows AS (
          SELECT
            coalesce(target_rows.ts_code, expected_rows.ts_code) AS ts_code,
            coalesce(target_rows.trade_date, expected_rows.trade_date) AS trade_date,
            target_rows.ts_code IS NULL AS missing_target,
            expected_rows.ts_code IS NULL AS unexpected_target,
            target_rows.open AS target_open,
            target_rows.high AS target_high,
            target_rows.low AS target_low,
            target_rows.close AS target_close,
            target_rows.pre_close AS target_pre_close,
            target_rows.change_amount AS target_change_amount,
            target_rows.pct_chg AS target_pct_chg,
            target_rows.vol AS target_vol,
            target_rows.amount AS target_amount,
            expected_rows.open AS expected_open,
            expected_rows.high AS expected_high,
            expected_rows.low AS expected_low,
            expected_rows.close AS expected_close,
            expected_rows.pre_close AS expected_pre_close,
            expected_rows.change_amount AS expected_change_amount,
            expected_rows.pct_chg AS expected_pct_chg,
            expected_rows.vol AS expected_vol,
            expected_rows.amount AS expected_amount
          FROM target_rows
          FULL OUTER JOIN expected_rows
            ON target_rows.ts_code = expected_rows.ts_code
           AND target_rows.trade_date = expected_rows.trade_date
        )
        SELECT
          (SELECT count(*) FROM target_rows) AS target_row_count,
          (SELECT count(*) FROM expected_rows) AS expected_row_count,
          count(*) FILTER (WHERE missing_target) AS missing_target_row_count,
          count(*) FILTER (WHERE unexpected_target) AS unexpected_target_row_count,
          count(*) FILTER (
            WHERE NOT missing_target
              AND NOT unexpected_target
              AND (
                abs(target_open - expected_open) > {tolerance}
                OR abs(target_high - expected_high) > {tolerance}
                OR abs(target_low - expected_low) > {tolerance}
                OR abs(target_close - expected_close) > {tolerance}
                OR abs(target_pre_close - expected_pre_close) > {tolerance}
                OR abs(target_change_amount - expected_change_amount) > {tolerance}
                OR abs(target_pct_chg - expected_pct_chg) > {tolerance}
              )
          ) AS formula_mismatch_count,
          count(*) FILTER (
            WHERE NOT missing_target
              AND (
                target_open <= 0
                OR target_high <= 0
                OR target_low <= 0
                OR target_close <= 0
                OR target_pre_close < 0
                OR target_vol < 0
                OR target_amount < 0
                OR target_high < greatest(target_open, target_close, target_low)
                OR target_low > least(target_open, target_close, target_high)
              )
          ) AS price_domain_failed_count
        FROM joined_rows
        """
    ).fetchone()
    return {
        "target_row_count": int(row[0]),
        "expected_row_count": int(row[1]),
        "missing_target_row_count": int(row[2]),
        "unexpected_target_row_count": int(row[3]),
        "formula_mismatch_count": int(row[4]),
        "price_domain_failed_count": int(row[5]),
    }


def _qfq_failure_samples(
    *,
    connection,
    qfq_path: Path,
    stock_daily_path: Path,
    adj_factor_path: Path,
    previous_stock_daily_paths: Sequence[Path],
    previous_adj_factor_paths: Sequence[Path],
    trade_date: str,
) -> list[dict[str, Any]]:
    expected_sql = build_stock_daily_qfq_select_sql(
        stock_daily_path=stock_daily_path,
        trade_adj_factor_path=adj_factor_path,
        previous_stock_daily_paths=previous_stock_daily_paths,
        previous_adj_factor_paths=previous_adj_factor_paths,
        as_of_adj_factor_path=adj_factor_path,
        trade_date=trade_date,
        as_of_trade_date=trade_date,
    )
    tolerance = GOLD_STOCK_DAILY_QFQ_PRICE_TOLERANCE
    rows = connection.execute(
        f"""
        WITH expected_rows AS (
          {expected_sql}
        ),
        target_rows AS (
          SELECT
            CAST(ts_code AS VARCHAR) AS ts_code,
            CAST(trade_date AS DATE) AS trade_date,
            CAST(open AS DOUBLE) AS open,
            CAST(high AS DOUBLE) AS high,
            CAST(low AS DOUBLE) AS low,
            CAST(close AS DOUBLE) AS close,
            CAST(pre_close AS DOUBLE) AS pre_close,
            CAST(change_amount AS DOUBLE) AS change_amount,
            CAST(pct_chg AS DOUBLE) AS pct_chg
          FROM {read_parquet(qfq_path, hive_partitioning=False)}
        )
        SELECT
          coalesce(target_rows.ts_code, expected_rows.ts_code) AS ts_code,
          coalesce(target_rows.trade_date, expected_rows.trade_date) AS trade_date,
          target_rows.close AS target_close,
          expected_rows.close AS expected_close,
          target_rows.pre_close AS target_pre_close,
          expected_rows.pre_close AS expected_pre_close,
          target_rows.change_amount AS target_change_amount,
          expected_rows.change_amount AS expected_change_amount,
          target_rows.pct_chg AS target_pct_chg,
          expected_rows.pct_chg AS expected_pct_chg
        FROM target_rows
        FULL OUTER JOIN expected_rows
          ON target_rows.ts_code = expected_rows.ts_code
         AND target_rows.trade_date = expected_rows.trade_date
        WHERE target_rows.ts_code IS NULL
           OR expected_rows.ts_code IS NULL
           OR abs(target_rows.open - expected_rows.open) > {tolerance}
           OR abs(target_rows.high - expected_rows.high) > {tolerance}
           OR abs(target_rows.low - expected_rows.low) > {tolerance}
           OR abs(target_rows.close - expected_rows.close) > {tolerance}
           OR abs(target_rows.pre_close - expected_rows.pre_close) > {tolerance}
           OR abs(target_rows.change_amount - expected_rows.change_amount) > {tolerance}
           OR abs(target_rows.pct_chg - expected_rows.pct_chg) > {tolerance}
        ORDER BY ts_code, trade_date
        LIMIT 10
        """
    ).fetchall()
    return _sample_dicts(
        (
            "ts_code",
            "trade_date",
            "target_close",
            "expected_close",
            "target_pre_close",
            "expected_pre_close",
            "target_change_amount",
            "expected_change_amount",
            "target_pct_chg",
            "expected_pct_chg",
        ),
        rows,
    )
