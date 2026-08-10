from orchestrator.defs.assets.idx_factor_pro_raw import raw_tushare_idx_factor_pro
from orchestrator.defs.assets.idx_factor_pro_silver import silver_index_factor_pro
from orchestrator.defs.catalog import (
    PartitionModel,
    get_lake_asset_catalog_entry,
    get_partition_model_definition,
)
from orchestrator.defs.checks.idx_factor_pro_checks import (
    raw_tushare_idx_factor_pro_contract_check,
    raw_tushare_idx_factor_pro_key_integrity_check,
    raw_tushare_idx_factor_pro_nullable_drift_check,
    raw_tushare_idx_factor_pro_partition_scope_check,
    raw_tushare_idx_factor_pro_selection_parity_check,
    silver_index_factor_pro_cast_integrity_check,
    silver_index_factor_pro_contract_check,
    silver_index_factor_pro_source_parity_check,
)
from orchestrator.defs.jobs.idx_factor_pro import (
    raw_tushare_idx_factor_pro_update_job,
    silver_index_factor_pro_update_job,
)
from orchestrator.defs.partitions import cn_major_index_factor_trade_days
from orchestrator.defs.run_contracts.idx_factor_pro import (
    IDX_FACTOR_PRO_RAW_ASSET_KEY,
    IDX_FACTOR_PRO_RAW_CHECKS,
    IDX_FACTOR_PRO_RAW_JOB_NAME,
    IDX_FACTOR_PRO_RAW_NULLABLE_CHECK,
    IDX_FACTOR_PRO_SILVER_ASSET_KEY,
    IDX_FACTOR_PRO_SILVER_CHECKS,
    IDX_FACTOR_PRO_SILVER_JOB_NAME,
)

RAW_CHECK_DEFINITIONS = (
    raw_tushare_idx_factor_pro_contract_check,
    raw_tushare_idx_factor_pro_partition_scope_check,
    raw_tushare_idx_factor_pro_key_integrity_check,
    raw_tushare_idx_factor_pro_selection_parity_check,
)
SILVER_CHECK_DEFINITIONS = (
    silver_index_factor_pro_contract_check,
    silver_index_factor_pro_source_parity_check,
    silver_index_factor_pro_cast_integrity_check,
)


def test_raw_asset_uses_exact_key_and_dedicated_partition_set() -> None:
    assert raw_tushare_idx_factor_pro.key.to_user_string() == (
        IDX_FACTOR_PRO_RAW_ASSET_KEY
    )
    assert (
        raw_tushare_idx_factor_pro.partitions_def
        is cn_major_index_factor_trade_days
    )
    assert raw_tushare_idx_factor_pro.dependency_keys == set()


def test_raw_blocking_and_nullable_checks_match_frozen_contract() -> None:
    assert tuple(
        next(iter(check.check_specs)).name for check in RAW_CHECK_DEFINITIONS
    ) == IDX_FACTOR_PRO_RAW_CHECKS
    for check in RAW_CHECK_DEFINITIONS:
        spec = next(iter(check.check_specs))
        assert spec.asset_key.to_user_string() == IDX_FACTOR_PRO_RAW_ASSET_KEY
        assert spec.blocking is True
        assert spec.partitions_def is cn_major_index_factor_trade_days

    nullable_spec = next(
        iter(raw_tushare_idx_factor_pro_nullable_drift_check.check_specs)
    )
    assert nullable_spec.name == IDX_FACTOR_PRO_RAW_NULLABLE_CHECK
    assert nullable_spec.asset_key.to_user_string() == IDX_FACTOR_PRO_RAW_ASSET_KEY
    assert nullable_spec.blocking is False
    assert nullable_spec.partitions_def is cn_major_index_factor_trade_days


def test_raw_catalog_and_partition_model_match_asset_contract() -> None:
    entry = get_lake_asset_catalog_entry(IDX_FACTOR_PRO_RAW_ASSET_KEY)
    assert entry.dataset_id == "idx_factor_pro"
    assert entry.blocking_check_names == IDX_FACTOR_PRO_RAW_CHECKS
    assert entry.partition_model is PartitionModel.TRADE_DATE_PARTITION_RAW_IDX_FACTOR_PRO
    assert entry.source_api == "idx_factor_pro"
    assert entry.path_template.endswith(
        "raw/tushare/idx_factor_pro/"
        "trade_date={partition_key}/part-000.parquet"
    )

    partition_model = get_partition_model_definition(entry.partition_model)
    assert partition_model.asset_family == "idx_factor_pro"
    assert partition_model.dagster_partition_dimension == "trade_date"


def test_silver_asset_depends_only_on_raw_and_uses_same_partition_set() -> None:
    assert silver_index_factor_pro.key.to_user_string() == (
        IDX_FACTOR_PRO_SILVER_ASSET_KEY
    )
    assert (
        silver_index_factor_pro.partitions_def
        is cn_major_index_factor_trade_days
    )
    assert silver_index_factor_pro.dependency_keys == {
        raw_tushare_idx_factor_pro.key
    }


def test_silver_checks_and_catalog_match_frozen_contract() -> None:
    assert tuple(
        next(iter(check.check_specs)).name for check in SILVER_CHECK_DEFINITIONS
    ) == IDX_FACTOR_PRO_SILVER_CHECKS
    for check in SILVER_CHECK_DEFINITIONS:
        spec = next(iter(check.check_specs))
        assert spec.asset_key.to_user_string() == IDX_FACTOR_PRO_SILVER_ASSET_KEY
        assert spec.blocking is True
        assert spec.partitions_def is cn_major_index_factor_trade_days

    entry = get_lake_asset_catalog_entry(IDX_FACTOR_PRO_SILVER_ASSET_KEY)
    assert entry.dataset_id == "index_factor_pro"
    assert entry.blocking_check_names == IDX_FACTOR_PRO_SILVER_CHECKS
    assert (
        entry.partition_model
        is PartitionModel.TRADE_DATE_PARTITION_SILVER_INDEX_FACTOR_PRO
    )
    assert entry.source_api is None
    assert entry.path_template.endswith(
        "silver/index/index_factor_pro/"
        "trade_date={partition_key}/part-000.parquet"
    )


def test_jobs_select_only_their_layer_and_blocking_checks() -> None:
    raw_selection = str(raw_tushare_idx_factor_pro_update_job.selection)
    silver_selection = str(silver_index_factor_pro_update_job.selection)

    assert raw_tushare_idx_factor_pro_update_job.name == IDX_FACTOR_PRO_RAW_JOB_NAME
    assert silver_index_factor_pro_update_job.name == IDX_FACTOR_PRO_SILVER_JOB_NAME
    assert IDX_FACTOR_PRO_RAW_ASSET_KEY in raw_selection
    assert IDX_FACTOR_PRO_SILVER_ASSET_KEY not in raw_selection
    assert IDX_FACTOR_PRO_SILVER_ASSET_KEY in silver_selection
    assert IDX_FACTOR_PRO_RAW_ASSET_KEY not in silver_selection
    assert "AssetChecksForAssetKeysSelection" in raw_selection
    assert "AssetChecksForAssetKeysSelection" in silver_selection
    assert (
        raw_tushare_idx_factor_pro_update_job.partitions_def
        is cn_major_index_factor_trade_days
    )
    assert (
        silver_index_factor_pro_update_job.partitions_def
        is cn_major_index_factor_trade_days
    )
