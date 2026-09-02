import inspect

import dagster as dg

from orchestrator.defs.assets import etf_daily as etf_daily_assets_module
from orchestrator.defs.assets.etf_daily import (
    raw_tushare_fund_adj,
    raw_tushare_fund_daily,
)
from orchestrator.defs.checks import etf_daily_checks as etf_daily_checks_module
from orchestrator.defs.checks.etf_daily_checks import (
    raw_tushare_fund_adj_key_integrity_check,
    raw_tushare_fund_adj_partition_scope_check,
    raw_tushare_fund_adj_source_contract_check,
    raw_tushare_fund_daily_key_integrity_check,
    raw_tushare_fund_daily_partition_scope_check,
    raw_tushare_fund_daily_source_contract_check,
)
from orchestrator.defs.io import etf_daily_raw_writer as etf_daily_writer_module
from orchestrator.defs.jobs import etf_daily as etf_daily_jobs_module
from orchestrator.defs.jobs.etf_daily import (
    raw_fund_adj_update_job,
    raw_fund_daily_update_job,
)
from orchestrator.defs.partitions import cn_a_etf_mins_trade_days
from orchestrator.defs.resources import (
    DuckDBResource,
    LakeRootResource,
    TushareResource,
)
from orchestrator.defs.run_contracts.etf_daily import (
    RAW_FUND_ADJ_CHECKS,
    RAW_FUND_ADJ_JOB_NAME,
    RAW_FUND_DAILY_CHECKS,
    RAW_FUND_DAILY_JOB_NAME,
    RAW_TUSHARE_FUND_ADJ_ASSET_KEY,
    RAW_TUSHARE_FUND_DAILY_ASSET_KEY,
)

DAILY_CHECKS = (
    raw_tushare_fund_daily_source_contract_check,
    raw_tushare_fund_daily_partition_scope_check,
    raw_tushare_fund_daily_key_integrity_check,
)
ADJ_CHECKS = (
    raw_tushare_fund_adj_source_contract_check,
    raw_tushare_fund_adj_partition_scope_check,
    raw_tushare_fund_adj_key_integrity_check,
)


def test_raw_assets_and_checks_match_the_frozen_p2_contract() -> None:
    assert raw_tushare_fund_daily.key.to_user_string() == (
        RAW_TUSHARE_FUND_DAILY_ASSET_KEY
    )
    assert raw_tushare_fund_adj.key.to_user_string() == (
        RAW_TUSHARE_FUND_ADJ_ASSET_KEY
    )
    assert raw_tushare_fund_daily.dependency_keys == set()
    assert raw_tushare_fund_adj.dependency_keys == set()
    assert raw_tushare_fund_daily.partitions_def is cn_a_etf_mins_trade_days
    assert raw_tushare_fund_adj.partitions_def is cn_a_etf_mins_trade_days

    for asset, checks, expected_names in (
        (raw_tushare_fund_daily, DAILY_CHECKS, RAW_FUND_DAILY_CHECKS),
        (raw_tushare_fund_adj, ADJ_CHECKS, RAW_FUND_ADJ_CHECKS),
    ):
        specs = tuple(next(iter(check.check_specs)) for check in checks)
        assert tuple(spec.name for spec in specs) == expected_names
        assert all(spec.asset_key == asset.key for spec in specs)
        assert all(spec.blocking is True for spec in specs)
        assert all(
            spec.partitions_def is cn_a_etf_mins_trade_days for spec in specs
        )


def test_raw_jobs_select_only_one_asset_and_its_checks() -> None:
    definitions = dg.Definitions(
        assets=[raw_tushare_fund_daily, raw_tushare_fund_adj],
        asset_checks=[*DAILY_CHECKS, *ADJ_CHECKS],
        jobs=[raw_fund_daily_update_job, raw_fund_adj_update_job],
        resources={
            "lake_root": LakeRootResource(root_path="/tmp/etf-daily-p2-lake"),
            "duckdb": DuckDBResource(),
            "tushare": TushareResource(token="fake-token"),
        },
    )
    dg.Definitions.validate_loadable(definitions)
    asset_graph = definitions.resolve_asset_graph()

    for job, job_name, asset, check_names in (
        (
            raw_fund_daily_update_job,
            RAW_FUND_DAILY_JOB_NAME,
            raw_tushare_fund_daily,
            RAW_FUND_DAILY_CHECKS,
        ),
        (
            raw_fund_adj_update_job,
            RAW_FUND_ADJ_JOB_NAME,
            raw_tushare_fund_adj,
            RAW_FUND_ADJ_CHECKS,
        ),
    ):
        assert job.name == job_name
        assert job.partitions_def is cn_a_etf_mins_trade_days
        assert job.selection.resolve(asset_graph) == {asset.key}
        assert {
            check_key.name
            for check_key in job.selection.resolve_checks(asset_graph)
        } == set(check_names)


def test_raw_job_module_contains_no_execution_or_storage_logic() -> None:
    source = inspect.getsource(etf_daily_jobs_module)
    for prohibited in (
        "TushareResource",
        "DuckDBResource",
        "write_fund_",
        "probe_fund_",
        "raw_fund_daily_path",
        "raw_fund_adj_path",
        "SELECT ",
    ):
        assert prohibited not in source


def test_raw_runtime_has_no_basic_prod_or_legacy_lake_dependency() -> None:
    source = "\n".join(
        inspect.getsource(module)
        for module in (
            etf_daily_assets_module,
            etf_daily_checks_module,
            etf_daily_writer_module,
        )
    )
    for prohibited in (
        "etf_basic",
        "ProdPostgresResource",
        "ProdClickHouseResource",
        "goldenshare-tushare-lake",
        "kopia",
        "_fetch_all_pages",
        "change_amount",
        "duckdb.connect(",
    ):
        assert prohibited not in source
