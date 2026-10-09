import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import duckdb

from orchestrator.defs.asset_guards.dc_board_source_probe import (
    DcBoardTushareSourceResult,
)
from orchestrator.defs.assets.dc_board import write_dc_member_partition
from orchestrator.defs.resources import TushareResult
from orchestrator.defs.run_contracts.dc_board import (
    DC_BOARD_MAX_ELAPSED_MS,
    build_dc_board_prod_completion_snapshot,
    build_dc_board_tushare_source_snapshot,
)
from orchestrator.defs.tushare_request_policy import TushareRequestPolicy
from tests.dc_board_quote_test_support import prod_result, source_proof
from tests.test_dc_board_raw_io import _daily_row, _index_row


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


def _market_source(codes):
    types = ("行业板块", "概念板块", "地域板块")
    index = tuple(_index_row(types[i % 3], code) for i, code in enumerate(codes))
    daily = tuple(_daily_row(types[i % 3], code) for i, code in enumerate(codes))
    return DcBoardTushareSourceResult("2026-07-14", True, "ready", 4, 4, 0, 1.0,
        build_dc_board_tushare_source_snapshot(trade_date="2026-07-14", index_rows=index, daily_rows=daily),
        {t: tuple(row for row in index if row["idx_type"] == t) for t in types}, daily)


def _market_response(api_name, params, fields):
    source = _market_source(tuple(f"BK{i:04d}.DC" for i in range(1, 1023)))
    rows = source.index_rows_by_type[params["idx_type"]] if api_name == "dc_index" else source.daily_rows
    return TushareResult(rows=list(rows), columns=tuple(fields), metadata={})


class _FakeTushare:
    def __init__(self):
        self.request_count = 0

    def call(self, api_name, params, fields):
        self.request_count += 1
        self.assert_api = api_name
        if api_name in ("dc_index", "dc_daily"):
            return _market_response(api_name, params, fields)
        code = params["ts_code"]
        return TushareResult(
            rows=[
                {
                    "trade_date": "20260714",
                    "ts_code": code,
                    "con_code": "000001.SZ",
                    "name": "股票一",
                }
            ],
            columns=tuple(fields),
            metadata={},
        )


class DcBoardPerformanceTests(unittest.TestCase):
    def test_1022_member_codes_stay_within_budget_and_emit_temp_report(self):
        codes = tuple(f"BK{index:04d}.DC" for index in range(1, 1023))
        source = _FakeTushare()
        policy = TushareRequestPolicy(
            minimum_interval_seconds=0.0,
            max_retries=0,
            max_requests=1_200,
            max_elapsed_seconds=DC_BOARD_MAX_ELAPSED_MS / 1000,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            completion = build_dc_board_prod_completion_snapshot(
                trade_date="2026-07-14",
                index_identity=tuple(("行业板块", code) for code in codes),
                daily_identity=tuple(("行业板块", code) for code in codes),
                member_codes=codes,
                member_row_count=len(codes),
            )
            pairs = tuple((code, "000001.SZ") for code in codes)
            with (
                patch(
                    "orchestrator.defs.asset_guards.dc_board_source_freeze.load_prod_dc_board_reference_snapshot",
                    return_value=prod_result(completion),
                ),
                patch(
                    "orchestrator.defs.assets.dc_board.load_prod_dc_member_pairs",
                    return_value=pairs,
                ),
            ):
                result = write_dc_member_partition(
                    source_snapshot_config=source_proof(completion, _market_source(codes), "raw_tushare_dc_member"),
                    lake_root_path=Path(temp_dir),
                    duckdb_resource=_MemoryDuckDB(),
                    tushare=source,
                    prod_postgres=object(),
                    partition_key="2026-07-14",
                    candidate_codes=codes,
                    policy=policy,
                )
            report = {
                "code_count": len(codes),
                "request_count": result.request_count,
                "page_count": result.page_count,
                "retry_count": result.retry_count,
                "source_row_count": result.source_row_count,
                "written_row_count": result.written_row_count,
                "elapsed_ms": round(result.elapsed_ms, 3),
                "target_size_bytes": result.target_path.stat().st_size,
                "policy": policy.to_details(),
            }

        self.assertEqual(source.request_count, len(codes) + 8)
        self.assertEqual(result.request_count, len(codes) + 8)
        self.assertEqual(result.source_row_count, len(codes))
        self.assertEqual(result.written_row_count, len(codes))
        self.assertLess(result.request_count, policy.max_requests)
        self.assertLess(result.elapsed_ms, policy.max_elapsed_seconds * 1000)
        self.assertEqual(
            result.source_closure_diagnostics["member_source_stability_code_count"],
            0,
        )
        self.assertEqual(
            result.source_closure_diagnostics["member_source_stability_request_count"],
            0,
        )
        Path("/private/tmp/dc_board_m3_performance_20260714.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n"
        )

    def test_1022_member_codes_confirm_only_the_affected_board_within_shared_budget(
        self,
    ):
        codes = tuple(f"BK{index:04d}.DC" for index in range(1, 1023))
        call_counts: dict[str, int] = {}

        class _RepairingTushare:
            def call(self, api_name, params, fields):
                self.assert_api = api_name
                if api_name in ("dc_index", "dc_daily"):
                    return _market_response(api_name, params, fields)
                code = params["ts_code"]
                call_counts[code] = call_counts.get(code, 0) + 1
                rows = [
                    {
                        "trade_date": "20260714",
                        "ts_code": code,
                        "con_code": (
                            "000002.SZ" if code == "BK1022.DC" else "000001.SZ"
                        ),
                        "name": "股票一",
                    }
                ]
                return TushareResult(rows=rows, columns=tuple(fields), metadata={})

        policy = TushareRequestPolicy(
            minimum_interval_seconds=0.0,
            max_retries=0,
            max_requests=1_200,
            max_elapsed_seconds=DC_BOARD_MAX_ELAPSED_MS / 1000,
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            completion = build_dc_board_prod_completion_snapshot(
                trade_date="2026-07-14",
                index_identity=tuple(("行业板块", code) for code in codes),
                daily_identity=tuple(("行业板块", code) for code in codes),
                member_codes=codes,
                member_row_count=len(codes),
            )
            pairs = tuple((code, "000001.SZ") for code in codes)
            with (
                patch(
                    "orchestrator.defs.asset_guards.dc_board_source_freeze.load_prod_dc_board_reference_snapshot",
                    return_value=prod_result(completion),
                ),
                patch(
                    "orchestrator.defs.assets.dc_board.load_prod_dc_member_pairs",
                    return_value=pairs,
                ),
            ):
                result = write_dc_member_partition(
                    source_snapshot_config=source_proof(completion, _market_source(codes), "raw_tushare_dc_member"),
                    lake_root_path=Path(temp_dir),
                    duckdb_resource=_MemoryDuckDB(),
                    tushare=_RepairingTushare(),
                    prod_postgres=object(),
                    partition_key="2026-07-14",
                    candidate_codes=codes,
                    policy=policy,
                )

        self.assertEqual(sum(call_counts.values()), len(codes) + 1)
        self.assertEqual(call_counts["BK1022.DC"], 2)
        self.assertEqual(result.request_count, len(codes) + 9)
        self.assertEqual(
            result.source_closure_diagnostics["member_source_stability_code_count"],
            1,
        )
        self.assertEqual(
            result.source_closure_diagnostics["member_source_stability_request_count"],
            1,
        )
        self.assertLess(result.request_count, policy.max_requests)


if __name__ == "__main__":
    unittest.main()
