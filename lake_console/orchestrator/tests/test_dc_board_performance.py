import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import duckdb

from orchestrator.defs.assets.dc_board import write_dc_member_partition
from orchestrator.defs.resources import TushareResult
from orchestrator.defs.run_contracts.dc_board import (
    DC_BOARD_MAX_ELAPSED_MS,
    build_dc_board_prod_completion_snapshot,
)
from orchestrator.defs.tushare_request_policy import TushareRequestPolicy


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
    def __init__(self):
        self.request_count = 0

    def call(self, api_name, params, fields):
        self.request_count += 1
        self.assert_api = api_name
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

        self.assertEqual(source.request_count, len(codes))
        self.assertEqual(result.request_count, len(codes))
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
                    tushare=_RepairingTushare(),
                    prod_postgres=object(),
                    partition_key="2026-07-14",
                    candidate_codes=codes,
                    policy=policy,
                )

        self.assertEqual(sum(call_counts.values()), len(codes) + 1)
        self.assertEqual(call_counts["BK1022.DC"], 2)
        self.assertEqual(result.request_count, len(codes) + 1)
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
