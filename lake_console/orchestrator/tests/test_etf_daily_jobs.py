from orchestrator.defs.assets.etf_basic import silver_etf_basic
from orchestrator.defs.assets.etf_daily import (
    raw_tushare_fund_adj,
    raw_tushare_fund_daily,
    silver_etf_adj_factor,
    silver_etf_daily,
)
from orchestrator.defs.checks.etf_daily_checks import (
    silver_etf_adj_factor_basic_coverage_check,
    silver_etf_adj_factor_contract_check,
    silver_etf_adj_factor_domain_check,
    silver_etf_adj_factor_key_integrity_check,
    silver_etf_adj_factor_source_filter_check,
    silver_etf_adj_factor_source_parity_check,
    silver_etf_daily_bar_domain_check,
    silver_etf_daily_basic_coverage_check,
    silver_etf_daily_contract_check,
    silver_etf_daily_key_integrity_check,
    silver_etf_daily_source_filter_check,
    silver_etf_daily_source_parity_check,
)
from orchestrator.defs.jobs.etf_daily import (
    raw_fund_adj_update_job,
    raw_fund_daily_update_job,
    silver_etf_adj_factor_update_job,
    silver_etf_daily_update_job,
)
from orchestrator.defs.partitions import cn_a_etf_mins_trade_days
from orchestrator.defs.run_contracts.etf_daily import (
    RAW_FUND_ADJ_JOB_NAME,
    RAW_FUND_DAILY_JOB_NAME,
    SILVER_ETF_ADJ_FACTOR_BLOCKING_CHECKS,
    SILVER_ETF_ADJ_FACTOR_COVERAGE_CHECK,
    SILVER_ETF_ADJ_FACTOR_JOB_NAME,
    SILVER_ETF_DAILY_BLOCKING_CHECKS,
    SILVER_ETF_DAILY_COVERAGE_CHECK,
    SILVER_ETF_DAILY_JOB_NAME,
)


def test_silver_assets_use_lineage_only_deps_and_shared_partitions() -> None:
    assert silver_etf_daily.dependency_keys == {
        raw_tushare_fund_daily.key,
        silver_etf_basic.key,
    }
    assert silver_etf_adj_factor.dependency_keys == {
        raw_tushare_fund_adj.key,
        silver_etf_basic.key,
    }
    assert silver_etf_daily.partitions_def is cn_a_etf_mins_trade_days
    assert silver_etf_adj_factor.partitions_def is cn_a_etf_mins_trade_days
    for asset in (silver_etf_daily, silver_etf_adj_factor):
        metadata = asset.metadata_by_key[asset.key]
        assert metadata["goldenshare/source_system"] == "derived"
        assert metadata["goldenshare/partition_set"] == (
            cn_a_etf_mins_trade_days.name
        )
        assert "dagster/column_schema" in metadata
        assert "goldenshare/path_template" in metadata


def test_silver_checks_are_bound_to_the_exact_assets_and_names() -> None:
    daily_checks = (
        silver_etf_daily_contract_check,
        silver_etf_daily_source_filter_check,
        silver_etf_daily_source_parity_check,
        silver_etf_daily_key_integrity_check,
        silver_etf_daily_bar_domain_check,
        silver_etf_daily_basic_coverage_check,
    )
    adj_checks = (
        silver_etf_adj_factor_contract_check,
        silver_etf_adj_factor_source_filter_check,
        silver_etf_adj_factor_source_parity_check,
        silver_etf_adj_factor_key_integrity_check,
        silver_etf_adj_factor_domain_check,
        silver_etf_adj_factor_basic_coverage_check,
    )
    assert tuple(next(iter(check.check_specs)).name for check in daily_checks) == (
        *SILVER_ETF_DAILY_BLOCKING_CHECKS,
        SILVER_ETF_DAILY_COVERAGE_CHECK,
    )
    assert tuple(next(iter(check.check_specs)).name for check in adj_checks) == (
        *SILVER_ETF_ADJ_FACTOR_BLOCKING_CHECKS,
        SILVER_ETF_ADJ_FACTOR_COVERAGE_CHECK,
    )
    for check in daily_checks:
        assert next(iter(check.check_specs)).asset_key == silver_etf_daily.key
    for check in adj_checks:
        assert next(iter(check.check_specs)).asset_key == silver_etf_adj_factor.key


def test_four_jobs_are_layer_isolated_and_share_one_partition_definition() -> None:
    jobs = (
        (raw_fund_daily_update_job, RAW_FUND_DAILY_JOB_NAME, "raw_tushare_fund_daily"),
        (raw_fund_adj_update_job, RAW_FUND_ADJ_JOB_NAME, "raw_tushare_fund_adj"),
        (
            silver_etf_daily_update_job,
            SILVER_ETF_DAILY_JOB_NAME,
            "silver_etf_daily",
        ),
        (
            silver_etf_adj_factor_update_job,
            SILVER_ETF_ADJ_FACTOR_JOB_NAME,
            "silver_etf_adj_factor",
        ),
    )
    all_asset_keys = {target for _, _, target in jobs}
    for job, name, target in jobs:
        selection = str(job.selection)
        assert job.name == name
        assert job.partitions_def is cn_a_etf_mins_trade_days
        assert target in selection
        assert all(other not in selection for other in all_asset_keys - {target})
        assert "AssetChecksForAssetKeysSelection" in selection
