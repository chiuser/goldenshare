from pathlib import Path

import duckdb

from orchestrator.defs.asset_guards.dc_board_raw_quality import RAW_DC_INDEX_QUALITY
from orchestrator.defs.checks.dc_board_checks import _core_check
from orchestrator.defs.paths import raw_dc_index_path
from orchestrator.defs.resources import DuckDBResource, LakeRootResource
from orchestrator.defs.run_contracts.asset_column_schemas import (
    RAW_TUSHARE_DC_INDEX_SCHEMA,
)


class _Context:
    partition_keys = ("2026-07-14",)


def _write_index(path: Path, ts_code: str = "BK0001.DC", trade_date: str = "20260714") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect()
    connection.execute(
        f"""
        COPY (
            SELECT
                CAST(ts_code AS VARCHAR) AS ts_code, CAST(trade_date AS VARCHAR) AS trade_date,
                CAST(name AS VARCHAR) AS name, CAST("leading" AS VARCHAR) AS "leading",
                CAST(leading_code AS VARCHAR) AS leading_code,
                CAST(pct_change AS DOUBLE) AS pct_change, CAST(leading_pct AS DOUBLE) AS leading_pct,
                CAST(total_mv AS DOUBLE) AS total_mv, CAST(turnover_rate AS DOUBLE) AS turnover_rate,
                CAST(up_num AS INTEGER) AS up_num, CAST(down_num AS INTEGER) AS down_num,
                CAST(idx_type AS VARCHAR) AS idx_type, CAST(level AS VARCHAR) AS level
            FROM (VALUES
                (?, ?, '板块', '股票', '000001.SZ', 1.0, 2.0, 3.0, 4.0, 5, 6, '行业板块', 'L1')
            ) AS t(ts_code, trade_date, name, "leading", leading_code, pct_change,
                   leading_pct, total_mv, turnover_rate, up_num, down_num, idx_type, level)
        ) TO '{path}' (FORMAT PARQUET)
        """,
        [ts_code, trade_date],
    )
    connection.close()


class _MemoryDuckDB(DuckDBResource):
    pass


def test_core_check_passes_for_valid_partition(tmp_path) -> None:
    root = Path(tmp_path)
    path = raw_dc_index_path(root, "2026-07-14")
    _write_index(path)
    result = _core_check(
        context=_Context(),
        lake_root=LakeRootResource(root_path=str(root)),
        duckdb_resource=_MemoryDuckDB(),
        dataset="dc_index",
        path_builder=raw_dc_index_path,
        schema=RAW_TUSHARE_DC_INDEX_SCHEMA,
        key_columns=("ts_code", "trade_date"),
        identity_predicate=(
            "ts_code IS NOT NULL AND regexp_full_match(trim(CAST(ts_code AS VARCHAR)), '^BK[0-9]{4}\\.DC$') "
            "AND idx_type IN ('行业板块', '概念板块', '地域板块') AND name IS NOT NULL"
        ),
        identity_columns=("ts_code", "idx_type", "name"),
    )
    assert result.passed is True


def test_core_check_reports_missing_file(tmp_path) -> None:
    result = _core_check(
        context=_Context(),
        lake_root=LakeRootResource(root_path=str(tmp_path)),
        duckdb_resource=_MemoryDuckDB(),
        dataset="dc_index",
        path_builder=raw_dc_index_path,
        schema=RAW_TUSHARE_DC_INDEX_SCHEMA,
        key_columns=("ts_code", "trade_date"),
        identity_predicate="true",
        identity_columns=("ts_code",),
    )
    assert result.passed is False
    assert result.metadata["goldenshare/reason_code"].value == "file_missing"


def test_core_check_rejects_exact_source_placeholder(tmp_path) -> None:
    root = Path(tmp_path)
    path = raw_dc_index_path(root, "2026-07-14")
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect()
    connection.execute(
        f"COPY (SELECT 'BK1675.DC' AS ts_code, '20260714' AS trade_date, '历史新高' AS name, '-' AS \"leading\", NULL::VARCHAR AS leading_code, 0.0::DOUBLE AS pct_change, 0.0::DOUBLE AS leading_pct, 0.0::DOUBLE AS total_mv, 0.0::DOUBLE AS turnover_rate, NULL::INTEGER AS up_num, NULL::INTEGER AS down_num, '概念板块' AS idx_type, NULL::VARCHAR AS level) TO '{path}' (FORMAT PARQUET)"
    )
    connection.close()

    result = _core_check(
        context=_Context(),
        lake_root=LakeRootResource(root_path=str(root)),
        duckdb_resource=_MemoryDuckDB(),
        dataset="dc_index",
        path_builder=raw_dc_index_path,
        schema=RAW_TUSHARE_DC_INDEX_SCHEMA,
        key_columns=("ts_code", "trade_date"),
        identity_predicate=RAW_DC_INDEX_QUALITY.identity_condition,
        identity_columns=("ts_code", "idx_type", "name"),
    )
    assert result.passed is False
    assert result.metadata["goldenshare/failed_rules"].value == [
        "dataset_identity_fields_legal"
    ]
