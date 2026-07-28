from pathlib import Path
from types import SimpleNamespace

import duckdb
import pytest

from orchestrator.defs.assets.index_global_raw import raw_index_global
from orchestrator.defs.assets.index_global_silver import silver_index_global
from orchestrator.defs.checks.index_global_checks import _core_check
from orchestrator.defs.catalog import (
    PartitionModel,
    get_lake_asset_catalog_entry,
    get_partition_model_definition,
)
from orchestrator.defs.jobs.index_global import (
    raw_index_global_update_job,
    silver_index_global_update_job,
)
from orchestrator.defs.partitions import cn_global_index_trade_days
from orchestrator.defs.paths import raw_index_global_path, silver_index_global_path
from orchestrator.defs.resources import DuckDBResource, LakeRootResource
from orchestrator.defs.run_contracts.asset_column_schemas import (
    RAW_INDEX_GLOBAL_SCHEMA,
    SILVER_INDEX_GLOBAL_SCHEMA,
)
from orchestrator.defs.run_contracts.index_global import (
    INDEX_GLOBAL_EXPECTED_CODES,
    INDEX_GLOBAL_RAW_CHECKS,
    INDEX_GLOBAL_SILVER_CHECKS,
    IndexGlobalRawConfig,
    validate_index_global_raw_config,
)
from orchestrator.defs.run_contracts.metadata import (
    CHECKED_ROW_COUNT_METADATA_KEY,
    FAILED_ROW_COUNT_METADATA_KEY,
)


PARTITION_KEY = "2022-01-04"


def _write_empty(path: Path, schema: tuple[object, ...]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    definitions = ", ".join(f'"{column.name}" {column.type}' for column in schema)
    select_columns = ", ".join(
        f'CAST(NULL AS {column.type}) AS "{column.name}"' for column in schema
    )
    with duckdb.connect() as connection:
        connection.execute(f"CREATE TABLE empty_rows ({definitions})")
        connection.execute(
            f"COPY (SELECT {select_columns} FROM empty_rows) TO '{path}' (FORMAT PARQUET)"
        )


def test_assets_checks_jobs_and_catalog_share_the_dedicated_partition_set() -> None:
    assert raw_index_global.partitions_def is cn_global_index_trade_days
    assert silver_index_global.partitions_def is cn_global_index_trade_days
    assert raw_index_global_update_job.partitions_def is cn_global_index_trade_days
    assert silver_index_global_update_job.partitions_def is cn_global_index_trade_days
    assert raw_index_global_update_job.name == "raw_index_global_update_job"
    assert silver_index_global_update_job.name == "silver_index_global_update_job"
    assert get_lake_asset_catalog_entry("raw_index_global").blocking_check_names == INDEX_GLOBAL_RAW_CHECKS
    assert get_lake_asset_catalog_entry("silver_index_global").blocking_check_names == INDEX_GLOBAL_SILVER_CHECKS
    assert get_partition_model_definition(
        PartitionModel.TRADE_DATE_PARTITION_RAW_INDEX_GLOBAL
    ).asset_family == "index_global"
    assert get_partition_model_definition(
        PartitionModel.TRADE_DATE_PARTITION_SILVER_INDEX_GLOBAL
    ).asset_family == "index_global"


def test_typed_raw_config_must_match_partition() -> None:
    config = IndexGlobalRawConfig(
        trade_date=PARTITION_KEY,
        probe_phase="asia_1",
        slot_key=f"{PARTITION_KEY}:asia_1",
    )
    assert validate_index_global_raw_config(config, partition_key=PARTITION_KEY) == PARTITION_KEY
    with pytest.raises(ValueError, match="does not match"):
        validate_index_global_raw_config(config, partition_key="2022-01-05")
    with pytest.raises(ValueError, match="late_empty"):
        validate_index_global_raw_config(
            IndexGlobalRawConfig(
                trade_date=PARTITION_KEY,
                probe_phase="late_empty",
                slot_key=PARTITION_KEY,
            ),
            partition_key=PARTITION_KEY,
        )


def test_empty_raw_and_silver_files_pass_core_contract(tmp_path: Path) -> None:
    raw_path = raw_index_global_path(tmp_path, PARTITION_KEY)
    silver_path = silver_index_global_path(tmp_path, PARTITION_KEY)
    _write_empty(raw_path, RAW_INDEX_GLOBAL_SCHEMA)
    _write_empty(silver_path, SILVER_INDEX_GLOBAL_SCHEMA)
    context = SimpleNamespace(partition_keys=(PARTITION_KEY,))
    lake_root = LakeRootResource(root_path=str(tmp_path))
    duckdb_resource = DuckDBResource()

    raw_result = _core_check(
        context=context,
        lake_root=lake_root,
        duckdb_resource=duckdb_resource,
        path=raw_path,
        schema=RAW_INDEX_GLOBAL_SCHEMA,
    )
    silver_result = _core_check(
        context=context,
        lake_root=lake_root,
        duckdb_resource=duckdb_resource,
        path=silver_path,
        schema=SILVER_INDEX_GLOBAL_SCHEMA,
    )
    assert raw_result.passed is True
    assert silver_result.passed is True
    assert raw_result.metadata[CHECKED_ROW_COUNT_METADATA_KEY].value == 0
    assert raw_result.metadata[FAILED_ROW_COUNT_METADATA_KEY].value == 0


def test_core_check_rejects_unknown_code_but_does_not_require_all_codes(tmp_path: Path) -> None:
    path = raw_index_global_path(tmp_path, PARTITION_KEY)
    path.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect() as connection:
        connection.execute(
            f"""
            COPY (
              SELECT 'XIN9'::VARCHAR AS ts_code, '20220104'::VARCHAR AS trade_date,
                     1.0::DOUBLE AS open, 1.0::DOUBLE AS close, 1.0::DOUBLE AS high,
                     1.0::DOUBLE AS low, 1.0::DOUBLE AS pre_close, 0.0::DOUBLE AS change,
                     0.0::DOUBLE AS pct_chg, 0.0::DOUBLE AS swing, 1.0::DOUBLE AS vol,
                     NULL::DOUBLE AS amount
              UNION ALL
              SELECT 'UNKNOWN'::VARCHAR, '20220104'::VARCHAR, 1.0, 1.0, 1.0, 1.0,
                     1.0, 0.0, 0.0, 0.0, 1.0, NULL
            ) TO '{path}' (FORMAT PARQUET)
            """
        )
    result = _core_check(
        context=SimpleNamespace(partition_keys=(PARTITION_KEY,)),
        lake_root=LakeRootResource(root_path=str(tmp_path)),
        duckdb_resource=DuckDBResource(),
        path=path,
        schema=RAW_INDEX_GLOBAL_SCHEMA,
    )
    assert result.passed is False
    assert "ts_code_non_null_and_known" in result.metadata["goldenshare/failed_rule_names"].value
    assert len(INDEX_GLOBAL_EXPECTED_CODES) == 21
