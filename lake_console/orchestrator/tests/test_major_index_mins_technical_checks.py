from pathlib import Path

import duckdb

from orchestrator.defs.checks.major_index_mins_technical_checks import (
    GOLD_MAJOR_INDEX_MINS_TECHNICAL_CHECK_DEFINITIONS,
    GOLD_MAJOR_INDEX_MINS_TECHNICAL_STATE_CHECK_DEFINITIONS,
    evaluate_major_index_mins_technical_check,
    evaluate_major_index_mins_technical_state_check,
)
from orchestrator.defs.duckdb_sql import copy_query_to_parquet, read_parquet
from orchestrator.defs.io.major_index_mins_technical_writer import (
    write_major_index_mins_technical_partition,
)
from orchestrator.defs.partitions import cn_major_index_mins_trade_days
from orchestrator.defs.paths import (
    gold_major_index_mins_technical_state_path,
    silver_major_index_mins_path,
)
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.run_contracts.major_index_mins_technical import (
    MAJOR_INDEX_MINS_TECHNICAL_FREQS,
    expected_major_index_mins_technical_codes,
    major_index_mins_technical_asset_key,
    major_index_mins_technical_checks,
    major_index_mins_technical_state_asset_key,
    major_index_mins_technical_state_checks,
)

DAY_1 = "2009-01-05"
DAY_2 = "2009-01-06"
FREQ = 120


def _write_silver_partition(root: Path, trade_date: str, close_base: float) -> Path:
    path = silver_major_index_mins_path(root, f"{FREQ}min", trade_date)
    path.parent.mkdir(parents=True, exist_ok=True)
    codes = expected_major_index_mins_technical_codes(trade_date)
    rows = [
        (
            code,
            f"{FREQ}min",
            f"{trade_date} {trade_time}",
            close_base + code_index + bar_index + 1.0,
            close_base + code_index + bar_index - 1.0,
            close_base + code_index + bar_index,
        )
        for code_index, code in enumerate(codes)
        for bar_index, trade_time in enumerate(("11:30:00", "15:00:00"))
    ]
    with duckdb.connect(":memory:") as connection:
        connection.execute(
            """
            CREATE TABLE rows (
              ts_code VARCHAR, freq VARCHAR, trade_time TIMESTAMP,
              high DOUBLE, low DOUBLE, close DOUBLE
            )
            """
        )
        connection.executemany("INSERT INTO rows VALUES (?, ?, ?, ?, ?, ?)", rows)
        connection.execute(
            copy_query_to_parquet(
                "SELECT * FROM rows ORDER BY ts_code, trade_time", path
            )
        )
    return path


def _materialize_two_days(lake_root: Path, staging_root: Path) -> None:
    _write_silver_partition(lake_root, DAY_1, 10.0)
    _write_silver_partition(lake_root, DAY_2, 14.0)
    for index, trade_date in enumerate((DAY_1, DAY_2), start=1):
        write_major_index_mins_technical_partition(
            lake_root_path=lake_root,
            staging_root_path=staging_root,
            duckdb_resource=DuckDBResource(),
            freq=FREQ,
            partition_key=trade_date,
            run_id=f"checks-{index}",
            expected_trade_dates=(DAY_1, DAY_2),
        )


def test_check_definitions_match_frozen_contract() -> None:
    assert len(GOLD_MAJOR_INDEX_MINS_TECHNICAL_CHECK_DEFINITIONS) == 42
    assert len(GOLD_MAJOR_INDEX_MINS_TECHNICAL_STATE_CHECK_DEFINITIONS) == 28
    for freq_index, freq in enumerate(MAJOR_INDEX_MINS_TECHNICAL_FREQS):
        technical_slice = GOLD_MAJOR_INDEX_MINS_TECHNICAL_CHECK_DEFINITIONS[
            freq_index * 6 : (freq_index + 1) * 6
        ]
        state_slice = GOLD_MAJOR_INDEX_MINS_TECHNICAL_STATE_CHECK_DEFINITIONS[
            freq_index * 4 : (freq_index + 1) * 4
        ]
        technical_specs = tuple(
            next(iter(definition.check_specs)) for definition in technical_slice
        )
        state_specs = tuple(
            next(iter(definition.check_specs)) for definition in state_slice
        )
        assert tuple(spec.name for spec in technical_specs) == (
            major_index_mins_technical_checks(freq)
        )
        assert tuple(spec.name for spec in state_specs) == (
            major_index_mins_technical_state_checks(freq)
        )
        assert all(spec.blocking is True for spec in technical_specs + state_specs)
        assert all(
            spec.partitions_def is cn_major_index_mins_trade_days
            for spec in technical_specs + state_specs
        )
        assert all(
            spec.asset_key.to_user_string()
            == major_index_mins_technical_asset_key(freq)
            for spec in technical_specs
        )
        assert all(
            spec.asset_key.to_user_string()
            == major_index_mins_technical_state_asset_key(freq)
            for spec in state_specs
        )


def test_all_partition_checks_pass_for_valid_two_day_chain(
    tmp_path: Path,
) -> None:
    lake_root = tmp_path / "lake"
    _materialize_two_days(lake_root, tmp_path / "staging")
    duckdb_resource = DuckDBResource()

    technical_results = tuple(
        evaluate_major_index_mins_technical_check(
            lake_root_path=lake_root,
            duckdb_resource=duckdb_resource,
            partition_key=DAY_2,
            freq=FREQ,
            check_kind=check_kind,
        )
        for check_kind in (
            "contract",
            "source_coverage",
            "partition_frequency",
            "key_integrity",
            "warmup_and_finite",
            "no_future_input",
        )
    )
    state_results = tuple(
        evaluate_major_index_mins_technical_state_check(
            lake_root_path=lake_root,
            duckdb_resource=duckdb_resource,
            partition_key=DAY_2,
            freq=FREQ,
            check_kind=check_kind,
            expected_trade_dates=(DAY_1, DAY_2),
        )
        for check_kind in (
            "contract",
            "coverage",
            "last_trade_time",
            "continuity",
        )
    )

    assert all(result.passed for result in technical_results + state_results)


def test_source_coverage_check_rejects_silver_key_drift(tmp_path: Path) -> None:
    lake_root = tmp_path / "lake"
    _materialize_two_days(lake_root, tmp_path / "staging")
    source_path = silver_major_index_mins_path(lake_root, f"{FREQ}min", DAY_2)
    replacement = tmp_path / "replacement.parquet"
    with duckdb.connect(":memory:") as connection:
        connection.execute(
            copy_query_to_parquet(
                f"SELECT * FROM {read_parquet(source_path, hive_partitioning=False)} "
                "QUALIFY row_number() OVER (ORDER BY ts_code, trade_time) > 1",
                replacement,
            )
        )
    replacement.replace(source_path)

    result = evaluate_major_index_mins_technical_check(
        lake_root_path=lake_root,
        duckdb_resource=DuckDBResource(),
        partition_key=DAY_2,
        freq=FREQ,
        check_kind="source_coverage",
    )

    assert result.passed is False


def test_continuity_check_rejects_missing_exact_previous_state(
    tmp_path: Path,
) -> None:
    lake_root = tmp_path / "lake"
    _materialize_two_days(lake_root, tmp_path / "staging")
    gold_major_index_mins_technical_state_path(
        lake_root, FREQ, DAY_1
    ).unlink()

    result = evaluate_major_index_mins_technical_state_check(
        lake_root_path=lake_root,
        duckdb_resource=DuckDBResource(),
        partition_key=DAY_2,
        freq=FREQ,
        check_kind="continuity",
        expected_trade_dates=(DAY_1, DAY_2),
    )

    assert result.passed is False


def test_continuity_check_rejects_missing_previous_expected_date(
    tmp_path: Path,
) -> None:
    lake_root = tmp_path / "lake"
    _materialize_two_days(lake_root, tmp_path / "staging")

    result = evaluate_major_index_mins_technical_state_check(
        lake_root_path=lake_root,
        duckdb_resource=DuckDBResource(),
        partition_key=DAY_2,
        freq=FREQ,
        check_kind="continuity",
        expected_trade_dates=(DAY_2,),
    )

    assert result.passed is False
