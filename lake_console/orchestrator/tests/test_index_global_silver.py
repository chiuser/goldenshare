from __future__ import annotations

from contextlib import contextmanager
from datetime import date
from pathlib import Path

import duckdb
import pytest

from orchestrator.defs.assets.index_global_raw import merge_index_global_phase
from orchestrator.defs.assets.index_global_silver import (
    IndexGlobalSilverValidationError,
    write_silver_index_global_partition,
)
from orchestrator.defs.paths import raw_index_global_path, silver_index_global_path


class _MemoryDuckDB:
    @contextmanager
    def connect(self):
        connection = duckdb.connect(":memory:")
        try:
            yield connection
        finally:
            connection.close()


def _row(
    code: str = "XIN9",
    trade_date: str = "20220104",
    *,
    change: float = 1.5,
    amount: float | None = None,
) -> dict[str, object]:
    return {
        "ts_code": code,
        "trade_date": trade_date,
        "open": 100.0,
        "close": 101.0,
        "high": 102.0,
        "low": 99.0,
        "pre_close": 99.5,
        "change": change,
        "pct_chg": 1.5,
        "swing": 3.0,
        "vol": 1000.0,
        "amount": amount,
    }


def _write_raw(
    root: Path,
    rows: list[dict[str, object]],
    *,
    run_id: str = "raw-run",
    phase: str = "asia_1",
) -> Path:
    return merge_index_global_phase(
        lake_root_path=root,
        duckdb_resource=_MemoryDuckDB(),
        trade_date="2022-01-04",
        probe_phase=phase,
        phase_rows=rows,
        run_id=run_id,
    ).target_path


def _write_raw_direct(root: Path, rows: list[dict[str, object]]) -> Path:
    """Write an intentionally malformed/duplicate Raw fixture for Silver tests."""

    path = raw_index_global_path(root, "2022-01-04")
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = (
        "ts_code VARCHAR, trade_date VARCHAR, open DOUBLE, close DOUBLE, high DOUBLE, "
        "low DOUBLE, pre_close DOUBLE, change DOUBLE, pct_chg DOUBLE, swing DOUBLE, "
        "vol DOUBLE, amount DOUBLE"
    )
    connection = duckdb.connect(":memory:")
    connection.execute(f"CREATE TABLE source ({columns})")
    connection.executemany(
        "INSERT INTO source VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [tuple(row[field] for field in (
            "ts_code", "trade_date", "open", "close", "high", "low",
            "pre_close", "change", "pct_chg", "swing", "vol", "amount",
        )) for row in rows],
    )
    quoted_path = str(path).replace("'", "''")
    connection.execute(
        f"COPY (SELECT * FROM source) TO '{quoted_path}' (FORMAT PARQUET)"
    )
    connection.close()
    return path


def _read_rows(path: Path) -> list[tuple[object, ...]]:
    with duckdb.connect(":memory:") as connection:
        return connection.execute(
            "SELECT * FROM read_parquet(?) ORDER BY ts_code",
            [str(path)],
        ).fetchall()


def test_writer_normalizes_raw_date_and_change_name(tmp_path: Path) -> None:
    _write_raw(tmp_path, [_row(amount=None)])

    result = write_silver_index_global_partition(
        lake_root_path=tmp_path,
        duckdb_resource=_MemoryDuckDB(),
        partition_key="2022-01-04",
        run_id="silver-run",
    )

    assert result.source_row_count == 1
    assert result.output_row_count == 1
    assert result.rejected_row_count == 0
    assert result.promoted is True
    assert result.staging_path.exists() is False
    assert _read_rows(result.target_file_path)[0] == (
        "XIN9",
        date(2022, 1, 4),
        100.0,
        102.0,
        99.0,
        101.0,
        99.5,
        1.5,
        1.5,
        3.0,
        1000.0,
        None,
    )

    with duckdb.connect(":memory:") as connection:
        schema = connection.execute(
            "DESCRIBE SELECT * FROM read_parquet(?)",
            [str(result.target_file_path)],
        ).fetchall()
    assert [(row[0], row[1]) for row in schema] == [
        ("ts_code", "VARCHAR"),
        ("trade_date", "DATE"),
        ("open", "DOUBLE"),
        ("high", "DOUBLE"),
        ("low", "DOUBLE"),
        ("close", "DOUBLE"),
        ("pre_close", "DOUBLE"),
        ("change_amount", "DOUBLE"),
        ("pct_chg", "DOUBLE"),
        ("swing", "DOUBLE"),
        ("vol", "DOUBLE"),
        ("amount", "DOUBLE"),
    ]


def test_empty_raw_promotes_fixed_schema_empty_silver(tmp_path: Path) -> None:
    _write_raw(tmp_path, [], phase="late_empty")

    result = write_silver_index_global_partition(
        lake_root_path=tmp_path,
        duckdb_resource=_MemoryDuckDB(),
        partition_key="2022-01-04",
        run_id="empty-run",
    )

    assert result.source_row_count == 0
    assert result.output_row_count == 0
    assert result.target_file_path == silver_index_global_path(tmp_path, "2022-01-04")
    assert result.target_file_path.exists()
    with duckdb.connect(":memory:") as connection:
        assert connection.execute(
            "SELECT count(*) FROM read_parquet(?)",
            [str(result.target_file_path)],
        ).fetchone()[0] == 0


def test_identical_duplicate_keys_are_deduplicated(tmp_path: Path) -> None:
    _write_raw_direct(tmp_path, [_row(), _row()])

    result = write_silver_index_global_partition(
        lake_root_path=tmp_path,
        duckdb_resource=_MemoryDuckDB(),
        partition_key="2022-01-04",
        run_id="duplicate-run",
    )

    assert result.duplicate_removed_count == 1
    assert result.output_row_count == 1


def test_conflicting_duplicate_keys_fail_without_overwriting_target(tmp_path: Path) -> None:
    rows = [_row(change=1.5), _row(change=2.5)]
    _write_raw_direct(tmp_path, rows)
    target = silver_index_global_path(tmp_path, "2022-01-04")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"existing-silver")

    with pytest.raises(IndexGlobalSilverValidationError, match="conflicting duplicate"):
        write_silver_index_global_partition(
            lake_root_path=tmp_path,
            duckdb_resource=_MemoryDuckDB(),
            partition_key="2022-01-04",
            run_id="conflict-run",
        )
    assert target.read_bytes() == b"existing-silver"


@pytest.mark.parametrize(
    ("code", "trade_date", "expected_reason"),
    [
        ("", "20220104", "ts_code_missing"),
        ("UNKNOWN", "20220104", "ts_code_unknown"),
        ("XIN9", "20220103", "trade_date_out_of_partition"),
    ],
)
def test_invalid_identity_or_date_fails_closed_without_overwrite(
    tmp_path: Path,
    code: str,
    trade_date: str,
    expected_reason: str,
) -> None:
    _write_raw_direct(tmp_path, [_row(code=code, trade_date=trade_date)])
    target = silver_index_global_path(tmp_path, "2022-01-04")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"existing-silver")

    with pytest.raises(IndexGlobalSilverValidationError, match=expected_reason):
        write_silver_index_global_partition(
            lake_root_path=tmp_path,
            duckdb_resource=_MemoryDuckDB(),
            partition_key="2022-01-04",
            run_id="invalid-run",
        )
    assert target.read_bytes() == b"existing-silver"


def test_missing_raw_is_rejected_before_target_creation(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        write_silver_index_global_partition(
            lake_root_path=tmp_path,
            duckdb_resource=_MemoryDuckDB(),
            partition_key="2022-01-04",
            run_id="missing-run",
        )
    assert not silver_index_global_path(tmp_path, "2022-01-04").exists()


def test_staging_component_rejects_path_traversal(tmp_path: Path) -> None:
    _write_raw(tmp_path, [_row()])
    with pytest.raises(ValueError, match="safe non-empty path component"):
        write_silver_index_global_partition(
            lake_root_path=tmp_path,
            duckdb_resource=_MemoryDuckDB(),
            partition_key="2022-01-04",
            run_id="../unsafe",
        )
