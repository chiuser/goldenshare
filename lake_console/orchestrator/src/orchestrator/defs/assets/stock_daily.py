import os
from pathlib import Path
from typing import Any

import dagster as dg

from orchestrator.defs.asset_guards.stock_daily import (
    assert_silver_stock_basic_fresh_for_stock_daily,
)
from orchestrator.defs.duckdb_connection import connect_configured_duckdb
from orchestrator.defs.assets.stock_basic import silver_stock_basic
from orchestrator.defs.assets.stock_lifecycle import silver_stock_lifecycle
from orchestrator.defs.assets.suspend_d import silver_stock_suspend_daily
from orchestrator.defs.duckdb_sql import (
    BJ_MARKET_OPEN_DATE,
    STOCK_DAILY_RAW_REQUIRED_COLUMNS,
    STOCK_DAILY_MIN_TRADE_DATE,
    copy_query_to_parquet,
    count_parquet_query,
    describe_parquet_query,
    silver_cny_stock_lifecycle_select,
    silver_stock_daily_select,
    stock_daily_normalized_select,
)
from orchestrator.defs.partitions import cn_a_stock_trade_days
from orchestrator.defs.paths import (
    PATH_TEMPLATE_LAKE_ROOT,
    PATH_TEMPLATE_PARTITION_KEY,
    lake_path_template,
    raw_stock_daily_path,
    silver_stock_basic_path,
    silver_stock_daily_path,
    silver_stock_lifecycle_path,
    silver_stock_suspend_daily_path,
)
from orchestrator.defs.resources import (
    DuckDBResource,
    LakeRootResource,
    TushareResource,
)
from orchestrator.defs.run_contracts.asset_tags import (
    AssetLayer,
    DataDomain,
    build_asset_tags,
)
from orchestrator.defs.run_contracts.asset_column_schemas import (
    RAW_TUSHARE_STOCK_DAILY_SCHEMA,
    SILVER_STOCK_DAILY_SCHEMA,
)
from orchestrator.defs.run_contracts.metadata import (
    SourceSystem,
    build_asset_definition_metadata,
    build_materialization_metadata,
)
from orchestrator.defs.run_contracts.configs import (
    STOCK_DAILY_RAW_CONFIG_SCHEMA,
    parse_stock_daily_raw_config,
)
from orchestrator.defs.tushare_api_io import (
    fetch_tushare_partition_to_raw,
    fetch_tushare_stock_daily_missing_codes_to_raw,
)
from orchestrator.utils.dg_log_helper import DgStdoutLogger


STOCK_DAILY_COLUMNS = tuple(column.name for column in SILVER_STOCK_DAILY_SCHEMA)

STOCK_DAILY_RAW_COLUMN_TYPES = {
    column.name: column.type for column in RAW_TUSHARE_STOCK_DAILY_SCHEMA
}


def _column_names(
    connection, path: Path, *, hive_partitioning: bool = False
) -> list[str]:
    rows = connection.execute(
        describe_parquet_query(path, hive_partitioning=hive_partitioning)
    ).fetchall()
    return [row[0] for row in rows]


def _row_count(connection, path: Path, *, hive_partitioning: bool = False) -> int:
    return int(
        connection.execute(
            count_parquet_query(path, hive_partitioning=hive_partitioning)
        ).fetchone()[0]
    )


def _sample_dicts(
    columns: list[str], rows: list[tuple[Any, ...]]
) -> list[dict[str, Any]]:
    samples = []
    for row in rows:
        sample = {}
        for column, value in zip(columns, row, strict=True):
            sample[column] = value.isoformat() if hasattr(value, "isoformat") else value
        samples.append(sample)
    return samples


def _human_materialization_metadata(
    *,
    summary: str,
    next_action: str,
    result_status: str,
    input_summary: dict[str, Any] | None = None,
    filter_summary: dict[str, Any] | None = None,
    diagnostic_ref: str,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "goldenshare/summary": summary,
        "goldenshare/next_action": next_action,
        "goldenshare/result_status": result_status,
        "goldenshare/diagnostic_ref": diagnostic_ref,
    }
    if input_summary:
        metadata["goldenshare/input_summary"] = input_summary
    if filter_summary:
        metadata["goldenshare/filter_summary"] = filter_summary
    return metadata


def _conflict_key_count(connection, raw_path: Path) -> int:
    normalized_sql = stock_daily_normalized_select(raw_path)
    return int(
        connection.execute(
            f"""
            WITH distinct_rows AS (
              SELECT DISTINCT *
              FROM ({normalized_sql}) normalized
            )
            SELECT count(*) AS conflict_key_count
            FROM (
              SELECT ts_code, trade_date
              FROM distinct_rows
              GROUP BY ts_code, trade_date
              HAVING count(*) > 1
            ) conflict_keys
            """
        ).fetchone()[0]
    )


def _conflict_sample_keys(connection, raw_path: Path) -> list[dict[str, Any]]:
    normalized_sql = stock_daily_normalized_select(raw_path)
    rows = connection.execute(
        f"""
        WITH distinct_rows AS (
          SELECT DISTINCT *
          FROM ({normalized_sql}) normalized
        )
        SELECT ts_code, trade_date, count(*) AS version_count
        FROM distinct_rows
        GROUP BY ts_code, trade_date
        HAVING count(*) > 1
        ORDER BY ts_code, trade_date
        LIMIT 10
        """
    ).fetchall()
    return _sample_dicts(["ts_code", "trade_date", "version_count"], rows)


def _conflict_sample_rows(connection, raw_path: Path) -> list[dict[str, Any]]:
    normalized_sql = stock_daily_normalized_select(raw_path)
    rows = connection.execute(
        f"""
        WITH distinct_rows AS (
          SELECT DISTINCT *
          FROM ({normalized_sql}) normalized
        ),
        conflict_keys AS (
          SELECT ts_code, trade_date
          FROM distinct_rows
          GROUP BY ts_code, trade_date
          HAVING count(*) > 1
        )
        SELECT
          distinct_rows.ts_code,
          distinct_rows.trade_date,
          distinct_rows.open,
          distinct_rows.high,
          distinct_rows.low,
          distinct_rows.close,
          distinct_rows.pre_close,
          distinct_rows.change_amount,
          distinct_rows.pct_chg,
          distinct_rows.vol,
          distinct_rows.amount
        FROM distinct_rows
        INNER JOIN conflict_keys
          ON distinct_rows.ts_code = conflict_keys.ts_code
         AND distinct_rows.trade_date = conflict_keys.trade_date
        ORDER BY distinct_rows.ts_code, distinct_rows.trade_date
        LIMIT 20
        """
    ).fetchall()
    return _sample_dicts(STOCK_DAILY_COLUMNS, rows)


def _duplicate_removed_count(connection, raw_path: Path) -> int:
    normalized_sql = stock_daily_normalized_select(raw_path)
    row = connection.execute(
        f"""
        WITH normalized AS (
          {normalized_sql}
        ),
        deduped AS (
          SELECT DISTINCT *
          FROM normalized
        )
        SELECT
          (SELECT count(*) FROM normalized) - (SELECT count(*) FROM deduped)
            AS duplicate_removed_count
        """
    ).fetchone()
    return int(row[0])


def _duplicate_key_count(connection, raw_path: Path) -> int:
    normalized_sql = stock_daily_normalized_select(raw_path)
    row = connection.execute(
        f"""
        WITH normalized AS (
          {normalized_sql}
        ),
        raw_key_counts AS (
          SELECT ts_code, trade_date, count(*) AS raw_row_count
          FROM normalized
          GROUP BY ts_code, trade_date
        ),
        deduped_key_counts AS (
          SELECT ts_code, trade_date, count(*) AS deduped_row_count
          FROM (
            SELECT DISTINCT *
            FROM normalized
          ) deduped
          GROUP BY ts_code, trade_date
        )
        SELECT count(*) AS duplicate_key_count
        FROM raw_key_counts
        INNER JOIN deduped_key_counts
          ON raw_key_counts.ts_code = deduped_key_counts.ts_code
         AND raw_key_counts.trade_date = deduped_key_counts.trade_date
        WHERE raw_key_counts.raw_row_count > deduped_key_counts.deduped_row_count
        """
    ).fetchone()
    return int(row[0])


def _duplicate_sample_rows(connection, raw_path: Path) -> list[dict[str, Any]]:
    normalized_sql = stock_daily_normalized_select(raw_path)
    rows = connection.execute(
        f"""
        WITH normalized AS (
          {normalized_sql}
        )
        SELECT
          ts_code,
          trade_date,
          open,
          high,
          low,
          close,
          pre_close,
          change_amount,
          pct_chg,
          vol,
          amount,
          count(*) AS duplicate_row_count
        FROM normalized
        GROUP BY
          ts_code,
          trade_date,
          open,
          high,
          low,
          close,
          pre_close,
          change_amount,
          pct_chg,
          vol,
          amount
        HAVING count(*) > 1
        ORDER BY ts_code, trade_date
        LIMIT 10
        """
    ).fetchall()
    return _sample_dicts([*STOCK_DAILY_COLUMNS, "duplicate_row_count"], rows)


def _silver_filter_counts(
    connection,
    raw_path: Path,
    stock_lifecycle_path: Path,
) -> dict[str, int]:
    normalized_sql = stock_daily_normalized_select(raw_path)
    row = connection.execute(
        f"""
        WITH normalized AS (
          {normalized_sql}
        ),
        deduped AS (
          SELECT DISTINCT *
          FROM normalized
        ),
        stock_lifecycle AS (
          {silver_cny_stock_lifecycle_select(stock_lifecycle_path)}
        ),
        after_lifecycle_code_match AS (
          SELECT deduped.*, stock_lifecycle.list_date, stock_lifecycle.delist_date
          FROM deduped
          INNER JOIN stock_lifecycle USING (ts_code)
        ),
        after_min_trade_date AS (
          SELECT *
          FROM after_lifecycle_code_match
          WHERE trade_date >= DATE '{STOCK_DAILY_MIN_TRADE_DATE}'
        ),
        after_list_date AS (
          SELECT *
          FROM after_min_trade_date
          WHERE trade_date >= list_date
        ),
        after_delist_date AS (
          SELECT *
          FROM after_list_date
          WHERE delist_date IS NULL
             OR trade_date <= delist_date
        ),
        after_bj_market_open_date AS (
          SELECT *
          FROM after_delist_date
          WHERE NOT ends_with(ts_code, '.BJ')
             OR trade_date >= DATE '{BJ_MARKET_OPEN_DATE}'
        )
        SELECT
          (SELECT count(*) FROM normalized) AS raw_normalized_row_count,
          (SELECT count(*) FROM deduped) AS deduped_row_count,
          (SELECT count(*) FROM after_lifecycle_code_match) AS after_lifecycle_code_match_count,
          (SELECT count(*) FROM after_min_trade_date) AS after_min_trade_date_count,
          (SELECT count(*) FROM after_list_date) AS after_list_date_count,
          (SELECT count(*) FROM after_delist_date) AS after_delist_date_count,
          (SELECT count(*) FROM after_bj_market_open_date) AS final_silver_row_count
        """
    ).fetchone()
    (
        raw_normalized_row_count,
        deduped_row_count,
        after_lifecycle_code_match_count,
        after_min_trade_date_count,
        after_list_date_count,
        after_delist_date_count,
        final_silver_row_count,
    ) = row
    return {
        "raw_normalized_row_count": int(raw_normalized_row_count),
        "deduped_row_count": int(deduped_row_count),
        "filtered_out_without_lifecycle_count": int(
            deduped_row_count - after_lifecycle_code_match_count
        ),
        "filtered_out_before_2014_count": int(
            after_lifecycle_code_match_count - after_min_trade_date_count
        ),
        "filtered_out_before_list_date_count": int(
            after_min_trade_date_count - after_list_date_count
        ),
        "filtered_out_after_delist_date_count": int(
            after_list_date_count - after_delist_date_count
        ),
        "filtered_out_bj_before_market_open_count": int(
            after_delist_date_count - final_silver_row_count
        ),
        "final_silver_row_count": int(final_silver_row_count),
    }


def _replace_parquet_from_query(connection, select_sql: str, target_path: Path) -> None:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = target_path.with_name(f"{target_path.name}.tmp")
    if temporary_path.exists():
        temporary_path.unlink()

    connection.execute(copy_query_to_parquet(select_sql, temporary_path))
    os.replace(temporary_path, target_path)


@dg.asset(
    name="raw_tushare_stock_daily",
    partitions_def=cn_a_stock_trade_days,
    config_schema=STOCK_DAILY_RAW_CONFIG_SCHEMA,
    group_name="quote",
    tags=build_asset_tags(layer=AssetLayer.RAW, data_domain=DataDomain.QUOTE_DATA),
    metadata=build_asset_definition_metadata(
        dataset_id="daily",
        source_system=SourceSystem.TUSHARE,
        source_api="daily",
        source_category_path="股票数据 / 行情数据",
        source_doc="docs/sources/tushare/股票数据/行情数据/0027_A股日线行情.md",
        data_contract="source_mirror",
        column_schema=RAW_TUSHARE_STOCK_DAILY_SCHEMA,
        path_template=lake_path_template(
            raw_stock_daily_path(PATH_TEMPLATE_LAKE_ROOT, PATH_TEMPLATE_PARTITION_KEY)
        ),
        extra_metadata={
            "raw_contract": (
                "Tushare daily source mirror: trade_date YYYYMMDD string, field name change."
            ),
            "write_summary": (
                "Tushare API rows written to raw parquet with explicit source contract fields."
            ),
        },
    ),
    description="Tushare 股票日线 raw 源镜像，按交易日保存 A 股日线行情，供股票日线 silver 标准化使用。",
)
def raw_tushare_stock_daily(
    context: dg.AssetExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
    tushare: TushareResource,
) -> dg.MaterializeResult:
    lake_root.ensure_available_for_run()
    partition_key = context.partition_key
    target_path = raw_stock_daily_path(lake_root.root(), partition_key)
    config = parse_stock_daily_raw_config(context.op_config)
    log = DgStdoutLogger("stock_daily")
    if config.write_mode == "missing_code_repair":
        if config.missing_code_repair is None:
            raise AssertionError("missing_code_repair config is required.")
        log.stdout(
            "raw_stock_daily_repair_started",
            partition_key=partition_key,
            requested_code_count=len(config.missing_code_repair.ts_codes),
            repair_attempt=config.missing_code_repair.repair_attempt,
        )
        metadata = fetch_tushare_stock_daily_missing_codes_to_raw(
            tushare=tushare,
            duckdb=duckdb,
            ts_codes=config.missing_code_repair.ts_codes,
            fields=STOCK_DAILY_RAW_REQUIRED_COLUMNS,
            column_types=STOCK_DAILY_RAW_COLUMN_TYPES,
            target_path=target_path,
            partition_key=partition_key,
            missing_codes_hash=config.missing_code_repair.missing_codes_hash,
            repair_attempt=config.missing_code_repair.repair_attempt,
        )
        metadata.update(
            _human_materialization_metadata(
                summary="已写入股票日线 raw missing-code repair 结果。",
                next_action="等待 raw blocking checks 全部通过；通过后 silver_stock_daily 才能消费。",
                result_status="written",
                input_summary={
                    "source": "Tushare daily",
                    "partition_key": partition_key,
                    "write_mode": "missing_code_repair",
                    "requested_code_count": len(config.missing_code_repair.ts_codes),
                    "repair_attempt": config.missing_code_repair.repair_attempt,
                    "target_path_exists": target_path.exists(),
                },
                diagnostic_ref="完整诊断看 raw stock daily checks、materialization metadata 和 run stdout。",
            )
        )
        log.stdout(
            "raw_stock_daily_repair_completed",
            partition_key=partition_key,
            output_row_count=metadata.get("dagster/row_count"),
            fetched_row_count=metadata.get("goldenshare/fetched_row_count"),
            repair_attempt=config.missing_code_repair.repair_attempt,
        )
    else:
        log.stdout(
            "raw_stock_daily_started",
            partition_key=partition_key,
            write_mode="replace",
        )
        metadata = fetch_tushare_partition_to_raw(
            tushare=tushare,
            duckdb=duckdb,
            api_name="daily",
            api_params={"trade_date": partition_key.replace("-", "")},
            fields=STOCK_DAILY_RAW_REQUIRED_COLUMNS,
            column_types=STOCK_DAILY_RAW_COLUMN_TYPES,
            target_path=target_path,
            partition_key=partition_key,
            allow_empty=False,
        )
        metadata.update(
            _human_materialization_metadata(
                summary="已写入股票日线 raw 源镜像分区。",
                next_action="等待 raw blocking checks 全部通过；通过后 silver_stock_daily 才能消费。",
                result_status="written",
                input_summary={
                    "source": "Tushare daily",
                    "partition_key": partition_key,
                    "write_mode": "replace",
                    "target_path_exists": target_path.exists(),
                },
                diagnostic_ref="完整诊断看 raw stock daily checks、materialization metadata 和 run stdout。",
            )
        )
        log.stdout(
            "raw_stock_daily_completed",
            partition_key=partition_key,
            output_row_count=metadata.get("dagster/row_count"),
            page_count=metadata.get("goldenshare/page_count"),
        )

    return dg.MaterializeResult(metadata=metadata)


@dg.asset(
    name="silver_stock_daily",
    deps=[
        raw_tushare_stock_daily,
        silver_stock_lifecycle,
        silver_stock_basic,
        silver_stock_suspend_daily,
    ],
    partitions_def=cn_a_stock_trade_days,
    group_name="quote",
    tags=build_asset_tags(layer=AssetLayer.SILVER, data_domain=DataDomain.QUOTE_DATA),
    metadata=build_asset_definition_metadata(
        dataset_id="daily",
        source_system=SourceSystem.DERIVED,
        data_contract="standardized_stock_daily_quote",
        column_schema=SILVER_STOCK_DAILY_SCHEMA,
        path_template=lake_path_template(
            silver_stock_daily_path(PATH_TEMPLATE_LAKE_ROOT, PATH_TEMPLATE_PARTITION_KEY)
        ),
        extra_metadata={
            "filter_policy": (
                "Keep CNY stocks whose trade_date falls within silver_stock_lifecycle "
                "list_date/delist_date lifecycle; keep rows on/after 2014-01-01; "
                "keep BJ stocks only on/after 2021-11-15; raw remains source mirror."
            ),
            "upstream_ready_policy": (
                "silver_stock_lifecycle, silver_stock_basic freshness guard, and "
                "silver_stock_suspend_daily partition must be ready before silver_stock_daily "
                "is produced; suspend facts are read-only prerequisites."
            ),
        },
    ),
    description="股票日线 silver 标准事实，按生命周期、币种、北交所开市日和停牌规则过滤，供分钟线、市场宽度和收益分布消费。",
)
def silver_stock_daily(
    context: dg.AssetExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.MaterializeResult:
    lake_root.ensure_available_for_run()
    partition_key = context.partition_key
    raw_path = raw_stock_daily_path(lake_root.root(), partition_key)
    stock_lifecycle_path = silver_stock_lifecycle_path(lake_root.root())
    basic_path = silver_stock_basic_path(lake_root.root())
    suspend_path = silver_stock_suspend_daily_path(lake_root.root(), partition_key)
    target_path = silver_stock_daily_path(lake_root.root(), partition_key)
    log = DgStdoutLogger("stock_daily")
    log.stdout(
        "silver_stock_daily_started",
        partition_key=partition_key,
        raw_exists=raw_path.exists(),
        lifecycle_exists=stock_lifecycle_path.exists(),
        basic_exists=basic_path.exists(),
        suspend_exists=suspend_path.exists(),
    )
    if not raw_path.exists():
        raise FileNotFoundError(f"Missing raw stock daily file: {raw_path}")
    if not stock_lifecycle_path.exists():
        raise FileNotFoundError(
            f"Missing silver stock lifecycle file: {stock_lifecycle_path}"
        )
    if not basic_path.exists():
        raise FileNotFoundError(f"Missing silver stock basic file: {basic_path}")
    if not suspend_path.exists():
        raise FileNotFoundError(f"Missing silver stock suspend file: {suspend_path}")

    assert_silver_stock_basic_fresh_for_stock_daily(context.instance, partition_key)

    with connect_configured_duckdb() as connection:
        conflict_key_count = _conflict_key_count(connection, raw_path)
        if conflict_key_count > 0:
            log.stdout(
                "silver_stock_daily_validation_failed",
                partition_key=partition_key,
                conflict_key_count=conflict_key_count,
            )
            raise dg.Failure(
                description=(
                    "Conflicting stock daily facts found for the same ts_code + trade_date."
                ),
                metadata=build_materialization_metadata(
                    extra_metadata={
                        **_human_materialization_metadata(
                            summary="未写入股票日线 silver：raw 中存在同一股票同一交易日的冲突行情事实。",
                            next_action="先修复 raw_tushare_stock_daily 的冲突 key，再重新触发 silver_stock_daily。",
                            result_status="failed_validation",
                            input_summary={
                                "source_asset": "raw_tushare_stock_daily",
                                "partition_key": partition_key,
                            },
                            diagnostic_ref="完整冲突样本看本次 Failure metadata；修复后等待下一次 silver run。",
                        ),
                        "raw_file_path": str(raw_path),
                        "partition_key": partition_key,
                        "conflict_key_count": conflict_key_count,
                        "conflict_sample_keys": _conflict_sample_keys(
                            connection, raw_path
                        ),
                        "conflict_sample_rows": _conflict_sample_rows(
                            connection, raw_path
                        ),
                    }
                ),
            )

        duplicate_removed_count = _duplicate_removed_count(connection, raw_path)
        duplicate_key_count = _duplicate_key_count(connection, raw_path)
        duplicate_sample_rows = _duplicate_sample_rows(connection, raw_path)
        filter_counts = _silver_filter_counts(connection, raw_path, stock_lifecycle_path)

        _replace_parquet_from_query(
            connection,
            silver_stock_daily_select(raw_path, stock_lifecycle_path),
            target_path,
        )
        columns = _column_names(connection, target_path, hive_partitioning=False)
        row_count = _row_count(connection, target_path, hive_partitioning=False)

    log.stdout(
        "silver_stock_daily_completed",
        partition_key=partition_key,
        output_row_count=row_count,
        raw_normalized_row_count=filter_counts["raw_normalized_row_count"],
        duplicate_removed_count=duplicate_removed_count,
    )
    return dg.MaterializeResult(
        metadata=build_materialization_metadata(
            uri=target_path,
            row_count=row_count,
            observed_columns=columns,
            extra_metadata={
                **_human_materialization_metadata(
                    summary="已写入股票日线 silver 标准事实分区。",
                    next_action="等待 silver blocking checks 全部通过；通过后分钟线、市场宽度和收益分布可以消费。",
                    result_status="written",
                    input_summary={
                        "source_asset": "raw_tushare_stock_daily",
                        "lifecycle_asset": "silver_stock_lifecycle",
                        "stock_basic_asset": "silver_stock_basic",
                        "suspend_asset": "silver_stock_suspend_daily",
                        "partition_key": partition_key,
                    },
                    filter_summary={
                        "raw_normalized_row_count": filter_counts[
                            "raw_normalized_row_count"
                        ],
                        "deduped_row_count": filter_counts["deduped_row_count"],
                        "final_silver_row_count": filter_counts[
                            "final_silver_row_count"
                        ],
                        "duplicate_removed_count": duplicate_removed_count,
                    },
                    diagnostic_ref="完整诊断看 silver stock daily checks、filter counts 和 run stdout。",
                ),
                "raw_file_path": str(raw_path),
                "silver_stock_lifecycle_file_path": str(stock_lifecycle_path),
                "stock_basic_file_path": str(basic_path),
                "stock_suspend_daily_file_path": str(suspend_path),
                "partition_key": partition_key,
                **filter_counts,
                "duplicate_removed_count": duplicate_removed_count,
                "duplicate_key_count": duplicate_key_count,
                "duplicate_sample_rows": duplicate_sample_rows,
                "conflict_key_count": conflict_key_count,
            },
        )
    )
