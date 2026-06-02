import json
import unittest
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from zoneinfo import ZoneInfo

import dagster as dg

from orchestrator.defs.assets import stk_mins
from orchestrator.defs.checks import stk_mins_checks
from orchestrator.defs.duckdb_sql import copy_query_to_parquet
from orchestrator.defs.jobs.stock_mins_raw_update import (
    stock_mins_raw_update_from_prod_job,
    stock_mins_raw_update_job,
)
from orchestrator.defs.paths import raw_stk_mins_path
from orchestrator.defs.prod_db.stk_mins import (
    PROD_STK_MINS_SELECT_SQL,
    validate_prod_stk_mins_select_contract,
)
from orchestrator.defs.resources import DuckDBResource, TushareResult
from orchestrator.defs.run_contracts.configs import (
    STOCK_MINS_RAW_CONFIG_SCHEMA,
    StockMinsMergeRepairConfig,
    build_stock_mins_raw_update_job_run_config,
    parse_stock_mins_raw_config,
)
from orchestrator.defs.run_contracts.stk_mins import (
    derive_stk_mins_exchange_from_ts_code,
)
from orchestrator.defs.sensors import readiness
from orchestrator.defs.sensors.stock_mins_raw_sensor import (
    _cursor_payload as build_stock_mins_raw_sensor_cursor,
)
from orchestrator.defs.sensors.stock_mins_raw_sensor import (
    STOCK_MINS_RAW_RUN_START,
    STOCK_MINS_RAW_SENSOR_JOB_NAME,
    STOCK_MINS_RAW_SOURCE,
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
from orchestrator.defs.sensors.stock_mins_silver_trade_day_sensor import (
    STOCK_MINS_SILVER_TRADE_DAY_REGISTER_START,
    _cursor_payload as build_stock_mins_silver_trade_day_cursor,
)
from orchestrator.defs.sensors.stock_mins_silver_trade_day_sensor import (
    _latest_registered_raw_trade_date,
    build_stock_mins_silver_trade_day_registration_decision,
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


class _FakeProdPostgres:
    @contextmanager
    def connect(self):
        yield object()


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


def _write_repair_target_raw_file(path: Path, *, row_freq: int = 1) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with DuckDBResource().connect() as connection:
        connection.execute(
            copy_query_to_parquet(
                f"""
                SELECT * FROM (
                  SELECT
                    '600000.SH'::VARCHAR AS ts_code,
                    {row_freq}::INTEGER AS freq,
                    TIMESTAMP '2026-05-29 09:30:00' AS trade_time,
                    1.0::DOUBLE AS open,
                    1.0::DOUBLE AS close,
                    1.0::DOUBLE AS high,
                    1.0::DOUBLE AS low,
                    100::BIGINT AS vol,
                    100.0::DOUBLE AS amount,
                    'XSHG'::VARCHAR AS exchange,
                    1.0::DOUBLE AS vwap
                  UNION ALL
                  SELECT
                    '600000.SH'::VARCHAR AS ts_code,
                    {row_freq}::INTEGER AS freq,
                    TIMESTAMP '2026-05-29 09:31:00' AS trade_time,
                    2.0::DOUBLE AS open,
                    2.0::DOUBLE AS close,
                    2.0::DOUBLE AS high,
                    2.0::DOUBLE AS low,
                    200::BIGINT AS vol,
                    400.0::DOUBLE AS amount,
                    'XSHG'::VARCHAR AS exchange,
                    2.0::DOUBLE AS vwap
                  UNION ALL
                  SELECT
                    '000001.SZ'::VARCHAR AS ts_code,
                    {row_freq}::INTEGER AS freq,
                    TIMESTAMP '2026-05-29 09:30:00' AS trade_time,
                    3.0::DOUBLE AS open,
                    3.0::DOUBLE AS close,
                    3.0::DOUBLE AS high,
                    3.0::DOUBLE AS low,
                    300::BIGINT AS vol,
                    900.0::DOUBLE AS amount,
                    'XSHE'::VARCHAR AS exchange,
                    3.0::DOUBLE AS vwap
                )
                ORDER BY ts_code, trade_time
                """,
                path,
            )
        )


def _repair_config(
    *,
    stock_codes: tuple[str, ...] = ("600000.SH",),
    start_time: str = "09:30:00",
    end_time: str = "09:32:00",
) -> StockMinsMergeRepairConfig:
    return StockMinsMergeRepairConfig(
        stock_codes=stock_codes,
        start_time=start_time,
        end_time=end_time,
    )


class StkMinsRawM4ContractTests(unittest.TestCase):
    def test_prod_db_exchange_and_vwap_derivation_contract(self) -> None:
        self.assertEqual(derive_stk_mins_exchange_from_ts_code("600000.SH"), "XSHG")
        self.assertEqual(derive_stk_mins_exchange_from_ts_code("000001.SZ"), "XSHE")
        self.assertEqual(derive_stk_mins_exchange_from_ts_code("920001.BJ"), "BSE")
        with self.assertRaisesRegex(ValueError, "Unsupported stk_mins ts_code suffix"):
            derive_stk_mins_exchange_from_ts_code("ABC.NY")

        normalized = stk_mins._normalize_prod_db_stk_mins_row(
            {
                "ts_code": "600000.SH",
                "freq": 1,
                "trade_time": datetime(2026, 5, 29, 9, 30),
                "open": 10.0,
                "close": 10.0,
                "high": 10.0,
                "low": 10.0,
                "vol": 100,
                "amount": 1234.5,
            },
            requested_ts_code="600000.SH",
            requested_freq=1,
            partition_key=PARTITION_KEY,
        )
        self.assertEqual(normalized["exchange"], "XSHG")
        self.assertEqual(normalized["vwap"], 12.345)
        zero_volume = stk_mins._normalize_prod_db_stk_mins_row(
            {
                "ts_code": "000001.SZ",
                "freq": 1,
                "trade_time": "2026-05-29 09:30:00",
                "open": 10.0,
                "close": 10.0,
                "high": 10.0,
                "low": 10.0,
                "vol": 0,
                "amount": 0.0,
            },
            requested_ts_code="000001.SZ",
            requested_freq=1,
            partition_key=PARTITION_KEY,
        )
        self.assertEqual(zero_volume["exchange"], "XSHE")
        self.assertEqual(zero_volume["vwap"], 0.0)

    def test_prod_db_select_uses_field_whitelist(self) -> None:
        validate_prod_stk_mins_select_contract()
        normalized_sql = " ".join(PROD_STK_MINS_SELECT_SQL.lower().split())
        self.assertNotIn("select *", normalized_sql)
        self.assertNotIn("api_name", normalized_sql)
        self.assertNotIn("fetched_at", normalized_sql)
        self.assertNotIn("raw_payload", normalized_sql)
        self.assertIn("ts_code = any(%(stock_codes)s)", normalized_sql)
        self.assertIn("where freq = %(freq)s", normalized_sql)
        self.assertIn("trade_time >=", normalized_sql)

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

    def test_prod_db_path_must_not_query_per_stock(self) -> None:
        with TemporaryDirectory() as directory:
            lake_root = Path(directory)
            calls = []

            def fake_fetch(
                connection,
                *,
                stock_codes,
                freq,
                start_datetime,
                end_datetime,
            ):
                calls.append(
                    {
                        "stock_codes": tuple(stock_codes),
                        "freq": freq,
                        "start_datetime": start_datetime,
                        "end_datetime": end_datetime,
                    }
                )
                return [
                    {
                        "ts_code": "600000.SH",
                        "freq": 1,
                        "trade_time": datetime(2026, 5, 29, 9, 30),
                        "open": 10.0,
                        "close": 10.0,
                        "high": 10.1,
                        "low": 9.9,
                        "vol": 100,
                        "amount": 1234.5,
                    }
                ]

            with patch.object(
                stk_mins,
                "fetch_prod_stk_mins_rows_for_stock_codes",
                fake_fetch,
            ):
                result = stk_mins.write_raw_stk_mins_partition_from_prod_db(
                    lake_root=lake_root,
                    duckdb=DuckDBResource(),
                    prod_postgres=_FakeProdPostgres(),
                    freq=1,
                    partition_key=PARTITION_KEY,
                    stock_codes=("600000.SH", "000001.SZ", "920001.BJ"),
                )

            self.assertEqual(result.source_method, "prod_db_raw_tushare")
            self.assertEqual(result.row_count, 1)
            self.assertEqual(result.returned_stock_code_count, 1)
            self.assertEqual(result.empty_stock_code_count, 2)
            self.assertEqual(result.query_count, 1)
            self.assertEqual(len(calls), 1)
            self.assertEqual(
                calls[0],
                {
                    "stock_codes": ("600000.SH", "000001.SZ", "920001.BJ"),
                    "freq": 1,
                    "start_datetime": "2026-05-29 09:00:00",
                    "end_datetime": "2026-05-29 19:00:00",
                },
            )

            with DuckDBResource().connect() as connection:
                row = connection.execute(
                    f"""
                    SELECT freq, vol, amount, exchange, vwap
                    FROM read_parquet('{result.raw_file_path.as_posix()}')
                    """
                ).fetchone()
            self.assertEqual(row, (1, 100, 1234.5, "XSHG", 12.345))

    def test_prod_db_batch_fetch_rejects_rows_outside_stock_pool(self) -> None:
        with TemporaryDirectory() as directory:
            lake_root = Path(directory)

            def fake_fetch(
                connection,
                *,
                stock_codes,
                freq,
                start_datetime,
                end_datetime,
            ):
                return [
                    {
                        "ts_code": "300001.SZ",
                        "freq": 1,
                        "trade_time": datetime(2026, 5, 29, 9, 30),
                        "open": 10.0,
                        "close": 10.0,
                        "high": 10.1,
                        "low": 9.9,
                        "vol": 100,
                        "amount": 1234.5,
                    }
                ]

            with patch.object(
                stk_mins,
                "fetch_prod_stk_mins_rows_for_stock_codes",
                fake_fetch,
            ):
                with self.assertRaisesRegex(RuntimeError, "outside the requested stock pool"):
                    stk_mins.write_raw_stk_mins_partition_from_prod_db(
                        lake_root=lake_root,
                        duckdb=DuckDBResource(),
                        prod_postgres=_FakeProdPostgres(),
                        freq=1,
                        partition_key=PARTITION_KEY,
                        stock_codes=("600000.SH", "000001.SZ"),
                    )

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

    def test_tushare_merge_repair_replaces_appends_and_preserves_other_rows(self) -> None:
        with TemporaryDirectory() as directory:
            lake_root = Path(directory)
            raw_path = raw_stk_mins_path(lake_root, 1, PARTITION_KEY)
            _write_repair_target_raw_file(raw_path)
            tushare = _FakeTushare(
                {
                    ("600000.SH", 0): [
                        {
                            "ts_code": "600000.SH",
                            "trade_time": "2026-05-29 09:30:00",
                            "open": 10.0,
                            "close": 10.0,
                            "high": 10.0,
                            "low": 10.0,
                            "vol": 1000.0,
                            "amount": 10000.0,
                            "freq": "1min",
                            "exchange": "XSHG",
                            "vwap": 10.0,
                        },
                        {
                            "ts_code": "600000.SH",
                            "trade_time": "2026-05-29 09:32:00",
                            "open": 12.0,
                            "close": 12.0,
                            "high": 12.0,
                            "low": 12.0,
                            "vol": 1200.0,
                            "amount": 14400.0,
                            "freq": "1min",
                            "exchange": "XSHG",
                            "vwap": 12.0,
                        },
                    ]
                }
            )

            result = stk_mins.merge_repair_raw_stk_mins_partition_from_tushare(
                lake_root=lake_root,
                duckdb=DuckDBResource(),
                tushare=tushare,
                freq=1,
                partition_key=PARTITION_KEY,
                repair_config=_repair_config(),
                request_interval_seconds=0,
            )

            self.assertEqual(result.source_method, "tushare_merge_repair")
            self.assertEqual(result.write_mode, "merge_repair")
            self.assertEqual(result.repair_replaced_row_count, 1)
            self.assertEqual(result.repair_appended_row_count, 1)
            self.assertEqual(result.repair_returned_row_count, 2)
            self.assertEqual(result.row_count, 4)

            with DuckDBResource().connect() as connection:
                rows = connection.execute(
                    f"""
                    SELECT ts_code, strftime(trade_time, '%H:%M:%S'), open
                    FROM read_parquet('{raw_path.as_posix()}')
                    ORDER BY ts_code, trade_time
                    """
                ).fetchall()
            self.assertEqual(
                rows,
                [
                    ("000001.SZ", "09:30:00", 3.0),
                    ("600000.SH", "09:30:00", 10.0),
                    ("600000.SH", "09:31:00", 2.0),
                    ("600000.SH", "09:32:00", 12.0),
                ],
            )

            metadata = result.materialization_extra_metadata(
                partition_key=PARTITION_KEY,
                freq=1,
            )
            self.assertEqual(metadata["write_mode"], "merge_repair")
            self.assertEqual(metadata["repair_stock_code_count"], 1)
            self.assertEqual(metadata["repair_start_time"], "09:30:00")
            self.assertEqual(metadata["repair_end_time"], "09:32:00")

    def test_tushare_merge_repair_rejects_missing_or_bad_target(self) -> None:
        with TemporaryDirectory() as directory:
            lake_root = Path(directory)
            with self.assertRaisesRegex(FileNotFoundError, "Cannot repair missing"):
                stk_mins.merge_repair_raw_stk_mins_partition_from_tushare(
                    lake_root=lake_root,
                    duckdb=DuckDBResource(),
                    tushare=_FakeTushare({}),
                    freq=1,
                    partition_key=PARTITION_KEY,
                    repair_config=_repair_config(),
                    request_interval_seconds=0,
                )

            raw_path = raw_stk_mins_path(lake_root, 1, PARTITION_KEY)
            _write_repair_target_raw_file(raw_path, row_freq=5)
            with self.assertRaisesRegex(RuntimeError, "not repairable"):
                stk_mins.merge_repair_raw_stk_mins_partition_from_tushare(
                    lake_root=lake_root,
                    duckdb=DuckDBResource(),
                    tushare=_FakeTushare({}),
                    freq=1,
                    partition_key=PARTITION_KEY,
                    repair_config=_repair_config(),
                    request_interval_seconds=0,
                )

    def test_tushare_merge_repair_rejects_empty_or_out_of_scope_source_rows(self) -> None:
        with TemporaryDirectory() as directory:
            lake_root = Path(directory)
            raw_path = raw_stk_mins_path(lake_root, 1, PARTITION_KEY)
            _write_repair_target_raw_file(raw_path)

            with self.assertRaisesRegex(RuntimeError, "returned 0 rows"):
                stk_mins.merge_repair_raw_stk_mins_partition_from_tushare(
                    lake_root=lake_root,
                    duckdb=DuckDBResource(),
                    tushare=_FakeTushare({("600000.SH", 0): []}),
                    freq=1,
                    partition_key=PARTITION_KEY,
                    repair_config=_repair_config(),
                    request_interval_seconds=0,
                )

            with self.assertRaisesRegex(RuntimeError, "outside the requested repair window"):
                stk_mins.merge_repair_raw_stk_mins_partition_from_tushare(
                    lake_root=lake_root,
                    duckdb=DuckDBResource(),
                    tushare=_FakeTushare(
                        {
                            ("600000.SH", 0): [
                                {
                                    "ts_code": "600000.SH",
                                    "trade_time": "2026-05-29 09:29:00",
                                    "open": 10.0,
                                    "close": 10.0,
                                    "high": 10.0,
                                    "low": 10.0,
                                    "vol": 100.0,
                                    "amount": 1000.0,
                                    "freq": "1min",
                                    "exchange": "XSHG",
                                    "vwap": 10.0,
                                }
                            ]
                        }
                    ),
                    freq=1,
                    partition_key=PARTITION_KEY,
                    repair_config=_repair_config(),
                    request_interval_seconds=0,
                )

            invalid_rows = (
                (
                    {
                        "ts_code": "000001.SZ",
                        "trade_time": "2026-05-29 09:30:00",
                        "freq": "1min",
                    },
                    "outside the requested stock code",
                ),
                (
                    {
                        "ts_code": "600000.SH",
                        "trade_time": "2026-05-29 09:30:00",
                        "freq": "5min",
                    },
                    "outside the requested frequency",
                ),
                (
                    {
                        "ts_code": "600000.SH",
                        "trade_time": "2026-05-28 09:30:00",
                        "freq": "1min",
                    },
                    "outside the requested trade date",
                ),
            )
            for partial_row, error_message in invalid_rows:
                row = {
                    "open": 10.0,
                    "close": 10.0,
                    "high": 10.0,
                    "low": 10.0,
                    "vol": 100.0,
                    "amount": 1000.0,
                    "exchange": "XSHG",
                    "vwap": 10.0,
                }
                row.update(partial_row)
                with self.assertRaisesRegex(RuntimeError, error_message):
                    stk_mins.merge_repair_raw_stk_mins_partition_from_tushare(
                        lake_root=lake_root,
                        duckdb=DuckDBResource(),
                        tushare=_FakeTushare({("600000.SH", 0): [row]}),
                        freq=1,
                        partition_key=PARTITION_KEY,
                        repair_config=_repair_config(),
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

        prod_selection_text = repr(stock_mins_raw_update_from_prod_job.selection)
        self.assertIn("raw_stk_mins_1m", prod_selection_text)
        self.assertIn("raw_stk_mins_60m", prod_selection_text)
        self.assertNotIn("silver_stk_mins", prod_selection_text)
        self.assertNotIn("silver_stock_basic", prod_selection_text)

    def test_stock_mins_prod_job_run_config_sets_source_only(self) -> None:
        run_config = build_stock_mins_raw_update_job_run_config(source="prod_db")
        self.assertEqual(
            sorted(run_config["ops"]),
            [
                "raw_stk_mins_15m",
                "raw_stk_mins_1m",
                "raw_stk_mins_30m",
                "raw_stk_mins_5m",
                "raw_stk_mins_60m",
            ],
        )
        for op_config in run_config["ops"].values():
            self.assertEqual(
                op_config,
                {
                    "config": {
                        "source": "prod_db",
                        "write_mode": {
                            "reuse_existing": {},
                        },
                    }
                },
            )

    def test_stock_mins_raw_config_selector_contract(self) -> None:
        @dg.asset(name="sample_stock_mins_raw", config_schema=STOCK_MINS_RAW_CONFIG_SCHEMA)
        def sample_stock_mins_raw(context):
            return context.op_config

        job = dg.define_asset_job(
            "sample_stock_mins_raw_job",
            selection=[sample_stock_mins_raw.key],
        )
        job_def = dg.Definitions(
            assets=[sample_stock_mins_raw],
            jobs=[job],
        ).resolve_job_def("sample_stock_mins_raw_job")

        dg.validate_run_config(job_def, {})
        dg.validate_run_config(
            job_def,
            {
                "ops": {
                    "sample_stock_mins_raw": {
                        "config": {
                            "source": "tushare",
                            "write_mode": {
                                "merge_repair": {
                                    "stock_codes": ["000030.SZ"],
                                    "start_time": "09:00:00",
                                    "end_time": "19:00:00",
                                }
                            },
                        }
                    }
                }
            },
        )
        with self.assertRaises(dg.DagsterInvalidConfigError):
            dg.validate_run_config(
                job_def,
                {
                    "ops": {
                        "sample_stock_mins_raw": {
                            "config": {
                                "source": "tushare",
                                "write_mode": {
                                    "reuse_existing": {},
                                    "merge_repair": {
                                        "stock_codes": ["000030.SZ"],
                                        "start_time": "09:00:00",
                                        "end_time": "19:00:00",
                                    },
                                },
                            }
                        }
                    }
                },
            )

    def test_stock_mins_raw_config_parser_rejects_unsafe_repair_config(self) -> None:
        self.assertEqual(
            parse_stock_mins_raw_config({}).write_mode,
            "reuse_existing",
        )
        with self.assertRaisesRegex(ValueError, "only supports source=tushare"):
            parse_stock_mins_raw_config(
                {
                    "source": "prod_db",
                    "write_mode": {
                        "merge_repair": {
                            "stock_codes": ["000030.SZ"],
                            "start_time": "09:00:00",
                            "end_time": "19:00:00",
                        }
                    },
                }
            )
        for invalid_config in (
            {
                "source": "tushare",
                "write_mode": {
                    "merge_repair": {
                        "stock_codes": [],
                        "start_time": "09:00:00",
                        "end_time": "19:00:00",
                    }
                },
            },
            {
                "source": "tushare",
                "write_mode": {
                    "merge_repair": {
                        "stock_codes": ["000030.SZ", "000030.SZ"],
                        "start_time": "09:00:00",
                        "end_time": "19:00:00",
                    }
                },
            },
            {
                "source": "tushare",
                "write_mode": {
                    "merge_repair": {
                        "stock_codes": ["000030.SZ"],
                        "start_time": "090000",
                        "end_time": "19:00:00",
                    }
                },
            },
            {
                "source": "tushare",
                "write_mode": {
                    "merge_repair": {
                        "stock_codes": ["000030.SZ"],
                        "start_time": "19:00:00",
                        "end_time": "09:00:00",
                    }
                },
            },
        ):
            with self.assertRaises(ValueError):
                parse_stock_mins_raw_config(invalid_config)

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

    def test_stock_mins_silver_trade_day_decision_requires_all_gates(self) -> None:
        selected = build_stock_mins_silver_trade_day_registration_decision(
            target_trade_date="2026-05-29",
            register_window_started=True,
            already_registered=False,
            raw_ready=True,
            stock_daily_ready=True,
            suspend_ready=True,
            identity_map_ready=True,
            namechange_ready=True,
        )
        before_window = build_stock_mins_silver_trade_day_registration_decision(
            target_trade_date="2026-05-29",
            register_window_started=False,
            already_registered=False,
            raw_ready=True,
            stock_daily_ready=True,
            suspend_ready=True,
            identity_map_ready=True,
            namechange_ready=True,
        )
        raw_blocked = build_stock_mins_silver_trade_day_registration_decision(
            target_trade_date="2026-05-29",
            register_window_started=True,
            already_registered=False,
            raw_ready=False,
            stock_daily_ready=True,
            suspend_ready=True,
            identity_map_ready=True,
            namechange_ready=True,
        )

        self.assertEqual(selected.selected_keys, ("2026-05-29",))
        self.assertEqual(before_window.selected_keys, ())
        self.assertIn("22:30", before_window.reason)
        self.assertEqual(raw_blocked.selected_keys, ())
        self.assertIn("raw 五频度", raw_blocked.reason)

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

        silver_decision = build_stock_mins_silver_trade_day_registration_decision(
            target_trade_date="2026-05-29",
            register_window_started=True,
            already_registered=False,
            raw_ready=True,
            stock_daily_ready=True,
            suspend_ready=True,
            identity_map_ready=True,
            namechange_ready=True,
        )
        silver_cursor = json.loads(
            build_stock_mins_silver_trade_day_cursor(
                decision=silver_decision,
                evaluated_at=EVALUATED_AT,
                raw_registered_trade_day_count=1,
                silver_registered_trade_day_count=0,
            )
        )
        self.assertEqual(silver_cursor["decision"], "register_partitions")
        self.assertEqual(silver_cursor["target_date"], "2026-05-29")
        self.assertEqual(
            silver_cursor["details"]["raw_partition_set"],
            "cn_a_stock_mins_trade_days",
        )
        self.assertEqual(
            silver_cursor["details"]["partition_set"],
            "cn_a_stock_mins_silver_trade_days",
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
        self.assertEqual(raw_cursor["details"]["source"], "prod_db")
        self.assertEqual(
            raw_cursor["details"]["job_name"],
            "stock_mins_raw_update_from_prod_job",
        )
        self.assertFalse(raw_cursor["details"]["stock_basic_freshness_required"])

        request = _run_request_for_trade_date("2026-05-29")
        self.assertEqual(request.partition_key, "2026-05-29")
        self.assertEqual(
            request.run_key,
            "stock_mins_raw_update_from_prod:2026-05-29",
        )
        self.assertEqual(request.tags, {})
        self.assertEqual(request.run_config, {})
        self.assertEqual(
            STOCK_MINS_RAW_SENSOR_JOB_NAME,
            "stock_mins_raw_update_from_prod_job",
        )
        self.assertEqual(STOCK_MINS_RAW_RUN_START.isoformat(), "22:00:00")
        self.assertEqual(STOCK_MINS_RAW_SOURCE, "prod_db")
        self.assertEqual(
            STOCK_MINS_SILVER_TRADE_DAY_REGISTER_START.isoformat(),
            "22:30:00",
        )

    def test_latest_registered_trade_date_uses_latest_not_after_today(self) -> None:
        self.assertEqual(
            _latest_registered_trade_date(
                ("2026-05-28", "2026-05-29", "2026-05-30"),
                EVALUATED_AT,
            ),
            "2026-05-29",
        )
        self.assertIsNone(_latest_registered_trade_date(("2026-05-30",), EVALUATED_AT))
        self.assertEqual(
            _latest_registered_raw_trade_date(
                ("2013-12-31", "2014-01-02", "2026-05-29", "2026-05-30"),
                EVALUATED_AT,
            ),
            "2026-05-29",
        )
        self.assertIsNone(_latest_registered_raw_trade_date(("2013-12-31",), EVALUATED_AT))

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
