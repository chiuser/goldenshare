from __future__ import annotations

from pathlib import Path

import pytest

from orchestrator.defs.catalog import (
    ComputeEngine,
    PartitionModel,
    get_lake_asset_catalog_entry,
)
from orchestrator.defs.partitions import (
    cn_major_index_factor_trade_days,
    cn_major_index_mins_trade_days,
)
from orchestrator.defs.paths import (
    DEFAULT_LAKE_STAGING_ROOT,
    raw_idx_factor_pro_path,
    raw_idx_factor_pro_staging_path,
    silver_index_factor_pro_path,
    silver_index_factor_pro_staging_path,
)
from orchestrator.defs.run_contracts.asset_column_schemas import (
    RAW_TUSHARE_IDX_FACTOR_PRO_SCHEMA,
    SILVER_INDEX_FACTOR_PRO_SCHEMA,
)
from orchestrator.defs.run_contracts.idx_factor_pro import (
    IDX_FACTOR_PRO_FIRST_AVAILABLE_TRADE_DATES,
    IDX_FACTOR_PRO_PAGE_LIMIT,
    IDX_FACTOR_PRO_SOURCE_COLUMNS,
    IdxFactorProContractError,
    active_idx_factor_pro_daily_codes,
    approved_idx_factor_pro_daily_codes,
    build_idx_factor_pro_daily_request,
    build_idx_factor_pro_history_request,
)


def test_source_contract_freezes_89_fields_and_11_code_daily_seed() -> None:
    approved_codes = approved_idx_factor_pro_daily_codes()

    assert len(IDX_FACTOR_PRO_SOURCE_COLUMNS) == 89
    assert IDX_FACTOR_PRO_SOURCE_COLUMNS[:2] == ("ts_code", "trade_date")
    assert len(approved_codes) == 11
    assert len(set(approved_codes)) == 11
    assert set(approved_codes) == set(IDX_FACTOR_PRO_FIRST_AVAILABLE_TRADE_DATES)
    assert {"899050.BJ", "000680.SH"} <= set(approved_codes)
    assert set(active_idx_factor_pro_daily_codes("2026-08-07")) == set(
        approved_codes
    )


def test_active_codes_intersect_daily_seed_with_source_first_date() -> None:
    before_source_start = active_idx_factor_pro_daily_codes("2025-01-16")
    on_source_start = active_idx_factor_pro_daily_codes("2025-01-17")

    assert "000680.SH" not in before_source_start
    assert "000680.SH" in on_source_start
    assert set(on_source_start) - set(before_source_start) == {"000680.SH"}


def test_daily_factor_uses_a_dedicated_partition_definition() -> None:
    assert cn_major_index_factor_trade_days.name == (
        "cn_major_index_factor_trade_days"
    )
    assert cn_major_index_factor_trade_days is not cn_major_index_mins_trade_days


def test_daily_request_uses_only_trade_date_and_8000_row_pagination() -> None:
    request = build_idx_factor_pro_daily_request("2026-08-07", offset=8_000)

    assert request.api_name == "idx_factor_pro"
    assert request.params == {
        "trade_date": "20260807",
        "limit": IDX_FACTOR_PRO_PAGE_LIMIT,
        "offset": 8_000,
    }
    assert set(request.params).isdisjoint({"ts_code", "start_date", "end_date"})
    assert request.fields == IDX_FACTOR_PRO_SOURCE_COLUMNS


def test_history_request_uses_one_approved_code_and_full_range() -> None:
    request = build_idx_factor_pro_history_request(
        "000001.sh",
        "1990-12-19",
        "2026-08-07",
        offset=0,
    )

    assert request.params == {
        "ts_code": "000001.SH",
        "start_date": "19901219",
        "end_date": "20260807",
        "limit": 8_000,
        "offset": 0,
    }
    assert "trade_date" not in request.params


@pytest.mark.parametrize("offset", [-1, 1, 6_000, True, 8_000.0])
def test_requests_reject_invalid_pagination_offsets(offset: object) -> None:
    with pytest.raises(IdxFactorProContractError, match="offset"):
        build_idx_factor_pro_daily_request("2026-08-07", offset=offset)  # type: ignore[arg-type]


def test_history_request_rejects_unknown_code_and_non_frozen_start() -> None:
    with pytest.raises(IdxFactorProContractError, match="outside the daily seed"):
        build_idx_factor_pro_history_request(
            "930000.CSI", "2020-01-01", "2026-08-07", offset=0
        )
    with pytest.raises(IdxFactorProContractError, match="frozen first available"):
        build_idx_factor_pro_history_request(
            "000680.SH", "2020-01-02", "2026-08-07", offset=0
        )


def test_paths_are_strict_and_catalog_uses_official_builders() -> None:
    root = Path("data_lake")
    staging_root = Path("data_lake_staging")

    assert DEFAULT_LAKE_STAGING_ROOT == "/Volumes/datasource/data_lake_staging"

    assert raw_idx_factor_pro_path(root, "2026-08-07").as_posix() == (
        "data_lake/raw/tushare/idx_factor_pro/"
        "trade_date=2026-08-07/part-000.parquet"
    )
    assert silver_index_factor_pro_path(root, "2026-08-07").as_posix() == (
        "data_lake/silver/index/index_factor_pro/"
        "trade_date=2026-08-07/part-000.parquet"
    )
    assert "run_id=run-1" in raw_idx_factor_pro_staging_path(
        staging_root, "run-1", "2026-08-07"
    ).as_posix()
    assert "run_id=run-1" in silver_index_factor_pro_staging_path(
        staging_root, "run-1", "2026-08-07"
    ).as_posix()
    with pytest.raises(ValueError, match="safe non-empty"):
        raw_idx_factor_pro_staging_path(
            staging_root, "../unsafe", "2026-08-07"
        )
    with pytest.raises(IdxFactorProContractError, match="YYYY-MM-DD"):
        raw_idx_factor_pro_path(root, "20260807")

    raw_entry = get_lake_asset_catalog_entry("raw_tushare_idx_factor_pro")
    silver_entry = get_lake_asset_catalog_entry("silver_index_factor_pro")
    assert raw_entry.partition_model is PartitionModel.TRADE_DATE_PARTITION_RAW_IDX_FACTOR_PRO
    assert raw_entry.performance_contract.compute_engine is ComputeEngine.TUSHARE_RESOURCE
    assert "11_daily_seed_codes" in raw_entry.performance_contract.source_request_policy
    assert silver_entry.partition_model is (
        PartitionModel.TRADE_DATE_PARTITION_SILVER_INDEX_FACTOR_PRO
    )


def test_raw_and_silver_schemas_share_order_but_cast_trade_date() -> None:
    assert tuple(column.name for column in RAW_TUSHARE_IDX_FACTOR_PRO_SCHEMA) == (
        IDX_FACTOR_PRO_SOURCE_COLUMNS
    )
    assert tuple(column.name for column in SILVER_INDEX_FACTOR_PRO_SCHEMA) == (
        IDX_FACTOR_PRO_SOURCE_COLUMNS
    )
    assert RAW_TUSHARE_IDX_FACTOR_PRO_SCHEMA[1].type == "VARCHAR"
    assert SILVER_INDEX_FACTOR_PRO_SCHEMA[1].type == "DATE"
    assert all(
        column.type == "DOUBLE" for column in RAW_TUSHARE_IDX_FACTOR_PRO_SCHEMA[2:]
    )
