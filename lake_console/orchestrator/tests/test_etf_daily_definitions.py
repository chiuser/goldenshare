import inspect

import dagster as dg

from orchestrator.definitions import defs as load_project_definitions
from orchestrator.defs.assets import etf_daily as etf_daily_assets_module
from orchestrator.defs.assets.etf_daily import (
    raw_tushare_fund_adj,
    raw_tushare_fund_daily,
    silver_etf_adj_factor,
    silver_etf_daily,
)
from orchestrator.defs.checks import etf_daily_checks as etf_daily_checks_module
from orchestrator.defs.checks.etf_daily_checks import (
    raw_tushare_fund_adj_key_integrity_check,
    raw_tushare_fund_adj_partition_scope_check,
    raw_tushare_fund_adj_source_contract_check,
    raw_tushare_fund_daily_key_integrity_check,
    raw_tushare_fund_daily_partition_scope_check,
    raw_tushare_fund_daily_source_contract_check,
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
from orchestrator.defs.io import etf_daily_raw_writer as etf_daily_writer_module
from orchestrator.defs.io import (
    etf_daily_silver_writer as etf_daily_silver_writer_module,
)
from orchestrator.defs.jobs import etf_daily as etf_daily_jobs_module
from orchestrator.defs.jobs.etf_daily import (
    raw_fund_adj_update_job,
    raw_fund_daily_update_job,
    silver_etf_adj_factor_update_job,
    silver_etf_daily_update_job,
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
    RAW_FUND_ADJ_SENSOR_NAME,
    RAW_FUND_DAILY_CHECKS,
    RAW_FUND_DAILY_JOB_NAME,
    RAW_FUND_DAILY_SENSOR_NAME,
    RAW_TUSHARE_FUND_ADJ_ASSET_KEY,
    RAW_TUSHARE_FUND_DAILY_ASSET_KEY,
    SILVER_ETF_ADJ_FACTOR_ASSET_KEY,
    SILVER_ETF_ADJ_FACTOR_BLOCKING_CHECKS,
    SILVER_ETF_ADJ_FACTOR_COVERAGE_CHECK,
    SILVER_ETF_ADJ_FACTOR_JOB_NAME,
    SILVER_ETF_ADJ_FACTOR_SENSOR_NAME,
    SILVER_ETF_DAILY_ASSET_KEY,
    SILVER_ETF_DAILY_BLOCKING_CHECKS,
    SILVER_ETF_DAILY_COVERAGE_CHECK,
    SILVER_ETF_DAILY_JOB_NAME,
    SILVER_ETF_DAILY_SENSOR_NAME,
)
from orchestrator.defs.sensors import etf_daily_sensor as etf_daily_sensor_module

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
SILVER_DAILY_CHECKS = (
    silver_etf_daily_contract_check,
    silver_etf_daily_source_filter_check,
    silver_etf_daily_source_parity_check,
    silver_etf_daily_key_integrity_check,
    silver_etf_daily_bar_domain_check,
    silver_etf_daily_basic_coverage_check,
)
SILVER_ADJ_CHECKS = (
    silver_etf_adj_factor_contract_check,
    silver_etf_adj_factor_source_filter_check,
    silver_etf_adj_factor_source_parity_check,
    silver_etf_adj_factor_key_integrity_check,
    silver_etf_adj_factor_domain_check,
    silver_etf_adj_factor_basic_coverage_check,
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


def test_silver_assets_checks_and_jobs_match_the_frozen_p3_contract() -> None:
    definitions = dg.Definitions(
        assets=[
            raw_tushare_fund_daily,
            raw_tushare_fund_adj,
            silver_etf_daily,
            silver_etf_adj_factor,
        ],
        asset_checks=[
            *DAILY_CHECKS,
            *ADJ_CHECKS,
            *SILVER_DAILY_CHECKS,
            *SILVER_ADJ_CHECKS,
        ],
        jobs=[
            raw_fund_daily_update_job,
            raw_fund_adj_update_job,
            silver_etf_daily_update_job,
            silver_etf_adj_factor_update_job,
        ],
        resources={
            "lake_root": LakeRootResource(root_path="/tmp/etf-daily-p3-lake"),
            "duckdb": DuckDBResource(),
            "tushare": TushareResource(token="fake-token"),
        },
    )
    dg.Definitions.validate_loadable(definitions)
    asset_graph = definitions.resolve_asset_graph()
    for asset, asset_key, raw_asset, checks, blocking_names, coverage_name in (
        (
            silver_etf_daily,
            SILVER_ETF_DAILY_ASSET_KEY,
            raw_tushare_fund_daily,
            SILVER_DAILY_CHECKS,
            SILVER_ETF_DAILY_BLOCKING_CHECKS,
            SILVER_ETF_DAILY_COVERAGE_CHECK,
        ),
        (
            silver_etf_adj_factor,
            SILVER_ETF_ADJ_FACTOR_ASSET_KEY,
            raw_tushare_fund_adj,
            SILVER_ADJ_CHECKS,
            SILVER_ETF_ADJ_FACTOR_BLOCKING_CHECKS,
            SILVER_ETF_ADJ_FACTOR_COVERAGE_CHECK,
        ),
    ):
        assert asset.key.to_user_string() == asset_key
        assert raw_asset.key in asset.dependency_keys
        assert asset.partitions_def is cn_a_etf_mins_trade_days
        specs = tuple(next(iter(check.check_specs)) for check in checks)
        assert tuple(spec.name for spec in specs) == (*blocking_names, coverage_name)
        assert all(spec.asset_key == asset.key for spec in specs)
        assert all(spec.blocking for spec in specs[:-1])
        assert specs[-1].blocking is False

    for job, job_name, asset, check_names in (
        (
            silver_etf_daily_update_job,
            SILVER_ETF_DAILY_JOB_NAME,
            silver_etf_daily,
            (*SILVER_ETF_DAILY_BLOCKING_CHECKS, SILVER_ETF_DAILY_COVERAGE_CHECK),
        ),
        (
            silver_etf_adj_factor_update_job,
            SILVER_ETF_ADJ_FACTOR_JOB_NAME,
            silver_etf_adj_factor,
            (
                *SILVER_ETF_ADJ_FACTOR_BLOCKING_CHECKS,
                SILVER_ETF_ADJ_FACTOR_COVERAGE_CHECK,
            ),
        ),
    ):
        assert job.name == job_name
        assert job.selection.resolve(asset_graph) == {asset.key}
        assert {
            check_key.name for check_key in job.selection.resolve_checks(asset_graph)
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
        (
            inspect.getsource(
                raw_tushare_fund_daily.op.compute_fn.decorated_fn
            ),
            inspect.getsource(raw_tushare_fund_adj.op.compute_fn.decorated_fn),
            inspect.getsource(etf_daily_writer_module),
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


def test_p3_runtime_has_no_prod_legacy_lake_or_row_loop_shortcuts() -> None:
    source = "\n".join(
        inspect.getsource(module)
        for module in (
            etf_daily_assets_module,
            etf_daily_checks_module,
            etf_daily_writer_module,
            etf_daily_silver_writer_module,
        )
    )
    for prohibited in (
        "ProdPostgresResource",
        "ProdClickHouseResource",
        "goldenshare-tushare-lake",
        "kopia",
        "_fetch_all_pages",
        "change_amount",
        "duckdb.connect(",
        ".iterrows(",
        ".itertuples(",
    ):
        assert prohibited not in source


def test_p4_sensor_runtime_has_no_check_history_partition_writer_or_custom_config() -> (
    None
):
    source = inspect.getsource(etf_daily_sensor_module)
    for prohibited in (
        "get_asset_check_execution_history",
        "get_latest_asset_check_execution_by_key",
        "DynamicPartitionsRequest",
        "run_config=",
        "ProdPostgresResource",
        "ProdClickHouseResource",
        "change_amount",
        "import duckdb",
    ):
        assert prohibited not in source


def test_project_definitions_discover_p4_assets_checks_jobs_and_sensors() -> None:
    repository = load_project_definitions().get_repository_def()
    asset_keys = {
        RAW_TUSHARE_FUND_DAILY_ASSET_KEY,
        RAW_TUSHARE_FUND_ADJ_ASSET_KEY,
        SILVER_ETF_DAILY_ASSET_KEY,
        SILVER_ETF_ADJ_FACTOR_ASSET_KEY,
    }
    assert asset_keys <= {
        key.to_user_string() for key in repository.asset_graph.get_all_asset_keys()
    }
    check_keys = {
        key
        for key in repository.asset_graph.asset_check_keys
        if key.asset_key.to_user_string() in asset_keys
    }
    assert len(check_keys) == 18
    for job_name in (
        RAW_FUND_DAILY_JOB_NAME,
        RAW_FUND_ADJ_JOB_NAME,
        SILVER_ETF_DAILY_JOB_NAME,
        SILVER_ETF_ADJ_FACTOR_JOB_NAME,
    ):
        assert repository.get_job(job_name) is not None
    for sensor_name in (
        RAW_FUND_DAILY_SENSOR_NAME,
        RAW_FUND_ADJ_SENSOR_NAME,
        SILVER_ETF_DAILY_SENSOR_NAME,
        SILVER_ETF_ADJ_FACTOR_SENSOR_NAME,
    ):
        assert repository.has_sensor_def(sensor_name)
        assert repository.get_sensor_def(sensor_name).default_status is (
            dg.DefaultSensorStatus.STOPPED
        )
