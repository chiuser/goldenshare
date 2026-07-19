import tempfile
import unittest
from pathlib import Path

import duckdb

from orchestrator.defs.assets.dc_board import (
    DcBoardRawValidationError,
    write_dc_daily_partition,
    write_dc_index_partition,
    write_dc_member_partition,
)
from orchestrator.defs.paths import raw_dc_index_path
from orchestrator.defs.resources import TushareResult


class _MemoryDuckDB:
    def connect(self):
        connection = duckdb.connect(":memory:")

        class _Context:
            def __enter__(self):
                return connection

            def __exit__(self, exc_type, exc, tb):
                connection.close()
                return False

        return _Context()


class _FakeTushare:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def call(self, api_name, params, fields):
        self.calls.append((api_name, dict(params), tuple(fields)))
        response = self.responses(api_name, params, tuple(fields))
        if isinstance(response, TushareResult):
            return response
        return TushareResult(rows=response, columns=tuple(fields), metadata={})


def _index_row(idx_type="行业板块", ts_code="BK0001.DC"):
    return {
        "ts_code": ts_code,
        "trade_date": "20260714",
        "name": "板块一",
        "leading": "股票一",
        "leading_code": "000001.SZ",
        "pct_change": 1.0,
        "leading_pct": 2.0,
        "total_mv": 100.0,
        "turnover_rate": 3.0,
        "up_num": 10,
        "down_num": 2,
        "idx_type": idx_type,
        "level": "L1",
    }


def _member_row(code="BK0001.DC", con_code="000001.SZ"):
    return {
        "trade_date": "20260714",
        "ts_code": code,
        "con_code": con_code,
        "name": "股票一",
    }


def _daily_row(category="行业板块", ts_code="BK0001.DC"):
    return {
        "ts_code": ts_code,
        "trade_date": "20260714",
        "close": 10.0,
        "open": 9.0,
        "high": 11.0,
        "low": 8.0,
        "change": 1.0,
        "pct_change": 10.0,
        "vol": 100.0,
        "amount": 1000.0,
        "swing": 3.0,
        "turnover_rate": 2.0,
        "category": category,
    }


def _write_daily_index_baseline(root: Path, codes: tuple[str, ...]) -> None:
    path = raw_dc_index_path(root, "2026-07-14")
    path.parent.mkdir(parents=True, exist_ok=True)
    values = ", ".join(f"('{code}')" for code in codes)
    with duckdb.connect(":memory:") as connection:
        connection.execute(
            f"COPY (SELECT * FROM (VALUES {values}) AS t(ts_code)) TO ? (FORMAT PARQUET)",
            [str(path)],
        )


class DcBoardRawIoTests(unittest.TestCase):
    def test_index_three_types_are_merged_and_written_atomically(self):
        def response(api_name, params, _fields):
            if api_name == "dc_index":
                code = {
                    "行业板块": "BK0001.DC",
                    "概念板块": "BK0002.DC",
                    "地域板块": "BK0003.DC",
                }[params["idx_type"]]
                return [_index_row(params["idx_type"], code)]
            raise AssertionError(api_name)

        with tempfile.TemporaryDirectory() as temp_dir:
            source = _FakeTushare(response)
            result = write_dc_index_partition(
                lake_root_path=Path(temp_dir),
                duckdb_resource=_MemoryDuckDB(),
                tushare=source,
                partition_key="2026-07-14",
                policy=_test_policy(),
            )
            self.assertEqual(result.source_row_count, 3)
            self.assertEqual(result.written_row_count, 3)
            self.assertEqual(len(source.calls), 3)
            self.assertEqual(
                duckdb.connect().execute(
                    "SELECT count(*) FROM read_parquet(?)", [str(result.target_path)]
                ).fetchone()[0],
                3,
            )

    def test_daily_preserves_category_as_part_of_key(self):
        def response(_api_name, params, _fields):
            if params["offset"] == 0:
                return [
                    _daily_row("行业板块"),
                    _daily_row("概念板块", "BK0002.DC"),
                    _daily_row("地域板块", "BK0003.DC"),
                ]
            return []

        with tempfile.TemporaryDirectory() as temp_dir:
            _write_daily_index_baseline(
                Path(temp_dir),
                ("BK0001.DC", "BK0002.DC", "BK0003.DC"),
            )
            result = write_dc_daily_partition(
                lake_root_path=Path(temp_dir),
                duckdb_resource=_MemoryDuckDB(),
                tushare=_FakeTushare(response),
                partition_key="2026-07-14",
                policy=_test_policy(),
            )
            connection = duckdb.connect()
            self.assertEqual(
                connection.execute(
                    "SELECT count(DISTINCT category) FROM read_parquet(?)",
                    [str(result.target_path)],
                ).fetchone()[0],
                3,
            )

    def test_daily_partial_source_fails_before_target_promotion(self):
        def response(_api_name, params, _fields):
            if params["offset"] == 0:
                return [
                    _daily_row("行业板块"),
                    _daily_row("概念板块", "BK0002.DC"),
                    _daily_row("地域板块", "BK0003.DC"),
                ]
            return []

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_daily_index_baseline(
                root,
                ("BK0001.DC", "BK0002.DC", "BK0003.DC", "BK0004.DC"),
            )
            with self.assertRaisesRegex(
                DcBoardRawValidationError,
                "same-day board code coverage is incomplete",
            ):
                write_dc_daily_partition(
                    lake_root_path=root,
                    duckdb_resource=_MemoryDuckDB(),
                    tushare=_FakeTushare(response),
                    partition_key="2026-07-14",
                    policy=_test_policy(),
                )
            self.assertFalse((root / "raw/board/dc_daily/trade_date=2026-07-14/part-000.parquet").exists())

    def test_member_requests_one_code_at_a_time_and_records_empty_code(self):
        def response(_api_name, params, _fields):
            if params["ts_code"] == "BK0002.DC":
                return []
            return [_member_row(params["ts_code"])]

        with tempfile.TemporaryDirectory() as temp_dir:
            source = _FakeTushare(response)
            result = write_dc_member_partition(
                lake_root_path=Path(temp_dir),
                duckdb_resource=_MemoryDuckDB(),
                tushare=source,
                partition_key="2026-07-14",
                candidate_codes=["BK0001.DC", "BK0002.DC"],
                policy=_test_policy(),
            )
            self.assertEqual(result.empty_codes, ("BK0002.DC",))
            self.assertEqual([call[1]["ts_code"] for call in source.calls], ["BK0001.DC", "BK0002.DC"])

    def test_validation_failure_keeps_existing_target_untouched(self):
        def response(_api_name, params, _fields):
            return [_daily_row(category="未知分类")]

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            target = root / "raw/board/dc_daily/trade_date=2026-07-14/part-000.parquet"
            target.parent.mkdir(parents=True)
            target.write_bytes(b"existing-target")
            with self.assertRaises(DcBoardRawValidationError):
                write_dc_daily_partition(
                    lake_root_path=root,
                    duckdb_resource=_MemoryDuckDB(),
                    tushare=_FakeTushare(response),
                    partition_key="2026-07-14",
                    policy=_test_policy(),
                )
            self.assertEqual(target.read_bytes(), b"existing-target")

    def test_column_drift_fails_before_target_promotion(self):
        def response(_api_name, _params, fields):
            return TushareResult(rows=[_daily_row()], columns=fields[:-1], metadata={})

        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaises(DcBoardRawValidationError):
                write_dc_daily_partition(
                    lake_root_path=Path(temp_dir),
                    duckdb_resource=_MemoryDuckDB(),
                    tushare=_FakeTushare(response),
                    partition_key="2026-07-14",
                    policy=_test_policy(),
                )

    def test_index_normalizes_tushare_nan_to_null(self):
        def response(_api_name, params, fields):
            if params["offset"]:
                return []
            code = {
                "行业板块": "BK0001.DC",
                "概念板块": "BK0002.DC",
                "地域板块": "BK0003.DC",
            }[params["idx_type"]]
            return [
                _index_row(params["idx_type"], code)
                | {"up_num": float("nan"), "down_num": float("nan")}
            ]

        with tempfile.TemporaryDirectory() as temp_dir:
            result = write_dc_index_partition(
                lake_root_path=Path(temp_dir),
                duckdb_resource=_MemoryDuckDB(),
                tushare=_FakeTushare(response),
                partition_key="2026-07-14",
                policy=_test_policy(),
            )
            connection = duckdb.connect()
            self.assertEqual(
                connection.execute(
                    "SELECT count(*) FROM read_parquet(?) WHERE up_num IS NULL AND down_num IS NULL",
                    [str(result.target_path)],
                ).fetchone()[0],
                3,
            )


def _test_policy():
    from orchestrator.defs.tushare_request_policy import TushareRequestPolicy

    return TushareRequestPolicy(
        minimum_interval_seconds=0.0,
        max_retries=0,
        max_requests=20,
        max_elapsed_seconds=30.0,
    )


if __name__ == "__main__":
    unittest.main()
