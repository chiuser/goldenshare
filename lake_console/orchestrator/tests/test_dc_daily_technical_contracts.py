from pathlib import Path

from orchestrator.defs.catalog.lake_assets import (
    EventPolicy,
    PartitionModel,
    PartitionPhysicalLayout,
    get_lake_asset_catalog_entry,
    get_partition_model_definition,
)
from orchestrator.defs.paths import gold_dc_daily_technical_path
from orchestrator.defs.run_contracts.asset_column_schemas import (
    GOLD_DC_DAILY_TECHNICAL_SCHEMA,
)
from orchestrator.defs.run_contracts.dc_daily_technical import (
    DC_DAILY_TECHNICAL_BOLL,
    DC_DAILY_TECHNICAL_BOLL_STD_DDOF,
    DC_DAILY_TECHNICAL_CHECKS,
    DC_DAILY_TECHNICAL_HISTORY_START_DATE,
    DC_DAILY_TECHNICAL_INDICATOR_VERSION,
    DC_DAILY_TECHNICAL_INPUT_COLUMNS,
    DC_DAILY_TECHNICAL_KDJ,
    DC_DAILY_TECHNICAL_MACD,
    DC_DAILY_TECHNICAL_MA_PERIODS,
    DC_DAILY_TECHNICAL_PARAMS_KEY,
    DC_DAILY_TECHNICAL_SENSOR_WINDOW_LIMIT,
)


def _column_names() -> tuple[str, ...]:
    return tuple(column.name for column in GOLD_DC_DAILY_TECHNICAL_SCHEMA)


def test_contract_constants_are_frozen() -> None:
    assert DC_DAILY_TECHNICAL_HISTORY_START_DATE == "2024-01-02"
    assert DC_DAILY_TECHNICAL_MA_PERIODS == (5, 10, 15, 20, 30, 60, 120, 250)
    assert DC_DAILY_TECHNICAL_MACD == (12, 26, 9)
    assert DC_DAILY_TECHNICAL_KDJ == (9, 3, 3)
    assert DC_DAILY_TECHNICAL_BOLL == (20, 2)
    assert DC_DAILY_TECHNICAL_BOLL_STD_DDOF == 0
    assert DC_DAILY_TECHNICAL_SENSOR_WINDOW_LIMIT == 10
    assert DC_DAILY_TECHNICAL_INDICATOR_VERSION == "v1"
    assert DC_DAILY_TECHNICAL_PARAMS_KEY == (
        "ma_5_10_15_20_30_60_120_250__"
        "macd_12_26_9__kdj_9_3_3__boll_20_2"
    )


def test_schema_has_one_source_key_and_explicit_warmup_fields() -> None:
    columns = _column_names()
    assert columns[:4] == ("ts_code", "trade_date", "category", "close")
    assert DC_DAILY_TECHNICAL_INPUT_COLUMNS == (
        "ts_code",
        "trade_date",
        "category",
        "close",
        "high",
        "low",
    )
    assert "high" not in columns
    assert "low" not in columns
    assert columns.count("ts_code") == 1
    assert columns.count("trade_date") == 1
    assert columns.count("category") == 1
    assert columns[-3:] == ("observation_count", "params_key", "indicator_version")

    descriptions = {column.name: column.description for column in GOLD_DC_DAILY_TECHNICAL_SCHEMA}
    for period in DC_DAILY_TECHNICAL_MA_PERIODS:
        assert "为空" in descriptions[f"ma_{period}"]
    for column in ("boll_mid", "boll_upper", "boll_lower"):
        assert "为空" in descriptions[column]


def test_path_is_trade_date_partition_single_file() -> None:
    path = gold_dc_daily_technical_path(Path("/tmp/test-lake"), "2026-07-14")
    assert path.as_posix() == (
        "/tmp/test-lake/gold/board/dc_daily_technical/"
        "trade_date=2026-07-14/part-000.parquet"
    )


def test_catalog_entry_is_governed() -> None:
    entry = get_lake_asset_catalog_entry("gold_dc_daily_technical")
    assert entry.dataset_id == "dc_daily_technical"
    assert entry.dataset_name == "板块日线技术指标"
    assert entry.layer.value == "gold"
    assert entry.data_domain.value == "derived_metric"
    assert entry.group_name == "board"
    assert entry.blocking_check_names == DC_DAILY_TECHNICAL_CHECKS
    assert entry.partition_model is PartitionModel.TRADE_DATE_PARTITION_GOLD_DC_DAILY_TECHNICAL
    assert entry.write_policy.value == "partition_file_atomic_replace"
    assert entry.event_policy is EventPolicy.SUPPORTS_RUNLESS_EVENT_BACKFILL
    assert entry.bootstrap_sources
    assert entry.performance_contract.batch_grain == "trade_date"
    assert entry.performance_contract.compute_engine.value == "duckdb_sql"
    assert entry.performance_contract.python_row_loop_allowed is False

    model = get_partition_model_definition(entry.partition_model)
    assert model.physical_layout is PartitionPhysicalLayout.PARTITION_FILE
    assert model.dagster_partition_dimension == "trade_date"
    assert entry.path_template == (
        "data_lake/gold/board/dc_daily_technical/"
        "trade_date={partition_key}/part-000.parquet"
    )


def test_p3_writer_boundary_and_p4_definition_modules() -> None:
    defs_root = Path("src/orchestrator/defs")
    writer_path = defs_root / "assets/dc_daily_technical.py"
    assert writer_path.exists()
    source = writer_path.read_text()
    assert "@dg.asset" not in source
    assert "for row in source" not in source
    assert "pandas" not in source
    for relative_path in (
        "assets/dc_daily_technical_asset.py",
        "checks/dc_daily_technical_checks.py",
        "asset_guards/dc_daily_technical_quality.py",
        "asset_guards/dc_daily_technical_lake_readiness.py",
        "jobs/dc_daily_technical.py",
        "sensors/dc_daily_technical_sensor.py",
        "sensors/dc_daily_technical_repair_sensor.py",
    ):
        assert (defs_root / relative_path).exists()
