from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import duckdb
import pytest

from orchestrator.defs.assets.index_global_raw import (
    IndexGlobalFetchError,
    fetch_index_global_phase,
    merge_index_global_phase,
    run_index_global_phase_sequence,
)
from orchestrator.defs.paths import raw_index_global_path, raw_index_global_staging_path
from orchestrator.defs.resources import TushareResult
from orchestrator.defs.run_contracts.index_global import (
    INDEX_GLOBAL_FIELDS,
    IndexGlobalRawValidationError,
)
from orchestrator.defs.tushare_request_policy import TushareRequestPolicy


class _MemoryDuckDB:
    @contextmanager
    def connect(self):
        connection = duckdb.connect(":memory:")
        try:
            yield connection
        finally:
            connection.close()


class _FakeTushare:
    def __init__(self, rows_by_offset):
        self.rows_by_offset = rows_by_offset
        self.calls = []

    def call(self, api_name, params, fields):
        self.calls.append((api_name, dict(params), tuple(fields)))
        assert api_name == "index_global"
        return TushareResult(
            rows=list(self.rows_by_offset.get(params["offset"], [])),
            columns=tuple(fields),
            metadata={},
        )


def _request_policy() -> TushareRequestPolicy:
    return TushareRequestPolicy(
        minimum_interval_seconds=0.0,
        max_retries=0,
        max_requests=20,
        max_elapsed_seconds=30.0,
    )


def _row(code: str = "XIN9", close: float = 1.0) -> dict[str, object]:
    return {
        "ts_code": code,
        "trade_date": "20220104",
        "open": close,
        "close": close,
        "high": close,
        "low": close,
        "pre_close": close,
        "change": 0.0,
        "pct_chg": 0.0,
        "swing": 0.0,
        "vol": 1.0,
        "amount": None,
    }


def test_bounded_fetch_uses_explicit_date_fields_and_increasing_offsets() -> None:
    pages = {0: [_row("XIN9"), _row("HSI")], 2: [_row("N225")], 4: []}
    tushare = _FakeTushare(pages)
    with patch(
        "orchestrator.defs.assets.index_global_raw.INDEX_GLOBAL_REQUEST_LIMIT",
        2,
    ):
        result = fetch_index_global_phase(
            tushare=tushare,
            trade_date="2022-01-04",
            probe_phase="asia_1",
            request_policy=_request_policy(),
        )

    assert [call[1]["offset"] for call in tushare.calls] == [0, 2]
    assert all(call[1]["trade_date"] == "20220104" for call in tushare.calls)
    assert all(call[2] == INDEX_GLOBAL_FIELDS for call in tushare.calls)
    assert result.page_count == 2
    assert len(result.rows) == 3


def test_bounded_fetch_accepts_empty_source_observation() -> None:
    result = fetch_index_global_phase(
        tushare=_FakeTushare({0: []}),
        trade_date="2022-01-01",
        probe_phase="asia_1",
        request_policy=_request_policy(),
    )
    assert result.empty is True
    assert result.request_count == 1


def test_bounded_fetch_fails_closed_on_response_column_drift() -> None:
    class _Drifted(_FakeTushare):
        def call(self, api_name, params, fields):
            self.calls.append((api_name, dict(params), tuple(fields)))
            return TushareResult(rows=[_row()], columns=("ts_code",), metadata={})

    with pytest.raises(IndexGlobalFetchError, match="bounded phase request failed"):
        fetch_index_global_phase(
            tushare=_Drifted({}),
            trade_date="2022-01-04",
            probe_phase="asia_1",
            request_policy=_request_policy(),
        )


def test_five_phase_sequence_accumulates_source_rows_in_temp_lake(tmp_path: Path) -> None:
    phase_codes = {
        "asia_1": "XIN9",
        "asia_2": "HSI",
        "asia_3": "N225",
        "europe": "FTSE",
        "americas": "SPX",
    }

    # The fake uses the request call order as the phase order, mirroring the
    # serial sequence runner without making the production fetcher phase-aware.
    class _SerialFake:
        def __init__(self):
            self.index = 0
            self.calls = []

        def call(self, api_name, params, fields):
            phase_code = tuple(phase_codes.values())[self.index]
            self.index += 1
            self.calls.append((api_name, dict(params), tuple(fields)))
            return TushareResult(
                rows=[_row(phase_code)], columns=tuple(fields), metadata={}
            )

    result = run_index_global_phase_sequence(
        lake_root_path=tmp_path,
        duckdb_resource=_MemoryDuckDB(),
        tushare=_SerialFake(),
        trade_date="2022-01-04",
        run_id="sequence-run",
        request_policy=_request_policy(),
    )

    assert len(result.phase_results) == 5
    assert result.request_count == 5
    assert len(_read_rows(raw_index_global_path(tmp_path, "2022-01-04"))) == 5


def test_sequence_rejects_duplicate_phase_names() -> None:
    with pytest.raises(IndexGlobalRawValidationError, match="must be unique"):
        run_index_global_phase_sequence(
            lake_root_path=Path("/tmp/index-global-test"),
            duckdb_resource=_MemoryDuckDB(),
            tushare=_FakeTushare({}),
            trade_date="2022-01-04",
            run_id="run",
            request_policy=_request_policy(),
            phases=("asia_1", "asia_1"),
        )


def _read_rows(path: Path) -> list[tuple]:
    with duckdb.connect(":memory:") as connection:
        return connection.execute("SELECT * FROM read_parquet(?) ORDER BY ts_code", [str(path)]).fetchall()


def test_phase_merge_creates_fixed_schema_and_promotes_to_target(tmp_path: Path) -> None:
    result = merge_index_global_phase(
        lake_root_path=tmp_path,
        duckdb_resource=_MemoryDuckDB(),
        trade_date="2022-01-04",
        probe_phase="asia_1",
        phase_rows=[_row("XIN9")],
        run_id="run-1",
    )

    assert result.promoted is True
    assert result.output_row_count == 1
    assert raw_index_global_path(tmp_path, "2022-01-04").exists()
    assert not raw_index_global_staging_path(tmp_path, "run-1", "2022-01-04", "asia_1").exists()
    assert len(_read_rows(result.target_path)) == 1


def test_later_phase_wins_and_replaced_count_is_recorded(tmp_path: Path) -> None:
    first = merge_index_global_phase(
        lake_root_path=tmp_path,
        duckdb_resource=_MemoryDuckDB(),
        trade_date="2022-01-04",
        probe_phase="asia_1",
        phase_rows=[_row("XIN9", 1.0), _row("HSI", 2.0)],
        run_id="run-1",
    )
    second = merge_index_global_phase(
        lake_root_path=tmp_path,
        duckdb_resource=_MemoryDuckDB(),
        trade_date="2022-01-04",
        probe_phase="europe",
        phase_rows=[_row("XIN9", 9.0), _row("DJI", 3.0)],
        run_id="run-2",
    )

    assert first.output_row_count == 2
    assert second.output_row_count == 3
    assert second.replaced_row_count == 1
    assert _read_rows(second.target_path)[0][0] == "DJI"
    assert _read_rows(second.target_path)[-1][0] == "XIN9"


def test_all_five_normal_phases_accumulate_rows(tmp_path: Path) -> None:
    phases = (
        ("asia_1", "XIN9"),
        ("asia_2", "HSI"),
        ("asia_3", "N225"),
        ("europe", "FTSE"),
        ("americas", "SPX"),
    )
    for index, (phase, code) in enumerate(phases):
        result = merge_index_global_phase(
            lake_root_path=tmp_path,
            duckdb_resource=_MemoryDuckDB(),
            trade_date="2022-01-04",
            probe_phase=phase,
            phase_rows=[_row(code, float(index + 1))],
            run_id=f"run-{index}",
        )
        assert result.output_row_count == index + 1
    assert len(_read_rows(raw_index_global_path(tmp_path, "2022-01-04"))) == 5


def test_empty_phase_preserves_existing_target(tmp_path: Path) -> None:
    merge_index_global_phase(
        lake_root_path=tmp_path,
        duckdb_resource=_MemoryDuckDB(),
        trade_date="2022-01-04",
        probe_phase="asia_1",
        phase_rows=[_row()],
        run_id="run-1",
    )
    before = _read_rows(raw_index_global_path(tmp_path, "2022-01-04"))
    result = merge_index_global_phase(
        lake_root_path=tmp_path,
        duckdb_resource=_MemoryDuckDB(),
        trade_date="2022-01-04",
        probe_phase="late_empty",
        phase_rows=[],
        run_id="run-2",
    )
    assert result.promoted is False
    assert result.staging_path is None
    assert _read_rows(result.target_path) == before


def test_empty_phase_without_target_writes_empty_fixed_schema_file(tmp_path: Path) -> None:
    result = merge_index_global_phase(
        lake_root_path=tmp_path,
        duckdb_resource=_MemoryDuckDB(),
        trade_date="2022-01-04",
        probe_phase="late_empty",
        phase_rows=[],
        run_id="run-empty",
    )
    assert result.output_row_count == 0
    with duckdb.connect(":memory:") as connection:
        description = connection.execute(
            "DESCRIBE SELECT * FROM read_parquet(?)", [str(result.target_path)]
        ).fetchall()
    assert [row[0] for row in description] == [
        "ts_code", "trade_date", "open", "close", "high", "low", "pre_close",
        "change", "pct_chg", "swing", "vol", "amount",
    ]


def test_invalid_existing_target_is_not_replaced(tmp_path: Path) -> None:
    target = raw_index_global_path(tmp_path, "2022-01-04")
    target.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(":memory:") as connection:
        connection.execute("COPY (SELECT 1 AS wrong) TO ? (FORMAT PARQUET)", [str(target)])
    with pytest.raises(IndexGlobalRawValidationError):
        merge_index_global_phase(
            lake_root_path=tmp_path,
            duckdb_resource=_MemoryDuckDB(),
            trade_date="2022-01-04",
            probe_phase="asia_1",
            phase_rows=[_row()],
            run_id="run-invalid",
        )
    with duckdb.connect(":memory:") as connection:
        assert connection.execute(
            "SELECT wrong FROM read_parquet(?)", [str(target)]
        ).fetchall() == [(1,)]


def test_staging_copy_failure_preserves_existing_target(tmp_path: Path) -> None:
    merge_index_global_phase(
        lake_root_path=tmp_path,
        duckdb_resource=_MemoryDuckDB(),
        trade_date="2022-01-04",
        probe_phase="asia_1",
        phase_rows=[_row("XIN9", 1.0)],
        run_id="run-old",
    )
    target = raw_index_global_path(tmp_path, "2022-01-04")
    before = _read_rows(target)
    with patch(
        "orchestrator.defs.assets.index_global_raw.copy_query_to_parquet",
        side_effect=RuntimeError("staging failed"),
    ), pytest.raises(RuntimeError, match="staging failed"):
        merge_index_global_phase(
            lake_root_path=tmp_path,
            duckdb_resource=_MemoryDuckDB(),
            trade_date="2022-01-04",
            probe_phase="europe",
            phase_rows=[_row("XIN9", 9.0)],
            run_id="run-failed",
        )
    assert _read_rows(target) == before


def test_phase_duplicate_and_numeric_failure_do_not_create_target(tmp_path: Path) -> None:
    with pytest.raises(IndexGlobalRawValidationError):
        merge_index_global_phase(
            lake_root_path=tmp_path,
            duckdb_resource=_MemoryDuckDB(),
            trade_date="2022-01-04",
            probe_phase="asia_1",
            phase_rows=[_row(), _row()],
            run_id="run-duplicate",
        )
    invalid = _row()
    invalid["close"] = "not-a-number"
    with pytest.raises(IndexGlobalRawValidationError):
        merge_index_global_phase(
            lake_root_path=tmp_path,
            duckdb_resource=_MemoryDuckDB(),
            trade_date="2022-01-04",
            probe_phase="asia_1",
            phase_rows=[invalid],
            run_id="run-numeric",
        )
    assert not (tmp_path / "raw/index_global").exists()
