from pathlib import Path

import duckdb
import pytest

from orchestrator.defs.duckdb_sql import copy_query_to_parquet, read_parquet
from orchestrator.defs.io.cn_a_gold_minute_bars import (
    CanonicalGoldMinuteValidationError,
)
from orchestrator.defs.io.cn_a_gold_minute_writer import (
    write_canonical_gold_minute_partition,
)
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.run_contracts.cn_a_derived_minute_bars import (
    CN_A_GOLD_MINUTE_FREQS,
    canonical_gold_minute_window_rows,
    expected_gold_minute_times,
)

TRADE_DATE = "2026-08-12"


def _write_source(path: Path, target_freq: int, *, omit_last: bool = False) -> None:
    source_times = tuple(
        dict.fromkeys(row[0] for row in canonical_gold_minute_window_rows(target_freq))
    )
    if omit_last:
        source_times = source_times[:-1]
    source_freq_value = {
        1: "1min",
        5: "1min",
        15: "5min",
        30: "5min",
        60: "30min",
        90: "30min",
        120: "60min",
    }[target_freq]
    rows = []
    for index, trade_time in enumerate(source_times, start=1):
        close = float(100 + index)
        rows.append(
            (
                "000001.SH",
                source_freq_value,
                f"{TRADE_DATE} {trade_time}",
                close,
                close + 1,
                close - 1,
                close,
                1.0,
                close,
                "SSE",
                close,
            )
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(":memory:") as connection:
        connection.execute(
            """
            CREATE TABLE source_rows (
              ts_code VARCHAR,
              freq VARCHAR,
              trade_time TIMESTAMP,
              open DOUBLE,
              high DOUBLE,
              low DOUBLE,
              close DOUBLE,
              vol DOUBLE,
              amount DOUBLE,
              exchange VARCHAR,
              vwap DOUBLE
            )
            """
        )
        connection.executemany(
            "INSERT INTO source_rows VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        connection.execute(
            copy_query_to_parquet(
                "SELECT * FROM source_rows ORDER BY ts_code, trade_time",
                path,
            )
        )


@pytest.mark.parametrize("target_freq", CN_A_GOLD_MINUTE_FREQS)
def test_writer_emits_exact_canonical_session_and_atomic_target(
    tmp_path: Path,
    target_freq: int,
) -> None:
    source = tmp_path / "source" / f"{target_freq}.parquet"
    target = tmp_path / "lake" / f"{target_freq}.parquet"
    staging = tmp_path / "lake" / f".{target_freq}.staging.parquet"
    _write_source(source, target_freq)

    result = write_canonical_gold_minute_partition(
        duckdb_resource=DuckDBResource(),
        source_path=source,
        target_path=target,
        staging_path=staging,
        target_freq=target_freq,
        partition_key=TRADE_DATE,
        expected_codes=("000001.SH",),
    )

    expected_times = expected_gold_minute_times("SSE", target_freq)
    with duckdb.connect(":memory:") as connection:
        rows = connection.execute(
            f"""
            SELECT strftime(trade_time, '%H:%M:%S') AS trade_time
            FROM {read_parquet(target, hive_partitioning=False)}
            ORDER BY trade_time
            """
        ).fetchall()
    actual_times = tuple(str(row[0]) for row in rows)
    assert actual_times == expected_times
    assert result.output_row_count == len(expected_times)
    assert result.expected_row_count == len(expected_times)
    assert actual_times[-1] == "15:00:00"
    if target_freq == 1:
        assert actual_times[0] == "09:30:00"
    else:
        assert "09:30:00" not in actual_times
    assert target.is_file()
    assert not staging.exists()


def test_writer_refuses_existing_target_without_touching_it(tmp_path: Path) -> None:
    source = tmp_path / "source.parquet"
    target = tmp_path / "target.parquet"
    staging = tmp_path / ".staging.parquet"
    _write_source(source, 5)
    target.write_bytes(b"existing-target")

    with pytest.raises(
        CanonicalGoldMinuteValidationError, match="refuses to overwrite"
    ):
        write_canonical_gold_minute_partition(
            duckdb_resource=DuckDBResource(),
            source_path=source,
            target_path=target,
            staging_path=staging,
            target_freq=5,
            partition_key=TRADE_DATE,
            expected_codes=("000001.SH",),
        )

    assert target.read_bytes() == b"existing-target"
    assert not staging.exists()


def test_writer_cleans_failed_staging_and_does_not_publish_partial_output(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.parquet"
    target = tmp_path / "target.parquet"
    staging = tmp_path / ".staging.parquet"
    _write_source(source, 5, omit_last=True)

    with pytest.raises(CanonicalGoldMinuteValidationError, match="failed core audit"):
        write_canonical_gold_minute_partition(
            duckdb_resource=DuckDBResource(),
            source_path=source,
            target_path=target,
            staging_path=staging,
            target_freq=5,
            partition_key=TRADE_DATE,
            expected_codes=("000001.SH",),
        )

    assert not target.exists()
    assert not staging.exists()
