from __future__ import annotations

from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from orchestrator.defs.assets import index_mins_silver_repair
from orchestrator.defs.assets.index_mins_silver_repair import (
    IndexMinsSilverFallbackRequest,
    compute_index_mins_fallback_source_revision,
    reconcile_silver_index_mins_native_partition,
    repair_silver_index_mins_source_empty,
    validate_silver_index_mins_source_empty_fallback,
)
from orchestrator.defs.assets.index_mins_silver import IndexMinsSilverValidationError
from orchestrator.defs.duckdb_sql import copy_query_to_parquet, read_parquet
from orchestrator.defs.paths import raw_index_mins_path, silver_index_mins_path
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.run_contracts.index_mins import (
    fallback_source_times_for_index_mins,
    fallback_target_times_for_index_mins_freq,
)


TRADE_DATE = "2026-07-27"
CODE = "000001.SH"


def _write_raw(root: Path, frequency: str, times: tuple[str, ...]) -> Path:
    path = raw_index_mins_path(root, frequency, TRADE_DATE)
    path.parent.mkdir(parents=True, exist_ok=True)
    with DuckDBResource().connect() as connection:
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
            [
                (
                    CODE,
                    frequency,
                    datetime.fromisoformat(f"{TRADE_DATE} {trade_time}"),
                    float(index + 1),
                    float(index + 1.5),
                    float(index + 2),
                    float(index + 0.5),
                    float(index + 10),
                    float(index + 100),
                    "XSHG",
                    float(index + 1.25),
                )
                for index, trade_time in enumerate(times)
            ],
        )
        connection.execute(copy_query_to_parquet("SELECT * FROM source_rows", path))
    return path


def _request(
    root: Path, *, target_frequencies: tuple[int, ...]
) -> IndexMinsSilverFallbackRequest:
    with DuckDBResource().connect() as connection:
        source_revision = compute_index_mins_fallback_source_revision(
            connection=connection,
            lake_root=root,
            partition_key=TRADE_DATE,
        )
    return IndexMinsSilverFallbackRequest(
        partition_key=TRADE_DATE,
        target_frequencies=target_frequencies,
        source_empty_frequencies=(15, 30, 60),
        effective_codes=(CODE,),
        source_revision=source_revision,
        source_empty_reason="source_probe_target_frequencies_empty",
    )


def _read_rows(path: Path) -> list[tuple[object, ...]]:
    with DuckDBResource().connect() as connection:
        return connection.execute(
            f"SELECT * FROM {read_parquet(path, hive_partitioning=False)} ORDER BY trade_time"
        ).fetchall()


def test_fallback_writer_builds_all_target_frequencies_from_complete_5min_source() -> (
    None
):
    with TemporaryDirectory() as directory:
        root = Path(directory)
        _write_raw(root, "5min", fallback_source_times_for_index_mins())
        request = _request(root, target_frequencies=(15, 30, 60))

        results = repair_silver_index_mins_source_empty(
            lake_root=root,
            duckdb=DuckDBResource(),
            request=request,
        )

        assert [result.silver_freq for result in results] == ["15min", "30min", "60min"]
        assert [result.written_row_count for result in results] == [17, 9, 5]
        assert all(result.source_mode == "derived_fallback" for result in results)
        assert all(
            result.write_mode == "bounded_repair_atomic_replace" for result in results
        )
        assert all(
            result.source_revision == request.source_revision for result in results
        )
        assert all(
            row[10] is None
            for result in results
            for row in _read_rows(result.silver_file_path)
        )
        assert list(root.rglob("*.tmp")) == []

        with DuckDBResource().connect() as connection:
            readiness = validate_silver_index_mins_source_empty_fallback(
                connection=connection,
                lake_root=root,
                request=request,
            )
        assert readiness.ready is True
        assert readiness.reason_code == "ready_after_source_empty_fallback"


def test_fallback_rejects_partial_raw_target_frequency() -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        _write_raw(root, "5min", fallback_source_times_for_index_mins())
        _write_raw(root, "15min", ("09:30:00",))
        request = _request(root, target_frequencies=(15, 30, 60))

        with pytest.raises(
            IndexMinsSilverValidationError, match="source-empty claim is false"
        ):
            repair_silver_index_mins_source_empty(
                lake_root=root,
                duckdb=DuckDBResource(),
                request=request,
            )
        assert not silver_index_mins_path(root, 15, TRADE_DATE).exists()
        assert not silver_index_mins_path(root, 30, TRADE_DATE).exists()
        assert not silver_index_mins_path(root, 60, TRADE_DATE).exists()
        assert list(root.rglob("*.tmp")) == []


def test_fallback_preserves_existing_target_when_source_contract_fails() -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        incomplete_times = fallback_source_times_for_index_mins()[:-1]
        _write_raw(root, "5min", incomplete_times)
        target = silver_index_mins_path(root, 15, TRADE_DATE)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"existing-target")
        request = _request(root, target_frequencies=(15,))

        with pytest.raises(
            IndexMinsSilverValidationError, match="time grid is incomplete"
        ):
            repair_silver_index_mins_source_empty(
                lake_root=root,
                duckdb=DuckDBResource(),
                request=request,
            )
        assert target.read_bytes() == b"existing-target"
        assert list(root.rglob("*.tmp")) == []


def test_native_reconcile_replaces_fallback_only_through_explicit_entry() -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        _write_raw(root, "5min", fallback_source_times_for_index_mins())
        fallback_request = _request(root, target_frequencies=(15,))
        repair_silver_index_mins_source_empty(
            lake_root=root,
            duckdb=DuckDBResource(),
            request=fallback_request,
        )
        fallback_rows = _read_rows(silver_index_mins_path(root, 15, TRADE_DATE))
        assert all(row[10] is None for row in fallback_rows)

        _write_raw(
            root,
            "15min",
            fallback_target_times_for_index_mins_freq(15),
        )
        result = reconcile_silver_index_mins_native_partition(
            lake_root=root,
            duckdb=DuckDBResource(),
            frequency=15,
            partition_key=TRADE_DATE,
        )
        assert result.source_mode == "native_reconcile"
        assert result.write_mode == "bounded_repair_atomic_replace"
        assert result.written_row_count == 17
        assert all(row[10] is not None for row in _read_rows(result.silver_file_path))
        assert list(root.rglob("*.tmp")) == []


def test_repair_module_is_not_an_active_dagster_or_event_history_path() -> None:
    source = Path(index_mins_silver_repair.__file__).read_text()
    assert "@dg." not in source
    assert "get_event_records" not in source
    assert "TushareResource" not in source
