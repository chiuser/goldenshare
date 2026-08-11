from orchestrator.defs.assets.major_index_mins_silver import (
    SILVER_MAJOR_INDEX_MINS_ASSETS,
)
from orchestrator.defs.assets.major_index_mins_technical import (
    GOLD_MAJOR_INDEX_MINS_TECHNICAL_ASSETS,
)
from orchestrator.defs.jobs.gold_major_index_mins_technical_daily_update import (
    gold_major_index_mins_technical_daily_update_job,
)
from orchestrator.defs.partitions import cn_major_index_mins_trade_days
from orchestrator.defs.run_contracts.major_index_mins_technical import (
    MAJOR_INDEX_MINS_TECHNICAL_FREQS,
    MAJOR_INDEX_MINS_TECHNICAL_JOB_NAME,
    major_index_mins_technical_asset_key,
    major_index_mins_technical_state_asset_key,
)


def test_seven_multi_assets_freeze_paired_write_boundary_and_dependencies() -> None:
    assert len(GOLD_MAJOR_INDEX_MINS_TECHNICAL_ASSETS) == 7

    for freq, definition, upstream in zip(
        MAJOR_INDEX_MINS_TECHNICAL_FREQS,
        GOLD_MAJOR_INDEX_MINS_TECHNICAL_ASSETS,
        SILVER_MAJOR_INDEX_MINS_ASSETS,
        strict=True,
    ):
        technical_key = major_index_mins_technical_asset_key(freq)
        state_key = major_index_mins_technical_state_asset_key(freq)
        assert definition.can_subset is False
        assert {key.to_user_string() for key in definition.keys} == {
            technical_key,
            state_key,
        }
        assert definition.asset_deps == {
            key: {upstream.key} for key in definition.keys
        }
        specs = {spec.key.to_user_string(): spec for spec in definition.specs}
        for asset_key, paired_key in (
            (technical_key, state_key),
            (state_key, technical_key),
        ):
            spec = specs[asset_key]
            assert spec.partitions_def is cn_major_index_mins_trade_days
            assert spec.group_name == "index"
            assert spec.tags == {
                "goldenshare/layer": "gold",
                "goldenshare/data_domain": "derived_metric",
            }
            assert spec.metadata["goldenshare/source_system"] == "derived"
            assert spec.metadata["goldenshare/freq"] == freq
            assert spec.metadata["goldenshare/paired_asset_key"] == paired_key
            assert (
                spec.metadata["goldenshare/write_boundary"]
                == "m5_daily_multi_asset"
            )


def test_m6_daily_job_selects_exactly_fourteen_assets_and_checks() -> None:
    selected_assets = gold_major_index_mins_technical_daily_update_job.selection.resolve(
        GOLD_MAJOR_INDEX_MINS_TECHNICAL_ASSETS
    )
    expected_keys = {
        key
        for definition in GOLD_MAJOR_INDEX_MINS_TECHNICAL_ASSETS
        for key in definition.keys
    }

    assert gold_major_index_mins_technical_daily_update_job.name == (
        MAJOR_INDEX_MINS_TECHNICAL_JOB_NAME
    )
    assert gold_major_index_mins_technical_daily_update_job.partitions_def is (
        cn_major_index_mins_trade_days
    )
    assert selected_assets == expected_keys
    assert len(selected_assets) == 14
    assert "AssetChecksForAssetKeysSelection" in repr(
        gold_major_index_mins_technical_daily_update_job.selection
    )
