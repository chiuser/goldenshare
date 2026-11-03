from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, time, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from orchestrator.defs.catalog import (
    ComputeEngine,
    DataContractSource,
    EventPolicy,
    IngestionSource,
    PartitionModel,
    PartitionModelFamily,
    PartitionPhysicalLayout,
    WritePolicy,
    get_lake_asset_catalog_entry,
    get_partition_model_definition,
    list_lake_asset_entries_by_dataset_id,
)
from orchestrator.defs.partitions import (
    cn_a_etf_mins_trade_days,
    cn_a_index_mins_trade_days,
    cn_a_stock_mins_trade_days,
)
from orchestrator.defs.paths import (
    PATH_TEMPLATE_LAKE_ROOT,
    PATH_TEMPLATE_PARTITION_KEY,
    PATH_TEMPLATE_SNAPSHOT_ID,
    etf_basic_staging_path,
    etf_mins_staging_path,
    raw_etf_basic_snapshot_path,
    raw_etf_mins_path,
    silver_etf_basic_snapshot_path,
    silver_etf_mins_path,
)
from orchestrator.defs.run_contracts.asset_column_schemas import (
    RAW_ETF_MINS_SCHEMA,
    SILVER_ETF_MINS_SCHEMA,
)
from orchestrator.defs.run_contracts.etf_basic import (
    build_etf_basic_silver_snapshot_reference,
)
from orchestrator.defs.run_contracts.etf_mins import (
    ETF_MINS_ASSET_FREQS,
    ETF_MINS_BOOTSTRAP_BATCH_TRADE_DAY_LIMIT,
    ETF_MINS_BOOTSTRAP_DISK_SAFETY_MULTIPLIER,
    ETF_MINS_BOOTSTRAP_MAX_TARGET_FILES,
    ETF_MINS_DIAGNOSTIC_SAMPLE_LIMIT,
    ETF_MINS_HISTORICAL_PROTECTION_CUTOFF,
    ETF_MINS_RAW_APPROVED_POLICY_VERSION,
    ETF_MINS_RAW_DECISION_BLOCKING_REASON_CODES,
    ETF_MINS_RAW_DECISION_WARNING_REASON_CODES,
    ETF_MINS_RAW_OBSERVATION_REASON_CODES,
    ETF_MINS_SENSOR_WINDOW_LIMIT,
    ETF_MINS_SOURCE_COLUMNS,
    ETF_MINS_SOURCE_EXCHANGE_BY_CODE_SUFFIX,
    ETF_MINS_SOURCE_FREQS,
    ETF_SENSOR_WINDOW_START,
    EtfMinsRawConfig,
    EtfMinsRequestableTarget,
    asset_freq_for_etf_mins_source_freq,
    build_etf_mins_prod_coverage_reference,
    build_etf_mins_raw_run_config,
    etf_sensor_window_is_open,
    expected_etf_mins_source_exchange,
    get_etf_mins_raw_decision_policy,
    normalize_etf_mins_asset_freq,
    normalize_etf_mins_source_freq,
    normalize_etf_mins_trade_date,
    normalize_etf_sensor_evaluated_at,
    raw_etf_mins_check_names,
    silver_etf_mins_check_names,
    source_freq_for_etf_mins_asset_freq,
)
from orchestrator.defs.run_contracts.metadata import SourceSystem

# Artificial second listing date, not 159915.SZ's real listing date.
# Hashes are independent SHA256 literals of the documented sorted compact JSON:
# Basic: ts_code/list_date/exchange objects; minute scope: sorted code strings.
_HISTORICAL_TARGETS = (
    EtfMinsRequestableTarget("510300.SH", date(2012, 5, 28), "SH"),
    EtfMinsRequestableTarget("159915.SZ", date(2026, 9, 1), "SZ"),
)
_HISTORICAL_BASIC_HASH = (
    "8c075a8ad076e38f38ef52b46b292decae61aefad5c6a73033de91a08092f01b"
)
_HISTORICAL_CODE_HASH = (
    "eb2a09141693d8ffa619fab66a698c210e3bb425bb9605e7996ed273428e99cc"
)
_LATER_CODE_HASH = "a93a2bf6cc52edb27e642540e204e9a59dd0663dcc8cbe0f4c91b5d30fb27423"


def _historical_basic_reference():  # type: ignore[no-untyped-def]
    return build_etf_basic_silver_snapshot_reference(
        raw_snapshot_hash="a" * 64,
        silver_content_hash="b" * 64,
        raw_uri="/isolated/raw-basic.parquet",
        silver_uri="/isolated/silver-basic.parquet",
        raw_observed_at="2026-09-30T08:00:00+08:00",
        silver_observed_at="2026-09-30T08:01:00+08:00",
        eligibility_as_of="2026-09-30",
        requestable_code_count=2,
        requestable_code_hash=_HISTORICAL_BASIC_HASH,
    )


def _historical_coverage(**overrides):  # type: ignore[no-untyped-def]
    values = {
        "trade_date": "2026-08-28",
        "basic_reference_fingerprint": (
            _historical_basic_reference().reference_fingerprint
        ),
        "expected_code_count": 1,
        "expected_code_hash": _HISTORICAL_CODE_HASH,
        "frequency_coverages": tuple((freq, 1, 1, 0) for freq in ETF_MINS_SOURCE_FREQS),
        "coverage_observed_at": "2026-09-30T21:00:00+08:00",
    }
    values.update(overrides)
    return build_etf_mins_prod_coverage_reference(**values)


@pytest.mark.parametrize(
    ("trade_date", "expected_count", "expected_hash"),
    [
        ("2026-08-28", 1, _HISTORICAL_CODE_HASH),
        ("2026-09-01", 2, _LATER_CODE_HASH),
    ],
)
def test_raw_config_accepts_historical_and_later_listing_scopes(
    trade_date: str, expected_count: int, expected_hash: str
) -> None:
    basic = _historical_basic_reference()
    coverage = _historical_coverage(
        trade_date=trade_date,
        expected_code_count=expected_count,
        expected_code_hash=expected_hash,
        frequency_coverages=tuple(
            (freq, expected_count, expected_count, 0) for freq in ETF_MINS_SOURCE_FREQS
        ),
    )
    result = build_etf_mins_raw_run_config(
        partition_key=trade_date,
        basic_reference=basic,
        requestable_targets=iter(_HISTORICAL_TARGETS),
        prod_coverage_reference=coverage,
    )
    assert set(result["ops"]) == {
        "raw_etf_mins_1m",
        "raw_etf_mins_5m",
        "raw_etf_mins_15m",
        "raw_etf_mins_30m",
        "raw_etf_mins_60m",
    }
    for op in result["ops"].values():
        assert set(op["config"]) == {
            "basic_snapshot_reference",
            "prod_coverage_reference",
        }
        config = EtfMinsRawConfig(**op["config"])
        assert config.basic_snapshot_reference.requestable_code_count == 2
        carried = config.prod_coverage_reference.to_reference()
        assert carried == coverage
        assert carried.expected_code_count == expected_count
        assert carried.expected_code_hash == expected_hash


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"trade_date": "2026-08-27"}, "does not match the partition"),
        ({"basic_reference_fingerprint": "d" * 64}, "different Basic snapshot"),
        ({"expected_code_hash": _LATER_CODE_HASH}, "code hash has changed"),
        (
            {
                "expected_code_count": 2,
                "frequency_coverages": tuple(
                    (freq, 2, 2, 0) for freq in ETF_MINS_SOURCE_FREQS
                ),
            },
            "expected count has changed",
        ),
    ],
)
def test_raw_config_rejects_valid_coverage_bound_to_wrong_inputs(
    overrides: dict[str, object], message: str
) -> None:
    coverage = _historical_coverage(**overrides)
    assert coverage.validate() == coverage  # Not a malformed-fingerprint shortcut.
    with pytest.raises(ValueError, match=message):
        build_etf_mins_raw_run_config(
            partition_key="2026-08-28",
            basic_reference=_historical_basic_reference(),
            requestable_targets=_HISTORICAL_TARGETS,
            prod_coverage_reference=coverage,
        )


@pytest.mark.parametrize(
    "targets",
    [
        _HISTORICAL_TARGETS[:1],
        (
            _HISTORICAL_TARGETS[0],
            EtfMinsRequestableTarget("159916.SZ", date(2026, 9, 1), "SZ"),
        ),
    ],
)
def test_raw_config_rejects_incomplete_or_substituted_basic_targets(targets) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(ValueError, match="targets do not match the frozen Basic"):
        build_etf_mins_raw_run_config(
            partition_key="2026-08-28",
            basic_reference=_historical_basic_reference(),
            requestable_targets=targets,
            prod_coverage_reference=_historical_coverage(),
        )


@pytest.mark.parametrize(
    "coverages",
    [
        (("1min", 1, 1, 0),),
        tuple((freq, 1, 0, 1) for freq in ETF_MINS_SOURCE_FREQS),
    ],
)
def test_raw_config_rejects_missing_frequencies_or_codes(coverages) -> None:  # type: ignore[no-untyped-def]
    invalid = replace(_historical_coverage(), frequency_coverages=coverages)
    with pytest.raises(ValueError, match="five.*frequencies"):
        build_etf_mins_raw_run_config(
            partition_key="2026-08-28",
            basic_reference=_historical_basic_reference(),
            requestable_targets=_HISTORICAL_TARGETS,
            prod_coverage_reference=invalid,
        )


def test_frequency_date_and_exchange_contracts_are_centralized() -> None:
    assert ETF_MINS_SOURCE_FREQS == ("1min", "5min", "15min", "30min", "60min")
    assert ETF_MINS_ASSET_FREQS == (1, 5, 15, 30, 60)
    for asset_freq, source_freq in zip(
        ETF_MINS_ASSET_FREQS,
        ETF_MINS_SOURCE_FREQS,
        strict=True,
    ):
        assert source_freq_for_etf_mins_asset_freq(asset_freq) == source_freq
        assert asset_freq_for_etf_mins_source_freq(source_freq) == asset_freq

    assert normalize_etf_mins_trade_date("2026-08-28") == "2026-08-28"
    assert ETF_MINS_SOURCE_EXCHANGE_BY_CODE_SUFFIX == {
        "SH": "XSHG",
        "SZ": "XSHE",
    }
    assert expected_etf_mins_source_exchange("510300.SH") == "XSHG"
    assert expected_etf_mins_source_exchange("159915.sz") == "XSHE"

    with pytest.raises(ValueError):
        normalize_etf_mins_source_freq("1m")
    with pytest.raises(ValueError):
        normalize_etf_mins_asset_freq(True)
    with pytest.raises(ValueError):
        normalize_etf_mins_trade_date("20260828")
    with pytest.raises(ValueError):
        expected_etf_mins_source_exchange("920001.BJ")


def test_raw_validator_consumes_the_single_exchange_mapping() -> None:
    validator_source = (
        Path(__file__).parents[1]
        / "src/orchestrator/defs/asset_guards/etf_mins_lake_readiness.py"
    ).read_text()

    assert "ETF_MINS_SOURCE_EXCHANGE_BY_CODE_SUFFIX" in validator_source
    assert "'XSHG'" not in validator_source
    assert "'XSHE'" not in validator_source


def test_operational_constants_match_the_approved_lld() -> None:
    assert ETF_MINS_SENSOR_WINDOW_LIMIT == 10
    assert ETF_MINS_BOOTSTRAP_BATCH_TRADE_DAY_LIMIT == 20
    assert ETF_MINS_BOOTSTRAP_MAX_TARGET_FILES == 10_000
    assert ETF_MINS_BOOTSTRAP_DISK_SAFETY_MULTIPLIER == 1.25
    assert ETF_MINS_DIAGNOSTIC_SAMPLE_LIMIT == 20
    assert ETF_MINS_HISTORICAL_PROTECTION_CUTOFF.isoformat() == "2026-01-01"
    assert ETF_SENSOR_WINDOW_START == time(21, 0)


def test_etf_sensor_window_is_21_to_midnight_in_shanghai() -> None:
    shanghai = ZoneInfo("Asia/Shanghai")

    assert not etf_sensor_window_is_open(
        datetime(2026, 8, 31, 20, 59, 59, tzinfo=shanghai)
    )
    assert etf_sensor_window_is_open(datetime(2026, 8, 31, 21, 0, 0, tzinfo=shanghai))
    assert etf_sensor_window_is_open(datetime(2026, 8, 31, 23, 59, 59, tzinfo=shanghai))
    assert not etf_sensor_window_is_open(datetime(2026, 9, 1, 0, 0, 0, tzinfo=shanghai))

    utc_boundary = datetime(2026, 8, 31, 13, 0, 0, tzinfo=timezone.utc)
    assert etf_sensor_window_is_open(utc_boundary)
    assert normalize_etf_sensor_evaluated_at(utc_boundary).hour == 21


def test_raw_decision_policy_freezes_the_approved_grid_and_reason_mapping() -> None:
    policy = get_etf_mins_raw_decision_policy(ETF_MINS_RAW_APPROVED_POLICY_VERSION)

    assert policy.version == "etf_mins_gap_policy_v1"
    assert {
        source_freq: len(clock_times)
        for source_freq, clock_times in policy.expected_clock_times_by_source_freq
    } == {
        "1min": 241,
        "5min": 49,
        "15min": 17,
        "30min": 9,
        "60min": 5,
    }
    assert policy.expected_clock_times("1min")[:2] == (
        "09:30:00",
        "09:31:00",
    )
    assert policy.expected_clock_times("1min")[120:122] == (
        "11:30:00",
        "13:01:00",
    )
    assert policy.expected_clock_times("60min") == (
        "09:30:00",
        "10:30:00",
        "11:30:00",
        "14:00:00",
        "15:00:00",
    )
    assert policy.blocking_reason_codes == (ETF_MINS_RAW_DECISION_BLOCKING_REASON_CODES)
    assert policy.warning_reason_codes == ETF_MINS_RAW_DECISION_WARNING_REASON_CODES
    assert "internal_grid_gap_candidate" in ETF_MINS_RAW_OBSERVATION_REASON_CODES
    assert "internal_grid_gap_candidate" not in policy.blocking_reason_codes
    assert "zero_volume_bar_observed" not in policy.warning_reason_codes
    assert "full_zero_volume_etf_day_observed" in policy.warning_reason_codes
    assert len(policy.policy_hash) == 64

    with pytest.raises(ValueError, match="not registered"):
        get_etf_mins_raw_decision_policy("operator-supplied-threshold")


def test_minute_schema_is_an_exact_eleven_column_copy_contract() -> None:
    raw_columns = tuple(column.name for column in RAW_ETF_MINS_SCHEMA)
    silver_columns = tuple(column.name for column in SILVER_ETF_MINS_SCHEMA)
    raw_types = tuple(column.type for column in RAW_ETF_MINS_SCHEMA)
    silver_types = tuple(column.type for column in SILVER_ETF_MINS_SCHEMA)

    assert raw_columns == ETF_MINS_SOURCE_COLUMNS
    assert silver_columns == ETF_MINS_SOURCE_COLUMNS
    assert raw_types == silver_types
    assert raw_types == (
        "VARCHAR",
        "VARCHAR",
        "TIMESTAMP",
        "DOUBLE",
        "DOUBLE",
        "DOUBLE",
        "DOUBLE",
        "BIGINT",
        "DOUBLE",
        "DOUBLE",
        "VARCHAR",
    )
    assert "trade_date" not in raw_columns


def test_paths_match_formal_lake_and_operation_staging_contracts() -> None:
    root = Path("data_lake")
    staging_root = Path("data_lake_staging")
    snapshot_id = "a" * 64

    assert raw_etf_basic_snapshot_path(root, snapshot_id).as_posix() == (
        f"data_lake/raw/tushare/etf_basic/snapshot_id={snapshot_id}/part-000.parquet"
    )
    assert silver_etf_basic_snapshot_path(root, snapshot_id).as_posix() == (
        f"data_lake/silver/basic/etf_basic/snapshot_id={snapshot_id}/part-000.parquet"
    )
    assert raw_etf_mins_path(root, 5, "2026-08-28").as_posix() == (
        "data_lake/raw/tushare/etf_mins/freq=5min/"
        "trade_date=2026-08-28/part-000.parquet"
    )
    assert silver_etf_mins_path(root, "5min", "2026-08-28").as_posix() == (
        "data_lake/silver/quote/etf_mins/freq=5min/"
        "trade_date=2026-08-28/part-000.parquet"
    )
    assert etf_basic_staging_path(staging_root, "run-1", "raw").as_posix() == (
        "data_lake_staging/etf_basic/run_id=run-1/raw/part-000.parquet"
    )
    assert etf_mins_staging_path(
        staging_root,
        "operation-1",
        "silver",
        60,
        "2026-08-28",
    ).as_posix() == (
        "data_lake_staging/etf_mins/operation_id=operation-1/silver/"
        "freq=60min/trade_date=2026-08-28/part-000.parquet"
    )

    assert (
        raw_etf_basic_snapshot_path(
            PATH_TEMPLATE_LAKE_ROOT,
            PATH_TEMPLATE_SNAPSHOT_ID,
        )
        .as_posix()
        .endswith("snapshot_id={snapshot_id}/part-000.parquet")
    )
    assert (
        raw_etf_mins_path(
            PATH_TEMPLATE_LAKE_ROOT,
            1,
            PATH_TEMPLATE_PARTITION_KEY,
        )
        .as_posix()
        .endswith("freq=1min/trade_date={partition_key}/part-000.parquet")
    )


@pytest.mark.parametrize(
    ("builder", "args"),
    (
        (raw_etf_basic_snapshot_path, (Path("lake"), "A" * 64)),
        (raw_etf_basic_snapshot_path, (Path("lake"), "../bad")),
        (raw_etf_mins_path, (Path("lake"), "2min", "2026-08-28")),
        (raw_etf_mins_path, (Path("lake"), "1min", "20260828")),
        (etf_basic_staging_path, (Path("staging"), "../bad", "raw")),
        (etf_basic_staging_path, (Path("staging"), "run-1", "gold")),
        (
            etf_mins_staging_path,
            (Path("staging"), "operation/1", "raw", 1, "2026-08-28"),
        ),
    ),
)
def test_paths_reject_unregistered_or_unsafe_components(builder, args) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(ValueError):
        builder(*args)


def test_etf_minutes_use_a_dedicated_dynamic_partition_definition() -> None:
    assert cn_a_etf_mins_trade_days.name == "cn_a_etf_mins_trade_days"
    assert cn_a_etf_mins_trade_days is not cn_a_index_mins_trade_days
    assert cn_a_etf_mins_trade_days is not cn_a_stock_mins_trade_days


def test_catalog_registers_twelve_contract_only_etf_entries() -> None:
    basic_entries = list_lake_asset_entries_by_dataset_id("etf_basic")
    minute_entries = list_lake_asset_entries_by_dataset_id("etf_mins")
    assert len(basic_entries) == 2
    assert len(minute_entries) == 10

    raw_basic = get_lake_asset_catalog_entry("raw_tushare_etf_basic")
    silver_basic = get_lake_asset_catalog_entry("silver_etf_basic")
    assert raw_basic.source_system is SourceSystem.TUSHARE
    assert raw_basic.data_contract_source is DataContractSource.TUSHARE_RAW_CONTRACT
    assert raw_basic.ingestion_sources == (IngestionSource.TUSHARE_API,)
    assert raw_basic.default_daily_ingestion_source is IngestionSource.TUSHARE_API
    assert raw_basic.bootstrap_sources == ()
    assert raw_basic.write_policy is WritePolicy.SINGLE_FILE_ATOMIC_REPLACE
    assert raw_basic.event_policy is EventPolicy.DAGSTER_RUN_ONLY
    assert raw_basic.partition_model is PartitionModel.FULL_FILE_RAW_ETF_BASIC_VERSIONED
    assert raw_basic.source_api == "etf_basic"
    assert raw_basic.source_doc == "docs/sources/tushare/ETF专题/0385_ETF基础信息.md"
    assert silver_basic.source_system is SourceSystem.DERIVED
    assert silver_basic.bootstrap_sources == ()
    assert silver_basic.partition_model is (
        PartitionModel.FULL_FILE_SILVER_ETF_BASIC_VERSIONED
    )

    for freq in ETF_MINS_ASSET_FREQS:
        raw_entry = get_lake_asset_catalog_entry(f"raw_etf_mins_{freq}m")
        silver_entry = get_lake_asset_catalog_entry(f"silver_etf_mins_{freq}m")
        assert raw_entry.source_system is SourceSystem.TUSHARE
        assert raw_entry.data_contract_source is DataContractSource.TUSHARE_RAW_CONTRACT
        assert raw_entry.ingestion_sources == (IngestionSource.PROD_DB_READONLY,)
        assert raw_entry.default_daily_ingestion_source is (
            IngestionSource.PROD_DB_READONLY
        )
        assert raw_entry.bootstrap_sources == (IngestionSource.PROD_DB_READONLY,)
        assert raw_entry.blocking_check_names == raw_etf_mins_check_names(freq)
        assert raw_entry.performance_contract.compute_engine is ComputeEngine.DUCKDB_SQL
        assert "prod-raw-db.raw_tushare.etf_minute_bar" in raw_entry.notes
        assert silver_entry.source_system is SourceSystem.DERIVED
        assert silver_entry.bootstrap_sources == (IngestionSource.DERIVED_FROM_ASSETS,)
        assert silver_entry.blocking_check_names == silver_etf_mins_check_names(freq)
        assert raw_entry.event_policy is EventPolicy.SUPPORTS_RUNLESS_EVENT_BACKFILL
        assert silver_entry.event_policy is EventPolicy.SUPPORTS_RUNLESS_EVENT_BACKFILL


def test_partition_models_match_their_physical_layouts() -> None:
    expected = {
        PartitionModel.FULL_FILE_RAW_ETF_BASIC_VERSIONED: (
            PartitionModelFamily.FULL_FILE,
            PartitionPhysicalLayout.SINGLE_FILE,
        ),
        PartitionModel.FULL_FILE_SILVER_ETF_BASIC_VERSIONED: (
            PartitionModelFamily.FULL_FILE,
            PartitionPhysicalLayout.SINGLE_FILE,
        ),
        PartitionModel.TRADE_DATE_PARTITION_RAW_ETF_MINS: (
            PartitionModelFamily.TRADE_DATE_PARTITION,
            PartitionPhysicalLayout.PARTITION_FILE,
        ),
        PartitionModel.TRADE_DATE_PARTITION_SILVER_ETF_MINS: (
            PartitionModelFamily.TRADE_DATE_PARTITION,
            PartitionPhysicalLayout.PARTITION_FILE,
        ),
    }
    for model, (family, layout) in expected.items():
        definition = get_partition_model_definition(model)
        assert definition.family is family
        assert definition.physical_layout is layout
