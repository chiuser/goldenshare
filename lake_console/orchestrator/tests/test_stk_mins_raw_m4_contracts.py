import json
import unittest
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from zoneinfo import ZoneInfo

from orchestrator.defs.assets import stk_mins
from orchestrator.defs.checks import stk_mins_checks
from orchestrator.defs.duckdb_sql import copy_query_to_parquet
from orchestrator.defs.jobs.stock_mins_raw_update import stock_mins_raw_update_job
from orchestrator.defs.paths import raw_stk_mins_path
from orchestrator.defs.resources import DuckDBResource, TushareResult
from orchestrator.defs.sensors import readiness
from orchestrator.defs.sensors.stock_mins_raw_sensor import (
    _cursor_payload as build_stock_mins_raw_sensor_cursor,
)
from orchestrator.defs.sensors.stock_mins_raw_sensor import (
    _has_materialized_check_problem,
    _latest_registered_trade_date,
    _run_request_for_trade_date,
)
from orchestrator.defs.sensors.stock_mins_trade_day_sensor import (
    _cursor_payload as build_stock_mins_trade_day_cursor,
)
from orchestrator.defs.sensors.stock_mins_trade_day_sensor import (
    build_stock_mins_trade_day_registration_decision,
)


PARTITION_KEY = "2026-05-29"
EVALUATED_AT = datetime(2026, 5, 29, 18, 30, tzinfo=ZoneInfo("Asia/Shanghai"))


class _FakeTushare:
    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    def call(self, api_name, params, fields):
        self.calls.append((api_name, dict(params), tuple(fields)))
        key = (params["ts_code"], int(params.get("offset", 0)))
        rows = self.pages.get(key, [])
        return TushareResult(rows=rows, columns=tuple(fields), metadata={})


class _FailingTushare:
    def call(self, api_name, params, fields):
        raise AssertionError("Tushare should not be called for reusable raw files")


class _LakeRoot:
    def __init__(self, root: Path):
        self._root = root

    def root(self) -> Path:
        return self._root


class _CheckContext:
    partition_key = PARTITION_KEY


class _AssetStatus:
    def __init__(self, *, materialized: bool, checks_passed: bool) -> None:
        self.materialized = materialized
        self.checks_passed = checks_passed


class _DatasetStatus:
    def __init__(self, statuses) -> None:
        self.statuses = tuple(statuses)


def _check_names(check_definitions) -> tuple[str, ...]:
    names = []
    for check_definition in check_definitions:
        check_key = next(iter(check_definition.check_keys))
        names.append(check_key.name)
    return tuple(sorted(names))


def _write_raw_stk_mins_file(path: Path, *, open_value: float = 10.0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with DuckDBResource().connect() as connection:
        connection.execute(
            copy_query_to_parquet(
                f"""
                SELECT
                  '600000.SH'::VARCHAR AS ts_code,
                  1::INTEGER AS freq,
                  TIMESTAMP '2026-05-29 09:30:00' AS trade_time,
                  {open_value}::DOUBLE AS open,
                  10.0::DOUBLE AS close,
                  10.0::DOUBLE AS high,
                  0.0::DOUBLE AS low,
                  0::BIGINT AS vol,
                  0.0::DOUBLE AS amount,
                  'XSHG'::VARCHAR AS exchange,
                  0.0::DOUBLE AS vwap
                """,
                path,
            )
        )


class StkMinsRawM4ContractTests(unittest.TestCase):
    def test_tushare_fetch_normalizes_freq_string_and_paginates(self) -> None:
        with TemporaryDirectory() as directory:
            lake_root = Path(directory)
            pages = {
                ("600000.SH", 0): [
                    {
                        "ts_code": "600000.SH",
                        "trade_time": "2026-05-29 09:30:00",
                        "open": 10.0,
                        "close": 10.1,
                        "high": 10.2,
                        "low": 9.9,
                        "vol": 100.0,
                        "amount": 1000.0,
                        "freq": "1min",
                        "exchange": "XSHG",
                        "vwap": 10.0,
                    }
                ],
            }
            tushare = _FakeTushare(pages)

            result = stk_mins.write_raw_stk_mins_partition(
                lake_root=lake_root,
                duckdb=DuckDBResource(),
                tushare=tushare,
                freq=1,
                partition_key=PARTITION_KEY,
                stock_codes=("600000.SH", "000001.SZ"),
                request_interval_seconds=0,
            )

            self.assertEqual(result.row_count, 1)
            self.assertEqual(result.returned_stock_code_count, 1)
            self.assertEqual(result.empty_stock_code_count, 1)
            self.assertEqual(result.page_count, 2)
            self.assertEqual(tushare.calls[0][1]["freq"], "1min")
            self.assertEqual(tushare.calls[0][1]["limit"], 8000)
            self.assertEqual(tushare.calls[0][1]["offset"], 0)

            with DuckDBResource().connect() as connection:
                row = connection.execute(
                    f"SELECT freq, vol FROM read_parquet('{result.raw_file_path.as_posix()}')"
                ).fetchone()
            self.assertEqual(row, (1, 100))

    def test_existing_valid_raw_file_is_reused_without_tushare_call(self) -> None:
        with TemporaryDirectory() as directory:
            lake_root = Path(directory)
            raw_path = raw_stk_mins_path(lake_root, 1, PARTITION_KEY)
            _write_raw_stk_mins_file(raw_path)

            result = stk_mins.write_raw_stk_mins_partition(
                lake_root=lake_root,
                duckdb=DuckDBResource(),
                tushare=_FailingTushare(),
                freq=1,
                partition_key=PARTITION_KEY,
                stock_codes=("600000.SH",),
                request_interval_seconds=0,
            )

            self.assertEqual(result.source_method, "existing_raw_partition_reused")
            self.assertEqual(result.row_count, 1)

    def test_existing_bad_raw_file_is_not_reused(self) -> None:
        with TemporaryDirectory() as directory:
            lake_root = Path(directory)
            raw_path = raw_stk_mins_path(lake_root, 1, PARTITION_KEY)
            _write_raw_stk_mins_file(raw_path, open_value=-1.0)

            with self.assertRaisesRegex(RuntimeError, "not reusable"):
                stk_mins.write_raw_stk_mins_partition(
                    lake_root=lake_root,
                    duckdb=DuckDBResource(),
                    tushare=_FailingTushare(),
                    freq=1,
                    partition_key=PARTITION_KEY,
                    stock_codes=("600000.SH",),
                    request_interval_seconds=0,
                )

    def test_raw_price_sanity_keeps_m3_legacy_zero_policy(self) -> None:
        with TemporaryDirectory() as directory:
            lake_root = Path(directory)
            raw_path = raw_stk_mins_path(lake_root, 1, PARTITION_KEY)
            _write_raw_stk_mins_file(raw_path)

            result = stk_mins_checks._price_volume_sanity(
                context=_CheckContext(),
                lake_root=_LakeRoot(lake_root),
                duckdb=DuckDBResource(),
                freq=1,
            )

            self.assertTrue(result.passed)

    def test_readiness_check_names_match_stk_mins_check_definitions(self) -> None:
        first_asset_check_definitions = stk_mins_checks.RAW_STK_MINS_CHECK_DEFINITIONS[
            : len(stk_mins_checks.RAW_STK_MINS_CHECK_NAMES)
        ]

        self.assertEqual(
            tuple(sorted(readiness.RAW_STK_MINS_CHECKS)),
            _check_names(first_asset_check_definitions),
        )

    def test_stock_mins_raw_update_job_selection_is_raw_only(self) -> None:
        selection_text = repr(stock_mins_raw_update_job.selection)

        self.assertIn("raw_stk_mins_1m", selection_text)
        self.assertIn("raw_stk_mins_60m", selection_text)
        self.assertNotIn("silver_stk_mins", selection_text)
        self.assertNotIn("silver_stock_basic", selection_text)

    def test_stock_mins_trade_day_decision_registers_after_six_pm(self) -> None:
        self.assertEqual(
            build_stock_mins_trade_day_registration_decision(
                today="2026-05-29",
                today_is_open=True,
                register_window_started=True,
                already_registered=False,
            ).selected_keys,
            ("2026-05-29",),
        )
        self.assertEqual(
            build_stock_mins_trade_day_registration_decision(
                today="2026-05-29",
                today_is_open=True,
                register_window_started=False,
                already_registered=False,
            ).selected_keys,
            (),
        )

    def test_stock_mins_sensor_cursors_and_run_request_contract(self) -> None:
        trade_day_decision = build_stock_mins_trade_day_registration_decision(
            today="2026-05-29",
            today_is_open=True,
            register_window_started=True,
            already_registered=False,
        )
        trade_day_cursor = json.loads(
            build_stock_mins_trade_day_cursor(
                decision=trade_day_decision,
                evaluated_at=EVALUATED_AT,
            )
        )
        self.assertEqual(trade_day_cursor["decision"], "register_partitions")
        self.assertEqual(trade_day_cursor["target_date"], "2026-05-29")
        self.assertEqual(
            trade_day_cursor["details"]["partition_set"],
            "cn_a_stock_mins_trade_days",
        )

        raw_cursor = json.loads(
            build_stock_mins_raw_sensor_cursor(
                evaluated_at=EVALUATED_AT,
                registered_trade_day_count=1,
                target_trade_date="2026-05-29",
                selected_trade_date="2026-05-29",
                reason="ready",
                source_window_started=True,
            )
        )
        self.assertEqual(raw_cursor["decision"], "request_runs")
        self.assertEqual(raw_cursor["target_date"], "2026-05-29")
        self.assertEqual(raw_cursor["selected_count"], 1)
        self.assertFalse(raw_cursor["details"]["stock_basic_freshness_required"])

        request = _run_request_for_trade_date("2026-05-29")
        self.assertEqual(request.partition_key, "2026-05-29")
        self.assertEqual(request.run_key, "stock_mins_raw_update:2026-05-29")
        self.assertEqual(request.tags, {})
        self.assertEqual(request.run_config, {})

    def test_latest_registered_trade_date_uses_latest_not_after_today(self) -> None:
        self.assertEqual(
            _latest_registered_trade_date(
                ("2026-05-28", "2026-05-29", "2026-05-30"),
                EVALUATED_AT,
            ),
            "2026-05-29",
        )
        self.assertIsNone(_latest_registered_trade_date(("2026-05-30",), EVALUATED_AT))

    def test_stock_mins_sensor_detects_materialized_check_problem(self) -> None:
        self.assertTrue(
            _has_materialized_check_problem(
                _DatasetStatus([_AssetStatus(materialized=True, checks_passed=False)])
            )
        )
        self.assertFalse(
            _has_materialized_check_problem(
                _DatasetStatus([_AssetStatus(materialized=False, checks_passed=False)])
            )
        )


if __name__ == "__main__":
    unittest.main()
