import json
import unittest
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

import dagster as dg
import duckdb

from orchestrator.defs.assets import stk_mins
from orchestrator.defs.asset_guards.stk_mins_lake_readiness import (
    StkMinsBatchReadiness,
    StkMinsDateReadiness,
)
from orchestrator.defs.asset_guards.stk_mins_prod_readiness import (
    StkMinsProdSourceReadiness,
)
from orchestrator.defs.asset_guards.stk_mins_stock_universe import (
    load_current_listed_stock_codes_for_stk_mins,
    stk_mins_stock_code_set_hash,
)
from orchestrator.defs.checks import stk_mins_checks
from orchestrator.defs.duckdb_sql import copy_query_to_parquet
from orchestrator.defs.duckdb_sql import duckdb_string
from orchestrator.defs.jobs.stock_mins_raw_update import (
    stock_mins_raw_update_from_prod_job,
    stock_mins_raw_update_job,
)
from orchestrator.defs.paths import (
    raw_stk_mins_path,
    silver_stock_basic_path,
    silver_trade_calendar_path,
)
from orchestrator.defs.prod_db.stk_mins import (
    PROD_STK_MINS_DUCKDB_ATTACHED_DATABASE,
    PROD_STK_MINS_DUCKDB_ATTACH_OPTIONS,
    build_prod_stk_mins_duckdb_source_sql,
    build_prod_stk_mins_remote_query,
    validate_prod_stk_mins_duckdb_attach_options_contract,
    validate_prod_stk_mins_duckdb_source_contract,
    validate_prod_stk_mins_select_contract,
    ProdStkMinsCodeCoverageProbe,
    ProdStkMinsFrequencyCoverage,
)
from orchestrator.defs.prod_db.stk_mins_task_run import (
    ProdStkMinsFullMarketTaskRun,
    ProdStkMinsTaskRunProbe,
)
from orchestrator.defs.resources import DuckDBResource, TushareResult
from orchestrator.defs.run_contracts.configs import (
    STOCK_MINS_RAW_CONFIG_SCHEMA,
    StockMinsMergeRepairConfig,
    build_stock_mins_raw_update_job_run_config,
    parse_stock_mins_raw_config,
)
from orchestrator.defs.run_contracts.stk_mins import (
    build_prod_stk_mins_completion_reference,
    derive_stk_mins_exchange_from_ts_code,
)
from orchestrator.defs.sensors import (
    readiness,
    stock_mins_raw_sensor as stock_mins_raw_sensor_module,
)
from orchestrator.defs.sensors.stock_mins_raw_sensor import (
    _cursor_payload as build_stock_mins_raw_sensor_cursor,
)
from orchestrator.defs.sensors.stock_mins_raw_sensor import (
    STOCK_MINS_RAW_RUN_START,
    STOCK_MINS_RAW_SENSOR_JOB_NAME,
    STOCK_MINS_RAW_SOURCE,
    _has_materialized_check_problem,
    _run_request_for_trade_date,
    stock_mins_raw_sensor,
)
from orchestrator.defs.sensors.stock_mins_silver_trade_day_sensor import (
    STOCK_MINS_SILVER_TRADE_DAY_REGISTER_START,
    _cursor_payload as build_stock_mins_silver_trade_day_cursor,
)
from orchestrator.defs.sensors.stock_mins_silver_trade_day_sensor import (
    build_stock_mins_silver_trade_day_registration_decision,
)


PARTITION_KEY = "2026-05-29"
EVALUATED_AT = datetime(2026, 5, 29, 18, 30, tzinfo=ZoneInfo("Asia/Shanghai"))


class _AfterRawWindowDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 5, 29, 19, 35, tzinfo=tz)


class _BeforeRawWindowDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 5, 29, 19, 29, tzinfo=tz)


class _AfterMidnightDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 5, 30, 0, 5, tzinfo=tz)


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

    def duckdb_connection_string(self) -> str:
        return "host=unused user=fake password=fake-secret dbname=unused"


class _LakeRoot:
    def __init__(self, root: Path):
        self._root = root

    def root(self) -> Path:
        return self._root

    def ensure_available_for_run(self) -> None:
        return None


class _SensorDuckDBResource:
    @contextmanager
    def connect(self):
        with duckdb.connect(database=":memory:") as connection:
            yield connection


class _CheckContext:
    partition_key = PARTITION_KEY


class _AssetStatus:
    def __init__(self, *, materialized: bool, checks_passed: bool) -> None:
        self.materialized = materialized
        self.checks_passed = checks_passed


class _DatasetStatus:
    def __init__(self, statuses) -> None:
        self.statuses = tuple(statuses)


class _StockMinsRawSensorInstance:
    def __init__(self, partitions: tuple[str, ...] = (PARTITION_KEY,)) -> None:
        self._partitions = partitions

    def get_dynamic_partitions(self, _name: str) -> list[str]:
        return list(self._partitions)


class _StockMinsRawSensorContext:
    def __init__(self, partitions: tuple[str, ...] = (PARTITION_KEY,)) -> None:
        self._temp_dir = TemporaryDirectory()
        lake_root = Path(self._temp_dir.name)
        _write_stock_mins_sensor_calendar_file(lake_root)
        self.instance = _StockMinsRawSensorInstance(partitions)
        self.resources = SimpleNamespace(
            lake_root=_LakeRoot(lake_root),
            duckdb=_SensorDuckDBResource(),
            prod_postgres=_FakeProdPostgres(),
        )

    def cleanup(self) -> None:
        self._temp_dir.cleanup()


def _sensor_asset_status(
    *,
    asset_key: str,
    ready: bool,
    materialized: bool,
    checks_passed: bool,
    freshness_passed: bool,
    reason: str,
) -> readiness.AssetReadinessStatus:
    return readiness.AssetReadinessStatus(
        asset_key=asset_key,
        partition_key=None,
        ready=ready,
        materialized=materialized,
        checks_passed=checks_passed,
        freshness_passed=freshness_passed,
        materialization_storage_id=1 if materialized else None,
        materialization_date=PARTITION_KEY if freshness_passed else "2026-05-28",
        missing_check_names=() if checks_passed else (f"{asset_key}_file_exists",),
        failed_check_names=(),
        reason=reason,
    )


def _raw_stk_mins_sensor_status(
    *,
    ready: bool,
    materialized: bool = False,
    checks_passed: bool = False,
    reason: str = "raw_stk_mins_1m has no materialization",
) -> readiness.DatasetReadinessStatus:
    return readiness.DatasetReadinessStatus(
        ready=ready,
        statuses=(
            _sensor_asset_status(
                asset_key="raw_stk_mins_1m",
                ready=ready,
                materialized=materialized,
                checks_passed=checks_passed,
                freshness_passed=ready,
                reason=reason,
            ),
        ),
    )


def _raw_stk_mins_lake_status(
    *,
    ready: bool,
    materialized: bool = False,
    checks_passed: bool = False,
    reason: str = "raw_stk_mins_1m has no materialization",
) -> StkMinsDateReadiness:
    return StkMinsDateReadiness(
        trade_date=PARTITION_KEY,
        ready=ready,
        materialized=materialized,
        checks_passed=checks_passed,
        reason=reason,
        failed_check_names=(
            () if ready else ("raw_stk_mins_contract_check",)
        ),
        missing_file_paths=(),
        expected_file_count=5,
        existing_file_count=5 if materialized else 0,
    )


def _raw_stk_mins_batch_status(status: StkMinsDateReadiness) -> StkMinsBatchReadiness:
    return StkMinsBatchReadiness(
        dataset="raw_stk_mins",
        expected_start_date=PARTITION_KEY,
        expected_end_date=PARTITION_KEY,
        expected_count=1,
        freq_count=5,
        elapsed_ms=1.0,
        statuses_by_trade_date={PARTITION_KEY: status},
    )


def _stock_basic_sensor_status(
    *,
    ready: bool,
    freshness_passed: bool = True,
    reason: str = "ready",
) -> readiness.DatasetReadinessStatus:
    return readiness.DatasetReadinessStatus(
        ready=ready,
        statuses=(
            _sensor_asset_status(
                asset_key="raw_tushare_stock_basic",
                ready=ready,
                materialized=True,
                checks_passed=True,
                freshness_passed=freshness_passed,
                reason=reason,
            ),
            _sensor_asset_status(
                asset_key="silver_stock_basic",
                ready=ready,
                materialized=True,
                checks_passed=True,
                freshness_passed=freshness_passed,
                reason=reason,
            ),
        ),
    )


def _prod_completion_reference():
    return build_prod_stk_mins_completion_reference(
        task_run_id=101,
        trade_date=PARTITION_KEY,
        ended_at="2026-05-29T19:30:00+08:00",
        expected_code_count=1,
        expected_code_hash=stk_mins_stock_code_set_hash(("600000.SH",)),
        frequency_code_counts={freq: 1 for freq in (1, 5, 15, 30, 60)},
        coverage_observed_at="2026-05-29T19:35:00+08:00",
    )


def _prod_source_readiness(*, ready: bool = True) -> StkMinsProdSourceReadiness:
    task_run = ProdStkMinsFullMarketTaskRun(
        task_run_id=101,
        trade_date=PARTITION_KEY,
        ended_at="2026-05-29T19:30:00+08:00",
        unit_total=5,
        unit_done=5,
        unit_failed=0,
        progress_percent=100.0,
        rows_fetched=5,
        rows_saved=5,
        rows_rejected=0,
    )
    task_run_status = ProdStkMinsTaskRunProbe(
        ready=ready,
        reason_code=("prod_ops_task_run_ready" if ready else "prod_ops_task_run_missing"),
        task_run=task_run if ready else None,
        candidate_task_run_id=101 if ready else None,
        candidate_status="success" if ready else None,
        candidate_reason_code=None,
        elapsed_ms=1,
    )
    frequency_coverages = tuple(
        ProdStkMinsFrequencyCoverage(
            freq=freq,
            expected_code_count=1,
            present_code_count=1 if ready else 0,
            missing_code_count=0 if ready else 1,
            missing_code_samples=() if ready else ("600000.SH",),
        )
        for freq in (1, 5, 15, 30, 60)
    )
    coverage_status = ProdStkMinsCodeCoverageProbe(
        ready=ready,
        reason_code=(
            "prod_source_code_coverage_ready"
            if ready
            else "prod_source_code_coverage_incomplete"
        ),
        frequency_coverages=frequency_coverages,
        first_missing_freq=None if ready else 1,
        elapsed_ms=1,
    )
    return StkMinsProdSourceReadiness(
        ready=ready,
        reason_code=("prod_source_ready" if ready else coverage_status.reason_code),
        task_run_status=task_run_status,
        coverage_status=coverage_status,
        completion_reference=_prod_completion_reference() if ready else None,
    )


def _stock_mins_raw_sensor_result(context: _StockMinsRawSensorContext):
    return stock_mins_raw_sensor._raw_fn(context)


def _write_stock_mins_sensor_calendar_file(lake_root: Path) -> None:
    calendar_path = silver_trade_calendar_path(lake_root)
    calendar_path.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(database=":memory:") as connection:
        connection.execute(
            f"""
            COPY (
              SELECT * FROM (
                VALUES
                  ('SSE', true, DATE '2026-05-29')
              ) AS calendar(exchange, is_open, trade_date)
            ) TO {duckdb_string(calendar_path)} (FORMAT PARQUET)
            """
        )


def _skip_message(result) -> str:
    return getattr(result.skip_reason, "skip_message", str(result.skip_reason))


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


def _write_prod_stk_mins_source_file(
    path: Path,
    *,
    rows_sql: str | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with DuckDBResource().connect() as connection:
        connection.execute(
            copy_query_to_parquet(
                rows_sql
                or """
                SELECT * FROM (
                  SELECT
                    '600000.SH'::VARCHAR AS ts_code,
                    1::INTEGER AS freq,
                    TIMESTAMP '2026-05-29 09:30:00' AS trade_time,
                    10.0::DOUBLE AS open,
                    10.0::DOUBLE AS close,
                    10.1::DOUBLE AS high,
                    9.9::DOUBLE AS low,
                    100::BIGINT AS vol,
                    1234.5::DOUBLE AS amount
                  UNION ALL
                  SELECT
                    '000001.SZ'::VARCHAR AS ts_code,
                    1::INTEGER AS freq,
                    TIMESTAMP '2026-05-29 09:30:00' AS trade_time,
                    20.0::DOUBLE AS open,
                    20.0::DOUBLE AS close,
                    20.1::DOUBLE AS high,
                    19.9::DOUBLE AS low,
                    0::BIGINT AS vol,
                    0.0::DOUBLE AS amount
                  UNION ALL
                  SELECT
                    '920001.BJ'::VARCHAR AS ts_code,
                    1::INTEGER AS freq,
                    TIMESTAMP '2026-05-29 09:30:00' AS trade_time,
                    30.0::DOUBLE AS open,
                    30.0::DOUBLE AS close,
                    30.1::DOUBLE AS high,
                    29.9::DOUBLE AS low,
                    300::BIGINT AS vol,
                    900.0::DOUBLE AS amount
                )
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

    def test_current_listed_stock_loader_excludes_b_share_currency_rows(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            path = silver_stock_basic_path(root)
            path.parent.mkdir(parents=True, exist_ok=True)
            with DuckDBResource().connect() as connection:
                connection.execute(
                    copy_query_to_parquet(
                        """
                        SELECT * FROM (
                          SELECT
                            '000001.SZ'::VARCHAR AS ts_code,
                            'CNY'::VARCHAR AS curr_type,
                            'L'::VARCHAR AS list_status,
                            DATE '1991-04-03' AS list_date
                          UNION ALL
                          SELECT '200001.SZ', 'HKD', 'L', DATE '1992-01-01'
                          UNION ALL
                          SELECT '900001.SH', 'USD', 'L', DATE '1992-01-01'
                          UNION ALL
                          SELECT '000002.SZ', 'CNY', 'D', DATE '1991-01-29'
                        )
                        """,
                        path,
                    )
                )

            codes = load_current_listed_stock_codes_for_stk_mins(
                lake_root=root,
                duckdb=DuckDBResource(),
                partition_key=PARTITION_KEY,
            )

        self.assertEqual(codes, ("000001.SZ",))
        with self.assertRaisesRegex(ValueError, "Unsupported stk_mins ts_code suffix"):
            derive_stk_mins_exchange_from_ts_code("ABC.NY")

    def test_prod_db_select_uses_field_whitelist(self) -> None:
        validate_prod_stk_mins_select_contract()
        validate_prod_stk_mins_duckdb_source_contract()
        query = build_prod_stk_mins_remote_query(
            stock_codes=("600000.SH", "000001.SZ"),
            freq=1,
            start_datetime="2026-05-29 09:00:00",
            end_datetime="2026-05-29 19:00:00",
        )
        normalized_sql = " ".join(query.lower().split())
        self.assertNotIn("select *", normalized_sql)
        self.assertNotIn("api_name", normalized_sql)
        self.assertNotIn("fetched_at", normalized_sql)
        self.assertNotIn("raw_payload", normalized_sql)
        self.assertIn("ts_code = any(array[", normalized_sql)
        self.assertIn("where freq = 1", normalized_sql)
        self.assertIn("trade_time >=", normalized_sql)

    def test_prod_db_duckdb_source_uses_attached_alias_without_conninfo(self) -> None:
        validate_prod_stk_mins_duckdb_attach_options_contract()
        source_sql = build_prod_stk_mins_duckdb_source_sql(
            stock_codes=("600000.SH", "000001.SZ"),
            freq=1,
            start_datetime="2026-05-29 09:00:00",
            end_datetime="2026-05-29 19:00:00",
        )
        normalized_sql = " ".join(source_sql.lower().split())
        self.assertIn(
            f"postgres_query('{PROD_STK_MINS_DUCKDB_ATTACHED_DATABASE}'",
            normalized_sql,
        )
        for forbidden_text in (
            "host=",
            "user=",
            "password=",
            "fake-secret",
            "dbname=",
            "connect_timeout=",
        ):
            self.assertNotIn(forbidden_text, normalized_sql)

    def test_prod_db_attach_forces_read_only(self) -> None:
        class CapturingConnection:
            def __init__(self):
                self.sqls = []

            def execute(self, sql):
                self.sqls.append(sql)

        connection = CapturingConnection()
        stk_mins._attach_prod_postgres_database(
            connection,
            postgres_connection_string="host=example password=fake-secret",
        )

        self.assertEqual(len(connection.sqls), 1)
        attach_sql = " ".join(connection.sqls[0].lower().replace(",", " ").split())
        expected_options = " ".join(
            PROD_STK_MINS_DUCKDB_ATTACH_OPTIONS.lower().replace(",", " ").split()
        )
        self.assertIn(
            f"as {PROD_STK_MINS_DUCKDB_ATTACHED_DATABASE}",
            attach_sql,
        )
        self.assertIn(expected_options, attach_sql)

    def test_prod_db_attach_error_omits_connection_details(self) -> None:
        class FailingConnection:
            def execute(self, sql):
                raise RuntimeError(
                    "could not connect with host=example password=fake-secret"
                )

        with self.assertRaises(RuntimeError) as raised:
            stk_mins._attach_prod_postgres_database(
                FailingConnection(),
                postgres_connection_string="host=example password=fake-secret",
            )

        message = str(raised.exception)
        self.assertIn("failed to attach prod Postgres", message)
        self.assertNotIn("fake-secret", message)
        self.assertNotIn("password=", message)
        self.assertIsNone(raised.exception.__cause__)

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
            source_path = lake_root / "prod_source.parquet"
            _write_prod_stk_mins_source_file(source_path)
            calls = []

            def fake_source_sql(
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
                return f"SELECT * FROM read_parquet('{source_path.as_posix()}')"

            with patch.object(
                stk_mins,
                "build_prod_stk_mins_duckdb_source_sql",
                fake_source_sql,
            ), patch.object(
                stk_mins,
                "_load_duckdb_postgres_extension",
                lambda connection: None,
            ), patch.object(
                stk_mins,
                "_attach_prod_postgres_database",
                lambda connection, *, postgres_connection_string: None,
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
            self.assertEqual(result.row_count, 3)
            self.assertEqual(result.returned_stock_code_count, 3)
            self.assertEqual(result.empty_stock_code_count, 0)
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
                rows = connection.execute(
                    f"""
                    SELECT freq, vol, amount, exchange, vwap
                    FROM read_parquet('{result.raw_file_path.as_posix()}')
                    ORDER BY ts_code
                    """
                ).fetchall()
            self.assertEqual(
                rows,
                [
                    (1, 0, 0.0, "XSHE", 0.0),
                    (1, 100, 1234.5, "XSHG", 12.345),
                    (1, 300, 900.0, "BSE", 3.0),
                ],
            )

    def test_prod_db_path_rejects_incomplete_code_coverage_without_replacing_target(
        self,
    ) -> None:
        with TemporaryDirectory() as directory:
            lake_root = Path(directory)
            source_path = lake_root / "prod_source.parquet"
            _write_prod_stk_mins_source_file(
                source_path,
                rows_sql="""
                SELECT
                  '600000.SH'::VARCHAR AS ts_code,
                  1::INTEGER AS freq,
                  TIMESTAMP '2026-05-29 09:30:00' AS trade_time,
                  10.0::DOUBLE AS open,
                  10.0::DOUBLE AS close,
                  10.1::DOUBLE AS high,
                  9.9::DOUBLE AS low,
                  100::BIGINT AS vol,
                  1234.5::DOUBLE AS amount
                """,
            )
            target_path = raw_stk_mins_path(lake_root, 1, PARTITION_KEY)
            _write_raw_stk_mins_file(target_path, open_value=7.0)

            with patch.object(
                stk_mins,
                "build_prod_stk_mins_duckdb_source_sql",
                lambda **_kwargs: f"SELECT * FROM read_parquet('{source_path.as_posix()}')",
            ), self.assertRaisesRegex(RuntimeError, "source coverage is incomplete"):
                stk_mins._write_raw_stk_mins_rows_from_prod_db_source(
                    duckdb=DuckDBResource(),
                    source_sql=f"SELECT * FROM read_parquet('{source_path.as_posix()}')",
                    target_path=target_path,
                    freq=1,
                    partition_key=PARTITION_KEY,
                    stock_codes=("000001.SZ", "600000.SH"),
                    load_postgres_extension=False,
                )

            self.assertFalse(target_path.with_name("part-000.parquet.tmp").exists())
            with DuckDBResource().connect() as connection:
                open_value = connection.execute(
                    f"SELECT open FROM read_parquet('{target_path.as_posix()}')"
                ).fetchone()[0]
            self.assertEqual(open_value, 7.0)

    def test_prod_db_path_does_not_use_python_row_fetch_or_executemany(self) -> None:
        source = Path(stk_mins.__file__).read_text()
        self.assertNotIn("fetch_prod_stk_mins_rows_for_stock_codes", source)
        self.assertNotIn("_normalize_prod_db_stk_mins_row", source)
        prod_section = source[
            source.index("def write_raw_stk_mins_partition_from_prod_db")
            : source.index("def merge_repair_raw_stk_mins_partition_from_tushare")
        ]
        self.assertNotIn("executemany", prod_section)
        self.assertIn("build_prod_stk_mins_duckdb_source_sql", prod_section)

    def test_prod_db_batch_fetch_rejects_rows_outside_stock_pool(self) -> None:
        with TemporaryDirectory() as directory:
            lake_root = Path(directory)
            source_path = lake_root / "prod_source.parquet"
            _write_prod_stk_mins_source_file(
                source_path,
                rows_sql="""
                SELECT
                  '300001.SZ'::VARCHAR AS ts_code,
                  1::INTEGER AS freq,
                  TIMESTAMP '2026-05-29 09:30:00' AS trade_time,
                  10.0::DOUBLE AS open,
                  10.0::DOUBLE AS close,
                  10.1::DOUBLE AS high,
                  9.9::DOUBLE AS low,
                  100::BIGINT AS vol,
                  1234.5::DOUBLE AS amount
                """,
            )

            def fake_source_sql(
                *,
                stock_codes,
                freq,
                start_datetime,
                end_datetime,
            ):
                return f"SELECT * FROM read_parquet('{source_path.as_posix()}')"

            with patch.object(
                stk_mins,
                "build_prod_stk_mins_duckdb_source_sql",
                fake_source_sql,
            ), patch.object(
                stk_mins,
                "_load_duckdb_postgres_extension",
                lambda connection: None,
            ), patch.object(
                stk_mins,
                "_attach_prod_postgres_database",
                lambda connection, *, postgres_connection_string: None,
            ):
                with self.assertRaisesRegex(RuntimeError, "outside the requested"):
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

    def test_stock_mins_prod_job_run_config_requires_completion_reference(self) -> None:
        completion_reference = _prod_completion_reference()
        run_config = build_stock_mins_raw_update_job_run_config(
            source="prod_db",
            prod_completion_reference=completion_reference,
        )
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
                        "prod_completion_reference": completion_reference.to_config_dict(),
                    }
                },
            )
        self.assertIsNone(stock_mins_raw_update_from_prod_job.config)

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
        with self.assertRaisesRegex(ValueError, "requires prod_completion_reference"):
            parse_stock_mins_raw_config({})
        parsed_prod = parse_stock_mins_raw_config(
            {
                "source": "prod_db",
                "write_mode": {"reuse_existing": {}},
                "prod_completion_reference": _prod_completion_reference().to_config_dict(),
            }
        )
        self.assertEqual(parsed_prod.source, "prod_db")
        self.assertEqual(
            parsed_prod.prod_completion_reference,
            _prod_completion_reference(),
        )
        self.assertEqual(
            parse_stock_mins_raw_config(
                {
                    "source": "tushare",
                    "write_mode": {
                        "reuse_existing": {},
                    },
                }
            ).source,
            "tushare",
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

    def test_stock_mins_silver_trade_day_decision_requires_all_gates(self) -> None:
        selected = build_stock_mins_silver_trade_day_registration_decision(
            target_trade_date="2026-05-29",
            register_window_started=True,
            already_registered=False,
            raw_ready=True,
            stock_daily_ready=True,
            suspend_ready=True,
            identity_map_ready=True,
        )
        before_window = build_stock_mins_silver_trade_day_registration_decision(
            target_trade_date="2026-05-29",
            register_window_started=False,
            already_registered=False,
            raw_ready=True,
            stock_daily_ready=True,
            suspend_ready=True,
            identity_map_ready=True,
        )
        raw_blocked = build_stock_mins_silver_trade_day_registration_decision(
            target_trade_date="2026-05-29",
            register_window_started=True,
            already_registered=False,
            raw_ready=False,
            stock_daily_ready=True,
            suspend_ready=True,
            identity_map_ready=True,
        )

        self.assertEqual(selected.selected_keys, ("2026-05-29",))
        self.assertEqual(before_window.selected_keys, ())
        self.assertIn("19:45", before_window.reason)
        self.assertEqual(raw_blocked.selected_keys, ())
        self.assertIn("raw 五频度", raw_blocked.reason)

    def test_stock_mins_raw_sensor_submits_when_raw_missing_and_stock_basic_fresh(
        self,
    ) -> None:
        context = _StockMinsRawSensorContext()
        raw_status = _raw_stk_mins_lake_status(ready=False)
        stock_basic_status = _stock_basic_sensor_status(ready=True)
        with patch(
            "orchestrator.defs.sensors.stock_mins_raw_sensor.datetime",
            _AfterRawWindowDateTime,
        ), patch(
            "orchestrator.defs.sensors.stock_mins_raw_sensor.batch_raw_stk_mins_lake_readiness",
            return_value=_raw_stk_mins_batch_status(raw_status),
        ) as raw_batch_mock, patch(
            "orchestrator.defs.sensors.stock_mins_raw_sensor.stock_basic_ready_for_trade_date",
            return_value=stock_basic_status,
        ) as stock_basic_ready_mock, patch(
            "orchestrator.defs.sensors.stock_mins_raw_sensor.load_current_listed_stock_codes_for_stk_mins",
            return_value=("600000.SH",),
        ) as stock_codes_mock, patch(
            "orchestrator.defs.sensors.stock_mins_raw_sensor.stk_mins_prod_source_ready_for_trade_date",
            return_value=_prod_source_readiness(),
        ) as prod_source_ready_mock:
            result = _stock_mins_raw_sensor_result(context)

        self.assertEqual(len(result.run_requests), 1)
        request = result.run_requests[0]
        self.assertEqual(request.partition_key, PARTITION_KEY)
        self.assertEqual(
            request.run_key,
            f"stock_mins_raw_update_from_prod:{PARTITION_KEY}",
        )
        raw_batch_mock.assert_called_once()
        stock_basic_ready_mock.assert_called_once_with(context.instance, PARTITION_KEY)
        stock_codes_mock.assert_called_once()
        prod_source_ready_mock.assert_called_once()
        self.assertFalse(hasattr(stock_mins_raw_sensor_module, "stock_basic_ready_without_freshness"))
        expected_config = build_stock_mins_raw_update_job_run_config(
            source="prod_db",
            prod_completion_reference=_prod_completion_reference(),
        )
        self.assertEqual(request.run_config, expected_config)

    def test_stock_mins_raw_sensor_does_not_read_prod_before_1930(self) -> None:
        context = _StockMinsRawSensorContext()
        raw_status = _raw_stk_mins_lake_status(ready=False)
        with patch(
            "orchestrator.defs.sensors.stock_mins_raw_sensor.datetime",
            _BeforeRawWindowDateTime,
        ), patch(
            "orchestrator.defs.sensors.stock_mins_raw_sensor.batch_raw_stk_mins_lake_readiness",
            return_value=_raw_stk_mins_batch_status(raw_status),
        ), patch(
            "orchestrator.defs.sensors.stock_mins_raw_sensor.load_current_listed_stock_codes_for_stk_mins",
            side_effect=AssertionError("sensor must not read the stock universe before 19:30"),
        ), patch(
            "orchestrator.defs.sensors.stock_mins_raw_sensor.stk_mins_prod_source_ready_for_trade_date",
            side_effect=AssertionError("sensor must not read prod before 19:30"),
        ):
            result = _stock_mins_raw_sensor_result(context)

        self.assertEqual(result.run_requests, [])
        self.assertIn("19:30", _skip_message(result))
        cursor = json.loads(result.cursor)
        self.assertEqual(cursor["details"]["reason_code"], "run_window_not_started")
        self.assertLess(len(result.cursor), 3072)

    def test_stock_mins_raw_sensor_does_not_auto_recover_after_midnight(self) -> None:
        context = _StockMinsRawSensorContext()
        raw_status = _raw_stk_mins_lake_status(ready=False)
        with patch(
            "orchestrator.defs.sensors.stock_mins_raw_sensor.datetime",
            _AfterMidnightDateTime,
        ), patch(
            "orchestrator.defs.sensors.stock_mins_raw_sensor.batch_raw_stk_mins_lake_readiness",
            return_value=_raw_stk_mins_batch_status(raw_status),
        ), patch(
            "orchestrator.defs.sensors.stock_mins_raw_sensor.load_current_listed_stock_codes_for_stk_mins",
            side_effect=AssertionError("historical recovery must not load a source universe"),
        ), patch(
            "orchestrator.defs.sensors.stock_mins_raw_sensor.stk_mins_prod_source_ready_for_trade_date",
            side_effect=AssertionError("historical recovery must not query prod"),
        ):
            result = _stock_mins_raw_sensor_result(context)

        self.assertEqual(result.run_requests, [])
        self.assertIn("受控历史 recovery", _skip_message(result))
        cursor = json.loads(result.cursor)
        self.assertEqual(
            cursor["details"]["reason_code"],
            "historical_raw_recovery_required",
        )
        self.assertEqual(
            cursor["details"]["blocked_component"],
            "historical_raw_recovery",
        )

    def test_stock_mins_raw_sensor_skips_when_stock_basic_not_fresh(self) -> None:
        context = _StockMinsRawSensorContext()
        raw_status = _raw_stk_mins_lake_status(ready=False)
        stock_basic_status = _stock_basic_sensor_status(
            ready=False,
            freshness_passed=False,
            reason=(
                "silver_stock_basic materialized at 2026-05-28, "
                "before required date 2026-05-29"
            ),
        )
        with patch(
            "orchestrator.defs.sensors.stock_mins_raw_sensor.datetime",
            _AfterRawWindowDateTime,
        ), patch(
            "orchestrator.defs.sensors.stock_mins_raw_sensor.batch_raw_stk_mins_lake_readiness",
            return_value=_raw_stk_mins_batch_status(raw_status),
        ), patch(
            "orchestrator.defs.sensors.stock_mins_raw_sensor.stock_basic_ready_for_trade_date",
            return_value=stock_basic_status,
        ) as stock_basic_ready_mock:
            result = _stock_mins_raw_sensor_result(context)

        self.assertEqual(result.run_requests, [])
        self.assertIn("freshness", _skip_message(result))
        self.assertIn("blocking checks", _skip_message(result))
        stock_basic_ready_mock.assert_called_once_with(context.instance, PARTITION_KEY)

        cursor = json.loads(result.cursor)
        self.assertEqual(cursor["decision"], "skip")
        self.assertEqual(cursor["target_date"], PARTITION_KEY)
        self.assertTrue(
            cursor["details"]["evidence"]["stock_basic_freshness_required"]
        )
        self.assertFalse(cursor["details"]["gate_statuses"]["stock_basic"]["ready"])
        self.assertEqual(cursor["details"]["blocked_component"], "stock_basic")
        self.assertIn("未触发", cursor["details"]["summary"])
        self.assertIn("stock_basic", cursor["details"]["next_action"])
        self.assertLess(len(result.cursor), 3072)

    def test_stock_mins_sensor_cursors_and_run_request_contract(self) -> None:
        silver_decision = build_stock_mins_silver_trade_day_registration_decision(
            target_trade_date="2026-05-29",
            register_window_started=True,
            already_registered=False,
            raw_ready=True,
            stock_daily_ready=True,
            suspend_ready=True,
            identity_map_ready=True,
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
            silver_cursor["details"]["evidence"]["raw_partition_set"],
            "cn_a_stock_mins_trade_days",
        )
        self.assertEqual(
            silver_cursor["details"]["partition_set"],
            "cn_a_stock_mins_silver_trade_days",
        )

        raw_cursor_text = build_stock_mins_raw_sensor_cursor(
            evaluated_at=EVALUATED_AT,
            registered_trade_day_count=1,
            target_trade_date="2026-05-29",
            selected_trade_date="2026-05-29",
            reason="ready",
            source_window_started=True,
        )
        raw_cursor = json.loads(raw_cursor_text)
        self.assertEqual(raw_cursor["decision"], "request_runs")
        self.assertEqual(raw_cursor["target_date"], "2026-05-29")
        self.assertEqual(raw_cursor["selected_count"], 1)
        self.assertEqual(raw_cursor["details"]["evidence"]["source"], "prod_db")
        self.assertLess(len(raw_cursor_text), 2048)
        self.assertIn("已触发", raw_cursor["details"]["summary"])
        self.assertIn("raw_stk_mins checks", raw_cursor["details"]["next_action"])
        self.assertEqual(
            raw_cursor["details"]["job_name"],
            "stock_mins_raw_update_from_prod_job",
        )
        self.assertTrue(
            raw_cursor["details"]["evidence"]["stock_basic_freshness_required"]
        )
        forbidden_cursor_fragments = (
            "status_samples",
            "to_cursor_details",
            "readiness_details",
            "repair_details",
            "sample_rows",
        )
        for fragment in forbidden_cursor_fragments:
            self.assertNotIn(fragment, raw_cursor_text)

        completion_reference = _prod_completion_reference()
        request = _run_request_for_trade_date(
            "2026-05-29",
            prod_completion_reference=completion_reference,
        )
        self.assertEqual(request.partition_key, "2026-05-29")
        self.assertEqual(
            request.run_key,
            "stock_mins_raw_update_from_prod:2026-05-29",
        )
        self.assertEqual(request.tags, {})
        self.assertEqual(
            request.run_config,
            build_stock_mins_raw_update_job_run_config(
                source="prod_db",
                prod_completion_reference=completion_reference,
            ),
        )
        self.assertEqual(
            STOCK_MINS_RAW_SENSOR_JOB_NAME,
            "stock_mins_raw_update_from_prod_job",
        )
        self.assertEqual(STOCK_MINS_RAW_RUN_START.isoformat(), "19:30:00")
        self.assertEqual(STOCK_MINS_RAW_SOURCE, "prod_db")
        self.assertEqual(
            STOCK_MINS_SILVER_TRADE_DAY_REGISTER_START.isoformat(),
            "19:45:00",
        )

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
