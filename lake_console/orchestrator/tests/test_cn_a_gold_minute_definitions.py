import dagster as dg

from orchestrator.definitions import defs as project_defs
from orchestrator.defs.assets.index_mins_gold import GOLD_INDEX_MINS_ASSETS
from orchestrator.defs.assets.index_mins_silver_defs import SILVER_INDEX_MINS_ASSETS
from orchestrator.defs.assets.major_index_mins_gold import GOLD_MAJOR_INDEX_MINS_ASSETS
from orchestrator.defs.assets.major_index_mins_silver import (
    SILVER_MAJOR_INDEX_MINS_ASSETS,
)
from orchestrator.defs.checks.index_mins_gold_checks import (
    GOLD_INDEX_MINS_CHECK_DEFS,
)
from orchestrator.defs.checks.major_index_mins_gold_checks import (
    GOLD_MAJOR_INDEX_MINS_CHECK_DEFS,
)
from orchestrator.defs.jobs.index_mins_gold import gold_index_mins_update_job
from orchestrator.defs.jobs.major_index_mins_gold import (
    gold_major_index_mins_update_job,
)
from orchestrator.defs.partitions import (
    cn_a_index_mins_trade_days,
    cn_major_index_mins_trade_days,
)
from orchestrator.defs.run_contracts.cn_a_derived_minute_bars import (
    CN_A_GOLD_MINUTE_FREQS,
    CN_A_GOLD_MINUTE_SOURCE_FREQ_BY_TARGET,
)
from orchestrator.defs.run_contracts.index_mins import (
    INDEX_MINS_GOLD_ASSET_NAMES,
    INDEX_MINS_GOLD_CHECKS,
)
from orchestrator.defs.run_contracts.major_index_mins import (
    MAJOR_INDEX_MINS_GOLD_ASSET_KEYS,
    MAJOR_INDEX_MINS_GOLD_CHECKS,
)
from orchestrator.defs.sensors.index_mins_gold_sensor import (
    gold_index_mins_update_job_sensor,
)
from orchestrator.defs.sensors.major_index_mins_gold_sensor import (
    gold_major_index_mins_update_job_sensor,
)


def _asset_by_freq(definitions):
    return dict(zip(CN_A_GOLD_MINUTE_FREQS, definitions, strict=True))


def test_gold_assets_depend_on_the_frozen_silver_source_frequency() -> None:
    for gold_assets, silver_assets, expected_names, partitions_def in (
        (
            GOLD_INDEX_MINS_ASSETS,
            SILVER_INDEX_MINS_ASSETS,
            INDEX_MINS_GOLD_ASSET_NAMES,
            cn_a_index_mins_trade_days,
        ),
        (
            GOLD_MAJOR_INDEX_MINS_ASSETS,
            SILVER_MAJOR_INDEX_MINS_ASSETS,
            MAJOR_INDEX_MINS_GOLD_ASSET_KEYS,
            cn_major_index_mins_trade_days,
        ),
    ):
        silver_by_freq = _asset_by_freq(silver_assets)
        for target_freq, expected_name, definition in zip(
            CN_A_GOLD_MINUTE_FREQS,
            expected_names,
            gold_assets,
            strict=True,
        ):
            assert definition.key.to_user_string() == expected_name
            assert definition.partitions_def is partitions_def
            source_freq = CN_A_GOLD_MINUTE_SOURCE_FREQ_BY_TARGET[target_freq]
            assert definition.asset_deps[definition.key] == {
                silver_by_freq[source_freq].key
            }


def test_gold_checks_are_single_partition_blocking_checks() -> None:
    for check_defs, check_names, partitions_def in (
        (
            GOLD_INDEX_MINS_CHECK_DEFS,
            INDEX_MINS_GOLD_CHECKS,
            cn_a_index_mins_trade_days,
        ),
        (
            GOLD_MAJOR_INDEX_MINS_CHECK_DEFS,
            MAJOR_INDEX_MINS_GOLD_CHECKS,
            cn_major_index_mins_trade_days,
        ),
    ):
        assert len(check_defs) == 7
        specs = tuple(next(iter(definition.check_specs)) for definition in check_defs)
        assert tuple(spec.name for spec in specs) == tuple(check_names)
        assert all(spec.blocking for spec in specs)
        assert all(spec.partitions_def is partitions_def for spec in specs)


def test_gold_jobs_select_only_their_seven_assets_and_checks() -> None:
    graph = project_defs().resolve_asset_graph()
    for job, assets, checks in (
        (
            gold_index_mins_update_job,
            GOLD_INDEX_MINS_ASSETS,
            GOLD_INDEX_MINS_CHECK_DEFS,
        ),
        (
            gold_major_index_mins_update_job,
            GOLD_MAJOR_INDEX_MINS_ASSETS,
            GOLD_MAJOR_INDEX_MINS_CHECK_DEFS,
        ),
    ):
        expected_asset_keys = {definition.key for definition in assets}
        expected_check_keys = {
            next(iter(definition.check_specs)).key for definition in checks
        }
        assert job.selection.resolve(graph) == expected_asset_keys
        assert job.selection.resolve_checks(graph) == expected_check_keys


def test_gold_sensors_are_stopped_and_bound_to_the_expected_jobs() -> None:
    assert gold_index_mins_update_job_sensor.default_status is (
        dg.DefaultSensorStatus.STOPPED
    )
    assert gold_index_mins_update_job_sensor.job_name == (
        gold_index_mins_update_job.name
    )
    assert gold_major_index_mins_update_job_sensor.default_status is (
        dg.DefaultSensorStatus.STOPPED
    )
    assert gold_major_index_mins_update_job_sensor.job_name == (
        gold_major_index_mins_update_job.name
    )
