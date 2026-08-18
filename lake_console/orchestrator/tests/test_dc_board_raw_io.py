import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import duckdb

from orchestrator.defs.asset_guards.dc_board_source_probe import (
    DcBoardTushareSourceResult,
)
from orchestrator.defs.assets.dc_board import (
    DcBoardRawValidationError,
    write_dc_daily_partition,
    write_dc_index_partition,
    write_dc_member_partition,
)
from orchestrator.defs.paths import raw_dc_index_path, raw_dc_member_path
from orchestrator.defs.resources import TushareResult
from orchestrator.defs.run_contracts.configs import DcBoardIndexSourceSnapshotConfig
from orchestrator.defs.run_contracts.dc_board import (
    build_dc_board_prod_completion_snapshot,
    build_dc_board_tushare_source_snapshot,
)
from orchestrator.defs.tushare_request_policy import TushareRequestPolicy

_TRADE_DATE = "2026-07-14"
_RAW_TRADE_DATE = _TRADE_DATE.replace("-", "")


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
        "trade_date": _RAW_TRADE_DATE,
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
        "trade_date": _RAW_TRADE_DATE,
        "ts_code": code,
        "con_code": con_code,
        "name": "股票一",
    }


def _daily_row(category="行业板块", ts_code="BK0001.DC"):
    return {
        "ts_code": ts_code,
        "trade_date": _RAW_TRADE_DATE,
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


def _completion(codes=("BK0001.DC", "BK0002.DC", "BK0003.DC")):
    identities = tuple(
        zip(("行业板块", "概念板块", "地域板块")[: len(codes)], codes, strict=True)
    )
    return build_dc_board_prod_completion_snapshot(
        trade_date=_TRADE_DATE,
        index_identity=identities,
        daily_identity=identities,
        member_codes=codes,
        member_row_count=len(codes),
    )


def _source_result(*, close: float = 10.0, daily_missing_count: int = 0):
    codes = {
        "行业板块": "BK0001.DC",
        "概念板块": "BK0002.DC",
        "地域板块": "BK0003.DC",
    }
    index_rows = tuple(_index_row(idx_type, code) for idx_type, code in codes.items())
    daily_rows = tuple(
        {**_daily_row(category, code), "close": close}
        for category, code in codes.items()
    )
    snapshot = build_dc_board_tushare_source_snapshot(
        trade_date=_TRADE_DATE,
        index_rows=index_rows,
        daily_rows=daily_rows,
    )
    return DcBoardTushareSourceResult(
        trade_date=_TRADE_DATE,
        ready=True,
        reason_code="ready",
        request_count=4,
        page_count=4,
        retry_count=0,
        elapsed_ms=1.0,
        snapshot=snapshot,
        index_rows_by_type={
            idx_type: (_index_row(idx_type, code),) for idx_type, code in codes.items()
        },
        daily_rows=daily_rows,
        daily_missing_count=daily_missing_count,
    )


def _config(completion, source_result=None):
    source_result = source_result or _source_result()
    assert source_result.snapshot is not None
    observed_at = datetime.now(UTC).isoformat()
    return DcBoardIndexSourceSnapshotConfig(
        trade_date=_TRADE_DATE,
        prod_completion_observed_at=observed_at,
        prod_completion_fingerprint=completion.completion_fingerprint,
        tushare_source_observed_at=observed_at,
        tushare_source_fingerprint=source_result.snapshot.source_fingerprint,
    )


def _test_policy():
    return TushareRequestPolicy(
        minimum_interval_seconds=0.0,
        max_retries=0,
        max_requests=20,
        max_elapsed_seconds=30.0,
    )


def _write_daily_index_baseline(root: Path, codes: tuple[str, ...]) -> None:
    path = raw_dc_index_path(root, _TRADE_DATE)
    path.parent.mkdir(parents=True, exist_ok=True)
    categories = ("行业板块", "概念板块", "地域板块")
    values = ", ".join(
        f"('{code}', '{categories[index % len(categories)]}')"
        for index, code in enumerate(codes)
    )
    with duckdb.connect(":memory:") as connection:
        connection.execute(
            f"COPY (SELECT * FROM (VALUES {values}) AS t(ts_code, idx_type)) TO ? (FORMAT PARQUET)",
            [str(path)],
        )


def _full_response(api_name, params, _fields):
    codes = {"行业板块": "BK0001.DC", "概念板块": "BK0002.DC", "地域板块": "BK0003.DC"}
    if params["offset"]:
        return []
    if api_name == "dc_index":
        return [_index_row(params["idx_type"], codes[params["idx_type"]])]
    if api_name == "dc_daily":
        return [_daily_row(category, code) for category, code in codes.items()]
    raise AssertionError(api_name)


class DcBoardRawIoTests(unittest.TestCase):
    def test_index_requires_completion_and_source_fingerprints_to_match(self):
        completion = _completion()
        source_result = _source_result()
        assert source_result.snapshot is not None
        with (
            tempfile.TemporaryDirectory() as temp_dir,
            patch(
                "orchestrator.defs.assets.dc_board.require_closed_prod_dc_board_completion",
                return_value=completion,
            ),
            patch(
                "orchestrator.defs.assets.dc_board.load_tushare_dc_index_daily_source_snapshot",
                return_value=source_result,
            ),
        ):
            result = write_dc_index_partition(
                lake_root_path=Path(temp_dir),
                duckdb_resource=_MemoryDuckDB(),
                tushare=_FakeTushare(_full_response),
                prod_postgres=object(),
                partition_key=_TRADE_DATE,
                source_snapshot_config=_config(completion, source_result),
                policy=_test_policy(),
            )
        self.assertEqual(result.written_row_count, 3)
        self.assertEqual(
            result.prod_completion_fingerprint,
            completion.completion_fingerprint,
        )
        self.assertEqual(
            result.tushare_source_fingerprint,
            source_result.snapshot.source_fingerprint,
        )

    def test_index_rejects_changed_prod_completion_before_any_target_write(self):
        frozen_completion = _completion()
        fresh_completion = _completion(("BK0004.DC", "BK0005.DC", "BK0006.DC"))
        with (
            tempfile.TemporaryDirectory() as temp_dir,
            patch(
                "orchestrator.defs.assets.dc_board.require_closed_prod_dc_board_completion",
                return_value=fresh_completion,
            ),
        ):
            with self.assertRaisesRegex(
                DcBoardRawValidationError, "completion changed"
            ):
                write_dc_index_partition(
                    lake_root_path=Path(temp_dir),
                    duckdb_resource=_MemoryDuckDB(),
                    tushare=_FakeTushare(_full_response),
                    prod_postgres=object(),
                    partition_key=_TRADE_DATE,
                    source_snapshot_config=_config(frozen_completion),
                    policy=_test_policy(),
                )
            self.assertFalse((Path(temp_dir) / "raw/board/dc_index").exists())

    def test_index_rejects_changed_tushare_source_before_target_write(self):
        completion = _completion()
        frozen_source = _source_result(close=10.0)
        changed_source = _source_result(close=11.0)
        with (
            tempfile.TemporaryDirectory() as temp_dir,
            patch(
                "orchestrator.defs.assets.dc_board.require_closed_prod_dc_board_completion",
                return_value=completion,
            ),
            patch(
                "orchestrator.defs.assets.dc_board.load_tushare_dc_index_daily_source_snapshot",
                return_value=changed_source,
            ),
        ):
            with self.assertRaisesRegex(
                DcBoardRawValidationError, "Tushare source changed"
            ):
                write_dc_index_partition(
                    lake_root_path=Path(temp_dir),
                    duckdb_resource=_MemoryDuckDB(),
                    tushare=_FakeTushare(_full_response),
                    prod_postgres=object(),
                    partition_key=_TRADE_DATE,
                    source_snapshot_config=_config(completion, frozen_source),
                    policy=_test_policy(),
                )
            self.assertFalse((Path(temp_dir) / "raw/board/dc_index").exists())

    def test_daily_rejects_same_day_index_code_missing_from_source(self):
        completion = _completion()
        with (
            tempfile.TemporaryDirectory() as temp_dir,
            patch(
                "orchestrator.defs.assets.dc_board.require_closed_prod_dc_board_completion",
                return_value=completion,
            ),
        ):
            root = Path(temp_dir)
            _write_daily_index_baseline(
                root, ("BK0001.DC", "BK0002.DC", "BK0003.DC", "BK0004.DC")
            )
            with self.assertRaisesRegex(
                DcBoardRawValidationError, "same-day board code coverage"
            ):
                write_dc_daily_partition(
                    lake_root_path=root,
                    duckdb_resource=_MemoryDuckDB(),
                    tushare=_FakeTushare(_full_response),
                    prod_postgres=object(),
                    partition_key=_TRADE_DATE,
                    policy=_test_policy(),
                )

    def test_daily_allows_source_code_beyond_same_day_index(self):
        index_identity = (
            ("行业板块", "BK0001.DC"),
            ("概念板块", "BK0002.DC"),
            ("地域板块", "BK0003.DC"),
        )
        source_daily_identity = (*index_identity, ("行业板块", "BK0004.DC"))
        completion = build_dc_board_prod_completion_snapshot(
            trade_date=_TRADE_DATE,
            index_identity=index_identity,
            daily_identity=index_identity,
            member_codes=("BK0001.DC", "BK0002.DC", "BK0003.DC"),
            member_row_count=3,
        )

        def response(api_name, params, _fields):
            assert api_name == "dc_daily"
            if params["offset"]:
                return []
            return [
                _daily_row(category, code) for category, code in source_daily_identity
            ]

        with (
            tempfile.TemporaryDirectory() as temp_dir,
            patch(
                "orchestrator.defs.assets.dc_board.require_closed_prod_dc_board_completion",
                return_value=completion,
            ),
        ):
            root = Path(temp_dir)
            _write_daily_index_baseline(
                root,
                ("BK0001.DC", "BK0002.DC", "BK0003.DC"),
            )
            result = write_dc_daily_partition(
                lake_root_path=root,
                duckdb_resource=_MemoryDuckDB(),
                tushare=_FakeTushare(response),
                prod_postgres=object(),
                partition_key=_TRADE_DATE,
                policy=_test_policy(),
            )

        self.assertEqual(result.written_row_count, 4)
        self.assertEqual(
            result.source_closure_diagnostics["prod_daily_extra_identity_count"],
            1,
        )

    def test_member_prod_difference_triggers_stability_confirmation_then_promotes(self):
        completion = _completion(("BK0001.DC", "BK0002.DC"))
        calls: list[str] = []

        def response(api_name, params, _fields):
            assert api_name == "dc_member"
            if params["offset"]:
                return []
            calls.append(params["ts_code"])
            return [_member_row(params["ts_code"], "000001.SZ")]

        with (
            tempfile.TemporaryDirectory() as temp_dir,
            patch(
                "orchestrator.defs.assets.dc_board.require_closed_prod_dc_board_completion",
                return_value=completion,
            ),
            patch(
                "orchestrator.defs.assets.dc_board.load_prod_dc_member_pairs",
                return_value=(("BK0001.DC", "000001.SZ"),),
            ),
        ):
            result = write_dc_member_partition(
                lake_root_path=Path(temp_dir),
                duckdb_resource=_MemoryDuckDB(),
                tushare=_FakeTushare(response),
                prod_postgres=object(),
                partition_key=_TRADE_DATE,
                candidate_codes=("BK0001.DC", "BK0002.DC"),
                policy=_test_policy(),
            )

        self.assertEqual(calls, ["BK0001.DC", "BK0002.DC", "BK0002.DC"])
        self.assertEqual(result.written_row_count, 2)
        self.assertEqual(
            result.source_closure_diagnostics["member_prod_extra_pair_count"],
            1,
        )

    def test_member_changed_tushare_rows_during_confirmation_fail_closed(self):
        completion = _completion(("BK0001.DC", "BK0002.DC"))
        call_counts: dict[str, int] = {}

        def response(api_name, params, _fields):
            assert api_name == "dc_member"
            if params["offset"]:
                return []
            code = params["ts_code"]
            call_counts[code] = call_counts.get(code, 0) + 1
            if code == "BK0001.DC" and call_counts[code] == 1:
                return [_member_row(code, "000001.SZ")]
            if code == "BK0001.DC":
                return [
                    _member_row(code, "000001.SZ"),
                    _member_row(code, "000002.SZ"),
                ]
            return [_member_row(code, "000001.SZ")]

        pairs = (
            ("BK0001.DC", "000001.SZ"),
            ("BK0001.DC", "000002.SZ"),
            ("BK0002.DC", "000001.SZ"),
        )
        with (
            tempfile.TemporaryDirectory() as temp_dir,
            patch(
                "orchestrator.defs.assets.dc_board.require_closed_prod_dc_board_completion",
                return_value=completion,
            ),
            patch(
                "orchestrator.defs.assets.dc_board.load_prod_dc_member_pairs",
                return_value=pairs,
            ),
            self.assertRaisesRegex(DcBoardRawValidationError, "rows changed"),
        ):
            write_dc_member_partition(
                lake_root_path=Path(temp_dir),
                duckdb_resource=_MemoryDuckDB(),
                tushare=_FakeTushare(response),
                prod_postgres=object(),
                partition_key=_TRADE_DATE,
                candidate_codes=("BK0001.DC", "BK0002.DC"),
                policy=_test_policy(),
            )

        self.assertEqual(call_counts, {"BK0001.DC": 2, "BK0002.DC": 1})

    def test_member_affected_scope_is_sorted_and_replaces_stable_rows(self):
        completion = _completion(("BK0001.DC", "BK0002.DC"))
        calls: list[str] = []

        def response(api_name, params, _fields):
            assert api_name == "dc_member"
            if params["offset"]:
                return []
            code = params["ts_code"]
            calls.append(code)
            return [
                _member_row(code, "000001.SZ"),
                _member_row(code, "000002.SZ"),
            ]

        pairs = (
            ("BK0001.DC", "000001.SZ"),
            ("BK0002.DC", "000001.SZ"),
        )
        with (
            tempfile.TemporaryDirectory() as temp_dir,
            patch(
                "orchestrator.defs.assets.dc_board.require_closed_prod_dc_board_completion",
                return_value=completion,
            ),
            patch(
                "orchestrator.defs.assets.dc_board.load_prod_dc_member_pairs",
                return_value=pairs,
            ),
        ):
            result = write_dc_member_partition(
                lake_root_path=Path(temp_dir),
                duckdb_resource=_MemoryDuckDB(),
                tushare=_FakeTushare(response),
                prod_postgres=object(),
                partition_key=_TRADE_DATE,
                candidate_codes=("BK0002.DC", "BK0001.DC"),
                policy=_test_policy(),
            )

        self.assertEqual(
            calls,
            ["BK0002.DC", "BK0001.DC", "BK0001.DC", "BK0002.DC"],
        )
        self.assertEqual(result.request_count, 4)
        self.assertEqual(result.written_row_count, 4)

    def test_member_extra_pairs_trigger_only_affected_code_confirmation(self):
        completion = _completion(("BK0001.DC", "BK0002.DC"))
        calls: list[str] = []

        def response(api_name, params, _fields):
            assert api_name == "dc_member"
            if params["offset"]:
                return []
            code = params["ts_code"]
            calls.append(code)
            return [
                _member_row(code, "000001.SZ"),
                _member_row(code, "000002.SZ"),
            ]

        with (
            tempfile.TemporaryDirectory() as temp_dir,
            patch(
                "orchestrator.defs.assets.dc_board.require_closed_prod_dc_board_completion",
                return_value=completion,
            ),
            patch(
                "orchestrator.defs.assets.dc_board.load_prod_dc_member_pairs",
                return_value=(
                    ("BK0001.DC", "000001.SZ"),
                    ("BK0002.DC", "000001.SZ"),
                ),
            ),
        ):
            result = write_dc_member_partition(
                lake_root_path=Path(temp_dir),
                duckdb_resource=_MemoryDuckDB(),
                tushare=_FakeTushare(response),
                prod_postgres=object(),
                partition_key=_TRADE_DATE,
                candidate_codes=("BK0001.DC", "BK0002.DC"),
                policy=_test_policy(),
            )

        self.assertEqual(
            calls,
            ["BK0001.DC", "BK0002.DC", "BK0001.DC", "BK0002.DC"],
        )
        self.assertEqual(result.written_row_count, 4)

    def test_member_stable_source_promotes_even_when_prod_missing_diff_remains(self):
        completion = _completion(("BK0001.DC", "BK0002.DC"))
        calls: list[str] = []

        def response(api_name, params, _fields):
            assert api_name == "dc_member"
            if params["offset"]:
                return []
            calls.append(params["ts_code"])
            return [_member_row(params["ts_code"], "000001.SZ")]

        with (
            tempfile.TemporaryDirectory() as temp_dir,
            patch(
                "orchestrator.defs.assets.dc_board.require_closed_prod_dc_board_completion",
                return_value=completion,
            ),
            patch(
                "orchestrator.defs.assets.dc_board.load_prod_dc_member_pairs",
                return_value=(
                    ("BK0001.DC", "000001.SZ"),
                    ("BK0001.DC", "000002.SZ"),
                    ("BK0002.DC", "000001.SZ"),
                ),
            ),
        ):
            root = Path(temp_dir)
            target_path = raw_dc_member_path(root, _TRADE_DATE)
            target_path.parent.mkdir(parents=True)
            target_path.write_bytes(b"existing target")
            result = write_dc_member_partition(
                lake_root_path=root,
                duckdb_resource=_MemoryDuckDB(),
                tushare=_FakeTushare(response),
                prod_postgres=object(),
                partition_key=_TRADE_DATE,
                candidate_codes=("BK0001.DC", "BK0002.DC"),
                policy=_test_policy(),
            )
            self.assertNotEqual(target_path.read_bytes(), b"existing target")

        self.assertEqual(calls, ["BK0001.DC", "BK0002.DC", "BK0001.DC"])
        self.assertEqual(result.written_row_count, 2)
        self.assertEqual(
            result.source_closure_diagnostics["member_final_prod_missing_pair_count"],
            1,
        )

    def test_member_confirmation_respects_the_initial_round_request_budget(self):
        completion = _completion(("BK0001.DC", "BK0002.DC"))
        calls: list[str] = []

        def response(api_name, params, _fields):
            assert api_name == "dc_member"
            if params["offset"]:
                return []
            calls.append(params["ts_code"])
            return [_member_row(params["ts_code"], "000001.SZ")]

        exhausted_policy = TushareRequestPolicy(
            minimum_interval_seconds=0.0,
            max_retries=0,
            max_requests=2,
            max_elapsed_seconds=30.0,
        )
        with (
            tempfile.TemporaryDirectory() as temp_dir,
            patch(
                "orchestrator.defs.assets.dc_board.require_closed_prod_dc_board_completion",
                return_value=completion,
            ),
            patch(
                "orchestrator.defs.assets.dc_board.load_prod_dc_member_pairs",
                return_value=(
                    ("BK0001.DC", "000001.SZ"),
                    ("BK0001.DC", "000002.SZ"),
                    ("BK0002.DC", "000001.SZ"),
                ),
            ),
        ):
            root = Path(temp_dir)
            target_path = raw_dc_member_path(root, _TRADE_DATE)
            target_path.parent.mkdir(parents=True)
            target_path.write_bytes(b"existing target")
            with self.assertRaisesRegex(
                DcBoardRawValidationError,
                "code_scope_exceeds_remaining_request_budget",
            ):
                write_dc_member_partition(
                    lake_root_path=root,
                    duckdb_resource=_MemoryDuckDB(),
                    tushare=_FakeTushare(response),
                    prod_postgres=object(),
                    partition_key=_TRADE_DATE,
                    candidate_codes=("BK0001.DC", "BK0002.DC"),
                    policy=exhausted_policy,
                )
            self.assertEqual(target_path.read_bytes(), b"existing target")

        self.assertEqual(calls, ["BK0001.DC", "BK0002.DC"])

    def test_member_pair_match_promotes_atomically(self):
        completion = _completion(("BK0001.DC", "BK0002.DC"))

        def response(api_name, params, _fields):
            assert api_name == "dc_member"
            if params["offset"]:
                return []
            return [_member_row(params["ts_code"], "000001.SZ")]

        pairs = (("BK0001.DC", "000001.SZ"), ("BK0002.DC", "000001.SZ"))
        with (
            tempfile.TemporaryDirectory() as temp_dir,
            patch(
                "orchestrator.defs.assets.dc_board.require_closed_prod_dc_board_completion",
                return_value=completion,
            ),
            patch(
                "orchestrator.defs.assets.dc_board.load_prod_dc_member_pairs",
                return_value=pairs,
            ),
        ):
            result = write_dc_member_partition(
                lake_root_path=Path(temp_dir),
                duckdb_resource=_MemoryDuckDB(),
                tushare=_FakeTushare(response),
                prod_postgres=object(),
                partition_key=_TRADE_DATE,
                candidate_codes=("BK0001.DC", "BK0002.DC"),
                policy=_test_policy(),
            )
        self.assertEqual(result.written_row_count, 2)
        self.assertEqual(
            result.prod_completion_fingerprint,
            completion.completion_fingerprint,
        )
        self.assertEqual(
            result.source_closure_diagnostics["member_source_stability_code_count"],
            0,
        )


if __name__ == "__main__":
    unittest.main()
