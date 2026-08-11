import dagster as dg

from orchestrator.definitions import defs as project_defs
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
    major_index_mins_technical_checks,
    major_index_mins_technical_state_asset_key,
    major_index_mins_technical_state_checks,
)


def _expected_technical_check_keys() -> set[dg.AssetCheckKey]:
    return {
        dg.AssetCheckKey(
            dg.AssetKey(major_index_mins_technical_asset_key(freq)),
            name,
        )
        for freq in MAJOR_INDEX_MINS_TECHNICAL_FREQS
        for name in major_index_mins_technical_checks(freq)
    }


def _expected_state_check_keys() -> set[dg.AssetCheckKey]:
    return {
        dg.AssetCheckKey(
            dg.AssetKey(major_index_mins_technical_state_asset_key(freq)),
            name,
        )
        for freq in MAJOR_INDEX_MINS_TECHNICAL_FREQS
        for name in major_index_mins_technical_state_checks(freq)
    }


def _expected_asset_keys() -> set[dg.AssetKey]:
    return {
        dg.AssetKey(asset_key)
        for freq in MAJOR_INDEX_MINS_TECHNICAL_FREQS
        for asset_key in (
            major_index_mins_technical_asset_key(freq),
            major_index_mins_technical_state_asset_key(freq),
        )
    }


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


def test_project_definitions_register_exactly_fourteen_assets_and_seventy_checks() -> None:
    definitions = project_defs()
    asset_graph = definitions.resolve_asset_graph()
    expected_assets = _expected_asset_keys()
    expected_technical_checks = _expected_technical_check_keys()
    expected_state_checks = _expected_state_check_keys()
    expected_checks = expected_technical_checks | expected_state_checks

    actual_family_assets = {
        asset_key
        for asset_key in asset_graph.get_all_asset_keys()
        if asset_key.to_user_string().startswith("gold_major_index_mins_technical")
    }
    actual_checks = {
        check_key
        for check_key in asset_graph.asset_check_keys
        if check_key.asset_key in expected_assets
    }
    actual_specs = [
        spec
        for definition in definitions.asset_checks or []
        for spec in definition.check_specs
        if spec.asset_key in expected_assets
    ]

    assert actual_family_assets == expected_assets
    assert len(actual_family_assets) == 14
    assert actual_checks == expected_checks
    assert len(actual_checks & expected_technical_checks) == 42
    assert len(actual_checks & expected_state_checks) == 28
    assert len(actual_specs) == 70
    assert {spec.key for spec in actual_specs} == expected_checks
    assert all(spec.blocking is True for spec in actual_specs)
    assert all(
        spec.partitions_def is cn_major_index_mins_trade_days for spec in actual_specs
    )
    dg.Definitions.validate_loadable(definitions)


def test_m6_daily_job_selects_exactly_fourteen_assets_and_seventy_checks() -> None:
    definitions = project_defs()
    asset_graph = definitions.resolve_asset_graph()
    expected_assets = _expected_asset_keys()
    expected_checks = _expected_technical_check_keys() | _expected_state_check_keys()
    selected_assets = gold_major_index_mins_technical_daily_update_job.selection.resolve(
        asset_graph
    )
    selected_checks = (
        gold_major_index_mins_technical_daily_update_job.selection.resolve_checks(
            asset_graph
        )
    )

    assert gold_major_index_mins_technical_daily_update_job.name == (
        MAJOR_INDEX_MINS_TECHNICAL_JOB_NAME
    )
    assert gold_major_index_mins_technical_daily_update_job.partitions_def is (
        cn_major_index_mins_trade_days
    )
    assert selected_assets == expected_assets
    assert len(selected_assets) == 14
    assert selected_checks == expected_checks
    assert len(selected_checks) == 70
