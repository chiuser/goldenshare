from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

import duckdb
import pytest

from orchestrator.defs.duckdb_sql import copy_query_to_parquet
from orchestrator.defs.io.major_index_mins_quality import (
    prepare_major_index_mins_raw_expected_tables,
    validate_major_index_mins_raw_relation,
)
from orchestrator.defs.io.major_index_mins_silver_writer import (
    MajorIndexMinsSilverValidationError,
    write_major_index_mins_silver_partition,
    write_major_index_mins_silver_partition_with_historical_fallback,
)
from orchestrator.defs.paths import (
    raw_major_index_mins_path,
    silver_major_index_mins_path,
)
from orchestrator.defs.run_contracts.major_index_mins import (
    MAJOR_INDEX_MINS_SOURCE_COLUMNS,
    effective_raw_request_codes_for_date,
    effective_silver_codes_for_date,
    major_index_mins_exchange_for_code,
    major_index_mins_historical_fallback_rule,
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


def _empty_raw_relation(connection) -> str:
    connection.execute(
        """
        CREATE TEMP TABLE empty_raw (
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
    return "empty_raw"


def _write_raw(
    root: Path,
    *,
    trade_date: str,
    freq: str,
    omit: tuple[str, str] | None = None,
    anomaly: str | None = None,
    source_exchange: str | None = "contract",
    omit_codes: frozenset[str] = frozenset(),
) -> Path:
    path = raw_major_index_mins_path(root, freq, trade_date)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for code in effective_raw_request_codes_for_date(trade_date):
        if code in omit_codes:
            continue
        exchange = major_index_mins_exchange_for_code(code)
        for index, source_time in enumerate(
            major_index_mins_session_times(exchange=exchange, source_freq=freq)
        ):
            if omit == (code, source_time):
                continue
            value = float(index + 1)
            open_value = value
            close_value = value + 0.5
            high_value = value + 1.0
            low_value = value - 0.5
            vol_value = value * 10
            amount_value = value * 100
            if (
                anomaly == "opening_sentinel"
                and trade_date == "2022-02-07"
                and source_time == "09:30:00"
                and code
                in {
                    "000001.SH",
                    "000016.SH",
                    "000300.SH",
                    "000688.SH",
                    "000852.SH",
                    "000905.SH",
                }
            ):
                high_value = 0.0
                low_value = 0.0
            if (
                anomaly in {"known_envelope", "unknown_envelope"}
                and code == "399001.SZ"
                and source_time == "09:30:00"
            ):
                high_value = close_value
                low_value = close_value
            if (
                anomaly == "bse_negative"
                and code == "899050.BJ"
                and source_time == "15:30:00"
            ):
                vol_value = -10.0
                amount_value = -100.0
            rows.append(
                (
                    f" {code.lower()} ",
                    f" {freq} ",
                    f"{trade_date} {source_time}",
                    open_value,
                    close_value,
                    high_value,
                    low_value,
                    vol_value,
                    amount_value,
                    exchange if source_exchange == "contract" else source_exchange,
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


def _write_fallback_file(
    root: Path,
    *,
    trade_date: str,
    freq: str,
) -> tuple[Path, tuple[str, ...]]:
    rule = major_index_mins_historical_fallback_rule(
        trade_date=trade_date,
        target_freq=freq,
    )
    assert rule is not None
    path = root / "fallback" / freq / trade_date / "part-000.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for code in rule.target_codes:
        exchange = major_index_mins_exchange_for_code(code)
        for index, source_time in enumerate(
            major_index_mins_session_times(
                exchange=exchange,
                source_freq=freq,
            )
        ):
            value = float(index + 10)
            rows.append(
                (
                    code,
                    freq,
                    f"{trade_date} {source_time}",
                    value,
                    value + 0.5,
                    value + 1.0,
                    value - 0.5,
                    value * 10,
                    value * 100,
                    exchange,
                    None,
                )
            )
    with duckdb.connect(":memory:") as connection:
        connection.execute(
            """
            CREATE TABLE fallback_rows (
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
            "INSERT INTO fallback_rows VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        connection.execute(
            copy_query_to_parquet(
                "SELECT * FROM fallback_rows ORDER BY ts_code, trade_time",
                path,
            )
        )
    return path, rule.target_codes


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


def test_raw_empty_partition_is_only_allowed_for_full_published_fallback() -> None:
    with duckdb.connect(":memory:") as connection:
        relation = _empty_raw_relation(connection)
        published_date = "2009-05-05"
        published_codes = effective_raw_request_codes_for_date(published_date)
        prepare_major_index_mins_raw_expected_tables(
            connection,
            expected_codes=published_codes,
            frequency="15min",
            partition_key=published_date,
        )
        published = validate_major_index_mins_raw_relation(
            connection,
            relation_sql=relation,
            expected_codes=published_codes,
            frequency="15min",
            partition_key=published_date,
        )
        assert published.errors == ()

        published_with_bse_date = "2024-10-30"
        published_with_bse_codes = effective_raw_request_codes_for_date(
            published_with_bse_date
        )
        prepare_major_index_mins_raw_expected_tables(
            connection,
            expected_codes=published_with_bse_codes,
            frequency="15min",
            partition_key=published_with_bse_date,
        )
        published_with_bse = validate_major_index_mins_raw_relation(
            connection,
            relation_sql=relation,
            expected_codes=published_with_bse_codes,
            frequency="15min",
            partition_key=published_with_bse_date,
        )
        assert published_with_bse.errors == ()

        unknown_date = "2026-08-04"
        unknown_codes = effective_raw_request_codes_for_date(unknown_date)
        prepare_major_index_mins_raw_expected_tables(
            connection,
            expected_codes=unknown_codes,
            frequency="15min",
            partition_key=unknown_date,
        )
        unknown = validate_major_index_mins_raw_relation(
            connection,
            relation_sql=relation,
            expected_codes=unknown_codes,
            frequency="15min",
            partition_key=unknown_date,
        )
        assert "row_count" in unknown.errors


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


def test_native_silver_cleans_only_published_ohlc_scopes(tmp_path: Path) -> None:
    _write_raw(
        tmp_path,
        trade_date="2022-02-07",
        freq="5min",
        anomaly="opening_sentinel",
        source_exchange=None,
    )
    sentinel = write_major_index_mins_silver_partition(
        lake_root_path=tmp_path,
        duckdb_resource=_MemoryDuckDB(),
        freq="5min",
        partition_key="2022-02-07",
        run_id="p7c-sentinel",
    )
    sentinel_row = _rows(sentinel.target_path, "000001.SH")[0]
    assert sentinel_row[5:7] == (1.5, 1.0)
    assert sentinel_row[9] == "XSHG"

    _write_raw(
        tmp_path,
        trade_date="2017-01-04",
        freq="5min",
        anomaly="known_envelope",
        source_exchange="nan",
    )
    envelope = write_major_index_mins_silver_partition(
        lake_root_path=tmp_path,
        duckdb_resource=_MemoryDuckDB(),
        freq="5min",
        partition_key="2017-01-04",
        run_id="p7c-envelope",
    )
    envelope_row = _rows(envelope.target_path, "399001.SZ")[0]
    assert envelope_row[5:7] == (1.5, 1.0)
    assert envelope_row[9] == "XSHE"

    _write_raw(
        tmp_path,
        trade_date="2017-02-03",
        freq="5min",
        anomaly="unknown_envelope",
    )
    with pytest.raises(MajorIndexMinsSilverValidationError, match="invalid_rows"):
        write_major_index_mins_silver_partition(
            lake_root_path=tmp_path,
            duckdb_resource=_MemoryDuckDB(),
            freq="5min",
            partition_key="2017-02-03",
            run_id="p7c-unknown-envelope",
        )


def test_bse_negative_source_fact_is_raw_only(tmp_path: Path) -> None:
    _write_raw(
        tmp_path,
        trade_date="2023-07-11",
        freq="60min",
        anomaly="bse_negative",
    )
    result = write_major_index_mins_silver_partition(
        lake_root_path=tmp_path,
        duckdb_resource=_MemoryDuckDB(),
        freq="60min",
        partition_key="2023-07-11",
        run_id="p7c-bse-negative",
    )
    assert _rows(result.target_path, "899050.BJ") == []


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


def test_bootstrap_only_fallback_merges_exact_published_scope(
    tmp_path: Path,
) -> None:
    trade_date = "2024-10-30"
    freq = "15min"
    fallback_path, fallback_codes = _write_fallback_file(
        tmp_path,
        trade_date=trade_date,
        freq=freq,
    )
    _write_raw(
        tmp_path,
        trade_date=trade_date,
        freq=freq,
        omit_codes=frozenset(fallback_codes),
    )

    result = write_major_index_mins_silver_partition_with_historical_fallback(
        lake_root_path=tmp_path,
        duckdb_resource=_MemoryDuckDB(),
        freq=freq,
        partition_key=trade_date,
        run_id="p7d-explicit-fallback",
        historical_fallback_path=fallback_path,
        historical_fallback_codes=fallback_codes,
    )

    assert result.source_mode == "native_with_historical_fallback"
    assert result.output_row_count == len(
        effective_silver_codes_for_date(trade_date)
    ) * len(
        major_index_mins_session_times(
            exchange="XSHG",
            source_freq=freq,
        )
    )
    assert _rows(result.target_path, fallback_codes[0])
    assert _rows(result.target_path, "899050.BJ") == []


def test_bootstrap_only_fallback_rejects_unpublished_scope(
    tmp_path: Path,
) -> None:
    fallback_path, fallback_codes = _write_fallback_file(
        tmp_path,
        trade_date="2024-10-30",
        freq="15min",
    )
    _write_raw(tmp_path, trade_date="2026-08-04", freq="15min")

    with pytest.raises(
        MajorIndexMinsSilverValidationError,
        match="published native scope",
    ):
        write_major_index_mins_silver_partition_with_historical_fallback(
            lake_root_path=tmp_path,
            duckdb_resource=_MemoryDuckDB(),
            freq="15min",
            partition_key="2026-08-04",
            run_id="p7d-unpublished-fallback",
            historical_fallback_path=fallback_path,
            historical_fallback_codes=fallback_codes,
        )


def test_derived_90m_excludes_bse_from_silver(tmp_path: Path) -> None:
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
    assert sh_times == ["11:00:00", "14:00:00", "15:00:00"]
    assert bj_rows == []
    assert result.expected_window_count == 30
    assert result.generated_window_count == 30


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

    for code in ("000001.SH", "399001.SZ"):
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
    assert _rows(result.target_path, "899050.BJ") == []
    assert result.expected_window_count == 20
    assert result.generated_window_count == 20


def test_bse_source_session_failure_does_not_block_silver(tmp_path: Path) -> None:
    _write_raw(
        tmp_path,
        trade_date="2025-10-30",
        freq="30min",
        omit=("899050.BJ", "15:30:00"),
    )
    result = write_major_index_mins_silver_partition(
        lake_root_path=tmp_path,
        duckdb_resource=_MemoryDuckDB(),
        freq="30min",
        partition_key="2025-10-30",
        run_id="p3-bse-source-gap",
    )
    assert result.output_row_count == 90
    assert _rows(result.target_path, "899050.BJ") == []


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
