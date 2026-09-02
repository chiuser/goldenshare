from pathlib import Path

import pytest

from orchestrator.defs.paths import (
    PATH_TEMPLATE_LAKE_ROOT,
    PATH_TEMPLATE_PARTITION_KEY,
    raw_fund_adj_path,
    raw_fund_adj_staging_path,
    raw_fund_daily_path,
    raw_fund_daily_staging_path,
    silver_etf_adj_factor_path,
    silver_etf_adj_factor_staging_path,
    silver_etf_daily_path,
    silver_etf_daily_staging_path,
)
from orchestrator.defs.run_contracts.etf_daily import EtfDailyContractError

TRADE_DATE = "2026-09-01"


def test_formal_paths_follow_the_frozen_lake_layout() -> None:
    root = Path("/Volumes/datasource/data_lake")

    assert raw_fund_daily_path(root, TRADE_DATE).as_posix() == (
        "/Volumes/datasource/data_lake/raw/tushare/fund_daily/"
        "trade_date=2026-09-01/part-000.parquet"
    )
    assert silver_etf_daily_path(root, TRADE_DATE).as_posix() == (
        "/Volumes/datasource/data_lake/silver/quote/etf_daily/"
        "trade_date=2026-09-01/part-000.parquet"
    )
    assert raw_fund_adj_path(root, TRADE_DATE).as_posix() == (
        "/Volumes/datasource/data_lake/raw/tushare/fund_adj/"
        "trade_date=2026-09-01/part-000.parquet"
    )
    assert silver_etf_adj_factor_path(root, TRADE_DATE).as_posix() == (
        "/Volumes/datasource/data_lake/silver/quote/etf_adj_factor/"
        "trade_date=2026-09-01/part-000.parquet"
    )


def test_staging_paths_are_operation_scoped_and_asset_specific() -> None:
    root = Path("/Volumes/datasource/data_lake_staging")
    expected_prefix = (
        "/Volumes/datasource/data_lake_staging/etf_daily/operation_id=run-1"
    )

    assert raw_fund_daily_staging_path(root, "run-1", TRADE_DATE).as_posix() == (
        f"{expected_prefix}/raw_tushare_fund_daily/"
        "trade_date=2026-09-01/part-000.parquet"
    )
    assert silver_etf_daily_staging_path(root, "run-1", TRADE_DATE).as_posix() == (
        f"{expected_prefix}/silver_etf_daily/"
        "trade_date=2026-09-01/part-000.parquet"
    )
    assert raw_fund_adj_staging_path(root, "run-1", TRADE_DATE).as_posix() == (
        f"{expected_prefix}/raw_tushare_fund_adj/"
        "trade_date=2026-09-01/part-000.parquet"
    )
    assert silver_etf_adj_factor_staging_path(
        root, "run-1", TRADE_DATE
    ).as_posix() == (
        f"{expected_prefix}/silver_etf_adj_factor/"
        "trade_date=2026-09-01/part-000.parquet"
    )


def test_path_templates_preserve_the_partition_placeholder() -> None:
    assert raw_fund_daily_path(
        PATH_TEMPLATE_LAKE_ROOT, PATH_TEMPLATE_PARTITION_KEY
    ).as_posix() == (
        "data_lake/raw/tushare/fund_daily/"
        "trade_date={partition_key}/part-000.parquet"
    )
    assert silver_etf_adj_factor_path(
        PATH_TEMPLATE_LAKE_ROOT, PATH_TEMPLATE_PARTITION_KEY
    ).as_posix() == (
        "data_lake/silver/quote/etf_adj_factor/"
        "trade_date={partition_key}/part-000.parquet"
    )


@pytest.mark.parametrize(
    "path_builder",
    (
        raw_fund_daily_path,
        silver_etf_daily_path,
        raw_fund_adj_path,
        silver_etf_adj_factor_path,
    ),
)
def test_formal_paths_reject_non_iso_dates(path_builder) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(EtfDailyContractError, match="YYYY-MM-DD"):
        path_builder(Path("data_lake"), "20260901")


@pytest.mark.parametrize(
    "path_builder",
    (
        raw_fund_daily_staging_path,
        silver_etf_daily_staging_path,
        raw_fund_adj_staging_path,
        silver_etf_adj_factor_staging_path,
    ),
)
def test_staging_paths_reject_unsafe_operation_ids(path_builder) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(ValueError, match="safe non-empty"):
        path_builder(Path("data_lake_staging"), "../unsafe", TRADE_DATE)
