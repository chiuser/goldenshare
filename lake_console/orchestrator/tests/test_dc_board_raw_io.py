import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import duckdb

from orchestrator.defs.assets.dc_board import (
    DcBoardRawValidationError,
    write_dc_daily_partition,
    write_dc_index_partition,
    write_dc_member_partition,
)
from orchestrator.defs.paths import raw_dc_index_path
from orchestrator.defs.resources import TushareResult
from orchestrator.defs.run_contracts.configs import DcBoardIndexReferenceConfig
from orchestrator.defs.run_contracts.dc_board import build_dc_board_prod_reference_snapshot
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
    return {"trade_date": _RAW_TRADE_DATE, "ts_code": code, "con_code": con_code, "name": "股票一"}


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


def _reference(codes=("BK0001.DC", "BK0002.DC", "BK0003.DC")):
    identities = tuple(zip(("行业板块", "概念板块", "地域板块")[: len(codes)], codes, strict=True))
    return build_dc_board_prod_reference_snapshot(
        trade_date=_TRADE_DATE,
        index_identity=identities,
        daily_identity=identities,
        member_codes=codes,
        member_row_count=len(codes),
    )


def _config(reference):
    return DcBoardIndexReferenceConfig(
        reference_trade_date=_TRADE_DATE,
        reference_observed_at=datetime.now(UTC).isoformat(),
        reference_fingerprint=reference.fingerprint,
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
    values = ", ".join(f"('{code}')" for code in codes)
    with duckdb.connect(":memory:") as connection:
        connection.execute(
            f"COPY (SELECT * FROM (VALUES {values}) AS t(ts_code)) TO ? (FORMAT PARQUET)",
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
    def test_index_requires_sensor_fingerprint_to_match_fresh_prod_reference(self):
        reference = _reference()
        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "orchestrator.defs.assets.dc_board.require_closed_prod_dc_board_reference",
            return_value=reference,
        ):
            result = write_dc_index_partition(
                lake_root_path=Path(temp_dir),
                duckdb_resource=_MemoryDuckDB(),
                tushare=_FakeTushare(_full_response),
                prod_postgres=object(),
                partition_key=_TRADE_DATE,
                reference_config=_config(reference),
                policy=_test_policy(),
            )
        self.assertEqual(result.written_row_count, 3)
        self.assertEqual(result.reference_fingerprint, reference.fingerprint)

    def test_index_rejects_changed_prod_reference_before_any_target_write(self):
        frozen_reference = _reference()
        fresh_reference = _reference(("BK0004.DC", "BK0005.DC", "BK0006.DC"))
        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "orchestrator.defs.assets.dc_board.require_closed_prod_dc_board_reference",
            return_value=fresh_reference,
        ):
            with self.assertRaisesRegex(DcBoardRawValidationError, "reference changed"):
                write_dc_index_partition(
                    lake_root_path=Path(temp_dir),
                    duckdb_resource=_MemoryDuckDB(),
                    tushare=_FakeTushare(_full_response),
                    prod_postgres=object(),
                    partition_key=_TRADE_DATE,
                    reference_config=_config(frozen_reference),
                    policy=_test_policy(),
                )
            self.assertFalse((Path(temp_dir) / "raw/board/dc_index").exists())

    def test_daily_requires_tushare_raw_index_and_prod_identity_to_agree(self):
        reference = _reference()
        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "orchestrator.defs.assets.dc_board.require_closed_prod_dc_board_reference",
            return_value=reference,
        ):
            root = Path(temp_dir)
            _write_daily_index_baseline(root, ("BK0001.DC", "BK0002.DC", "BK0003.DC", "BK0004.DC"))
            with self.assertRaisesRegex(DcBoardRawValidationError, "same-day board code coverage"):
                write_dc_daily_partition(
                    lake_root_path=root,
                    duckdb_resource=_MemoryDuckDB(),
                    tushare=_FakeTushare(_full_response),
                    prod_postgres=object(),
                    partition_key=_TRADE_DATE,
                    policy=_test_policy(),
                )

    def test_member_pair_difference_blocks_target_promotion(self):
        reference = _reference(("BK0001.DC", "BK0002.DC"))

        def response(api_name, params, _fields):
            assert api_name == "dc_member"
            if params["offset"]:
                return []
            return [_member_row(params["ts_code"], "000001.SZ")]

        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "orchestrator.defs.assets.dc_board.require_closed_prod_dc_board_reference",
            return_value=reference,
        ), patch(
            "orchestrator.defs.assets.dc_board.load_prod_dc_member_pairs",
            return_value=(("BK0001.DC", "000001.SZ"),),
        ):
            with self.assertRaisesRegex(DcBoardRawValidationError, "pair identity differs"):
                write_dc_member_partition(
                    lake_root_path=Path(temp_dir),
                    duckdb_resource=_MemoryDuckDB(),
                    tushare=_FakeTushare(response),
                    prod_postgres=object(),
                    partition_key=_TRADE_DATE,
                    candidate_codes=("BK0001.DC", "BK0002.DC"),
                    policy=_test_policy(),
                )

    def test_member_pair_match_promotes_atomically(self):
        reference = _reference(("BK0001.DC", "BK0002.DC"))

        def response(api_name, params, _fields):
            assert api_name == "dc_member"
            if params["offset"]:
                return []
            return [_member_row(params["ts_code"], "000001.SZ")]

        pairs = (("BK0001.DC", "000001.SZ"), ("BK0002.DC", "000001.SZ"))
        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "orchestrator.defs.assets.dc_board.require_closed_prod_dc_board_reference",
            return_value=reference,
        ), patch(
            "orchestrator.defs.assets.dc_board.load_prod_dc_member_pairs",
            return_value=pairs,
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
        self.assertEqual(result.reference_fingerprint, reference.fingerprint)


if __name__ == "__main__":
    unittest.main()
