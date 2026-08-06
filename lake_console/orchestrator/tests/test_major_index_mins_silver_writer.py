from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

import duckdb
import pytest

from orchestrator.defs.duckdb_sql import copy_query_to_parquet
from orchestrator.defs.io.major_index_mins_silver_writer import (
    MajorIndexMinsSilverValidationError,
    write_major_index_mins_silver_partition,
)
from orchestrator.defs.paths import (
    raw_major_index_mins_path,
    silver_major_index_mins_path,
)
from orchestrator.defs.run_contracts.major_index_mins import (
    MAJOR_INDEX_MINS_SOURCE_COLUMNS,
    effective_codes_for_date,
    major_index_mins_exchange_for_code,
    major_index_mins_session_times,
)


class _MemoryDuckDB:
    @contextmanager
    def connect(self):
        connection = duckdb.connect(":memory:")
        try:
            yield connection
        finally:
            connection.close()


def _write_raw(
    root: Path,
    *,
    trade_date: str,
    freq: str,
    omit: tuple[str, str] | None = None,
) -> Path:
    path = raw_major_index_mins_path(root, freq, trade_date)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for code in effective_codes_for_date(trade_date):
        exchange = major_index_mins_exchange_for_code(code)
        for index, source_time in enumerate(
            major_index_mins_session_times(exchange=exchange, source_freq=freq)
        ):
            if omit == (code, source_time):
                continue
            value = float(index + 1)
            rows.append(
                (
                    f" {code.lower()} ",
                    f" {freq} ",
                    f"{trade_date} {source_time}",
                    value,
                    value + 0.5,
                    value + 1.0,
                    value - 0.5,
                    value * 10,
                    value * 100,
                    exchange,
                    value + 0.25,
                )
            )
    with duckdb.connect(":memory:") as connection:
        connection.execute(
            """
            CREATE TABLE source_rows (
              ts_code VARCHAR,
              freq VARCHAR,
              trade_time TIMESTAMP,
              open DOUBLE,
              close DOUBLE,
              high DOUBLE,
              low DOUBLE,
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
    return path


def _rows(path: Path, code: str) -> list[tuple[object, ...]]:
    with duckdb.connect(":memory:") as connection:
        return connection.execute(
            "SELECT * FROM read_parquet(?, hive_partitioning=false) "
            "WHERE ts_code = ? ORDER BY trade_time",
            [str(path), code],
        ).fetchall()


def test_real_session_fixtures_cover_sh_sz_and_bj() -> None:
    expected_counts = {
        "XSHG": {"1min": 241, "5min": 49, "15min": 17, "30min": 9, "60min": 5},
        "XSHE": {"1min": 241, "5min": 49, "15min": 17, "30min": 9, "60min": 5},
        "BSE": {"1min": 271, "5min": 55, "15min": 19, "30min": 10, "60min": 6},
    }
    for exchange, by_freq in expected_counts.items():
        for freq, expected_count in by_freq.items():
            times = major_index_mins_session_times(exchange=exchange, source_freq=freq)
            assert len(times) == expected_count
            assert times[0] == "09:30:00"
            assert times[-1] == ("15:30:00" if exchange == "BSE" else "15:00:00")
            assert "12:00:00" not in times
            assert "13:00:00" not in times


def test_native_silver_normalizes_and_preserves_vwap(tmp_path: Path) -> None:
    _write_raw(tmp_path, trade_date="2026-08-04", freq="60min")
    result = write_major_index_mins_silver_partition(
        lake_root_path=tmp_path,
        duckdb_resource=_MemoryDuckDB(),
        freq="60min",
        partition_key="2026-08-04",
        run_id="p3-native",
    )

    assert result.source_mode == "native"
    assert result.source_row_count == 50
    assert result.output_row_count == 50
    assert result.write_mode == "staged_atomic_replace"
    row = _rows(result.target_path, "000001.SH")[0]
    assert row[0:2] == ("000001.SH", "60min")
    assert row[9] == "XSHG"
    assert row[10] == 1.25
    with duckdb.connect(":memory:") as connection:
        observed_columns = tuple(
            value[0]
            for value in connection.execute(
            "DESCRIBE SELECT * FROM read_parquet(?, hive_partitioning=false)",
            [str(result.target_path)],
            ).fetchall()
        )
    assert MAJOR_INDEX_MINS_SOURCE_COLUMNS == observed_columns


def test_native_silver_rejects_incomplete_session_without_target(tmp_path: Path) -> None:
    _write_raw(
        tmp_path,
        trade_date="2026-08-04",
        freq="60min",
        omit=("000001.SH", "15:00:00"),
    )
    with pytest.raises(
        MajorIndexMinsSilverValidationError,
        match="session grid",
    ):
        write_major_index_mins_silver_partition(
            lake_root_path=tmp_path,
            duckdb_resource=_MemoryDuckDB(),
            freq="60min",
            partition_key="2026-08-04",
            run_id="p3-incomplete",
        )
    assert not silver_major_index_mins_path(
        tmp_path,
        "60min",
        "2026-08-04",
    ).exists()


def test_derived_90m_uses_exchange_specific_final_window(tmp_path: Path) -> None:
    _write_raw(tmp_path, trade_date="2025-10-30", freq="30min")
    write_major_index_mins_silver_partition(
        lake_root_path=tmp_path,
        duckdb_resource=_MemoryDuckDB(),
        freq="30min",
        partition_key="2025-10-30",
        run_id="p3-native-30",
    )
    result = write_major_index_mins_silver_partition(
        lake_root_path=tmp_path,
        duckdb_resource=_MemoryDuckDB(),
        freq="90min",
        partition_key="2025-10-30",
        run_id="p3-derived-90",
    )

    sh_times = [row[2].strftime("%H:%M:%S") for row in _rows(result.target_path, "000001.SH")]
    bj_rows = _rows(result.target_path, "899050.BJ")
    bj_times = [row[2].strftime("%H:%M:%S") for row in bj_rows]
    assert sh_times == ["11:00:00", "14:00:00", "15:00:00"]
    assert bj_times == ["11:00:00", "14:00:00", "15:30:00"]
    assert all(row[1] == "90min" and row[10] is None for row in bj_rows)
    assert bj_rows[-1][3:9] == (8.0, 10.5, 11.0, 7.5, 270.0, 2700.0)
    assert result.expected_window_count == 33
    assert result.generated_window_count == 33


def test_derived_120m_drops_incomplete_exchange_tail(tmp_path: Path) -> None:
    _write_raw(tmp_path, trade_date="2025-10-30", freq="60min")
    write_major_index_mins_silver_partition(
        lake_root_path=tmp_path,
        duckdb_resource=_MemoryDuckDB(),
        freq="60min",
        partition_key="2025-10-30",
        run_id="p3-native-60",
    )
    result = write_major_index_mins_silver_partition(
        lake_root_path=tmp_path,
        duckdb_resource=_MemoryDuckDB(),
        freq="120min",
        partition_key="2025-10-30",
        run_id="p3-derived-120",
    )

    for code in ("000001.SH", "399001.SZ", "899050.BJ"):
        rows = _rows(result.target_path, code)
        assert [row[2].strftime("%H:%M:%S") for row in rows] == [
            "10:30:00",
            "14:00:00",
        ]
        assert all(row[10] is None for row in rows)
    assert _rows(result.target_path, "000001.SH")[0][3:9] == (
        1.0,
        2.5,
        3.0,
        0.5,
        30.0,
        300.0,
    )
    assert result.expected_window_count == 22
    assert result.generated_window_count == 22


def test_derived_source_session_failure_does_not_create_target(tmp_path: Path) -> None:
    _write_raw(
        tmp_path,
        trade_date="2025-10-30",
        freq="30min",
        omit=("899050.BJ", "15:30:00"),
    )
    with pytest.raises(MajorIndexMinsSilverValidationError, match="session grid"):
        write_major_index_mins_silver_partition(
            lake_root_path=tmp_path,
            duckdb_resource=_MemoryDuckDB(),
            freq="30min",
            partition_key="2025-10-30",
            run_id="p3-bad-native",
        )
    assert not silver_major_index_mins_path(
        tmp_path,
        "30min",
        "2025-10-30",
    ).exists()


def test_invalid_existing_silver_target_is_not_overwritten(tmp_path: Path) -> None:
    _write_raw(tmp_path, trade_date="2026-08-04", freq="60min")
    target = silver_major_index_mins_path(tmp_path, "60min", "2026-08-04")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"invalid parquet")
    original = target.read_bytes()

    with pytest.raises(MajorIndexMinsSilverValidationError):
        write_major_index_mins_silver_partition(
            lake_root_path=tmp_path,
            duckdb_resource=_MemoryDuckDB(),
            freq="60min",
            partition_key="2026-08-04",
            run_id="p3-invalid-existing",
        )
    assert target.read_bytes() == original
