from __future__ import annotations

from orchestrator.defs.assets.index_mins_raw import RAW_INDEX_MINS_ASSETS
from orchestrator.defs.assets.index_mins_silver_defs import SILVER_INDEX_MINS_ASSETS
from orchestrator.defs.catalog import list_lake_asset_catalog_entries
from orchestrator.defs.checks.index_mins_checks import (
    raw_index_mins_1m_core_check,
    raw_index_mins_5m_core_check,
    raw_index_mins_15m_core_check,
    raw_index_mins_30m_core_check,
    raw_index_mins_60m_core_check,
    silver_index_mins_1m_core_check,
    silver_index_mins_5m_core_check,
    silver_index_mins_15m_core_check,
    silver_index_mins_30m_core_check,
    silver_index_mins_60m_core_check,
    silver_index_mins_90m_core_check,
    silver_index_mins_120m_core_check,
)
from orchestrator.defs.jobs.index_mins import (
    raw_index_mins_update_job,
    silver_index_mins_update_job,
)
from orchestrator.defs.partitions import cn_a_index_mins_trade_days
from orchestrator.defs.run_contracts.index_mins import (
    INDEX_MINS_GOLD_ASSET_NAMES,
    INDEX_MINS_GOLD_CHECKS,
    INDEX_MINS_RAW_ASSET_NAMES,
    INDEX_MINS_RAW_CHECKS,
    INDEX_MINS_SILVER_ASSET_NAMES,
    INDEX_MINS_SILVER_CHECKS,
)

RAW_CHECKS = (
    raw_index_mins_1m_core_check,
    raw_index_mins_5m_core_check,
    raw_index_mins_15m_core_check,
    raw_index_mins_30m_core_check,
    raw_index_mins_60m_core_check,
)
SILVER_CHECKS = (
    silver_index_mins_1m_core_check,
    silver_index_mins_5m_core_check,
    silver_index_mins_15m_core_check,
    silver_index_mins_30m_core_check,
    silver_index_mins_60m_core_check,
    silver_index_mins_90m_core_check,
    silver_index_mins_120m_core_check,
)


def test_index_mins_assets_use_the_dedicated_partition_set() -> None:
    assert len(RAW_INDEX_MINS_ASSETS) == 5
    assert len(SILVER_INDEX_MINS_ASSETS) == 7
    assert all(asset.partitions_def is cn_a_index_mins_trade_days for asset in RAW_INDEX_MINS_ASSETS)
    assert all(asset.partitions_def is cn_a_index_mins_trade_days for asset in SILVER_INDEX_MINS_ASSETS)
    assert all(
        asset.key.to_user_string().startswith("raw_index_mins_")
        for asset in RAW_INDEX_MINS_ASSETS
    )
    assert all(
        asset.key.to_user_string().startswith("silver_index_mins_")
        for asset in SILVER_INDEX_MINS_ASSETS
    )


def test_index_mins_dependency_graph_keeps_native_and_derived_sources_separate() -> None:
    raw_by_name = {asset.key.to_user_string(): asset for asset in RAW_INDEX_MINS_ASSETS}
    silver_by_name = {
        asset.key.to_user_string(): asset for asset in SILVER_INDEX_MINS_ASSETS
    }
    for frequency in (1, 5, 15, 30, 60):
        raw_dependencies = raw_by_name[f"raw_index_mins_{frequency}m"].dependency_keys
        assert {key.to_user_string() for key in raw_dependencies} == {"silver_index_basic"}
        assert (
            next(iter(silver_by_name[f"silver_index_mins_{frequency}m"].dependency_keys))
            == raw_by_name[f"raw_index_mins_{frequency}m"].key
        )
    assert silver_by_name["silver_index_mins_90m"].dependency_keys == {
        silver_by_name["silver_index_mins_30m"].key
    }
    assert silver_by_name["silver_index_mins_120m"].dependency_keys == {
        silver_by_name["silver_index_mins_60m"].key
    }


def test_index_mins_checks_are_single_partition_blocking_checks() -> None:
    assert len(RAW_CHECKS) + len(SILVER_CHECKS) == 12
    for check in (*RAW_CHECKS, *SILVER_CHECKS):
        specs = tuple(check.check_specs)
        assert len(specs) == 1
        assert specs[0].blocking is True
        assert specs[0].partitions_def is cn_a_index_mins_trade_days
        assert specs[0].name.endswith("_core_check")


def test_index_mins_jobs_select_only_their_own_layer_and_partition_set() -> None:
    raw_selection = str(raw_index_mins_update_job.selection)
    silver_selection = str(silver_index_mins_update_job.selection)
    for asset in RAW_INDEX_MINS_ASSETS:
        assert asset.key.to_user_string() in raw_selection
        assert asset.key.to_user_string() not in silver_selection
    for asset in SILVER_INDEX_MINS_ASSETS:
        assert asset.key.to_user_string() in silver_selection
        assert asset.key.to_user_string() not in raw_selection
    assert "AssetChecksForAssetKeysSelection" in raw_selection
    assert "AssetChecksForAssetKeysSelection" in silver_selection
    assert raw_index_mins_update_job.partitions_def is cn_a_index_mins_trade_days
    assert silver_index_mins_update_job.partitions_def is cn_a_index_mins_trade_days


def test_index_mins_catalog_has_one_governed_core_check_per_asset() -> None:
    entries = [
        entry
        for entry in list_lake_asset_catalog_entries()
        if entry.dataset_id == "index_mins"
    ]
    expected_asset_names = (
        *INDEX_MINS_RAW_ASSET_NAMES,
        *INDEX_MINS_SILVER_ASSET_NAMES,
        *INDEX_MINS_GOLD_ASSET_NAMES,
    )
    expected_check_names = (
        *INDEX_MINS_RAW_CHECKS,
        *INDEX_MINS_SILVER_CHECKS,
        *INDEX_MINS_GOLD_CHECKS,
    )
    assert {entry.asset_key for entry in entries} == set(expected_asset_names)
    assert {
        entry.blocking_check_names[0] for entry in entries
    } == set(expected_check_names)
    for entry in entries:
        assert entry.blocking_check_names == (f"{entry.asset_key}_core_check",)
        assert entry.partition_model.value.endswith("index_mins")
