from orchestrator.defs.assets.major_index_mins_raw import RAW_MAJOR_INDEX_MINS_ASSETS
from orchestrator.defs.assets.major_index_mins_silver import (
    SILVER_MAJOR_INDEX_MINS_ASSETS,
)
from orchestrator.defs.catalog import list_lake_asset_catalog_entries
from orchestrator.defs.checks.major_index_mins_checks import (
    RAW_MAJOR_INDEX_MINS_CHECKS,
    SILVER_MAJOR_INDEX_MINS_CHECKS,
)
from orchestrator.defs.jobs.major_index_mins import (
    raw_major_index_mins_update_job,
    silver_major_index_mins_update_job,
)
from orchestrator.defs.partitions import cn_major_index_mins_trade_days
from orchestrator.defs.run_contracts.major_index_mins import (
    MAJOR_INDEX_MINS_RAW_ASSET_KEYS,
    MAJOR_INDEX_MINS_RAW_CHECKS,
    MAJOR_INDEX_MINS_SILVER_ASSET_KEYS,
    MAJOR_INDEX_MINS_SILVER_CHECKS,
)


def test_assets_use_exact_names_and_dedicated_partition_set() -> None:
    assert tuple(
        asset.key.to_user_string() for asset in RAW_MAJOR_INDEX_MINS_ASSETS
    ) == MAJOR_INDEX_MINS_RAW_ASSET_KEYS
    assert tuple(
        asset.key.to_user_string() for asset in SILVER_MAJOR_INDEX_MINS_ASSETS
    ) == MAJOR_INDEX_MINS_SILVER_ASSET_KEYS
    assert all(
        asset.partitions_def is cn_major_index_mins_trade_days
        for asset in (*RAW_MAJOR_INDEX_MINS_ASSETS, *SILVER_MAJOR_INDEX_MINS_ASSETS)
    )


def test_dependency_graph_keeps_native_and_derived_sources_explicit() -> None:
    raw_by_name = {
        asset.key.to_user_string(): asset for asset in RAW_MAJOR_INDEX_MINS_ASSETS
    }
    silver_by_name = {
        asset.key.to_user_string(): asset for asset in SILVER_MAJOR_INDEX_MINS_ASSETS
    }
    for frequency in (1, 5, 15, 30, 60):
        assert raw_by_name[f"raw_major_index_mins_{frequency}m"].dependency_keys == set()
        assert silver_by_name[
            f"silver_major_index_mins_{frequency}m"
        ].dependency_keys == {
            raw_by_name[f"raw_major_index_mins_{frequency}m"].key
        }
    assert silver_by_name["silver_major_index_mins_90m"].dependency_keys == {
        silver_by_name["silver_major_index_mins_30m"].key
    }
    assert silver_by_name["silver_major_index_mins_120m"].dependency_keys == {
        silver_by_name["silver_major_index_mins_60m"].key
    }


def test_checks_are_exact_single_partition_blocking_checks() -> None:
    assert tuple(
        next(iter(check.check_specs)).name for check in RAW_MAJOR_INDEX_MINS_CHECKS
    ) == MAJOR_INDEX_MINS_RAW_CHECKS
    assert tuple(
        next(iter(check.check_specs)).name for check in SILVER_MAJOR_INDEX_MINS_CHECKS
    ) == MAJOR_INDEX_MINS_SILVER_CHECKS
    for check in (*RAW_MAJOR_INDEX_MINS_CHECKS, *SILVER_MAJOR_INDEX_MINS_CHECKS):
        specs = tuple(check.check_specs)
        assert len(specs) == 1
        assert specs[0].blocking is True
        assert specs[0].partitions_def is cn_major_index_mins_trade_days


def test_jobs_select_only_their_layer_and_checks() -> None:
    raw_selection = str(raw_major_index_mins_update_job.selection)
    silver_selection = str(silver_major_index_mins_update_job.selection)
    for asset_key in MAJOR_INDEX_MINS_RAW_ASSET_KEYS:
        assert asset_key in raw_selection
        assert asset_key not in silver_selection
    for asset_key in MAJOR_INDEX_MINS_SILVER_ASSET_KEYS:
        assert asset_key in silver_selection
        assert asset_key not in raw_selection
    assert "AssetChecksForAssetKeysSelection" in raw_selection
    assert "AssetChecksForAssetKeysSelection" in silver_selection
    assert raw_major_index_mins_update_job.partitions_def is cn_major_index_mins_trade_days
    assert (
        silver_major_index_mins_update_job.partitions_def
        is cn_major_index_mins_trade_days
    )


def test_catalog_has_exact_asset_and_check_mapping() -> None:
    entries = tuple(
        entry
        for entry in list_lake_asset_catalog_entries()
        if entry.dataset_id == "major_index_mins"
    )
    expected_keys = set(
        (*MAJOR_INDEX_MINS_RAW_ASSET_KEYS, *MAJOR_INDEX_MINS_SILVER_ASSET_KEYS)
    )
    assert {entry.asset_key for entry in entries} == expected_keys
    for entry in entries:
        assert entry.dataset_name == "主要指数分钟线"
        assert entry.blocking_check_names == (f"{entry.asset_key}_core_check",)
        assert entry.partition_model.value.endswith("major_index_mins")
