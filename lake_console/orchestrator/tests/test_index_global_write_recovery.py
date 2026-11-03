"""Real temporary Raw/Silver files; transport only is replaced with a fixture.

Columns follow RAW_INDEX_GLOBAL_SCHEMA and source document 0211. Literal
expected prices/dates below are independent of the writer under test.
"""

import json
from contextlib import contextmanager
from datetime import date
from unittest.mock import patch

import duckdb
import pytest

from orchestrator.defs.assets.index_global_raw import (
    IndexGlobalFetchError,
    _raw_publication,
    merge_index_global_phase,
    run_index_global_phase,
)
from orchestrator.defs.assets.index_global_silver import (
    write_silver_index_global_partition,
)
from orchestrator.defs.paths import raw_index_global_path, raw_index_global_staging_path
from orchestrator.defs.resources import TushareResult
from orchestrator.defs.run_contracts.index_global import IndexGlobalRawValidationError
from orchestrator.defs.tushare_request_policy import TushareRequestPolicy


class MemoryDuckDB:
    @contextmanager
    def connect(self):
        connection = duckdb.connect(":memory:")
        try:
            yield connection
        finally:
            connection.close()


class FixtureSource:
    def __init__(self, *, missing_amount=False):
        self.calls = 0
        self.missing_amount = missing_amount

    def call(self, api, params, fields):
        self.calls += 1
        assert self.calls == 1, "continuation must reuse frozen source input"
        assert api == "index_global"
        assert params == {"trade_date": "20220104", "limit": 4000, "offset": 0}
        assert tuple(fields) == (
            "ts_code",
            "trade_date",
            "open",
            "close",
            "high",
            "low",
            "pre_close",
            "change",
            "pct_chg",
            "swing",
            "vol",
            "amount",
        )
        return TushareResult(
            rows=[
                {
                    "ts_code": "XIN9",
                    "trade_date": "20220104",
                    "open": 100.0,
                    "close": 101.0,
                    "high": 102.0,
                    "low": 99.0,
                    "pre_close": 99.5,
                    "change": 1.5,
                    "pct_chg": 1.5,
                    "swing": 3.0,
                    "vol": 1000.0,
                    "amount": float("nan") if self.missing_amount else None,
                }
            ],
            columns=tuple(fields),
            metadata={},
        )


def run_phase(root, source, *, operation="raw-operation", run_id="raw-run"):
    return run_index_global_phase(
        lake_root_path=root,
        duckdb_resource=MemoryDuckDB(),
        tushare=source,
        trade_date="2022-01-04",
        probe_phase="asia_1",
        run_id=run_id,
        publication_id=operation,
        request_policy=TushareRequestPolicy(minimum_interval_seconds=0, max_retries=0),
    )


def test_raw_to_silver_real_temporary_files_and_idempotent_replay(tmp_path):
    source = FixtureSource()
    fetched, raw = run_phase(tmp_path, source)
    before = raw.target_path.stat()
    fetched_again, replayed = run_phase(tmp_path, source, run_id="child-run")
    after = replayed.target_path.stat()
    assert (before.st_ino, before.st_mtime_ns) == (after.st_ino, after.st_mtime_ns)
    assert (
        source.calls == 1 and fetched_again.request_count == fetched.request_count == 1
    )
    silver = write_silver_index_global_partition(
        lake_root_path=tmp_path,
        duckdb_resource=MemoryDuckDB(),
        partition_key="2022-01-04",
        run_id="silver-operation",
    )
    with duckdb.connect(":memory:") as connection:
        assert connection.execute(
            "SELECT ts_code,trade_date,open,high,low,close,change_amount,amount "
            "FROM read_parquet(?)",
            [str(silver.target_file_path)],
        ).fetchall() == [
            ("XIN9", date(2022, 1, 4), 100.0, 102.0, 99.0, 101.0, 1.5, None)
        ]
    assert raw.output_row_count == silver.output_row_count == 1
    assert not list((tmp_path / "raw").rglob("_staging"))
    assert not list((tmp_path / "silver").rglob("_staging"))


def test_failed_candidate_retained_and_nan_normalized_before_freezing(tmp_path):
    source = FixtureSource(missing_amount=True)
    with (
        patch(
            "orchestrator.defs.assets.index_global_raw._validate_staging",
            side_effect=RuntimeError("candidate validation interrupted"),
        ),
        pytest.raises(RuntimeError, match="candidate validation interrupted"),
    ):
        run_phase(tmp_path, source)
    operation = raw_index_global_staging_path(
        tmp_path,
        "raw-operation",
        "2022-01-04",
        "asia_1",
    ).parent
    candidates = list(operation.glob("attempt=*/part-000.parquet"))
    assert len(candidates) == 1 and candidates[0].is_file()
    frozen_text = (operation / "phase_rows.json").read_text()
    assert "NaN" not in frozen_text and "Infinity" not in frozen_text
    assert json.loads(frozen_text)["rows"][0]["amount"] is None
    _, result = run_phase(tmp_path, source, run_id="retry-run")
    assert candidates[0].is_file(), (
        "failed evidence must survive successful continuation"
    )
    assert source.calls == 1 and result.output_row_count == 1
    with duckdb.connect(":memory:") as connection:
        assert connection.execute(
            "SELECT amount FROM read_parquet(?)",
            [str(result.target_path)],
        ).fetchall() == [(None,)]


def test_silver_completed_operation_does_not_repeat_copy(tmp_path):
    _, raw = run_phase(tmp_path, FixtureSource())
    arguments = {
        "lake_root_path": tmp_path,
        "duckdb_resource": MemoryDuckDB(),
        "partition_key": "2022-01-04",
        "run_id": "silver-first",
        "publication_id": "silver-root",
    }
    first = write_silver_index_global_partition(**arguments)
    before = first.target_file_path.stat()
    with patch(
        "orchestrator.defs.assets.index_global_silver.copy_query_to_parquet",
        side_effect=AssertionError("completed Silver must not COPY again"),
    ):
        repeated = write_silver_index_global_partition(
            **{**arguments, "run_id": "silver-child"}
        )
    assert repeated.output_row_count == raw.output_row_count == 1
    assert repeated.target_file_path.stat().st_ino == before.st_ino


def test_raw_rejects_mismatched_internal_publication_before_building(tmp_path):
    with (
        _raw_publication(tmp_path, "2022-01-03", "asia_1", "wrong-day") as publication,
        pytest.raises(IndexGlobalRawValidationError, match="scope differs"),
    ):
        merge_index_global_phase(
            lake_root_path=tmp_path,
            duckdb_resource=MemoryDuckDB(),
            trade_date="2022-01-04",
            probe_phase="asia_1",
            phase_rows=[],
            run_id="wrong-day",
            _publication=publication,
        )
    assert not raw_index_global_path(tmp_path, "2022-01-03").exists()
    assert not raw_index_global_path(tmp_path, "2022-01-04").exists()


def test_changed_target_after_fetch_failure_stops_before_another_request(tmp_path):
    class UnavailableSource:
        def call(self, api, params, fields):
            raise ConnectionError("deliberate isolated source failure")

    with pytest.raises(IndexGlobalFetchError):
        run_phase(tmp_path, UnavailableSource())
    target = raw_index_global_path(tmp_path, "2022-01-04")
    target.parent.mkdir(parents=True)
    target.write_bytes(b"another writer changed the target")
    source = FixtureSource()
    with pytest.raises(ValueError, match="target changed"):
        run_phase(tmp_path, source)
    assert source.calls == 0
    assert target.read_bytes() == b"another writer changed the target"
